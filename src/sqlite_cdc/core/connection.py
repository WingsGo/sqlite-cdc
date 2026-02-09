"""
CDC 连接包装器 - 拦截 SQLite 写入并记录审计日志
"""

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple, Union

from sqlite_cdc.models.audit import OperationType
from sqlite_cdc.utils.logging import get_logger
from sqlite_cdc.utils.sql_parser import parse_sql

logger = get_logger(__name__)


def _row_to_dict(row: Any, cursor: sqlite3.Cursor) -> Dict[str, Any]:
    """安全地将查询结果行转换为字典

    Args:
        row: 查询结果行，可能是 sqlite3.Row 或 tuple
        cursor: 游标对象，用于获取列名

    Returns:
        Dict[str, Any]: 列名到值的映射字典
    """
    if row is None:
        return {}

    # 如果已经是字典，直接返回
    if isinstance(row, dict):
        return row

    # 如果有 keys 方法(sqlite3.Row)，使用它
    if hasattr(row, 'keys'):
        return dict(row)

    # 如果是 tuple，使用列名构建字典
    if isinstance(row, (tuple, list)):
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))

    # 其他情况尝试直接转换
    return dict(row)


class CDCConnection:
    """
    CDC 包装的 SQLite 连接

    拦截 execute 系列操作，将 INSERT/UPDATE/DELETE 自动记录到审计表。
    审计记录和业务数据在同一事务中写入，保证原子性。

    属性:
        _conn: 底层 SQLite 连接
        _audit_table: 审计表名，默认 "_cdc_audit_log"
        _enabled_tables: 需要审计的表名列表（空表示所有表）

    示例:
        ```python
        # 使用 CDC 包装连接
        raw_conn = sqlite3.connect("/data/app.db")
        cdc_conn = CDCConnection(raw_conn, enabled_tables=["users", "orders"])

        # 所有写入自动记录审计日志
        cdc_conn.execute(
            "INSERT INTO users (name, email) VALUES (?, ?)",
            ("张三", "zhang@example.com")
        )
        # 自动在 _cdc_audit_log 生成记录
        ```
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        audit_table: str = "_cdc_audit_log",
        enabled_tables: Optional[List[str]] = None
    ):
        self._conn = conn
        self._audit_table = audit_table
        self._enabled_tables = set(enabled_tables or [])
        self._ensure_audit_table()

    def _ensure_audit_table(self) -> None:
        """确保审计表存在"""
        create_sql = f"""
        CREATE TABLE IF NOT EXISTS {self._audit_table} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT NOT NULL,
            operation TEXT NOT NULL,
            row_id TEXT,
            before_data JSON,
            after_data JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            consumed_at TIMESTAMP,
            retry_count INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_{self._audit_table}_unconsumed
            ON {self._audit_table}(id) WHERE consumed_at IS NULL;
        CREATE INDEX IF NOT EXISTS idx_{self._audit_table}_table
            ON {self._audit_table}(table_name, created_at);
        """
        self._conn.executescript(create_sql)

    def _should_audit(self, table_name: str) -> bool:
        """检查表是否需要审计"""
        if not self._enabled_tables:
            return True
        return table_name in self._enabled_tables

    def execute(
        self,
        sql: str,
        parameters: Union[tuple, dict, list] = ()
    ) -> sqlite3.Cursor:
        """
        执行 SQL，自动记录审计日志

        对于 INSERT/UPDATE/DELETE 操作：
        1. 解析 SQL 获取表名和操作类型
        2. 对于 UPDATE/DELETE，查询变更前的数据
        3. 在同一事务中执行业务 SQL 并记录审计日志

        参数:
            sql: SQL 语句
            parameters: SQL 参数

        返回:
            sqlite3.Cursor: 游标对象
        """
        operation, table_name = parse_sql(sql)

        if operation and self._should_audit(table_name):
            return self._execute_with_audit(sql, parameters, operation, table_name)

        # 非审计操作，直接执行
        return self._conn.execute(sql, _convert_parameters(parameters))

    def executemany(
        self,
        sql: str,
        parameters: List[Union[tuple, dict]]
    ) -> sqlite3.Cursor:
        """
        批量执行 SQL，自动记录审计日志

        参数:
            sql: SQL 语句
            parameters: SQL 参数列表

        返回:
            sqlite3.Cursor: 游标对象
        """
        operation, table_name = parse_sql(sql)

        if operation and self._should_audit(table_name):
            # 批量执行并记录审计
            cursor = self._conn.cursor()
            for params in parameters:
                self._execute_with_audit(sql, params, operation, table_name)
            return cursor

        # 非审计操作，直接执行
        return self._conn.executemany(sql, parameters)

    def _execute_with_audit(
        self,
        sql: str,
        parameters: Union[tuple, dict, list],
        operation: str,
        table_name: str
    ) -> sqlite3.Cursor:
        """执行 SQL 并记录审计日志"""
        params = _convert_parameters(parameters)

        # 获取变更前数据
        before_data: Optional[Dict[str, Any]] = None
        row_id: Optional[str] = None

        if operation == "UPDATE":
            before_data = self._fetch_before_data(sql, params, table_name)
            row_id = self._extract_row_id_from_where(sql, params, before_data)
        elif operation == "DELETE":
            before_data = self._fetch_before_data(sql, params, table_name)
            row_id = self._extract_row_id_from_where(sql, params, before_data)

        # 执行业务 SQL
        cursor = self._conn.execute(sql, params)

        # 获取变更后数据
        after_data: Optional[Dict[str, Any]] = None

        if operation == "INSERT":
            row_id = str(cursor.lastrowid) if cursor.lastrowid else None
            after_data = self._fetch_after_data(table_name, row_id)
        elif operation == "UPDATE":
            after_data = self._fetch_after_data(table_name, row_id)

        # 写入审计日志
        self._write_audit_log(
            table=table_name,
            operation=operation,
            row_id=row_id,
            before_data=before_data,
            after_data=after_data
        )

        return cursor

    def _fetch_before_data(
        self,
        sql: str,
        params: tuple,
        table_name: str
    ) -> Optional[Dict[str, Any]]:
        """获取变更前的数据快照"""
        try:
            # 构建 SELECT 查询获取变更前的数据
            # 简单处理：从原始 SQL 提取 WHERE 条件
            where_clause = self._extract_where_clause(sql)
            if not where_clause:
                return None

            select_sql = f"SELECT * FROM {table_name} WHERE {where_clause} LIMIT 1"
            cursor = self._conn.execute(select_sql, params)
            row = cursor.fetchone()

            if row:
                return _row_to_dict(row, cursor)
            return None
        except Exception as e:
            logger.warning(
                "fetch_before_data_failed",
                table=table_name,
                error=str(e)
            )
            return None

    def _fetch_after_data(
        self,
        table_name: str,
        row_id: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """获取变更后的数据快照"""
        if row_id is None:
            return None

        try:
            # 使用 ROWID 查询
            cursor = self._conn.execute(
                f"SELECT * FROM {table_name} WHERE ROWID = ?",
                (row_id,)
            )
            row = cursor.fetchone()

            if row:
                return _row_to_dict(row, cursor)
            return None
        except Exception as e:
            logger.warning(
                "fetch_after_data_failed",
                table=table_name,
                row_id=row_id,
                error=str(e)
            )
            return None

    def _extract_where_clause(self, sql: str) -> Optional[str]:
        """从 SQL 中提取 WHERE 子句"""
        sql_upper = sql.upper()
        where_idx = sql_upper.find("WHERE")
        if where_idx == -1:
            return None

        # 提取 WHERE 后的内容（直到 ORDER BY, GROUP BY, LIMIT 等）
        where_part = sql[where_idx + 5:]  # +5 for "WHERE"

        for keyword in [" ORDER BY", " GROUP BY", " LIMIT", " OFFSET"]:
            kw_idx = where_part.upper().find(keyword)
            if kw_idx != -1:
                where_part = where_part[:kw_idx]
                break

        return where_part.strip()

    def _extract_row_id_from_where(
        self,
        sql: str,
        params: tuple,
        before_data: Optional[Dict[str, Any]]
    ) -> Optional[str]:
        """从 WHERE 条件或 before_data 中提取行 ID"""
        if before_data and "ROWID" in before_data:
            return str(before_data["ROWID"])

        try:
            # 尝试从 SQL 中提取 id = ? 的值
            where_clause = self._extract_where_clause(sql)
            if where_clause and "ROWID" in where_clause.upper():
                # 简单提取 ROWID = ? 的参数
                parts = where_clause.upper().split("ROWID")
                if len(parts) >= 2 and "=" in parts[1]:
                    # 参数位置匹配
                    return str(params[0]) if params else None
        except Exception:
            pass

        return None

    def _write_audit_log(
        self,
        table: str,
        operation: str,
        row_id: Optional[str],
        before_data: Optional[Dict[str, Any]],
        after_data: Optional[Dict[str, Any]]
    ) -> None:
        """写入审计日志"""
        try:
            self._conn.execute(f"""
                INSERT INTO {self._audit_table}
                    (table_name, operation, row_id, before_data, after_data)
                VALUES (?, ?, ?, ?, ?)
            """, (
                table,
                operation,
                row_id,
                json.dumps(before_data) if before_data else None,
                json.dumps(after_data) if after_data else None
            ))
        except Exception as e:
            logger.error(
                "write_audit_log_failed",
                table=table,
                operation=operation,
                error=str(e)
            )
            raise

    # ========================================================================
    # 委托给底层连接的方法
    # ========================================================================

    def commit(self) -> None:
        """提交事务"""
        self._conn.commit()

    def rollback(self) -> None:
        """回滚事务"""
        self._conn.rollback()

    def close(self) -> None:
        """关闭连接"""
        self._conn.close()

    def cursor(self) -> sqlite3.Cursor:
        """获取游标"""
        return self._conn.cursor()

    def executescript(self, sql: str) -> sqlite3.Cursor:
        """执行脚本"""
        return self._conn.executescript(sql)

    @contextmanager
    def transaction(self):
        """事务上下文管理器"""
        try:
            yield self
            self.commit()
        except Exception:
            self.rollback()
            raise

    def __enter__(self) -> "CDCConnection":
        """上下文管理器入口"""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """上下文管理器退出"""
        if exc_type is None:
            self.commit()
        else:
            self.rollback()


def _convert_parameters(params: Union[tuple, dict, list]) -> tuple:
    """转换参数为 sqlite3 可接受的格式"""
    if isinstance(params, (list, tuple)):
        return tuple(params)
    elif isinstance(params, dict):
        return tuple(params.values())
    return ()
