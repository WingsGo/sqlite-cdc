"""
字段转换器单元测试 (unittest)
"""

import unittest

from sqlite_cdc.models.sync_config import ConverterType
from sqlite_cdc.utils.converters import convert, get_converter


class TestConverters(unittest.TestCase):
    """转换器测试"""

    def test_lowercase(self):
        """测试转小写"""
        result = convert("HELLO WORLD", ConverterType.LOWERCASE, {})
        self.assertEqual(result, "hello world")

    def test_lowercase_with_none(self):
        """测试转小写 - None 值"""
        result = convert(None, ConverterType.LOWERCASE, {})
        self.assertIsNone(result)

    def test_uppercase(self):
        """测试转大写"""
        result = convert("hello world", ConverterType.UPPERCASE, {})
        self.assertEqual(result, "HELLO WORLD")

    def test_trim(self):
        """测试去除空白"""
        result = convert("  hello world  ", ConverterType.TRIM, {})
        self.assertEqual(result, "hello world")

    def test_default_with_none(self):
        """测试默认值 - None 值时使用默认"""
        result = convert(None, ConverterType.DEFAULT, {"value": "default"})
        self.assertEqual(result, "default")

    def test_default_with_empty_string(self):
        """测试默认值 - 空字符串时使用默认"""
        result = convert("", ConverterType.DEFAULT, {"value": "default"})
        self.assertEqual(result, "default")

    def test_default_with_value(self):
        """测试默认值 - 有值时保留原值"""
        result = convert("hello", ConverterType.DEFAULT, {"value": "default"})
        self.assertEqual(result, "hello")

    def test_typecast_to_int(self):
        """测试类型转换为 int"""
        result = convert("123", ConverterType.TYPECAST, {"target_type": "int"})
        self.assertEqual(result, 123)
        self.assertIsInstance(result, int)

    def test_typecast_to_float(self):
        """测试类型转换为 float"""
        result = convert("3.14", ConverterType.TYPECAST, {"target_type": "float"})
        self.assertEqual(result, 3.14)
        self.assertIsInstance(result, float)

    def test_typecast_to_str(self):
        """测试类型转换为 str"""
        result = convert(123, ConverterType.TYPECAST, {"target_type": "str"})
        self.assertEqual(result, "123")
        self.assertIsInstance(result, str)

    def test_typecast_invalid_value(self):
        """测试无效值类型转换时保留原值"""
        result = convert("not-a-number", ConverterType.TYPECAST, {"target_type": "int"})
        self.assertEqual(result, "not-a-number")  # 转换失败保留原值

    def test_get_converter(self):
        """测试通过名称获取转换器"""
        converter = get_converter("lowercase")
        self.assertIsNotNone(converter)
        self.assertEqual(converter("HELLO", {}), "hello")

    def test_get_converter_invalid(self):
        """测试获取无效转换器"""
        converter = get_converter("invalid")
        self.assertIsNone(converter)


class TestTransformer(unittest.TestCase):
    """数据转换器测试"""

    def test_transform_basic(self):
        """测试基本转换"""
        from sqlite_cdc.models.sync_config import FieldMapping, TableMapping
        from sqlite_cdc.utils.transformer import DataTransformer

        mapping = TableMapping(
            source_table="users",
            field_mappings=[
                FieldMapping(source_field="email", converter=ConverterType.LOWERCASE)
            ]
        )

        transformer = DataTransformer(mapping)
        result = transformer.transform({
            "id": 1,
            "name": "张三",
            "email": "ZHANGSAN@EXAMPLE.COM"
        })

        self.assertEqual(result["email"], "zhangsan@example.com")
        self.assertEqual(result["id"], 1)
        self.assertEqual(result["name"], "张三")

    def test_transform_field_rename(self):
        """测试字段重命名"""
        from sqlite_cdc.models.sync_config import FieldMapping, TableMapping
        from sqlite_cdc.utils.transformer import DataTransformer

        mapping = TableMapping(
            source_table="users",
            field_mappings=[
                FieldMapping(source_field="name", target_field="user_name")
            ]
        )

        transformer = DataTransformer(mapping)
        result = transformer.transform({
            "id": 1,
            "name": "张三"
        })

        self.assertEqual(result["user_name"], "张三")
        self.assertNotIn("name", result)

    def test_transform_batch(self):
        """测试批量转换"""
        from sqlite_cdc.models.sync_config import TableMapping
        from sqlite_cdc.utils.transformer import DataTransformer

        mapping = TableMapping(source_table="users")
        transformer = DataTransformer(mapping)

        rows = [
            {"id": 1, "name": "张三"},
            {"id": 2, "name": "李四"}
        ]

        results = transformer.transform_batch(rows)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["name"], "张三")
        self.assertEqual(results[1]["name"], "李四")


if __name__ == "__main__":
    unittest.main()