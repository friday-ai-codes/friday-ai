"""编码完成飞书回写公共服务（LOOP-01 / Phase 101）。

把 MCP ``_write_results_back`` 的飞书评论 + 文档 append 能力抽为链路无关的
``CompletionWritebackService``：入参中性化（work_item 三元组 + 每仓结果列表 +
可选文档 append + ``initiated_by_user_id``），供 MCP / workflow / chat 三链路
统一接入。

契约（CONTEXT LOOP-01 锁定）：
- 渲染模板逐字迁移自 ``mcp_tools.work_item_execution_service``（零回归前提）；
- 回写失败记 ``writeback_failed`` 结构化事件后跳过，绝不重试、绝不上抛；
- 三元组缺失 / space 解析不到记 ``writeback_skipped`` 后双 skipped 返回；
- 异常文本仅入内部日志（structlog 已挂脱敏 processor），不写入飞书评论正文。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import structlog
from django.utils import timezone

from agents.tools.feishu_doc_tools import create_feishu_doc_client_for_project
from services.feishu import create_feishu_client_for_project
from services.feishu_doc import FeishuDocAPIError

logger = structlog.get_logger(__name__)

_COMPONENT = "delivery"


@dataclass(frozen=True)
class RepoResult:
    """每仓执行结果的中性形状（不依赖任何 MCP 模型）。"""

    repo_name: str
    status: str
    branch_name: str = ""
    commit_sha: str = ""
    mr_url: str = ""
    error: str = ""


def _table_cell(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("|", "\\|").replace("`", "\\`").replace("\n", "<br>").strip()


def render_results_markdown(results: list[RepoResult]) -> str:
    """渲染 "## 执行结果" markdown 表格（逐字迁移自 ``_execution_results_markdown``）。"""
    lines = [
        "## 执行结果",
        "",
        f"更新时间：{timezone.now().isoformat()}",
        "",
        "| 仓库 | 状态 | 分支 | Commit | PR/MR | 错误 |",
        "|---|---|---|---|---|---|",
    ]
    for result in results:
        lines.append(
            "| {repo} | {status} | `{branch}` | `{commit}` | {mr} | {error} |".format(
                repo=_table_cell(result.repo_name),
                status=_table_cell(result.status),
                branch=_table_cell(result.branch_name),
                commit=_table_cell(result.commit_sha),
                mr=_table_cell(result.mr_url or ""),
                error=_table_cell(result.error or ""),
            )
        )
    return "\n".join(lines) + "\n"


def render_comment_lines(title: str, results: list[RepoResult]) -> str:
    """渲染飞书工作项评论正文（逐字迁移自 ``_write_results_back`` 评论文案）。

    正文只用结构化 RepoResult 字段，不含上游异常文本（T-101-01-01）。
    """
    lines = [
        f"Friday 已更新执行结果：{title}",
        "",
        "仓库状态：",
    ]
    for result in results:
        lines.append(
            f"- {result.repo_name}: {result.status}, branch `{result.branch_name}`, MR {result.mr_url or '未生成'}"
        )
    return "\n".join(lines)


class CompletionWritebackService:
    """三链路统一的编码完成飞书回写服务（评论 + 可选文档 append）。

    语义严格镜像 MCP ``_write_results_back`` 的飞书两写条件与返回形状；
    MCP 专属的 plan 模型状态翻转不在本层（留在 MCP 薄包装内）。
    """

    async def awrite_back(
        self,
        *,
        feishu_project_key: str,
        work_item_type: str,
        work_item_id: int | None,
        title: str,
        results: list[RepoResult],
        space=None,
        feishu_document_id: str = "",
        doc_markdown: str = "",
        initiated_by_user_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """回写执行结果到飞书（文档 append + 工作项评论）。

        Args:
            feishu_project_key: 飞书项目 key（三元组之一）。
            work_item_type: 工作项类型（三元组之一）。
            work_item_id: 工作项 id（三元组之一，None 视为缺失）。
            title: 工作项/方案标题（评论文案用）。
            results: 每仓执行结果列表。
            space: ``projects.models.Space``；None 时经 feishu_project_key 反查。
            feishu_document_id: 飞书文档 id；非空且 doc_markdown 非空才 append。
            doc_markdown: 待 append 的 markdown 内容。
            initiated_by_user_id: 触发用户归因（无则记 "system"）。

        Returns:
            ``(document_update, comment)`` 双状态 dict，与 MCP 现状外形一致：
            ``{"status": "skipped"|"appended"|"written"|"error", ...}``。
        """
        started = time.monotonic()
        actor = initiated_by_user_id or "system"
        document_update: dict[str, Any] = {"status": "skipped"}
        comment: dict[str, Any] = {"status": "skipped"}

        # 观测与回写都 best-effort：整个方法体兜底捕获，绝不反噬调用方。
        try:
            resolved_space = space
            if resolved_space is None and feishu_project_key:
                from projects.models import Space  # lazy import 防循环

                resolved_space = await Space.objects.filter(
                    feishu_project_key=feishu_project_key
                ).afirst()

            # 守门（P3）：三元组任一缺失或 space 解析不到 → 记 skipped 事件后双 skipped 返回。
            missing_reason = ""
            if not feishu_project_key:
                missing_reason = "missing_feishu_project_key"
            elif work_item_id is None:
                missing_reason = "missing_work_item_id"
            elif not work_item_type:
                missing_reason = "missing_work_item_type"
            elif resolved_space is None:
                missing_reason = "space_not_found"
            if missing_reason:
                logger.info(
                    "writeback_skipped",
                    reason=missing_reason,
                    feishu_project_key=feishu_project_key,
                    work_item_id=work_item_id,
                    category="caller",
                    component=_COMPONENT,
                    initiated_by_user_id=actor,
                )
                return document_update, comment

            if resolved_space and feishu_document_id and doc_markdown:
                try:
                    doc_client = await create_feishu_doc_client_for_project(resolved_space)
                    result = await doc_client.append_markdown(feishu_document_id, doc_markdown)
                    document_update = {"status": "appended", **result}
                except (ValueError, FeishuDocAPIError) as exc:
                    document_update = {"status": "error", "error": str(exc)}
                except Exception as exc:  # noqa: BLE001 - writeback errors should be retryable state.
                    document_update = {"status": "error", "error": str(exc)}

            if resolved_space:
                try:
                    client = create_feishu_client_for_project(resolved_space)
                    ok = await client.add_comment(
                        feishu_project_key,
                        work_item_id,
                        work_item_type,
                        render_comment_lines(title, results),
                    )
                    comment = (
                        {"status": "written"}
                        if ok
                        else {"status": "error", "error": "Feishu 工作项评论写入失败"}
                    )
                except Exception as exc:  # noqa: BLE001 - writeback failure is partial state.
                    comment = {"status": "error", "error": str(exc)}

            duration_ms = int((time.monotonic() - started) * 1000)
            if document_update.get("status") == "error" or comment.get("status") == "error":
                logger.warning(
                    "writeback_failed",
                    document_status=document_update.get("status"),
                    comment_status=comment.get("status"),
                    error=str(document_update.get("error") or comment.get("error") or ""),
                    feishu_project_key=feishu_project_key,
                    work_item_id=work_item_id,
                    duration_ms=duration_ms,
                    category="caller",
                    component=_COMPONENT,
                    initiated_by_user_id=actor,
                )
            else:
                logger.info(
                    "writeback_completed",
                    document_status=document_update.get("status"),
                    comment_status=comment.get("status"),
                    feishu_project_key=feishu_project_key,
                    work_item_id=work_item_id,
                    duration_ms=duration_ms,
                    category="caller",
                    component=_COMPONENT,
                    initiated_by_user_id=actor,
                )
            return document_update, comment
        except Exception as exc:  # noqa: BLE001 - 回写兜底：绝不上抛反噬调用方。
            try:
                logger.warning(
                    "writeback_failed",
                    document_status=document_update.get("status"),
                    comment_status=comment.get("status"),
                    error=str(exc),
                    error_type=type(exc).__name__,
                    feishu_project_key=feishu_project_key,
                    work_item_id=work_item_id,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    category="caller",
                    component=_COMPONENT,
                    initiated_by_user_id=actor,
                )
            except Exception:  # noqa: BLE001, S110 - 观测失败也吞掉
                pass
            if document_update.get("status") == "skipped":
                document_update = {"status": "error", "error": str(exc)}
            if comment.get("status") == "skipped":
                comment = {"status": "error", "error": str(exc)}
            return document_update, comment
