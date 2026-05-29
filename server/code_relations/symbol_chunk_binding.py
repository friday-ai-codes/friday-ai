"""Symbol ↔ chunk_id 持久化绑定回填（Phase 第二阶段）。
索引完成后，把每个 codegraph ``Symbol`` 绑定到其所属的 RAG ``chunk_id``（落库到
``Symbol.chunk_id``），取代 ``CallEdgeBuilder`` / ``find_related`` 等在运行时反复用
``SymbolChunkResolver`` 做行号 bisect 的软对齐。
因 Phase 第一阶段后向量轨 chunk 已按**符号边界**切分，``symbol.start_line``
通常精确落在对应 chunk 的行区间内，bisect 回填准确率高；绑定一次落库后，下游查询
直接读 ``Symbol.chunk_id`` 即可，省去每次扫描 Qdrant。
放在 ``code_relations``（而非 ``codegraph``）：本模块同时依赖 ``codegraph.Symbol``
与 ``code_relations.SymbolChunkResolver``，而 ``code_relations`` → ``codegraph`` 已是
既有依赖方向（import_edge 等），反向会成环。
全程纯 async ORM（``async for`` + ``abulk_update``）：与 indexer 索引主流程的
async 上下文一致，避免 sync_to_async 在 SQLite 下的跨连接表锁。
"""
from __future__ import annotations
import structlog
from code_relations.symbol_lookup import SymbolChunkResolver
logger = structlog.get_logger(__name__)
__all__ = ["backfill_symbol_chunk_ids"]
async def backfill_symbol_chunk_ids(repository_id: str) -> int:
 """回填该仓库所有 ``Symbol.chunk_id``，返回本次新绑定的符号数。
 - 用 ``SymbolChunkResolver``（一次性 scroll Qdrant payload + 内存 bisect）把
 ``(file_path, start_line)`` 解析到所属 chunk_id；命中且有变化才写入。
 - 异常隔离：任何失败仅 ``warning`` 不重抛——绑定是优化项，绝不拖垮索引主流程。
 Args:
 repository_id: 仓库 UUID 字符串。
 Returns:
 本次实际更新（chunk_id 变化）的 Symbol 数量；失败返回 0。
 """
 from codegraph.models import Symbol
 try:
 resolver = SymbolChunkResolver(repository_id)
 to_update: list[Symbol] =
 total = 0
 async for sym in Symbol.objects.filter(repository_id=repository_id).only(
 "id", "file_path", "start_line", "chunk_id"
 ):
 total += 1
 cid = await resolver.resolve(sym.file_path, sym.start_line)
 if cid is not None and sym.chunk_id != cid:
 sym.chunk_id = cid
 to_update.append(sym)
 if to_update:
 await Symbol.objects.abulk_update(to_update, ["chunk_id"], batch_size=500)
 logger.info(
 "symbol_chunk_id_backfill_complete",
 repository_id=repository_id,
 total_symbols=total,
 bound=len(to_update),
 )
 return len(to_update)
 except Exception as exc:
 logger.warning(
 "symbol_chunk_id_backfill_failed",
 repository_id=repository_id,
 error=str(exc),
 error_type=type(exc).__name__,
 )
 return 0
