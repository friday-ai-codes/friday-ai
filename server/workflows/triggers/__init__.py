"""Trigger infrastructure for workflow execution.
Provides unified trigger handling with:
- TriggerContext: Unified context for all trigger sources
- TriggerHandlerRegistry: Handler registration and lookup
- TriggerHandler: Abstract base class for trigger handlers
- register_handler: Decorator for auto-registration
"""
from workflows.triggers.context import TriggerContext
from workflows.triggers.handlers import TriggerHandler
from workflows.triggers.registry import TriggerHandlerRegistry, register_handler
__all__ = [
 "TriggerContext",
 "TriggerHandler",
 "TriggerHandlerRegistry",
 "register_handler",
]
