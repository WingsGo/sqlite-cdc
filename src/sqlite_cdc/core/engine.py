"""
同步引擎 - 核心协调器
"""

import asyncio
import sqlite3
import time
from typing import Any, Dict, List, Optional

from sqlite_cdc.core.audit_reader import AuditReader
from sqlite_cdc.core.initial_sync import InitialSync
from sqlite_cdc.models.event import ChangeEvent
from sqlite_cdc.models.position import SyncPosition, SyncState, SyncStatus
from sqlite_cdc.models.sync_config import SyncConfig, TableMapping
from sqlite_cdc.storage.checkpoint import CheckpointStore
from sqlite_cdc.targets.base import BaseTargetWriter
from sqlite_cdc.targets.mysql_writer import MySQLTargetWriter
from sqlite_cdc.targets.oracle_writer import OracleTargetWriter
from sqlite_cdc.utils.logging import get_logger
from sqlite_cdc.utils.transformer import DataTransformer

logger = get_logger(__name__)


class SyncEngine:
    """
    同步引擎 - 协调存量和增量同步

    管理完整的数据同步流程，包括：
    - 存量数据全量同步
    - 增量数据实时同步
    - 断点续传
    - 错误处理
    """

    def __init__(self, config: SyncConfig):
        """
        初始化同步引擎

        参数:
            config: 同步配置
        """
        self.config = config
        self.status = SyncStatus(
            source_db=config.source.db_path,
            targets=[t.name for t in config.targets]
        )
        self._running = False
        self._stop_event = asyncio.Event()
        self._checkpoint_store = CheckpointStore()
        self._targets: List[BaseTargetWriter] = []
        self._source_conn: Optional[sqlite3.Connection] = None
        self._audit_reader: Optional[AuditReader] = None

        # 统计
        self._start_time: Optional[float] = None
        self._last_status_time = 0.0

    async def start(
        self,
        tables: Optional[List[str]] = None,
        run_initial: bool = True
    ) -> None:
        """
        启动同步

        参数:
            tables: 要同步的表（默认全部）
            run_initial: 是否执行存量同步
        """
        if self._running:
            raise RuntimeError("同步引擎已在运行")

        self._running = True
        self.status.state = SyncState.RUNNING
        self._start_time = time.time()

        logger.info(
            "sync_engine_start",
            source_db=self.config.source.db_path,
            targets=[t.name for t in self.config.targets],
            run_initial=run_initial
        )

        # 连接源数据库
        self._source_conn = sqlite3.connect(self.config.source.db_path)
        self._source_conn.row_factory = sqlite3.Row

        # 初始化目标写入器
        await self._init_targets()

        try:
            if run_initial:
                # 执行存量同步
                await self._run_initial_sync(tables)

            # 启动增量同步
            await self._run_incremental_sync()

        except Exception as e:
            logger.error("sync_engine_error", error=str(e))
            self.status.state = SyncState.ERROR
            self.status.record_error(str(e))
            raise

    async def stop(self) -> None:
        """停止同步"""
        if not self._running:
            return

        logger.info("sync_engine_stopping")
        self._running = False
        self._stop_event.set()
        self.status.state = SyncState.PAUSED

        # 关闭目标连接
        for target in self._targets:
            try:
                await target.disconnect()
            except Exception as e:
                logger.warning(
                    "target_disconnect_failed",
                    target=target.name,
                    error=str(e)
                )

        # 关闭源连接
        if self._source_conn:
            self._source_conn.close()
            self._source_conn = None

        self._targets = []

        logger.info("sync_engine_stopped")

    def is_running(self) -> bool:
        """检查是否运行中"""
        return self._running

    def get_status(self) -> SyncStatus:
        """获取当前状态"""
        # 计算延迟
        if self._audit_reader:
            stats = self._audit_reader.get_stats()
            pending = stats.get("pending", 0)
            lag = pending * 0.1  # 估算延迟
            self.status.update_lag(lag)

        # 计算速率
        if self._start_time and self.status.total_events > 0:
            elapsed = time.time() - self._start_time
            self.status.events_per_second = self.status.total_events / elapsed

        return self.status

    async def _init_targets(self) -> None:
        """初始化目标写入器"""
        for target_config in self.config.targets:
            if target_config.type.value == "mysql":
                writer = MySQLTargetWriter(target_config)
            elif target_config.type.value == "oracle":
                writer = OracleTargetWriter(target_config)
            else:
                raise ValueError(f"不支持的目标类型: {target_config.type}")

            await writer.connect()
            self._targets.append(writer)
            logger.info("target_connected", target=target_config.name)

    async def _run_initial_sync(self, tables: Optional[List[str]]) -> None:
        """执行存量同步"""
        if not self._source_conn:
            raise RuntimeError("源数据库未连接")

        tables_to_sync = tables or [m.source_table for m in self.config.mappings]

        logger.info(
            "initial_sync_start",
            tables=tables_to_sync
        )

        initial_sync = InitialSync(
            source_conn=self._source_conn,
            targets=self._targets,
            config=self.config,
            checkpoint_store=self._checkpoint_store
        )

        for table in tables_to_sync:
            count = await initial_sync.sync_table(table)
            logger.info(
                "initial_sync_table_complete",
                table=table,
                count=count
            )

    async def _run_incremental_sync(self) -> None:
        """执行增量同步"""
        if not self._source_conn:
            raise RuntimeError("源数据库未连接")

        # 获取各目标的断点
        start_positions: Dict[str, int] = {}
        for target in self._targets:
            pos = self._checkpoint_store.load_position(
                self.config.source.db_path,
                target.name
            )
            start_positions[target.name] = pos.last_audit_id

        # 使用最小的断点作为起点（确保不遗漏）
        start_id = min(start_positions.values()) if start_positions else 0

        logger.info(
            "incremental_sync_start",
            start_id=start_id,
            target_positions=start_positions
        )

        # 创建审计日志读取器
        self._audit_reader = AuditReader(
            conn=self._source_conn,
            batch_size=self.config.batch_size,
            poll_interval=1.0
        )
        await self._audit_reader.start(from_id=start_id)

        # 消费循环
        consumed_ids: List[int] = []

        while self._running and not self._stop_event.is_set():
            try:
                # 获取一批事件
                events = await self._audit_reader.fetch_batch()

                if events:
                    # 处理事件
                    await self._process_events(events, consumed_ids)

                    # 保存断点
                    if consumed_ids:
                        await self._save_checkpoints(consumed_ids)
                        consumed_ids = []

                # 检查停止信号
                if self._stop_event.is_set():
                    break

            except Exception as e:
                logger.error("incremental_sync_error", error=str(e))
                self.status.record_error(str(e))
                await asyncio.sleep(5)  # 错误后等待

        await self._audit_reader.stop()

    async def _process_events(
        self,
        events: List[ChangeEvent],
        consumed_ids: List[int]
    ) -> None:
        """处理事件列表"""
        # 按表分组
        by_table: Dict[str, List[ChangeEvent]] = {}
        for event in events:
            by_table.setdefault(event.table_name, []).append(event)

        # 处理每个表的事件
        for table_name, table_events in by_table.items():
            await self._process_table_events(table_name, table_events)
            consumed_ids.extend([e.audit_id for e in table_events])

        self.status.total_events += len(events)

    async def _process_table_events(
        self,
        table_name: str,
        events: List[ChangeEvent]
    ) -> None:
        """处理单个表的事件"""
        table_mapping = self.config.get_table_mapping(table_name)
        if not table_mapping:
            logger.warning("no_mapping_for_table", table=table_name)
            return

        transformer = DataTransformer(table_mapping)
        target_table = transformer.get_target_table()

        # 转换事件数据
        rows = []
        for event in events:
            if event.operation.value == "DELETE":
                continue  # DELETE 单独处理

            data = event.after_data or {}
            transformed = transformer.transform(data)
            rows.append(transformed)

        # 批量写入
        if rows:
            tasks = [
                target.batch_upsert(target_table, rows)
                for target in self._targets
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

        # 处理 DELETE
        for event in events:
            if event.operation.value == "DELETE":
                tasks = [
                    target.delete(target_table, event.row_id)
                    for target in self._targets
                ]
                await asyncio.gather(*tasks, return_exceptions=True)

        # 更新统计
        if table_name not in self.status.table_stats:
            self.status.table_stats[table_name] = {
                "events": 0,
                "inserts": 0,
                "updates": 0,
                "deletes": 0
            }

        stats = self.status.table_stats[table_name]
        stats["events"] += len(events)
        for event in events:
            op = event.operation.value.lower() + "s"
            if op in stats:
                stats[op] += 1

    async def _save_checkpoints(self, audit_ids: List[int]) -> None:
        """保存断点"""
        if not audit_ids:
            return

        max_id = max(audit_ids)

        for target in self._targets:
            position = SyncPosition(
                source_db_path=self.config.source.db_path,
                target_name=target.name,
                last_audit_id=max_id,
                total_events=self.status.total_events
            )
            self._checkpoint_store.save_position(
                self.config.source.db_path,
                target.name,
                position
            )

        logger.debug("checkpoints_saved", max_id=max_id)
