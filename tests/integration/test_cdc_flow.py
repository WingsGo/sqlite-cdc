"""
CDC 端到端集成测试 (unittest)
"""

import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

from sqlite_cdc.core.audit_reader import AuditReader
from sqlite_cdc.core.connection import CDCConnection


class TestCDCFlow(IsolatedAsyncioTestCase):
    """CDC 完整流程测试"""

    def setUp(self):
        """创建临时数据库"""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = str(Path(self.temp_dir) / "test.db")
        self._connections = []  # 保存连接引用以便关闭

    def tearDown(self):
        """清理临时数据库"""
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

    def _create_connection(self):
        """创建 CDC 连接"""
        raw_conn = sqlite3.connect(self.db_path)
        raw_conn.row_factory = sqlite3.Row

        # 创建测试表
        raw_conn.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                email TEXT
            )
        """)
        raw_conn.commit()

        cdc = CDCConnection(raw_conn, enabled_tables=["users"])
        self._connections.append(cdc)
        self._connections.append(raw_conn)
        return cdc

    def test_insert_audit_record(self):
        """测试 INSERT 生成审计记录"""
        connection = self._create_connection()

        # 插入数据
        connection.execute(
            "INSERT INTO users (name, email) VALUES (?, ?)",
            ("张三", "zhangsan@example.com")
        )
        connection.commit()

        # 查询审计表
        cursor = connection._conn.execute("SELECT * FROM _cdc_audit_log")
        rows = cursor.fetchall()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["operation"], "INSERT")
        self.assertEqual(rows[0]["table_name"], "users")

        # 验证数据
        after_data = json.loads(rows[0]["after_data"])
        self.assertEqual(after_data["name"], "张三")
        self.assertEqual(after_data["email"], "zhangsan@example.com")

    def test_update_audit_record(self):
        """测试 UPDATE 生成审计记录"""
        connection = self._create_connection()

        # 先插入数据
        connection.execute(
            "INSERT INTO users (name, email) VALUES (?, ?)",
            ("张三", "zhangsan@example.com")
        )
        connection.commit()

        # 更新数据
        connection.execute(
            "UPDATE users SET email = ? WHERE name = ?",
            ("newemail@example.com", "张三")
        )
        connection.commit()

        # 查询审计表
        cursor = connection._conn.execute(
            "SELECT * FROM _cdc_audit_log WHERE operation = 'UPDATE'"
        )
        rows = cursor.fetchall()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["operation"], "UPDATE")

    def test_delete_audit_record(self):
        """测试 DELETE 生成审计记录"""
        connection = self._create_connection()

        # 先插入数据
        connection.execute(
            "INSERT INTO users (name, email) VALUES (?, ?)",
            ("张三", "zhangsan@example.com")
        )
        connection.commit()

        # 删除数据
        connection.execute("DELETE FROM users WHERE name = ?", ("张三",))
        connection.commit()

        # 查询审计表
        cursor = connection._conn.execute(
            "SELECT * FROM _cdc_audit_log WHERE operation = 'DELETE'"
        )
        rows = cursor.fetchall()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["operation"], "DELETE")

    def test_multiple_operations(self):
        """测试多个操作生成多条审计记录"""
        connection = self._create_connection()

        # 插入多条数据
        for i in range(5):
            connection.execute(
                "INSERT INTO users (name, email) VALUES (?, ?)",
                (f"用户{i}", f"user{i}@example.com")
            )
        connection.commit()

        # 查询审计表
        cursor = connection._conn.execute("SELECT COUNT(*) FROM _cdc_audit_log")
        count = cursor.fetchone()[0]

        self.assertEqual(count, 5)

    async def test_audit_reader_fetch(self):
        """测试 AuditReader 拉取审计记录"""
        connection = self._create_connection()

        # 插入数据
        connection.execute(
            "INSERT INTO users (name, email) VALUES (?, ?)",
            ("张三", "zhangsan@example.com")
        )
        connection.commit()

        # 创建 AuditReader 并启动
        reader = AuditReader(connection._conn)
        await reader.start(from_id=0)

        # 拉取未消费记录
        events = await reader.fetch_batch()

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].operation.value, "INSERT")
        self.assertEqual(events[0].table_name, "users")

        await reader.stop()

    async def test_audit_reader_mark_consumed(self):
        """测试 AuditReader 标记已消费"""
        connection = self._create_connection()

        # 插入数据
        connection.execute(
            "INSERT INTO users (name, email) VALUES (?, ?)",
            ("张三", "zhangsan@example.com")
        )
        connection.commit()

        # 创建 AuditReader 并启动
        reader = AuditReader(connection._conn)
        await reader.start(from_id=0)

        # 拉取并标记已消费
        events = await reader.fetch_batch()
        reader.mark_consumed([e.audit_id for e in events])

        # 再次拉取应该为空（该批次已消费）
        events = await reader.fetch_batch()
        self.assertEqual(len(events), 0)

        await reader.stop()


class TestCDCAsyncFlow(IsolatedAsyncioTestCase):
    """CDC 异步流程测试"""

    async def test_async_reader(self):
        """测试异步审计读取"""
        import aiosqlite

        temp_dir = tempfile.mkdtemp()
        db_path = str(Path(temp_dir) / "async_reader.db")

        try:
            # 创建表和初始数据
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT
                )
            """)
            conn.commit()

            # 使用 CDCConnection 插入数据
            cdc = CDCConnection(conn, enabled_tables=["items"])
            cdc.execute("INSERT INTO items (name) VALUES (?)", ("item1",))
            cdc.commit()
            cdc.close()

            # 使用异步连接读取
            async with aiosqlite.connect(db_path) as async_conn:
                async_conn.row_factory = aiosqlite.Row

                cursor = await async_conn.execute(
                    "SELECT * FROM _cdc_audit_log"
                )
                rows = await cursor.fetchall()

                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["operation"], "INSERT")
        finally:
            import shutil
            if Path(temp_dir).exists():
                shutil.rmtree(temp_dir)


if __name__ == "__main__":
    unittest.main()