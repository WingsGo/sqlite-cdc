"""
SQLite CDC 同步引擎

一个 SQLite 到 MySQL/Oracle 的 CDC（变更数据捕获）同步引擎，
支持存量数据全量同步和基于审计日志的实时增量同步。
"""

from typing import Any

__version__ = "0.1.0"

# 延迟导入，避免循环依赖
__all__ = [
    "SyncEngine",
    "CDCConnection",
    "SyncConfig",
    "ChangeEvent",
    "load_config",
]


def __getattr__(name: str) -> Any:
    """延迟加载核心类"""
    if name == "SyncEngine":
        from sqlite_cdc.core.engine import SyncEngine
        return SyncEngine
    elif name == "CDCConnection":
        from sqlite_cdc.core.connection import CDCConnection
        return CDCConnection
    elif name == "SyncConfig":
        from sqlite_cdc.models.sync_config import SyncConfig
        return SyncConfig
    elif name == "ChangeEvent":
        from sqlite_cdc.models.event import ChangeEvent
        return ChangeEvent
    elif name == "load_config":
        from sqlite_cdc.config import load_config
        return load_config
    raise AttributeError(f"module 'sqlite_cdc' has no attribute '{name}'")
