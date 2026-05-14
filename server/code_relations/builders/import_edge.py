"""ImportEdgeBuilder：codegraph.ImportEdge → ChunkEdge[IMPORT]（per Phase）。"""
from __future__ import annotations
import uuid
from typing import TYPE_CHECKING
import structlog
from asgiref.sync import sync_to_async
from code_relations.builders.base import BaseEdgeBuilder
from code_relations.models import ChunkEdge, ChunkRegistry, EdgeType
if TYPE_CHECKING:
 from repositories.models import Repository
logger = structlog.get_logger(__name__)
__all__ = ["ImportEdgeBuilder"]
_CANDIDATE_EXTENSIONS = (".py", ".ts", ".tsx", ".js", ".jsx", ".go")
class ImportEdgeBuilder(BaseEdgeBuilder):
 """从 codegraph.ImportEdge 派生 chunk-level IMPORT 边（per ）。
 - source_file → 该文件的第一个 chunk (chunk_index=0)
 - target_module → 解析为候选 file_path（替换 . → / + 加扩展名候选），
 ChunkRegistry 内 endswith 匹配第一个找到的；找不到 → skip
 - weight=1.0 固定（import 是 binary 关系，无频次）
 - metadata = {source_file, target_module, target_file, imported_names, is_relative}
 """
 edge_type_label: str = "ImportEdge"
 async def build(
 self,
 repository: "Repository",
 dirty_chunk_ids: list[uuid.UUID],
 ) -> list[ChunkEdge]:
 from codegraph.models import ImportEdge as CodegraphImportEdge
 first_chunk_cache: dict[str, uuid.UUID | None] = {}
 async def _first_chunk_id(file_path: str) -> uuid.UUID | None:
 if file_path in first_chunk_cache:
 return first_chunk_cache[file_path]
 obj = await sync_to_async(
 ChunkRegistry.objects.filter(
 repository_id=repository.id,
 file_path=file_path,
 chunk_index=0,
 ).first
 )
 cid = obj.chunk_id if obj is not None else None
 first_chunk_cache[file_path] = cid
 return cid
 async def _resolve_target_file(target_module: str, is_relative: bool) -> str | None:
 base = (
 target_module.replace(".", "/")
 if not is_relative
 else target_module.lstrip("./")
 )
 for ext in _CANDIDATE_EXTENSIONS:
 candidate = f"{base}{ext}"
 obj = await sync_to_async(
 ChunkRegistry.objects.filter(
 repository_id=repository.id,
 file_path__endswith=candidate,
 ).first
 )
 if obj is not None:
 return obj.file_path
 return None
 edges: list[ChunkEdge] =
 skipped_source = 0
 skipped_target = 0
 qs = CodegraphImportEdge.objects.filter(repository_id=repository.id)
 async for iedge in qs.aiterator(chunk_size=1000):
 src_cid = await _first_chunk_id(iedge.source_file)
 if src_cid is None:
 skipped_source += 1
 continue
 target_file = await _resolve_target_file(
 iedge.target_module, iedge.is_relative
 )
 if target_file is None:
 skipped_target += 1
 continue
 tgt_cid = await _first_chunk_id(target_file)
 if tgt_cid is None:
 skipped_target += 1
 continue
 edges.append(
 ChunkEdge(
 source_chunk_id=src_cid,
 target_chunk_id=tgt_cid,
 edge_type=EdgeType.IMPORT,
 weight=1.0,
 metadata={
 "source_file": iedge.source_file,
 "target_module": iedge.target_module,
 "target_file": target_file,
 "imported_names": list(iedge.imported_names or ),
 "is_relative": bool(iedge.is_relative),
 },
 repository=repository,
 )
 )
 logger.info(
 "import_edge_build_complete",
 repository_id=str(repository.id),
 edges_built=len(edges),
 skipped_source=skipped_source,
 skipped_target=skipped_target,
 )
 return edges
