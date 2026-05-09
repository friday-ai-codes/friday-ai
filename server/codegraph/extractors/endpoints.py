"""Endpoint 抽取器 —— Django/DRF API 端点三层扫描（per ）。
三层扫描：
 Layer 1: 装饰器函数视图（@api_view / @action / @method_decorator）
 Layer 2: URL patterns（path / re_path / url）- 仅 urls.py 文件
 Layer 3: ViewSet + Router 注册 - 仅 urls.py 文件
per: 系统能从 Django/DRF 项目中提取 API 端点映射。
per: 仅处理 Django/DRF，不处理 FastAPI/Flask。
"""
from typing import Any
import structlog
logger = structlog.get_logger(__name__)
def extract_endpoints(
 tree: Any, source: str, ctx: "FileContext"
) -> "list[EndpointData]":
 """三层扫描提取 Django/DRF API 端点。
 Layer 1: 装饰器函数视图（@api_view / @action / @method_decorator）
 Layer 2: URL patterns（path / re_path / url）
 Layer 3: ViewSet + Router 注册
 Args:
 tree: tree-sitter Tree 对象
 source: 源文件完整文本（用于解析 decorator 参数）
 ctx: FileContext
 Returns:
 list[EndpointData]: 去重后的端点列表
 """
 from codegraph.extractors.base import EndpointData
 endpoints: list[EndpointData] =
 # Layer 1: decorator scan（所有 .py 文件）
 endpoints.extend(_scan_decorators(tree, source, ctx))
 # Layer 2 + 3: URL patterns + ViewSet/Router（仅 urls.py 文件）
 if ctx.file_path.lower.endswith("urls.py"):
 endpoints.extend(_scan_url_patterns(tree, source, ctx))
 endpoints.extend(_scan_viewset_routers(tree, source, ctx))
 # 去重: (http_method, url_path, handler_name, file_path)
 seen: set[tuple[str, str, str, str]] = set
 deduped: list[EndpointData] =
 for ep in endpoints:
 key = (ep.http_method, ep.url_path or "", ep.handler_name, ep.file_path)
 if key not in seen:
 seen.add(key)
 deduped.append(ep)
 return deduped
# =============================================================================
# Layer 1: 装饰器函数视图扫描
# =============================================================================
def _scan_decorators(
 tree: Any, source: str, ctx: "FileContext"
) -> "list[EndpointData]":
 """扫描 @api_view / @action / @method_decorator 装饰器函数。
 per 验证维度 1。
 """
 from codegraph.extractors.base import EndpointData
 from codegraph.extractors.walker import walk_tree
 endpoints: list[EndpointData] =
 for wn in walk_tree(tree, ctx.language):
 node = wn.node
 if node.type != "decorated_definition":
 continue
 # 找到内部函数定义
 inner_func = None
 for child in node.children:
 if child.type == "function_definition":
 inner_func = child
 break
 if inner_func is None:
 continue
 # 获取函数名
 func_name_node = inner_func.child_by_field_name("name")
 if func_name_node is None:
 continue
 handler_name = func_name_node.text
 if isinstance(handler_name, bytes):
 handler_name = handler_name.decode("utf-8")
 # 遍历装饰器
 for child in node.children:
 if child.type != "decorator":
 continue
 # 装饰器节点内含 call 子节点（如 @api_view(["GET"]) 中 api_view(["GET"]) 是 call）
 call_node = None
 for dec_child in child.children:
 if dec_child.type == "call":
 call_node = dec_child
 break
 if call_node is None:
 continue
 dec_func = call_node.child_by_field_name("function")
 if dec_func is None:
 continue
 dec_name = dec_func.text
 if isinstance(dec_name, bytes):
 dec_name = dec_name.decode("utf-8")
 if dec_name == "api_view":
 methods = _parse_decorator_methods(call_node)
 view_type = "FUNCTION_VIEW"
 for method in methods:
 endpoints.append(
 EndpointData(
 http_method=method,
 url_path=None,
 handler_name=handler_name,
 view_type=view_type,
 file_path=ctx.file_path,
 line_number=node.start_point[0] + 1,
 )
 )
 elif dec_name == "action":
 methods = _parse_decorator_methods(call_node)
 url_path = _parse_action_url_path(call_node)
 view_type = "VIEWSET"
 for method in methods:
 endpoints.append(
 EndpointData(
 http_method=method,
 url_path=url_path,
 handler_name=handler_name,
 view_type=view_type,
 file_path=ctx.file_path,
 line_number=node.start_point[0] + 1,
 )
 )
 elif dec_name == "method_decorator":
 # 简化处理：不解析具体 methods
 pass
 return endpoints
def _parse_decorator_methods(decorator_node: Any) -> list[str]:
 """从装饰器节点解析 HTTP methods 列表。
 支持 @api_view(["GET", "POST"]) 和 @action(methods=["post"]) 两种形式。
 解析失败时返回 ["*"] 并记录 warning。
 """
 args_node = decorator_node.child_by_field_name("arguments")
 if args_node is None:
 return ["*"]
 # 查找列表/元组中的字符串（@api_view(["GET"]) 的第一个参数）
 for child in args_node.named_children:
 if child.type in ("list", "tuple"):
 methods: list[str] =
 for item in child.named_children:
 if item.type == "string":
 text = _extract_string_value(item)
 if text:
 methods.append(text.upper)
 if methods:
 return methods
 # 查找 keyword_argument name="methods"（@action(methods=["post"])）
 for child in args_node.named_children:
 if child.type == "keyword_argument":
 kw_name_node = child.child_by_field_name("name")
 if kw_name_node is not None:
 kw_name = kw_name_node.text
 if isinstance(kw_name, bytes):
 kw_name = kw_name.decode("utf-8")
 if kw_name == "methods":
 kw_value = child.child_by_field_name("value")
 if kw_value is not None and kw_value.type in ("list", "tuple"):
 methods: list[str] =
 for item in kw_value.named_children:
 if item.type == "string":
 text = _extract_string_value(item)
 if text:
 methods.append(text.upper)
 if methods:
 return methods
 # 全部失败 → 默认 "*"
 logger.warning(
 "decorator_methods_parse_failed",
 decorator_text=_safe_text(decorator_node),
 )
 return ["*"]
def _parse_action_url_path(decorator_node: Any) -> str | None:
 """从 @action 装饰器解析 url_path 关键字参数。"""
 args_node = decorator_node.child_by_field_name("arguments")
 if args_node is None:
 return None
 for child in args_node.named_children:
 if child.type == "keyword_argument":
 kw_name_node = child.child_by_field_name("name")
 if kw_name_node is not None:
 kw_name = kw_name_node.text
 if isinstance(kw_name, bytes):
 kw_name = kw_name.decode("utf-8")
 if kw_name == "url_path":
 kw_value = child.child_by_field_name("value")
 if kw_value is not None:
 text = _extract_string_value(kw_value)
 if text:
 return text
 return None
# =============================================================================
# Layer 2: URL patterns 扫描
# =============================================================================
URL_FUNCTION_NAMES = {"path", "re_path", "url"}
def _scan_url_patterns(
 tree: Any, source: str, ctx: "FileContext"
) -> "list[EndpointData]":
 """扫描 path / re_path / url 调用，提取 URL 模式。
 仅在 file_path 以 urls.py 结尾时调用。
 """
 from codegraph.extractors.base import EndpointData
 from codegraph.extractors.walker import walk_tree
 endpoints: list[EndpointData] =
 for wn in walk_tree(tree, ctx.language):
 node = wn.node
 if node.type != "call":
 continue
 func_node = node.child_by_field_name("function")
 if func_node is None:
 continue
 # 仅处理 identifier 类型的 path/re_path/url 调用
 if func_node.type != "identifier":
 continue
 func_name = func_node.text
 if isinstance(func_name, bytes):
 func_name = func_name.decode("utf-8")
 if func_name not in URL_FUNCTION_NAMES:
 continue
 # 跳过 include 调用
 if func_name == "include":
 continue
 args_node = node.child_by_field_name("arguments")
 if args_node is None:
 continue
 named_args = args_node.named_children
 if len(named_args) < 2:
 continue
 # 第一个参数：URL 路径
 url_path = _extract_string_value(named_args[0])
 if url_path is None:
 continue
 # URL 路径标准化：去除首尾空格，确保以 / 开头
 url_path = url_path.strip
 if not url_path.startswith("/") and not url_path.startswith("^"):
 url_path = "/" + url_path
 # 第二个参数：视图引用
 view_ref = named_args[1]
 handler_name, view_type, extra_methods = _resolve_view_ref(view_ref)
 if handler_name is None:
 continue
 if extra_methods:
 # as_view({"get": "list", ...}) → 为每个 method 生成一个 EndpointData
 for method in extra_methods:
 endpoints.append(
 EndpointData(
 http_method=method.upper,
 url_path=url_path,
 handler_name=handler_name,
 view_type=view_type,
 file_path=ctx.file_path,
 line_number=node.start_point[0] + 1,
 )
 )
 else:
 # 普通视图引用 → http_method 暂填 "*"
 endpoints.append(
 EndpointData(
 http_method="*",
 url_path=url_path,
 handler_name=handler_name,
 view_type=view_type,
 file_path=ctx.file_path,
 line_number=node.start_point[0] + 1,
 )
 )
 return endpoints
def _resolve_view_ref(
 view_node: Any,
) -> "tuple[str | None, str, list[str]]":
 """解析视图引用，返回 (handler_name, view_type, extra_methods)。
 - identifier: views.user_detail → handler_name="views.user_detail"
 - attribute: views.UserViewSet.as_view → handler_name="views.UserViewSet", view_type="CLASS_VIEW"
 """
 handler_name: str | None = None
 view_type: str = "FUNCTION_VIEW"
 extra_methods: list[str] =
 if view_node.type == "identifier":
 name = view_node.text
 if isinstance(name, bytes):
 name = name.decode("utf-8")
 handler_name = name
 elif view_node.type == "attribute":
 # views.UserViewSet.as_view 或 views.UserViewSet.as_view
 obj_node = view_node.child_by_field_name("object")
 attr_node = view_node.child_by_field_name("attribute")
 if obj_node is not None:
 obj_name = obj_node.text
 if isinstance(obj_name, bytes):
 obj_name = obj_name.decode("utf-8")
 handler_name = obj_name
 view_type = "CLASS_VIEW"
 # 检查 attribute 是否为 call (as_view({"get": "list"}))
 if attr_node is not None:
 attr_name = attr_node.text
 if isinstance(attr_name, bytes):
 attr_name = attr_name.decode("utf-8")
 elif view_node.type == "call":
 # views.UserViewSet.as_view({"get": "list"})
 func_in_call = view_node.child_by_field_name("function")
 if func_in_call is not None and func_in_call.type == "attribute":
 obj_node = func_in_call.child_by_field_name("object")
 if obj_node is not None:
 obj_name = obj_node.text
 if isinstance(obj_name, bytes):
 obj_name = obj_name.decode("utf-8")
 handler_name = obj_name
 view_type = "VIEWSET"
 # 解析 as_view 的 dict 参数 → methods mapping
 call_args = view_node.child_by_field_name("arguments")
 if call_args is not None:
 for arg in call_args.named_children:
 if arg.type == "dictionary":
 extra_methods = _parse_dict_methods(arg)
 return handler_name, view_type, extra_methods
def _parse_dict_methods(dict_node: Any) -> list[str]:
 """解析字典中的 method → action 映射，返回 method 列表。"""
 methods: list[str] =
 for pair in dict_node.named_children:
 if pair.type == "pair":
 key_node = pair.child_by_field_name("key")
 if key_node is not None:
 key_text = _extract_string_value(key_node)
 if key_text:
 methods.append(key_text)
 return methods
# =============================================================================
# Layer 3: ViewSet + Router 注册扫描
# =============================================================================
VIEWSET_BASE_CLASSES = {
 "ViewSet",
 "ModelViewSet",
 "GenericViewSet",
 "ReadOnlyModelViewSet",
}
VIEWSET_DEFAULT_ACTIONS: dict[str, list[tuple[str, str, str]]] = {
 "ModelViewSet": [
 ("list", "GET", ""),
 ("create", "POST", ""),
 ("retrieve", "GET", "{pk}/"),
 ("update", "PUT", "{pk}/"),
 ("partial_update", "PATCH", "{pk}/"),
 ("destroy", "DELETE", "{pk}/"),
 ],
 "ReadOnlyModelViewSet": [
 ("list", "GET", ""),
 ("retrieve", "GET", "{pk}/"),
 ],
 # ViewSet / GenericViewSet: 无默认 actions
}
def _scan_viewset_routers(
 tree: Any, source: str, ctx: "FileContext"
) -> "list[EndpointData]":
 """扫描 ViewSet 类定义 + Router.register 注册。
 Layer 3: 仅在 urls.py 文件中调用。
 """
 from codegraph.extractors.base import EndpointData
 from codegraph.extractors.walker import walk_tree
 endpoints: list[EndpointData] =
 # ---- Pass 1: 收集 ViewSet 类定义 + @action 装饰器 ----
 viewsets: dict[str, dict] = {} # class_name -> {file_path, actions}
 for wn in walk_tree(tree, ctx.language):
 node = wn.node
 if node.type != "class_definition":
 continue
 # 检查父类是否包含 ViewSet
 parent_classes = _get_parent_class_names(node)
 viewset_type = None
 for pc in parent_classes:
 if pc in VIEWSET_BASE_CLASSES:
 viewset_type = pc
 break
 if viewset_type is None:
 continue
 # 获取类名
 name_node = node.child_by_field_name("name")
 if name_node is None:
 continue
 class_name = name_node.text
 if isinstance(class_name, bytes):
 class_name = class_name.decode("utf-8")
 # 收集 ViewSet 信息
 viewsets[class_name] = {
 "file_path": ctx.file_path,
 "viewset_type": viewset_type,
 "actions":, # list of (action_name, http_method, url_suffix)
 }
 # ---- Pass 2: 扫描 router.register 调用 ----
 # 在 urls.py 中寻找 router.register(prefix, ViewSetClass, ...)
 for wn in walk_tree(tree, ctx.language):
 node = wn.node
 if node.type != "call":
 continue
 func_node = node.child_by_field_name("function")
 if func_node is None or func_node.type != "attribute":
 continue
 attr_node = func_node.child_by_field_name("attribute")
 if attr_node is None:
 continue
 attr_name = attr_node.text
 if isinstance(attr_name, bytes):
 attr_name = attr_name.decode("utf-8")
 if attr_name != "register":
 continue
 # 获取参数
 args_node = node.child_by_field_name("arguments")
 if args_node is None:
 continue
 named_args = args_node.named_children
 if len(named_args) < 2:
 continue
 # 第一个参数：prefix
 prefix = _extract_string_value(named_args[0])
 if prefix is None:
 continue
 # 标准化 prefix：去除首尾引号和 /
 prefix = prefix.strip.strip("'\"").strip("/")
 # 第二个参数：ViewSet 类引用
 viewset_ref = named_args[1]
 viewset_class_name = _resolve_viewset_class_name(viewset_ref)
 if viewset_class_name is None:
 continue
 if viewset_class_name in viewsets:
 vs_info = viewsets[viewset_class_name]
 default_actions = VIEWSET_DEFAULT_ACTIONS.get(vs_info["viewset_type"], )
 else:
 # 跨文件引用：ViewSet 类定义不在当前文件中
 # 使用 ModelViewSet 的默认 actions（最常见的 ViewSet 类型）
 default_actions = VIEWSET_DEFAULT_ACTIONS.get("ModelViewSet", )
 # 生成默认 actions
 for action_name, method, url_suffix in default_actions:
 url_path = f"/{prefix}/{url_suffix}" if url_suffix else f"/{prefix}/"
 endpoints.append(
 EndpointData(
 http_method=method,
 url_path=url_path,
 handler_name=f"{viewset_class_name}.{action_name}",
 view_type="VIEWSET",
 file_path=ctx.file_path,
 line_number=node.start_point[0] + 1,
 )
 )
 return endpoints
def _get_parent_class_names(class_node: Any) -> list[str]:
 """获取类定义的父类名列表。"""
 parent_names: list[str] =
 for child in class_node.children:
 if child.type == "argument_list":
 for arg in child.named_children:
 if arg.type == "identifier":
 name = arg.text
 if isinstance(name, bytes):
 name = name.decode("utf-8")
 parent_names.append(name)
 elif arg.type == "attribute":
 # 如 rest_framework.viewsets.ModelViewSet
 attr = arg.child_by_field_name("attribute")
 if attr is not None:
 name = attr.text
 if isinstance(name, bytes):
 name = name.decode("utf-8")
 parent_names.append(name)
 return parent_names
def _resolve_viewset_class_name(ref_node: Any) -> str | None:
 """从 router.register 的参数解析 ViewSet 类名。"""
 if ref_node.type == "identifier":
 name = ref_node.text
 if isinstance(name, bytes):
 name = name.decode("utf-8")
 return name
 return None
# =============================================================================
# 工具函数
# =============================================================================
def _extract_string_value(node: Any) -> str | None:
 """从 tree-sitter 节点提取字符串字面值。
 支持 string 类型节点，去除首尾引号。
 """
 if node.type == "string":
 text = node.text
 if isinstance(text, bytes):
 text = text.decode("utf-8")
 # 去除引号
 text = text.strip
 if (text.startswith('"') and text.endswith('"')) or \
 (text.startswith("'") and text.endswith("'")):
 return text[1:-1]
 if text.startswith('r"') and text.endswith('"'):
 return text[2:-1]
 if text.startswith("r'") and text.endswith("'"):
 return text[2:-1]
 return text
 return None
def _safe_text(node: Any) -> str:
 """安全获取节点文本（截断）。"""
 try:
 text = node.text
 if isinstance(text, bytes):
 text = text.decode("utf-8")
 return text[:100]
 except Exception:
 return "<unable to decode>"
__all__ = ["extract_endpoints"]
