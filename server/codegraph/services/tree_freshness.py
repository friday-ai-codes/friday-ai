"""能力树增量新鲜度维护（webhook 分层刷新，从不同步调 claude code）。

索引完成（含 webhook 自动索引）后调用 apply_index_delta：

1. 把本次变更文件路径映射到树节点 paths——命中已有节点 → 节点标 stale
   （描述可能过时），树结构不动；
2. 未被任何节点覆盖的新顶级目录 → 记入 new_paths；
3. 阈值判定：出现新顶级目录 / stale 节点占比超 30% / 树龄超 30 天且有变更
   → 异步重新 dispatch repo_summary（claude code 容器任务）重建树。

事实层（节点 payload 的 facets / api_domains）刷新由调用方走
RepoIndexTreeBuilder.refresh_facts + FacetService，零 LLM。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

STALE_RATIO_THRESHOLD = 0.30
REBUILD_MAX_AGE_DAYS = 30

# 与索引无关的顶级目录变化不应触发树重建
_IGNORED_TOP_DIRS = {
    ".github", ".gitlab", ".vscode", ".idea", "node_modules",
    "dist", "build", "out", "vendor", "__pycache__",
}


def _collect_node_paths(tree: list[dict[str, Any]]) -> list[tuple[str, list[str]]]:
    """扁平化 (node_id, paths)。"""
    out: list[tuple[str, list[str]]] = []
    stack = list(tree or [])
    while stack:
        node = stack.pop()
        out.append((str(node.get("node_id", "")), list(node.get("paths", []))))
        stack.extend(node.get("children", []))
    return out


def evaluate_delta(
    tree: list[dict[str, Any]], changed_files: list[str]
) -> tuple[set[str], set[str]]:
    """变更文件 → (命中的 stale 节点 id 集合, 未覆盖的新顶级目录集合)。"""
    node_paths = _collect_node_paths(tree)
    top_dirs_in_tree: set[str] = set()
    for _, paths in node_paths:
        for p in paths:
            seg = p.strip("/").split("/")[0]
            if seg:
                top_dirs_in_tree.add(seg)

    stale_ids: set[str] = set()
    uncovered_top_dirs: set[str] = set()

    for raw in changed_files:
        f = str(raw).strip("/")
        if not f:
            continue
        covered = False
        for node_id, paths in node_paths:
            if any(f == p or f.startswith(p + "/") for p in paths if p):
                stale_ids.add(node_id)
                covered = True
        if not covered:
            top = f.split("/")[0]
            # 根目录散文件（如 README.md）不算新顶级目录
            if "/" in f and top not in top_dirs_in_tree and top not in _IGNORED_TOP_DIRS:
                uncovered_top_dirs.add(top)

    return stale_ids, uncovered_top_dirs


async def apply_index_delta(
    repository_id: str, changed_files: list[str]
) -> dict[str, Any]:
    """索引完成后的树新鲜度维护入口。

    Returns:
        {"status": "skipped"|"marked"|"rebuild_dispatched", ...}
    """
    from repositories.models import AISummaryStatus, Repository

    repo = await Repository.objects.filter(id=repository_id).afirst()
    if repo is None:
        return {"status": "skipped", "reason": "repo_not_found"}
    if not repo.ai_summary_tree:
        # 尚无树：不自动 dispatch（成本控制），由回填命令/手动触发负责
        return {"status": "skipped", "reason": "no_tree"}
    if not changed_files:
        return {"status": "skipped", "reason": "no_changes"}

    stale_ids, new_top_dirs = evaluate_delta(repo.ai_summary_tree, changed_files)

    state = dict(repo.tree_stale_state or {})
    accumulated_stale = set(state.get("stale_node_ids", [])) | stale_ids
    accumulated_new = set(state.get("new_paths", [])) | new_top_dirs

    total_nodes = len(_collect_node_paths(repo.ai_summary_tree)) or 1
    stale_ratio = len(accumulated_stale) / total_nodes

    tree_age_exceeded = False
    if repo.ai_summary_generated_at is not None:
        age = datetime.now(UTC) - repo.ai_summary_generated_at
        tree_age_exceeded = age > timedelta(days=REBUILD_MAX_AGE_DAYS)

    should_rebuild = bool(accumulated_new) or stale_ratio > STALE_RATIO_THRESHOLD or (
        tree_age_exceeded and (accumulated_stale or stale_ids)
    )

    repo.tree_stale_state = {
        "stale_node_ids": sorted(accumulated_stale),
        "new_paths": sorted(accumulated_new),
        "evaluated_at": datetime.now(UTC).isoformat(),
    }
    await repo.asave(update_fields=["tree_stale_state", "updated_at"])

    if not should_rebuild:
        logger.info(
            "tree_freshness_marked",
            repository_id=repository_id,
            stale_count=len(accumulated_stale),
            stale_ratio=round(stale_ratio, 3),
            new_top_dirs=sorted(accumulated_new),
        )
        return {
            "status": "marked",
            "stale_count": len(accumulated_stale),
            "stale_ratio": stale_ratio,
        }

    # 阈值命中 → 异步重建树（防重入：已有 pending/running 任务则跳过）
    if repo.ai_summary_status in (AISummaryStatus.PENDING, AISummaryStatus.RUNNING):
        return {"status": "marked", "reason": "rebuild_already_in_flight"}

    from repositories.summary_service import dispatch_repo_summary

    try:
        session_id = await dispatch_repo_summary(repo)
    except Exception:  # noqa: BLE001 — dispatch 失败不阻塞索引收尾
        logger.warning(
            "tree_rebuild_dispatch_failed",
            repository_id=repository_id,
            exc_info=True,
        )
        return {"status": "marked", "reason": "dispatch_failed"}

    logger.info(
        "tree_rebuild_dispatched",
        repository_id=repository_id,
        session_id=session_id,
        stale_ratio=round(stale_ratio, 3),
        new_top_dirs=sorted(accumulated_new),
        tree_age_exceeded=tree_age_exceeded,
    )
    return {"status": "rebuild_dispatched", "session_id": session_id}


__all__ = ["apply_index_delta", "evaluate_delta"]
