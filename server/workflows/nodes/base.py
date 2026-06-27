"""Base node class and related data structures."""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar, Literal, TypedDict

import jsonschema

if TYPE_CHECKING:
    from workflows.models import NodeExecution, WorkflowExecution


class GlobalVariable(TypedDict, total=False):
    """全局变量结构"""

    key: str  # 变量标识符
    name: str  # 显示名称
    desc: str  # 描述（选填）
    value: Any  # 变量值
    required: bool  # 是否必填
    source_node: str  # 来源节点 ID


class NodeCategory(str, Enum):
    """节点分类"""

    TRIGGER = "trigger"  # 触发器
    ACTION = "action"  # 动作
    CONTROL = "control"  # 控制流
    INTEGRATION = "integration"  # 集成
    AI = "ai"  # AI 相关


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
    # 详细输出结构 (JSON Schema 格式)
    # 用于描述 object/array 类型端口的具体字段
    schema: dict | None = None
    # 能力/内容契约标识（与 port_type 正交）：port_type 描述「数据类型」，
    # shape 描述「能力语义」——能产出/消费同一类内容/能力的端口才可连。
    # 空字符串 = 通配宽松（向后兼容，既有节点/工作流零回归）；取值面向能力，
    # 见 workflows.nodes.shapes.KNOWN_PORT_SHAPES（如 clarification_request /
    # clarification_answer / feishu_message 等，取值可扩展、非闭集）。
    # 带默认值放在末尾，避免既有位置参数构造 TypeError（Pitfall 2）。
    shape: str = ""


@dataclass
class NodeResult:
    """节点执行结果"""

    status: str  # completed, failed, waiting_approval, waiting_input
    output: dict = field(default_factory=dict)
    error: str | None = None
    next_handle: str = "default"  # 用于条件分支，指定走哪个输出


@dataclass
class ExecutionContext:
    """节点执行上下文"""

    execution_id: str
    node_id: str
    node_config: dict
    input_data: dict
    workflow_context: dict  # 全局上下文
    previous_outputs: dict[str, dict]  # 上游节点输出 {node_id: output}

    # 触发器数据
    trigger_data: dict = field(default_factory=dict)

    # 服务注入
    workflow_execution: "WorkflowExecution | None" = None
    node_execution: "NodeExecution | None" = None

    # implementation contract contract：per-node Provider 快照
    #
    # Shape: {node_id: {provider_type: str, model: str, source: str,
    #                   credential_id: str | None}}
    #
    # 由 WorkflowEngine.start_execution 统一写入；AI 节点 runner 优先读。
    # miss 时（历史 Execution 无快照 OR 节点非 AI 类型）fallback 到运行时
    # aresolve + structlog warning log（事件名 snapshot.miss_fallback_to_runtime_resolve）。
    node_snapshots: dict[str, dict] = field(default_factory=dict)

    # RTOOL-03 机会性 PAT：仅当本 Execution 由「带 PAT 的实时请求线程」触发时，
    # 由 start_execution 在触发边界从请求 ContextVar 捕获后写入此瞬态字段。
    # 安全契约：仅内存运行时存在，绝不落库（不进 WorkflowExecution.context）、绝不进日志。
    # 缺省空串 → 下游不注入 env_FRIDAY_TASK_USER_TOKEN（向后兼容降级）。
    user_pat_plaintext: str = ""

    def get_input(self, key: str, default: Any = None) -> Any:
        """获取输入数据

        Args:
            key: 数据键，支持点分隔路径如 "project.id"
            default: 默认值

        Returns:
            输入数据值
        """
        parts = key.split(".")
        current = self.input_data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return default
            if current is None:
                return default
        return current

    def get_config(self, key: str, default: Any = None) -> Any:
        """获取节点配置"""
        return self.node_config.get(key, default)

    def get_context(self, key: str, default: Any = None) -> Any:
        """获取工作流上下文"""
        return self.workflow_context.get(key, default)

    def get_previous_output(self, node_id: str, key: str | None = None, default: Any = None) -> Any:
        """获取上游节点输出

        支持点分嵌套路径（dict 键 + list 数字索引），如 "data.name"、"items.0.name"。

        注意与模板解析路径的语义差异：render_template/get_template_value 对
        nodes.* 引用执行严格语义（解析失败抛 TemplateResolutionError），而本方法
        被节点代码直接调用，路径任一段缺失时返回 default 而不抛异常，
        保持对直接调用方的兼容。
        """
        output = self.previous_outputs.get(node_id, {})
        if not key:
            return output
        # 兼容历史扁平 key：含点号的字面量键优先精确匹配
        if isinstance(output, dict) and key in output:
            return output[key]
        current: Any = output
        for part in key.split("."):
            if isinstance(current, dict):
                if part not in current:
                    return default
                current = current[part]
            elif isinstance(current, list):
                try:
                    current = current[int(part)]
                except (ValueError, IndexError):
                    return default
            else:
                return default
        return current

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

    async def aset_global_param(self, key: str, value: Any) -> None:
        """设置全局参数（async 版本）

        更新 workflow_execution.global_params 并持久化到数据库。

        Args:
            key: 参数键
            value: 参数值
        """
        if self.workflow_execution:
            await self.workflow_execution.aset_global_param(key, value)
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

    async def aset_global_variable(
        self,
        key: str,
        name: str,
        value: Any,
        desc: str = "",
        required: bool = False,
    ) -> None:
        """设置全局变量（async 版本，带元数据）

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
            await self.workflow_execution.aset_global_variable(key, variable)

        # 同时更新本地 context
        if "global_variables" not in self.workflow_context:
            self.workflow_context["global_variables"] = {}
        self.workflow_context["global_variables"][key] = variable

        # 同时更新 global_params 以保持向后兼容
        await self.aset_global_param(key, value)

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
            return self.workflow_execution.get_all_global_variables()
        return self.workflow_context.get("global_variables", {})

    def render_template(self, template: str) -> str:
        """渲染模板字符串，支持变量替换（薄委托 template_resolver 解析核心）

        支持格式：
        - {{$.key}} - 输入数据简写（等同于 input.key）
        - {{$nodes.id.field[*].value}} - JSONPath 表达式（包含 [ 字符）
        - {{input.key}} - 输入数据
        - {{context.key}} - 工作流上下文
        - {{config.key}} - 节点配置
        - {{nodes.node_id.key}} - 上游节点输出（严格语义，解析失败抛
          TemplateResolutionError）
        - {{global.key}} - 全局参数
        - {{trigger.key}} - 触发器数据
        """
        # 延迟导入：避免与 workflows.engine 包初始化形成循环依赖
        from workflows.engine.template_resolver import render_template

        return render_template(template, self._build_resolution_sources(), self._resolve_jsonpath)

    def get_template_value(self, template: str) -> Any:
        """Get template value preserving complex types.

        Unlike render_template() which returns str, this returns
        the actual value for single-variable templates.

        Supports two modes:
        1. Simple path mode: {{input.space.id}}, {{global.repositories}}
        2. JSONPath mode: {{$.input.repositories[*].id}} - starts with $

        Examples:
            "{{global.repositories}}" -> list of dicts
            "{{global.repositories[0]}}" -> single dict
            "{{$.input.repositories[*].id}}" -> ["id1", "id2", ...]
            "prefix_{{global.name}}_suffix" -> str (uses render_template)
        """
        # 延迟导入：避免与 workflows.engine 包初始化形成循环依赖
        from workflows.engine.template_resolver import get_template_value

        return get_template_value(
            template, self._build_resolution_sources(), self._resolve_jsonpath
        )

    def _build_resolution_sources(self) -> Any:
        """构造解析核心所需的数据源集合（ResolutionSources）。"""
        from workflows.engine.template_resolver import ResolutionSources

        return ResolutionSources(
            previous_outputs=self.previous_outputs or {},
            input_data=self.input_data or {},
            workflow_context=self.workflow_context or {},
            node_config=self.node_config or {},
            trigger_data=self.trigger_data or {},
            global_values=self._get_global_values(),
        )

    def _resolve_jsonpath(self, jsonpath_expr: str) -> Any:
        """Resolve JSONPath expression against execution context.

        The JSONPath is evaluated against a virtual document:
        {
            "input": <input_data>,
            "global": <global_params>,
            "nodes": <previous_outputs>,
            "trigger": <trigger_data>,
            "config": <node_config>,
            "context": <workflow_context>
        }

        Examples:
            $.input.repositories[*].id -> extract all repository IDs
            $.input.space.name -> get project name
            $.global.repositories[-1] -> last repository

        Raises:
            ValueError: If referencing a non-existent node ID
        """
        from jsonpath_ng.exceptions import JsonPathParserError
        from jsonpath_ng.ext import parse as jsonpath_parse

        nodes_data = self.previous_outputs or {}

        # Validate node ID reference before JSONPath evaluation
        # Extract node ID from paths like $.nodes.SLT.xxx or $.nodes.SLT[...]
        node_ref_match = re.match(r"^\$\.?nodes\.([^.\[\]]+)", jsonpath_expr)
        if node_ref_match:
            referenced_node_id = node_ref_match.group(1)
            available_node_ids = list(nodes_data.keys())

            if referenced_node_id not in available_node_ids:
                # Check for case-insensitive match to provide helpful error
                case_insensitive_match = None
                for node_id in available_node_ids:
                    if node_id.lower() == referenced_node_id.lower():
                        case_insensitive_match = node_id
                        break

                if case_insensitive_match:
                    raise ValueError(
                        f"节点 ID '{referenced_node_id}' 不存在。"
                        f"你是否想使用 '{case_insensitive_match}'？"
                        f"（节点 ID 区分大小写）"
                    )
                else:
                    raise ValueError(
                        f"节点 ID '{referenced_node_id}' 不存在。"
                        f"可用的节点 ID: {available_node_ids}"
                    )

        # Build virtual document for JSONPath evaluation
        document = {
            "input": self.input_data or {},
            "global": self._get_global_values(),
            "nodes": nodes_data,
            "trigger": self.trigger_data or {},
            "config": self.node_config or {},
            "context": self.workflow_context or {},
        }

        try:
            jsonpath_expr_obj = jsonpath_parse(jsonpath_expr)
            matches = jsonpath_expr_obj.find(document)

            if not matches:
                return ""

            # Single match: return value directly
            if len(matches) == 1:
                return matches[0].value

            # Multiple matches: return list of values
            return [m.value for m in matches]

        except JsonPathParserError as e:
            raise ValueError(f"无效的 JSONPath 表达式: {jsonpath_expr}。错误: {e}")

    def _get_global_values(self) -> dict:
        """Get all global values (from variables and params) as flat dict."""
        result = {}
        # Add global params：模型字段为持久化源（set_global_param/aset_global_param
        # 只写 WorkflowExecution.global_params，不写 context 镜像），execution 从 DB
        # 重载（resume/approve 等路径）后镜像为空，必须兜底模型字段（WR-01 回归修复）；
        # context 镜像随后覆盖，保证同进程内最新写入值优先
        if self.workflow_execution is not None:
            result.update(self.workflow_execution.global_params or {})
        result.update(self.workflow_context.get("global_params", {}))
        # Add global variable values (override params if same key)
        for key, var in self.get_all_global_variables().items():
            if isinstance(var, dict) and "value" in var:
                result[key] = var["value"]
            else:
                result[key] = var
        return result


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
        "required": [],
    }

    # 输入/输出端口
    inputs: ClassVar[list[NodePort]] = [NodePort(name="default", label="输入", required=False)]
    outputs: ClassVar[list[NodePort]] = [NodePort(name="default", label="输出")]

    # 执行模式
    execution_mode: ClassVar[Literal["server_local", "runner_dispatched"]]

    # 执行选项
    requires_container: ClassVar[bool] = False  # 是否需要 Docker 容器
    supports_retry: ClassVar[bool] = True  # 是否支持重试
    is_blocking: ClassVar[bool] = False  # 是否阻塞（如审批节点）

    # 废弃标记：默认非废弃。子类设 True 表示节点已废弃（仅为向后兼容保留注册，
    # 不再从前端节点库暴露给新建工作流）。既有实例仍可经 registry 查找并 execute。
    deprecated: ClassVar[bool] = False

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # 跳过抽象中间类（无 node_type 或有 abstractmethods）
        if not hasattr(cls, "node_type") or getattr(cls, "__abstractmethods__", None):
            return
        if "execution_mode" not in cls.__dict__ and not any(
            "execution_mode" in getattr(base, "__dict__", {})
            for base in cls.__mro__[1:]
            if base is not BaseNode
        ):
            raise TypeError(f"{cls.__name__} 必须声明 execution_mode")

    @classmethod
    def validate_config(cls, config: dict) -> list[str]:
        """验证节点配置"""
        errors = []
        try:
            jsonschema.validate(config, cls.config_schema)
        except jsonschema.ValidationError as e:
            errors.append(str(e.message))
        return errors

    # UI Schema（声明式配置表单描述）
    # 由子类覆盖，或从 node-definitions.json 注入
    ui_schema: ClassVar[dict | None] = None

    @classmethod
    def _get_ui_schema(cls) -> dict | None:
        """获取 ui_schema：优先子类覆盖，其次从 NodeRegistry 注入。"""
        if cls.ui_schema is not None:
            return cls.ui_schema
        # 延迟导入避免循环依赖
        from .registry import NodeRegistry

        return NodeRegistry.get_ui_schema(cls.node_type)

    @classmethod
    def _get_default_config(cls) -> dict:
        """从 config_schema.properties.*.default 收集顶层默认值。

        仅收集含 "default" 的顶层字段；config_schema 为空或无 properties 时返回 {}，
        免去前端 schema.parse({}) 反推默认值（D-01）。
        """
        props = (cls.config_schema or {}).get("properties", {}) or {}
        return {k: v["default"] for k, v in props.items() if isinstance(v, dict) and "default" in v}

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
            "ui_schema": cls._get_ui_schema(),
            "default_config": cls._get_default_config(),
            "inputs": [
                {
                    "name": p.name,
                    "label": p.label,
                    "type": p.port_type.value,
                    "required": p.required,
                    "description": p.description,
                    "schema": p.schema,
                    "shape": p.shape,
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
                    "schema": p.schema,
                    "shape": p.shape,
                }
                for p in cls.outputs
            ],
            "requires_container": cls.requires_container,
            "is_blocking": cls.is_blocking,
            "execution_mode": cls.execution_mode,
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


def normalize_repositories(
    config: dict[str, Any],
    context: ExecutionContext,
) -> list[dict[str, Any]]:
    """Normalize repository configuration to list format.

    Supports:
    - repositories: List[str|dict] - list of IDs or repository objects
    - repository: str|dict - single ID or object (auto-wrapped)
    - repository_ids: List[str] - list of IDs (alias)
    - Template variables: {{global.repositories}}
    - Auto-fallback: if config is empty, check global.repositories

    String formats supported:
    - JSON object array: [{"id": "xxx", ...}, ...] -> extract id from each object
    - JSON string array: ["xxx", "yyy"] or ['xxx', 'yyy']
    - Comma-separated: "id1, id2, id3" -> split and trim

    Per CONTEXT.md:
    - `repositories` takes priority over `repository`
    - Single values silently wrap to list (no log)
    - Returns list of dicts with at least 'id' key

    Args:
        config: Node configuration dict
        context: Execution context for template resolution

    Returns:
        List of repository dicts, each with at least 'id' key
    """
    import json

    # Check plural forms first (take priority per CONTEXT.md)
    value = config.get("repositories") or config.get("repository_ids")
    if value is None:
        # Fallback to singular forms
        value = config.get("repository")

    # Auto-fallback: if config is empty, try global.repositories
    if value is None or (isinstance(value, list) and len(value) == 0):
        global_repos = context.get_global_variable_value("repositories")
        if global_repos:
            value = global_repos

    if value is None:
        return []

    # Handle template variable
    if isinstance(value, str) and "{{" in value:
        resolved = context.get_template_value(value)
        if resolved is not None and resolved != "":
            value = resolved
        # else: Template didn't resolve - treat as literal string (single ID)

    # Normalize to list of dicts
    def to_repo_dict(item: Any) -> dict[str, Any] | None:
        if isinstance(item, str):
            item = item.strip()
            if not item:
                return None
            return {"id": item}
        elif isinstance(item, dict):
            # If dict has 'id' field, use it; otherwise return the dict as-is
            return item
        return None

    def parse_string_value(s: str) -> list[dict[str, Any]]:
        """Parse string value into list of repo dicts.

        Supports:
        1. JSON object array: [{"id": "xxx"}, ...]
        2. JSON string array: ["xxx", "yyy"] or ['xxx', 'yyy']
        3. Comma-separated: "id1, id2, id3"
        """
        s = s.strip()
        if not s:
            return []

        # Try JSON parsing first (handles both object and string arrays)
        if s.startswith("["):
            try:
                # Replace single quotes with double quotes for JSON compatibility
                json_str = s.replace("'", '"')
                parsed = json.loads(json_str)
                if isinstance(parsed, list):
                    result = []
                    for item in parsed:
                        repo_dict = to_repo_dict(item)
                        if repo_dict is not None:
                            result.append(repo_dict)
                    return result
            except json.JSONDecodeError:
                pass  # Fall through to comma-separated parsing

        # Comma-separated string: "id1, id2, id3"
        if "," in s:
            result = []
            for part in s.split(","):
                part = part.strip()
                if part:
                    result.append({"id": part})
            return result

        # Single ID string
        return [{"id": s}]

    if isinstance(value, str):
        return parse_string_value(value)
    elif isinstance(value, dict):
        # Single repository object
        return [value]
    elif isinstance(value, list):
        # Already a list - normalize each item
        result = []
        for item in value:
            repo_dict = to_repo_dict(item)
            if repo_dict is not None:
                result.append(repo_dict)
        return result

    return []
