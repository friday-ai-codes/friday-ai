"""``find_related_code`` agent tool —— per Phase Plan / ROADMAP -#3。
把 Phase 落地的 ``HybridSearchService.find_related`` Python API 包装成 MCP tool：
- **三起点解析**：``chunk_id`` 直传 / ``file_path`` 走 ``ChunkRegistry.afirst`` /
 ``symbol_name`` 走 ``Provider.lookup_symbols`` → ``ChunkRegistry`` 取含起始行
 的 chunk（精确）+ 首 chunk fallback。
- **结构化错误**：``repository_id`` 缺失 / Pydantic ``ValidationError`` / 起点
 解析失败均走 ``ToolResult(success=False, error=...)``，不让异常冒泡到 agent
 runtime（per work-item ）。
- **NullProvider 守卫**：``symbol_name`` 路径用 ``isinstance(provider,
 SymbolCapableProvider)`` 运行时守卫；NullProvider 返结构化 error 而不抛
 ``AttributeError``（per work-item ）。
- **reason 透传**：``list[NeighborMetadata] → list[NeighborOutput]`` 字段同序
 装配，``reason`` 直接走 Phase reason 模板输出**不重写**（per work-item，CI grep gate 守门 —— 本模块禁止 import / 引用上游 reason 模板生成器）。
**注册路径**：Plan 已通过 ``agents/tools/__init__.py`` 顶层 ``from
agents.tools.find_related_code import find_related_code`` 触发 ``@tool``
装饰器注册到 ``ToolRegistry``。本模块在测试 / 工具脚本中**单独 import 不会重复
注册**——Python 模块缓存（``sys.modules``）保证 ``@tool`` 装饰器仅在首次 import
时执行一次。Plan snapshot 契约测试守住函数签名 / JSON schema 漂移。
"""
from __future__ import annotations
import dataclasses
from typing import Any
import structlog
from django.core.exceptions import ValidationError as DjangoValidationError
from pydantic import ValidationError
from agents.tools.base import ToolResult, tool
from agents.tools.schemas.find_related_code import (
 FindRelatedCodeInput,
 FindRelatedCodeOutput,
 NeighborOutput,
)
from code_relations.models import ChunkRegistry
from services.code_intel import get_provider
from services.retrieval import HybridSearchService
logger = structlog.get_logger(__name__)
_TOOL_DESCRIPTION = (
 "Find code chunks related to a known starting point "
 "(file / chunk_id / symbol_name) by graph relations.\n"
 "\n"
 "USE WHEN you have a CONCRETE starting point and want to discover related "
 "code via:\n"
 " - CALL: who calls this / what does this call\n"
 " - IMPORT: who imports this module / what does this import\n"
 " - TEST_OF: where are the tests for this code\n"
 "\n"
 "DO NOT USE FOR natural language queries — use `search_repository_code` "
 "instead.\n"
 "\n"
 "Decision tree:\n"
 ' - "show me callers of foo" → find_related_code(symbol_name="foo", '
 'direction="upstream")\n'
 ' - "what does foo call internally" → find_related_code('
 'symbol_name="foo", direction="downstream")\n'
 ' - "find tests for src/auth.py" → find_related_code('
 'file_path="src/auth.py", relation_types=["TEST_OF"])\n'
 ' - "search for password validation logic" → search_repository_code('
 'query="password validation")'
)
"""Tool description 决策树文本（per work-item / Plan）。
LLM 读 description 即应能判别：CONCRETE 起点（file / chunk_id / symbol_name）走
本工具图遍历，自然语言 query 走 ``search_repository_code`` hybrid 检索。
"""
_TOOL_PARAMETERS: dict[str, Any] = {
 "type": "object",
 "properties": {
 "file_path": {
 "type": "string",
 "description": (
 "起点文件路径（相对 repository 根）。与 chunk_id / symbol_name 三选一。"
 ),
 },
 "chunk_id": {
 "type": "string",
 "description": (
 "起点 chunk UUID。最精准的起点形式（直接传给 "
 "HybridSearchService.find_related）。与 file_path / symbol_name 三选一。"
 ),
 },
 "symbol_name": {
 "type": "string",
 "description": (
 "起点符号名（如函数 / 类 / 方法名）。走 Provider.lookup_symbols "
 "解析为所在文件 → chunk。与 file_path / chunk_id 三选一。"
 ),
 },
 "repository_id": {
 "type": "string",
 "description": (
 "**REQUIRED.** 目标仓库 UUID。chunk_id 跨 repo 语义上需限定单 repo "
 "查询；None / 缺省时 tool 函数报错 'repository_id is required'。"
 ),
 },
 "relation_types": {
 "type": "array",
 "items": {
 "type": "string",
 "enum": [
 "CALL",
 "IMPORT",
 "SAME_FILE",
 "TEST_OF",
 "CO_CHANGED",
 "SEMANTIC",
 ],
 },
 "description": (
 "图谱遍历关心的边类型；默认 ['CALL','IMPORT','TEST_OF']（强信号）。"
 "弱信号 SAME_FILE / CO_CHANGED / SEMANTIC 不默认开避免邻居稀释。"
 ),
 "default": ["CALL", "IMPORT", "TEST_OF"],
 },
 "hops": {
 "type": "integer",
 "minimum": 1,
 "maximum": 2,
 "default": 1,
 "description": (
 "图谱遍历跳数上限；硬约束 ≤2，与 Phase MAX_HOPS=2 对齐。"
 ),
 },
 "direction": {
 "type": "string",
 "enum": ["downstream", "upstream", "both"],
 "default": "both",
 "description": (
 "遍历方向：downstream（我依赖谁）/ upstream（谁依赖我）/ "
 "both（双向各取 limit/2 去重合并）。"
 ),
 },
 "limit": {
 "type": "integer",
 "minimum": 1,
 "maximum": 100,
 "default": 20,
 "description": (
 "返回邻居数量上限；hops=2 时优先填 hop=1 再填 hop=2。"
 ),
 },
 },
 "required": ["repository_id"],
}
"""JSON Schema 镜像 ``FindRelatedCodeInput`` 字段（per Task 2 must_have）。
``required: ["repository_id"]`` 与 tool 函数运行时校验对齐：``chunk_id`` 跨 repo
不唯一，必须显式限定单 repo 查询（per work-item ）。Pydantic schema 仍保持
``repository_id: str | None`` 留给未来 inferred-from-context 扩展，但 LLM 调用方
读 JSON Schema 应一次性看到必填语义（per work-item ）。
字面值与 ``FindRelatedCodeInput.model_json_schema`` 字段对齐，Plan snapshot
契约测试在 description 升级时 diff 必须可 review。"""
@tool(
 name="find_related_code",
 description=_TOOL_DESCRIPTION,
 category="PROJECT",
 parameters=_TOOL_PARAMETERS,
)
async def find_related_code(
 file_path: str | None = None,
 chunk_id: str | None = None,
 symbol_name: str | None = None,
 repository_id: str | None = None,
 relation_types: list[str] | None = None,
 hops: int = 1,
 direction: str = "both",
 limit: int = 20,
) -> ToolResult:
 """查 chunk / file / symbol 起点的图谱邻居（一跳 / 二跳，多方向，多关系过滤）。
 Args:
 file_path: 起点文件路径（与 chunk_id / symbol_name 三选一）。
 chunk_id: 起点 chunk UUID（直传给 HybridSearchService.find_related）。
 symbol_name: 起点符号名（走 Provider.lookup_symbols 解析）。
 repository_id: 目标仓库 UUID（必填，per work-item ）。
 relation_types: 限定 EdgeType（None / 不传 → schema 默认强信号三类）。
 hops: 跳数（1 或 2；schema 守 ge=1, le=2）。
 direction: ``downstream`` / ``upstream`` / ``both``（schema 守 Literal）。
 limit: 邻居数上限（schema 守 ge=1, le=100）。
 Returns:
 ``ToolResult``：成功路径 ``output={"data": FindRelatedCodeOutput, ...}``；
 失败路径 ``success=False`` + ``error`` 字符串。**永不冒泡异常**——
 Pydantic ``ValidationError``、Django ``ValidationError``、``ValueError``、
 ``TypeError`` 等均被捕获后转结构化 ``ToolResult(success=False, error=...)``
 （per Phase 双层防御：schema 层 UUID 形态守卫 + tool 层 ORM
 异常兜底）。
 """
 logger.info(
 "find_related_code_called",
 file_path=file_path,
 chunk_id=chunk_id,
 symbol_name=symbol_name,
 repository_id=repository_id,
 hops=hops,
 direction=direction,
 limit=limit,
 )
 try:
 return await _find_related_code_impl(
 file_path=file_path,
 chunk_id=chunk_id,
 symbol_name=symbol_name,
 repository_id=repository_id,
 relation_types=relation_types,
 hops=hops,
 direction=direction,
 limit=limit,
 )
 except (ValueError, TypeError, DjangoValidationError) as exc:
 logger.warning(
 "find_related_code_failed",
 error_type=type(exc).__name__,
 error=str(exc),
 )
 return ToolResult(
 success=False,
 error=f"invalid input or downstream failure: {exc}",
 )
 except ValidationError as exc:
 logger.warning(
 "find_related_code_failed",
 error_type="ValidationError",
 error=str(exc),
 )
 return ToolResult(success=False, error=str(exc))
async def _find_related_code_impl(
 *,
 file_path: str | None,
 chunk_id: str | None,
 symbol_name: str | None,
 repository_id: str | None,
 relation_types: list[str] | None,
 hops: int,
 direction: str,
 limit: int,
) -> ToolResult:
 """``find_related_code`` 函数体实现（per：抽内层以承接外层 try/except）。
 所有 ORM / Provider 调用集中在此，外层 ``find_related_code`` 包统一异常兜底。
 保持原行为不变（含 Pydantic 层 ``ValidationError`` 走原 try/except 路径）。
 """
 input_kwargs: dict[str, Any] = {
 "file_path": file_path,
 "chunk_id": chunk_id,
 "symbol_name": symbol_name,
 "repository_id": repository_id,
 "hops": hops,
 "direction": direction,
 "limit": limit,
 }
 if relation_types is not None:
 input_kwargs["relation_types"] = relation_types
 try:
 validated = FindRelatedCodeInput(**input_kwargs)
 except ValidationError as exc:
 logger.warning(
 "find_related_code_failed",
 error_type="ValidationError",
 error=str(exc),
 )
 return ToolResult(success=False, error=str(exc))
 if validated.repository_id is None:
 logger.warning(
 "find_related_code_failed",
 error_type="MissingRepositoryId",
 )
 return ToolResult(
 success=False,
 error=(
 "repository_id is required (chunk_id 跨 repo 语义上需限定单仓库；"
 "per work-item )"
 ),
 )
 repo_id: str = validated.repository_id
 provider = get_provider
 resolved_via: str
 start_chunk_id: str
 if validated.chunk_id is not None:
 start_chunk_id = validated.chunk_id
 resolved_via = "chunk_id"
 elif validated.file_path is not None:
 reg = (
 await ChunkRegistry.objects.filter(
 repository_id=repo_id, file_path=validated.file_path
 )
 .order_by("chunk_index")
 .afirst
 )
 if reg is None:
 logger.warning(
 "find_related_code_failed",
 error_type="FilePathNotFound",
 file_path=validated.file_path,
 repository_id=repo_id,
 )
 return ToolResult(
 success=False,
 error=(
 f"no chunk found for file_path={validated.file_path} in "
 f"repository_id={repo_id}"
 ),
 )
 start_chunk_id = str(reg.chunk_id)
 resolved_via = "file_path"
 else:
 assert validated.symbol_name is not None
 # 走 capabilities 集合 + hasattr 双层守卫（per protocols.py 文档推荐：
 # ``"symbol_lookup" in provider.capabilities`` 避直接 isinstance 耦合
 # Protocol 类型；同时 hasattr 兜底防 capabilities 集合声明但方法缺失）。
 # NullProvider.capabilities == frozenset → 守卫失败返结构化 error，
 # 不抛 AttributeError（per work-item ）。
 # 防御 Protocol 实现漂移：getattr(..., default) 仅在属性不存在时
 # 回退；若 provider 类显式定义 capabilities = None / / 其他非容器，
 # "symbol_lookup" not in None 会抛 TypeError。``or frozenset`` 让
 # None / 空容器统一 falsy 落回 frozenset，简洁且类型安全。
 raw_caps = getattr(provider, "capabilities", None)
 provider_caps: frozenset[str] = (
 raw_caps
 if isinstance(raw_caps, (frozenset, set, list, tuple))
 else frozenset
 )
 if "symbol_lookup" not in provider_caps or not hasattr(
 provider, "lookup_symbols"
 ):
 logger.warning(
 "find_related_code_failed",
 error_type="ProviderLacksSymbolLookup",
 provider_type=type(provider).__name__,
 capabilities=list(provider_caps),
 )
 return ToolResult(
 success=False,
 error=(
 "symbol_name path requires SymbolCapableProvider; current "
 f"provider ({type(provider).__name__}) lacks symbol_lookup "
 "capability"
 ),
 )
 symbols = await provider.lookup_symbols(
 [validated.symbol_name], repository_ids=[repo_id]
 )
 if not symbols:
 logger.warning(
 "find_related_code_failed",
 error_type="SymbolNotMatched",
 symbol_name=validated.symbol_name,
 repository_id=repo_id,
 )
 return ToolResult(
 success=False,
 error=(
 f"no symbol matched symbol_name={validated.symbol_name} in "
 f"repository_id={repo_id}"
 ),
 )
 sym = symbols[0]
 sym_file_path = sym.get("file_path") or ""
 if not sym_file_path:
 # 防御 Protocol 实现漂移：第三方 Provider 若返回 dict 缺
 # file_path 键 / 值为 None / 空串，下游 ChunkRegistry.filter(file_path="")
 # 查不到 → 错误信息空路径调试一头雾水。提前返结构化 error 让调用方
 # 拿到清晰诊断。LocalProvider 保证 file_path 非空（来自 Django Model
 # 必填字段），此分支当前不触发，但 BaseCodeProvider Protocol 未约束。
 logger.warning(
 "find_related_code_failed",
 error_type="ProviderReturnedSymbolWithoutFilePath",
 symbol_name=validated.symbol_name,
 sym_dict=sym,
 )
 return ToolResult(
 success=False,
 error=(
 f"provider returned symbol for {validated.symbol_name} "
 "without file_path; cannot resolve start chunk"
 ),
 )
 start_line = sym.get("start_line")
 reg = None
 if start_line is not None:
 reg = (
 await ChunkRegistry.objects.filter(
 repository_id=repo_id,
 file_path=sym_file_path,
 line_start__lte=start_line,
 line_end__gte=start_line,
 )
 .order_by("chunk_index")
 .afirst
 )
 if reg is None:
 logger.warning(
 "symbol_chunk_match_fallback_first",
 symbol_name=validated.symbol_name,
 file_path=sym_file_path,
 start_line=start_line,
 )
 reg = (
 await ChunkRegistry.objects.filter(
 repository_id=repo_id, file_path=sym_file_path
 )
 .order_by("chunk_index")
 .afirst
 )
 if reg is None:
 logger.warning(
 "find_related_code_failed",
 error_type="SymbolChunkUnresolved",
 symbol_name=validated.symbol_name,
 file_path=sym_file_path,
 )
 return ToolResult(
 success=False,
 error=(
 f"symbol {validated.symbol_name} found at {sym_file_path} "
 "but no chunk indexed yet"
 ),
 )
 start_chunk_id = str(reg.chunk_id)
 resolved_via = "symbol_name"
 neighbors_metadata = await HybridSearchService(provider).find_related(
 start_chunk_id,
 repo_ids=[repo_id],
 relation_types=list(validated.relation_types),
 hops=validated.hops,
 direction=validated.direction,
 limit=validated.limit,
 )
 neighbors_out: list[NeighborOutput] = [
 NeighborOutput(**dataclasses.asdict(n)) for n in neighbors_metadata
 ]
 message = "无关联代码" if not neighbors_out else ""
 output_model = FindRelatedCodeOutput(neighbors=neighbors_out, message=message)
 metadata: dict[str, Any] = {
 "start_chunk_id": start_chunk_id,
 "resolved_via": resolved_via,
 "repository_id": repo_id,
 "hops": validated.hops,
 "direction": validated.direction,
 "total_neighbors": len(neighbors_out),
 }
 logger.info(
 "find_related_code_success",
 start_chunk_id=start_chunk_id,
 resolved_via=resolved_via,
 neighbor_count=len(neighbors_out),
 )
 return ToolResult(
 success=True,
 output={
 "data": output_model.model_dump,
 "metadata": metadata,
 },
 )
__all__ = ["find_related_code"]
