"""`file:line → chunk_id` 反查服务（Phase 25 IDX-02 后半）。

给定 仓库 + 文件 + 行号，定位覆盖该行的 chunk(s)。命中条件：
``repository_id + file_path + branch_name`` 一致，且 ``line_start <= line <= line_end``
（1-based 闭区间，行号由 25-01 在索引时回填进 ``ChunkRegistry``）。

安全边界（复用 Phase 22 排除单一匹配器，DOMAIN §9.1）：被排除文件全程 fail-closed
—— 经 ``build_matcher_for_repo`` 取匹配器，命中排除规则则返回空列表并打 ``exclusion.blocked``
审计埋点，**绝不**经此面泄漏被排除文件的 chunk_id / 行位置（T-25-04）。失败模式一律
fail-closed：matcher 构造异常、路径归一越界、判定异常都视为「不可见」返回空列表，对齐
``services/retrieval/rag_search.py`` 范式（per D-03 / D-04）。

仅读 ``ChunkRegistry``，不触 Qdrant。
"""

from __future__ import annotations

import structlog
from asgiref.sync import sync_to_async

from services.exclusion import (
    build_matcher_for_repo,
    log_exclusion_blocked,
    normalize_rel_path,
)

logger = structlog.get_logger(__name__)

__all__ = ["find_chunk_at"]


async def find_chunk_at(
    repository_id: str,
    file_path: str,
    line: int,
    *,
    branch_name: str = "",
) -> list[dict]:
    """返回覆盖 ``file_path:line`` 的 chunk 列表，最具体（区间最小）优先。

    流程（每步 fail-closed）：
    1. ``build_matcher_for_repo`` 取匹配器；构造异常 → 埋点 + 返回 ``[]``（绝不放行）。
    2. ``normalize_rel_path`` 归一；越界/非法（None）→ 返回 ``[]``。
    3. ``matcher.is_excluded`` 为 True（含判定异常视为 True）→ 埋点 + 返回 ``[]``。
    4. 查 ``ChunkRegistry``：repo + file_path + branch_name + 行号闭区间命中。
    5. 按覆盖区间宽度 ``(line_end - line_start)`` 升序排序（最具体优先），返回全部命中。

    返回每项：``{"chunk_id", "file_path", "line_start", "line_end", "chunk_index"}``。
    """
    # 1. 构造匹配器（fail-closed：构造失败一律视为排除，不放行）
    try:
        matcher = await build_matcher_for_repo(repository_id)
    except Exception as exc:  # noqa: BLE001 — 构造失败一律 fail-closed（T-25-04，对齐 rag_search）
        logger.warning(
            "chunk_lookup_matcher_build_failed",
            repository_id=repository_id,
            error=str(exc),
        )
        log_exclusion_blocked(
            surface="chunk_at", repository_id=repository_id, rel_path=str(file_path)
        )
        return []

    # 2. 路径归一（越界/绝对路径/非法 → None → 空返回，T-25-07）
    norm_path = normalize_rel_path(file_path)
    if norm_path is None:
        return []

    # 3. 排除判定（is_excluded 自身对判定异常 fail-closed 返回 True）
    if matcher.is_excluded(norm_path):
        log_exclusion_blocked(
            surface="chunk_at", repository_id=repository_id, rel_path=norm_path
        )
        return []

    # 4. 查询覆盖该行的 chunk（仅命中已回填行号的 row，NULL 行号天然排除）
    rows = await _query_covering_chunks(repository_id, norm_path, line, branch_name)

    # 5. 最具体优先：区间宽度升序（次序稳定按 chunk_index）
    rows.sort(key=lambda r: (r["line_end"] - r["line_start"], r["chunk_index"]))
    return rows


@sync_to_async
def _query_covering_chunks(
    repository_id: str, file_path: str, line: int, branch_name: str
) -> list[dict]:
    """同步 ORM 查询：命中覆盖 ``line`` 的 chunk row（经 sync_to_async 在异步上下文调用）。"""
    from code_relations.models import ChunkRegistry

    qs = ChunkRegistry.objects.filter(
        repository_id=repository_id,
        file_path=file_path,
        branch_name=branch_name,
        line_start__isnull=False,
        line_end__isnull=False,
        line_start__lte=line,
        line_end__gte=line,
    ).values("chunk_id", "file_path", "line_start", "line_end", "chunk_index")

    return [
        {
            "chunk_id": str(r["chunk_id"]),
            "file_path": r["file_path"],
            "line_start": r["line_start"],
            "line_end": r["line_end"],
            "chunk_index": r["chunk_index"],
        }
        for r in qs
    ]
