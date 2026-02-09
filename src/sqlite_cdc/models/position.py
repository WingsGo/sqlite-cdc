"""
同步位置（断点）模型 - 用于故障恢复
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SyncState(str, Enum):
    """同步状态"""
    IDLE = "idle"  # 空闲
    RUNNING = "running"  # 运行中
    PAUSED = "paused"  # 暂停
    ERROR = "error"  # 错误
    COMPLETED = "completed"  # 已完成


class SyncPosition(BaseModel):
    """
    同步位置（断点）信息

    用于记录同步进度，支持故障恢复。

    属性:
        source_db_path: 源数据库路径
        target_name: 目标名称
        last_audit_id: 最后处理的审计日志序列号
        last_processed_at: 最后处理时间
        total_events: 已处理事件总数
    """
    source_db_path: str = Field(..., description="源数据库路径")
    target_name: str = Field(..., description="目标名称")
    last_audit_id: int = Field(default=0, ge=0, description="最后处理的审计日志序列号")
    last_processed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="最后处理时间"
    )
    total_events: int = Field(default=0, ge=0, description="已处理事件总数")

    model_config = ConfigDict(from_attributes=True)

    def update(self, audit_id: int) -> None:
        """更新同步位置"""
        self.last_audit_id = audit_id
        self.last_processed_at = datetime.now(timezone.utc)
        self.total_events += 1


class InitialSyncCheckpoint(BaseModel):
    """
    存量同步断点

    用于记录存量同步进度，支持中断恢复。
    """
    table_name: str = Field(..., description="当前同步的表")
    last_pk: Optional[Union[int, str]] = Field(
        default=None, description="最后处理的主键值"
    )
    total_synced: int = Field(default=0, ge=0, description="该表已同步行数")
    status: SyncState = Field(default=SyncState.RUNNING, description="同步状态")
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="开始时间"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="更新时间"
    )

    def complete(self) -> None:
        """标记为已完成"""
        self.status = SyncState.COMPLETED
        self.updated_at = datetime.now(timezone.utc)

    def fail(self) -> None:
        """标记为失败"""
        self.status = SyncState.ERROR
        self.updated_at = datetime.now(timezone.utc)

    def update_progress(self, pk: Union[int, str], count: int) -> None:
        """更新进度"""
        self.last_pk = pk
        self.total_synced = count
        self.updated_at = datetime.now(timezone.utc)


class SyncStatus(BaseModel):
    """
    同步状态信息

    运行时状态查询返回的数据。
    """
    state: SyncState = Field(default=SyncState.IDLE, description="当前状态")
    source_db: str = Field(default="", description="源数据库路径")
    targets: list[str] = Field(default_factory=list, description="目标列表")

    # 统计信息
    total_events: int = Field(default=0, description="已处理事件总数")
    events_per_second: float = Field(default=0.0, description="处理速率")
    lag_seconds: float = Field(default=0.0, description="同步延迟（秒）")

    # 各表统计
    table_stats: dict[str, dict[str, Any]] = Field(
        default_factory=dict, description="各表统计"
    )

    # 错误信息
    last_error: Optional[str] = Field(default=None, description="最后错误信息")
    last_error_at: Optional[datetime] = Field(default=None, description="最后错误时间")

    def is_running(self) -> bool:
        """检查是否运行中"""
        return self.state == SyncState.RUNNING

    def update_lag(self, lag: float) -> None:
        """更新延迟"""
        self.lag_seconds = lag

    def record_error(self, error: str) -> None:
        """记录错误"""
        self.last_error = error
        self.last_error_at = datetime.now(timezone.utc)
        self.state = SyncState.ERROR
