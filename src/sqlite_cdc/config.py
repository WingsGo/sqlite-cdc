"""
配置加载模块 - 支持 YAML 和环境变量
"""

import os
from pathlib import Path
from typing import Any

import yaml

from sqlite_cdc.models.sync_config import SyncConfig, expand_env_vars


class ConfigError(Exception):
    """配置错误"""
    pass


def load_config(path: str | Path) -> SyncConfig:
    """
    加载 YAML 配置文件

    支持环境变量替换，格式:
        - ${VAR_NAME}
        - ${VAR_NAME:-default_value}

    参数:
        path: 配置文件路径

    返回:
        SyncConfig: 验证后的配置对象

    异常:
        ConfigError: 配置文件不存在或格式错误
        ValueError: 配置验证失败

    示例:
        ```python
        config = load_config("sync.yaml")
        print(config.source.db_path)
        ```
    """
    config_path = Path(path)

    if not config_path.exists():
        raise ConfigError(f"配置文件不存在: {config_path}")

    try:
        content = config_path.read_text(encoding="utf-8")
    except Exception as e:
        raise ConfigError(f"读取配置文件失败: {e}")

    try:
        raw_config = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML 解析失败: {e}")

    if not isinstance(raw_config, dict):
        raise ConfigError("配置文件必须是一个对象")

    # 展开环境变量
    expanded_config = expand_env_vars(raw_config)

    try:
        return SyncConfig(**expanded_config)
    except ValueError as e:
        raise ConfigError(f"配置验证失败: {e}")


def load_config_from_string(content: str) -> SyncConfig:
    """
    从字符串加载配置（用于测试）

    参数:
        content: YAML 配置字符串

    返回:
        SyncConfig: 验证后的配置对象
    """
    raw_config = yaml.safe_load(content)
    expanded_config = expand_env_vars(raw_config)
    return SyncConfig(**expanded_config)


def generate_config_template() -> str:
    """
    生成配置模板

    返回:
        str: YAML 配置模板
    """
    return '''# SQLite CDC 同步引擎配置

# 源数据库配置
source:
  db_path: "./source.db"
  tables: ["users", "orders"]  # 空列表表示同步所有表

# 目标数据库配置
targets:
  - name: "mysql_prod"
    type: "mysql"
    connection:
      type: "mysql"
      host: "localhost"
      port: 3306
      database: "cdc_backup"
      username: "${MYSQL_USER}"
      password: "${MYSQL_PASSWORD}"
    batch_size: 100
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

# 表映射配置
mappings:
  - source_table: "users"
    target_table: "users_backup"
    primary_key: "id"
    field_mappings:
      - source_field: "name"
        # 目标字段同名，无需映射
      - source_field: "email"
        converter: "lowercase"  # 转为小写
    filter_condition: "deleted_at IS NULL"  # 只同步未删除记录

  - source_table: "orders"
    target_table: "orders_backup"
    primary_key: "order_id"

# 全局配置
batch_size: 100               # 批量写入大小
checkpoint_interval: 10       # 每N个事件刷新一次断点
log_level: "INFO"             # 日志级别 (DEBUG, INFO, WARNING, ERROR)
'''


def save_config_template(path: str | Path) -> None:
    """
    保存配置模板到文件

    参数:
        path: 输出文件路径
    """
    config_path = Path(path)
    config_path.write_text(generate_config_template(), encoding="utf-8")
