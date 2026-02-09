# SQLite CDC 同步引擎

[![Build status](https://ci.appveyor.com/api/projects/status/lwf6pldcpdeyt6lk/branch/master?svg=true)](https://ci.appveyor.com/project/Wingsgo/sqlite-cdc/branch/master)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

SQLite CDC 同步引擎是一个 Python 库和 CLI 工具，用于将 SQLite 数据库的变更实时同步到 MySQL 或 Oracle 数据库。
代码由[Claude Code](https://github.com/anthropics/claude-code) + Kimi-K2.5 + [spec-kit](https://github.com/github/spec-kit) 生成，人工进行少量微调与验证，用于体验Vibe Coding能力，同时作为小规模场景下生产环境使用。

## 特性

- **CDC 变更捕获**: 通过审计日志表捕获 SQLite 数据变更
- **双模式同步**: 支持存量数据全量同步和增量实时同步
- **多目标支持**: 可同时同步到多个 MySQL/Oracle 目标库
- **字段映射**: 支持字段名映射和值转换
- **最终一致性**: 断点续传、幂等写入保证 exactly-once 语义
- **CLI + 库**: 既可作为命令行工具使用，也可作为 Python 库集成

## 快速开始

### 安装

```bash
pip install sqlite-cdc
```

### 命令行使用

```bash
# 生成配置模板
sqlite-cdc init sync.yaml

# 执行同步（存量 + 增量）
sqlite-cdc sync --config sync.yaml --mode full
```

### Python 库使用

```python
import asyncio
from sqlite_cdc import SyncEngine, load_config

async def main():
    config = await load_config("sync.yaml")
    engine = SyncEngine(config)
    await engine.start()

if __name__ == "__main__":
    asyncio.run(main())
```

## 配置示例

```yaml
source:
  db_path: "./app.db"
  tables: ["users", "orders"]

targets:
  - name: "mysql_prod"
    type: "mysql"
    connection:
      host: "localhost"
      port: 3306
      database: "backup"
      username: "${MYSQL_USER}"
      password: "${MYSQL_PASSWORD}"

mappings:
  - source_table: "users"
    target_table: "users_backup"
    field_mappings:
      - source_field: "email"
        converter: "lowercase"

batch_size: 100
checkpoint_interval: 10
```

## 文档

- [快速开始指南](docs/quickstart.md)
- [API 参考](docs/API.md)
- [配置详解](docs/configuration.md)

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
make test

# 代码检查
make lint

# 格式化代码
make format
```

## 许可证

MIT License
