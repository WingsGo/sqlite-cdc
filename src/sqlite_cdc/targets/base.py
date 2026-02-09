"""
目标写入器抽象基类
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from sqlite_cdc.models.event import ChangeEvent
from sqlite_cdc.models.sync_config import RetryPolicy, TargetConfig


class BaseTargetWriter(ABC):
    """
    目标数据库写入器抽象基类

    所有目标数据库写入器（MySQL、Oracle等）的基类，
    定义统一的写入接口。
    """

    def __init__(self, config: TargetConfig):
        """
        初始化写入器

        参数:
            config: 目标数据库配置
        """
        self.config = config
        self.name = config.name
        self.type = config.type
        self.retry_policy = config.retry_policy or RetryPolicy()
        self._connected = False

    @abstractmethod
    async def connect(self) -> None:
        """建立数据库连接"""
        raise NotImplementedError

    @abstractmethod
    async def disconnect(self) -> None:
        """断开数据库连接"""
        raise NotImplementedError

    @abstractmethod
    async def upsert(self, table: str, data: Dict[str, Any]) -> None:
        """
        单条数据 UPSERT

        参数:
            table: 目标表名
            data: 数据字典（包含主键）
        """
        raise NotImplementedError

    @abstractmethod
    async def batch_upsert(self, table: str, rows: List[Dict[str, Any]]) -> None:
        """
        批量数据 UPSERT

        参数:
            table: 目标表名
            rows: 数据字典列表
        """
        raise NotImplementedError

    async def write_event(self, event: ChangeEvent, table_mapping: Any) -> None:
        """
        写入单个变更事件

        参数:
            event: 变更事件
            table_mapping: 表映射配置
        """
        if event.operation.value == "DELETE":
            await self.delete(table_mapping.target_table, event.row_id)
        else:
            data = event.after_data or {}
            await self.upsert(table_mapping.target_table, data)

    @abstractmethod
    async def delete(self, table: str, row_id: Any) -> None:
        """
        删除数据

        参数:
            table: 目标表名
            row_id: 主键值
        """
        raise NotImplementedError

    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self._connected

    async def health_check(self) -> bool:
        """
        健康检查

        返回:
            连接是否健康
        """
        if not self._connected:
            return False
        try:
            await self._ping()
            return True
        except Exception:
            return False

    @abstractmethod
    async def _ping(self) -> None:
        """发送 ping 检查连接"""
        raise NotImplementedError

    def _should_retry(self, attempt: int, error: Exception) -> bool:
        """
        判断是否应重试

        参数:
            attempt: 当前尝试次数
            error: 异常对象

        返回:
            是否应重试
        """
        if attempt >= self.retry_policy.max_retries:
            return False

        # 判断错误类型是否可重试
        # 连接错误通常是可重试的
        error_msg = str(error).lower()
        retryable_errors = [
            "connection", "timeout", "closed", "reset", "refused",
            "network", "temporary", "deadlock"
        ]

        return any(err in error_msg for err in retryable_errors)

    def _get_backoff_delay(self, attempt: int) -> float:
        """
        计算退避延迟

        参数:
            attempt: 尝试次数

        返回:
            延迟秒数
        """
        import random

        delay = self.retry_policy.backoff_factor * (2 ** attempt)
        jitter = random.uniform(0, 1)
        return min(delay + jitter, self.retry_policy.max_delay)
