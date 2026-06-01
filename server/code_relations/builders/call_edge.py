"""CallEdgeBuilder：codegraph.CallEdge → ChunkEdge[CALL]（per Phase）。"""
from __future__ import annotations
import math
import uuid
from typing import TYPE_CHECKING
import structlog
from asgiref.sync import sync_to_async
from code_relations.builders.base import BaseEdgeBuilder
from code_relations.models import ChunkEdge, EdgeType
from code_relations.symbol_lookup import SymbolChunkResolver
if TYPE_CHECKING:
 from repositories.models import Repository
logger = structlog.get_logger(__name__)
__all__ = ["CallEdgeBuilder"]
class CallEdgeBuilder(BaseEdgeBuilder):
 """从 codegraph.CallEdge 派生 chunk-level CALL 边（per ）。
 weight = log10(call_count + 1) / 3.0，clamp 到 [0, 1]：
 - call_count=1 → 0.100
 - call_count=10 → 0.367
 - call_count=100 → 0.667
 - call_count=1000 → 1.000
 callee 解析：在同 repository 内按 callee_name 取首个 Symbol（ 简化策略；
 跨文件同名歧义留 Phase/255 优化）。callee 找不到 → skip 该 CallEdge。
 """
 edge_type_label: str = "CallEdge"
 async def build(
 self,
 repository: "Repository",
 dirty_chunk_ids: list[uuid.UUID],
 *,
 branch_name: str = "",
 ) -> list[ChunkEdge]:
 from codegraph.models import CallEdge as CodegraphCallEdge
 from codegraph.models import Symbol
 resolver = SymbolChunkResolver(str(repository.id))
 # 用 (count, names) 元组结构避免 mypy 对 dict[str, object] 的二次 narrow
 groups: dict[tuple[uuid.UUID, uuid.UUID], tuple[int, set[str]]] = {}
 skipped_callee = 0
 skipped_caller_chunk = 0
 qs = CodegraphCallEdge.objects.filter(
 repository_id=repository.id, branch_name=branch_name
 ).select_related("caller_symbol")
 callee_cache: dict[str, "Symbol | None"] = {}
 async for cedge in qs.aiterator(chunk_size=1000):
 caller = cedge.caller_symbol
 # 模块级调用边 caller_symbol=NULL（Phase）：chunk 级 CALL 图以
 # Symbol 为节点，模块级 caller 无 file_path/start_line，直接跳过（仿 callee skip 模式）。
 if caller is None:
 skipped_caller_chunk += 1
 continue
 caller_cid = await resolver.resolve(caller.file_path, caller.start_line)
 if caller_cid is None:
 skipped_caller_chunk += 1
 continue
 if cedge.callee_name not in callee_cache:
 callee_cache[cedge.callee_name] = await sync_to_async(
 Symbol.objects.filter(
 repository_id=repository.id,
 name=cedge.callee_name,
 branch_name=branch_name,
 ).first
 )
 callee_sym = callee_cache[cedge.callee_name]
 if callee_sym is None:
 skipped_callee += 1
 continue
 callee_cid = await resolver.resolve(
 callee_sym.file_path, callee_sym.start_line
 )
 if callee_cid is None:
 skipped_callee += 1
 continue
 key = (caller_cid, callee_cid)
 current = groups.get(key, (0, set))
 current_names = current[1]
 current_names.add(cedge.callee_name)
 groups[key] = (current[0] + 1, current_names)
 edges: list[ChunkEdge] =
 for (src, tgt), (count, names) in groups.items:
 weight = max(0.0, min(1.0, math.log10(count + 1) / 3.0))
 #：``names`` 必非空（构造方一定 add 一次 callee_name），但
 # 保留 ``or ""`` 兜底使 mypy 对 sorted 序列化结果更宽容。
 callee_name = sorted(names)[0] if names else ""
 edges.append(
 ChunkEdge(
 source_chunk_id=src,
 target_chunk_id=tgt,
 edge_type=EdgeType.CALL,
 weight=weight,
 metadata={
 "call_count": count,
 "callee_name": callee_name,
 },
 repository=repository,
 branch_name=branch_name,
 )
 )
 logger.info(
 "call_edge_build_complete",
 repository_id=str(repository.id),
 edges_built=len(edges),
 skipped_callee=skipped_callee,
 skipped_caller_chunk=skipped_caller_chunk,
 )
 return edges
