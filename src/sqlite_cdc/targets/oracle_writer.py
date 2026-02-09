"""
Oracle 目标写入器实现
"""

from typing import Any, Dict, List, Optional

from sqlite_cdc.models.sync_config import OracleConnection, TargetConfig
from sqlite_cdc.targets.base import BaseTargetWriter
from sqlite_cdc.utils.logging import get_logger

logger = get_logger(__name__)


class OracleTargetWriter(BaseTargetWriter):
    """
    Oracle 目标数据库写入器

    使用 oracledb 实现异步 Oracle 连接和写入。
    支持 UPSERT（MERGE INTO 语法）
    """

    def __init__(self, config: TargetConfig):
        """
        初始化 Oracle 写入器

        参数:
            config: 目标配置（type 必须为 oracle）
        """
        super().__init__(config)
        if not isinstance(config.connection, OracleConnection):
            raise ValueError("OracleTargetWriter 需要 OracleConnection 配置")

        self.conn_config: OracleConnection = config.connection
        self._pool: Optional[Any] = None
        self._batch_size = config.batch_size or 100

    async def connect(self) -> None:
        """建立 Oracle 连接池"""
        import oracledb

        try:
            # 启用 thin 模式（无需 Oracle 客户端）
            oracledb.defaults.fetch_lobs = False

            # 创建连接池
            self._pool = oracledb.create_pool_async(
                user=self.conn_config.username,
                password=self.conn_config.password,
                host=self.conn_config.host,
                port=self.conn_config.port,
                service_name=self.conn_config.service_name,
                min_size=1,
                max_size=self.conn_config.pool_size,
            )
            self._connected = True
            logger.info(
                "oracle_connected",
                target=self.name,
                host=self.conn_config.host,
                service_name=self.conn_config.service_name
            )
        except Exception as e:
            logger.error(
                "oracle_connect_failed",
                target=self.name,
                error=str(e)
            )
            raise

    async def disconnect(self) -> None:
        """关闭连接池"""
        if self._pool:
            await self._pool.close()
            self._pool = None
        self._connected = False
        logger.info("oracle_disconnected", target=self.name)

    async def upsert(self, table: str, data: Dict[str, Any]) -> None:
        """
        单条数据 UPSERT

        使用 MERGE INTO 语法
        """
        if not self._pool:
            raise RuntimeError("Oracle 未连接")

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql, params = self._build_merge_sql(table, data)
                await cursor.execute(sql, params)
            await conn.commit()

    async def batch_upsert(self, table: str, rows: List[Dict[str, Any]]) -> None:
        """
        批量数据 UPSERT

        Oracle 12c+ 支持多行 MERGE，但较复杂，这里使用逐条执行
        """
        if not self._pool:
            raise RuntimeError("Oracle 未连接")

        if not rows:
            return

        batch_size = self._batch_size

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cursor:
                for i, row in enumerate(rows):
                    sql, params = self._build_merge_sql(table, row)
                    await cursor.execute(sql, params)

                    # 每批次提交
                    if (i + 1) % batch_size == 0:
                        await conn.commit()

                # 剩余提交
                await conn.commit()

        logger.debug(
            "oracle_batch_upsert",
            target=self.name,
            table=table,
            count=len(rows)
        )

    def _build_merge_sql(
        self,
        table: str,
        data: Dict[str, Any],
        pk_column: str = "id"
    ) -> tuple[str, dict[str, Any]]:
        """
        构建 MERGE SQL 语句

        使用 Oracle MERGE INTO 语法：
        MERGE INTO table t
        USING (SELECT :id id, :name name FROM dual) s
        ON (t.id = s.id)
        WHEN MATCHED THEN UPDATE SET t.name = s.name
        WHEN NOT MATCHED THEN INSERT (id, name) VALUES (s.id, s.name)
        """
        columns = list(data.keys())

        # 构建 USING 子句
        using_parts = []
        for col in columns:
            using_parts.append(f":{col} {col}")
        using_clause = f"SELECT {', '.join(using_parts)} FROM dual"

        # 构建 UPDATE SET 子句（排除主键）
        update_cols = [c for c in columns if c != pk_column]
        if update_cols:
            update_sets = [f"t.{col} = s.{col}" for col in update_cols]
            update_clause = f"UPDATE SET {', '.join(update_sets)}"
        else:
            update_clause = "UPDATE SET t.id = t.id"  # 无意义更新，满足语法

        # 构建 INSERT 子句
        insert_cols = ', '.join(columns)
        insert_vals = ', '.join([f"s.{col}" for col in columns])
        insert_clause = f"INSERT ({insert_cols}) VALUES ({insert_vals})"

        # 完整 SQL
        sql = f"""
        MERGE INTO {table} t
        USING ({using_clause}) s
        ON (t.{pk_column} = s.{pk_column})
        WHEN MATCHED THEN {update_clause}
        WHEN NOT MATCHED THEN {insert_clause}
        """

        return sql, data

    async def delete(self, table: str, row_id: Any) -> None:
        """
        删除数据

        参数:
            table: 目标表名
            row_id: 主键值（假设主键名为 'id'）
        """
        if not self._pool:
            raise RuntimeError("Oracle 未连接")

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    f"DELETE FROM {table} WHERE id = :1",
                    (row_id,)
                )
            await conn.commit()

    async def _ping(self) -> None:
        """发送 ping 检查连接"""
        if not self._pool:
            raise RuntimeError("Oracle 未连接")

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT 1 FROM dual")
