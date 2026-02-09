"""
同步配置模型 - 使用 Pydantic 进行配置验证
"""

import os
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TargetType(str, Enum):
    """目标数据库类型"""
    MYSQL = "mysql"
    ORACLE = "oracle"


class ConverterType(str, Enum):
    """字段转换器类型"""
    LOWERCASE = "lowercase"           # 转为小写
    UPPERCASE = "uppercase"           # 转为大写
    TRIM = "trim"                     # 去除空白
    DEFAULT = "default"               # 默认值
    TYPECAST = "typecast"             # 类型转换


class SQLiteConfig(BaseModel):
    """
    SQLite 源数据库配置

    属性:
        db_path: SQLite 数据库文件路径
        journal_mode: 日志模式，必须为 WAL
        tables: 需要同步的表名列表，为空表示同步所有表
    """
    db_path: str = Field(..., description="SQLite 数据库文件路径")
    journal_mode: Literal["WAL"] = Field(default="WAL", description="日志模式，必须为 WAL")
    tables: List[str] = Field(default=[], description="同步表列表，空表示所有表")

    @field_validator("db_path")
    @classmethod
    def validate_db_exists(cls, v: str) -> str:
        """验证数据库文件存在（延迟验证选项）"""
        # 在配置解析阶段不强制检查，允许后续创建
        # 但格式必须正确
        if not v or not v.endswith(".db"):
            raise ValueError("数据库路径必须以 .db 结尾")
        return v

    @field_validator("journal_mode")
    @classmethod
    def validate_wal_mode(cls, v: str) -> str:
        """验证 WAL 模式"""
        if v != "WAL":
            raise ValueError("CDC 要求 SQLite 必须使用 WAL 模式")
        return v


class RetryPolicy(BaseModel):
    """
    重试策略配置

    属性:
        max_retries: 最大重试次数，默认 3
        backoff_factor: 退避系数，默认 1.0
        max_delay: 最大退避延迟(秒)，默认 60
    """
    max_retries: int = Field(default=3, ge=0, description="最大重试次数")
    backoff_factor: float = Field(default=1.0, ge=0, description="退避系数")
    max_delay: int = Field(default=60, ge=1, description="最大退避延迟(秒)")


class MySQLConnection(BaseModel):
    """MySQL 连接配置"""
    model_config = ConfigDict(title="MySQL Connection")

    type: Literal["mysql"] = Field(default="mysql", description="连接类型")
    host: str = Field(..., description="主机地址")
    port: int = Field(default=3306, ge=1, le=65535, description="端口")
    database: str = Field(..., description="数据库名")
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")
    charset: str = Field(default="utf8mb4", description="字符集")
    pool_size: int = Field(default=5, ge=1, le=50, description="连接池大小")


class OracleConnection(BaseModel):
    """Oracle 连接配置"""
    model_config = ConfigDict(title="Oracle Connection")

    type: Literal["oracle"] = Field(default="oracle", description="连接类型")
    host: str = Field(..., description="主机地址")
    port: int = Field(default=1521, ge=1, le=65535, description="端口")
    service_name: str = Field(..., description="服务名")
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")
    pool_size: int = Field(default=5, ge=1, le=50, description="连接池大小")


class TargetConfig(BaseModel):
    """
    目标数据库配置

    属性:
        name: 目标名称，用于标识
        type: 数据库类型 (mysql/oracle)
        connection: 连接配置
        batch_size: 此目标的批量大小（覆盖全局配置）
        retry_policy: 重试策略
    """
    name: str = Field(..., min_length=1, description="目标名称标识")
    type: TargetType = Field(..., description="数据库类型")
    connection: Union[MySQLConnection, OracleConnection] = Field(
        ..., discriminator="type", description="连接配置"
    )
    batch_size: Optional[int] = Field(default=None, ge=1, le=1000, description="批量大小覆盖")
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy, description="重试策略")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """验证名称格式"""
        if not v.isalnum() and "_" not in v:
            raise ValueError("目标名称只能包含字母、数字和下划线")
        return v


class FieldMapping(BaseModel):
    """
    字段级映射配置

    属性:
        source_field: 源字段名
        target_field: 目标字段名（默认同源字段名）
        converter: 转换器类型（可选）
        converter_params: 转换器参数
    """
    source_field: str = Field(..., min_length=1, description="源字段名")
    target_field: Optional[str] = Field(default=None, description="目标字段名")
    converter: Optional[ConverterType] = Field(default=None, description="转换器类型")
    converter_params: Dict[str, Any] = Field(default_factory=dict, description="转换器参数")

    @model_validator(mode="after")
    def set_default_target(self) -> "FieldMapping":
        """设置默认目标字段名"""
        if self.target_field is None:
            self.target_field = self.source_field
        return self

    @model_validator(mode="after")
    def validate_converter_params(self) -> "FieldMapping":
        """验证转换器参数"""
        if self.converter == ConverterType.DEFAULT:
            if "value" not in self.converter_params:
                raise ValueError("default 转换器必须提供 value 参数")
        return self


class TableMapping(BaseModel):
    """
    表级映射配置

    属性:
        source_table: 源表名
        target_table: 目标表名（默认同源表名）
        field_mappings: 字段映射列表
        filter_condition: 过滤条件 SQL（可选）
        primary_key: 主键字段名（默认 "id"）
    """
    source_table: str = Field(..., min_length=1, description="源表名")
    target_table: Optional[str] = Field(default=None, description="目标表名")
    field_mappings: List[FieldMapping] = Field(default_factory=list, description="字段映射")
    filter_condition: Optional[str] = Field(
        default=None,
        description="行级过滤条件，如: status = 'active'"
    )
    primary_key: str = Field(default="id", description="主键字段名")

    @model_validator(mode="after")
    def set_default_target(self) -> "TableMapping":
        """设置默认目标表名"""
        if self.target_table is None:
            self.target_table = self.source_table
        return self


class SyncConfig(BaseModel):
    """
    CDC 同步配置根对象

    属性:
        source: 源 SQLite 数据库配置
        targets: 目标数据库配置列表（支持多个目标）
        mappings: 表映射规则列表
        batch_size: 批量写入大小，默认 100
        checkpoint_interval: 断点刷新间隔（事件数），默认 10
        log_level: 日志级别，默认 INFO
    """
    source: SQLiteConfig = Field(..., description="源数据库配置")
    targets: List[TargetConfig] = Field(
        ..., min_length=1, description="目标数据库配置列表"
    )
    mappings: List[TableMapping] = Field(
        ..., min_length=1, description="表映射规则列表"
    )
    batch_size: int = Field(
        default=100, ge=1, le=1000, description="批量写入大小"
    )
    checkpoint_interval: int = Field(
        default=10, ge=1, description="断点刷新间隔（事件数）"
    )
    log_level: str = Field(default="INFO", description="日志级别")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """验证日志级别"""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR"]
        if v.upper() not in valid_levels:
            raise ValueError(f"日志级别必须是以下之一: {valid_levels}")
        return v.upper()

    @model_validator(mode="after")
    def validate_target_names_unique(self) -> "SyncConfig":
        """验证目标名称唯一"""
        names = [t.name for t in self.targets]
        if len(names) != len(set(names)):
            raise ValueError("目标名称必须唯一")
        return self

    @model_validator(mode="after")
    def validate_source_tables_exists(self) -> "SyncConfig":
        """验证映射中的表在 source.tables 中有定义（如果指定了）"""
        if self.source.tables:
            source_tables = set(self.source.tables)
            mapping_tables = {m.source_table for m in self.mappings}
            undefined = mapping_tables - source_tables
            if undefined:
                raise ValueError(
                    f"以下表在 mappings 中但未在 source.tables 定义: {undefined}"
                )
        return self

    def get_table_mapping(self, table_name: str) -> Optional[TableMapping]:
        """获取指定表的映射配置"""
        for mapping in self.mappings:
            if mapping.source_table == table_name:
                return mapping
        return None

    def get_target_config(self, target_name: str) -> Optional[TargetConfig]:
        """获取指定目标的配置"""
        for target in self.targets:
            if target.name == target_name:
                return target
        return None


def expand_env_vars(value: Any) -> Any:
    """
    递归展开值中的环境变量

    支持格式:
        - ${VAR_NAME}
        - ${VAR_NAME:-default_value}
    """
    if isinstance(value, str):
        import re

        # 匹配 ${VAR} 或 ${VAR:-default}
        pattern = r'\$\{([^}:-]+)(?::-([^}]*))?\}'

        def replacer(match: "re.Match[str]") -> str:
            var_name = match.group(1)
            default_val = match.group(2)
            env_value = os.getenv(var_name)
            if env_value is None:
                if default_val is not None:
                    return default_val
                raise ValueError(f"环境变量 {var_name} 未设置且无默认值")
            return env_value

        result: Any = re.sub(pattern, replacer, value)
        return result
    elif isinstance(value, dict):
        return {k: expand_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [expand_env_vars(item) for item in value]
    return value
