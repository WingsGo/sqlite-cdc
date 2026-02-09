"""
SQL 解析工具 - 提取操作类型和表名
"""

import re
from typing import Optional, Tuple

import sqlparse
from sqlparse.sql import Function, Identifier, IdentifierList, Token
from sqlparse.tokens import Keyword, Name, Token as TokenType


def parse_operation(sql: str) -> Optional[str]:
    """
    解析 SQL 语句的操作类型

    参数:
        sql: SQL 语句

    返回:
        操作类型 (INSERT/UPDATE/DELETE) 或 None

    示例:
        >>> parse_operation("INSERT INTO users VALUES (1, 'test')")
        'INSERT'
        >>> parse_operation("SELECT * FROM users")
        None
    """
    sql_upper = sql.strip().upper()

    if sql_upper.startswith("INSERT"):
        return "INSERT"
    elif sql_upper.startswith("UPDATE"):
        return "UPDATE"
    elif sql_upper.startswith("DELETE"):
        return "DELETE"

    return None


def extract_table_name(sql: str) -> Optional[str]:
    """
    从 SQL 语句中提取表名

    支持:
        - INSERT INTO table_name ...
        - UPDATE table_name SET ...
        - DELETE FROM table_name ...

    参数:
        sql: SQL 语句

    返回:
        表名或 None

    示例:
        >>> extract_table_name("INSERT INTO users VALUES (1)")
        'users'
        >>> extract_table_name("UPDATE orders SET status='done'")
        'orders'
    """
    operation = parse_operation(sql)
    if operation is None:
        return None

    # 尝试使用 sqlparse 解析
    try:
        parsed = sqlparse.parse(sql)
        if not parsed:
            return None

        stmt = parsed[0]
        tokens = [t for t in stmt.tokens if not t.is_whitespace]

        if operation == "INSERT":
            return _extract_from_insert(tokens)
        elif operation == "UPDATE":
            return _extract_from_update(tokens)
        elif operation == "DELETE":
            return _extract_from_delete(tokens)

    except Exception:
        # 回退到正则解析
        return _extract_with_regex(sql, operation)

    return None


def _extract_from_insert(tokens: list[Token]) -> Optional[str]:
    """从 INSERT 语句提取表名"""
    # INSERT INTO table_name ...
    found_into = False
    for token in tokens:
        if token.is_whitespace:
            continue
        if not found_into:
            if token.value.upper() == "INTO":
                found_into = True
            continue

        # INTO 后的第一个非空白 token 应该是表名
        # sqlparse 可能将 "users (id)" 解析为 Function 类型
        if isinstance(token, (Identifier, Function)):
            # 获取 token 的字符串表示，取括号前的部分
            raw = str(token)
            if '(' in raw:
                raw = raw.split('(')[0].strip()
            return raw.strip('"\'`')
        else:
            return str(token.value).strip('"\'`')
    return None


def _extract_from_update(tokens: list[Token]) -> Optional[str]:
    """从 UPDATE 语句提取表名"""
    # UPDATE table_name SET ...
    found_update = False
    for token in tokens:
        if token.is_whitespace:
            continue
        if not found_update:
            if token.value.upper() == "UPDATE":
                found_update = True
            continue

        # UPDATE 后的第一个非空白 token 应该是表名
        if isinstance(token, Identifier):
            name = token.get_real_name()
            return str(name) if name else None
        else:
            return str(token.value).strip('"\'`')
    return None


def _extract_from_delete(tokens: list[Token]) -> Optional[str]:
    """从 DELETE 语句提取表名"""
    # DELETE FROM table_name ...
    found_from = False
    for token in tokens:
        if token.is_whitespace:
            continue
        if not found_from:
            if token.ttype is Keyword and token.value.upper() == "FROM":
                found_from = True
            continue

        # 找到 FROM 后的第一个标识符
        if isinstance(token, Identifier):
            name = token.get_real_name()
            return str(name) if name else None
        elif token.ttype in (Name, Keyword):
            return str(token.value).strip('"\'`')
        break

    return None


def _extract_with_regex(sql: str, operation: str) -> Optional[str]:
    """使用正则表达式回退提取表名"""
    sql_clean = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)  # 移除注释

    if operation == "INSERT":
        # INSERT INTO [table]
        match = re.search(
            r"INSERT\s+INTO\s+[`\"\']?(\w+)[`\"\']?",
            sql_clean,
            re.IGNORECASE
        )
    elif operation == "UPDATE":
        # UPDATE [table] SET
        match = re.search(
            r"UPDATE\s+[`\"\']?(\w+)[`\"\']?",
            sql_clean,
            re.IGNORECASE
        )
    elif operation == "DELETE":
        # DELETE FROM [table] 或 DELETE [table] FROM
        match = re.search(
            r"DELETE\s+(?:FROM\s+)?[`\"\']?(\w+)[`\"\']?",
            sql_clean,
            re.IGNORECASE
        )
    else:
        return None

    return match.group(1) if match else None


def parse_sql(sql: str) -> Tuple[Optional[str], Optional[str]]:
    """
    解析 SQL 语句，返回 (operation, table_name)

    参数:
        sql: SQL 语句

    返回:
        (操作类型, 表名) 元组

    示例:
        >>> parse_sql("INSERT INTO users (name) VALUES ('test')")
        ('INSERT', 'users')
        >>> parse_sql("SELECT * FROM users")
        (None, None)
    """
    operation = parse_operation(sql)
    if operation is None:
        return None, None

    table_name = extract_table_name(sql)
    return operation, table_name


def is_write_operation(sql: str) -> bool:
    """
    判断是否为写操作

    参数:
        sql: SQL 语句

    返回:
        是否为 INSERT/UPDATE/DELETE
    """
    return parse_operation(sql) is not None


def normalize_sql(sql: str) -> str:
    """
    规范化 SQL 语句（移除多余空白、统一大小写关键字）

    参数:
        sql: 原始 SQL

    返回:
        规范化后的 SQL
    """
    # 使用 sqlparse 格式化
    formatted = sqlparse.format(
        sql,
        keyword_case="upper",
        identifier_case="lower",
        strip_comments=True,
        strip_whitespace=True
    )
    return formatted.strip()
