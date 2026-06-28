"""Trigger handlers package.

All handlers are auto-registered via the @register_handler decorator.
Import this package to ensure all handlers are registered.
"""

from workflows.triggers.handlers.base import TriggerHandler
from workflows.triggers.handlers.feishu import FeishuEventHandler
from workflows.triggers.handlers.manual import ManualHandler
from workflows.triggers.handlers.tool_invoke import ToolInvokeHandler
from workflows.triggers.handlers.webhook import WebhookHandler

__all__ = [
    "TriggerHandler",
    "ManualHandler",
    "WebhookHandler",
    "FeishuEventHandler",
    "ToolInvokeHandler",
]
