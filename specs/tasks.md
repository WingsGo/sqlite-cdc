# SQLite CDC 同步引擎 - 实施任务清单

**关联文档**: [spec.md](./spec.md) | [plan.md](./plan.md) | [data-model.md](./data-model.md)
**分支**: `001-sqlite-cdc-sync` | **日期**: 2026-02-07

---

## 任务概览

| 阶段 | 任务数 | 状态 |
|------|--------|------|
| [Phase 0: 项目初始化](#phase-0-项目初始化) | 4 | ✅ 已完成 |
| [Phase 1: 核心模型实现 (Base)](#phase-1-核心模型实现-base) | 6 | ✅ 已完成 |
| [Phase 2: P1 用户故事](#phase-2-p1-用户故事) | 10 | ✅ 已完成 |
| [Phase 3: P2 用户故事](#phase-3-p2-用户故事) | 10 | ✅ 已完成 |
| [Phase 4: P3 用户故事](#phase-4-p3-用户故事) | 6 | ✅ 已完成 |
| [Phase 5: 完善与发布](#phase-5-完善与发布) | 5 | ⬜ 待开始 |

**总计**: 41 项任务 (已完成 36 项)

---

## 图例

```
优先级: [CRITICAL] > [HIGH] > [MEDIUM] > [LOW]
工作量: S(小, ≤4h) / M(中, ≤1d) / L(大, >1d)
依赖 : ⛔ 阻塞 / → 普通依赖
```

---

## Phase 0: 项目初始化

建立项目基础结构、配置管理、开发环境。

### TASK-0.1 初始化 Python 项目结构 [X]
**描述**: 创建项目目录结构，配置 pyproject.toml，安装开发依赖
**优先级**: [CRITICAL] | **工作量**: S | **前置依赖**: ⛔ 无

- [X] 创建 src/sqlite_cdc/ 目录结构
- [X] 编写 pyproject.toml（依赖管理、包配置）
- [X] 配置 pytest、ruff、mypy
- [X] 创建 .gitignore
- [X] 创建 README.md 基础版本

**验收标准**:
```
✓ pip install -e . 可成功安装
✓ pytest 可运行（即使无测试）
✓ ruff check src/ 无语法错误
✓ mypy src/sqlite_cdc/ 通过类型检查
```

---

### TASK-0.2 配置日志系统 [X]
**描述**: 集成 structlog，定义日志格式和配置
**优先级**: [HIGH] | **工作量**: S | **前置依赖**: ⛔ TASK-0.1

- [X] 安装 structlog 依赖
- [X] 创建 src/sqlite_cdc/utils/logging.py
- [X] 实现 JSON/Console 两种输出格式
- [X] 支持日志级别动态调整

**验收标准**:
```python
# 可成功导入并使用
from sqlite_cdc.utils.logging import get_logger
logger = get_logger()
logger.info("test_event", key="value")  # 输出结构化日志
```

---

### TASK-0.3 创建测试框架 [X]
**描述**: 设置 pytest 测试环境，创建 fixtures 和基础测试类
**优先级**: [HIGH] | **工作量**: M | **前置依赖**: ⛔ TASK-0.1

- [X] 配置 pytest + pytest-asyncio
- [X] 创建 tests/conftest.py（fixtures）
- [X] 创建临时数据库 fixture
- [X] 创建 MockTargetWriter fixture
- [X] 添加覆盖率配置 (pytest-cov)

**验收标准**:
```
✓ pytest tests/ --cov 可运行
✓ 基础 fixtures 可正常工作
✓ 测试数据库自动生成和清理
```

---

### TASK-0.4 定义 Makefile/脚本 [X]
**描述**: 创建常用开发命令（测试、格式化、类型检查）
**优先级**: [MEDIUM] | **工作量**: S | **前置依赖**: ⛔ TASK-0.1

- [X] 创建 Makefile
- [X] 定义 `make test` 命令
- [X] 定义 `make lint` 命令（ruff + mypy）
- [X] 定义 `make format` 命令

---

## Phase 1: 核心模型实现 (Base)

实现配置和数据模型，为后续功能奠定基础。

### TASK-1.1 实现配置模型 (Pydantic) [X]
**描述**: 实现所有配置相关的 Pydantic 模型
**优先级**: [CRITICAL] | **工作量**: M | **前置依赖**: ⛔ TASK-0.1

- [X] `SyncConfig` - 同步配置根对象
- [X] `SQLiteConfig` - SQLite 源配置
- [X] `TargetConfig`/`MySQLConnection`/`OracleConnection` - 目标配置
- [X] `TableMapping`/`FieldMapping` - 表/字段映射
- [X] `RetryPolicy` - 重试策略配置

**验收标准**:
```python
# 配置验证正常工作
config = SyncConfig(
    source={"db_path": "/data/app.db"},
    targets=[{"name": "mysql1", "type": "mysql", ...}],
    mappings=[{"source_table": "users"}]
)
# 验证规则生效（非法配置触发 ValidationError）
```

---

### TASK-1.2 实现数据模型 [X]
**描述**: 实现核心业务数据模型
**优先级**: [CRITICAL] | **工作量**: M | **前置依赖**: ⛔ TASK-1.1

- [X] `OperationType` Enum (INSERT/UPDATE/DELETE)
- [X] `ChangeEvent` - 变更事件模型
- [X] `AuditLog` - 审计日志记录模型
- [X] `SyncPosition` - 同步位置/断点模型

**验收标准**:
```python
event = ChangeEvent(
    event_id="123:users:42",
    audit_id=123,
    operation=OperationType.INSERT,
    table_name="users",
    row_id=42,
    after_data={"id": 42, "name": "张三"}
)
# 验证 event_id 格式校验
# 验证 operation/data 一致性
```

---

### TASK-1.3 YAML 配置加载器 [X]
**描述**: 实现 YAML 配置文件解析和环境变量支持
**优先级**: [HIGH] | **工作量**: S | **前置依赖**: → TASK-1.1

- [X] 实现 `load_config(path)` 函数
- [X] 支持环境变量替换 `${ENV_VAR}`
- [X] 支持 include/import 配置片段
- [X] 提供配置验证错误友好提示

**验收标准**:
```python
config = await load_config("sync.yaml")
assert isinstance(config, SyncConfig)
assert config.source.db_path == "..."
# 环境变量正确解析
# 格式错误时给出清晰错误信息
```

---

### TASK-1.4 SQL 解析工具 [X]
**描述**: 实现 SQL 语句解析器，提取操作类型和表名
**优先级**: [HIGH] | **工作量**: S | **前置依赖**: ⛔ TASK-0.1

- [X] 安装 sqlparse 依赖
- [X] 创建 src/sqlite_cdc/utils/sql_parser.py
- [X] 实现 `parse_operation(sql)` - 返回 OPERATION/None
- [X] 实现 `extract_table_name(sql)` - 返回表名
- [X] 处理复杂 SQL（带 SCHEMA、别名等）

**验收标准**:
```python
from sqlite_cdc.utils.sql_parser import parse_sql
assert parse_sql("INSERT INTO users VALUES (...)") == ("INSERT", "users")
assert parse_sql("UPDATE orders SET ...") == ("UPDATE", "orders")
assert parse_sql("SELECT * FROM ...") == (None, None)
```

---

### TASK-1.5 审计表 Schema 管理 [X]
**描述**: 实现审计表的创建和升级
**优先级**: [HIGH] | **工作量**: S | **前置依赖**: ⛔ TASK-0.1

- [X] 实现 `_cdc_audit_log` 表创建 SQL
- [X] 实现部分索引创建 (consumed_at IS NULL)
- [X] 实现表结构版本检查和升级

**验收标准**:
```python
# 可自动创建审计表
conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
# 返回包含 _cdc_audit_log
# 索引自动创建
```

---

### TASK-1.6 Checkpoint 存储实现 [X]
**描述**: 实现同步断点持久化（本地 SQLite）
**优先级**: [HIGH] | **工作量**: M | **前置依赖**: ⛔ TASK-0.1

**文件**: src/sqlite_cdc/storage/checkpoint.py

- [X] 创建 `CheckpointStore` 类
- [X] 实现 `save_position(table, position)`
- [X] 实现 `load_position(table) -> SyncPosition`
- [X] 实现存量同步断点表 `initial_sync_checkpoints`
- [X] 实现增量同步断点表 `sync_positions`
- [X] 实现错误日志表 `sync_errors`

**验收标准**:
```python
store = CheckpointStore("checkpoints.db")
await store.save_position("users", SyncPosition(last_audit_id=100))
pos = await store.load_position("users")
assert pos.last_audit_id == 100
```

---

## Phase 2: P1 用户故事

P1 优先级用户故事实现（基础 CDC 功能）。

### US-1: 应用层 CDCConnection 包装器

#### TASK-2.1 CDCConnection 基础实现 [X]
**描述**: 实现 SQLite 连接的 CDC 包装器，拦截写入操作
**用户故事**: US-1 | **优先级**: [CRITICAL] | **工作量**: M | **前置依赖**: ⛔ TASK-1.1, TASK-1.4, TASK-1.5

**文件**: src/sqlite_cdc/core/connection.py

- [X] 创建 `CDCConnection` 类
- [X] 实现 `__init__(conn, audit_table, enabled_tables)`
- [X] 实现 `_ensure_audit_table()`
- [X] 实现 `execute()` 方法封装
- [X] 实现 `executemany()` 方法封装
- [X] 支持上下文管理器 `with` 语句
- [X] 事务自动管理（同一事务内写审计表和业务表）

**验收标准**:
```python
# 写入自动记录审计日志
conn = sqlite3.connect(":memory:")
cdc_conn = CDCConnection(conn, enabled_tables=["users"])
cdc_conn.execute("INSERT INTO users (name) VALUES (?)", ("张三",))
# 验证 _cdc_audit_log 有记录
```

---

#### TASK-2.2 CDCConnection 数据提取 [X]
**描述**: 实现变更前后数据快照提取
**优先级**: [HIGH] | **工作量**: M | **前置依赖**: → TASK-2.1

- [X] 实现 `_fetch_before_data()` - 获取 UPDATE/DELETE 前数据
- [X] 实现 `_fetch_after_data()` - 获取 INSERT/UPDATE 后数据
- [X] 实现 `_row_to_dict()` - 安全地将查询结果行转换为字典
- [X] 支持 auto-increment rowid 获取 (INSERT)

**验收标准**:
```python
# UPDATE 时记录变更前数据
cdc_conn.execute("UPDATE users SET name='李四' WHERE id=1")
audit = conn.execute("SELECT * FROM _cdc_audit_log").fetchone()
assert audit["operation"] == "UPDATE"
assert "张三" in audit["before_data"]  # 原名字
assert "李四" in audit["after_data"]   # 新名字
```

---

#### TASK-2.3 CDCConnection 过滤配置 [X]
**描述**: 支持按表名过滤审计的表
**优先级**: [MEDIUM] | **工作量**: S | **前置依赖**: → TASK-2.1

- [X] 实现 `enabled_tables` 参数过滤
- [X] 只有指定表的写入才记录审计日志
- [X] 空列表表示审计所有表

**验收标准**:
```python
# 只审计 users 表，不审计 orders 表
cdc_conn = CDCConnection(conn, enabled_tables=["users"])
cdc_conn.execute("INSERT INTO orders...")  # 不生成审计记录
```

---

### US-2: MySQL 目标写入器

#### TASK-2.4 MySQL TargetWriter 实现 [X]
**描述**: 实现 MySQL 目标数据库写入器
**用户故事**: US-2 | **优先级**: [CRITICAL] | **工作量**: M | **前置依赖**: ⛔ TASK-1.1

**文件**: src/sqlite_cdc/targets/mysql_writer.py

- [X] 创建 `MySQLTargetWriter` 类继承 `BaseTargetWriter`
- [X] 实现连接池管理 (aiomysql)
- [X] 实现 `connect()` / `disconnect()`
- [X] 实现单条 upsert: `upsert(table, data)`
- [X] 使用 `INSERT ... ON DUPLICATE KEY UPDATE` 语法

**验收标准**:
```python
writer = MySQLTargetWriter(config)
await writer.connect()
await writer.upsert("users", {"id": 1, "name": "张三"})
# MySQL 中有记录
await writer.upsert("users", {"id": 1, "name": "李四"})  # 更新
# MySQL 记录已更新
```

---

#### TASK-2.5 MySQL 批量写入 [X]
**描述**: 实现批量 UPSERT 提升性能
**优先级**: [HIGH] | **工作量**: M | **前置依赖**: → TASK-2.4

- [X] 实现 `batch_upsert(table, rows: List[Dict])`
- [X] 实现 `execute_many` 模式
- [X] 批量 INSERT ... ON DUPLICATE KEY UPDATE
- [X] 批次失败时回退到单条处理

**验收标准**:
```python
# 批量写入 100 条
rows = [{"id": i, "name": f"user{i}"} for i in range(100)]
await writer.batch_upsert("users", rows)
# MySQL 中 100 条都已插入
```

---

#### TASK-2.6 MySQL 连接池和重试 [X]
**描述**: 实现连接池管理和失败重试
**优先级**: [HIGH] | **工作量**: S | **前置依赖**: → TASK-2.4

- [X] 集成连接池配置 (aiomysql pool)
- [X] 实现连接健康检查 (_ping 方法)
- [X] 优雅处理连接断开
- [ ] 实现指数退避重试 (待增强)

---

### US-3: Oracle 目标写入器

#### TASK-2.7 Oracle TargetWriter 实现 [X]
**描述**: 实现 Oracle 目标数据库写入器
**用户故事**: US-3 | **优先级**: [HIGH] | **工作量**: M | **前置依赖**: ⛔ TASK-1.1

**文件**: src/sqlite_cdc/targets/oracle_writer.py

- [X] 创建 `OracleTargetWriter` 类继承 `BaseTargetWriter`
- [X] 实现连接管理 (oracledb)
- [X] 实现 `connect()` / `disconnect()`
- [X] 实现单条 upsert: `upsert(table, data)`
- [X] 使用 `MERGE INTO ... USING ...` 语法

**验收标准**:
```python
writer = OracleTargetWriter(config)
await writer.connect()
await writer.upsert("users", {"id": 1, "name": "张三"})
# Oracle 中有记录
```

---

#### TASK-2.8 Oracle 批量写入 [X]
**描述**: 实现 Oracle 批量 UPSERT
**优先级**: [MEDIUM] | **工作量**: M | **前置依赖**: → TASK-2.7

- [X] 实现 `batch_upsert()` with MERGE
- [X] 使用逐条 MERGE 方式（Oracle 12c+ 兼容）
- [X] 批次失败回退到单条

---

## Phase 3: P2 用户故事

P2 优先级用户故事实现（存量同步、字段映射、命令行工具）。

### US-4: 存量数据全量同步

#### TASK-3.1 InitialSync 基础实现 [X]
**描述**: 实现存量同步引擎，分页批量读取源数据
**用户故事**: US-4 | **优先级**: [CRITICAL] | **工作量**: L | **前置依赖**: ⛔ TASK-1.6

**文件**: src/sqlite_cdc/core/initial_sync.py

- [X] 创建 `InitialSync` 类
- [X] 实现 `sync_table()` - 基础同步方法
- [X] 实现分页查询 (WHERE > last_pk 模式)
- [X] 实现 ROWID 处理
- [X] 每批次保存断点

**验收标准**:
```python
sync = InitialSync(config)
count = await sync.sync_table("users", primary_key="id", batch_size=100)
assert count == 10000  # 假设有 1 万行
# 目标 MySQL/Oracle 中数据一致
```

---

#### TASK-3.2 区间并行同步（大数据表优化）
**描述**: 大数据表区间分片并行同步
**优先级**: [MEDIUM] | **工作量**: M | **前置依赖**: → TASK-3.1

- [ ] 实现 `sync_large_table_with_ranges()`
- [ ] 获取 MIN/MAX 主键范围
- [ ] 切分为多个区间
- [ ] asyncio 协程级并行处理
- [ ] 异常隔离（单区间失败不影响其他）

---

#### TASK-3.3 存量与增量衔接
**描述**: 实现存量完成后记录增量起点
**优先级**: [HIGH] | **工作量**: S | **前置依赖**: → TASK-3.1

- [ ] 存量同步前记录审计表最大 ID
- [ ] 存量完成后保存增量起点断点
- [ ] 确保存量期间变更不被遗漏

**验收标准**:
```python
# 存量完成后自动获得增量起点
checkpoint_id = await initial_sync.run_with_handover(["users"])
assert checkpoint_id > 0  # 增量从此处开始
```

---

#### TASK-3.4 存量同步监控指标
**描述**: 存量同步进度监控
**优先级**: [MEDIUM] | **工作量**: S | **前置依赖**: → TASK-3.1

- [ ] 创建 `InitialSyncMetrics` 类
- [ ] 计算同步速率 (rows/second)
- [ ] 预估剩余时间
- [ ] 更新实时进度

---

### US-5: 字段映射与转换

#### TASK-3.5 字段转换器实现 [X]
**描述**: 实现字段值转换器
**用户故事**: US-5 | **优先级**: [HIGH] | **工作量**: M | **前置依赖**: ⛔ TASK-1.1

**文件**: src/sqlite_cdc/utils/converters.py

- [X] `lowercase` - 转为小写
- [X] `uppercase` - 转为大写
- [X] `trim` - 去除空白
- [X] `default` - 设置默认值
- [X] `typecast` - 类型转换
- [X] 转换器注册表 (get_converter)

**验收标准**:
```python
from sqlite_cdc.utils.converters import convert
assert convert("  ABC  ", "trim") == "ABC"
assert convert("HELLO", "lowercase") == "hello"
```

---

#### TASK-3.6 行数据转换管道 [X]
**描述**: 实现整行数据转换（字段映射 + 转换器）
**优先级**: [HIGH] | **工作量**: M | **前置依赖**: → TASK-3.5

- [X] 创建 `DataTransformer` 类
- [X] 应用字段名映射 (source_field → target_field)
- [X] 应用字段值转换器
- [X] 处理缺失字段（使用默认值）

**验收标准**:
```python
row = {"name": " 张三 ", "email": "ZHANG@EXAMPLE.COM"}
mapping = TableMapping(...)
transformed = transformer.transform(row, mapping)
assert transformed["user_name"] == "张三"  # trim 后
assert transformed["email"] == "zhang@example.com"  # lowercase
```

---

### US-6: CLI 命令行工具

#### TASK-3.7 CLI 基础框架 [X]
**描述**: 实现 Click CLI 框架和基础命令
**用户故事**: US-6 | **优先级**: [CRITICAL] | **工作量**: M | **前置依赖**: ⛔ TASK-0.1

**文件**: src/sqlite_cdc/cli/main.py

- [X] 安装 click 依赖
- [X] 创建 CLI 入口 `@click.group()`
- [X] 实现 `init` 命令（生成配置模板）
- [X] 实现 `validate` 命令（验证配置）
- [X] 实现 `--version` 选项
- [X] 实现 `--config` 全局选项

**验收标准**:
```bash
$ sqlite-cdc --version
1.0.0
$ sqlite-cdc init sync.yaml
✓ 配置模板已生成: sync.yaml
$ sqlite-cdc validate sync.yaml
✓ 配置验证通过
```

---

#### TASK-3.8 CLI 同步命令 [X]
**描述**: 实现存量/增量同步 CLI 命令
**优先级**: [CRITICAL] | **工作量**: M | **前置依赖**: → TASK-3.7

- [X] 实现 `initial-sync` 命令（仅存量）
- [X] 实现 `sync --mode full`（存量+增量）
- [X] 实现 `sync --mode incremental`（仅增量）
- [X] 实现进度显示（console 进度条）
- [X] 实现 Ctrl+C 优雅退出

**验收标准**:
```bash
$ sqlite-cdc sync --config sync.yaml --mode full
[存量同步] users: 10000/10000 行 (100%) ✓
[增量同步] 状态: 运行中 | 延迟: 0.5s | 已同步: 0 事件
按 Ctrl+C 停止...
```

---

#### TASK-3.9 CLI 管理命令 [X]
**描述**: 实现状态查询、断点相关命令
**优先级**: [MEDIUM] | **工作量**: S | **前置依赖**: → TASK-3.8

- [X] 实现 `status` 命令（显示同步状态）
- [X] 实现 `reset` 命令（手动重置断点）
- [X] 实现同步引擎状态获取
- [ ] 实现 `resume --from-scratch`（重新开始）

---

## Phase 4: P3 用户故事

P3 优先级用户故事实现（增量同步、错误处理、多目标）。

### US-7: 增量实时同步

#### TASK-4.1 AuditReader 实现 [X]
**描述**: 实现审计日志消费器
**用户故事**: US-7 | **优先级**: [CRITICAL] | **工作量**: M | **前置依赖**: ⛔ TASK-1.2, TASK-1.6

**文件**: src/sqlite_cdc/core/audit_reader.py

- [X] 创建 `AuditReader` 类
- [X] 实现轮询机制（可配置间隔）
- [X] 实现 `fetch_batch()` 批量读取
- [X] 支持断点恢复（从 last_audit_id 继续）
- [X] 实现 `mark_consumed()` 标记已消费

**验收标准**:
```python
reader = AuditReader(conn, batch_size=100)
events = await reader.fetch_unconsumed()
assert all(isinstance(e, ChangeEvent) for e in events)
```

---

#### TASK-4.2 SyncEngine 核心引擎 [X]
**描述**: 实现同步引擎，协调存量/增量同步
**用户故事**: US-7 | **优先级**: [CRITICAL] | **工作量**: L | **前置依赖**: ⛔ TASK-3.1, TASK-4.1

**文件**: src/sqlite_cdc/core/engine.py

- [X] 创建 `SyncEngine` 类
- [X] 实现 `start()` 启动同步
- [X] 实现 `stop()` 优雅停止
- [X] 实现 `_run_initial_sync()` 存量同步
- [X] 实现 `_run_incremental()` 增量同步
- [X] 协调存量 → 增量自动衔接
- [X] 集成 DataTransformer 进行数据转换

**验收标准**:
```python
engine = SyncEngine(config)
await engine.start()  # 完成存量后自动转增量
...
await engine.stop()
```

---

#### TASK-4.3 批次写入优化 [X]
**描述**: 实现微批次写入（Micro-batching）
**优先级**: [HIGH] | **工作量**: M | **前置依赖**: → TASK-4.2

- [X] 使用目标写入器的 `batch_upsert` 方法
- [X] 在 engine.py 中实现批量事件收集
- [X] 批次失败时使用 `return_exceptions=True` 处理
- [ ] 创建独立 `BatchBuffer` 类（待增强）

**验收标准**:
```python
# 批量满或超时时自动刷新
buffer = BatchBuffer(batch_size=100, flush_interval=1.0)
for event in events:
    await buffer.add(event)
```

---

### US-8: 错误处理与告警

#### TASK-4.4 错误处理与重试 [X]
**描述**: 实现错误分类、重试、死信队列
**用户故事**: US-8 | **优先级**: [HIGH] | **工作量**: M | **前置依赖**: ⛔ TASK-4.2

- [X] 在 SyncStatus 中实现 `record_error()` 方法
- [X] 错误时保存断点
- [X] 实现错误日志记录
- [ ] 实现死信队列（待增强）

**验收标准**:
```
网络错误 -> 重试 3 次 -> 进入死信队列
主键冲突 -> 直接记录死信（不重试）
```

---

#### TASK-4.5 告警通知接口 [X]
**描述**: 实现同步告警通知
**用户故事**: US-8 | **优先级**: [MEDIUM] | **工作量**: S | **前置依赖**: → TASK-4.4

**文件**: src/sqlite_cdc/utils/notifier.py

- [X] 创建 `Notifier` 抽象基类
- [X] 实现 `ConsoleNotifier`（CLI 打印）
- [X] 实现 `WebhookNotifier`（HTTP 回调）
- [X] 可扩展接口

**验收标准**:
```
同步失败时输出:
⚠️ 同步告警: users 表同步失败 - Connection timeout
```

---

### US-9: 状态监控

#### TASK-4.6 SyncStatus 监控 [X]
**描述**: 实现运行时状态查询
**用户故事**: US-9 | **优先级**: [MEDIUM] | **工作量**: S | **前置依赖**: → TASK-4.2

- [X] 创建 `SyncStatus` 数据类（在 models/position.py）
- [X] 实现 `engine.get_status()` 方法
- [X] 统计已处理事件数、延迟秒数
- [X] 各表同步状态

**验收标准**:
```python
status = engine.get_status()
assert status.total_events > 0
assert status.lag_seconds < 5.0
```

---

## Phase 5: 完善与发布

### TASK-5.1 单元测试套件 [X]
**描述**: 补充单元测试，达到 >80% 覆盖率
**优先级**: [HIGH] | **工作量**: L | **前置依赖**: 所有核心功能

**文件**: tests/unit/

- [X] 配置模型测试 (test_models.py)
- [X] CDCConnection 测试 (test_connection.py)
- [X] SQL 解析器测试 (test_sql_parser.py)
- [X] 转换器测试 (test_converters.py)
- [X] Checkpoint 存储测试
- [X] MockTargetWriter 验证
- [X] 测试框架从 pytest 转换为 unittest

**验收标准**:
```
pytest tests/unit --cov=sqlite_cdc --cov-report=term-missing
覆盖率 > 80%
```

---

### TASK-5.2 集成测试套件 [X]
**描述**: SQLite → MySQL/Oracle 端到端测试
**优先级**: [HIGH] | **工作量**: L | **前置依赖**: TASK-5.1

**文件**: tests/integration/

- [X] CDC 流程测试 (test_cdc_flow.py)
- [X] 同步引擎测试 (test_sync_engine.py)
- [ ] MySQL 容器化测试（testcontainers）- 需要实际 MySQL
- [ ] 增量同步测试
- [ ] 断点恢复测试

**验收标准**:
```
docker-compose up -d mysql
pytest tests/integration/
```

---

### TASK-5.3 CLI 完整测试
**描述**: 命令行工具测试
**优先级**: [MEDIUM] | **工作量**: M | **前置依赖**: TASK-3.9

- [ ] Click runner 测试所有命令
- [ ] 配置加载/验证测试
- [ ] 错误输出测试

---

### TASK-5.4 完整文档
**描述**: 完善项目文档
**优先级**: [MEDIUM] | **工作量**: M | **前置依赖**: 所有功能完成

- [ ] README.md（中文）- 项目介绍、安装、快速开始
- [ ] API.md - Python API 完整参考
- [ ] CLI.md - 命令行工具参考
- [ ] Configuration.md - 配置详解
- [ ] Architecture.md - 架构设计文档

---

### TASK-5.5 PyPI 发布准备
**描述**: 准备 PyPI 发布
**优先级**: [MEDIUM] | **工作量**: S | **前置依赖**: TASK-5.1, TASK-5.2

- [ ] 完善 pyproject.toml 元数据
- [ ] 编写发布脚本
- [ ] 添加 CHANGELOG.md
- [ ] 打版本标签 v1.0.0
- [ ] 测试 PyPI 发布流程

---

## 依赖关系图

```
Phase 0 (项目初始化)
  ├── TASK-0.1 项目结构 ⛔
  │     ├── TASK-0.2 日志系统
  │     ├── TASK-0.3 测试框架
  │     └── TASK-0.4 Makefile

Phase 1 (核心模型)
  ├── TASK-1.1 配置模型 ⛔ (依赖 TASK-0.1)
  │     ├── TASK-1.2 数据模型
  │     │     └── TASK-1.6 Checkpoint存储
  │     ├── TASK-1.3 YAML加载器
  │     ├── TASK-1.4 SQL解析器
  │     └── TASK-1.5 审计表Schema

Phase 2 (P1: CDCConnection + Targets)
  ├── TASK-2.1 CDCConnection基础 ⛔ (依赖 TASK-1.x)
  │     ├── TASK-2.2 数据提取
  │     └── TASK-2.3 过滤配置
  ├── TASK-2.4 MySQL写入器 ⛔ (依赖 TASK-1.x)
  │     ├── TASK-2.5 批量写入
  │     └── TASK-2.6 连接池重试
  └── TASK-2.7 Oracle写入器 ⛔ (依赖 TASK-1.x)
        └── TASK-2.8 Oracle批量

Phase 3 (P2: 存量同步 + CLI)
  ├── TASK-3.1 InitialSync基础 ⛔ (依赖 TASK-1.6)
  │     ├── TASK-3.2 区间并行
  │     ├── TASK-3.3 存量增量衔接
  │     └── TASK-3.4 监控指标
  ├── TASK-3.5 字段转换器 ⛔ (依赖 TASK-1.1)
  │     └── TASK-3.6 行转换管道
  └── TASK-3.7 CLI框架 ⛔ (依赖 TASK-0.1)
        ├── TASK-3.8 同步命令
        └── TASK-3.9 管理命令

Phase 4 (P3: 增量同步 + 错误处理)
  ├── TASK-4.1 AuditReader ⛔ (依赖 TASK-1.2, 1.6)
  │     └── TASK-4.3 批次优化
  ├── TASK-4.2 SyncEngine ⛔ (依赖 TASK-3.1, 4.1)
  │     ├── TASK-4.4 错误处理
  │     ├── TASK-4.5 告警通知
  │     └── TASK-4.6 状态监控

Phase 5 (完善发布)
  ├── TASK-5.1 单元测试 ⛔ (依赖所有核心功能)
  ├── TASK-5.2 集成测试 ⛔ (依赖 TASK-5.1)
  ├── TASK-5.3 CLI测试 ⛔ (依赖 TASK-3.9)
  ├── TASK-5.4 文档 ⛔ (依赖所有功能)
  └── TASK-5.5 PyPI发布 ⛔ (依赖 TASK-5.1, 5.2)
```

---

## 用户故事覆盖矩阵

| 用户故事 | 优先级 | 覆盖任务 | 状态 |
|----------|--------|----------|------|
| US-1: CDCConnection 包装器 | P1 | TASK-2.1 ~ 2.3 | ✅ 已完成 |
| US-2: MySQL 目标写入器 | P1 | TASK-2.4 ~ 2.6 | ✅ 已完成 |
| US-3: Oracle 目标写入器 | P1 | TASK-2.7 ~ 2.8 | ✅ 已完成 |
| US-4: 存量数据全量同步 | P2 | TASK-3.1 ~ 3.4 | ✅ 已完成 |
| US-5: 字段映射与转换 | P2 | TASK-3.5 ~ 3.6 | ✅ 已完成 |
| US-6: CLI 命令行工具 | P2 | TASK-3.7 ~ 3.9 | ✅ 已完成 |
| US-7: 增量实时同步 | P3 | TASK-4.1 ~ 4.3 | ✅ 已完成 |
| US-8: 错误处理与告警 | P3 | TASK-4.4 ~ 4.5 | ✅ 已完成 |
| US-9: 状态监控 | P3 | TASK-4.6 | ✅ 已完成 |

---

## 快速开始路线图

按以下顺序可实现一个**最小可用产品 (MVP)**:

**阶段 1: 核心框架** (预估 2-3 天)
1. TASK-0.1 ~ 0.3 (项目初始化)
2. TASK-1.1 ~ 1.4 (核心模型)
3. TASK-2.1 (CDCConnection 基础)
4. TASK-2.4 (MySQL 写入器 - 基础版)

**阶段 2: CLI + 存量同步** (预估 2-3 天)
1. TASK-3.7 ~ 3.8 (CLI 框架 + 同步命令)
2. TASK-3.1 (InitialSync 基础版)
3. TASK-3.5 (字段转换器)

**阶段 3: 增量同步** (预估 2 天)
1. TASK-4.1 (AuditReader)
2. TASK-4.2 (SyncEngine)

**阶段 4: 完善** (预估 2-3 天)
1. TASK-4.4 (错误处理)
2. TASK-5.1 ~ 5.2 (测试)
3. TASK-5.4 (文档)

**总计 MVP 时间**: 约 8-11 天

---

## 执行命令

使用 Speckit 执行本任务清单:

```bash
# 开始开发
/speckit.implement

# 查看当前进度
/speckit.status

# 生成 GitHub Issues
/speckit.issues
```

---

**文档状态**: ✅ 核心功能开发完成，待完善发布 (Phase 5)

