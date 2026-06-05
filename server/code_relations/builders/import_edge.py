"""ImportEdgeBuilder：codegraph.ImportEdge → ChunkEdge[IMPORT]（per implementation contract）。"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog
from asgiref.sync import sync_to_async
from django.db.models import Q

from code_relations.builders.base import BaseEdgeBuilder
from code_relations.constants import CANDIDATE_EXTENSIONS
from code_relations.models import ChunkEdge, ChunkRegistry, EdgeType

if TYPE_CHECKING:
    from repositories.models import Repository

logger = structlog.get_logger(__name__)

__all__ = ["ImportEdgeBuilder"]

_CANDIDATE_EXTENSIONS = CANDIDATE_EXTENSIONS
"""work item：从 ``code_relations.constants`` 导出，新增语言只改常量不改 builder。"""


class ImportEdgeBuilder(BaseEdgeBuilder):
    """从 codegraph.ImportEdge 派生 chunk-level IMPORT 边（per contract）。

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
        *,
        branch_name: str = "",
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
                    branch_name=branch_name,
                ).first
            )()
            cid = obj.chunk_id if obj is not None else None
            first_chunk_cache[file_path] = cid
            return cid

        async def _resolve_target_file(
            target_module: str, is_relative: bool, source_file: str
        ) -> str | None:
            """target_module → 候选 file_path（work item + work item 修复）。

            work item：原 ``lstrip("./")`` 是字符集剥离会把 ``..`` 一并剥掉，破坏
            PEP 328 父级相对导入语义。改为按前导点数量决定向上回溯层级（n
            dots → 1 dots = 同包，2 dots = 父包...），从 ``source_file`` 目录
            出发计算 base path。

            work item：``file_path__endswith=candidate`` 无锚定时 ``auth.py`` 会
            匹配 ``xauth.py`` / ``oauth.py``。改为 ``Q(file_path=candidate) |
            Q(file_path__endswith="/" + candidate)`` 加 ``/`` 锚定避免误匹配。
            """
            # 先剥离显式文件扩展名（如 ``./Foo.vue`` / ``./a.ts``）。JS/TS 相对导入
            # 常带扩展名，若不剥离，后续 ``replace(".","/")`` 会把扩展名的点也替换
            # 成 ``/``（``index.vue`` → ``index/vue``），导致 ``.vue`` / 任何显式扩展名
            # 导入永远解析失败（这是 Vue 组件 import 边建不出 ChunkEdge 的根因）。
            explicit_ext = ""
            mod = target_module
            for _ext in _CANDIDATE_EXTENSIONS:
                if mod.endswith(_ext):
                    explicit_ext = _ext
                    mod = mod[: -len(_ext)]
                    break

            if is_relative and mod.startswith("."):
                n_leading_dots = 0
                for ch in mod:
                    if ch == ".":
                        n_leading_dots += 1
                    else:
                        break
                suffix = mod[n_leading_dots:]
                # 带显式扩展名的相对路径用 ``/`` 分隔，不能再 dot→slash；只有无扩展名
                # 的点分模块（Python ``..utils`` / 别名 ``components.Button``）才转换。
                suffix_path = suffix if explicit_ext else suffix.replace(".", "/")
                src_dir = source_file.rsplit("/", 1)[0] if "/" in source_file else ""
                up_levels = max(0, n_leading_dots - 1)
                parts = src_dir.split("/") if src_dir else []
                if up_levels > 0:
                    if up_levels >= len(parts):
                        parts = []
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
                base = mod if explicit_ext else mod.replace(".", "/")

            # 归一化路径分隔符：折叠重复 ``/`` 与前导 ``/``，避免 ``./Foo`` 拼出
            # ``src//Foo`` 这类双斜杠导致 endswith 锚定匹配失败（相对导入常见）。
            base = "/".join(seg for seg in base.split("/") if seg)

            # 显式扩展名：只按该扩展精确匹配，不再枚举候选扩展（避免误命中）。
            if explicit_ext:
                candidate = f"{base}{explicit_ext}"
                anchored = f"/{candidate}"
                obj = await sync_to_async(
                    ChunkRegistry.objects.filter(
                        repository_id=repository.id, branch_name=branch_name
                    )
                    .filter(Q(file_path=candidate) | Q(file_path__endswith=anchored))
                    .first
                )()
                return obj.file_path if obj is not None else None

            for ext in _CANDIDATE_EXTENSIONS:
                candidate = f"{base}{ext}"
                anchored = f"/{candidate}"
                obj = await sync_to_async(
                    ChunkRegistry.objects.filter(
                        repository_id=repository.id, branch_name=branch_name
                    )
                    .filter(
                        Q(file_path=candidate) | Q(file_path__endswith=anchored)
                    )
                    .first
                )()
                if obj is not None:
                    return obj.file_path
            return None

        edges: list[ChunkEdge] = []
        skipped_source = 0
        skipped_target = 0

        qs = CodegraphImportEdge.objects.filter(
            repository_id=repository.id, branch_name=branch_name
        )
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
                        "imported_names": list(iedge.imported_names or []),
                        "is_relative": bool(iedge.is_relative),
                    },
                    repository=repository,
                    branch_name=branch_name,
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
