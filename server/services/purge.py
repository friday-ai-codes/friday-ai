"""统一文件删除入口（PF-03 + PF-05）。

``purge_file(repository_id, rel_path)`` 是三条索引删除路径（``run_incremental_index`` /
``run_git_diff_index`` 的 DELETE 分支）与 Phase 23 排除/敏感清理共用的**唯一派生数据
删除点**。一次调用清净一个文件在以下五个数据面的残留：

1. Qdrant 主 collection —— 复用 ``QdrantService.delete_by_file_path``。
2. Qdrant overlay collections（**PF-05 收口**）—— 枚举该 repo 所有非空
   ``RepositoryBranchIndex.collection_name``，逐一
   ``delete_by_payload_field("file_path", rel_path)``。
3. ``FileIndex`` 行 —— 该 ``(repository, file_path)`` 行删空。
4. ``ChunkRegistry``（含 ``ChunkEdge``，**PF-03 收口**）—— 跨所有 ``branch_name`` 删
   ChunkRegistry；务必走 queryset ``.adelete()`` 逐实例触发既有 ``pre_delete`` 信号，
   联动清掉指向被删 chunk 的 ``ChunkEdge`` 并调度 reconcile（绝不绕过信号）。
5. codegraph（Symbol / ImportEdge / Endpoint / CallEdge）—— 对 base("") + 各已索引
   feature 分支调 ``GraphWriter.adelete_for_files``。

语义保证：
- **删后无残留**：返回的 :class:`PurgeResult` 暴露各面删除计数/成功标记，调用方据此
  判定是否全净。
- **幂等**：文件已不存在 / 各面已空时全部 no-op，绝不抛出（计数为 0、``failures`` 空）。
- **best-effort 逐面隔离**（T-23-04）：单面失败（如 Qdrant 连接错）记 structlog warning
  并在 ``PurgeResult.failures`` 标记该面，不阻断其余面；调用方据 result 决定是否重试，
  不静默假装全净。
- **repository_id 作用域**（T-23-03）：所有删除 filter 均带 ``repository_id``，Qdrant
  collection 名由 repo 派生，杜绝跨 repo 误删。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog
from asgiref.sync import sync_to_async

from services.qdrant_service import QdrantService

logger = structlog.get_logger(__name__)

__all__ = ["PurgeResult", "purge_file"]


@dataclass
class PurgeResult:
    """单文件 purge 的各面删除结果（供调用方判定是否全净）。"""

    qdrant_main: bool = False
    qdrant_overlays: int = 0
    file_index_deleted: int = 0
    chunk_registry_deleted: int = 0
    codegraph_deleted: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """无任一面失败时为真（删后全净）。"""
        return not self.failures


async def _overlay_collection_names(repository_id: str) -> list[str]:
    """枚举该 repo 所有非空 ``RepositoryBranchIndex.collection_name``（PF-05 overlay 集合）。"""

    def _query() -> list[str]:
        from repositories.models import RepositoryBranchIndex

        return list(
            RepositoryBranchIndex.objects.filter(repository_id=repository_id)
            .exclude(collection_name__isnull=True)
            .exclude(collection_name="")
            .values_list("collection_name", flat=True)
        )

    return await sync_to_async(_query)()


async def _branch_names(repository_id: str) -> list[str]:
    """枚举该 repo 在 codegraph 中可能存在的分支命名空间（归一化口径）。

    base 分支恒归一为 ``""``（与 ``_resolve_write_branch`` / codegraph 写入口径一致）；
    feature 分支用其原始 ``branch_name``。返回去重列表，``""`` 恒包含，供逐分支
    ``adelete_for_files``。
    """

    def _query() -> list[str]:
        from repositories.models import Repository, RepositoryBranchIndex

        repo = Repository.objects.filter(id=repository_id).first()
        base = ""
        if repo is not None:
            base = repo.base_branch or repo.default_branch or ""

        names: set[str] = {""}
        rows = RepositoryBranchIndex.objects.filter(repository_id=repository_id).values_list(
            "branch_name", "is_base_branch"
        )
        for branch_name, is_base in rows:
            if is_base or not branch_name or branch_name == base:
                names.add("")  # base 归一为 ""
            else:
                names.add(branch_name)
        return sorted(names)

    return await sync_to_async(_query)()


async def purge_file(repository_id: str, rel_path: str) -> PurgeResult:
    """删净一个文件在五个派生数据面的残留（幂等、best-effort 逐面隔离）。

    Args:
        repository_id: 仓库 UUID 字符串。
        rel_path: 仓库根的相对 POSIX 路径（与 Qdrant ``file_path`` payload 口径一致）。

    Returns:
        :class:`PurgeResult` —— 各面删除计数 / 成功标记 + ``failures`` 列表。
    """
    repo_id = str(repository_id)
    result = PurgeResult()

    # --- 1. Qdrant 主 collection ---
    try:
        ok = await sync_to_async(QdrantService.delete_by_file_path)(repo_id, rel_path)
        result.qdrant_main = bool(ok)
        if not ok:
            result.failures.append("qdrant_main")
    except Exception as exc:  # noqa: BLE001 — 单面失败隔离，不阻断其余面
        logger.warning(
            "purge_file.qdrant_main_failed",
            repository_id=repo_id,
            rel_path=rel_path,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        result.failures.append("qdrant_main")

    # --- 2. Qdrant overlay collections（PF-05）---
    try:
        overlay_names = await _overlay_collection_names(repo_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "purge_file.overlay_enum_failed",
            repository_id=repo_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        overlay_names = []
        result.failures.append("qdrant_overlays_enum")

    for name in overlay_names:
        try:
            ok = await sync_to_async(QdrantService.delete_by_payload_field)(
                name, "file_path", rel_path
            )
            if ok:
                result.qdrant_overlays += 1
            else:
                result.failures.append(f"qdrant_overlay:{name}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "purge_file.overlay_delete_failed",
                repository_id=repo_id,
                collection_name=name,
                rel_path=rel_path,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            result.failures.append(f"qdrant_overlay:{name}")

    # --- 3. FileIndex ---
    try:
        from repositories.models import FileIndex

        deleted, _ = await FileIndex.objects.filter(
            repository_id=repo_id, file_path=rel_path
        ).adelete()
        result.file_index_deleted = int(deleted)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "purge_file.file_index_failed",
            repository_id=repo_id,
            rel_path=rel_path,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        result.failures.append("file_index")

    # --- 4. ChunkRegistry（+ ChunkEdge via pre_delete 信号，PF-03）---
    # 务必走 queryset.adelete() 逐实例触发 pre_delete，联动清边 + 调度 reconcile；
    # 绝不绕过信号（否则指向被删 chunk 的 ChunkEdge 成孤儿）。
    try:
        from code_relations.models import ChunkRegistry

        deleted, _ = await ChunkRegistry.objects.filter(
            repository_id=repo_id, file_path=rel_path
        ).adelete()
        result.chunk_registry_deleted = int(deleted)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "purge_file.chunk_registry_failed",
            repository_id=repo_id,
            rel_path=rel_path,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        result.failures.append("chunk_registry")

    # --- 5. codegraph（Symbol / ImportEdge / Endpoint / CallEdge）逐分支 ---
    try:
        from codegraph.services.graph_writer import GraphWriter

        branches = await _branch_names(repo_id)
        writer = GraphWriter()
        total = 0
        for branch_name in branches:
            total += await writer.adelete_for_files(repo_id, [rel_path], branch_name=branch_name)
        result.codegraph_deleted = int(total)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "purge_file.codegraph_failed",
            repository_id=repo_id,
            rel_path=rel_path,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        result.failures.append("codegraph")

    logger.info(
        "purge_file.completed",
        repository_id=repo_id,
        rel_path=rel_path,
        qdrant_main=result.qdrant_main,
        qdrant_overlays=result.qdrant_overlays,
        file_index_deleted=result.file_index_deleted,
        chunk_registry_deleted=result.chunk_registry_deleted,
        codegraph_deleted=result.codegraph_deleted,
        failures=result.failures,
    )
    return result
