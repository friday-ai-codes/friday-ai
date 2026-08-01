"""按 ``path``（+ 可选行区间）读仓库源码正文的**唯一实现**（Phase 116-07，VIEW-02）。

**用途**：从 ``mcp_tools/views.GetRepositoryFileView`` 下沉而来——MCP 工具面
（``get_repository_file``）与 SPA 引用预览面（``GET /api/repositories/<id>/file-lines/``）
共享这一份实现，⛔ 绝不各自复制一份排除判定。优先走本地 bare 镜像（``git show``，行号精确、
内容全量、``source="git"``）；镜像不可用（未启用 / fetch 失败 / 文件不在快照中）时回退
Qdrant 索引 chunk 拼接路径（``source="index"``），逐字保持下沉前的行为不回退。

**两个调用面的口径分道（⛔ 不得互相污染）**：本模块返回**中性结构**（下方恒定键闭集），
由两个 View 各自映射成自己的对外契约——

- MCP 面把 ``excluded`` 映射成 **404 ``file_excluded``**（既有对外契约，逐字不变），
  ``not_found`` / ``unavailable`` 映射成既有的 404 ``file_not_found``；
- SPA 面把 ``excluded`` / ``not_found`` / ``unavailable`` **统一映射成 200 空**
  （中性口径，与 ``repositories/chunk_at_views.py:5-9`` 的存在性防线同源：被排除文件与
  「无命中」对外不可区分，避免存在性泄漏）。

⛔ 本模块不构造任何 DRF ``Response`` / ``error_response``，也不知道 HTTP 状态码——
状态码是调用面的事，混进来就是两个口径互相污染的起点。

**fail-closed 纪律**：排除判定对 **requested 与 resolved 两个路径都复判**（防后缀解析
绕过，T-22-21）；匹配器构造失败一律视为「已排除」（宁可多排不可漏，T-22-25，范式对齐
``services/chunk_lookup.py``）；⭐ **命中排除绝不返回任何 content**——``excluded`` /
``not_found`` / ``unavailable`` 三态下 ``content`` 恒为 ``""``、``lines`` 恒为 ``[]``。

**观测**：⛔ 文件路径与源码正文**一律不进日志**，只记 ``path_len`` / ``content_len`` /
``line_count`` / ``truncated`` 等标量；异常文本过 ``redact_secrets_in_text``。命中排除时调
既有 ``log_exclusion_blocked``（``surface`` 由调用方传入以区分调用面；该埋点自身的
``rel_path=`` 是 Phase 22 既有审计行为，本模块沿用不改）。观测一律 best-effort，
⛔ 绝不反噬读取主流程。
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from agents.tools.chat_tools import _list_indexed_paths, _scroll_file_from_collection
from common.logging import redact_secrets_in_text
from repositories.models import IndexStatus, Repository
from services.branch_utils import resolve_branch_for_query
from services.exclusion import build_matcher_for_repo, log_exclusion_blocked
from services.qdrant_service import QdrantService
from services.repo_mirror import (
    MirrorError,
    ensure_mirror_commit,
    list_mirror_paths,
    read_mirror_file,
)

logger = structlog.get_logger(__name__)

_COMPONENT = "repo_file_read"

#: 未显式给 ``max_lines`` 时的返回行数上界（逐字沿用下沉前 MCP serializer 的缺省 500）。
_DEFAULT_MAX_LINES = 500

_EXT_LANG_MAP = {
    "py": "python",
    "js": "javascript",
    "jsx": "javascript",
    "ts": "typescript",
    "tsx": "typescript",
    "go": "go",
    "css": "css",
    "html": "html",
    "json": "json",
    "vue": "vue",
    "md": "markdown",
}

__all__ = ["aread_repository_file", "language_from_path"]


def language_from_path(file_path: str) -> str:
    """按扩展名推语言标签；未知扩展返回空串（下沉自 ``mcp_tools.views._language_from_path``）。"""
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    return _EXT_LANG_MAP.get(ext, "")


def _neutral(
    status: str,
    *,
    path: str,
    line_start: int | None,
    line_end: int | None,
    detail: str = "",
) -> dict[str, Any]:
    """构造「不可读」中性结构：⭐ ``content`` 与 ``lines`` 恒空（命中排除绝不返回任何正文）。"""
    return {
        "status": status,
        "path": path,
        "resolved_path": "",
        "content": "",
        "lines": [],
        "line_start": line_start,
        "line_end": line_end,
        "truncated": False,
        "detail": detail,
        "source": "",
        "commit_sha": "",
        "language": "",
        "total_chunks": 0,
        "total_lines": 0,
        "returned_lines": 0,
    }


def _number_lines(
    texts: list[str],
    *,
    base_line_no: int,
    line_start: int | None,
    line_end: int | None,
) -> list[dict[str, Any]]:
    """把正文行编号成 ``{"line_no", "text"}``（**1-based**，与 citation 的 ``line_start`` 同口径）。

    给了区间时按区间裁剪：镜像路径的切片本就等于区间（裁剪是恒等操作），索引回退路径拿到的是
    整块 chunk 拼接结果，裁剪把它收窄到调用方真正要的那几行。
    """
    numbered: list[dict[str, Any]] = []
    for offset, text in enumerate(texts):
        line_no = base_line_no + offset
        if line_start is not None and line_no < int(line_start):
            continue
        if line_end is not None and line_no > int(line_end):
            continue
        numbered.append({"line_no": line_no, "text": text})
    return numbered


async def _acheck_excluded(repository_id: str, *paths: str, surface: str) -> bool:
    """对 requested / resolved 路径做 fail-closed 排除判定；命中 → 审计埋点并返回 ``True``。

    ⭐ ``resolved_path`` **必须复判**（防后缀解析绕过，T-22-21）：requested 写成 ``env``
    可能解析到真实的 ``.env``，只判 requested 就漏了。命中绝不返回任何 content。
    匹配器构造异常一律 fail-closed 视为命中（T-22-25）。
    """
    try:
        matcher = await build_matcher_for_repo(repository_id)
    except Exception as exc:  # noqa: BLE001 — 构造失败一律 fail-closed（宁可多排不可漏）
        logger.warning(
            "repo_file_read_matcher_build_failed",
            category="sampling",
            component=_COMPONENT,
            repository_id=repository_id,
            surface=surface,
            error=redact_secrets_in_text(str(exc))[:200],
        )
        log_exclusion_blocked(
            surface=surface,
            repository_id=repository_id,
            rel_path=str(paths[0]) if paths else "",
        )
        return True
    for candidate in paths:
        if candidate and matcher.is_excluded(str(candidate)):
            log_exclusion_blocked(
                surface=surface,
                repository_id=repository_id,
                rel_path=str(candidate),
            )
            return True
    return False


async def _aread_from_mirror(
    repository_id: str,
    branch: str | None,
    file_path: str,
) -> tuple[str, str, Any] | None:
    """尝试从本地镜像读文件；任何不可用情形返回 ``None`` 走索引回退。

    严格匹配失败时做**唯一后缀候选**兜底（多于一个候选即视为歧义、不猜）；返回的
    ``resolved_path`` 由调用方连同 requested 一起复判排除（T-22-21）。
    """
    try:
        snapshot = await ensure_mirror_commit(repository_id, branch)
        text = await read_mirror_file(snapshot, file_path)
        resolved_path = file_path
        if text is None:
            candidates = [
                path for path in await list_mirror_paths(snapshot) if path.endswith(file_path)
            ]
            if len(candidates) == 1:
                resolved_path = candidates[0]
                text = await read_mirror_file(snapshot, resolved_path)
        if text is None:
            return None
        return resolved_path, text, snapshot
    except MirrorError as exc:
        # ⛔ 路径与正文不进日志，只记长度标量。
        logger.info(
            "repo_mirror_file_fallback_index",
            category="sampling",
            component=_COMPONENT,
            repository_id=repository_id,
            path_len=len(file_path),
            code=exc.code,
            detail=redact_secrets_in_text(str(exc.detail))[:300],
        )
        return None


async def _aresolve_indexed_repo(repository_id: str) -> Repository | None:
    """解析已建索引且未删除的仓库；不存在 / 未建索引一律返回 ``None``（调用面自行映射）。

    ⚠️ MCP 面**不走这里**——它用基类 ``McpToolView._get_indexed_repo`` 预解析并把 ``repo``
    传进来，以保住 ``repository_not_found`` 404 / ``repository_not_indexed`` 400 两个既有
    错误码的逐字契约。本函数只服务于「三态不可区分」的中性调用面。
    """
    try:
        repo = await Repository.objects.aget(id=repository_id, is_deleted=False)
    except Exception:  # noqa: BLE001 — 不存在 / 非法 uuid 一律视为不可读（中性口径）
        return None
    if repo.index_status != IndexStatus.INDEXED:
        return None
    return repo


async def _aresolve_collection(
    repository_id: str,
    repo: Repository,
    branch_name: str,
) -> tuple[str | None, str | None]:
    """解析图分支与 Qdrant collection（口径逐字对齐 ``McpToolView._resolve_graph_branch``）。"""
    effective_branch, branch_index = await resolve_branch_for_query(
        repository_id, branch_name or None
    )
    base_branch = repo.base_branch or repo.default_branch
    graph_branch = (
        effective_branch if effective_branch and effective_branch != base_branch else None
    )
    collection_name = (
        branch_index.collection_name
        if graph_branch and branch_index and branch_index.collection_name
        else QdrantService.get_collection_name(repository_id)
    )
    return graph_branch, collection_name


def _emit(
    result: dict[str, Any],
    *,
    repository_id: str,
    surface: str,
    started: float,
) -> dict[str, Any]:
    """采样类收口事件：⛔ 只记标量，路径与正文一律不进日志；best-effort 绝不反噬业务。"""
    try:
        logger.debug(
            "repo_file_read_completed",
            category="sampling",
            component=_COMPONENT,
            repository_id=repository_id,
            surface=surface,
            result_status=result["status"],
            path_len=len(str(result["path"])),
            content_len=len(str(result["content"])),
            line_count=len(result["lines"]),
            truncated=result["truncated"],
            read_source=result["source"],
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
    except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬读取主流程
        pass
    return result


async def aread_repository_file(
    repository_id: str,
    path: str,
    *,
    branch_name: str = "",
    surface: str = "",
    line_start: int | None = None,
    line_end: int | None = None,
    max_lines: int | None = None,
    repo: Any = None,
    collection_name: str | None = None,
) -> dict[str, Any]:
    """读 ``repository_id`` 的 ``path``（可选 ``line_start``..``line_end`` 闭区间）。

    ``line_start`` / ``line_end`` 为 ``None`` ⇒ 返回整文件（MCP 面的既有行为）；给了区间
    ⇒ ``lines`` 只含该区间，并按 ``max_lines`` 截断置 ``truncated``（⛔ 超上界是**截断**
    而不是报错——区间来自半可信来源，写错一个数字不该让整次读取失败）。

    ``repo`` / ``collection_name`` 是**可选预解析入参**：MCP 面已用基类方法解析过（并据此回
    自己那两个既有错误码），传进来以免重复解析、也避免把 MCP 的错误码语义搬进本模块。
    不传则本模块自行解析，解析不出记 ``unavailable``。

    恒定返回键（闭集）::

        {"status", "path", "resolved_path", "content", "lines", "line_start", "line_end",
         "truncated", "detail", "source", "commit_sha", "language", "total_chunks",
         "total_lines", "returned_lines"}

    ``status`` ∈ ``{"ok", "excluded", "not_found", "unavailable"}``；后三者下 ``content``
    恒为 ``""``、``lines`` 恒为 ``[]``。``lines`` 项形状 ``{"line_no": int, "text": str}``
    （**1-based**）。
    """
    started = time.monotonic()
    requested_path = str(path or "")
    limit = max(int(max_lines) if max_lines is not None else _DEFAULT_MAX_LINES, 1)

    if repo is None:
        repo = await _aresolve_indexed_repo(repository_id)
        if repo is None:
            return _emit(
                _neutral(
                    "unavailable",
                    path=requested_path,
                    line_start=line_start,
                    line_end=line_end,
                    detail="仓库不可读或尚未建立索引",
                ),
                repository_id=repository_id,
                surface=surface,
                started=started,
            )
    if collection_name is None:
        _graph_branch, collection_name = await _aresolve_collection(
            repository_id, repo, branch_name
        )

    # ① 镜像路径（行号精确）
    mirror_hit = await _aread_from_mirror(repository_id, branch_name or None, requested_path)
    if mirror_hit is not None:
        resolved_path, full_text, snapshot = mirror_hit
        if await _acheck_excluded(repository_id, requested_path, resolved_path, surface=surface):
            return _emit(
                _neutral(
                    "excluded",
                    path=requested_path,
                    line_start=line_start,
                    line_end=line_end,
                    detail="文件已被排除策略屏蔽",
                ),
                repository_id=repository_id,
                surface=surface,
                started=started,
            )
        all_lines = full_text.splitlines()
        total_lines = len(all_lines)
        slice_start = int(line_start) - 1 if line_start is not None else 0
        slice_end = int(line_end) if line_end is not None else total_lines
        selected_texts = all_lines[slice_start:slice_end]
        truncated = len(selected_texts) > limit
        returned_texts = selected_texts[:limit]
        result = _neutral("ok", path=requested_path, line_start=line_start, line_end=line_end)
        result.update(
            {
                "resolved_path": resolved_path,
                "content": "\n".join(returned_texts),
                "lines": _number_lines(
                    returned_texts,
                    base_line_no=slice_start + 1,
                    line_start=line_start,
                    line_end=line_end,
                ),
                "truncated": truncated,
                "source": "git",
                "commit_sha": str(getattr(snapshot, "commit_sha", "") or ""),
                "language": language_from_path(resolved_path),
                "total_chunks": 0,
                "total_lines": total_lines,
                "returned_lines": len(returned_texts),
            }
        )
        return _emit(result, repository_id=repository_id, surface=surface, started=started)

    # ② Qdrant 索引 chunk 拼接回退
    chunks_raw = await _scroll_file_from_collection(collection_name, requested_path)
    resolved_path = requested_path
    if not chunks_raw:
        candidates = [
            candidate
            for candidate in await _list_indexed_paths(collection_name)
            if candidate.endswith(requested_path)
        ]
        if len(candidates) == 1:
            resolved_path = candidates[0]
            chunks_raw = await _scroll_file_from_collection(collection_name, resolved_path)
    if not chunks_raw:
        # ⚠️ 顺序逐字保持下沉前：索引无命中先于排除判定（对外两者都不可区分，无存在性预言机）。
        return _emit(
            _neutral(
                "not_found",
                path=requested_path,
                line_start=line_start,
                line_end=line_end,
                detail="索引中找不到文件",
            ),
            repository_id=repository_id,
            surface=surface,
            started=started,
        )

    if await _acheck_excluded(repository_id, requested_path, resolved_path, surface=surface):
        return _emit(
            _neutral(
                "excluded",
                path=requested_path,
                line_start=line_start,
                line_end=line_end,
                detail="文件已被排除策略屏蔽",
            ),
            repository_id=repository_id,
            surface=surface,
            started=started,
        )

    chunks_raw.sort(key=lambda chunk: chunk.get("chunk_index", 0))
    selected_chunks: list[dict[str, Any]] = []
    for chunk in chunks_raw:
        chunk_start = chunk.get("start_line", 0) or 0
        chunk_end = chunk.get("end_line", float("inf")) or float("inf")
        if line_start is not None and chunk_end < int(line_start):
            continue
        if line_end is not None and chunk_start > int(line_end):
            continue
        selected_chunks.append(chunk)

    texts: list[str] = []
    language = ""
    for chunk in selected_chunks:
        if not language:
            language = str(chunk.get("language") or "")
        texts.extend(str(chunk.get("content") or "").splitlines())
    truncated = len(texts) > limit
    returned_texts = texts[:limit]
    base_line_no = int(selected_chunks[0].get("start_line") or 0) or 1 if selected_chunks else 1
    result = _neutral("ok", path=requested_path, line_start=line_start, line_end=line_end)
    result.update(
        {
            "resolved_path": resolved_path,
            "content": "\n".join(returned_texts),
            "lines": _number_lines(
                returned_texts,
                base_line_no=base_line_no,
                line_start=line_start,
                line_end=line_end,
            ),
            "truncated": truncated,
            "source": "index",
            "commit_sha": "",
            "language": language,
            "total_chunks": len(chunks_raw),
            "total_lines": len(texts),
            "returned_lines": len(returned_texts),
        }
    )
    return _emit(result, repository_id=repository_id, surface=surface, started=started)
