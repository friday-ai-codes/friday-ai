"""模板变量解析核心（Phase 17 实现契约）。

本模块是 `render_template` / `get_template_value` 两个 API 共享的纯函数解析核心：
不 import Django ORM、不依赖 ExecutionContext，输入全部为 plain dict，
pytest 零 DB 可测。

严格语义定界（VAR-02，OQ#1 定界结论——必须遵守，勿扩大化）：
- ``nodes.*`` 前缀：节点 ID 不存在 / 字段（含嵌套路径）不存在 → 抛
  :class:`TemplateResolutionError`（fail-fast，不再静默空串）。
- 未知前缀（不属于 input/context/config/nodes/global/trigger/$）→ 抛
  :class:`TemplateResolutionError`，不再原样保留 ``{{...}}`` 字面量。
- ``input. / trigger. / global. / context. / config.`` 前缀的字段缺失
  维持现状：返回 None（由上层转空串），不报错。Phase 18（trigger 注入）
  / Phase 20（保存校验）再行收紧。
- JSONPath（``$`` 开头）语法维持现状不动：由调用方传入的 jsonpath_resolver
  回调处理，零匹配时 render 保留字面量（characterization，见 Pitfall 6）。

错误分类（reason 枚举）：
- ``node_not_found``：引用的节点 ID 在 previous_outputs 中不存在
- ``field_not_found``：节点存在但字段路径（含嵌套中途断路）不存在
- ``unknown_prefix``：前缀不在合法前缀列表内
- ``missing_field_path``：``{{nodes.<id>}}`` 缺少字段路径（仅两段）
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# 合法前缀列表（unknown_prefix 错误的 available 候选）
VALID_PREFIXES = ["input", "context", "config", "nodes", "global", "trigger", "$"]

# UUID 形态键的识别正则（available 候选过滤用，只列 short_id 形态）
_UUID_KEY_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-")

# {{...}} 变量占位符
_TEMPLATE_VAR_RE = re.compile(r"\{\{(.+?)\}\}")

# [n] / [-n] 数组索引后缀（get_template_value 现状保留）
_INDEX_SUFFIX_RE = re.compile(r"(.+?)\[(-?\d+)\]$")


class TemplateResolutionError(ValueError):
    """模板解析失败。

    继承 ValueError 保持对既有 ``except ValueError`` 调用方的兼容。

    Attributes:
        template: 完整模板片段（如 "结果: {{nodes.zzz.output}}"）
        reference: 失败的引用路径（如 "nodes.zzz.output"）
        reason: 失败原因分类，取值
            node_not_found | field_not_found | unknown_prefix | missing_field_path
        available: 可用候选（节点 ID 列表 / 字段 keys / 合法前缀），
            只含键名，绝不包含上游输出值（T-17-01 缓解）
    """

    def __init__(
        self,
        *,
        template: str,
        reference: str,
        reason: str,
        available: list[str],
        message: str,
    ):
        super().__init__(message)
        self.template = template
        self.reference = reference
        self.reason = reason
        self.available = available


@dataclass
class ResolutionSources:
    """解析数据源集合（全部为 plain dict，由调用方构造）。

    global_values 由调用方预先展平传入（对应
    ``ExecutionContext._get_global_values()`` 的产物：global_params 与
    全局变量 value 的合并视图）。
    """

    previous_outputs: dict = field(default_factory=dict)
    input_data: dict = field(default_factory=dict)
    workflow_context: dict = field(default_factory=dict)
    node_config: dict = field(default_factory=dict)
    trigger_data: dict = field(default_factory=dict)
    global_values: dict = field(default_factory=dict)


def _dig_lenient(data: Any, parts: list[str]) -> Any:
    """宽松嵌套下钻（input/trigger 现状语义）：任一段缺失返回 None。"""
    current = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
        if current is None:
            return None
    return current


def _node_id_candidates(previous_outputs: dict) -> list[str]:
    """node_not_found 的 available 候选：过滤 UUID 形态键，只列 short_id。

    过滤后为空（previous_outputs 只有 UUID 键）则回退列全部键。
    """
    keys = list(previous_outputs.keys())
    short_ids = [k for k in keys if not _UUID_KEY_RE.match(k)]
    return short_ids or keys


def _resolve_nodes_path(
    parts: list[str],
    sources: ResolutionSources,
    *,
    reference: str,
    template: str,
) -> Any:
    """nodes.* 前缀的严格解析：节点归一化查找 + 嵌套下钻断路即抛。"""
    if len(parts) < 3:
        raise TemplateResolutionError(
            template=template,
            reference=reference,
            reason="missing_field_path",
            available=_node_id_candidates(sources.previous_outputs),
            message=(f"引用 '{reference}' 缺少字段路径，应为 nodes.<节点ID>.<字段路径> 格式。"),
        )

    node_id = parts[1]
    field_parts = parts[2:]
    nodes_data = sources.previous_outputs or {}

    if node_id not in nodes_data:
        available = _node_id_candidates(nodes_data)
        # 大小写近似提示（节点 ID 区分大小写）
        case_match = next(
            (nid for nid in nodes_data if nid.lower() == node_id.lower()),
            None,
        )
        if case_match:
            message = (
                f"节点 ID '{node_id}' 不存在。你是否想使用 '{case_match}'？（节点 ID 区分大小写）"
            )
        else:
            message = f"节点 ID '{node_id}' 不存在。可用的节点 ID: {available}"
        raise TemplateResolutionError(
            template=template,
            reference=reference,
            reason="node_not_found",
            available=available,
            message=message,
        )

    output = nodes_data[node_id]
    field_path = ".".join(field_parts)
    # available 只列该节点输出的顶层字段 keys（绝不含输出值，T-17-01）
    top_level_keys = list(output.keys()) if isinstance(output, dict) else []

    current = output
    for i, part in enumerate(field_parts):
        failed = False
        if isinstance(current, dict):
            if part in current:
                current = current[part]
            else:
                failed = True
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                failed = True
        else:
            failed = True

        if failed:
            traversed = ".".join(field_parts[: i + 1])
            raise TemplateResolutionError(
                template=template,
                reference=reference,
                reason="field_not_found",
                available=top_level_keys,
                message=(
                    f"节点 '{node_id}' 输出中不存在字段 '{field_path}'"
                    f"（解析在 '{traversed}' 处断路）。"
                    f"该节点输出的顶层字段: {top_level_keys}"
                ),
            )
    return current


def resolve_path(
    path: str,
    sources: ResolutionSources,
    *,
    template: str | None = None,
) -> Any:
    """按前缀分发解析单个引用路径。

    - ``nodes.*``：严格语义（不存在即抛 TemplateResolutionError）
    - ``input./trigger.``：嵌套下钻，缺失返回 None（现状）
    - ``context./config./global.``：扁平 key 查找，缺失返回 None（现状）
    - 未知前缀：抛 unknown_prefix

    Args:
        path: 去掉 ``{{ }}`` 的引用路径，如 "nodes.aB1.data.name"
        sources: 解析数据源
        template: 完整模板片段（错误上下文用），缺省取 path 本身
    """
    template = template if template is not None else "{{" + path + "}}"
    parts = path.split(".")
    prefix = parts[0]
    rest = ".".join(parts[1:])

    if prefix == "nodes":
        return _resolve_nodes_path(parts, sources, reference=path, template=template)
    if prefix == "input":
        return _dig_lenient(sources.input_data, parts[1:]) if rest else None
    if prefix == "trigger":
        return _dig_lenient(sources.trigger_data, parts[1:]) if rest else None
    if prefix == "context":
        # 现状：扁平 key 查找（点分余段整体作为 key）
        return sources.workflow_context.get(rest) if rest else None
    if prefix == "config":
        return sources.node_config.get(rest) if rest else None
    if prefix == "global":
        return sources.global_values.get(rest) if rest else None

    raise TemplateResolutionError(
        template=template,
        reference=path,
        reason="unknown_prefix",
        available=list(VALID_PREFIXES),
        message=(
            f"未知的变量前缀 '{prefix}'（引用 '{path}'）。合法前缀: {', '.join(VALID_PREFIXES)}"
        ),
    )


def render_template(
    template: str,
    sources: ResolutionSources,
    jsonpath_resolver: Callable[[str], Any],
) -> str:
    """渲染模板字符串（多变量拼接为 str）。

    支持格式（与原 ExecutionContext.render_template 一致）：
    - ``{{$.key}}`` —— 输入数据简写（等同于 input.key，宽松语义现状保留）
    - ``{{$nodes.id.field[*].value}}`` —— JSONPath 表达式（包含 [ 字符），
      行为现状保留：零匹配/空结果保留字面量
    - ``{{input.key}}`` / ``{{context.key}}`` / ``{{config.key}}`` /
      ``{{global.key}}`` / ``{{trigger.key}}`` —— 字段缺失现状空串
    - ``{{nodes.node_id.key}}`` —— 严格语义（解析失败抛
      TemplateResolutionError）
    """

    def replace(match: re.Match) -> str:
        path = match.group(1).strip()

        # JSONPath 模式：$ 开头且含 [（数组访问/过滤器）——现状原样保留
        if path.startswith("$") and "[" in path:
            jsonpath_expr = path
            if not path.startswith("$."):
                jsonpath_expr = "$." + path[1:]
            result = jsonpath_resolver(jsonpath_expr)
            if isinstance(result, list):
                return "\n".join(str(item) for item in result)
            # 空结果保留字面量（Pitfall 6 characterization，现状锁定）
            return str(result) if result != "" else match.group(0)

        # $ 简写语法：$.key 等同于 input.key（宽松，现状保留）
        if path.startswith("$."):
            value = _dig_lenient(sources.input_data, path[2:].split("."))
            return "" if value is None else str(value)

        parts = path.split(".")

        if parts[0] == "$":
            # {{$}} 单独使用表示整个 input 对象（现状保留）
            return str(sources.input_data or "")

        if path.startswith("$"):
            # 其余 $ 开头形态（如 {{$nodes.x.y}} 不含 [）：现状保留字面量，
            # 归属 JSONPath 家族，不落入 unknown_prefix 严格语义
            return match.group(0)

        value = resolve_path(path, sources, template=template)
        return "" if value is None else str(value)

    return _TEMPLATE_VAR_RE.sub(replace, template)


def get_template_value(
    template: str,
    sources: ResolutionSources,
    jsonpath_resolver: Callable[[str], Any],
) -> Any:
    """获取模板值（单变量保留原始类型）。

    与 render_template 共享同一解析核心，错误语义一致：
    - 单变量 ``{{nodes.aB1.count}}``（int 42）返回 int 42 而非 "42"
    - ``[n]`` / ``[-n]`` 数组索引后缀现状保留（越界返回空串不报错）
    - JSONPath（$ 开头）走 jsonpath_resolver 回调（现状保留）
    - 多变量/混合内容回退到 render_template 字符串渲染
    """
    template = template.strip()

    match = re.fullmatch(r"\{\{(.+?)\}\}", template)
    if not match:
        # 多变量或混合内容——字符串渲染
        return render_template(template, sources, jsonpath_resolver)

    path = match.group(1).strip()

    # JSONPath 模式：$ 开头（现状原样保留）
    if path.startswith("$"):
        return jsonpath_resolver(path)

    # [n] / [-n] 数组索引后缀（现状保留）
    index = None
    index_match = _INDEX_SUFFIX_RE.match(path)
    if index_match:
        path = index_match.group(1)
        index = int(index_match.group(2))

    value = resolve_path(path, sources, template=template)

    if index is not None and isinstance(value, list):
        try:
            value = value[index]
        except IndexError:
            value = None

    # 与现状一致：None 统一转空串
    if value is None:
        return ""

    return value
