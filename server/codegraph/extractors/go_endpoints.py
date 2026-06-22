"""Go gin 端点抽取器 —— 宽松识别 <recv>.{GET|POST|...}(...) 路由注册调用。

per work item（legacy spike T10/T11 决策）：
  - 扫描所有 <recv>.{GET|POST|PUT|DELETE|PATCH|HEAD}(...)，不限 recv 类型
  - 第一个 string_literal 为 url；最后一个 selector_expression/identifier 为 handler
  - <recv>.Use(...) 不写入 endpoint 表，直接忽略
  - 提取 ogin.G* 参数验证 middleware 元数据写入 metadata JSON 字段
  - work item（已删）：不实装 Group 嵌套前缀合并

Kratos / grpc-gateway 兼容（2026-06 修正）：
  proto 生成的 ``*_http.pb.go`` 路由注册形如
  ``r.GET("/v1/...", _Xxx_Method0_HTTP_Handler(srv))``，handler 实参是一个
  **函数调用**（call_expression），而非裸标识符/选择器。原实现只接受
  selector_expression/identifier/func_literal，导致这类 handler 全部被判
  ``handler_not_found`` 跳过、endpoint 表为 0。现已让 handler 提取支持
  call_expression：取其被调用函数名（如 ``_Xxx_HTTP_Handler``）作为 handler。
"""

from __future__ import annotations

from typing import Any, Generator

import structlog

from codegraph.extractors.base import EndpointData, FileContext

logger = structlog.get_logger(__name__)

# 支持识别的 HTTP 方法（宽松匹配，不限 recv 类型）
GIN_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"})

# ogin.G* 函数名到参数位置的前缀映射
_OGIN_LOCATION_MAP: dict[str, str] = {
    "path": "path_params",
    "query": "query_params",
    "header": "header_params",
    "body": "body_params",
}


def extract_go_endpoints(
    tree: Any, source: str, ctx: FileContext
) -> list[EndpointData]:
    """扫描 Go 源文件，识别所有 <recv>.{GET|POST|PUT|DELETE|PATCH|HEAD}(...) 路由注册调用。

    Args:
        tree: tree-sitter Tree 对象（Go 语法）
        source: 源文件完整文本
        ctx: FileContext（language="go"）

    Returns:
        list[EndpointData]：去重后的 gin 端点列表
    """
    endpoints: list[EndpointData] = []

    for call_node in _walk_call_expressions(tree.root_node):
        func_node = call_node.child_by_field_name("function")
        if func_node is None or func_node.type != "selector_expression":
            continue

        field_node = func_node.child_by_field_name("field")
        if field_node is None:
            continue

        method = _node_text(field_node)
        if not method:
            continue

        # 忽略 Use() 调用
        if method == "Use":
            continue

        # 只处理标准 HTTP 方法
        if method not in GIN_HTTP_METHODS:
            continue

        args_node = call_node.child_by_field_name("arguments")
        if args_node is None:
            continue

        named_args = args_node.named_children
        if len(named_args) < 2:
            continue

        # 第一个 string literal 为 url
        url_path = _extract_url_path(named_args)
        if url_path is None:
            logger.warning(
                "go_endpoint_url_not_found",
                file_path=ctx.file_path,
                line=call_node.start_point[0] + 1,
            )
            continue

        # 最后一个 selector_expression/identifier 为 handler
        handler_name = _extract_handler_name(named_args)
        if handler_name is None:
            logger.warning(
                "go_endpoint_handler_not_found",
                file_path=ctx.file_path,
                url_path=url_path,
                line=call_node.start_point[0] + 1,
            )
            continue

        # 提取 ogin.G* metadata
        metadata = _extract_ogin_metadata(named_args)

        endpoints.append(
            EndpointData(
                http_method=method,
                url_path=url_path,
                handler_name=handler_name,
                view_type="FUNCTION_VIEW",
                file_path=ctx.file_path,
                line_number=call_node.start_point[0] + 1,
                metadata=metadata,
            )
        )

    # 去重：(method, url_path, handler_name, file_path)
    seen: set[tuple[str, str, str, str]] = set()
    deduped: list[EndpointData] = []
    for ep in endpoints:
        key = (ep.http_method, ep.url_path or "", ep.handler_name, ep.file_path)
        if key not in seen:
            seen.add(key)
            deduped.append(ep)

    return deduped


# =============================================================================
# AST 遍历工具
# =============================================================================


def _walk_call_expressions(node: Any) -> Generator[Any, None, None]:
    """DFS 遍历 AST，yield 所有 call_expression 节点。"""
    if node.type == "call_expression":
        yield node
    for child in node.children:
        yield from _walk_call_expressions(child)


def _node_text(node: Any) -> str:
    """安全获取节点文本（bytes → str）。"""
    text = node.text
    if isinstance(text, bytes):
        return text.decode("utf-8")
    return str(text) if text is not None else ""


# =============================================================================
# URL 路径 + Handler 提取
# =============================================================================


def _extract_url_path(args: list[Any]) -> str | None:
    """从参数列表中提取第一个 string literal 作为 URL 路径。

    Go 字符串类型：
      - interpreted_string_literal："..."
      - raw_string_literal：`...`
    """
    for arg in args:
        result = _extract_go_string(arg)
        if result is not None:
            return result
    return None


def _extract_go_string(node: Any) -> str | None:
    """从 Go string literal 节点提取字符串值（strip 首尾引号/反引号）。"""
    if node.type in ("interpreted_string_literal", "raw_string_literal"):
        text = _node_text(node)
        if len(text) >= 2:
            return text[1:-1]
    return None


def _extract_handler_name(args: list[Any]) -> str | None:
    """从参数列表末尾找 handler 标识。

    优先级（从后向前）：
    1. selector_expression → 完整文本（如 newTopic.GetTopicDetailV2）
    2. identifier → 文本（如 handleFunc）
    3. call_expression → 被调用函数名（Kratos/grpc-gateway 的
       ``_Xxx_HTTP_Handler(srv)``，取 ``_Xxx_HTTP_Handler``）
    4. func_literal → "<anonymous>"
    """
    for arg in reversed(args):
        if arg.type == "selector_expression":
            return _node_text(arg)
        if arg.type == "identifier":
            return _node_text(arg)
        if arg.type == "call_expression":
            # Kratos / grpc-gateway：r.GET("/path", _Xxx_HTTP_Handler(srv))
            # handler 是函数调用，取被调用函数名作为 handler 标识。
            func_node = arg.child_by_field_name("function")
            if func_node is not None:
                handler_text = _node_text(func_node)
                if handler_text:
                    return handler_text
        if arg.type == "func_literal":
            return "<anonymous>"
    return None


# =============================================================================
# ogin.G* metadata 提取
# =============================================================================


def _extract_ogin_metadata(args: list[Any]) -> dict[str, Any] | None:
    """从中间参数（排除第一个 string 和最后一个 handler）提取 ogin.G* 参数验证元数据。

    返回格式：
    {
      "path_params": [{"name": "topicId", "required": true, "type": "string"}],
      "query_params": [{"name": "subjectId", "required": true, "type": "int"}],
      "header_params": [{"name": "client-type", "required": false, "type": "string"}]
    }

    无任何 G* middleware → 返回 None。
    """
    result: dict[str, list[dict[str, Any]]] = {}

    for arg in args:
        if arg.type != "call_expression":
            continue

        func_node = arg.child_by_field_name("function")
        if func_node is None or func_node.type != "selector_expression":
            continue

        field_node = func_node.child_by_field_name("field")
        if field_node is None:
            continue

        func_name = _node_text(field_node)
        parsed = _parse_ogin_func_name(func_name)
        if parsed is None:
            continue

        location_key, required, param_type = parsed

        # 提取参数名（函数的第一个 string_literal 参数）
        call_args_node = arg.child_by_field_name("arguments")
        if call_args_node is None:
            continue

        call_args = call_args_node.named_children
        if not call_args:
            continue

        param_name = _extract_go_string(call_args[0])
        if param_name is None:
            continue

        entry: dict[str, Any] = {
            "name": param_name,
            "required": required,
            "type": param_type,
        }
        result.setdefault(location_key, []).append(entry)

    return result if result else None


def _parse_ogin_func_name(name: str) -> tuple[str, bool, str] | None:
    """解析 ogin.G* 函数名，返回 (location_key, required, type)。

    命名规律：G{Path|Query|Header|Body}{Require|Optional}{String|Int|...}

    示例：
      GPathRequireString  → ("path_params", True, "string")
      GQueryOptionalInt   → ("query_params", False, "int")
      GHeaderOptionalString → ("header_params", False, "string")
    """
    if not name.startswith("G"):
        return None

    rest = name[1:]  # strip leading G

    # 识别 Location
    location_key: str | None = None
    for loc_lower, loc_key in _OGIN_LOCATION_MAP.items():
        loc_cap = loc_lower.capitalize()
        if rest.upper().startswith(loc_cap.upper()):
            location_key = loc_key
            rest = rest[len(loc_cap):]
            break

    if location_key is None:
        return None

    # 识别 Required/Optional
    if rest.upper().startswith("REQUIRE"):
        required = True
        rest = rest[7:]  # len("Require") = 7
    elif rest.upper().startswith("OPTIONAL"):
        required = False
        rest = rest[8:]  # len("Optional") = 8
    else:
        return None

    # 识别 Type（String / Int / 或其他）
    param_type = rest.lower() if rest else "string"

    return location_key, required, param_type


__all__ = ["extract_go_endpoints"]
