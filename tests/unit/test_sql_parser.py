"""
SQL 解析器单元测试 (unittest)
"""

import unittest

from sqlite_cdc.utils.sql_parser import (
    extract_table_name,
    is_write_operation,
    normalize_sql,
    parse_operation,
    parse_sql,
)


class TestParseOperation(unittest.TestCase):
    """操作类型解析测试"""

    def test_parse_insert(self):
        """测试解析 INSERT"""
        self.assertEqual(parse_operation("INSERT INTO users VALUES (1)"), "INSERT")
        self.assertEqual(parse_operation("insert into users values (1)"), "INSERT")
        self.assertEqual(parse_operation("  INSERT INTO users..."), "INSERT")

    def test_parse_update(self):
        """测试解析 UPDATE"""
        self.assertEqual(parse_operation("UPDATE users SET name='test'"), "UPDATE")
        self.assertEqual(parse_operation("update users set name='test'"), "UPDATE")

    def test_parse_delete(self):
        """测试解析 DELETE"""
        self.assertEqual(parse_operation("DELETE FROM users WHERE id=1"), "DELETE")
        self.assertEqual(parse_operation("delete from users where id=1"), "DELETE")

    def test_parse_select(self):
        """测试解析 SELECT 返回 None"""
        self.assertIsNone(parse_operation("SELECT * FROM users"))
        self.assertIsNone(parse_operation("select * from users"))

    def test_parse_empty(self):
        """测试解析空字符串"""
        self.assertIsNone(parse_operation(""))
        self.assertIsNone(parse_operation("   "))


class TestExtractTableName(unittest.TestCase):
    """表名提取测试"""

    def test_extract_from_insert(self):
        """测试从 INSERT 提取表名"""
        self.assertEqual(extract_table_name("INSERT INTO users VALUES (1)"), "users")
        self.assertEqual(extract_table_name("INSERT INTO orders (id) VALUES (1)"), "orders")

    def test_extract_from_update(self):
        """测试从 UPDATE 提取表名"""
        self.assertEqual(extract_table_name("UPDATE users SET name='test'"), "users")
        self.assertEqual(extract_table_name("UPDATE orders SET status='done'"), "orders")

    def test_extract_from_delete(self):
        """测试从 DELETE 提取表名"""
        self.assertEqual(extract_table_name("DELETE FROM users WHERE id=1"), "users")
        self.assertEqual(extract_table_name("DELETE FROM orders WHERE id=1"), "orders")

    def test_extract_from_select(self):
        """测试从 SELECT 不提取表名"""
        self.assertIsNone(extract_table_name("SELECT * FROM users"))

    def test_extract_with_backticks(self):
        """测试提取带反引号的表名"""
        self.assertEqual(extract_table_name("INSERT INTO `users` VALUES (1)"), "users")

    def test_extract_with_quotes(self):
        """测试提取带引号的表名"""
        self.assertEqual(extract_table_name('INSERT INTO "users" VALUES (1)'), "users")


class TestParseSQL(unittest.TestCase):
    """完整 SQL 解析测试"""

    def test_parse_insert_sql(self):
        """测试解析 INSERT SQL"""
        op, table = parse_sql("INSERT INTO users (name) VALUES ('test')")
        self.assertEqual(op, "INSERT")
        self.assertEqual(table, "users")

    def test_parse_update_sql(self):
        """测试解析 UPDATE SQL"""
        op, table = parse_sql("UPDATE users SET name='test' WHERE id=1")
        self.assertEqual(op, "UPDATE")
        self.assertEqual(table, "users")

    def test_parse_delete_sql(self):
        """测试解析 DELETE SQL"""
        op, table = parse_sql("DELETE FROM users WHERE id=1")
        self.assertEqual(op, "DELETE")
        self.assertEqual(table, "users")

    def test_parse_select_sql(self):
        """测试解析 SELECT SQL"""
        op, table = parse_sql("SELECT * FROM users")
        self.assertIsNone(op)
        self.assertIsNone(table)


class TestIsWriteOperation(unittest.TestCase):
    """写操作判断测试"""

    def test_insert_is_write(self):
        """测试 INSERT 是写操作"""
        self.assertTrue(is_write_operation("INSERT INTO users VALUES (1)"))

    def test_update_is_write(self):
        """测试 UPDATE 是写操作"""
        self.assertTrue(is_write_operation("UPDATE users SET name='test'"))

    def test_delete_is_write(self):
        """测试 DELETE 是写操作"""
        self.assertTrue(is_write_operation("DELETE FROM users WHERE id=1"))

    def test_select_is_not_write(self):
        """测试 SELECT 不是写操作"""
        self.assertFalse(is_write_operation("SELECT * FROM users"))


class TestNormalizeSQL(unittest.TestCase):
    """SQL 规范化测试"""

    def test_normalize_basic(self):
        """测试基本规范化"""
        sql = "  select   *   from   users  "
        normalized = normalize_sql(sql)
        self.assertIn("SELECT", normalized)
        self.assertIn("*", normalized)
        self.assertIn("FROM", normalized)
        self.assertIn("users", normalized)

    def test_normalize_removes_comments(self):
        """测试移除注释"""
        sql = "SELECT * FROM users /* comment */ WHERE id=1"
        normalized = normalize_sql(sql)
        self.assertNotIn("/* comment */", normalized)

    def test_normalize_uppercase_keywords(self):
        """测试关键字大写"""
        sql = "select * from users"
        normalized = normalize_sql(sql)
        self.assertIn("SELECT", normalized)
        self.assertIn("FROM", normalized)


if __name__ == "__main__":
    unittest.main()