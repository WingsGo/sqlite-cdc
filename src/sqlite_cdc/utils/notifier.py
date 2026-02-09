"""
告警通知模块 - 支持多种通知方式
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from sqlite_cdc.utils.logging import get_logger

logger = get_logger(__name__)


class Notifier(ABC):
    """通知器抽象基类"""

    @abstractmethod
    async def notify(self, level: str, title: str, message: str) -> None:
        """
        发送通知

        参数:
            level: 级别 (info/warning/error)
            title: 标题
            message: 消息内容
        """
        raise NotImplementedError


class ConsoleNotifier(Notifier):
    """控制台通知器 - 打印到控制台"""

    def __init__(self, use_colors: bool = True):
        self.use_colors = use_colors

    async def notify(self, level: str, title: str, message: str) -> None:
        """打印到控制台"""
        if self.use_colors:
            colors = {
                "info": "\033[36m",      # 青色
                "warning": "\033[33m",   # 黄色
                "error": "\033[31m",     # 红色
                "reset": "\033[0m"
            }
            color = colors.get(level, colors["reset"])
            reset = colors["reset"]
            print(f"{color}[{level.upper()}] {title}{reset}")
        else:
            print(f"[{level.upper()}] {title}")
        print(f"  {message}")


class WebhookNotifier(Notifier):
    """Webhook 通知器 - HTTP 回调"""

    def __init__(self, webhook_url: str, headers: Optional[Dict[str, str]] = None):
        self.webhook_url = webhook_url
        self.headers = headers or {}

    async def notify(self, level: str, title: str, message: str) -> None:
        """发送 HTTP  webhook"""
        try:
            import aiohttp

            payload = {
                "level": level,
                "title": title,
                "message": message,
                "source": "sqlite-cdc"
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json=payload,
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status >= 400:
                        logger.warning(
                            "webhook_notification_failed",
                            status=response.status
                        )
        except Exception as e:
            logger.error("webhook_notification_error", error=str(e))


class NotifierManager:
    """通知管理器 - 管理多个通知渠道"""

    def __init__(self):
        self._notifiers: list[Notifier] = []

    def add_notifier(self, notifier: Notifier) -> None:
        """添加通知器"""
        self._notifiers.append(notifier)

    def remove_notifier(self, notifier: Notifier) -> None:
        """移除通知器"""
        if notifier in self._notifiers:
            self._notifiers.remove(notifier)

    async def notify(self, level: str, title: str, message: str) -> None:
        """
        发送通知到所有渠道

        参数:
            level: 级别 (info/warning/error)
            title: 标题
            message: 消息内容
        """
        for notifier in self._notifiers:
            try:
                await notifier.notify(level, title, message)
            except Exception as e:
                logger.error(
                    "notification_failed",
                    notifier_type=type(notifier).__name__,
                    error=str(e)
                )

    async def info(self, title: str, message: str) -> None:
        """发送信息级别通知"""
        await self.notify("info", title, message)

    async def warning(self, title: str, message: str) -> None:
        """发送警告级别通知"""
        await self.notify("warning", title, message)

    async def error(self, title: str, message: str) -> None:
        """发送错误级别通知"""
        await self.notify("error", title, message)


# 全局通知管理器实例
_global_notifier_manager: Optional[NotifierManager] = None


def get_notifier_manager() -> NotifierManager:
    """获取全局通知管理器"""
    global _global_notifier_manager
    if _global_notifier_manager is None:
        _global_notifier_manager = NotifierManager()
        # 默认添加控制台通知器
        _global_notifier_manager.add_notifier(ConsoleNotifier())
    return _global_notifier_manager


def configure_notifier(webhook_url: Optional[str] = None) -> None:
    """
    配置通知器

    参数:
        webhook_url: Webhook URL（可选）
    """
    manager = get_notifier_manager()

    if webhook_url:
        manager.add_notifier(WebhookNotifier(webhook_url))
