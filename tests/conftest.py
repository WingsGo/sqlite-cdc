"""
测试配置和共享工具 (unittest 兼容)
"""

import asyncio
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Generator
from unittest.mock import AsyncMock, MagicMock


# ============================================================================
# SQLite 数据库工具
# ============================================================================

def create_temp_db_path() -> Generator[Path, None, None]:
    """创建临时数据库文件路径"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    yield path
    # 清理
    if path.exists():
        path.unlink()
        # 清理 WAL 文件
        for suffix in ["-journal", "-wal", "-shm"]:
            wal_file = Path(str(path) + suffix)
            if wal_file.exists():
                wal_file.unlink()


def create_sqlite_connection(db_path: Path) -> sqlite3.Connection:
    """创建配置了 SQLite 连接"""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    # 启用 WAL 模式
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def create_sqlite_with_tables(db_path: Path) -> sqlite3.Connection:
    """创建带有测试表的 SQLite 连接"""
    conn = create_sqlite_connection(db_path)

    # 创建 users 表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 创建 orders 表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id INTEGER PRIMARY KEY,
            user_id INTEGER,
            total REAL,
            status TEXT DEFAULT 'pending'
        )
    """)

    conn.commit()
    return conn


# ============================================================================
# Mock TargetWriter 工厂函数
# ============================================================================

def create_mock_target_writer() -> MagicMock:
    """创建 Mock TargetWriter"""
    writer = MagicMock()
    writer.connect = AsyncMock()
    writer.disconnect = AsyncMock()
    writer.upsert = AsyncMock()
    writer.batch_upsert = AsyncMock()
    writer.name = "mock_target"
    writer.type = "mock"
    return writer


def create_mock_mysql_writer() -> MagicMock:
    """创建 Mock MySQL writer"""
    writer = MagicMock()
    writer.connect = AsyncMock()
    writer.disconnect = AsyncMock()
    writer.upsert = AsyncMock()
    writer.batch_upsert = AsyncMock()
    writer.name = "mysql_test"
    writer.type = "mysql"
    return writer


def create_mock_oracle_writer() -> MagicMock:
    """创建 Mock Oracle writer"""
    writer = MagicMock()
    writer.connect = AsyncMock()
    writer.disconnect = AsyncMock()
    writer.upsert = AsyncMock()
    writer.batch_upsert = AsyncMock()
    writer.name = "oracle_test"
    writer.type = "oracle"
    return writer


# ============================================================================
# 配置工厂函数
# ============================================================================

def create_test_config_dict(db_path: Path) -> dict[str, Any]:
    """返回测试配置字典"""
    return {
        "source": {
            "db_path": str(db_path),
            "tables": ["users", "orders"],
        },
        "targets": [
            {
                "name": "mysql_test",
                "type": "mysql",
                "connection": {
                    "type": "mysql",
                    "host": "localhost",
                    "port": 3306,
                    "database": "test",
                    "username": "test",
                    "password": "test",
                },
            }
        ],
        "mappings": [
            {
                "source_table": "users",
                "target_table": "users_backup",
                "primary_key": "id",
            },
            {
                "source_table": "orders",
                "target_table": "orders_backup",
                "primary_key": "order_id",
            },
        ],
        "batch_size": 100,
        "checkpoint_interval": 10,
        "log_level": "DEBUG",
    }


def create_test_config_yaml(db_path: Path) -> str:
    """返回测试配置 YAML 字符串"""
    return f"""
source:
  db_path: "{db_path}"
  tables: ["users", "orders"]

targets:
  - name: "mysql_test"
    type: "mysql"
    connection:
      type: "mysql"
      host: "localhost"
      port: 3306
      database: "test"
      username: "test"
      password: "test"

mappings:
  - source_table: "users"
    target_table: "users_backup"
    primary_key: "id"

batch_size: 100
checkpoint_interval: 10
log_level: "DEBUG"
"""


# ============================================================================
# 测试数据工厂函数
# ============================================================================

def get_sample_users_data() -> list[dict[str, Any]]:
    """返回样本用户数据"""
    return [
        {"id": 1, "name": "张三", "email": "zhangsan@example.com"},
        {"id": 2, "name": "李四", "email": "lisi@example.com"},
        {"id": 3, "name": "王五", "email": "wangwu@example.com"},
    ]


def get_sample_change_events() -> list[dict[str, Any]]:
    """返回样本变更事件数据"""
    return [
        {
            "event_id": "1:users:1",
            "audit_id": 1,
            "operation": "INSERT",
            "table_name": "users",
            "row_id": 1,
            "after_data": {"id": 1, "name": "张三"},
        },
        {
            "event_id": "2:users:1",
            "audit_id": 2,
            "operation": "UPDATE",
            "table_name": "users",
            "row_id": 1,
            "before_data": {"id": 1, "name": "张三"},
            "after_data": {"id": 1, "name": "张三丰"},
        },
    ]


# ============================================================================
# 工具函数
# ============================================================================

def setup_logging():
    """设置测试日志级别"""
    from sqlite_cdc.utils.logging import configure_logging
    configure_logging(log_level="DEBUG", json_format=False)


def create_empty_audit_table(conn: sqlite3.Connection) -> sqlite3.Connection:
    """创建空的审计表"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _cdc_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT NOT NULL,
            operation TEXT NOT NULL,
            row_id TEXT,
            before_data JSON,
            after_data JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            consumed_at TIMESTAMP,
            retry_count INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_audit_unconsumed
            ON _cdc_audit_log(id) WHERE consumed_at IS NULL
    """)
    conn.commit()
    return conn


# ============================================================================
# 事件循环管理 (仅用于 asyncio 测试)
# ============================================================================

def create_event_loop() -> asyncio.AbstractEventLoop:
    """创建事件循环"""
    return asyncio.get_event_loop_policy().new_event_loop()