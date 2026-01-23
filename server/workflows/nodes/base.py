"""Base node class and related data structures."""
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar
import jsonschema
if TYPE_CHECKING:
 from workflows.models import NodeExecution, WorkflowExecution
class NodeCategory(str, Enum):
 """节点分类"""
 TRIGGER = "trigger" # 触发器
 ACTION = "action" # 动作
 CONTROL = "control" # 控制流
 INTEGRATION = "integration" # 集成
 AI = "ai" # AI 相关
class PortType(str, Enum):
 """端口数据类型"""
 ANY = "any"
 STRING = "string"
 NUMBER = "number"
 BOOLEAN = "boolean"
 OBJECT = "object"
 ARRAY = "array"
 FILE = "file"
@dataclass
class NodePort:
 """节点端口定义"""
 name: str
 label: str
 port_type: PortType = PortType.ANY
 required: bool = True
 default: Any = None
 description: str = ""
@dataclass
class NodeResult:
 """节点执行结果"""
 status: str # completed, failed, waiting_approval, waiting_input
 output: dict = field(default_factory=dict)
 error: str | None = None
 next_handle: str = "default" # 用于条件分支，指定走哪个输出
@dataclass
class ExecutionContext:
 """节点执行上下文"""
 execution_id: str
 node_id: str
 node_config: dict
 input_data: dict
 workflow_context: dict # 全局上下文
 previous_outputs: dict[str, dict] # 上游节点输出 {node_id: output}
 # 服务注入
 workflow_execution: "WorkflowExecution | None" = None
 node_execution: "NodeExecution | None" = None
 def get_input(self, key: str, default: Any = None) -> Any:
 """获取输入数据"""
 return self.input_data.get(key, default)
 def get_config(self, key: str, default: Any = None) -> Any:
 """获取节点配置"""
 return self.node_config.get(key, default)
 def get_context(self, key: str, default: Any = None) -> Any:
 """获取工作流上下文"""
 return self.workflow_context.get(key, default)
 def get_previous_output(
 self, node_id: str, key: str | None = None, default: Any = None
 ) -> Any:
 """获取上游节点输出"""
 output = self.previous_outputs.get(node_id, {})
 if key:
 return output.get(key, default)
 return output
 def render_template(self, template: str) -> str:
 """渲染模板字符串，支持变量替换
 支持格式：
 - {{input.key}} - 输入数据
 - {{context.key}} - 工作流上下文
 - {{config.key}} - 节点配置
 - {{nodes.node_id.key}} - 上游节点输出
 """
 def replace(match: re.Match) -> str:
 path = match.group(1).strip
 parts = path.split(".")
 if parts[0] == "input":
 return str(self.get_input(".".join(parts[1:]), ""))
 elif parts[0] == "context":
 return str(self.get_context(".".join(parts[1:]), ""))
 elif parts[0] == "config":
 return str(self.get_config(".".join(parts[1:]), ""))
 elif parts[0] == "nodes" and len(parts) >= 3:
 node_id = parts[1]
 key = ".".join(parts[2:])
 return str(self.get_previous_output(node_id, key, ""))
 return match.group(0) # 无法解析则保持原样
 return re.sub(r"\{\{(.+?)\}\}", replace, template)
class BaseNode(ABC):
 """节点基类
 所有节点类型必须继承此类并实现 execute 方法。
 """
 # 节点类型标识（必须唯一）
 node_type: ClassVar[str]
 # 显示信息
 display_name: ClassVar[str]
 description: ClassVar[str] = ""
 icon: ClassVar[str] = "box"
 # 分类
 category: ClassVar[NodeCategory]
 # 配置 Schema（JSON Schema 格式）
 config_schema: ClassVar[dict] = {
 "type": "object",
 "properties": {},
 "required":,
 }
 # 输入/输出端口
 inputs: ClassVar[list[NodePort]] = [
 NodePort(name="default", label="输入", required=False)
 ]
 outputs: ClassVar[list[NodePort]] = [NodePort(name="default", label="输出")]
 # 执行选项
 requires_container: ClassVar[bool] = False # 是否需要 Docker 容器
 supports_retry: ClassVar[bool] = True # 是否支持重试
 is_blocking: ClassVar[bool] = False # 是否阻塞（如审批节点）
 @classmethod
 def validate_config(cls, config: dict) -> list[str]:
 """验证节点配置"""
 errors =
 try:
 jsonschema.validate(config, cls.config_schema)
 except jsonschema.ValidationError as e:
 errors.append(str(e.message))
 return errors
 @classmethod
 def get_schema(cls) -> dict:
 """获取完整的节点 Schema（用于前端）"""
 return {
 "node_type": cls.node_type,
 "display_name": cls.display_name,
 "description": cls.description,
 "icon": cls.icon,
 "category": cls.category.value,
 "config_schema": cls.config_schema,
 "inputs": [
 {
 "name": p.name,
 "label": p.label,
 "type": p.port_type.value,
 "required": p.required,
 "description": p.description,
 }
 for p in cls.inputs
 ],
 "outputs": [
 {
 "name": p.name,
 "label": p.label,
 "type": p.port_type.value,
 "description": p.description,
 }
 for p in cls.outputs
 ],
 "requires_container": cls.requires_container,
 "is_blocking": cls.is_blocking,
 }
 @abstractmethod
 async def execute(self, context: ExecutionContext) -> NodeResult:
 """执行节点
 Args:
 context: 执行上下文
 Returns:
 NodeResult: 执行结果
 """
 pass
 async def on_cancel(self, context: ExecutionContext) -> None:
 """取消执行时的清理操作"""
 pass
 async def on_timeout(self, context: ExecutionContext) -> None:
 """超时时的清理操作"""
 pass
