"""
SyncEngine 集成测试 (unittest)
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock

from sqlite_cdc.core.engine import SyncEngine
from sqlite_cdc.models.sync_config import (
    MySQLConnection,
    SQLiteConfig,
    SyncConfig,
    TableMapping,
    TargetConfig,
    TargetType,
)


class TestSyncEngineIntegration(IsolatedAsyncioTestCase):
    """SyncEngine 集成测试"""

    def setUp(self):
        """设置测试数据库"""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = str(Path(self.temp_dir) / "test_engine.db")
        self.checkpoint_dir = str(Path(self.temp_dir) / "checkpoints")
        os.makedirs(self.checkpoint_dir, exist_ok=True)
        self._connections = []  # 保存连接引用

        # 创建并初始化数据库
        conn = sqlite3.connect(self.db_path)
        self._connections.append(conn)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                email TEXT
            )
        """)
        # 插入测试数据
        conn.execute("INSERT INTO users (name, email) VALUES (?, ?)",
                    ("张三", "zhangsan@example.com"))
        conn.execute("INSERT INTO users (name, email) VALUES (?, ?)",
                    ("李四", "lisi@example.com"))
        conn.commit()

    def tearDown(self):
        """清理临时文件"""
        import shutil
        # 先关闭所有连接
        for conn in self._connections:
            try:
                conn.close()
            except Exception:
                pass
        self._connections.clear()

        # 尝试删除临时目录（Windows 上可能因文件锁失败）
        if Path(self.temp_dir).exists():
            try:
                shutil.rmtree(self.temp_dir)
            except PermissionError:
                # Windows 上文件可能被锁定，忽略
                pass

    def _create_sync_config(self):
        """创建同步配置"""
        return SyncConfig(
            source=SQLiteConfig(db_path=self.db_path),
            targets=[
                TargetConfig(
                    name="test_mysql",
                    type=TargetType.MYSQL,
                    connection=MySQLConnection(
                        host="localhost",
                        port=3306,
                        database="test",
                        username="root",
                        password="test"
                    )
                )
            ],
            mappings=[
                TableMapping(source_table="users", target_table="users_backup")
            ],
            checkpoint_dir=self.checkpoint_dir
        )

    async def test_engine_initialization(self):
        """测试引擎初始化"""
        config = self._create_sync_config()
        engine = SyncEngine(config)

        self.assertEqual(engine.config, config)
        self.assertFalse(engine.is_running())

    async def test_engine_status_initial(self):
        """测试初始状态"""
        config = self._create_sync_config()
        engine = SyncEngine(config)

        status = engine.get_status()

        self.assertEqual(status.state.value, "idle")
        self.assertEqual(status.source_db, config.source.db_path)


class TestCDCToEngineIntegration(unittest.TestCase):
    """CDC 到 SyncEngine 的端到端测试"""

    def setUp(self):
        """设置测试"""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = str(Path(self.temp_dir) / "test_cdc_engine.db")
        self._connections = []  # 保存连接引用

    def tearDown(self):
        """清理临时文件"""
        import shutil
        # 先关闭所有连接
        for conn in self._connections:
            try:
                if hasattr(conn, 'close'):
                    conn.close()
            except Exception:
                pass
        self._connections.clear()

        # 尝试删除临时目录（Windows 上可能因文件锁失败）
        if Path(self.temp_dir).exists():
            try:
                shutil.rmtree(self.temp_dir)
            except PermissionError:
                # Windows 上文件可能被锁定，忽略
                pass

    def _create_cdc_connection(self):
        """创建 CDC 连接"""
        from sqlite_cdc.core.connection import CDCConnection

        raw_conn = sqlite3.connect(self.db_path)
        raw_conn.row_factory = sqlite3.Row
        self._connections.append(raw_conn)

        # 创建表
        raw_conn.execute("""
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer TEXT,
                amount REAL
            )
        """)
        raw_conn.commit()

        cdc = CDCConnection(raw_conn, enabled_tables=["orders"])
        self._connections.append(cdc)
        return cdc

    def test_cdc_audit_to_event_conversion(self):
        """测试审计记录到事件转换"""
        cdc_connection = self._create_cdc_connection()

        # 插入数据
        cdc_connection.execute(
            "INSERT INTO orders (customer, amount) VALUES (?, ?)",
            ("客户A", 100.0)
        )
        cdc_connection.commit()

        # 查询审计记录
        cursor = cdc_connection._conn.execute(
            "SELECT * FROM _cdc_audit_log WHERE table_name='orders'"
        )
        row = cursor.fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row["operation"], "INSERT")

        # 转换为 AuditLog
        from sqlite_cdc.models.audit import AuditLog
        import json

        audit_log = AuditLog(
            id=row["id"],
            table_name=row["table_name"],
            operation=row["operation"],
            row_id=row["row_id"],
            after_data=json.loads(row["after_data"]) if row["after_data"] else None
        )

        # 转换为 ChangeEvent
        event = audit_log.to_change_event()

        self.assertEqual(event.table_name, "orders")
        self.assertEqual(event.operation.value, "INSERT")
        self.assertEqual(event.after_data["customer"], "客户A")

    def test_cdc_multiple_operations(self):
        """测试多个 CDC 操作"""
        cdc_connection = self._create_cdc_connection()

        # 多个 INSERT
        customers = [("客户A", 100.0), ("客户B", 200.0), ("客户C", 300.0)]
        for customer, amount in customers:
            cdc_connection.execute(
                "INSERT INTO orders (customer, amount) VALUES (?, ?)",
                (customer, amount)
            )
        cdc_connection.commit()

        # 验证有 3 条审计记录
        cursor = cdc_connection._conn.execute(
            "SELECT COUNT(*) FROM _cdc_audit_log WHERE table_name='orders'"
        )
        count = cursor.fetchone()[0]
        self.assertEqual(count, 3)

    def test_cdc_update_audit(self):
        """测试 UPDATE 审计"""
        cdc_connection = self._create_cdc_connection()

        # 插入
        cdc_connection.execute(
            "INSERT INTO orders (customer, amount) VALUES (?, ?)",
            ("客户A", 100.0)
        )
        cdc_connection.commit()

        # 更新
        cdc_connection.execute(
            "UPDATE orders SET amount = ? WHERE customer = ?",
            (150.0, "客户A")
        )
        cdc_connection.commit()

        # 验证 UPDATE 审计记录
        cursor = cdc_connection._conn.execute(
            "SELECT * FROM _cdc_audit_log WHERE operation='UPDATE'"
        )
        row = cursor.fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row["operation"], "UPDATE")

    def test_cdc_delete_audit(self):
        """测试 DELETE 审计"""
        cdc_connection = self._create_cdc_connection()

        # 插入
        cdc_connection.execute(
            "INSERT INTO orders (customer, amount) VALUES (?, ?)",
            ("客户A", 100.0)
        )
        cdc_connection.commit()

        # 删除
        cdc_connection.execute(
            "DELETE FROM orders WHERE customer = ?",
            ("客户A",)
        )
        cdc_connection.commit()

        # 验证 DELETE 审计记录
        cursor = cdc_connection._conn.execute(
            "SELECT * FROM _cdc_audit_log WHERE operation='DELETE'"
        )
        row = cursor.fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row["operation"], "DELETE")


class TestCheckpointIntegration(unittest.TestCase):
    """断点续传集成测试"""

    def setUp(self):
        """设置测试"""
        self.temp_dir = tempfile.mkdtemp()
        self.checkpoint_db = str(Path(self.temp_dir) / "checkpoint.db")
        self._stores = []  # 保存 store 引用

    def tearDown(self):
        """清理临时文件"""
        import shutil
        # 先关闭所有 store 连接
        for store in self._stores:
            try:
                if hasattr(store, 'close'):
                    store.close()
            except Exception:
                pass
        self._stores.clear()

        # 尝试删除临时目录（Windows 上可能因文件锁失败）
        if Path(self.temp_dir).exists():
            try:
                shutil.rmtree(self.temp_dir)
            except PermissionError:
                # Windows 上文件可能被锁定，忽略
                pass

    def test_checkpoint_save_and_load(self):
        """测试断点保存和加载"""
        from sqlite_cdc.models.position import SyncPosition
        from sqlite_cdc.storage.checkpoint import CheckpointStore

        store = CheckpointStore(self.checkpoint_db)
        self._stores.append(store)

        # 创建并保存断点
        position = SyncPosition(
            source_db_path="/data/test.db",
            target_name="mysql1",
            last_audit_id=100
        )
        store.save_position("/data/test.db", "mysql1", position)

        # 加载断点
        loaded = store.load_position("/data/test.db", "mysql1")

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.last_audit_id, 100)
        self.assertEqual(loaded.source_db_path, "/data/test.db")
        self.assertEqual(loaded.target_name, "mysql1")


if __name__ == "__main__":
    unittest.main()