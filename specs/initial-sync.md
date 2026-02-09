# 存量数据同步设计

**日期**: 2026-02-07
**关联**: [spec.md](./spec.md), [data-model.md](./data-model.md), [research.md](./research.md)

---

## 概述

存量同步（Initial Sync / Full Sync）是 CDC 方案的第一步，将 SQLite 中已有数据完整复制到目标库（MySQL/Oracle），为后续增量同步建立基准。

---

## 方案对比

| 方案 | 实现方式 | 优点 | 缺点 | 适用场景 | 决策 |
|------|----------|------|------|----------|------|
| **A. 分页批量查询** | `SELECT ... ORDER BY pk LIMIT batch_size` | 实现简单，内存可控，可随时中断恢复 | 需要有效的主键或排序字段 | 通用场景，有主键的表 | ✅ **主要方案** |
| **B. 区间分批查询** | `SELECT ... WHERE pk BETWEEN start AND end` | 无 OFFSET 性能问题，可多区间并行 | 需要连续的主键 | 大数据表优化 | ✅ **辅助方案** |
| **C. 流式游标** | Python 生成器逐条读取 | 代码最简单 | 大数据量内存风险 | 小表（<10万行） | ⚠️ 可选 |
| **D. 文件导出导入** | `.dump` 或 CSV | 速度最快 | 需文件操作，仅 CLI 适用 | CLI 快速迁移 | ⚠️ 可选 |

---

## 推荐方案：混合策略（A + B）

**策略 A 为基础方案**，**策略 B 针对大数据表优化**

### 核心思想

- **小表**（<10万行）：简单分页，单线程顺序处理
- **大表**（≥10万行）：区间分片，并行处理各区间
- **无主键表**：使用 SQLite 隐含 `ROWID` 作为排序字段

---

## 实现细节

### 1. 基础分页方案（策略 A）

```python
async def sync_table_with_pagination(
    self,
    table: str,
    primary_key: str,
    batch_size: int = 1000
) -> int:
    """
    分页同步单表存量数据

    使用 WHERE > last_pk 替代 OFFSET，利用索引提升性能
    """
    synced = 0
    last_pk = None

    while True:
        # 关键优化：使用 WHERE 条件而非 OFFSET
        if last_pk is None:
            sql = f"""
                SELECT * FROM {table}
                ORDER BY {primary_key}
                LIMIT {batch_size}
            """
            params = ()
        else:
            sql = f"""
                SELECT * FROM {table}
                WHERE {primary_key} > ?
                ORDER BY {primary_key}
                LIMIT {batch_size}
            """
            params = (last_pk,)

        batch = await self._source.fetchall(sql, params)

        if not batch:
            break

        # 同步到所有目标（并行）
        await self._sync_batch_to_all_targets(table, batch)

        # 更新断点（支持中断恢复）
        last_pk = batch[-1][primary_key]
        await self._save_checkpoint(table, last_pk)

        synced += len(batch)

        # 流控：避免压垮目标库
        if len(batch) == batch_size:
            await asyncio.sleep(0.001)  # 1ms

    return synced
```

**关键技术点**:
- **WHERE > last_pk**: 比 OFFSET 索引友好，性能稳定
- **断点保存**: 每批次保存位置，支持随时中断和恢复
- **批量写入**: 使用批量 INSERT 减少网络往返
- **流控**: 短暂睡眠避免目标库过载

---

### 2. 区间并行方案（策略 B，大数据表优化）

```python
async def sync_large_table_with_ranges(
    self,
    table: str,
    primary_key: str,
    num_ranges: int = 4
) -> int:
    """
    区间分片并行同步大表

    将表按主键范围切分为多个区间，并行处理
    """
    # 获取主键范围
    row = await self._source.fetchone(
        f"SELECT MIN({primary_key}), MAX({primary_key}) FROM {table}"
    )
    min_pk, max_pk = row[0], row[1]

    if min_pk is None:
        return 0  # 空表

    # 计算区间（处理主键不连续的情况）
    range_size = (max_pk - min_pk + 1) // num_ranges
    ranges = []

    for i in range(num_ranges):
        start = min_pk + i * range_size
        end = min_pk + (i + 1) * range_size - 1 if i < num_ranges - 1 else max_pk
        ranges.append((start, end))

    # 并行同步各区间（协程级并行，非线程级）
    tasks = [
        self._sync_range(table, primary_key, start, end)
        for start, end in ranges
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 错误处理
    total = 0
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"区间 {ranges[i]} 同步失败: {result}")
            raise result
        total += result

    return total

async def _sync_range(
    self,
    table: str,
    primary_key: str,
    start: Any,
    end: Any
) -> int:
    """同步单个区间"""
    sql = f"""
        SELECT * FROM {table}
        WHERE {primary_key} >= ? AND {primary_key} <= ?
        ORDER BY {primary_key}
    """

    # 使用游标逐批读取
    cursor = await self._source.cursor(sql, (start, end))
    synced = 0
    batch = []

    async for row in cursor:
        batch.append(row)

        if len(batch) >= self.batch_size:
            await self._sync_batch_to_all_targets(table, batch)
            synced += len(batch)
            batch = []

    # 剩余批次
    if batch:
        await self._sync_batch_to_all_targets(table, batch)
        synced += len(batch)

    return synced
```

**关键技术点**:
- **区间切分**: 根据主键范围均分为多段
- **协程并行**: 使用 asyncio 并行处理区间，非多线程（避免 SQLite 串行化）
- **独立游标**: 每个区间独立游标，互不干扰
- **异常隔离**: 单个区间失败不影响其他区间

---

### 3. 无主键表处理

```python
def get_effective_primary_key(
    self,
    table: str,
    user_defined_pk: Optional[str] = None
) -> str:
    """
    获取表的有效排序键

    优先级:
    1. 用户配置的 primary_key
    2. 表的实际主键
    3. SQLite 的 ROWID（隐含主键）
    """
    if user_defined_pk:
        return user_defined_pk

    # 查询表的主键
    schema = await self._get_table_schema(table)
    pk_columns = [col for col in schema if col.is_primary_key]

    if pk_columns:
        return pk_columns[0].name

    # 无主键表使用 ROWID（SQLite 每个表都有）
    # ROWID 在 VACUUM 或整行 UPDATE 时会变化，但在批量同步期间是稳定的
    return "ROWID"

async def _check_rowid_stability(self, table: str) -> bool:
    """检查 ROWID 是否稳定（无 INTEGER PRIMARY KEY 别名）"""
    # 如果表有 INTEGER PRIMARY KEY，它会成为 ROWID 的别名
    # 这种情况下 ROWID 是稳定的，否则在 UPDATE 时可能变化
    sql = """
        SELECT sql FROM sqlite_master
        WHERE type='table' AND name=?
    """
    row = await self._source.fetchone(sql, (table,))
    if row:
        create_sql = row[0].upper()
        # 检查是否有 INTEGER PRIMARY KEY
        return "INTEGER" in create_sql and "PRIMARY KEY" in create_sql
    return False
```

**注意事项**:
- **ROWID 稳定性**: 仅当表有 `INTEGER PRIMARY KEY` 时，ROWID 完全稳定；否则批量 UPDATE 可能导致 ROWID 变化
- **建议**: 存量同步期间避免对无主键表执行 UPDATE

---

### 4. 批量写入目标库

```python
async def _sync_batch_to_all_targets(
    self,
    table: str,
    batch: List[Dict[str, Any]]
) -> None:
    """
    将一批数据同步到所有目标库

    并行写入多目标，但每个目标按顺序 UPSERT
    """
    if not batch:
        return

    # 获取字段映射
    table_mapping = self._config.get_table_mapping(table)

    # 转换数据（字段映射、类型转换）
    transformed_batch = [
        self._transform_row(row, table_mapping)
        for row in batch
    ]

    # 并行写入所有目标
    tasks = [
        self._upsert_to_target(target, table_mapping.target_table, transformed_batch)
        for target in self._targets
    ]

    await asyncio.gather(*tasks)

async def _upsert_to_target(
    self,
    target: TargetWriter,
    target_table: str,
    batch: List[Dict[str, Any]]
) -> None:
    """单目标批量 UPSERT"""
    # MySQL: INSERT ... ON DUPLICATE KEY UPDATE
    # Oracle: MERGE INTO ... USING ... ON ... WHEN MATCHED ... WHEN NOT MATCHED ...
    await target.batch_upsert(target_table, batch)
```

---

## 存量与增量的衔接

### 时序问题

存量同步期间，业务系统可能继续写入新数据，需要确保这些变更不被遗漏。

```
时间点序列:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
T0: 存量同步开始
    ├─ 记录审计表当前最大 ID: checkpoint_id = 1000
    ├─ 开始扫描 users 表主键 1-5000
    ├─ 扫描期间业务写入: 新记录写入审计表 ID 1001-1050
    └─ 存量完成，扫描到主键 5000

T1: 增量同步开始
    ├─ 从 checkpoint_id = 1000 开始消费审计表
    ├─ 消费 ID 1001-1050（存量期间的新 INSERT）
    └─ 后续正常消费新变更
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 一致性保证

| 场景 | 处理方式 | 结果 |
|------|----------|------|
| 存量扫描了行 X，增量又审计了 UPDATE X | UPSERT 再次写入，数据被更新 | ✅ 最终一致 |
| 存量期间新 INSERT 行 Y（主键 > 存量范围） | 增量从 checkpoint 消费到该变更 | ✅ 不遗漏 |
| 存量期间 DELETE 行 Z（存量已扫描） | 增量消费 DELETE 事件，目标库删除 | ✅ 最终一致 |

### 实现代码

```python
async def run_with_incremental_handover(self, tables: List[str]):
    """
    执行存量同步，完成后无缝衔接增量
    """
    # 1. 记录审计表断点（增量起点）
    checkpoint_id = await self._get_max_audit_log_id()

    # 2. 执行存量同步
    for table in tables:
        await self.sync_table(table)

    # 3. 持久化断点
    await self._save_incremental_checkpoint(checkpoint_id)

    logger.info(f"存量同步完成，增量从 audit_id={checkpoint_id} 开始")

    return checkpoint_id

async def _get_max_audit_log_id(self) -> int:
    """获取审计表当前最大 ID"""
    row = await self._source.fetchone(
        "SELECT MAX(id) FROM _cdc_audit_log"
    )
    return row[0] or 0
```

---

## 断点恢复设计

### 断点信息结构

```python
@dataclass
class InitialSyncCheckpoint:
    """存量同步断点"""
    table: str                    # 当前同步的表
    last_pk: Any                  # 最后处理的主键值
    total_synced: int             # 该表已同步行数
    status: Literal["running", "completed", "failed"]
    started_at: datetime
    updated_at: datetime
```

### 断点存储

```sql
-- checkpoints.db
CREATE TABLE initial_sync_checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_db_path TEXT NOT NULL,
    table_name TEXT NOT NULL,
    last_pk TEXT,                    -- 最后处理的主键（字符串化）
    total_synced INTEGER DEFAULT 0,
    status TEXT DEFAULT 'running',   -- running/completed/failed
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_db_path, table_name)
);
```

### 恢复流程

```python
async def resume_if_needed(self, table: str) -> Optional[Any]:
    """检查是否需要恢复，返回继续同步的起始主键"""
    checkpoint = await self._load_checkpoint(table)

    if not checkpoint:
        return None  # 全新同步

    if checkpoint.status == "completed":
        logger.info(f"表 {table} 存量已完成，跳过")
        return None  # 已完成

    if checkpoint.status == "running":
        logger.info(f"表 {table} 存量中断，从 pk={checkpoint.last_pk} 恢复")
        return checkpoint.last_pk

    # failed 状态：从头开始或根据策略决定
    if checkpoint.status == "failed":
        logger.warning(f"表 {table} 上次同步失败，重新开始")
        return None
```

---

## 性能优化

### 1. 批量大小调优

| 表大小 | 建议 batch_size | 理由 |
|--------|-----------------|------|
| < 1万行 | 100 | 小步快跑，减少内存 |
| 1-10万行 | 500-1000 | 平衡性能和内存 |
| 10-100万行 | 1000-2000 | 大批量减少网络往返 |
| > 100万行 | 2000-5000 | 最大化吞吐 |

### 2. 并行策略

```python
def decide_sync_strategy(self, table: str, estimated_rows: int) -> SyncStrategy:
    """根据表大小选择同步策略"""
    if estimated_rows < 100000:
        return SyncStrategy.PAGINATION  # 简单分页
    elif estimated_rows < 1000000:
        return SyncStrategy.PARALLEL_RANGES  # 4 区间并行
    else:
        return SyncStrategy.PARALLEL_RANGES_WITH_BATCH  # 大区间分批
```

### 3. 数据库参数优化

```python
async def optimize_for_bulk_read(self):
    """为批量读取优化 SQLite 连接"""
    # 增加缓存大小
    await self._source.execute("PRAGMA cache_size = 10000")

    # 临时存储（内存模式）
    await self._source.execute("PRAGMA temp_store = MEMORY")

    # 同步模式（ NORMAL 足够，OFF 可能有风险）
    await self._source.execute("PRAGMA synchronous = NORMAL")
```

---

## 错误处理

### 常见错误及策略

| 错误类型 | 处理策略 | 备注 |
|----------|----------|------|
| 网络中断（目标库） | 重试 3 次 → 暂停 → 告警 | 保存断点，人工介入 |
| 主键冲突 | 转为 UPSERT | 使用 INSERT ... ON CONFLICT |
| 字段类型不匹配 | 记录到错误表 → 跳过 | 继续同步其他行 |
| SQLite 锁超时 | 退避重试 | 等待业务事务完成 |
| 内存不足 | 减小 batch_size | 动态调整 |

### 死信队列

```python
async def handle_sync_error(
    self,
    table: str,
    row: Dict,
    error: Exception,
    retry_count: int
):
    """处理同步错误"""
    if retry_count >= self.max_retries:
        # 写入死信表
        await self._save_to_dead_letter(table, row, error)
        logger.error(f"行同步失败，已转入死信: {error}")
    else:
        # 指数退避重试
        await asyncio.sleep(2 ** retry_count)
        raise RetryableError(error)
```

---

## 监控指标

```python
@dataclass
class InitialSyncMetrics:
    """存量同步监控指标"""
    table: str
    total_rows: int           # 总行数
    synced_rows: int          # 已同步行数
    percentage: float         # 完成百分比
    rows_per_second: float    # 同步速率
    estimated_remaining: int  # 预计剩余秒数
    current_batch_latency: float  # 当前批次延迟
```

---

## 接口设计

### Python API

```python
# 独立执行存量同步
engine = SyncEngine(config)
report = await engine.run_initial_sync(tables=["users", "orders"])

print(f"同步完成: {report.total_rows} 行")
print(f"耗时: {report.duration} 秒")
print(f"速率: {report.rows_per_second:.1f} 行/秒")

# 存量 + 增量自动衔接
checkpoint = await engine.run_initial_then_incremental(
    tables=["users", "orders"]
)
await engine.start_incremental(from_checkpoint=checkpoint)
```

### CLI 接口

```bash
# 仅执行存量同步
sqlite-cdc initial-sync --config sync.yaml --tables users,orders

# 存量后自动启动增量
sqlite-cdc sync --config sync.yaml --mode full

# 查看存量进度
sqlite-cdc status --config sync.yaml
```

---

## 测试策略

### 单元测试

```python
async def test_pagination_sync():
    """测试分页同步"""
    # 准备 10000 行测试数据
    await insert_test_data(rows=10000)

    # 执行同步
    synced = await sync_table_with_pagination("test_table", "id", batch_size=100)

    # 验证
    assert synced == 10000
    assert target_db.count("test_table") == 10000

async def test_checkpoint_resume():
    """测试断点恢复"""
    # 模拟中断
    # 恢复后验证不从 0 开始
```

### 集成测试

- **数据一致性校验**: 源库 vs 目标库 MD5/行数/采样对比
- **并发场景**: 存量期间并行写入，验证最终一致
- **故障恢复**: 模拟中断，验证断点恢复

---

## 设计决策总结

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 分页策略 | WHERE > last_pk 替代 OFFSET | 性能稳定，主键索引友好 |
| 并行策略 | 协程级区间并行 | 避免 SQLite 多线程锁竞争 |
| 事务策略 | 每批次独立事务 | 减少锁持有，支持断点 |
| 断点粒度 | 每批次保存 | 细粒度恢复，避免重复 |
| 主键策略 | 优先用户配置 → 实际 PK → ROWID | 最大化兼容性 |
| 目标写入 | 批量 UPSERT | 幂等，防重复 |

---

## 关联文档

- [规格文档](./spec.md) - 用户场景与功能需求
- [数据模型](./data-model.md) - 实体定义
- [调研文档](./research.md) - 技术选型
