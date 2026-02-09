# Implementation Plan: SQLite CDC 同步引擎

**Branch**: `001-sqlite-cdc-sync` | **Date**: 2026-02-07 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-sqlite-cdc-sync/spec.md`

## Summary

实现一个 SQLite 到 MySQL/Oracle 的 CDC（变更数据捕获）同步引擎，支持存量数据全量同步和基于审计日志的实时增量同步。系统提供 PyPI 三方库和 CLI 两种使用方式，支持字段名映射配置，保证最终一致性，同步过程异步执行不影响主链路。

技术方案：使用 Python 3.11+ 开发，基于**审计日志表**（`_cdc_audit_log`）捕获变更，通过 SQLAlchemy 适配多目标数据库，采用 asyncio 实现高性能异步处理。

**架构变更**：原 WAL 监听方案因风险过高改为审计日志方案（应用层 CDCConnection 拦截写入）。

## Technical Context

**Language/Version**: Python 3.11+ (宪法规定，asyncio 原生支持更好)
**Primary Dependencies**:
- SQLAlchemy 2.0+ (ORM，支持 MySQL/Oracle 多数据库适配)
- aiosqlite (异步 SQLite 访问)
- aiomysql / oracledb (异步目标库连接)
- pydantic (配置验证)
- structlog (结构化日志)
- click (CLI 框架)
- pytest-asyncio (异步测试)
- sqlparse (SQL 解析，用于 CDCConnection)

**Storage**:
- SQLite (源数据库)
- MySQL / Oracle (目标数据库)
- SQLite (本地 checkpoint/offset 元数据存储)
- `_cdc_audit_log` 表（审计日志，与业务库同库）

**Testing**: pytest + pytest-asyncio，覆盖率目标 >80% (宪法要求)
**Target Platform**: Linux / macOS / Windows，Python 3.11+
**Project Type**: Single project (PyPI 库 + CLI 二合一)
**Performance Goals**:
- 增量同步延迟 < 5 秒 (SC-002)
- 支持 100+ TPS 源库写入
- 对源库性能影响 < 5% (SC-003)

**Constraints**:
- 源数据库表必须有主键或唯一索引 (用于幂等 UPSERT)
- exactly-once 交付语义 (宪法 II 原则)
- 所有文档、注释使用中文 (宪法 I 原则)
- 应用层必须使用 CDCConnection 包装连接（审计日志方案要求）

**Scale/Scope**:
- 单源SQLite → 单/多目标 (MySQL/Oracle)
- 支持百万级存量数据同步
- 持续实时增量同步

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**CDC-Specific Requirements** (from Constitution):

- [x] **Data Consistency**: Design includes exactly-once delivery semantics and idempotency guarantees
  - ✓ 使用审计日志自增 ID + 表名 + 主键作为唯一标识，目标库 UPSERT 保证幂等
- [x] **Event Schema**: All data changes defined with standardized event schema
  - ✓ ChangeEvent 实体包含 event_type, table_name, row_id, timestamp, payload
- [x] **Test Coverage**: Contract tests planned for audit log change detection, event serialization
  - ✓ Phase 0 已研究测试策略，Phase 1 设计契约测试
- [x] **Simplicity Justification**: Each component documented
  - ✓ 单项目结构，核心组件：CDCConnection, AuditReader, SyncEngine, TargetWriter
- [x] **Observability**: Logging strategy defined
  - ✓ structlog 结构化日志，支持日志级别动态调整
- [x] **Technology Alignment**: Language matches project constraints
  - ✓ Python 3.11+ 符合宪法技术约束

**宪法合规状态**: ✅ 通过 - 无需添加 Complexity Tracking

## Project Structure

### Documentation (this feature)

```text
specs/001-sqlite-cdc-sync/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output - 技术调研与方案对比
├── data-model.md        # Phase 1 output - 数据模型设计
├── initial-sync.md      # Phase 1 output - 存量同步详细设计
├── quickstart.md        # Phase 1 output - 快速开始指南
├── contracts/           # Phase 1 output - API 契约
│   └── api.md           # Python API 和 CLI 接口定义
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/
sqlite_cdc/
├── __init__.py          # 包入口，导出 SyncEngine, CDCConnection
├── config.py            # 配置模型 (Pydantic)
├── models/
│   ├── __init__.py
│   ├── sync_config.py   # SyncConfig, TableMapping, FieldMapping
│   ├── position.py      # SyncPosition 断点信息
│   ├── event.py         # ChangeEvent 变更事件
│   └── audit.py         # AuditLog 审计日志模型
├── core/
│   ├── __init__.py
│   ├── engine.py        # SyncEngine 主体
│   ├── connection.py    # CDCConnection 连接包装器（拦截写入）
│   ├── audit_reader.py  # 审计日志轮询/消费
│   ├── change_parser.py # SQL 解析与变更提取
│   ├── initial_sync.py  # 存量同步实现
│   └── target_writer.py # 目标库写入
├── targets/
│   ├── __init__.py
│   ├── base.py          # TargetWriter 抽象基类
│   ├── mysql_writer.py  # MySQL 写入实现
│   └── oracle_writer.py # Oracle 写入实现
├── storage/
│   ├── __init__.py
│   └── checkpoint.py    # 断点持久化 (SQLite)
├── cli/
│   ├── __init__.py
│   └── main.py          # Click CLI 入口
└── utils/
    ├── __init__.py
    ├── logging.py       # structlog 配置
    └── sql_parser.py    # SQL 解析工具

tests/
├── __init__.py
├── unit/                # 单元测试
├── integration/         # 集成测试 (SQLite → MySQL/Oracle)
├── contract/            # 契约测试
└── conftest.py          # pytest fixtures

docs/
├── README.md            # 中文文档
└── API.md               # API 参考

pyproject.toml           # 包配置、依赖
sync.yaml.example        # 配置示例
```

**Structure Decision**: 采用单一项目结构，所有代码放在 `src/sqlite_cdc/` 目录下，同时支持库导入和 CLI 命令。这种设计符合宪法 V 原则（简单性），没有不必要的项目拆分。

## Phase 0: Research & Technology Decisions

### Research Topics

1. **变更捕获方案（已确定为审计日志方案）**
   - ~~选项 A: WAL 文件直接解析~~（已排除，风险过高）
   - ~~选项 B: sqlite3_update_hook~~（已排除，功能限制）
   - **选项 C: 审计日志表** ✅ **已采用**
     - CDCConnection 连接包装器设计
     - 审计表结构优化（部分索引、清理策略）
     - SQL 解析与拦截实现

2. **目标数据库兼容性**
   - MySQL: INSERT ... ON DUPLICATE KEY UPDATE vs REPLACE
   - Oracle: MERGE 语句语法差异
   - 批量写入优化策略

3. **异步架构选型**
   - asyncio 事件循环管理
   - 背压处理 (backpressure) 策略
   - 优雅关闭机制

4. **exactly-once 实现**
   - 幂等键设计：审计表自增 ID + UPSERT
   - 断点持久化策略
   - 故障恢复流程

5. **存量同步方案**（详见 initial-sync.md）
   - 分页查询（WHERE > last_pk）
   - 区间并行（大数据表优化）
   - 无主键表处理（ROWID）

### 架构变更说明

**重大变更**：从 WAL 监听方案改为**审计日志方案**

| 对比项 | WAL 监听（原方案） | 审计日志（新方案） |
|--------|-------------------|-------------------|
| 侵入性 | 无侵入 | 应用层需要改用 CDCConnection |
| 可靠性 | 低（格式复杂） | 高（事务保证） |
| 实现难度 | 高（逆向工程） | 中（SQL 拦截） |
| 性能影响 | 低（只读 WAL） | 极低（同一事务写入） |

### Research Output

详见 [research.md](./research.md) 和 [initial-sync.md](./initial-sync.md)

## Phase 1: Design & Contracts

### Design Artifacts

1. **[data-model.md](./data-model.md)**: 实体关系、字段定义、验证规则
   - SyncConfig, CDCConnection, AuditLog, ChangeEvent, SyncPosition
   - 审计表 Schema、元数据表 Schema

2. **[initial-sync.md](./initial-sync.md)**: 存量同步详细设计
   - 分页/区间同步策略
   - 断点恢复机制
   - 性能优化方案

3. **[contracts/api.md](./contracts/api.md)**: API 契约
   - Python 库 API（SyncEngine, SyncStatus, 异常类）
   - CLI 接口（start, stop, status, init, validate, checkpoint, resume）

4. **[quickstart.md](./quickstart.md)**: 快速开始指南

### Design Principles

- 使用 Pydantic v2 进行配置验证
- SQLAlchemy 2.0 Style (type-annotated)
- 所有公共 API 必须有中文文档字符串
- 审计日志与业务数据同一事务，保证原子性
- 批量 UPSERT 保证幂等性

## Phase 2: 待生成的任务

由 `/speckit.tasks` 命令生成，包括：
- 核心组件实现（CDCConnection, AuditReader, SyncEngine）
- 目标库写入器（MySQLWriter, OracleWriter）
- 存量同步实现（InitialSync）
- CLI 命令实现
- 测试套件（单元测试、集成测试、契约测试）
- 文档完善

---

**文档状态**: ✅ Phase 0 和 Phase 1 完成，等待 `/speckit.tasks` 生成实现任务
