"""
日志配置模块 - 使用 structlog 提供结构化日志
"""

import logging
import sys
from typing import Any, Mapping

import structlog
from structlog.types import EventDict, WrappedLogger


def _add_timestamp(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """添加 ISO 格式时间戳"""
    from datetime import datetime, timezone

    event_dict["timestamp"] = datetime.now(timezone.utc).isoformat()
    return event_dict


def _add_log_level(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """添加日志级别"""
    event_dict["level"] = method_name
    return event_dict


def _format_exception(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """格式化异常信息"""
    exc_info = event_dict.pop("exc_info", None)
    if exc_info:
        if isinstance(exc_info, BaseException):
            event_dict["exception"] = f"{type(exc_info).__name__}: {exc_info}"
        elif exc_info is True:
            import traceback

            event_dict["exception"] = traceback.format_exc()
    return event_dict


def configure_logging(
    log_level: str = "INFO",
    json_format: bool = False,
) -> None:
    """
    配置结构化日志

    参数:
        log_level: 日志级别 (DEBUG, INFO, WARNING, ERROR)
        json_format: 是否使用 JSON 格式输出（生产环境推荐）
    """
    # 配置标准库 logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper()),
    )

    # 配置 structlog 处理器
    if json_format:
        # JSON 格式（用于生产环境）
        processors: list[Any] = [
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            _format_exception,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ]
    else:
        # 控制台格式（用于开发环境）
        processors = [
            structlog.contextvars.merge_contextvars,
            _add_timestamp,
            _add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            _format_exception,
            structlog.dev.ConsoleRenderer(
                colors=True,
                sort_keys=False,
                pad_level=False,
            ),
        ]

    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> Any:
    """
    获取结构化日志记录器

    参数:
        name: 日志记录器名称，通常为 __name__

    返回:
        BoundLogger: 结构化日志记录器

    示例:
        >>> from sqlite_cdc.utils.logging import get_logger
        >>> logger = get_logger(__name__)
        >>> logger.info("sync_started", table="users")
        2024-01-01T10:30:00 [info] sync_started table=users
    """
    return structlog.get_logger(name)


def set_log_level(level: str) -> None:
    """
    动态设置日志级别

    参数:
        level: 新的日志级别 (DEBUG, INFO, WARNING, ERROR)
    """
    logging.getLogger().setLevel(getattr(logging, level.upper()))


# 默认日志字段绑定
def bind_context(**kwargs: Any) -> None:
    """
    绑定全局上下文字段到所有日志记录

    示例:
        >>> bind_context(sync_id="sync-001", target="mysql_prod")
        >>> logger.info("event_processed")  # 自动包含 sync_id 和 target
    """
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """清除全局上下文字段"""
    structlog.contextvars.clear_contextvars()
