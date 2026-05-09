"""GraphWriter —— 将 ExtractionBundle 的四维图谱数据批量写入 Django ORM。
per: 图谱写入失败时不阻塞向量轨。调用方负责 try/except。
per: 图谱写入共享索引管线的事务锁（复用 _acquire_index_lock）。
per RESEARCH.md §E.2: 两阶段写入 —— Symbols → ImportEdges/Endpoints → CallEdges (FK resolution)。
per RESEARCH.md §H.4: 重新索引幂等性 —— per-file adelete 再 abulk_create。
"""
from typing import Any
import structlog
from django.conf import settings
from codegraph.models import CallEdge, Endpoint, ImportEdge, Symbol
logger = structlog.get_logger(__name__)
class GraphWriter:
 """将 ExtractionBundle 的四维图谱数据批量写入 Django ORM。
 单次调用 write_bundle 处理一个文件的完整图谱数据。
 由 IndexerService（Plan）在每个索引文件后调用，或批量处理。
 """
 async def write_bundle(self, repository_id: str, bundle: Any) -> dict[str, int]:
 """将单文件的 ExtractionBundle 批量写入 Django ORM。
 写入策略（per-file 幂等性）：
 1. 删除该文件旧记录：Symbol/ImportEdge/Endpoint 按 file_path 过滤 adelete
 （CallEdge 通过 caller_symbol FK 的 CASCADE 自动删除，无需单独处理）
 2. 先 bul_create Symbol → 构建 symbol_id_map
 3. bul_create ImportEdge 和 Endpoint（无 FK 依赖）
 4. bul_create CallEdge（通过 symbol_id_map 解析 caller_symbol FK）
 Args:
 repository_id: 仓库 UUID 字符串
 bundle: ExtractionBundle dataclass 实例（含 symbols/imports/calls/endpoints/file_path）
 Returns:
 dict: {"symbols": N, "imports": N, "calls": N, "endpoints": N} 各维度写入数量
 """
 file_path = bundle.file_path
 # =====================================================================
 # 第一步：删除该文件的旧图谱记录（幂等性保证）
 # =====================================================================
 await Symbol.objects.filter(
 repository_id=repository_id, file_path=file_path
 ).adelete
 await ImportEdge.objects.filter(
 repository_id=repository_id, source_file=file_path
 ).adelete
 await Endpoint.objects.filter(
 repository_id=repository_id, file_path=file_path
 ).adelete
 # CallEdge 不单独删除 —— caller_symbol FK 的 CASCADE 已在上一步
 # Symbol adelete 时自动清理关联的 CallEdge
 stats: dict[str, int] = {"symbols": 0, "imports": 0, "calls": 0, "endpoints": 0}
 # =====================================================================
 # 第二步：批量创建 Symbol（必须先于 CallEdge）
 # =====================================================================
 symbol_objs: list[Symbol] =
 for s in bundle.symbols:
 symbol_objs.append(Symbol(
 repository_id=repository_id,
 name=s.name,
 symbol_type=s.symbol_type,
 file_path=s.file_path,
 start_line=s.start_line,
 end_line=s.end_line,
 signature=s.signature,
 is_async=s.is_async,
 ))
 if symbol_objs:
 created_symbols = await Symbol.objects.abulk_create(symbol_objs)
 stats["symbols"] = len(created_symbols)
 # 构建 symbol_id_map: (file_path, name, start_line) -> Symbol.id
 # 用于 CallEdge 的 caller_symbol FK 解析
 symbol_id_map: dict[tuple[str, str, int], str] = {}
 for sym in created_symbols:
 key = (sym.file_path, sym.name, sym.start_line)
 symbol_id_map[key] = str(sym.id)
 else:
 symbol_id_map = {}
 # =====================================================================
 # 第三步：批量创建 ImportEdge（无 FK 依赖）
 # =====================================================================
 import_objs: list[ImportEdge] =
 for imp in bundle.imports:
 import_objs.append(ImportEdge(
 repository_id=repository_id,
 source_file=imp.source_file,
 target_module=imp.target_module,
 imported_names=imp.imported_names,
 is_relative=imp.is_relative,
 ))
 if import_objs:
 await ImportEdge.objects.abulk_create(import_objs)
 stats["imports"] = len(import_objs)
 # =====================================================================
 # 第四步：批量创建 Endpoint（无 FK 依赖）
 # =====================================================================
 endpoint_objs: list[Endpoint] =
 for ep in bundle.endpoints:
 # url_path 可能为 None（Layer 1 装饰器扫描结果未关联 URL）
 endpoint_objs.append(Endpoint(
 repository_id=repository_id,
 http_method=ep.http_method,
 url_path=ep.url_path or "",
 handler_name=ep.handler_name,
 view_type=ep.view_type,
 file_path=ep.file_path,
 line_number=ep.line_number,
 ))
 if endpoint_objs:
 await Endpoint.objects.abulk_create(endpoint_objs)
 stats["endpoints"] = len(endpoint_objs)
 # =====================================================================
 # 第五步：批量创建 CallEdge（依赖 symbol_id_map 解析 FK）
 # =====================================================================
 call_objs: list[CallEdge] =
 skipped_calls = 0
 for call in bundle.calls:
 caller_key = (
 call.caller_key[0], # file_path
 call.caller_key[1], # name
 call.caller_key[2], # start_line
 )
 caller_id = symbol_id_map.get(caller_key)
 if caller_id is None:
 # 调用点不在任何已提取的 Symbol 内（模块级调用、嵌套 lambda 等），跳过
 skipped_calls += 1
 continue
 call_objs.append(CallEdge(
 repository_id=repository_id,
 caller_symbol_id=caller_id,
 callee_name=call.callee_name,
 call_type=call.call_type,
 line_number=call.line_number,
 ))
 if call_objs:
 await CallEdge.objects.abulk_create(call_objs)
 stats["calls"] = len(call_objs)
 if skipped_calls > 0:
 logger.debug(
 "call_edge_skipped_no_caller",
 file_path=file_path,
 skipped=skipped_calls,
 reason="caller not found in symbol_id_map (module-level call or dynamic dispatch)",
 )
 logger.info(
 "graph_bundle_written",
 file_path=file_path,
 symbols=stats["symbols"],
 imports=stats["imports"],
 calls=stats["calls"],
 endpoints=stats["endpoints"],
 skipped_calls=skipped_calls,
 )
 return stats
