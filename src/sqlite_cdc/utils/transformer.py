"""
数据转换管道 - 应用字段映射和转换器
"""

from typing import Any, Dict, List, Optional

from sqlite_cdc.models.sync_config import FieldMapping, TableMapping
from sqlite_cdc.utils.converters import convert


class DataTransformer:
    """
    数据转换器

    应用字段映射和值转换。
    """

    def __init__(self, table_mapping: TableMapping):
        """
        初始化转换器

        参数:
            table_mapping: 表映射配置
        """
        self.mapping = table_mapping
        self._field_converters: Dict[str, FieldMapping] = {
            fm.source_field: fm for fm in table_mapping.field_mappings
        }

    def transform(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """
        转换单行数据

        参数:
            row: 原始数据行

        返回:
            转换后的数据行
        """
        result: Dict[str, Any] = {}

        for source_field, value in row.items():
            # 检查是否有字段映射
            if source_field in self._field_converters:
                field_mapping = self._field_converters[source_field]

                # 应用转换器
                if field_mapping.converter:
                    value = convert(
                        value,
                        field_mapping.converter,
                        field_mapping.converter_params
                    )

                # 使用目标字段名
                target_field = field_mapping.target_field or source_field
                result[target_field] = value
            else:
                # 无映射，使用原字段名
                result[source_field] = value

        return result

    def transform_batch(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        批量转换数据

        参数:
            rows: 原始数据行列表

        返回:
            转换后的数据行列表
        """
        return [self.transform(row) for row in rows]

    def get_target_table(self) -> str:
        """获取目标表名"""
        return self.mapping.target_table or self.mapping.source_table

    def get_primary_key(self) -> str:
        """获取主键名"""
        return self.mapping.primary_key
