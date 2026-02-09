# Research: SQLite CDC 同步引擎技术调研

**日期**: 2026-02-07
**目的**: 为 SQLite CDC 项目确定关键技术决策

---

## 1. 审计日志方案（已采用的最终方案）

### 问题分析

CDC 的核心是实时捕获数据库变更。经过评估，WAL 文件直接解析风险过高，决定采用**审计日志（Audit Log）**方案：

1. **应用层拦截**: 包装 SQLite 连接，拦截 INSERT/UPDATE/DELETE 操作
2. **原子写入**: 在同一事务中，先写入审计表，再写入业务表
3. **异步消费**: 后台线程轮询审计表，批量消费并同步到目标库

### 方案对比

| 方案 | 实现方式 | 优点 | 缺点 | 决策 |
|------|----------|------|------|------|
| A. WAL 文件监听 | 直接解析 WAL 二进制文件 | 无侵入，真正实时 | 格式复杂，逆向工程工作量大，风险高 | ❌ 放弃 |
| B. 审计日志表 | 应用层拦截写入审计表 | 实现简单可靠，数据完整，可控 | 轻微侵入性（需使用包装连接） | ✅ 采用 |
| C. 触发器方案 | 数据库触发器写审计表 | 对应用透明 | 需要创建触发器，DDL侵入，无法捕获应用上下文 | ❌ 放弃 |

### 最终决策

**方案 B: 审计日志表（应用层拦截）**

#### Decision
使用 `CDCConnection` 包装器拦截 SQLite 操作，自动将变更写入 `_cdc_audit_log` 审计表。

```python
class CDCConnection:
    """
    CDC 包装的 SQLite 连接

    拦截 execute 操作，将 INSERT/UPDATE/DELETE 记录到审计表
    """
    def __init__(self, conn: sqlite3.Connection, audit_table: str = "_cdc_audit_log"):
        self._conn = conn
        self._audit_table = audit_table
        self._ensure_audit_table()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        operation = self._parse_operation(sql)

        if operation in ("INSERT", "UPDATE", "DELETE"):
            # 同一事务内：先写审计表，再执行业务 SQL
            table = self._parse_table(sql)
            before_data = self._fetch_before_data(operation, table, params)

            with self._conn:  # 自动事务
                self._write_audit_log(operation, table, before_data, params)
                return self._conn.execute(sql, params)
        else:
            return self._conn.execute(sql, params)
```

#### Rationale
1. **可靠性**: 审计表和业务表在同一事务，保证原子性
2. **数据完整性**: 可捕获变更前/后的完整行数据
3. **可控性**: 应用层实现，便于调试和监控
4. **可测试性**: 不依赖 SQLite 内部实现细节

#### 审计表结构
```sql
CREATE TABLE _cdc_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,  -- 自增 ID，作为断点
    table_name TEXT NOT NULL,               -- 变更表名
    operation TEXT NOT NULL,                -- INSERT/UPDATE/DELETE
    row_id TEXT,                            -- 业务表主键值
    before_data JSON,                       -- 变更前数据（UPDATE/DELETE）
    after_data JSON,                        -- 变更后数据（INSERT/UPDATE）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    consumed_at TIMESTAMP,                  -- 消费时间戳（NULL 表示未消费）
    retry_count INTEGER DEFAULT 0           -- 重试次数
);

CREATE INDEX idx_audit_unconsumed ON _cdc_audit_log(id) WHERE consumed_at IS NULL;
```

#### 消费流程
```python
async def consume_audit_log(self):
    """后台消费审计日志"""
    while self._running:
        # 批量读取未消费记录
        batch = await self._fetch_unconsumed(limit=self.batch_size)

        if batch:
            # 同步到目标库
            await self._sync_to_targets(batch)

            # 标记为已消费
            await self._mark_consumed([record.id for record in batch])

        await asyncio.sleep(self.poll_interval)
```

#### Alternatives Considered
- ❌ WAL 文件监听: 风险过高，格式复杂
- ❌ 触发器方案: DDL 侵入，无法获取应用上下文

---

## 2. 异步架构设计

### 问题分析

需要同时处理多个任务：
1. WAL 文件监听 (IO bound)
2. 数据库写入 (IO bound)
3. 批量处理优化 (CPU bound for serialization)

### 架构选型

#### Decision
使用 `asyncio` 单事件循环 + `asyncio.Queue` 实现生产者-消费者模式

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ WAL Watcher │────▶│ Event Queue │────▶│  Change     │
│ (Producer)  │     │ (asyncio    │     │  Parser     │
└─────────────┘     │  Queue)     │     └──────┬──────┘
                    └─────────────┘            │
                                                ▼
                    ┌─────────────┐     ┌─────────────┐
                    │  Target DB  │◀────│  Writer     │
                    │  (MySQL/    │     │  (Consumer) │
                    │   Oracle)   │     │             │
                    └─────────────┘     └─────────────┘
```

#### Rationale
1. **并发性能**: asyncio 轻量级，适合大量 IO 操作
2. **背压控制**: Queue 自动处理消费跟不上生产的情况
3. **故障隔离**: Watcher/Parser/Writer 可独立重试

#### Alternatives Considered
- ❌ threading: GIL 限制，无法真正并行
- ❌ multiprocessing: 进程间通信复杂，不符合简单性原则

---

## 3. exactly-once 交付实现

### 问题分析

CDC 系统必须保证：
1. 变更不丢失
2. 变更不重复
3. 故障后可恢复

### 幂等键设计

#### Decision
使用复合键: `{wal_frame_number}:{table_name}:{primary_key_value}`

```python
class ChangeEvent:
    event_id: str  # 格式: "12345:users:42"
    wal_frame: int
    table_name: str
    row_id: Union[int, str]
    operation: Literal["INSERT", "UPDATE", "DELETE"]
    payload: Dict[str, Any]
```

#### Rationale
1. **唯一性**: WAL 帧号单调递增，全局唯一
2. **可恢复**: 从断点继续时知道处理到哪里
3. **目标库幂等**: 使用 UPSERT (INSERT ... ON CONFLICT UPDATE)

### 断点持久化

#### Decision
使用本地 SQLite 数据库存储 checkpoint

```python
# checkpoints.db 结构
CREATE TABLE sync_positions (
    id INTEGER PRIMARY KEY,
    source_db_path TEXT NOT NULL,
    target_name TEXT NOT NULL,
    last_wal_frame INTEGER NOT NULL,
    last_processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_db_path, target_name)
);
```

#### Rationale
1. **轻量级**: 无需外部依赖
2. **原子性**: SQLite 事务保证 checkpoint 原子写入
3. **可观测**: 可查询同步进度

---

## 4. 目标数据库兼容性

### MySQL 写入策略

#### Decision
使用 `INSERT ... ON DUPLICATE KEY UPDATE`

```sql
INSERT INTO users (id, name, email) VALUES (%s, %s, %s)
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    email = VALUES(email)
```

#### Rationale
- 自动处理 INSERT/UPDATE 场景
- 比 REPLACE 更安全（不会先删后插，避免外键问题）

### Oracle 写入策略

#### Decision
使用 `MERGE` 语句

```sql
MERGE INTO users t
USING (SELECT :id id, :name name, :email email FROM dual) s
ON (t.id = s.id)
WHEN MATCHED THEN
    UPDATE SET t.name = s.name, t.email = s.email
WHEN NOT MATCHED THEN
    INSERT (id, name, email) VALUES (s.id, s.name, s.email)
```

#### Rationale
- Oracle 标准语法，无需特殊权限
- 单条语句实现 UPSERT 语义

---

## 5. 目标数据库连接器选型

### MySQL

#### Decision: `aiomysql` (纯 Python, asyncio 原生支持)

| 库 | 优点 | 缺点 | 决策 |
|----|------|------|------|
| aiomysql | asyncio 原生，易用 | 性能略低 | ✅ 采用 |
| asyncmy | 性能更高 | 需要 Cython | ❌ 放弃 |

### Oracle

#### Decision: `oracledb` (官方 Python 驱动，支持 asyncio)

| 库 | 优点 | 缺点 | 决策 |
|----|------|------|------|
| oracledb | 官方支持，thin mode 无需客户端 | 相对较新 | ✅ 采用 |
| cx_Oracle | 成熟稳定 | 需要Oracle客户端，无 asyncio | ❌ 放弃 |

---

## 6. 配置管理

### Decision: Pydantic v2 配置模型

```python
from pydantic import BaseModel, Field

class SyncConfig(BaseModel):
    """同步配置模型"""
    source: SQLiteConfig
    targets: List[TargetConfig]
    mappings: List[TableMapping]
    batch_size: int = Field(default=100, ge=1, le=1000)
    checkpoint_interval: int = Field(default=10, description="每N个事件刷新一次断点")
```

#### Rationale
1. **类型安全**: 运行时自动验证
2. **序列化**: 内置 YAML/JSON 支持
3. **文档生成**: 字段描述可作为配置文档

---

## 7. 日志和可观测性

### Decision: structlog + 标准库 logging

```python
import structlog

logger = structlog.get_logger()

logger.info(
    "change_event_captured",
    table="users",
    operation="INSERT",
    row_id=42,
    wal_frame=12345,
)
```

#### Output Format (JSON)
```json
{
  "timestamp": "2026-02-07T10:30:00Z",
  "level": "info",
  "event": "change_event_captured",
  "table": "users",
  "operation": "INSERT",
  "row_id": 42,
  "wal_frame": 12345
}
```

#### Rationale
1. **结构化**: 便于日志聚合系统解析 (ELK/CloudWatch)
2. **上下文**: 可绑定请求上下文
3. **性能**: 延迟格式化，避免不必要的字符串拼接

---

## 8. 批量写入优化

### Decision: 微批次 (micro-batching)

```python
class BatchWriter:
    def __init__(self, batch_size: int = 100, flush_interval: float = 1.0):
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.buffer: List[ChangeEvent] = []

    async def add(self, event: ChangeEvent):
        self.buffer.append(event)
        if len(self.buffer) >= self.batch_size:
            await self.flush()

    async def flush(self):
        if not self.buffer:
            return
        # 批量写入数据库
        await self.target_writer.write_batch(self.buffer)
        self.buffer.clear()
```

#### Rationale
1. **吞吐 vs 延迟权衡**: 100条/批或1秒/批，以先到者为准
2. **失败处理**: 批次失败时逐条重试，避免阻塞整批
3. **配置化**: 允许用户根据场景调整

---

## 总结

| 决策项 | 选择 | 影响 |
|--------|------|------|
| WAL 监听 | watchdog + wal 文件监听 | 真正实时，无轮询开销 |
| 异步框架 | asyncio + Queue | 高并发，低内存占用 |
| 幂等实现 | UPSERT + checkpoint | exactly-once 保证 |
| MySQL 驱动 | aiomysql | asyncio 原生兼容 |
| Oracle 驱动 | oracledb | 官方支持，thin mode |
| 配置管理 | Pydantic v2 | 类型安全，自动验证 |
| 日志系统 | structlog | 结构化，可观测性 |
| 批量策略 | 微批次 (100条/1秒) | 吞吐与延迟平衡 |

---

**验证**: 所有决策符合宪法要求：
- ✅ 使用中文 (文档和代码注释)
- ✅ 数据一致性 (exactly-once 设计)
- ✅ 事件驱动架构 (asyncio Queue)
- ✅ 测试优先 (后续设计测试策略)
- ✅ 简单性 (单项目，清晰组件划分)
- ✅ 可观测性 (结构化日志)
