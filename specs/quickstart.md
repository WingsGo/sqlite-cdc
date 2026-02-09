# 快速开始指南

**版本**: 1.0.0
**日期**: 2026-02-07

---

## 安装

```bash
# 从 PyPI 安装
pip install sqlite-cdc

# 验证安装
sqlite-cdc --version
```

---

## 5 分钟快速体验

### 1. 准备测试数据

```bash
# 创建测试 SQLite 数据库
python3 << 'EOF'
import sqlite3

conn = sqlite3.connect("test.db")
cursor = conn.cursor()

# 创建用户表
cursor.execute("""
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

# 插入测试数据
for i in range(100):
    cursor.execute(
        "INSERT INTO users (name, email) VALUES (?, ?)",
        (f"用户{i}", f"user{i}@example.com")
    )

conn.commit()
conn.close()
print("✓ 测试数据库创建完成: test.db (100 条用户数据)")
EOF
```

### 2. 创建配置文件

```bash
# 生成配置模板
sqlite-cdc init sync.yaml

# 编辑配置（或使用以下示例）
cat > sync.yaml << 'EOF'
source:
  db_path: "./test.db"
  tables: ["users"]  # 同步的表

targets:
  - name: "mysql_local"
    type: "mysql"
    connection:
      type: "mysql"
      host: "localhost"
      port: 3306
      database: "cdc_test"
      username: "root"
      password: "${MYSQL_PASSWORD}"  # 或使用环境变量

mappings:
  - source_table: "users"
    target_table: "users_backup"
    primary_key: "id"
    field_mappings:
      - source_field: "name"
        # 目标字段同名，无需映射
      - source_field: "email"
        converter: "lowercase"  # 转为小写

batch_size: 100
checkpoint_interval: 10
log_level: "INFO"
EOF
```

### 3. 启动同步

```bash
# 执行存量同步 + 增量同步
sqlite-cdc sync --config sync.yaml --mode full
```

预期输出：
```
SQLite CDC 同步引擎
====================
配置: sync.yaml

[存量同步]
表: users
进度: 100/100 行 (100%)
状态: ✓ 完成

[增量同步]
状态: 运行中
延迟: 0.1 秒
已同步: 0 事件

按 Ctrl+C 停止...
```

### 4. 验证同步

在另一个终端测试实时同步：

```python
import sqlite3
from sqlite_cdc import CDCConnection

# 使用 CDC 连接包装器
conn = sqlite3.connect("test.db")
cdc_conn = CDCConnection(conn)

# 插入新数据
cdc_conn.execute(
    "INSERT INTO users (name, email) VALUES (?, ?)",
    ("新用户", "newuser@example.com")
)
cdc_conn.commit()

print("✓ 新数据已插入，将在 1-5 秒内同步到 MySQL")
```

---

## 库模式使用（Python 代码集成）

### 基础用法

```python
import asyncio
from sqlite_cdc import SyncEngine, load_config

async def main():
    # 加载配置
    config = await load_config("sync.yaml")

    # 创建同步引擎
    engine = SyncEngine(config)

    # 启动同步（存量 + 增量）
    await engine.start()

    # 查看状态
    status = engine.get_status()
    print(f"状态: {status.state}")
    print(f"已处理: {status.total_events} 事件")

    # 保持运行
    try:
        while True:
            await asyncio.sleep(1)
            status = engine.get_status()
            print(f"\r延迟: {status.lag_seconds:.2f}s", end="")
    except KeyboardInterrupt:
        print("\n停止同步...")
        await engine.stop()

if __name__ == "__main__":
    asyncio.run(main())
```

### 只使用 CDC 连接（仅审计，不同步）

```python
import sqlite3
from sqlite_cdc import CDCConnection

# 标准 SQLite 连接
conn = sqlite3.connect("myapp.db")

# 包装为 CDC 连接
cdc_conn = CDCConnection(
    conn,
    audit_table="_cdc_audit_log",
    enabled_tables=["orders", "products"]  # 只审计这些表
)

# 正常使用，自动记录审计日志
cdc_conn.execute(
    "INSERT INTO orders (user_id, total) VALUES (?, ?)",
    (42, 199.99)
)
cdc_conn.commit()

# 审计表已自动生成记录
```

### 自定义事件处理

```python
from sqlite_cdc import ChangeEvent

async def main():
    config = await load_config("sync.yaml")
    engine = SyncEngine(config)

    # 注册自定义回调
    def on_user_change(event: ChangeEvent):
        if event.table_name == "users":
            print(f"用户变更: {event.operation} {event.after_data}")

    engine.on_event(on_user_change)

    await engine.start()
```

---

## CLI 命令参考

### 常用命令

```bash
# 初始化配置文件
sqlite-cdc init sync.yaml

# 验证配置
sqlite-cdc validate sync.yaml

# 仅执行存量同步
sqlite-cdc sync --config sync.yaml --mode initial

# 仅执行增量同步（跳过存量）
sqlite-cdc sync --config sync.yaml --mode incremental

# 存量 + 增量（完整流程）
sqlite-cdc sync --config sync.yaml --mode full

# 后台运行
sqlite-cdc sync --config sync.yaml --mode full --daemon --pid-file /var/run/sqlite-cdc.pid

# 查看状态
sqlite-cdc status --config sync.yaml

# 停止同步
sqlite-cdc stop --pid-file /var/run/sqlite-cdc.pid

# 手动触发断点刷新
sqlite-cdc checkpoint --config sync.yaml

# 从断点恢复（故障后）
sqlite-cdc resume --config sync.yaml

# 跳过断点重新开始
sqlite-cdc resume --config sync.yaml --from-scratch
```

### 环境变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `SQLITE_CDC_CONFIG` | 默认配置文件路径 | `/etc/sqlite-cdc/config.yaml` |
| `SQLITE_CDC_LOG_LEVEL` | 日志级别 | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `SQLITE_CDC_LOG_FILE` | 日志文件路径 | `/var/log/sqlite-cdc.log` |

---

## 配置详解

### 最小配置

```yaml
source:
  db_path: "/data/app.db"

targets:
  - name: "mysql_prod"
    type: "mysql"
    connection:
      host: "mysql.example.com"
      database: "backup"
      username: "sync"
      password: "secret"

mappings:
  - source_table: "users"
    target_table: "users_backup"
```

### 完整配置示例

```yaml
source:
  db_path: "/data/app.db"
  tables: ["users", "orders", "products"]  # 空列表表示所有表

targets:
  - name: "mysql_prod"
    type: "mysql"
    connection:
      type: "mysql"
      host: "mysql.example.com"
      port: 3306
      database: "backup_db"
      username: "${MYSQL_USER}"
      password: "${MYSQL_PASSWORD}"
      pool_size: 5
    batch_size: 500
    retry_policy:
      max_retries: 3
      backoff_factor: 1.0

  - name: "oracle_dr"
    type: "oracle"
    connection:
      type: "oracle"
      host: "oracle.example.com"
      port: 1521
      service_name: "ORCL"
      username: "${ORACLE_USER}"
      password: "${ORACLE_PASSWORD}"

mappings:
  - source_table: "users"
    target_table: "app_users"
    primary_key: "id"
    field_mappings:
      - source_field: "name"
        target_field: "user_name"
      - source_field: "email"
        converter: "lowercase"
      - source_field: "status"
        converter: "default"
        converter_params:
          value: "active"
    filter_condition: "deleted_at IS NULL"

  - source_table: "orders"
    target_table: "orders"
    primary_key: "order_id"

batch_size: 100
checkpoint_interval: 100
log_level: "INFO"
```

### 字段转换器

| 转换器 | 说明 | 参数 |
|--------|------|------|
| `lowercase` | 转为小写 | - |
| `uppercase` | 转为大写 | - |
| `trim` | 去除空白 | - |
| `default` | 设置默认值 | `value`: 默认值 |
| `typecast` | 类型转换 | `target_type`: 目标类型 |

---

## 故障排查

### 常见问题

**Q: 同步延迟过高？**

```bash
# 检查审计表积压
sqlite3 app.db "SELECT COUNT(*) FROM _cdc_audit_log WHERE consumed_at IS NULL"

# 如果积压严重，增加批量大小或检查目标库性能
```

**Q: 目标库连接失败？**

```bash
# 验证目标库连接
sqlite-cdc validate sync.yaml

# 检查网络
nc -zv mysql.example.com 3306
```

**Q: 如何清理已消费的审计日志？**

```sql
-- 手动清理（注意：确认消费完成后再清理）
DELETE FROM _cdc_audit_log WHERE consumed_at < datetime('now', '-7 days');
```

### 日志调试

```yaml
# 启用 DEBUG 级别日志
log_level: "DEBUG"

# 日志输出示例
# 2026-02-07 10:30:00 | INFO | change_captured | table=users operation=INSERT row_id=42
# 2026-02-07 10:30:01 | DEBUG | audit_query | batch_size=100 consumed=50 remaining=10
# 2026-02-07 10:30:02 | INFO | batch_flushed | target=mysql_prod rows=100 latency=0.05s
```

---

## 性能优化建议

1. **批量大小的选择**
   - 小表 (<10万行): batch_size=100
   - 中表 (10-100万行): batch_size=500-1000
   - 大表 (>100万行): batch_size=2000-5000

2. **索引优化**
   - 确保业务表有主键
   - 审计表的 `consumed_at` 条件索引自动创建

3. **网络优化**
   - 目标库使用连接池
   - 批量写入减少网络往返

4. **监控指标**
   ```bash
   # 查看实时速率
   sqlite-cdc status --config sync.yaml --watch
   ```

---

## 下一步

- 详细 API 文档: [API.md](../API.md)
- 存量同步设计: [initial-sync.md](./initial-sync.md)
- 数据模型说明: [data-model.md](./data-model.md)
- 问题反馈: https://github.com/your-org/sqlite-cdc/issues
