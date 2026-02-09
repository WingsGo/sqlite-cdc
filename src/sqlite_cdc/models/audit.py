"""
审计日志模型 - 审计表记录的数据模型
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, model_validator

from sqlite_cdc.models.event import ChangeEvent, OperationType


class AuditLog(BaseModel):
    """
    审计日志记录

    审计日志表存储所有被 CDC 捕获的数据变更，
    是增量同步的数据源。

    属性:
        id: 自增主键，作为消费断点
        table_name: 变更的业务表名
        operation: 操作类型 (INSERT/UPDATE/DELETE)
        row_id: 业务表主键值（字符串形式）
        before_data: 变更前的行数据（JSON 格式）
        after_data: 变更后的行数据（JSON 格式）
        created_at: 记录创建时间（即变更发生时间）
        consumed_at: 记录被消费时间（NULL 表示未消费）
        retry_count: 消费重试次数

    数据库表结构:
        ```sql
        CREATE TABLE _cdc_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT NOT NULL,
            operation TEXT NOT NULL CHECK(operation IN ('INSERT', 'UPDATE', 'DELETE')),
            row_id TEXT,
            before_data JSON,
            after_data JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            consumed_at TIMESTAMP,
            retry_count INTEGER DEFAULT 0
        );

        CREATE INDEX idx_audit_unconsumed ON _cdc_audit_log(id)
            WHERE consumed_at IS NULL;
        ```
    """
    id: int = Field(..., description="自增主键，消费断点")
    table_name: str = Field(..., description="变更的业务表名")
    operation: OperationType = Field(..., description="操作类型")
    row_id: Optional[str] = Field(default=None, description="业务表主键值")
    before_data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="变更前数据（UPDATE/DELETE）"
    )
    after_data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="变更后数据（INSERT/UPDATE）"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="记录创建时间"
    )
    consumed_at: Optional[datetime] = Field(
        default=None,
        description="消费时间戳，NULL 表示未消费"
    )
    retry_count: int = Field(default=0, ge=0, description="消费重试次数")

    @model_validator(mode="after")
    def validate_data_consistency(self) -> "AuditLog":
        """验证数据一致性"""
        if self.operation == OperationType.INSERT and self.after_data is None:
            raise ValueError("INSERT 操作必须提供 after_data")
        if self.operation == OperationType.DELETE and self.before_data is None:
            raise ValueError("DELETE 操作必须提供 before_data")
        return self

    def is_consumed(self) -> bool:
        """检查是否已消费"""
        return self.consumed_at is not None

    def mark_consumed(self) -> None:
        """标记为已消费"""
        self.consumed_at = datetime.now(timezone.utc)

    def to_change_event(self) -> ChangeEvent:
        """转换为 ChangeEvent 对象"""
        row_id: Any = self.row_id or ""
        # 尝试将 row_id 转为 int（如果是数字主键）
        try:
            row_id = int(row_id)
        except (ValueError, TypeError):
            pass

        return ChangeEvent(
            event_id=f"{self.id}:{self.table_name}:{row_id}",
            audit_id=self.id,
            timestamp=self.created_at,
            operation=self.operation,
            table_name=self.table_name,
            row_id=row_id,
            before_data=self.before_data,
            after_data=self.after_data
        )

    @classmethod
    def from_change_event(cls, event: ChangeEvent) -> "AuditLog":
        """从 ChangeEvent 创建 AuditLog（用于测试）"""
        # 从 event_id 解析 audit_id
        parts = event.event_id.split(":")
        audit_id = int(parts[0])

        return cls(
            id=audit_id,
            table_name=event.table_name,
            operation=event.operation,
            row_id=str(event.row_id),
            before_data=event.before_data,
            after_data=event.after_data,
            created_at=event.timestamp,
        )
