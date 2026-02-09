"""
变更事件模型 - 表示一次数据变更
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


class OperationType(str, Enum):
    """数据库操作类型"""
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


class ChangeEvent(BaseModel):
    """
    变更事件对象

    表示 SQLite 中捕获的单行数据变更。
    此对象是 CDC 系统的核心数据流单元。

    属性:
        event_id: 全局唯一事件标识 (格式: "{audit_id}:{table_name}:{row_id}")
        audit_id: 审计日志序列号，用于排序和断点恢复
        timestamp: 事件捕获时间戳
        operation: 操作类型 (INSERT/UPDATE/DELETE)
        table_name: 源表名
        row_id: 主键值
        before_data: 变更前数据 (UPDATE/DELETE 时有值)
        after_data: 变更后数据 (INSERT/UPDATE 时有值)

    示例:
        ```python
        event = ChangeEvent(
            event_id="12345:users:42",
            audit_id=12345,
            timestamp=datetime.now(),
            operation=OperationType.INSERT,
            table_name="users",
            row_id=42,
            after_data={"id": 42, "name": "张三", "email": "zhang@example.com"}
        )
        ```
    """
    event_id: str = Field(..., description="全局唯一事件标识")
    audit_id: int = Field(..., ge=0, description="审计日志序列号")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="事件捕获时间戳"
    )
    operation: OperationType = Field(..., description="操作类型")
    table_name: str = Field(..., description="源表名")
    row_id: Union[int, str] = Field(..., description="主键值")
    before_data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="变更前数据快照"
    )
    after_data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="变更后数据快照"
    )

    @model_validator(mode="after")
    def validate_event_id(self) -> "ChangeEvent":
        """验证 event_id 格式"""
        expected = f"{self.audit_id}:{self.table_name}:{self.row_id}"
        if self.event_id != expected:
            raise ValueError(
                f"event_id 格式错误，期望: {expected}, 实际: {self.event_id}"
            )
        return self

    @model_validator(mode="after")
    def validate_data_consistency(self) -> "ChangeEvent":
        """验证数据一致性"""
        if self.operation == OperationType.INSERT and self.after_data is None:
            raise ValueError("INSERT 操作必须提供 after_data")
        if self.operation == OperationType.DELETE and self.before_data is None:
            raise ValueError("DELETE 操作必须提供 before_data")
        if self.operation == OperationType.UPDATE:
            if self.before_data is None or self.after_data is None:
                raise ValueError("UPDATE 操作必须提供 before_data 和 after_data")
        return self

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典，用于序列化"""
        return self.model_dump()


class BatchEvent(BaseModel):
    """
    批次事件 - 包含多个变更事件

    用于批量处理优化
    """
    events: list[ChangeEvent] = Field(default_factory=list, description="事件列表")
    batch_id: str = Field(default="", description="批次唯一标识")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="批次创建时间"
    )

    def __len__(self) -> int:
        """返回事件数量"""
        return len(self.events)

    def is_empty(self) -> bool:
        """检查是否为空批次"""
        return len(self.events) == 0

    def append(self, event: ChangeEvent) -> None:
        """添加事件到批次"""
        self.events.append(event)

    def extend(self, events: list[ChangeEvent]) -> None:
        """扩展事件列表"""
        self.events.extend(events)
