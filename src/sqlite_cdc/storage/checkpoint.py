"""
断点持久化存储 - 使用 SQLite 本地存储
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

from sqlite_cdc.models.event import ChangeEvent
from sqlite_cdc.models.position import InitialSyncCheckpoint, SyncPosition, SyncState


class CheckpointStore:
    """
    断点存储管理器

    使用本地 SQLite 数据库存储同步断点和状态。
    """

    def __init__(self, db_path: Union[str, Path] = "checkpoints.db"):
        """
        初始化断点存储

        参数:
            db_path: 存储数据库路径，默认 checkpoints.db
        """
        self.db_path = Path(db_path)
        self._ensure_tables()

    def close(self) -> None:
        """关闭存储连接"""
        # CheckpointStore 每次操作都打开新连接
        # 只需确保文件句柄释放
        pass

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_tables(self) -> None:
        """确保表结构存在"""
        with self._get_connection() as conn:
            # 同步位置表（增量同步断点）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_db_path TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    last_audit_id INTEGER NOT NULL DEFAULT 0,
                    total_events INTEGER NOT NULL DEFAULT 0,
                    last_processed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_db_path, target_name)
                )
            """)

            # 存量同步断点表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS initial_sync_checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_db_path TEXT NOT NULL,
                    table_name TEXT NOT NULL,
                    last_pk TEXT,
                    total_synced INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'running',
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_db_path, table_name)
                )
            """)

            # 错误日志表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_db_path TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    event_id TEXT,
                    error_type TEXT NOT NULL,
                    error_message TEXT NOT NULL,
                    retry_count INTEGER DEFAULT 0,
                    resolved BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    resolved_at TIMESTAMP
                )
            """)

            # 同步统计表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_db_path TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    table_name TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    count INTEGER DEFAULT 0,
                    last_sync_at TIMESTAMP,
                    UNIQUE(source_db_path, target_name, table_name, operation)
                )
            """)

            # 创建索引
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_positions_source
                    ON sync_positions(source_db_path, target_name)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_initial_source
                    ON initial_sync_checkpoints(source_db_path, table_name)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_errors_unresolved
                    ON sync_errors(resolved, created_at) WHERE resolved = FALSE
            """)

    # ========================================================================
    # 增量同步位置管理
    # ========================================================================

    def save_position(
        self,
        source_db_path: str,
        target_name: str,
        position: SyncPosition
    ) -> None:
        """
        保存同步位置

        参数:
            source_db_path: 源数据库路径
            target_name: 目标名称
            position: 同步位置信息
        """
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO sync_positions
                    (source_db_path, target_name, last_audit_id, total_events,
                     last_processed_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                source_db_path,
                target_name,
                position.last_audit_id,
                position.total_events,
                position.last_processed_at.isoformat() if position.last_processed_at else None,
                datetime.now(timezone.utc).isoformat()
            ))

    def load_position(
        self,
        source_db_path: str,
        target_name: str
    ) -> SyncPosition:
        """
        加载同步位置

        参数:
            source_db_path: 源数据库路径
            target_name: 目标名称

        返回:
            SyncPosition: 同步位置，不存在则返回默认位置（从 0 开始）
        """
        with self._get_connection() as conn:
            row = conn.execute("""
                SELECT last_audit_id, total_events, last_processed_at
                FROM sync_positions
                WHERE source_db_path = ? AND target_name = ?
            """, (source_db_path, target_name)).fetchone()

            if row:
                return SyncPosition(
                    source_db_path=source_db_path,
                    target_name=target_name,
                    last_audit_id=row["last_audit_id"],
                    total_events=row["total_events"],
                    last_processed_at=datetime.fromisoformat(row["last_processed_at"])
                    if row["last_processed_at"] else datetime.now(timezone.utc)
                )

            return SyncPosition(
                source_db_path=source_db_path,
                target_name=target_name,
                last_audit_id=0
            )

    # ========================================================================
    # 存量同步断点管理
    # ========================================================================

    def save_initial_checkpoint(
        self,
        source_db_path: str,
        checkpoint: InitialSyncCheckpoint
    ) -> None:
        """
        保存存量同步断点

        参数:
            source_db_path: 源数据库路径
            checkpoint: 存量同步断点信息
        """
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO initial_sync_checkpoints
                    (source_db_path, table_name, last_pk, total_synced,
                     status, started_at, updated_at)
                VALUES (
                    ?, ?, ?, ?,
                    ?,
                    COALESCE((SELECT started_at FROM initial_sync_checkpoints
                             WHERE source_db_path = ? AND table_name = ?),
                             CURRENT_TIMESTAMP),
                    CURRENT_TIMESTAMP
                )
            """, (
                source_db_path,
                checkpoint.table_name,
                str(checkpoint.last_pk) if checkpoint.last_pk else None,
                checkpoint.total_synced,
                checkpoint.status.value,
                source_db_path,
                checkpoint.table_name
            ))

    def load_initial_checkpoint(
        self,
        source_db_path: str,
        table_name: str
    ) -> Optional[InitialSyncCheckpoint]:
        """
        加载存量同步断点

        参数:
            source_db_path: 源数据库路径
            table_name: 表名

        返回:
            InitialSyncCheckpoint 或 None（如果无记录）
        """
        with self._get_connection() as conn:
            row = conn.execute("""
                SELECT table_name, last_pk, total_synced, status,
                       started_at, updated_at
                FROM initial_sync_checkpoints
                WHERE source_db_path = ? AND table_name = ?
            """, (source_db_path, table_name)).fetchone()

            if row:
                # 解析 last_pk（可能是 int 或 str）
                last_pk = row["last_pk"]
                if last_pk is not None:
                    try:
                        last_pk = int(last_pk)
                    except ValueError:
                        pass

                return InitialSyncCheckpoint(
                    table_name=row["table_name"],
                    last_pk=last_pk,
                    total_synced=row["total_synced"],
                    status=SyncState(row["status"]),
                    started_at=datetime.fromisoformat(row["started_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"])
                )

            return None

    def list_initial_checkpoints(
        self,
        source_db_path: str
    ) -> dict[str, InitialSyncCheckpoint]:
        """
        列出所有存量同步断点

        参数:
            source_db_path: 源数据库路径

        返回:
            {table_name: checkpoint} 字典
        """
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT table_name, last_pk, total_synced, status,
                       started_at, updated_at
                FROM initial_sync_checkpoints
                WHERE source_db_path = ?
            """, (source_db_path,)).fetchall()

            result = {}
            for row in rows:
                last_pk = row["last_pk"]
                if last_pk is not None:
                    try:
                        last_pk = int(last_pk)
                    except ValueError:
                        pass

                result[row["table_name"]] = InitialSyncCheckpoint(
                    table_name=row["table_name"],
                    last_pk=last_pk,
                    total_synced=row["total_synced"],
                    status=SyncState(row["status"]),
                    started_at=datetime.fromisoformat(row["started_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"])
                )

            return result

    def mark_initial_complete(
        self,
        source_db_path: str,
        table_name: str
    ) -> None:
        """标记存量同步为完成状态"""
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE initial_sync_checkpoints
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE source_db_path = ? AND table_name = ?
            """, (SyncState.COMPLETED.value, source_db_path, table_name))

    def delete_initial_checkpoint(
        self,
        source_db_path: str,
        table_name: str
    ) -> None:
        """删除存量同步断点（用于重新开始）"""
        with self._get_connection() as conn:
            conn.execute("""
                DELETE FROM initial_sync_checkpoints
                WHERE source_db_path = ? AND table_name = ?
            """, (source_db_path, table_name))

    # ========================================================================
    # 错误日志管理
    # ========================================================================

    def log_error(
        self,
        source_db_path: str,
        target_name: str,
        event_id: Optional[str],
        error_type: str,
        error_message: str
    ) -> int:
        """
        记录同步错误

        返回:
            错误记录 ID
        """
        with self._get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO sync_errors
                    (source_db_path, target_name, event_id,
                     error_type, error_message)
                VALUES (?, ?, ?, ?, ?)
            """, (source_db_path, target_name, event_id, error_type, error_message))
            return cursor.lastrowid or 0

    def list_unresolved_errors(
        self,
        source_db_path: str,
        target_name: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """列出未解决的错误"""
        with self._get_connection() as conn:
            if target_name:
                rows = conn.execute("""
                    SELECT id, event_id, error_type, error_message,
                           retry_count, created_at
                    FROM sync_errors
                    WHERE source_db_path = ? AND target_name = ? AND resolved = FALSE
                    ORDER BY created_at
                """, (source_db_path, target_name)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT id, target_name, event_id, error_type, error_message,
                           retry_count, created_at
                    FROM sync_errors
                    WHERE source_db_path = ? AND resolved = FALSE
                    ORDER BY created_at
                """, (source_db_path,)).fetchall()

            return [dict(row) for row in rows]

    def resolve_error(self, error_id: int) -> None:
        """标记错误为已解决"""
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE sync_errors
                SET resolved = TRUE, resolved_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (error_id,))

    def increment_retry_count(self, error_id: int) -> int:
        """增加重试计数"""
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE sync_errors
                SET retry_count = retry_count + 1
                WHERE id = ?
            """, (error_id,))
            row = conn.execute(
                "SELECT retry_count FROM sync_errors WHERE id = ?",
                (error_id,)
            ).fetchone()
            return int(row["retry_count"]) if row and row["retry_count"] is not None else 0

    # ========================================================================
    # 统计信息管理
    # ========================================================================

    def update_stats(
        self,
        source_db_path: str,
        target_name: str,
        table_name: str,
        operation: str,
        count: int = 1
    ) -> None:
        """更新同步统计"""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO sync_stats
                    (source_db_path, target_name, table_name, operation, count, last_sync_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(source_db_path, target_name, table_name, operation)
                DO UPDATE SET
                    count = count + ?,
                    last_sync_at = CURRENT_TIMESTAMP
            """, (source_db_path, target_name, table_name, operation, count, count))

    def get_stats(
        self,
        source_db_path: str,
        target_name: str
    ) -> dict[str, Any]:
        """获取同步统计信息"""
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT table_name, operation, count, last_sync_at
                FROM sync_stats
                WHERE source_db_path = ? AND target_name = ?
            """, (source_db_path, target_name)).fetchall()

            stats = {}
            for row in rows:
                key = f"{row['table_name']}.{row['operation']}"
                stats[key] = {
                    "count": row["count"],
                    "last_sync_at": row["last_sync_at"]
                }

            return stats

    def reset_stats(self, source_db_path: str, target_name: str) -> None:
        """重置统计信息"""
        with self._get_connection() as conn:
            conn.execute("""
                DELETE FROM sync_stats
                WHERE source_db_path = ? AND target_name = ?
            """, (source_db_path, target_name))
