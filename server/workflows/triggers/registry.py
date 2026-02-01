"""Trigger handler registry with decorator registration."""
from typing import TYPE_CHECKING, Type
import structlog
if TYPE_CHECKING:
 from workflows.triggers.handlers.base import TriggerHandler
logger = structlog.get_logger
class TriggerHandlerRegistry:
 """触发处理器注册表（单例模式）
 管理所有触发处理器的注册和查找。
 遵循 NodeRegistry 的设计模式。
 """
 _instance = None
 _handlers: dict[str, Type["TriggerHandler"]] = {}
 def __new__(cls):
 if cls._instance is None:
 cls._instance = super.__new__(cls)
 return cls._instance
 @classmethod
 def register(cls, handler_class: Type["TriggerHandler"]) -> None:
 """注册处理器类
 Args:
 handler_class: 处理器类，必须有 trigger_type 属性
 Raises:
 ValueError: 处理器类缺少 trigger_type 属性
 """
 if not hasattr(handler_class, "trigger_type"):
 raise ValueError(f"处理器类 {handler_class.__name__} 缺少 trigger_type 属性")
 trigger_type = handler_class.trigger_type
 if trigger_type in cls._handlers:
 logger.warning(
 "handler_already_registered",
 trigger_type=trigger_type,
 existing=cls._handlers[trigger_type].__name__,
 new=handler_class.__name__,
 )
 cls._handlers[trigger_type] = handler_class
 logger.debug("handler_registered", trigger_type=trigger_type)
 @classmethod
 def get(cls, trigger_type: str) -> Type["TriggerHandler"] | None:
 """根据触发类型获取处理器类
 Args:
 trigger_type: 触发类型标识
 Returns:
 处理器类，未找到返回 None
 """
 return cls._handlers.get(trigger_type)
 @classmethod
 def get_all(cls) -> dict[str, Type["TriggerHandler"]]:
 """获取所有已注册的处理器
 Returns:
 处理器字典的副本 {trigger_type: handler_class}
 """
 return cls._handlers.copy
def register_handler(cls: Type["TriggerHandler"]) -> Type["TriggerHandler"]:
 """处理器注册装饰器
 用法：
 @register_handler
 class FeishuHandler(TriggerHandler):
 trigger_type = "feishu"
 ...
 Args:
 cls: 处理器类
 Returns:
 原处理器类（不做修改）
 """
 TriggerHandlerRegistry.register(cls)
 return cls
