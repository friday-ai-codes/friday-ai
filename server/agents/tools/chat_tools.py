"""Chat 对话工具 — 项目知识检索 + 深度分析。

检索工具（数据来自 Qdrant 已索引内容）：
- browse_file_content: 浏览已索引文件内容（按 chunk 返回）
- list_space_structure: 查看空间文件树结构
- get_space_overview: 获取空间概览信息

深度分析工具：
- deep_analysis: 将复杂分析任务 dispatch 到 Runner 上的 Claude Code 执行
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from qdrant_client.http import models as qdrant_models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from agents.tools.base import ToolResult, tool
from projects.models import Project
from repositories.models import Repository
from services.exclusion import build_matcher_for_repo, log_exclusion_blocked
from services.qdrant_service import QdrantService

logger = structlog.get_logger(__name__)


async def _build_matcher_failclosed(repository_id: str) -> Any:
    """获取仓库排除匹配器（EXCL-02 单一匹配器）；构造异常 → 返回 ``None``（fail-closed 兜底）。

    调用方用 ``_matcher_excludes(matcher, path)`` 判定，``None`` 一律视为命中（拒读/过滤），
    绝不在匹配器不可用时降级放行被排除文件。
    """
    try:
        return await build_matcher_for_repo(repository_id)
    except Exception:  # noqa: BLE001 — 构造失败一律 fail-closed
        logger.warning("exclusion.matcher_build_failed", repository_id=repository_id)
        return None


def _matcher_excludes(matcher: Any, rel_path: str) -> bool:
    """fail-closed 判定：``matcher`` 缺失或判定异常一律视为「已排除」。"""
    if matcher is None:
        return True
    try:
        return matcher.is_excluded(rel_path)
    except Exception:  # noqa: BLE001 — 判定异常 → fail-closed
        return True


def _excluded_browse_result(repository_id: str, file_path: str) -> ToolResult:
    """browse_file_content 命中排除的拒读返回（chunks=[]，绝不带任何明文）。"""
    return ToolResult(
        success=True,
        output={
            "data": {
                "file_path": file_path,
                "repository_id": repository_id,
                "chunks": [],
                "total_chunks": 0,
            },
            "error": "File is excluded by policy",
        },
    )


# (collection_name) -> (expires_at_unix_ts, sorted_file_paths)
# 60s TTL 足够覆盖一次 LLM 的连续 N 次失败重试；过期后再 scroll 一次。
# 索引完成 / 文件新增不会立刻反映到 chat，可接受。
_PATH_CACHE_TTL_SECONDS: float = 60.0
_indexed_paths_cache: dict[str, tuple[float, list[str]]] = {}
# 文件清单 scroll 兜底上限（×1000 points）：避免超大 collection 全量 scroll 拖慢工具。
_MAX_SCROLL_BATCHES: int = 40


# ---------------------------------------------------------------------------
# 共享 scroll 辅助 — 按 collection 名 + file_path 拉取全部 chunk
# ---------------------------------------------------------------------------


@sync_to_async  # KEEP: Qdrant SDK 同步限制
def _scroll_file_from_collection(collection_name: str, file_path: str) -> list[dict[str, Any]]:
    """从指定 collection 按 file_path 拉取所有 chunk payload。"""
    try:
        client = QdrantService.get_client()
        all_points: list[dict[str, Any]] = []
        offset = None

        while True:
            result = client.scroll(
                collection_name=collection_name,
                scroll_filter=qdrant_models.Filter(
                    must=[
                        qdrant_models.FieldCondition(
                            key="file_path",
                            match=qdrant_models.MatchValue(value=file_path),
                        )
                    ]
                ),
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            points, next_offset = result
            for point in points:
                if point.payload:
                    all_points.append(point.payload)
            if next_offset is None:
                break
            offset = next_offset

        return all_points
    except (ResponseHandlingException, UnexpectedResponse) as e:
        logger.warning(
            "qdrant_scroll_failed", collection=collection_name, file_path=file_path, error=str(e)
        )
        return []


@sync_to_async  # KEEP: Qdrant SDK 同步限制
def _list_indexed_paths(collection_name: str) -> list[str]:
    """列出 collection 内所有去重的 file_path，带 TTL 缓存。

    使用场景：browse_file_content 严格 file_path 匹配失败时做 endswith 兜底。
    LLM 在 monorepo 场景常把仓库名误拼成目录前缀（如把 'apps/foo.vue' 写成
    'apps/<repo-name>/src/apps/foo.vue'），用真实文件清单做后缀匹配可纠正。

    实现：scroll 全部 points 只取 file_path payload。每次 scroll batch=1000，
    19913 points ≈ 20 次 scroll < 1s；命中缓存时 ~0ms。
    """
    cached = _indexed_paths_cache.get(collection_name)
    now = time.monotonic()
    if cached and cached[0] > now:
        return cached[1]

    try:
        client = QdrantService.get_client()
        seen: set[str] = set()
        offset = None
        # 兜底上限：超大 collection 下 scroll 全量会拖慢工具调用（甚至拉长整个 turn
        # 触发客户端/网关超时）；最多扫 _MAX_SCROLL_BATCHES×1000 个 point 即停（足够
        # 覆盖绝大多数仓库的文件清单，仅用于 endswith 兜底匹配，部分清单可接受）。
        for _ in range(_MAX_SCROLL_BATCHES):
            result = client.scroll(
                collection_name=collection_name,
                limit=1000,
                offset=offset,
                with_payload=["file_path"],
                with_vectors=False,
            )
            points, next_offset = result
            for p in points:
                if p.payload:
                    fp = p.payload.get("file_path")
                    if isinstance(fp, str) and fp:
                        seen.add(fp)
            if next_offset is None:
                break
            offset = next_offset
        paths = sorted(seen)
        _indexed_paths_cache[collection_name] = (now + _PATH_CACHE_TTL_SECONDS, paths)
        return paths
    except (ResponseHandlingException, UnexpectedResponse) as e:
        logger.warning("qdrant_list_paths_failed", collection=collection_name, error=str(e))
        return []


def _resolve_fuzzy_path(
    requested: str,
    indexed_paths: list[str],
    *,
    max_candidates: int = 5,
) -> list[str]:
    """从 indexed_paths 里找与 requested 路径"尾部对齐"的真实路径候选。

    匹配优先级（由严到松）:
      1. 完整路径 endswith requested —— LLM 路径就是真实路径的尾段，最理想。
      2. 真实路径 endswith requested 的尾 N 段（N 从全部段数递减到 2 段，
         一旦命中即停止下探，保证返回最长尾匹配）。
      3. 都没命中返回 basename（文件名）相同的候选，作为提示。

    举例：requested='apps/study-app/src/apps/foo/index.vue'，indexed 含
    'apps/foo/index.vue'。step 1 失败，step 2 用尾段 'apps/foo/index.vue'
    匹配命中。

    Args:
        requested: LLM 提供的 file_path（可能多了仓库名前缀等噪声）
        indexed_paths: 真实索引的 file_path 全集
        max_candidates: 至多返回多少个候选（截断防止前端噪声）
    """
    if not indexed_paths:
        return []

    # Step 1: 完整 endswith
    direct = [p for p in indexed_paths if p.endswith(requested)]
    if direct:
        return direct[:max_candidates]

    # Step 2: 用 requested 的尾 N 段反向匹配
    segments = [s for s in requested.split("/") if s]
    for n in range(len(segments), 1, -1):
        suffix = "/".join(segments[-n:])
        hits = [p for p in indexed_paths if p.endswith(suffix)]
        if hits:
            return hits[:max_candidates]

    # Step 3: basename 同名（最后的 hint，可能噪声大，仅作建议）
    basename = segments[-1] if segments else requested
    basename_hits = [p for p in indexed_paths if p.endswith("/" + basename) or p == basename]
    return basename_hits[:max_candidates]


@tool(
    name="browse_file_content",
    description=(
        "Browse the content of an indexed file by file path. "
        "Returns file content as chunks ordered by position. "
        "Optionally filter by line range to reduce output."
    ),
    category="PROJECT",
    parameters={
        "type": "object",
        "properties": {
            "repository_id": {
                "type": "string",
                "description": "UUID of the repository containing the file",
            },
            "file_path": {
                "type": "string",
                "description": "Full file path within the repository",
            },
            "start_line": {
                "type": "integer",
                "description": "Start line number (1-based, optional)",
            },
            "end_line": {
                "type": "integer",
                "description": "End line number (1-based, optional)",
            },
            "branch": {
                "type": "string",
                "description": "Branch name for branch-aware file browsing (optional)",
            },
        },
        "required": ["repository_id", "file_path"],
    },
)
async def browse_file_content(
    repository_id: str,
    file_path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    branch: str | None = None,
) -> ToolResult:
    """浏览已索引文件的内容。

    从 Qdrant 按 file_path 过滤获取所有 chunk，
    按 chunk_index 排序后返回。支持行范围过滤和分支感知路由。
    """
    logger.info(
        "browse_file_content",
        repository_id=repository_id,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        branch=branch,
    )

    # EXCL-02 fail-closed：入口即按 (repository_id, file_path) 判定排除，命中拒读，
    # 绝不进入 scroll 返回任何 chunk 明文（T-22-08）。
    matcher = await _build_matcher_failclosed(repository_id)
    if _matcher_excludes(matcher, file_path):
        log_exclusion_blocked(
            surface="browse_file_content", repository_id=repository_id, rel_path=str(file_path)
        )
        return _excluded_browse_result(repository_id, file_path)

    chunks_raw: list[dict[str, Any]] = []

    # 分支路由：功能分支文件需要从 overlay collection 获取
    if branch:
        from repositories.models import BranchFileIndex
        from services.branch_utils import (
            is_branch_index_enabled_async,
            resolve_branch_for_query,
        )

        if await is_branch_index_enabled_async(repository_id):
            _, branch_index = await resolve_branch_for_query(repository_id, branch)
            if (
                branch_index
                and not branch_index.is_base_branch
                and branch_index.status != "inherited"
            ):
                file_change = await BranchFileIndex.objects.filter(
                    branch_index=branch_index, file_path=file_path
                ).afirst()

                if file_change and file_change.change_type == "deleted":
                    return ToolResult(
                        success=True,
                        output={
                            "data": {
                                "file_path": file_path,
                                "repository_id": repository_id,
                                "branch": branch,
                                "chunks": [],
                                "total_chunks": 0,
                            },
                            "error": "File deleted in this branch",
                        },
                    )

                if (
                    file_change
                    and file_change.change_type in ("added", "modified")
                    and branch_index.collection_name
                ):
                    chunks_raw = await _scroll_file_from_collection(
                        branch_index.collection_name, file_path
                    )

    # 默认：从 base collection 获取（未命中分支路由或无 branch 参数）
    base_collection = QdrantService.get_collection_name(repository_id)
    if not chunks_raw:
        chunks_raw = await _scroll_file_from_collection(base_collection, file_path)

    # 严格匹配失败兜底：用 endswith 模糊查真实路径，纠正 LLM 路径 hallucination。
    # 常见场景：monorepo 仓库里 LLM 把仓库名当作目录前缀拼进路径。
    resolved_path = file_path
    if not chunks_raw:
        indexed_paths = await _list_indexed_paths(base_collection)
        candidates = _resolve_fuzzy_path(file_path, indexed_paths)

        if len(candidates) == 1:
            # 唯一匹配：直接用真实路径重 scroll，对 LLM 透明
            resolved_path = candidates[0]
            # 后缀解析出的真实路径必须复判（防止经 endswith 匹配绕过排除，T-22-09）。
            if _matcher_excludes(matcher, resolved_path):
                log_exclusion_blocked(
                    surface="browse_file_content",
                    repository_id=repository_id,
                    rel_path=str(resolved_path),
                )
                return _excluded_browse_result(repository_id, resolved_path)
            logger.info(
                "browse_file_content_fuzzy_resolved",
                requested=file_path,
                resolved=resolved_path,
                repository_id=repository_id,
            )
            chunks_raw = await _scroll_file_from_collection(base_collection, resolved_path)

        elif len(candidates) > 1:
            # 多候选：让 LLM 选，避免猜错
            logger.info(
                "browse_file_content_fuzzy_ambiguous",
                requested=file_path,
                candidate_count=len(candidates),
                repository_id=repository_id,
            )
            return ToolResult(
                success=True,
                output={
                    "data": {
                        "file_path": file_path,
                        "repository_id": repository_id,
                        "chunks": [],
                        "total_chunks": 0,
                        "candidates": candidates,
                    },
                    "error": (
                        f"File not found at exact path '{file_path}'. "
                        f"Found {len(candidates)} similar indexed files; "
                        f"retry with one of: {candidates}"
                    ),
                },
            )

    if not chunks_raw:
        # 仍未命中：在 error 里附 basename-level 提示，帮 LLM 修正
        indexed_paths = await _list_indexed_paths(base_collection)
        hints = _resolve_fuzzy_path(file_path, indexed_paths, max_candidates=3)
        hint_str = f" Did you mean any of: {hints}?" if hints else ""
        return ToolResult(
            success=True,
            output={
                "data": {
                    "file_path": file_path,
                    "repository_id": repository_id,
                    "chunks": [],
                    "total_chunks": 0,
                },
                "error": f"File not found in index: {file_path}.{hint_str}",
            },
        )

    # 按 chunk_index 排序
    chunks_raw.sort(key=lambda c: c.get("chunk_index", 0))

    # 行范围过滤
    chunks = []
    for chunk in chunks_raw:
        chunk_start = chunk.get("start_line", 0)
        chunk_end = chunk.get("end_line", float("inf"))

        if start_line is not None and chunk_end < start_line:
            continue
        if end_line is not None and chunk_start > end_line:
            continue

        chunks.append(
            {
                "content": chunk.get("content", ""),
                "chunk_index": chunk.get("chunk_index", 0),
                "start_line": chunk.get("start_line"),
                "end_line": chunk.get("end_line"),
                "language": chunk.get("language", ""),
            }
        )

    logger.info(
        "browse_file_content_success",
        requested_file_path=file_path,
        resolved_file_path=resolved_path,
        total_chunks=len(chunks),
    )

    output_data: dict[str, Any] = {
        "file_path": resolved_path,
        "repository_id": repository_id,
        "chunks": chunks,
        "total_chunks": len(chunks),
    }
    # 仅当真做了路径纠正时附 requested_file_path 字段，避免噪声
    if resolved_path != file_path:
        output_data["requested_file_path"] = file_path
        output_data["resolved_note"] = (
            f"Requested path '{file_path}' was not indexed; auto-resolved to "
            f"'{resolved_path}' via suffix match."
        )

    return ToolResult(
        success=True,
        output={"data": output_data},
    )


@tool(
    name="list_space_structure",
    description=(
        "列出项目下已索引仓库的文件树结构（缩进格式 + 语言标注）。\n"
        "- 不传 repository_id：列出空间下所有已索引仓库的文件树（每个仓库一棵树）\n"
        "- 传 repository_id：只列该单个仓库（深度分析模式下常用 ——"
        "  先 list_space_repositories 选中相关仓库，再单仓库列文件树定位入口）"
    ),
    category="PROJECT",
    parameters={
        "type": "object",
        "properties": {
            "space_id": {
                "type": "string",
                "description": "UUID of the project to query",
            },
            "repository_id": {
                "type": "string",
                "description": ("可选：限定到单个仓库的 UUID。不传则列出空间下所有已索引仓库。"),
            },
            "branch": {
                "type": "string",
                "description": "Branch name for branch-aware file tree (optional)",
            },
        },
        "required": ["space_id"],
    },
)
async def list_space_structure(
    space_id: str,
    repository_id: str | None = None,
    branch: str | None = None,
) -> ToolResult:
    """查看空间文件树结构。

    查询项目关联的所有已索引仓库（或单个指定仓库），从 Qdrant 获取
    文件路径列表，构建缩进格式的树状结构。
    """
    logger.info(
        "list_space_structure",
        space_id=space_id,
        repository_id=repository_id,
    )

    # 获取已索引仓库（可选按 repository_id 过滤为单仓库）
    repo_filter = Repository.objects.filter(
        projects__id=space_id,
        index_status="indexed",
        is_deleted=False,
    )
    if repository_id:
        repo_filter = repo_filter.filter(id=repository_id)
    indexed_repos = [repo async for repo in repo_filter]

    if not indexed_repos:
        if repository_id:
            err_msg = (
                f"Repository {repository_id} not found in space {space_id} "
                f"(either not indexed, deleted, or not associated with this space)"
            )
        else:
            err_msg = "No indexed repositories found for this project"
        return ToolResult(
            success=True,
            output={
                "data": {
                    "space_id": space_id,
                    "repository_id": repository_id,
                    "structure": "",
                    "total_files": 0,
                },
                "error": err_msg,
            },
        )

    @sync_to_async  # KEEP: Qdrant SDK 同步限制
    def _get_file_paths(repo_id: str) -> list[dict[str, str]]:
        try:
            client = QdrantService.get_client()
            collection = QdrantService.get_collection_name(repo_id)

            file_info: dict[str, str] = {}  # path -> language
            offset = None

            while True:
                result = client.scroll(
                    collection_name=collection,
                    scroll_filter=None,
                    limit=1000,
                    offset=offset,
                    with_payload=["file_path", "language"],
                    with_vectors=False,
                )

                points, next_offset = result

                for point in points:
                    if point.payload:
                        fp = point.payload.get("file_path", "")
                        lang = point.payload.get("language", "")
                        if fp and fp not in file_info:
                            file_info[fp] = lang

                if next_offset is None:
                    break
                offset = next_offset

            return [{"path": p, "language": lang} for p, lang in sorted(file_info.items())]
        except UnexpectedResponse:
            return []

    # 收集所有仓库的文件信息
    all_files: list[dict[str, str]] = []
    repo_names: dict[str, str] = {}

    for repo in indexed_repos:
        repo_id = str(repo.id)
        repo_names[repo_id] = repo.name
        files = await _get_file_paths(repo_id)
        for f in files:
            f["repo_name"] = repo.name

        # 分支视图叠加：base 文件树 + BranchFileIndex 差异
        if branch:
            from repositories.models import BranchFileIndex
            from services.branch_utils import (
                is_branch_index_enabled_async,
                resolve_branch_for_query,
            )

            if await is_branch_index_enabled_async(repo_id):
                _, branch_index = await resolve_branch_for_query(repo_id, branch)
                if (
                    branch_index
                    and not branch_index.is_base_branch
                    and branch_index.status != "inherited"
                ):
                    added: set[str] = set()
                    deleted: set[str] = set()
                    async for fi in BranchFileIndex.objects.filter(
                        branch_index=branch_index,
                    ):
                        if fi.change_type == "added":
                            added.add(fi.file_path)
                        elif fi.change_type == "deleted":
                            deleted.add(fi.file_path)

                    base_paths = {f["path"] for f in files}
                    final_paths = (base_paths - deleted) | added

                    base_map = {f["path"]: f for f in files}
                    merged_files: list[dict[str, str]] = []
                    for p in sorted(final_paths):
                        if p in base_map:
                            merged_files.append(base_map[p])
                        else:
                            merged_files.append(
                                {
                                    "path": p,
                                    "language": "",
                                    "repo_name": repo.name,
                                }
                            )
                    files = merged_files

        # EXCL-02 fail-closed：按各自 repo 的匹配器过滤被排除文件，不进入文件树。
        repo_matcher = await _build_matcher_failclosed(repo_id)
        kept_files = [f for f in files if not _matcher_excludes(repo_matcher, f["path"])]
        if len(kept_files) != len(files):
            log_exclusion_blocked(
                surface="list_space_structure", repository_id=repo_id, rel_path=""
            )
        files = kept_files

        all_files.extend(files)

    # 构建树状结构
    tree_lines: list[str] = []
    for repo in indexed_repos:
        repo_files = [f for f in all_files if f["repo_name"] == repo.name]
        if not repo_files:
            continue

        tree_lines.append(f"{repo.name}/")
        tree_lines.extend(_build_tree(repo_files))

    structure = "\n".join(tree_lines)
    total_files = len(all_files)

    logger.info(
        "list_space_structure_success",
        space_id=space_id,
        repository_id=repository_id,
        total_files=total_files,
    )

    return ToolResult(
        success=True,
        output={
            "data": {
                "space_id": space_id,
                "repository_id": repository_id,
                "structure": structure,
                "total_files": total_files,
            },
        },
    )


def _build_tree(files: list[dict[str, str]]) -> list[str]:
    """从文件列表构建缩进格式的树状结构。"""
    # 按路径分组到目录
    tree: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for f in files:
        path = f["path"]
        parts = path.rsplit("/", 1)
        if len(parts) == 2:
            directory, filename = parts
        else:
            directory, filename = "", parts[0]
        lang = f.get("language", "")
        tree[directory].append((filename, lang))

    # 排序：收集所有目录路径
    all_dirs = sorted(tree.keys())
    lines: list[str] = []

    for d in all_dirs:
        # 目录行（缩进级别 = 路径深度）
        if d:
            depth = d.count("/") + 1
            indent = "  " * depth
            dir_name = d.rsplit("/", 1)[-1]
            lines.append(f"{indent}{dir_name}/")

        # 文件行
        file_depth = (d.count("/") + 2) if d else 1
        file_indent = "  " * file_depth
        for filename, lang in sorted(tree[d]):
            lang_tag = f" [{lang}]" if lang else ""
            lines.append(f"{file_indent}{filename}{lang_tag}")

    return lines


@tool(
    name="get_space_overview",
    description=(
        "Get an overview of a project including name, description, "
        "linked repositories with their index status, file counts, "
        "and language distribution."
    ),
    category="PROJECT",
    parameters={
        "type": "object",
        "properties": {
            "space_id": {
                "type": "string",
                "description": "UUID of the project to query",
            },
            "branch": {
                "type": "string",
                "description": "Branch name for branch-aware overview (optional)",
            },
        },
        "required": ["space_id"],
    },
)
async def get_space_overview(
    space_id: str,
    branch: str | None = None,
) -> ToolResult:
    """获取空间概览信息。

    返回项目基本信息、关联仓库列表（含索引状态、文件数、语言分布）。
    """
    logger.info("get_space_overview", space_id=space_id)

    try:
        project = await Project.objects.aget(id=space_id)
    except Project.DoesNotExist:
        return ToolResult(
            success=True,
            output={
                "data": None,
                "error": f"Space not found: {space_id}",
            },
        )

    # 获取关联仓库
    repositories = [
        repo
        async for repo in Repository.objects.filter(
            projects=project,
            is_deleted=False,
        )
    ]

    @sync_to_async  # KEEP: Qdrant SDK 同步限制
    def _get_repo_stats(repo_id: str) -> dict[str, Any]:
        """获取仓库的文件数和语言分布。"""
        try:
            client = QdrantService.get_client()
            collection = QdrantService.get_collection_name(repo_id)

            file_paths: set[str] = set()
            language_counts: dict[str, int] = defaultdict(int)
            offset = None

            while True:
                result = client.scroll(
                    collection_name=collection,
                    scroll_filter=None,
                    limit=1000,
                    offset=offset,
                    with_payload=["file_path", "language"],
                    with_vectors=False,
                )

                points, next_offset = result

                for point in points:
                    if point.payload:
                        fp = point.payload.get("file_path", "")
                        lang = point.payload.get("language", "")
                        if fp:
                            file_paths.add(fp)
                        if lang:
                            language_counts[lang] += 1

                if next_offset is None:
                    break
                offset = next_offset

            return {
                "file_count": len(file_paths),
                "languages": dict(
                    sorted(
                        language_counts.items(),
                        key=lambda x: x[1],
                        reverse=True,
                    )
                ),
            }
        except (ResponseHandlingException, UnexpectedResponse) as e:
            logger.warning("qdrant_repo_stats_failed", repo_id=repo_id, error=str(e))
            return {"file_count": 0, "languages": {}}

    repo_data = []
    for repo in repositories:
        repo_info: dict[str, Any] = {
            "id": str(repo.id),
            "name": repo.name,
            "index_status": repo.index_status,
        }

        if repo.index_status == "indexed":
            stats = await _get_repo_stats(str(repo.id))
            repo_info["file_count"] = stats["file_count"]
            repo_info["languages"] = stats["languages"]

            # 分支统计调整
            if branch:
                from repositories.models import BranchFileIndex
                from services.branch_utils import (
                    is_branch_index_enabled_async,
                    resolve_branch_for_query,
                )

                repo_id_str = str(repo.id)
                if await is_branch_index_enabled_async(repo_id_str):
                    _, branch_index = await resolve_branch_for_query(repo_id_str, branch)
                    if (
                        branch_index
                        and not branch_index.is_base_branch
                        and branch_index.status != "inherited"
                    ):
                        added_count = await BranchFileIndex.objects.filter(
                            branch_index=branch_index, change_type="added"
                        ).acount()
                        deleted_count = await BranchFileIndex.objects.filter(
                            branch_index=branch_index, change_type="deleted"
                        ).acount()
                        repo_info["file_count"] = (
                            repo_info["file_count"] - deleted_count + added_count
                        )
                        repo_info["branch"] = branch
        else:
            repo_info["file_count"] = 0
            repo_info["languages"] = {}

        repo_data.append(repo_info)

    logger.info(
        "get_space_overview_success",
        space_id=space_id,
        repo_count=len(repo_data),
    )

    return ToolResult(
        success=True,
        output={
            "data": {
                "project_name": project.name,
                "description": project.description or "",
                "space_id": str(project.id),
                "repositories": repo_data,
                "total_repositories": len(repo_data),
            },
        },
    )


# ============================================================================
# 深度分析工具 — dispatch 到 Runner 上的 Claude Code
# ============================================================================

DEEP_ANALYSIS_TIMEOUT = 1800  # 30 分钟


@tool(
    name="deep_analysis",
    description=(
        "对指定仓库启动一个 Claude Code 容器做深度代码分析（远程 Runner 执行，"
        "Claude Code 拥有完整仓库 fs 访问 + 多文件交叉阅读 + 代码执行能力）。\n"
        "适合：架构梳理、跨模块追踪、复杂业务逻辑理解、需要多文件综合的问答。\n\n"
        "**并行 dispatch 强烈推荐**：\n"
        "  在同一轮 tool_calls 里可以对**不同 repository_id** emit 多个 deep_analysis 调用，"
        "系统会并行 dispatch 多个 Claude Code 容器同时工作。\n"
        "  跨仓库问题（如「书房入口→错题本跳转」涉及 2 个仓库）必须同时 emit "
        "两个 deep_analysis（每个仓库一个），不要串行等待。\n"
        "  同一 repository_id 同一 conversation 内只允许一个 in-flight 容器（重复调用会复用），\n"
        "  所以「同仓库不同角度」的问题请合并到一个 task_description 里。\n\n"
        "Dispatch 后立即返回 blocking marker，系统会等所有并行任务完成后统一回灌结果。"
        "\n\n"
        "**完成回流**（implementation）：每次容器完成时 Server 端会自动回算 "
        "cross_repo_relevance —— 结果落 RepositoryRoutingTrace（triggered_by="
        "deep_analysis_completion）+ 写入 AgentSession.metadata['cross_repo_relevance'] "
        "+ 拼到本工具返回 text 末尾 `[cross_repo_relevance:<trace_id>]` 段。"
        "你在 deep_analysis 之后调 create_coding_plan 时可直接从 metadata 引用 "
        "recommended_repository_ids，无需再次调 analyze_repository_relevance。"
    ),
    category="PROJECT",
    parameters={
        "type": "object",
        "properties": {
            "space_id": {
                "type": "string",
                "description": "项目 UUID（自动注入，无需 LLM 提供）",
            },
            "task_description": {
                "type": "string",
                "description": (
                    "聚焦的分析任务描述，应明确「分析什么 + 用户最终想知道的结论」，"
                    "例如：'梳理 studyRoom 入口跳转到错题本的路由配置 + 参数传递链路，"
                    "重点说明 entrance 字段是怎么被解析到 wrongBook 的'。"
                    "避免泛泛的 'analyze this repo'。"
                ),
            },
            "repository_id": {
                "type": "string",
                "description": (
                    "**必填**：目标仓库 UUID（虽然 schema 标 optional，但深度分析模式"
                    "必须明确指定 —— 不指定会落到「第一个 indexed 仓库」，多仓库场景下"
                    "几乎肯定不是你想分析的那个）。先用 list_space_repositories 拿到所有"
                    "可用 repository_id，再按相关性选择。"
                ),
            },
            "conversation_id": {
                "type": "string",
                "description": "会话 UUID（自动注入，无需 LLM 提供）",
            },
            "branch": {
                "type": "string",
                "description": "分支名（可选，未指定时分析默认分支）",
            },
        },
        "required": ["space_id", "task_description"],
    },
)
async def deep_analysis(
    space_id: str,
    task_description: str,
    repository_id: str | None = None,
    conversation_id: str = "",
    branch: str | None = None,
) -> ToolResult:
    """将复杂分析任务 dispatch 到 Runner 上的 Claude Code。

    Fire-and-forget 模式：dispatch 后立即返回 __blocking_task__ 标记，
    等待和恢复由 graph interrupt/resume 机制处理。
    """
    from runners.dispatcher import DispatchTask, get_dispatcher
    from subagent.models import SubAgentSession

    logger.info(
        "deep_analysis_requested",
        space_id=space_id,
        task_description=task_description[:100],
        repository_id=repository_id,
    )

    # 1. 查找目标仓库
    try:
        project = await Project.objects.aget(id=space_id)
    except Project.DoesNotExist:
        return ToolResult(success=False, error=f"Space not found: {space_id}")

    if repository_id:
        repos = [
            repo
            async for repo in Repository.objects.filter(
                id=repository_id,
                projects=project,
                is_deleted=False,
                index_status="indexed",
            )
        ]
    else:
        repos = [
            repo
            async for repo in Repository.objects.filter(
                projects=project,
                is_deleted=False,
                index_status="indexed",
            )[:1]
        ]

    if not repos:
        return ToolResult(
            success=False,
            error="No indexed repositories found. Deep analysis requires at least one indexed repository.",
        )

    repo = repos[0]

    # 2.1 同一会话 + 同一仓库内若已有未结束的深度分析，直接复用等待，避免重复开容器。
    # Phase P15：复用键由 (conversation_id, source) 升级为
    # (conversation_id, repository_id, source) —— 让 LLM 在同一 conversation 内
    # 可以对**不同仓库**并行 dispatch 多个 Claude Code 容器（跨仓库追踪场景）。
    # 同一 (conv, repo) 仍然单实例：避免重复浪费容器；不同角度的问题应该合并到
    # 一个 task_description（已在 deep_analysis 工具 description 里告知 LLM）。
    existing_session = None
    target_repo_id = str(repo.id)
    async for candidate in SubAgentSession.objects.filter(
        task_type=SubAgentSession.TaskType.EXPLORE,
        status__in=[SubAgentSession.Status.PENDING, SubAgentSession.Status.RUNNING],
    ).select_related("main_session"):
        output = candidate.last_output or {}
        if (
            isinstance(output, dict)
            and output.get("source") == "chat_deep_analysis"
            and output.get("conversation_id") == conversation_id
            and output.get("repository_id") == target_repo_id
        ):
            existing_session = candidate
            break

    # 2. 检查是否有在线 Runner（重试 3 次，每次等 5 秒，应对 server reload 后 Runner 重连间隙）
    from django.utils import timezone as tz

    from runners.models import Runner

    online_runners = 0
    for _attempt in range(3):
        heartbeat_threshold = tz.now() - __import__("datetime").timedelta(seconds=120)
        online_runners = await Runner.objects.filter(
            status="online",
            last_heartbeat__gte=heartbeat_threshold,
        ).acount()
        if online_runners > 0:
            break
        await asyncio.sleep(5)
    if online_runners == 0:
        return ToolResult(success=False, error="没有可用的 Runner（等待 15 秒后仍无心跳）")

    # 3. 创建 AgentSession（SubAgentSession 的 main_session 外键）
    from agents.models import AgentSession

    if existing_session is not None:
        session = existing_session
        session_id = session.session_id
        logger.info(
            "deep_analysis_reuse_existing_session",
            session_id=session_id,
            conversation_id=conversation_id,
        )
        output = session.last_output or {}
        output["task_description"] = task_description
        session.last_output = output
        await session.asave(update_fields=["last_output", "updated_at"])
    else:
        session_id = f"deep-{uuid.uuid4().hex[:12]}"
        agent_session = await AgentSession.objects.acreate(
            session_id=f"agent-{session_id}",
            project=project,
            status=AgentSession.Status.RUNNING,
            metadata={"source": "chat_deep_analysis", "conversation_id": conversation_id},
        )

        session = await SubAgentSession.objects.acreate(
            session_id=session_id,
            main_session=agent_session,
            task_type=SubAgentSession.TaskType.EXPLORE,
            status=SubAgentSession.Status.PENDING,
            last_output={
                "task_type": "explore",
                "source": "chat_deep_analysis",
                "space_id": space_id,
                "conversation_id": conversation_id,
                "repository_id": str(repo.id),
                "task_description": task_description,
            },
        )

    # 4. 构建 prompt
    branch_context = f"\n分支：{branch}\n请基于该分支的代码进行分析。" if branch else ""
    prompt = (
        f"你正在分析项目「{project.name}」的代码仓库「{repo.name}」。{branch_context}\n\n"
        f"任务：{task_description}\n\n"
        f"请深入分析代码，给出详细的技术分析结果。用中文回答。"
    )

    # 5. 从 ProviderCredential 获取 API 凭据 + Git 凭据，通过 metadata 注入容器
    # Claude Code 任务容器统一凭证来源：优先读「Claude Code 编码配置」
    # （选定凭证 + 三档映射）；未配置时 runtime_config 内部回退系统默认 anthropic 凭证。
    from services.git_credentials import aresolve_git_token
    from services.provider_config import aget_claude_code_runtime_config

    cc = await aget_claude_code_runtime_config()
    api_key = cc["api_key"]
    base_url = cc["base_url"]
    system_model = cc["default_model"]
    small_model = cc["haiku_model"]

    env_metadata: dict[str, str] = {
        "repository_id": str(repo.id),
        "env_FRIDAY_TASK_CLAUDE_API_KEY": api_key,
        "env_FRIDAY_TASK_CLAUDE_BASE_URL": base_url,
        "env_FRIDAY_TASK_CLAUDE_MODEL": system_model,
        "env_FRIDAY_TASK_CLAUDE_SMALL_MODEL": small_model,
        # explore 模式标识：双层 git 写操作拦截（work item）
        # FRIDAY_TASK_MODE -> wrapper 脚本读取（Shell 层）
        # FRIDAY_TASK_TASK_MODE -> pydantic-settings 映射到 TaskConfig.task_mode（Python 层）
        "env_FRIDAY_TASK_MODE": "explore",
        "env_FRIDAY_TASK_TASK_MODE": "explore",
    }

    repo_url = repo.git_url
    # Git 凭据：经统一解析器取 token（per-repo 优先 → host 实例池 fallback，D-02）
    token = await aresolve_git_token(repo)
    if token:
        env_metadata["env_FRIDAY_TASK_GIT_ACCESS_TOKEN"] = token
        env_metadata["env_FRIDAY_TASK_GIT_AUTH_TYPE"] = "token"
        env_metadata["env_FRIDAY_TASK_GIT_SSL_VERIFY"] = "false"
        # SSH URL → HTTPS（token 认证需要 HTTPS）
        if repo_url.startswith("git@"):
            import re

            m = re.match(r"git@([^:]+):(.+?)(?:\.git)?$", repo_url)
            if m:
                repo_url = f"https://{m.group(1)}/{m.group(2)}.git"

    dispatch_task = DispatchTask(
        task_id=session_id,
        task_type="explore",
        tags=[],
        image="",
        repo_url=repo_url,
        branch=branch or repo.default_branch,
        target_branch="",
        prompt=prompt,
        timeout=DEEP_ANALYSIS_TIMEOUT,
        node_execution_id="",
        session_id=session_id,
        metadata=env_metadata,
    )

    if existing_session is None:
        await get_dispatcher().dispatch(dispatch_task)

        logger.info(
            "deep_analysis_dispatched",
            session_id=session_id,
            repo_name=repo.name,
            repo_url=repo.git_url,
        )

    # 6. Fire-and-forget: 注册到 blocking_task_registry 后立即返回
    from agents.tools.blocking_task_registry import register_blocking_task

    blocking_info: dict[str, Any] = {
        "task_id": session_id,
        "task_type": "deep_analysis",
        "params": {
            "task_description": task_description,
            "space_id": space_id,
            "repository_id": str(repo.id),
        },
    }
    await register_blocking_task(conversation_id, blocking_info)

    return ToolResult(
        success=True,
        output={
            "__blocking_task__": True,
            "task_id": session_id,
            "task_type": "deep_analysis",
            "params": {
                "task_description": task_description,
                "space_id": space_id,
                "repository_id": str(repo.id),
            },
            "placeholder": f"已启动深度分析任务 ({session_id})，分析完成后将自动返回结果。",
        },
    )
