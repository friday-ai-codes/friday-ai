"""ImportEdgeBuilder：codegraph.ImportEdge → ChunkEdge[IMPORT]（per Phase）。"""
from __future__ import annotations
import uuid
from typing import TYPE_CHECKING
import structlog
from asgiref.sync import sync_to_async
from django.db.models import Q
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
 async def _resolve_target_file(
 target_module: str, is_relative: bool, source_file: str
 ) -> str | None:
 """target_module → 候选 file_path（ + 修复）。：原 ``lstrip("./")`` 是字符集剥离会把 ``..`` 一并剥掉，破坏
 PEP 328 父级相对导入语义。改为按前导点数量决定向上回溯层级（n
 dots → 1 dots = 同包，2 dots = 父包...），从 ``source_file`` 目录
 出发计算 base path。：``file_path__endswith=candidate`` 无锚定时 ``auth.py`` 会
 匹配 ``xauth.py`` / ``oauth.py``。改为 ``Q(file_path=candidate) |
 Q(file_path__endswith="/" + candidate)`` 加 ``/`` 锚定避免误匹配。
 """
 if is_relative and target_module.startswith("."):
 n_leading_dots = 0
 for ch in target_module:
 if ch == ".":
 n_leading_dots += 1
 else:
 break
 suffix = target_module[n_leading_dots:]
 suffix_path = suffix.replace(".", "/")
 src_dir = source_file.rsplit("/", 1)[0] if "/" in source_file else ""
 up_levels = max(0, n_leading_dots - 1)
 parts = src_dir.split("/") if src_dir else
 if up_levels > 0:
 if up_levels >= len(parts):
 parts =
 else:
 parts = parts[:-up_levels]
 base_dir = "/".join(p for p in parts if p)
 if base_dir and suffix_path:
 base = f"{base_dir}/{suffix_path}"
 elif base_dir:
 base = base_dir
 else:
 base = suffix_path
 else:
 base = target_module.replace(".", "/")
 for ext in _CANDIDATE_EXTENSIONS:
 candidate = f"{base}{ext}"
 anchored = f"/{candidate}"
 obj = await sync_to_async(
 ChunkRegistry.objects.filter(repository_id=repository.id)
 .filter(
 Q(file_path=candidate) | Q(file_path__endswith=anchored)
 )
 .first
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
 iedge.target_module, iedge.is_relative, iedge.source_file
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
