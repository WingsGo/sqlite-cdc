<!--
SYNC IMPACT REPORT
==================
Previous Version: 1.0.0
New Version: 1.1.0
Change Type: MINOR (New principle added as Principle I, existing principles renumbered)

Modifications:
- Added new Principle I: 使用中文 (Use Chinese)
- Renumbered existing principles: I→II, II→III, III→IV, IV→V, V→VI

Modified Principles:
- I. 数据一致性与可靠性 → II. 数据一致性与可靠性
- II. 事件驱动架构 → III. 事件驱动架构
- III. 测试优先开发 → IV. 测试优先开发
- IV. 简单性与极简主义 → V. 简单性与极简主义
- V. 可观测性与可调试性 → VI. 可观测性与可调试性

Added Principles:
- I. 使用中文 (Use Chinese) (NEW - moved to top priority)

Added Sections:
- None

Removed Sections:
- None

Templates Requiring Updates:
✅ plan-template.md - Constitution Check section aligned
✅ spec-template.md - No changes required
✅ tasks-template.md - No changes required
✅ checklist-template.md - No changes required

TODO Items:
- None
-->

# SQLite CDC Specify 项目宪法

## 核心原则

### I. 使用中文 (NON-NEGOTIABLE / 不可协商)

所有项目文档、代码注释、提交信息、PR 描述、Issue 讨论必须使用中文。变量名和函数名优先使用英文，但必须以中文编写文档字符串（docstring）说明其用途。API 文档、README、架构设计文档必须使用中文撰写。团队沟通以中文为唯一工作语言。

**设计原理**: 语言是思维的载体。使用母语进行技术沟通可以降低认知负担，提高表达精度，确保复杂概念被准确传达。对于 SQLite CDC 这类数据基础设施项目，精确沟通是避免误解和错误的关键。此原则优先于其他所有原则。

### II. 数据一致性与可靠性 (NON-NEGOTIABLE / 不可协商)

所有 CDC 操作必须保证 exactly-once 交付语义。系统必须以原子方式处理 SQLite WAL (Write-Ahead Log) 变更，并确保所有消费者的幂等性。每个捕获的变更在传播前必须进行数据完整性检查。

**设计原理**: CDC 系统是数据同步的基石。任何数据丢失、重复或损坏都会级联传播到下游，且几乎无法恢复。此原则是绝对且不可协商的。

### III. 事件驱动架构

系统必须将所有数据变更暴露为离散的、定义明确的事件。事件必须遵循标准化模式，包含以下必需字段：event_type、table_name、row_id、timestamp 和 payload。架构必须使用消息队列或流将生产者（SQLite 变更检测）与消费者解耦。

**设计原理**: 事件驱动架构实现了松耦合、水平扩展和多个独立消费者。它使系统能够演进而不破坏下游集成，并支持用于恢复场景的重放能力。

### IV. 测试优先开发 (NON-NEGOTIABLE / 不可协商)

所有功能必须从失败的测试开始。没有定义预期行为的相应测试，就不编写实现代码。CDC 契约测试必须验证：WAL 变更检测、事件序列化、消费者交付保证以及故障恢复场景。

**设计原理**: CDC 系统是任务关键型基础设施，在生产环境中发现错误的成本极高。测试优先确保规范清晰，并为重构提供信心。"红-绿-重构"循环必须严格执行。

### V. 简单性与极简主义

每个组件都必须证明其存在的必要性。优先选择直接解决方案而非抽象。代码库必须避免过早的泛化。如果一个特性不服务于具体的、有文档记录的用例，则应被排除（YAGNI - You Aren't Gonna Need It）。

**设计原理**: 简单性减少了错误、认知负担和维护负担。CDC 系统持续运行；更简单的代码具有更少的故障模式，并且在凌晨 3 点调试时更容易排查。抵制过度工程的冲动。

### VI. 可观测性与可调试性

所有操作必须在适当的详细级别产生结构化日志。CDC 延迟必须持续监控和报告。失败的事件必须捕获到死信队列中，并包含完整的调试上下文。健康检查端点必须暴露系统状态。

**设计原理**: 生产环境中的 CDC 故障通常是竞态条件或边界情况，需要快速诊断。可观测性支持主动告警和取证。没有变更传播延迟和错误率的可见性，是不可能获得操作信心的。

## 技术约束

以下约束规范技术和实现选择：

- **语言**: Python 3.11+ 优先（生态系统兼容性）；Rust 可用于性能关键组件
- **协议**: SQLite WAL 模式是必需的（变更检测依赖于此）
- **事件格式**: JSON 配合严格的模式验证；高吞吐量场景可选 AVRO
- **持久化**: SQLite 用于元数据；PostgreSQL 或 Redis 用于偏移量追踪
- **依赖**: 最小化外部依赖；每个依赖必须被积极维护

## 开发工作流

### 代码审查要求

- 所有 PR 需要至少一次审查，审查意见必须使用中文
- CDC 契约变更需要项目维护者的明确批准
- 性能敏感的代码路径需要基准测试

### 测试门禁

- 单元测试必须通过（pytest，覆盖率 >80%）
- 集成测试必须通过（SQLite WAL → Event → Consumer 流程）
- 契约测试必须通过（模式验证、序列化往返）
- 主分支中不允许存在不稳定测试（flakey tests）

### 部署审批

- CDC 版本升级需要 CHANGELOG 更新
- 事件模式的破坏性变更需要迁移计划
- 生产部署需要运维手册验证

## 治理

本宪法优于所有其他开发实践。此文档与其他指南之间的任何冲突均以此宪法为准解决。

### 修订程序

1. 在 PR 中以中文记录拟议的变更及其原理
2. 证明该修订如何提高对 CDC 可靠性标准的遵守程度
3. 更新相关模板（spec-template、plan-template、tasks-template）
4. 根据语义化版本规则递增版本号
5. 需要项目维护者批准

### 版本控制策略

- **MAJOR**: 不兼容的治理变更，或原则移除/重定义
- **MINOR**: 新增原则、章节或实质性扩展的指南
- **PATCH**: 澄清说明、措辞改进、拼写错误修复

### 合规性审查

通过以下方式验证对本宪法的遵守：
- CI/CD 管道中的自动化检查
- PR 模板中的强制性审查清单
- 每季度对累积异常的手动审查

---

**版本**: 1.1.0 | **批准日期**: 2026-02-07 | **最后修订**: 2026-02-07
