"""McpCodingExecutionTrace → [plan 锚, code_change] 双事件 normalizer（Phase 100 / KNOW-03）。

照 task_result.py 双事件结构：

- **plan 锚事件**：复用 ``mcp_coding_plan.build_plan_event``（同源拼法纪律——
  content 与 mcp_coding_plan normalizer 主事件逐字节一致，锚短路重摄不翻版本），
  ``IMPLEMENTED_BY``（方案→代码变更）EdgeSpec 挂**锚事件**，边方向与
  task_result.py L219-225 完全一致；plan 最新 version 缺失 → 降级单事件
  （code_change 独立入图）+ warning。
- **code_change 主事件**：kind 复用既有值 ``code_change``；content 为执行摘要
  markdown（branch_summary 摘要 + file_changes 文件路径列表 + test_results 概要
  + error 截断）；**diff 原文（last_diff）与 runner_logs 全文绝不进 content/payload**
  （task_result.py T-14-24 payload 纪律同款，本 plan T-100-06）；execution→PR
  信息（mr_url/commit_sha）入 payload（locked decision）。
"""

from __future__ import annotations

import structlog

from common.logging import redact_secrets_in_text
from knowledge.ingestion import EdgeSpec, IngestionEvent, IngestionRequest
from knowledge.models import EdgeRelation, EntityKind, EntityOrigin, generate_entity_id

logger = structlog.get_logger(__name__)

__all__ = ["normalize"]


def _file_paths(file_changes: object) -> list[str]:
    """file_changes JSON → 文件路径列表（只取路径，不取 diff 内容）。"""
    paths: list[str] = []
    for item in file_changes if isinstance(file_changes, list) else []:
        if isinstance(item, dict):
            path = str(item.get("path") or item.get("file_path") or "")
        else:
            path = str(item)
        if path:
            paths.append(path)
    return paths


def _build_content(trace, title: str, mr_url: str) -> str:
    """执行摘要 markdown（T-100-06：last_diff / runner_logs 零接触）。"""
    lines: list[str] = [
        f"# {title}",
        "",
        "## 执行概要",
        f"- 状态：{trace.status}",
        f"- 分支：{trace.branch_name or '（无）'} → {trace.target_branch or '（无）'}",
        f"- commit：{trace.commit_sha or '（无）'}",
    ]
    if mr_url:
        lines.append(f"- MR：{mr_url}")
    lines.append("")
    summary = trace.branch_summary if isinstance(trace.branch_summary, dict) else {}
    for key, value in summary.items():
        if isinstance(value, str) and value.strip():
            lines += [f"## {key}", "", value.strip(), ""]
    paths = _file_paths(trace.file_changes)
    if paths:
        lines += ["## 变更文件", "", *[f"- {p}" for p in paths], ""]
    test_lines: list[str] = []
    for item in trace.test_results if isinstance(trace.test_results, list) else []:
        if isinstance(item, dict):
            desc = str(item.get("command") or item.get("name") or "")
            status_text = str(item.get("status") or "")
            text = "：".join(part for part in (desc, status_text) if part)
        else:
            text = str(item)
        if text:
            test_lines.append(f"- {text}")
    if test_lines:
        lines += ["## 测试结果", "", *test_lines, ""]
    if trace.error:
        # error 来自 runner/git 执行失败文本，可能含带凭证的 remote URL / 上游响应片段；
        # 入库留痕（PG content + Qdrant 可检索）前必须脱敏（先脱敏再截断，避免截断残留半个凭证）。
        lines += ["## 错误", "", redact_secrets_in_text(trace.error)[:500], ""]
    return "\n".join(lines).rstrip() + "\n"


async def normalize(request: IngestionRequest) -> list[IngestionEvent]:
    """McpCodingExecutionTrace → [plan 锚, code_change] 双事件（锚在前）。"""
    from knowledge.sources.mcp_coding_plan import _resolve_work_item, build_plan_event
    from mcp_tools.models import McpCodingExecutionTrace

    trace = (
        await McpCodingExecutionTrace.objects.select_related("plan", "plan_version", "repository")
        .filter(id=request.source_id)
        .afirst()
    )
    if trace is None:
        logger.warning(
            "knowledge_normalize_source_missing",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
            component="knowledge",
            category="sampling",
        )
        return []

    repository = trace.repository
    mr_result = trace.mr_result if isinstance(trace.mr_result, dict) else {}
    mr_url = str(mr_result.get("mr_url") or mr_result.get("url") or "")
    title = f"{repository.name} MCP 执行 @ {trace.commit_sha[:8] or trace.status}"
    # updated_at 而非 completed_at/created_at：completed_at 不变而内容再变（如 error
    # 补写后经 backfill 重摄）会撞 kversion_valid_range CHECK（invalid_at 须严格大于
    # 旧版 valid_at）；auto_now updated_at 随每次 asave 推进且恒为 aware
    # （learning_case.py / build_plan_event 同款纪律，HI-01 同批修复）。
    code_change_event = IngestionEvent(
        kind=EntityKind.CODE_CHANGE,
        origin=EntityOrigin.MCP,
        source_kind="mcp_execution_trace",
        source_id=str(trace.id),
        title=title,
        content=_build_content(trace, title, mr_url),
        # execution→PR 信息入 payload（locked decision）；diff 原文绝不进 payload（T-100-06）
        payload={
            "plan_id": str(trace.plan_id),
            "plan_version_id": str(trace.plan_version_id),
            "status": trace.status,
            "branch_name": trace.branch_name,
            "target_branch": trace.target_branch,
            "commit_sha": trace.commit_sha,
            "mr_url": mr_url,
            "file_change_count": len(_file_paths(trace.file_changes)),
            "retry_count": trace.retry_count,
        },
        space_id=None,
        repository_id=str(trace.repository_id),
        event_time=trace.updated_at,
    )

    # ---- plan 锚事件（build_plan_event 同源拼法 + IMPLEMENTED_BY 出边挂锚）----
    latest_version = await trace.plan.versions.order_by("-version").afirst()
    if latest_version is None:
        # 无可用方案版本降级：边随锚缺席，code_change 单事件仍入图
        logger.warning(
            "knowledge_normalize_anchor_plan_missing",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
            component="knowledge",
            category="sampling",
        )
        return [code_change_event]
    # D-03（quick-260726-q3z）：锚事件与 mcp_coding_plan 主事件同款 space_id 来源
    # （work_item 可解析且 technical_plan 带 space）；space_id 不进 content/hash，
    # 锚同源拼法 byte-equal 纪律不破。
    resolved = await _resolve_work_item(trace.plan_id)
    anchor_space_id: str | None = None
    if resolved is not None and resolved[1].space_id:
        anchor_space_id = str(resolved[1].space_id)
    anchor_event = build_plan_event(
        trace.plan,
        latest_version,
        edges=(
            EdgeSpec(
                relation=EdgeRelation.IMPLEMENTED_BY,
                target_entity_id=generate_entity_id(
                    "code_change", "mcp_execution_trace", str(trace.id)
                ),
            ),
        ),
        space_id=anchor_space_id,
    )
    return [anchor_event, code_change_event]
