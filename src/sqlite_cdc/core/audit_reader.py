"""
审计日志消费器 - 轮询并消费审计表变更
"""

import asyncio
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlite_cdc.models.audit import AuditLog
from sqlite_cdc.models.event import ChangeEvent
from sqlite_cdc.utils.logging import get_logger

logger = get_logger(__name__)


class AuditReader:
    """
    审计日志读取器

    定期轮询 _cdc_audit_log 表，读取未消费的变更记录。
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        batch_size: int = 100,
        poll_interval: float = 1.0,
        audit_table: str = "_cdc_audit_log"
    ):
        """
        初始化审计日志读取器

        参数:
            conn: SQLite 连接
            batch_size: 每批次读取数量
            poll_interval: 轮询间隔（秒）
            audit_table: 审计表名
        """
        self.conn = conn
        self.batch_size = batch_size
        self.poll_interval = poll_interval
        self.audit_table = audit_table
        self._running = False
        self._last_audit_id = 0

    async def start(self, from_id: int = 0) -> None:
        """
        启动读取器

        参数:
            from_id: 从指定审计 ID 开始读取
        """
        self._last_audit_id = from_id
        self._running = True
        logger.info(
            "audit_reader_started",
            from_id=from_id,
            batch_size=self.batch_size,
            poll_interval=self.poll_interval
        )

    async def stop(self) -> None:
        """停止读取器"""
        self._running = False
        logger.info("audit_reader_stopped")

    def is_running(self) -> bool:
        """检查是否运行中"""
        return self._running

    async def fetch_batch(self) -> List[ChangeEvent]:
        """
        获取一批未消费的变更事件

        返回:
            ChangeEvent 列表
        """
        if not self._running:
            return []

        rows = self._fetch_unconsumed(self._last_audit_id, self.batch_size)

        if not rows:
            # 无数据时等待
            await asyncio.sleep(self.poll_interval)
            return []

        # 转换为 ChangeEvent
        events = []
        for row in rows:
            audit_log = self._row_to_audit_log(row)
            event = audit_log.to_change_event()
            events.append(event)

            # 更新最后读取的 ID
            if event.audit_id > self._last_audit_id:
                self._last_audit_id = event.audit_id

        logger.debug(
            "audit_batch_fetched",
            count=len(events),
            last_id=self._last_audit_id
        )

        return events

    def _fetch_unconsumed(
        self,
        last_id: int,
        limit: int
    ) -> List[sqlite3.Row]:
        """从数据库获取未消费记录"""
        try:
            cursor = self.conn.execute(f"""
                SELECT id, table_name, operation, row_id,
                       before_data, after_data, created_at, retry_count
                FROM {self.audit_table}
                WHERE id > ?
                  AND consumed_at IS NULL
                ORDER BY id
                LIMIT ?
            """, (last_id, limit))

            return cursor.fetchall()
        except Exception as e:
            logger.error("fetch_unconsumed_failed", error=str(e))
            return []

    def mark_consumed(self, audit_ids: List[int]) -> None:
        """
        标记记录为已消费

        参数:
            audit_ids: 审计记录 ID 列表
        """
        if not audit_ids:
            return

        try:
            # 使用参数化查询批量更新
            placeholders = ",".join(["?"] * len(audit_ids))
            self.conn.execute(f"""
                UPDATE {self.audit_table}
                SET consumed_at = ?
                WHERE id IN ({placeholders})
            """, (datetime.now(timezone.utc).isoformat(), *audit_ids))

            self.conn.commit()

            logger.debug("audit_mark_consumed", count=len(audit_ids))
        except Exception as e:
            logger.error("mark_consumed_failed", error=str(e))
            raise

    def mark_consumed_single(self, audit_id: int) -> None:
        """标记单条记录为已消费"""
        self.mark_consumed([audit_id])

    def get_stats(self) -> Dict[str, Any]:
        """获取审计表统计信息"""
        try:
            # 未消费记录数
            cursor = self.conn.execute(f"""
                SELECT COUNT(*) FROM {self.audit_table}
                WHERE consumed_at IS NULL
            """)
            unconsumed = cursor.fetchone()[0]

            # 总记录数
            cursor = self.conn.execute(f"""
                SELECT COUNT(*) FROM {self.audit_table}
            """)
            total = cursor.fetchone()[0]

            # 最大 ID
            cursor = self.conn.execute(f"""
                SELECT COALESCE(MAX(id), 0) FROM {self.audit_table}
            """)
            max_id = cursor.fetchone()[0]

            return {
                "total": total,
                "unconsumed": unconsumed,
                "max_id": max_id,
                "last_read_id": self._last_audit_id,
                "pending": max(0, max_id - self._last_audit_id)
            }
        except Exception as e:
            logger.error("get_stats_failed", error=str(e))
            return {
                "total": 0,
                "unconsumed": 0,
                "max_id": 0,
                "last_read_id": self._last_audit_id,
                "pending": 0
            }

    def _row_to_audit_log(self, row: sqlite3.Row) -> AuditLog:
        """将数据库行转换为 AuditLog 对象"""
        import json

        before_data = None
        after_data = None

        if row["before_data"]:
            try:
                before_data = json.loads(row["before_data"])
            except json.JSONDecodeError:
                pass

        if row["after_data"]:
            try:
                after_data = json.loads(row["after_data"])
            except json.JSONDecodeError:
                pass

        return AuditLog(
            id=row["id"],
            table_name=row["table_name"],
            operation=row["operation"],
            row_id=row["row_id"],
            before_data=before_data,
            after_data=after_data,
            created_at=datetime.fromisoformat(row["created_at"]),
            retry_count=row["retry_count"]
        )
