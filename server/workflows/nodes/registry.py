"""Node type registry with auto-discovery."""
import importlib
import pkgutil
from typing import Type
import structlog
from .base import BaseNode
logger = structlog.get_logger
class NodeRegistry:
 """节点类型注册表
 使用单例模式，自动发现并注册所有节点类型。
 """
 _instance = None
 _nodes: dict[str, Type[BaseNode]] = {}
 _initialized = False
 def __new__(cls):
 if cls._instance is None:
 cls._instance = super.__new__(cls)
 return cls._instance
 @classmethod
 def register(cls, node_class: Type[BaseNode]) -> None:
 """手动注册节点类型"""
 if not hasattr(node_class, "node_type"):
 raise ValueError(f"节点类 {node_class.__name__} 缺少 node_type 属性")
 node_type = node_class.node_type
 if node_type in cls._nodes:
 logger.warning(
 "node_type_already_registered",
 node_type=node_type,
 existing=cls._nodes[node_type].__name__,
 new=node_class.__name__,
 )
 cls._nodes[node_type] = node_class
 logger.debug("node_type_registered", node_type=node_type)
 @classmethod
 def get(cls, node_type: str) -> Type[BaseNode] | None:
 """获取节点类型"""
 cls._ensure_initialized
 return cls._nodes.get(node_type)
 @classmethod
 def get_all(cls) -> dict[str, Type[BaseNode]]:
 """获取所有注册的节点类型"""
 cls._ensure_initialized
 return cls._nodes.copy
 @classmethod
 def get_by_category(cls, category: str) -> list[Type[BaseNode]]:
 """按分类获取节点类型"""
 cls._ensure_initialized
 return [node for node in cls._nodes.values if node.category.value == category]
 @classmethod
 def get_all_schemas(cls) -> list[dict]:
 """获取所有节点的 Schema（用于前端）"""
 cls._ensure_initialized
 return [node.get_schema for node in cls._nodes.values]
 @classmethod
 def _ensure_initialized(cls) -> None:
 """确保已初始化（自动发现节点）"""
 if cls._initialized:
 return
 cls._auto_discover
 cls._initialized = True
 @classmethod
 def _auto_discover(cls) -> None:
 """自动发现并注册节点类型
 扫描 workflows.nodes 下的所有模块，找到 BaseNode 的子类。
 """
 import workflows.nodes as nodes_package
 # 遍历 nodes 包下的所有子模块
 for importer, modname, ispkg in pkgutil.walk_packages(
 nodes_package.__path__,
 prefix=nodes_package.__name__ + ".",
 ):
 try:
 module = importlib.import_module(modname)
 # 查找模块中所有 BaseNode 的子类
 for attr_name in dir(module):
 attr = getattr(module, attr_name)
 if (
 isinstance(attr, type)
 and issubclass(attr, BaseNode)
 and attr is not BaseNode
 and hasattr(attr, "node_type")
 ):
 cls.register(attr)
 except Exception as e:
 logger.error(
 "node_discovery_error",
 module=modname,
 error=str(e),
 )
# 装饰器，用于注册节点
def register_node(cls: Type[BaseNode]) -> Type[BaseNode]:
 """节点注册装饰器
 用法：
 @register_node
 class MyNode(BaseNode):
 node_type = "my_node"
 ...
 """
 NodeRegistry.register(cls)
 return cls
