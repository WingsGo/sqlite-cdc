"""
CDCConnection 单元测试 (unittest)
"""

import sqlite3
import unittest

from sqlite_cdc.core.connection import CDCConnection


class TestCDCConnection(unittest.TestCase):
    """CDCConnection 测试"""

    def setUp(self):
        """创建内存数据库"""
        self.in_memory_db = sqlite3.connect(":memory:")
        self.in_memory_db.row_factory = sqlite3.Row

    def tearDown(self):
        """关闭数据库连接"""
        self.in_memory_db.close()

    def _create_cdc_conn(self, enabled_tables=None):
        """创建 CDCConnection 的辅助方法"""
        # 创建测试表
        self.in_memory_db.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                email TEXT
            )
        """)
        self.in_memory_db.commit()

        if enabled_tables is None:
            enabled_tables = ["users"]
        return CDCConnection(self.in_memory_db, enabled_tables=enabled_tables)

    def test_ensure_audit_table(self):
        """测试自动创建审计表"""
        cdc = CDCConnection(self.in_memory_db)

        cursor = self.in_memory_db.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='_cdc_audit_log'
        """)
        self.assertIsNotNone(cursor.fetchone())

    def test_insert_creates_audit_log(self):
        """测试 INSERT 创建审计日志"""
        cdc = self._create_cdc_conn()

        cdc.execute(
            "INSERT INTO users (name, email) VALUES (?, ?)",
            ("张三", "zhangsan@example.com")
        )
        cdc.commit()

        cursor = cdc._conn.execute(
            "SELECT * FROM _cdc_audit_log WHERE table_name='users'"
        )
        row = cursor.fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row["operation"], "INSERT")
        self.assertEqual(row["table_name"], "users")

    def test_audit_log_contains_data(self):
        """测试审计日志包含数据"""
        cdc = self._create_cdc_conn()

        cdc.execute(
            "INSERT INTO users (name, email) VALUES (?, ?)",
            ("张三", "zhangsan@example.com")
        )
        cdc.commit()

        cursor = cdc._conn.execute("SELECT * FROM _cdc_audit_log")
        row = cursor.fetchone()

        import json
        after_data = json.loads(row["after_data"])
        self.assertEqual(after_data["name"], "张三")
        self.assertEqual(after_data["email"], "zhangsan@example.com")

    def test_select_does_not_create_audit(self):
        """测试 SELECT 不创建审计日志"""
        cdc = self._create_cdc_conn()

        # 先插入数据
        cdc.execute(
            "INSERT INTO users (name) VALUES (?)", ("张三",)
        )
        cdc.commit()

        # 统计审计记录数
        cursor = cdc._conn.execute("SELECT COUNT(*) FROM _cdc_audit_log")
        count_before = cursor.fetchone()[0]

        # 执行 SELECT
        cdc.execute("SELECT * FROM users")

        # 验证审计记录数未变
        cursor = cdc._conn.execute("SELECT COUNT(*) FROM _cdc_audit_log")
        count_after = cursor.fetchone()[0]

        self.assertEqual(count_before, count_after)

    def test_context_manager(self):
        """测试上下文管理器"""
        self.in_memory_db.execute("CREATE TABLE test (id INTEGER)")
        self.in_memory_db.commit()

        with CDCConnection(self.in_memory_db) as cdc:
            cdc.execute("INSERT INTO test (id) VALUES (1)")

        # 验证已提交
        cursor = self.in_memory_db.execute("SELECT * FROM test")
        self.assertEqual(cursor.fetchone()[0], 1)

    def test_enabled_tables_filter(self):
        """测试只审计指定表"""
        # 创建两个表
        self.in_memory_db.execute("CREATE TABLE table1 (id INTEGER)")
        self.in_memory_db.execute("CREATE TABLE table2 (id INTEGER)")
        self.in_memory_db.commit()

        # 只审计 table1
        cdc = CDCConnection(self.in_memory_db, enabled_tables=["table1"])

        # 插入 table1
        cdc.execute("INSERT INTO table1 (id) VALUES (1)")
        cdc.execute("INSERT INTO table2 (id) VALUES (1)")
        cdc.commit()

        # 应该只有 table1 的审计记录
        cursor = cdc._conn.execute(
            "SELECT COUNT(*) FROM _cdc_audit_log WHERE table_name='table1'"
        )
        self.assertEqual(cursor.fetchone()[0], 1)

        cursor = cdc._conn.execute(
            "SELECT COUNT(*) FROM _cdc_audit_log WHERE table_name='table2'"
        )
        self.assertEqual(cursor.fetchone()[0], 0)

    def test_transaction_rollback(self):
        """测试事务回滚"""
        self.in_memory_db.execute("CREATE TABLE test (id INTEGER)")
        self.in_memory_db.commit()

        cdc = CDCConnection(self.in_memory_db)

        try:
            cdc.execute("INSERT INTO test (id) VALUES (1)")
            raise Exception("模拟错误")
        except Exception:
            cdc.rollback()

        # 验证数据已回滚
        cursor = cdc._conn.execute("SELECT COUNT(*) FROM test")
        self.assertEqual(cursor.fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()