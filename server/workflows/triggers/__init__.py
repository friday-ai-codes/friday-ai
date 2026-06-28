"""Trigger infrastructure for workflow execution.

Provides unified trigger handling with:
- TriggerContext: Unified context for all trigger sources
- TriggerDispatcher: Central dispatcher for all trigger sources
- TriggerHandlerRegistry: Handler registration and lookup
- TriggerHandler: Abstract base class for trigger handlers
- register_handler: Decorator for auto-registration
"""

from workflows.triggers.context import TriggerContext
from workflows.triggers.dispatcher import TriggerDispatcher
from workflows.triggers.handlers import TriggerHandler
from workflows.triggers.registry import TriggerHandlerRegistry, register_handler
from workflows.triggers.result import (
    await_execution_result,
    build_tool_result,
    deliver_callback_result,
    project_output,
)

__all__ = [
    "TriggerContext",
    "TriggerDispatcher",
    "TriggerHandler",
    "TriggerHandlerRegistry",
    "register_handler",
    "project_output",
    "build_tool_result",
    "await_execution_result",
    "deliver_callback_result",
]
