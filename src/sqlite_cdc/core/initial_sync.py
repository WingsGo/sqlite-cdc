"""
存量数据同步实现 - 全量数据同步到目标库
"""

import asyncio
import sqlite3
from typing import Any, Dict, List, Optional, Union

from sqlite_cdc.models.position import InitialSyncCheckpoint, SyncState
from sqlite_cdc.models.sync_config import SyncConfig, TableMapping
from sqlite_cdc.storage.checkpoint import CheckpointStore
from sqlite_cdc.targets.base import BaseTargetWriter
from sqlite_cdc.utils.logging import get_logger
from sqlite_cdc.utils.transformer import DataTransformer

logger = get_logger(__name__)


class InitialSync:
    """
    存量数据同步器

    将 SQLite 中的现有数据全量同步到目标数据库。
    支持分页查询、断点续传、区间并行。
    """

    def __init__(
        self,
        source_conn: sqlite3.Connection,
        targets: List[BaseTargetWriter],
        config: SyncConfig,
        checkpoint_store: Optional[CheckpointStore] = None
    ):
        """
        初始化存量同步器

        参数:
            source_conn: SQLite 源连接
            targets: 目标写入器列表
            config: 同步配置
            checkpoint_store: 断点存储
        """
        self.source_conn = source_conn
        self.targets = targets
        self.config = config
        self.checkpoint_store = checkpoint_store or CheckpointStore()
        self.batch_size = config.batch_size

    async def sync_table(
        self,
        table_name: str,
        resume: bool = True
    ) -> int:
        """
        同步单表存量数据

        参数:
            table_name: 表名
            resume: 是否尝试断点续传

        返回:
            同步行数
        """
        table_mapping = self.config.get_table_mapping(table_name)
        if not table_mapping:
            raise ValueError(f"表 {table_name} 未在 mappings 中配置")

        # 检查是否需要恢复
        source_path = self.source_conn.execute("PRAGMA database_list").fetchone()[2]
        checkpoint: Optional[InitialSyncCheckpoint] = None

        if resume:
            checkpoint = self.checkpoint_store.load_initial_checkpoint(
                source_path, table_name
            )

        if checkpoint and checkpoint.status == SyncState.COMPLETED:
            logger.info(
                "initial_sync_skip_completed",
                table=table_name,
                total_synced=checkpoint.total_synced
            )
            return checkpoint.total_synced

        # 获取排序键
        pk_column = self._get_effective_primary_key(table_name, table_mapping)

        # 开始同步
        logger.info(
            "initial_sync_start",
            table=table_name,
            pk_column=pk_column,
            resume_from=checkpoint.last_pk if checkpoint else None
        )

        synced = await self._sync_with_pagination(
            table_name=table_name,
            table_mapping=table_mapping,
            pk_column=pk_column,
            start_pk=checkpoint.last_pk if checkpoint else None
        )

        # 标记完成
        final_checkpoint = InitialSyncCheckpoint(
            table_name=table_name,
            total_synced=synced,
            status=SyncState.COMPLETED
        )
        final_checkpoint.complete()
        self.checkpoint_store.save_initial_checkpoint(source_path, final_checkpoint)

        logger.info(
            "initial_sync_complete",
            table=table_name,
            total_synced=synced
        )

        return synced

    async def _sync_with_pagination(
        self,
        table_name: str,
        table_mapping: TableMapping,
        pk_column: str,
        start_pk: Optional[Union[int, str]] = None
    ) -> int:
        """
        使用分页方式同步表

        使用 WHERE pk > last_pk 而不是 OFFSET，性能更好。
        """
        transformer = DataTransformer(table_mapping)
        target_table = transformer.get_target_table()

        synced = 0
        last_pk = start_pk
        batch_num = 0

        while True:
            # 查询一批数据
            rows = self._fetch_batch(table_name, pk_column, last_pk, self.batch_size)

            if not rows:
                break

            # 转换数据
            transformed_rows = transformer.transform_batch(rows)

            # 同步到所有目标
            await self._sync_batch_to_all_targets(target_table, transformed_rows)

            synced += len(rows)
            last_pk = rows[-1].get(pk_column)
            batch_num += 1

            # 保存断点
            if batch_num % 10 == 0:
                source_path = self.source_conn.execute("PRAGMA database_list").fetchone()[2]
                checkpoint = InitialSyncCheckpoint(
                    table_name=table_name,
                    last_pk=last_pk,
                    total_synced=synced,
                    status=SyncState.RUNNING
                )
                self.checkpoint_store.save_initial_checkpoint(source_path, checkpoint)
                logger.debug(
                    "initial_sync_checkpoint",
                    table=table_name,
                    synced=synced,
                    last_pk=last_pk
                )

            # 流控：短暂休息避免压垮目标库
            if len(rows) == self.batch_size:
                await asyncio.sleep(0.001)

        return synced

    def _fetch_batch(
        self,
        table: str,
        pk_column: str,
        last_pk: Optional[Union[int, str]],
        batch_size: int
    ) -> List[Dict[str, Any]]:
        """获取一批数据"""
        if last_pk is None:
            sql = f"""
                SELECT * FROM {table}
                ORDER BY {pk_column}
                LIMIT {batch_size}
            """
            params = ()
        else:
            sql = f"""
                SELECT * FROM {table}
                WHERE {pk_column} > ?
                ORDER BY {pk_column}
                LIMIT {batch_size}
            """
            params = (last_pk,)

        cursor = self.source_conn.execute(sql, params)
        rows = cursor.fetchall()

        # 转换为字典列表
        if rows:
            columns = [description[0] for description in cursor.description]
            return [dict(zip(columns, row)) for row in rows]
        return []

    async def _sync_batch_to_all_targets(
        self,
        table: str,
        batch: List[Dict[str, Any]]
    ) -> None:
        """将一批数据同步到所有目标"""
        if not batch:
            return

        tasks = [
            target.batch_upsert(table, batch)
            for target in self.targets
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理错误
        for target, result in zip(self.targets, results):
            if isinstance(result, Exception):
                logger.error(
                    "initial_sync_batch_failed",
                    target=target.name,
                    table=table,
                    error=str(result)
                )
                raise result

    def _get_effective_primary_key(
        self,
        table: str,
        table_mapping: TableMapping
    ) -> str:
        """
        获取表的有效排序键

        优先级:
        1. 用户配置的 primary_key
        2. 表的实际主键
        3. SQLite 的 ROWID（隐含主键）
        """
        # 1. 用户配置
        if table_mapping.primary_key:
            return table_mapping.primary_key

        # 2. 查询表的主键
        try:
            cursor = self.source_conn.execute(
                "PRAGMA table_info(?)", (table,)
            )
            rows = cursor.fetchall()

            for row in rows:
                # row: (cid, name, type, notnull, dflt_value, pk)
                if row[5] == 1:  # pk column
                    return row[1]
        except Exception:
            pass

        # 3. 使用 ROWID
        return "ROWID"

    async def run_with_handover(self, tables: Optional[List[str]] = None) -> int:
        """
        执行存量同步并记录增量起点

        参数:
            tables: 要同步的表（默认配置中的所有表）

        返回:
            审计日志断点 ID（增量同步从此开始）
        """
        tables_to_sync = tables or [m.source_table for m in self.config.mappings]

        # 1. 记录审计表当前最大 ID（增量起点）
        checkpoint_id = self._get_max_audit_log_id()

        logger.info(
            "initial_sync_with_handover",
            tables=tables_to_sync,
            checkpoint_id=checkpoint_id
        )

        # 2. 执行存量同步
        for table in tables_to_sync:
            await self.sync_table(table)

        # 3. 返回增量起点
        logger.info(
            "initial_sync_handover_complete",
            checkpoint_id=checkpoint_id
        )

        return checkpoint_id

    def _get_max_audit_log_id(self) -> int:
        """获取审计表当前最大 ID"""
        try:
            cursor = self.source_conn.execute(
                "SELECT MAX(id) FROM _cdc_audit_log"
            )
            row = cursor.fetchone()
            return row[0] or 0
        except Exception:
            return 0
