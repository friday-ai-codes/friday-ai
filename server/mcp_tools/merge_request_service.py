"""Branch summary and merge-request helpers for MCP tools."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import structlog
from django.utils import timezone

from chat.models import CodingSession
from mcp_tools.models import McpCodingExecutionTrace
from repositories.models import Repository
from services.git_credentials import aresolve_git_token
from services.git_platform import get_git_platform_client
from services.git_platform.models import MRCreateRequest

logger = structlog.get_logger(__name__)


class MergeRequestToolError(Exception):
    """Git credential or platform operation error."""


async def _get_client(repository: Repository) -> Any:
    # Phase 26 REPO-01：统一经解析器取 token（per-repo 优先 → 同 host 实例凭证池 fallback）
    token = await aresolve_git_token(repository)
    if not token:
        raise MergeRequestToolError("仓库缺少 Git 平台访问凭据")
    return get_git_platform_client(repository, token)


def _risk_summary(files: list[dict[str, Any]], has_conflicts: bool) -> list[str]:
    risks: list[str] = []
    if has_conflicts:
        risks.append("目标分支存在潜在冲突，合并前需要人工复核。")
    if len(files) > 20:
        risks.append("变更文件较多，建议拆分验证重点。")
    if not files:
        risks.append("平台未返回文件差异，需确认分支是否已推送。")
    return risks or ["未发现明显合并风险。"]


def _test_suggestions(files: list[dict[str, Any]]) -> list[str]:
    test_files = [f["path"] for f in files if "test" in str(f.get("path", "")).lower()]
    if test_files:
        return [f"复跑相关测试文件：{', '.join(test_files[:5])}"]
    return [
        "复跑受影响模块的单元测试。",
        "检查分支 diff 与编码方案影响文件是否一致。",
    ]


def _draft_from_summary(
    *,
    repository: Repository,
    source_branch: str,
    target_branch: str,
    summary: dict[str, Any],
) -> dict[str, str]:
    """同步拼装 draft 标题/描述（不含影响面；create 路径统一 append，幂等安全）。"""
    title = f"{repository.name}: {source_branch}"
    file_lines = "\n".join(
        f"- {item['path']} ({item['change_type']}, +{item['additions']}/-{item['deletions']})"
        for item in summary.get("files", [])[:20]
    ) or "- 平台未返回文件差异"
    risk_lines = "\n".join(f"- {risk}" for risk in summary.get("risks", []))
    test_lines = "\n".join(f"- {item}" for item in summary.get("test_suggestions", []))
    description = (
        f"## Summary\n\nMerge `{source_branch}` into `{target_branch}`.\n\n"
        f"## Changed Files\n\n{file_lines}\n\n"
        f"## Risks\n\n{risk_lines}\n\n"
        f"## Tests\n\n{test_lines}"
    )
    return {"title": title[:200], "description": description}


async def summarize_branch(
    *,
    repository: Repository,
    source_branch: str,
    target_branch: str,
    max_files: int,
    trace: McpCodingExecutionTrace | None = None,
) -> dict[str, Any]:
    client = await _get_client(repository)
    result = await client.compare_branches(
        source_branch=source_branch,
        target_branch=target_branch,
        max_files=max_files,
    )
    if not result.success:
        raise MergeRequestToolError(result.error or "分支对比失败")
    files = [asdict(item) for item in result.files]
    commits = []
    if trace is not None and trace.commit_sha:
        commits.append({"sha": trace.commit_sha, "source": "execution_trace"})
    summary = {
        "repository_id": str(repository.id),
        "source_branch": source_branch,
        "target_branch": target_branch,
        "ahead_by": result.ahead_by,
        "behind_by": result.behind_by,
        "files": files,
        "total_additions": result.total_additions,
        "total_deletions": result.total_deletions,
        "truncated": result.truncated,
        "has_potential_conflicts": result.has_potential_conflicts,
        "conflicting_files": result.conflicting_files,
        "commits": commits,
        "risks": _risk_summary(files, result.has_potential_conflicts),
        "test_suggestions": _test_suggestions(files),
        "generated_at": timezone.now().isoformat(),
    }
    summary["mr_draft"] = _draft_from_summary(
        repository=repository,
        source_branch=source_branch,
        target_branch=target_branch,
        summary=summary,
    )
    if trace is not None:
        trace.branch_summary = summary
        trace.last_diff = {
            "files": files,
            "total_additions": result.total_additions,
            "total_deletions": result.total_deletions,
            "truncated": result.truncated,
        }
        await trace.asave(update_fields=["branch_summary", "last_diff", "updated_at"])
    return summary


async def create_merge_request(
    *,
    repository: Repository,
    source_branch: str,
    target_branch: str,
    title: str,
    description: str,
    reviewer_usernames: list[str],
    remove_source_branch: bool,
    trace: McpCodingExecutionTrace | None = None,
    user: Any | None = None,
) -> dict[str, Any]:
    client = await _get_client(repository)
    if not title:
        title = f"{repository.name}: {source_branch}"[:200]
    if not description:
        if trace is not None and isinstance(trace.branch_summary, dict):
            draft = trace.branch_summary.get("mr_draft") or {}
            description = str(draft.get("description") or "")
        description = description or f"Merge `{source_branch}` into `{target_branch}`."

    # Phase 124 DIFF-04：与 AICodingNode 同一 helper；显式已含 ## 影响面 时幂等跳过（D-06/D-09）
    try:
        from services.code_graph.impact_report import (
            append_impact_report,
            build_impact_report_section,
        )

        section = await build_impact_report_section(
            repository=repository,
            user=user,
            compare=source_branch,
            base_ref=target_branch,
        )
        description = append_impact_report(description, section)
    except Exception as exc:  # noqa: BLE001 — 最后兜底；helper 内应已吞
        try:
            logger.warning(
                "impact_report_shell_failed",
                component="mcp_tools",
                category="caller",
                repository_id=str(getattr(repository, "id", "") or ""),
                error=str(exc)[:200],
            )
        except Exception:  # noqa: BLE001 — 观测永不反噬
            pass

    # Phase 127 TAINT-02：与 AICodingNode 同一 security helper（D-04/D-06）
    try:
        from services.code_graph.security_scan_report import (
            append_security_scan,  # noqa: F401 — D-06 dual-link 合同字面量
            attach_security_scan_pending,
        )

        description = await attach_security_scan_pending(
            description,
            repository=repository,
            source_branch=source_branch,
            target_branch=target_branch,
            user=user,
            enqueue=False,
        )
    except Exception as exc:  # noqa: BLE001 — 最后兜底；helper 内应已吞
        try:
            logger.warning(
                "security_scan_shell_failed",
                component="mcp_tools",
                category="caller",
                repository_id=str(getattr(repository, "id", "") or ""),
                error=str(exc)[:200],
            )
        except Exception:  # noqa: BLE001 — 观测永不反噬
            pass

    request = MRCreateRequest(
        source_branch=source_branch,
        target_branch=target_branch,
        title=title,
        description=description,
        reviewer_usernames=reviewer_usernames,
        remove_source_branch=remove_source_branch,
    )
    result = await client.create_merge_request(request)
    if result.success:
        try:
            from services.code_graph.semgrep_enqueue import enqueue_semgrep_scan

            initiated_by = (
                str(user.id)
                if user is not None and getattr(user, "id", None) is not None
                else "system"
            )
            await enqueue_semgrep_scan(
                str(getattr(repository, "id", "") or ""),
                mr_key=str(result.mr_id or ""),
                source_sha="",
                target_sha="",
                branch_name=source_branch,
                initiated_by_user_id=initiated_by,
            )
        except Exception as exc:  # noqa: BLE001 — enqueue 失败不反噬已建 MR
            try:
                logger.warning(
                    "security_scan_shell_failed",
                    component="mcp_tools",
                    category="caller",
                    repository_id=str(getattr(repository, "id", "") or ""),
                    error=str(exc)[:200],
                )
            except Exception:  # noqa: BLE001
                pass
    payload = {
        "success": result.success,
        "mr_id": result.mr_id,
        "mr_url": result.mr_url,
        "title": title,
        "description": description,
        "source_branch": source_branch,
        "target_branch": target_branch,
        "has_conflicts": result.has_conflicts,
        "error": result.error,
        "created_at": timezone.now().isoformat(),
    }
    if trace is not None:
        trace.mr_result = payload
        if result.success:
            trace.status = McpCodingExecutionTrace.Status.COMPLETED
            trace.recovery_state = {
                **(trace.recovery_state if isinstance(trace.recovery_state, dict) else {}),
                "retryable": False,
                "mr_url": result.mr_url,
                "mr_id": result.mr_id,
            }
            if trace.coding_session_id:
                await CodingSession.objects.filter(id=trace.coding_session_id).aupdate(
                    pr_url=result.mr_url,
                    status=CodingSession.Status.COMPLETED,
                )
        else:
            if trace.commit_sha or trace.push_result:
                trace.status = McpCodingExecutionTrace.Status.PARTIAL
            trace.recovery_state = {
                **(trace.recovery_state if isinstance(trace.recovery_state, dict) else {}),
                "retryable": True,
                "mr_error": result.error,
                "branch_name": source_branch,
                "target_branch": target_branch,
                "commit_sha": trace.commit_sha,
            }
        await trace.asave(update_fields=["mr_result", "status", "recovery_state", "updated_at"])
    return payload
