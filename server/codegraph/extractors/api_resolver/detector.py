"""Step 0/1/2 检测器 —— 三步推断算法核心实现。
Step 0: 扫描 axios.{METHOD} 调用 → 识别所在 export function 为 LowLevelHelper
Step 1: 找调用 LowLevelHelper 的 export function → ApiWrapper，提取 URL+method
Step 2: volar textDocument/references 反向追踪 ApiWrapper → ApiCallSite
Vue SFC 支持：通过 vue_sfc_splitter 拆 script block 后用 TS parser 解析
"""
from __future__ import annotations
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING, Any
import structlog
from codegraph.extractors.api_resolver.base import ApiCallSiteData, ApiWrapperData
from codegraph.extractors.api_resolver.config import get_api_detector_config, strip_base_url
logger = structlog.get_logger(__name__)
# axios 方法名集合（识别 LowLevelHelper 的锚点）
_AXIOS_METHODS: frozenset[str] = frozenset(
 ["get", "post", "put", "delete", "del", "patch", "request"]
)
# =============================================================================
# 工具函数：tree-sitter AST 遍历
# =============================================================================
def _walk_all(node: Any) -> Generator[Any, None, None]:
 """DFS 遍历 AST 所有节点。"""
 yield node
 for child in node.children:
 yield from _walk_all(child)
def _get_export_func_name(export_node: Any) -> str | None:
 """从 export_statement 提取 export function 名。
 支持：
 - export function foo {}
 - export const foo = => {}
 - export const foo = function {}
 """
 decl = export_node.child_by_field_name("declaration")
 if decl is None:
 return None
 if decl.type == "function_declaration":
 name_node = decl.child_by_field_name("name")
 return name_node.text.decode("utf-8") if name_node else None
 if decl.type in ("lexical_declaration", "variable_declaration"):
 for child in decl.children:
 if child.type == "variable_declarator":
 name_node = child.child_by_field_name("name")
 if name_node:
 return name_node.text.decode("utf-8")
 return None
def _get_export_func_body(export_node: Any) -> Any | None:
 """获取 export function 的函数体节点（statement_block）。"""
 decl = export_node.child_by_field_name("declaration")
 if decl is None:
 return None
 if decl.type == "function_declaration":
 return decl.child_by_field_name("body")
 if decl.type in ("lexical_declaration", "variable_declaration"):
 for child in decl.children:
 if child.type == "variable_declarator":
 value = child.child_by_field_name("value")
 if value is not None:
 if value.type == "arrow_function":
 body = value.child_by_field_name("body")
 return body
 if value.type in ("function", "function_expression"):
 return value.child_by_field_name("body")
 return None
def _get_export_func_start_line(export_node: Any) -> int:
 """获取 export function 起始行（1-indexed）。"""
 decl = export_node.child_by_field_name("declaration")
 if decl:
 return decl.start_point[0] + 1
 return export_node.start_point[0] + 1
def _get_preceding_jsdoc(parent_node: Any, export_index: int) -> str | None:
 """获取 export_statement 紧前方的 JSDoc 注释（/** ... */）。"""
 if export_index <= 0:
 return None
 prev = parent_node.children[export_index - 1]
 if prev.type == "comment":
 text = prev.text.decode("utf-8", errors="replace")
 if text.strip.startswith("/**"):
 return text
 return None
def _extract_string_value(node: Any) -> str | None:
 """从 string / template_string 节点提取字符串值。
 - string/string_literal: 去引号
 - template_string/template_literal: 提取字面量部分（去除 ${...} 模板表达式）
 """
 if node is None:
 return None
 if node.type in ("string", "string_literal"):
 text = node.text.decode("utf-8", errors="replace")
 return text.strip("'\"`")
 if node.type in ("template_string", "template_literal"):
 parts: list[str] =
 for child in node.children:
 if child.type == "string_fragment":
 parts.append(child.text.decode("utf-8", errors="replace"))
 # 跳过 template_substitution（${...} 表达式）和反引号
 raw = "".join(parts)
 return raw if raw else None
 return None
# =============================================================================
# Step 0: axios 锚点 → LowLevelHelper 识别
# =============================================================================
def _has_axios_call(body_node: Any, axios_obj_names: frozenset[str] = frozenset(["axios"])) -> bool:
 """检查函数体内是否有 axios.METHOD(...) 或 http.METHOD(...) 调用。
 识别模式：
 - axios.get(...)
 - axios.post(...)
 - instance.get(...)（axios.create 返回的实例）
 """
 if body_node is None:
 return False
 for node in _walk_all(body_node):
 if node.type != "call_expression":
 continue
 func = node.child_by_field_name("function")
 if func is None or func.type != "member_expression":
 continue
 obj = func.child_by_field_name("object")
 prop = func.child_by_field_name("property")
 if obj is None or prop is None:
 continue
 obj_text = obj.text.decode("utf-8", errors="replace")
 prop_text = prop.text.decode("utf-8", errors="replace")
 if any(name in obj_text for name in axios_obj_names) and prop_text in _AXIOS_METHODS:
 return True
 return False
def discover_low_level_helpers(
 tree: Any,
 source: str,
 file_path: str,
 config: dict[str, Any],
) -> list[str]:
 """Step 0: 扫描文件，找调用 axios.METHOD 的 export function 为 LowLevelHelper。
 Args:
 tree: tree-sitter 解析树
 source: 源文件文本
 file_path: 文件路径（用于日志）
 config: API_DETECTOR_CONFIG 合并后的 dict
 Returns:
 LowLevelHelper 函数名列表（per ）
 """
 helpers: list[str] =
 root = tree.root_node
 axios_obj_names: frozenset[str] = frozenset(["axios"])
 for child in root.children:
 if child.type != "export_statement":
 continue
 func_name = _get_export_func_name(child)
 if func_name is None:
 continue
 body = _get_export_func_body(child)
 if _has_axios_call(body, axios_obj_names):
 helpers.append(func_name)
 logger.debug(
 "low_level_helper_found",
 file_path=file_path,
 func_name=func_name,
 )
 # 追加 force_helpers（按 file_path 匹配）
 for fh in config.get("force_helpers", ):
 if not isinstance(fh, dict):
 continue
 fh_file: str = fh.get("file_path", "")
 fh_func: str = fh.get("func_name", "")
 if not fh_file or not fh_func:
 continue
 if fh_file in file_path or file_path.endswith(fh_file):
 if fh_func not in helpers:
 helpers.append(fh_func)
 logger.debug(
 "low_level_helper_force_added",
 file_path=file_path,
 func_name=fh_func,
 )
 return helpers
# =============================================================================
# Step 1: LowLevelHelper → ApiWrapper 识别
# =============================================================================
def _find_helper_calls(
 body_node: Any, helper_names: set[str]
) -> list[tuple[str, Any]]:
 """在函数体内找调用 helper_names 中函数的 call_expression。
 识别模式：
 - 直接调用：get(url, params)
 - 成员调用：api.get(url)（成员调用的 property 在 helper_names 中）
 Returns:
 list of (helper_name, call_expression_node)
 """
 results: list[tuple[str, Any]] =
 if body_node is None:
 return results
 for node in _walk_all(body_node):
 if node.type != "call_expression":
 continue
 func = node.child_by_field_name("function")
 if func is None:
 continue
 if func.type == "identifier":
 name = func.text.decode("utf-8", errors="replace")
 if name in helper_names:
 results.append((name, node))
 elif func.type == "member_expression":
 prop = func.child_by_field_name("property")
 if prop:
 prop_name = prop.text.decode("utf-8", errors="replace")
 if prop_name in helper_names:
 results.append((prop_name, node))
 return results
def _extract_first_string_arg(call_node: Any) -> str | None:
 """从 call_expression 的 arguments 中提取第一个字符串参数（URL）。"""
 args = call_node.child_by_field_name("arguments")
 if args is None:
 return None
 for child in args.children:
 if child.type in ("string", "string_literal", "template_string", "template_literal"):
 return _extract_string_value(child)
 # type_arguments 泛型参数跳过（TypeScript call_expression<T>）
 return None
def discover_api_wrappers(
 tree: Any,
 source: str,
 file_path: str,
 helper_names: set[str],
 config: dict[str, Any],
) -> list[ApiWrapperData]:
 """Step 1: 找调用 LowLevelHelper 的 export function → ApiWrapper。
 提取：
 - function_symbol: export function 名
 - http_method: helper name → HTTP method（per config.helper_method_map）
 - url_path_raw: 第一个字符串参数（原始 URL，含模板变量）
 - url_path_pattern: strip_base_url 后的路径
 - _jsdoc_text: 紧前方 JSDoc 注释（Plan JSDoc 富集消费）
 Args:
 tree: tree-sitter 解析树
 source: 源文件文本
 file_path: 文件路径
 helper_names: Step 0 识别的 LowLevelHelper 名集合
 config: 合并后的 config dict
 Returns:
 ApiWrapperData 列表（per ）
 """
 if not helper_names:
 return
 helper_method_map: dict[str, str] = config.get("helper_method_map", {})
 exclude_set: set[str] = set(config.get("exclude_helpers", ))
 active_helpers = helper_names - exclude_set
 wrappers: list[ApiWrapperData] =
 root = tree.root_node
 for idx, child in enumerate(root.children):
 if child.type != "export_statement":
 continue
 func_name = _get_export_func_name(child)
 if func_name is None:
 continue
 body = _get_export_func_body(child)
 helper_calls = _find_helper_calls(body, active_helpers)
 if not helper_calls:
 continue
 # 取第一个 helper 调用（ApiWrapper 通常只有一个 HTTP call）
 helper_name, call_node = helper_calls[0]
 url_raw = _extract_first_string_arg(call_node)
 if url_raw is None:
 logger.debug(
 "api_wrapper_no_url",
 file_path=file_path,
 func_name=func_name,
 helper_name=helper_name,
 )
 continue
 http_method = helper_method_map.get(helper_name, "GET")
 url_pattern = strip_base_url(url_raw, config)
 start_line = _get_export_func_start_line(child)
 jsdoc_text = _get_preceding_jsdoc(root, idx)
 wrappers.append(
 ApiWrapperData(
 file_path=file_path,
 function_symbol=func_name,
 http_method=http_method,
 url_path_raw=url_raw,
 url_path_pattern=url_pattern,
 detected_via="axios_anchor",
 line_number=start_line,
 metadata=None,
 _jsdoc_text=jsdoc_text,
 )
 )
 logger.debug(
 "api_wrapper_detected",
 file_path=file_path,
 func_name=func_name,
 http_method=http_method,
 url_pattern=url_pattern,
 )
 logger.info(
 "api_resolver_step1_file_complete",
 file_path=file_path,
 wrapper_count=len(wrappers),
 )
 return wrappers
# =============================================================================
# 文件解析工具
# =============================================================================
def parse_ts_or_vue_for_api(file_path: str) -> tuple[Any, str] | None:
 """解析 TS/.tsx 或 Vue SFC 文件，返回 (tree, source) 或 None。
 Vue SFC：通过 vue_sfc_splitter 拆 script block，再用 TS parser 解析。
 TS/TSX：直接 TS parser 解析。
 Args:
 file_path: 文件绝对或相对路径
 Returns:
 (tree, source_text) 或 None（不支持的文件 / 解析失败）
 """
 fp = Path(file_path)
 if not fp.exists:
 return None
 if fp.suffix == ".vue":
 return _parse_vue_file(file_path)
 if fp.suffix in (".ts", ".tsx", ".js", ".jsx"):
 return _parse_ts_file(file_path)
 return None
def _parse_ts_file(file_path: str) -> tuple[Any, str] | None:
 """解析 TS/TSX/JS/JSX 文件。
 tree-sitter-typescript 暴露 language_typescript（TS）和 language_tsx（TSX）两个函数。
 对 .js/.jsx 文件使用 tree_sitter_javascript.language。
 """
 try:
 from tree_sitter import Language, Parser
 with open(file_path, encoding="utf-8", errors="ignore") as f:
 source = f.read
 fp = Path(file_path)
 if fp.suffix in (".ts",):
 import tree_sitter_typescript as ts_ts
 lang_obj = Language(ts_ts.language_typescript)
 elif fp.suffix in (".tsx",):
 import tree_sitter_typescript as ts_ts
 lang_obj = Language(ts_ts.language_tsx)
 else:
 # .js / .jsx
 import tree_sitter_javascript as ts_js # type: ignore[import-untyped]
 lang_obj = Language(ts_js.language)
 parser = Parser(lang_obj)
 tree = parser.parse(source.encode("utf-8"))
 return tree, source
 except Exception as e:
 logger.warning(
 "api_resolver_ts_parse_failed", file_path=file_path, error=str(e)
 )
 return None
def _parse_vue_file(file_path: str) -> tuple[Any, str] | None:
 """解析 Vue SFC：拆 script block → TS parser。
 split_sfc 返回 list[SfcBlock]，遍历找 kind="script" 的块提取 content。
 """
 try:
 from codegraph.extractors.vue_sfc_splitter import split_sfc
 with open(file_path, encoding="utf-8", errors="ignore") as f:
 sfc_source = f.read
 blocks = split_sfc(sfc_source)
 # list[SfcBlock]：找 kind="script" 的块（普通 script 或 setup）
 script_src = ""
 for block in blocks:
 if block.kind == "script" and block.content.strip:
 script_src = block.content
 break
 if not script_src.strip:
 return None
 import tree_sitter_typescript as ts_ts
 from tree_sitter import Language, Parser
 TS_LANGUAGE = Language(ts_ts.language_typescript)
 parser = Parser(TS_LANGUAGE)
 tree = parser.parse(script_src.encode("utf-8"))
 return tree, script_src
 except Exception as e:
 logger.warning(
 "api_resolver_vue_parse_failed", file_path=file_path, error=str(e)
 )
 return None
# =============================================================================
# 顶层入口：全仓库扫描 Step 0+1
# =============================================================================
def resolve_wrappers_for_repository(
 file_paths: list[str],
 repo_root: str,
 config: dict[str, Any] | None = None,
) -> list[ApiWrapperData]:
 """对仓库所有 TS/Vue 文件执行 Step 0+1，返回全部 ApiWrapperData。
 两阶段：
 - Phase A（Step 0）：全扫描识别 LowLevelHelper（每个文件独立）
 - Phase B（Step 1）：基于 Phase A 的 helper_names 全扫描识别 ApiWrapper
 Args:
 file_paths: TS/Vue 文件路径列表
 repo_root: 仓库根路径（用于 config.yaml 读取）
 config: 已合并的 config dict（None 时自动加载）
 Returns:
 ApiWrapperData 列表（已完成 JSDoc 富集）
 """
 if config is None:
 config = get_api_detector_config(repo_root)
 # -------------------------------------------------------------------------
 # Phase A: 发现 LowLevelHelper（Step 0）
 # -------------------------------------------------------------------------
 all_helper_names: set[str] = set
 helper_file_count = 0
 for fp in file_paths:
 parsed = parse_ts_or_vue_for_api(fp)
 if parsed is None:
 continue
 tree, source = parsed
 helpers = discover_low_level_helpers(tree, source, fp, config)
 if helpers:
 all_helper_names.update(helpers)
 helper_file_count += 1
 logger.info(
 "api_resolver_step0_complete",
 helper_count=len(all_helper_names),
 helper_files=helper_file_count,
 helper_names=sorted(all_helper_names),
 )
 if not all_helper_names:
 logger.warning("api_resolver_no_helpers_found", repo_root=repo_root)
 return
 # -------------------------------------------------------------------------
 # Phase B: 发现 ApiWrapper（Step 1）
 # -------------------------------------------------------------------------
 all_wrappers: list[ApiWrapperData] =
 for fp in file_paths:
 parsed = parse_ts_or_vue_for_api(fp)
 if parsed is None:
 continue
 tree, source = parsed
 wrappers = discover_api_wrappers(tree, source, fp, all_helper_names, config)
 all_wrappers.extend(wrappers)
 logger.info(
 "api_resolver_step1_complete",
 wrapper_count=len(all_wrappers),
 repo_root=repo_root,
 )
 # JSDoc 富集（，Plan enrich_wrapper_metadata 调用）
 from codegraph.extractors.api_resolver.jsdoc_parser import enrich_wrapper_metadata
 all_wrappers = enrich_wrapper_metadata(all_wrappers)
 return all_wrappers
# =============================================================================
# Step 2: volar references → ApiCallSite
# =============================================================================
def _find_symbol_position(
 tree: Any, func_name: str
) -> tuple[int, int] | None:
 """在 AST 中定位 export function 的函数名标识符位置（0-indexed line, col）。
 用于向 volar 发 textDocument/references 请求。
 Returns:
 (line, col) 0-indexed 或 None（未找到）
 """
 root = tree.root_node
 for child in root.children:
 if child.type != "export_statement":
 continue
 decl = child.child_by_field_name("declaration")
 if decl is None:
 continue
 if decl.type == "function_declaration":
 name_node = decl.child_by_field_name("name")
 if name_node and name_node.text.decode("utf-8") == func_name:
 return (name_node.start_point[0], name_node.start_point[1])
 elif decl.type in ("lexical_declaration", "variable_declaration"):
 for grandchild in decl.children:
 if grandchild.type == "variable_declarator":
 name_node = grandchild.child_by_field_name("name")
 if name_node and name_node.text.decode("utf-8") == func_name:
 return (name_node.start_point[0], name_node.start_point[1])
 return None
def _find_enclosing_function(
 tree: Any, line_0indexed: int
) -> str | None:
 """在 AST 中找包含 line 的最近函数（用于 CallSite 的 caller_function）。
 Returns:
 函数名字符串或 None（未找到，调用者为模块级代码）
 """
 best_start: int = -1
 best_name: str | None = None
 def _search(node: Any) -> None:
 nonlocal best_start, best_name
 if node.type in (
 "function_declaration",
 "arrow_function",
 "function",
 "function_expression",
 "method_definition",
 ):
 start = node.start_point[0]
 end = node.end_point[0]
 if start <= line_0indexed <= end and start > best_start:
 name_node = node.child_by_field_name("name")
 name = name_node.text.decode("utf-8") if name_node else "<anonymous>"
 best_start = start
 best_name = name
 for child in node.children:
 _search(child)
 _search(tree.root_node)
 return best_name
def resolve_call_sites_for_wrapper(
 wrapper: ApiWrapperData,
 supervisor: Any,
 timeout: float = 15.0,
) -> list[ApiCallSiteData]:
 """Step 2: volar textDocument/references 反向追踪 ApiWrapper 调用点。
 Args:
 wrapper: ApiWrapperData（含 file_path + function_symbol）
 supervisor: Phase VolarPool 获取的 LspSupervisor 实例
 timeout: LSP 请求超时（秒）
 Returns:
 ApiCallSiteData 列表（volar 失败时返回，非阻塞）
 """
 from codegraph.lsp.protocol import path_to_uri, uri_to_path
 from lsprotocol import types as lsp
 # 1. 定位函数名在文件中的位置
 parsed = parse_ts_or_vue_for_api(wrapper.file_path)
 if parsed is None:
 logger.warning(
 "api_resolver_step2_parse_failed",
 file_path=wrapper.file_path,
 symbol=wrapper.function_symbol,
 )
 return
 tree, _ = parsed
 pos = _find_symbol_position(tree, wrapper.function_symbol)
 if pos is None:
 logger.warning(
 "api_resolver_step2_symbol_not_found",
 file_path=wrapper.file_path,
 symbol=wrapper.function_symbol,
 )
 return
 line_0idx, col_0idx = pos
 uri = path_to_uri(Path(wrapper.file_path).resolve)
 # 2. 发 textDocument/references 请求
 async def _get_refs -> list:
 client = supervisor._client
 if client is None:
 raise RuntimeError("volar client 未启动")
 result = await client.request_references(
 uri,
 lsp.Position(line=line_0idx, character=col_0idx),
 include_declaration=False,
 timeout=timeout,
 )
 return result or
 try:
 refs = supervisor.call_async_in_loop(_get_refs, timeout=timeout)
 except Exception as e:
 logger.warning(
 "volar_references_failed",
 file_path=wrapper.file_path,
 symbol=wrapper.function_symbol,
 error=str(e),
 )
 return
 # 3. 转换 refs → ApiCallSiteData
 sites: list[ApiCallSiteData] =
 for ref in refs:
 try:
 ref_path = uri_to_path(ref.uri)
 ref_file = str(ref_path)
 # 找包含该行的函数（caller_function）
 caller_func = "<module>"
 ref_parsed = parse_ts_or_vue_for_api(ref_file)
 if ref_parsed:
 caller_func = (
 _find_enclosing_function(ref_parsed[0], ref.range.start.line)
 or "<module>"
 )
 sites.append(
 ApiCallSiteData(
 api_wrapper_file=wrapper.file_path,
 api_wrapper_symbol=wrapper.function_symbol,
 caller_file=ref_file,
 caller_function=caller_func,
 line_number=ref.range.start.line + 1,
 )
 )
 logger.debug(
 "api_call_site_detected",
 wrapper_symbol=wrapper.function_symbol,
 caller_file=ref_file,
 caller_function=caller_func,
 line=ref.range.start.line + 1,
 )
 except Exception as e:
 logger.warning(
 "api_call_site_conversion_failed",
 symbol=wrapper.function_symbol,
 error=str(e),
 )
 logger.info(
 "api_resolver_step2_complete",
 wrapper_symbol=wrapper.function_symbol,
 site_count=len(sites),
 )
 return sites
__all__ = [
 "discover_low_level_helpers",
 "discover_api_wrappers",
 "resolve_wrappers_for_repository",
 "resolve_call_sites_for_wrapper",
 "parse_ts_or_vue_for_api",
]
