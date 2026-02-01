"""Base node class and related data structures."""
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar, TypedDict
import jsonschema
if TYPE_CHECKING:
 from workflows.models import NodeExecution, WorkflowExecution
class GlobalVariable(TypedDict, total=False):
 """全局变量结构"""
 key: str # 变量标识符
 name: str # 显示名称
 desc: str # 描述（选填）
 value: Any # 变量值
 required: bool # 是否必填
 source_node: str # 来源节点 ID
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
 # 触发器数据
 trigger_data: dict = field(default_factory=dict)
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
 def get_previous_output(self, node_id: str, key: str | None = None, default: Any = None) -> Any:
 """获取上游节点输出"""
 output = self.previous_outputs.get(node_id, {})
 if key:
 return output.get(key, default)
 return output
 def get_trigger_data(self, key: str, default: Any = None) -> Any:
 """获取触发器数据
 Args:
 key: 数据键，支持点分隔路径如 "payload.work_item_id"
 default: 默认值
 Returns:
 触发器数据值
 """
 parts = key.split(".")
 current = self.trigger_data
 for part in parts:
 if isinstance(current, dict):
 current = current.get(part)
 else:
 return default
 if current is None:
 return default
 return current
 def get_global_param(self, key: str, default: Any = None) -> Any:
 """获取全局参数
 从 workflow_context 的 global_params 中读取，
 或者从 workflow_execution.global_params 中读取。
 Args:
 key: 参数键
 default: 默认值
 Returns:
 参数值
 """
 # 优先从 workflow_execution 读取（最新值）
 if self.workflow_execution:
 return self.workflow_execution.get_global_param(key, default)
 # 回退到 workflow_context
 global_params = self.workflow_context.get("global_params", {})
 return global_params.get(key, default)
 def set_global_param(self, key: str, value: Any) -> None:
 """设置全局参数
 更新 workflow_execution.global_params 并持久化到数据库。
 Args:
 key: 参数键
 value: 参数值
 """
 if self.workflow_execution:
 self.workflow_execution.set_global_param(key, value)
 # 同时更新本地 context 以便后续节点读取
 if "global_params" not in self.workflow_context:
 self.workflow_context["global_params"] = {}
 self.workflow_context["global_params"][key] = value
 def update_global_params(self, data: dict) -> None:
 """批量更新全局参数
 Args:
 data: 要更新的参数字典
 """
 if self.workflow_execution:
 self.workflow_execution.update_global_params(data)
 # 同时更新本地 context
 if "global_params" not in self.workflow_context:
 self.workflow_context["global_params"] = {}
 self.workflow_context["global_params"].update(data)
 # ===== 全局变量管理（带元数据） =====
 def set_global_variable(
 self,
 key: str,
 name: str,
 value: Any,
 desc: str = "",
 required: bool = False,
 ) -> None:
 """设置全局变量（带元数据）
 Args:
 key: 变量标识符，用于在模板中引用
 name: 显示名称
 value: 变量值
 desc: 描述信息
 required: 是否必填
 """
 variable: GlobalVariable = {
 "key": key,
 "name": name,
 "value": value,
 "desc": desc,
 "required": required,
 "source_node": self.node_id,
 }
 # 存储到 workflow_execution.context['global_variables']
 if self.workflow_execution:
 self.workflow_execution.set_global_variable(key, variable)
 # 同时更新本地 context
 if "global_variables" not in self.workflow_context:
 self.workflow_context["global_variables"] = {}
 self.workflow_context["global_variables"][key] = variable
 # 同时更新 global_params 以保持向后兼容
 self.set_global_param(key, value)
 def get_global_variable(self, key: str) -> GlobalVariable | None:
 """获取全局变量（含元数据）
 Args:
 key: 变量标识符
 Returns:
 GlobalVariable 或 None
 """
 if self.workflow_execution:
 return self.workflow_execution.get_global_variable(key)
 global_vars = self.workflow_context.get("global_variables", {})
 return global_vars.get(key)
 def get_global_variable_value(self, key: str, default: Any = None) -> Any:
 """获取全局变量的值
 Args:
 key: 变量标识符
 default: 默认值
 Returns:
 变量值
 """
 var = self.get_global_variable(key)
 if var is not None:
 return var.get("value", default)
 # 回退到 global_params
 return self.get_global_param(key, default)
 def get_all_global_variables(self) -> dict[str, GlobalVariable]:
 """获取所有全局变量
 Returns:
 {key: GlobalVariable} 字典
 """
 if self.workflow_execution:
 return self.workflow_execution.get_all_global_variables
 return self.workflow_context.get("global_variables", {})
 def render_template(self, template: str) -> str:
 """渲染模板字符串，支持变量替换
 支持格式：
 - {{$.key}} - 输入数据简写（等同于 input.key）
 - {{input.key}} - 输入数据
 - {{context.key}} - 工作流上下文
 - {{config.key}} - 节点配置
 - {{nodes.node_id.key}} - 上游节点输出
 - {{global.key}} - 全局参数
 - {{trigger.key}} - 触发器数据
 """
 def replace(match: re.Match) -> str:
 path = match.group(1).strip
 # 处理 $ 简写语法：$.key 或 $key 等同于 input.key
 if path.startswith("$."):
 # {{$.repositories}} -> input.repositories
 return str(self.get_input(path[2:], ""))
 elif path.startswith("$") and not path.startswith("$"):
 # {{$repositories}} -> input.repositories
 return str(self.get_input(path[1:], ""))
 parts = path.split(".")
 if parts[0] == "$":
 # {{$}} 单独使用表示整个 input 对象
 return str(self.input_data or "")
 elif parts[0] == "input":
 return str(self.get_input(".".join(parts[1:]), ""))
 elif parts[0] == "context":
 return str(self.get_context(".".join(parts[1:]), ""))
 elif parts[0] == "config":
 return str(self.get_config(".".join(parts[1:]), ""))
 elif parts[0] == "nodes" and len(parts) >= 3:
 node_id = parts[1]
 key = ".".join(parts[2:])
 return str(self.get_previous_output(node_id, key, ""))
 elif parts[0] == "global":
 # 优先从全局变量获取值
 var_key = ".".join(parts[1:])
 value = self.get_global_variable_value(var_key, None)
 if value is not None:
 return str(value)
 # 回退到 global_params
 return str(self.get_global_param(var_key, ""))
 elif parts[0] == "trigger":
 return str(self.get_trigger_data(".".join(parts[1:]), ""))
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
 inputs: ClassVar[list[NodePort]] = [NodePort(name="default", label="输入", required=False)]
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
 "required": p.required,
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
