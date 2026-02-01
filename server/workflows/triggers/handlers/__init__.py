"""Trigger handlers package.
All handlers are auto-registered via the @register_handler decorator.
Import this package to ensure all handlers are registered.
"""
from workflows.triggers.handlers.base import TriggerHandler
from workflows.triggers.handlers.manual import ManualHandler
__all__ = [
 "TriggerHandler",
 "ManualHandler",
]
