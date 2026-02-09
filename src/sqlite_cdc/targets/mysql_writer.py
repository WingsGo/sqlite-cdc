"""
MySQL 目标写入器实现
"""

from typing import Any, Dict, List, Optional

import aiomysql

from sqlite_cdc.models.sync_config import MySQLConnection, TargetConfig
from sqlite_cdc.targets.base import BaseTargetWriter
from sqlite_cdc.utils.logging import get_logger

logger = get_logger(__name__)


class MySQLTargetWriter(BaseTargetWriter):
    """
    MySQL 目标数据库写入器

    使用 aiomysql 实现异步 MySQL 连接和写入。
    支持 UPSERT（INSERT ... ON DUPLICATE KEY UPDATE）
    """

    def __init__(self, config: TargetConfig):
        """
        初始化 MySQL 写入器

        参数:
            config: 目标配置（type 必须为 mysql）
        """
        super().__init__(config)
        if not isinstance(config.connection, MySQLConnection):
            raise ValueError("MySQLTargetWriter 需要 MySQLConnection 配置")

        self.conn_config: MySQLConnection = config.connection
        self._pool: Optional[aiomysql.Pool] = None
        self._batch_size = config.batch_size or 100

    async def connect(self) -> None:
        """建立 MySQL 连接池"""
        try:
            self._pool = await aiomysql.create_pool(
                host=self.conn_config.host,
                port=self.conn_config.port,
                user=self.conn_config.username,
                password=self.conn_config.password,
                db=self.conn_config.database,
                charset=self.conn_config.charset,
                minsize=1,
                maxsize=self.conn_config.pool_size,
                autocommit=False,
            )
            self._connected = True
            logger.info(
                "mysql_connected",
                target=self.name,
                host=self.conn_config.host,
                database=self.conn_config.database
            )
        except Exception as e:
            logger.error(
                "mysql_connect_failed",
                target=self.name,
                error=str(e)
            )
            raise

    async def disconnect(self) -> None:
        """关闭连接池"""
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None
        self._connected = False
        logger.info("mysql_disconnected", target=self.name)

    async def upsert(self, table: str, data: Dict[str, Any]) -> None:
        """
        单条数据 UPSERT

        使用 INSERT ... ON DUPLICATE KEY UPDATE 语法
        """
        if not self._pool:
            raise RuntimeError("MySQL 未连接")

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = self._build_upsert_sql(table, [data])
                values = self._extract_values([data])
                await cursor.execute(sql, values[0])
            await conn.commit()

    async def batch_upsert(self, table: str, rows: List[Dict[str, Any]]) -> None:
        """
        批量数据 UPSERT

        分批处理以提高性能
        """
        if not self._pool:
            raise RuntimeError("MySQL 未连接")

        if not rows:
            return

        batch_size = self._batch_size

        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            await self._upsert_batch(table, batch)

    async def _upsert_batch(self, table: str, batch: List[Dict[str, Any]]) -> None:
        """执行批量 UPSERT"""
        if not batch:
            return

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = self._build_upsert_sql(table, batch)

                # 方法1: 尝试使用 executemany
                try:
                    values = self._extract_values(batch)
                    await cursor.executemany(sql, [tuple(row.values()) for row in batch])
                except Exception:
                    # 回退到单条执行
                    for row in batch:
                        values = tuple(row.values())
                        await cursor.execute(sql, values)

            await conn.commit()

        logger.debug(
            "mysql_batch_upsert",
            target=self.name,
            table=table,
            count=len(batch)
        )

    def _build_upsert_sql(self, table: str, rows: List[Dict[str, Any]]) -> str:
        """
        构建 UPSERT SQL 语句

        使用 INSERT ... ON DUPLICATE KEY UPDATE 语法
        """
        if not rows:
            raise ValueError("rows 不能为空")

        # 获取字段名（使用第一行的字段）
        columns = list(rows[0].keys())
        placeholders = [f"%s" for _ in columns]

        # 构建 INSERT 部分
        insert_sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"

        # 构建 ON DUPLICATE KEY UPDATE 部分
        update_parts = [f"{col} = VALUES({col})" for col in columns]
        upsert_sql = f"{insert_sql} ON DUPLICATE KEY UPDATE {', '.join(update_parts)}"

        return upsert_sql

    def _extract_values(self, rows: List[Dict[str, Any]]) -> List[tuple]:
        """提取值列表"""
        return [tuple(row.values()) for row in rows]

    async def delete(self, table: str, row_id: Any) -> None:
        """
        删除数据

        参数:
            table: 目标表名
            row_id: 主键值（需要知道主键名，这里假设为 'id'）
        """
        if not self._pool:
            raise RuntimeError("MySQL 未连接")

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # 假设主键名为 'id'，实际应从配置中获取
                await cursor.execute(
                    f"DELETE FROM {table} WHERE id = %s",
                    (row_id,)
                )
            await conn.commit()

    async def _ping(self) -> None:
        """发送 ping 检查连接"""
        if not self._pool:
            raise RuntimeError("MySQL 未连接")

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT 1")
