"""建 MR 挂点的两端 commit sha 解析（Phase 127 / TAINT-01 / D-01..D-04）。

``run_semgrep_scan`` 在 ``source_sha`` / ``target_sha`` 任一为空时立即 fail-open 返回
``unavailable``，因此挂点**必须**先把「source 分支 HEAD」与「target/base 分支 HEAD」
解析成真实 sha 再入队，否则 diff-aware 扫描永不执行。

解析顺序（每一端独立）：

1. 调用方已持有的 sha（如 ``mr_service`` 的 ``commit_sha``）——校验是 40 位 hex 后直用；
2. 既有 Git 平台客户端 ``resolve_branch_sha``（GitLab ``branches.get`` /
   GitHub ``get_branch``）——建 MR 挂点手里本来就有 client，零新增抽象；
3. 本地 bare 镜像 ``ensure_mirror_commit``（无 client / 平台抖动时的兜底）。

两端都解析不出来时返回空串，由挂点记 ``code_graph_enqueue_semgrep_scan_skipped_missing_sha``
并保留 pending stub —— ⛔ 不入队注定 ``unavailable`` 的任务。

本模块 best-effort：任何异常都吞成"解析不到"，绝不反噬建 MR。
"""

from __future__ import annotations

import re
from typing import Any, Final

import structlog

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

_SHA_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")

__all__ = ["normalize_sha", "resolve_branch_sha", "resolve_scan_shas"]


def normalize_sha(value: Any) -> str:
    """规范化并校验完整 40 位 commit sha；非法 → 空串。"""
    sha = str(value or "").strip().lower()
    return sha if _SHA_RE.match(sha) else ""


async def _sha_from_client(client: Any, branch: str) -> str:
    if client is None or not branch:
        return ""
    resolver = getattr(client, "resolve_branch_sha", None)
    if resolver is None:
        return ""
    try:
        return normalize_sha(await resolver(branch))
    except Exception as exc:  # noqa: BLE001 — 平台抖动降级到镜像兜底
        try:
            logger.warning(
                "code_graph_semgrep_branch_sha_client_failed",
                category="sampling",
                component="code_graph",
                branch=branch,
                error=redact_secrets_in_text(str(exc))[:200],
            )
        except Exception:  # noqa: BLE001 — 观测永不反噬
            pass
        return ""


async def _sha_from_mirror(repository_id: str, branch: str) -> str:
    if not repository_id or not branch:
        return ""
    try:
        from services.repo_mirror import ensure_mirror_commit

        snapshot = await ensure_mirror_commit(repository_id, branch)
        return normalize_sha(getattr(snapshot, "commit_sha", ""))
    except Exception as exc:  # noqa: BLE001 — 镜像不可用即"解析不到"
        try:
            logger.warning(
                "code_graph_semgrep_branch_sha_mirror_failed",
                category="sampling",
                component="code_graph",
                repository_id=str(repository_id),
                branch=branch,
                error=redact_secrets_in_text(str(exc))[:200],
            )
        except Exception:  # noqa: BLE001 — 观测永不反噬
            pass
        return ""


async def resolve_branch_sha(
    *,
    repository_id: str,
    branch: str,
    client: Any = None,
    known_sha: str = "",
) -> str:
    """解析单个分支的 HEAD sha：已知 sha → 平台 client → 本地镜像；失败返回空串。"""
    known = normalize_sha(known_sha)
    if known:
        return known
    name = (branch or "").strip()
    if not name:
        return ""
    sha = await _sha_from_client(client, name)
    if sha:
        return sha
    return await _sha_from_mirror(str(repository_id or ""), name)


async def resolve_scan_shas(
    *,
    repository_id: str,
    source_branch: str,
    target_branch: str,
    client: Any = None,
    source_sha: str = "",
    target_sha: str = "",
) -> tuple[str, str]:
    """解析 Semgrep 扫描两端 sha。

    Returns:
        ``(source_sha, target_sha)``；任一端解析不出即为空串——调用方须据此
        跳过入队（``run_semgrep_scan`` 对空 sha 只会返回 ``unavailable``）。
    """
    repo_id = str(repository_id or "")
    resolved_source = await resolve_branch_sha(
        repository_id=repo_id,
        branch=source_branch,
        client=client,
        known_sha=source_sha,
    )
    resolved_target = await resolve_branch_sha(
        repository_id=repo_id,
        branch=target_branch,
        client=client,
        known_sha=target_sha,
    )
    return resolved_source, resolved_target
