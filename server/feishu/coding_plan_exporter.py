"""CodingPlan → 飞书云文档导出器（implementation / work item）。

把一份 CodingPlan + 关联 CodingSession 列表组装成一篇飞书云文档：

    Heading1: <plan.title>
    Heading2: 技术方案
    <plan.tech_plan 的 markdown 转 block>
    Heading2: 影响文件
    <affected_files 表格>
    Heading2: 目标仓库与编码状态
    <coding_sessions 表格>
    Paragraph: 生成时间：YYYY-MM-DD HH:MM:SS

设计要点：
    - 不重造 markdown → block 转换：把所有 section 拼成一篇大 markdown，
      直接交给 ``FeishuDocClient.create_document``（内部已用 ``markdown_to_blocks``
      处理表格、代码块、列表、heading 等）。
    - 不直连飞书 HTTP：通过 ``services/feishu_doc`` 与
      ``agents/tools/feishu_doc_tools`` 已有 client / 凭证回退链路。
    - 单测 mock client：导出器允许 caller 注入 ``doc_client``，默认 ``None`` 时
      从 ``conversation.space`` 构造凭证（生产路径）。
"""

from __future__ import annotations

from typing import Any

import structlog
from django.utils import timezone

from chat.models import CodingPlan, CodingPlanProvenance, CodingSession
from services.feishu_doc import (
    FeishuDocAPIError,
    FeishuDocClient,
    markdown_to_blocks,
)

logger = structlog.get_logger(__name__)


# 显式声明导出符号，让 mypy / linter 知道 markdown_to_blocks 虽未直接调用，
# 但属于该模块的依赖契约（FeishuDocClient.create_document 内部使用）。
__all__ = ["export_coding_plan_to_feishu", "markdown_to_blocks"]


# CodingSession.Status → 飞书表格中的中文徽章文案。
# 与 implementation CodingSession.Status 枚举（chat/models.py 中 6 态）一一对应；
# 缺省时降级为原始 status 字符串，避免 KeyError 中断导出。
# RELY-01 导出侧「未经代码调研」告示（markdown blockquote）。
# 主句 `本方案未经代码调研` 与次行前半段与界面侧（`TechPlanCard` 草稿横幅）**逐字一致**，
# 导出侧仅追加一句行动指引「正式方案请经技术方案编排产出。」—— 导出物脱离上下文流转，
# 多一句指引值得。双侧口径一致才能让用户在界面与文档间建立同一心智。
_DRAFT_NOTICE = (
    "> ⚠️ **本方案未经代码调研**\n"
    ">\n"
    "> 由对话直接生成，未经仓库路由、代码召回与并行调研，"
    "文件清单与实现步骤可能不准确。正式方案请经技术方案编排产出。\n"
)


_STATUS_LABEL: dict[str, str] = {
    CodingSession.Status.DRAFT: "📝 草稿",
    CodingSession.Status.CONFIRMED: "🟢 已确认",
    CodingSession.Status.RUNNING: "⏳ 进行中",
    CodingSession.Status.AWAITING_CONFIRMATION: "🟡 等待确认",
    CodingSession.Status.COMPLETED: "✅ 已完成",
    CodingSession.Status.FAILED: "❌ 失败",
}


async def export_coding_plan_to_feishu(
    coding_plan: CodingPlan,
    folder_token: str,
    title: str | None = None,
    doc_client: FeishuDocClient | None = None,
) -> dict[str, str]:
    """导出 CodingPlan 为飞书云文档。

    Args:
        coding_plan: 目标方案（caller 需保证 ``conversation.space`` 可用；
            ``coding_sessions`` 通过异步 ORM 查询自动拉取，无需 prefetch）。
        folder_token: 目标飞书文件夹 token。
        title: 覆盖文档标题；为 None / 空字符串时回退到 ``coding_plan.title``。
        doc_client: 注入用 client（单测 / 自定义场景）；为 None 时按项目级凭证
            构造（生产路径）。

    Returns:
        ``{"doc_token": "...", "doc_url": "..."}``

    Raises:
        FeishuDocAPIError: 飞书 API 调用失败（含权限 / 速率 / 写入错误）。
    """
    if doc_client is None:
        # 延迟 import 避免 agents/tools 与 chat/feishu 互相引用导致的循环
        from agents.tools.feishu_doc_tools import (
            create_feishu_doc_client_for_project,
        )

        project = await _aget_project_for_plan(coding_plan)
        doc_client = await create_feishu_doc_client_for_project(project)

    doc_title = title or coding_plan.title or "未命名方案"

    sessions = await _aload_coding_sessions(coding_plan)
    markdown = _compose_plan_markdown(coding_plan, sessions)

    log = logger.bind(
        plan_id=str(coding_plan.id),
        folder_token=folder_token,
        title=doc_title,
        sessions_count=len(sessions),
    )

    try:
        result = await doc_client.create_document(
            title=doc_title,
            folder_token=folder_token,
            content=markdown,
        )
    except FeishuDocAPIError:
        log.warning("coding_plan_feishu_export_create_document_failed")
        raise

    document_id = str(result.get("document_id", ""))
    doc_url = str(result.get("url", ""))

    coding_plan.feishu_doc_token = document_id
    coding_plan.feishu_doc_url = doc_url
    await coding_plan.asave(
        update_fields=["feishu_doc_token", "feishu_doc_url", "updated_at"]
    )

    log.info("coding_plan_feishu_export_success", document_id=document_id)

    return {"doc_token": document_id, "doc_url": doc_url}


# ---------------------------------------------------------------------------
# 内部辅助：异步加载关联模型 / 拼接 markdown / 构造表格
# ---------------------------------------------------------------------------


async def _aget_project_for_plan(coding_plan: CodingPlan) -> Any:
    """异步获取 ``coding_plan.conversation.space``。

    避免触发 sync ORM 抛 ``SynchronousOnlyOperation``；显式走 async manager
    重新拉一次带 ``select_related`` 的 plan 拿到 project。
    """
    refetched = await CodingPlan.objects.select_related(
        "conversation__space"
    ).aget(id=coding_plan.id)
    return refetched.conversation.space


async def _aload_coding_sessions(coding_plan: CodingPlan) -> list[CodingSession]:
    """异步加载 ``coding_plan.coding_sessions``（含 repository / subagent_session 关联）。

    ``commit_sha`` 与 implementation runtime serializer 同源：
    ``subagent_session.task_result.commit_sha`` —— CodingSession 本身没有
    ``commit_sha`` 列。
    """
    sessions: list[CodingSession] = []
    async for s in (
        CodingSession.objects.filter(coding_plan=coding_plan)
        .select_related(
            "repository",
            "subagent_session",
            "subagent_session__task_result",
        )
        .order_by("created_at")
    ):
        sessions.append(s)
    return sessions


def _session_commit_sha(session: CodingSession) -> str:
    """从 ``subagent_session.task_result.commit_sha`` 取 commit；缺失返回空串。

    ``TaskResult``（subagent/models.py）是 ``SubAgentSession`` 的 OneToOne 反向
    关联，缺失时反向访问抛 ``RelatedObjectDoesNotExist``。这里用 ``getattr``
    + try/except 安全降级。
    """
    sa = session.subagent_session
    if sa is None:
        return ""
    try:
        task_result = sa.task_result  # type: ignore[attr-defined]
    except Exception:
        return ""
    if task_result is None:
        return ""
    sha = getattr(task_result, "commit_sha", "") or ""
    return str(sha)


def _compose_plan_markdown(
    coding_plan: CodingPlan, sessions: list[CodingSession]
) -> str:
    """组装一篇 markdown 字符串供 ``create_document`` 一次性转 block 写入。"""
    parts: list[str] = []
    parts.append(f"# {coding_plan.title or '未命名方案'}\n")
    # RELY-01：告示置于正文之前 —— 用户在读到任何方案内容前先看到「这份东西未经调研」。
    # 三条纪律：① 判定只读数据层 `provenance` 字段，绝不匹配正文文案（新增产出路径时
    # 正文格式不可控，文案判定必然漏标）；② 允许清单 —— 仅 `orchestrated` 免标注，
    # 未知取值 / 空值一律标注；③ 不把 `provenance` 原始取值写进文档（上游非受控值上屏
    # 即泄漏面）。
    if str(coding_plan.provenance or "") != CodingPlanProvenance.ORCHESTRATED:
        parts.append(_DRAFT_NOTICE)
    parts.append("## 技术方案\n")
    tech_plan = (coding_plan.tech_plan or "").strip()
    if tech_plan:
        parts.append(tech_plan + "\n")
    else:
        parts.append("（暂无技术方案文本）\n")
    parts.append("## 影响文件\n")
    parts.append(_build_affected_files_table(coding_plan.affected_files or []))
    parts.append("## 目标仓库与编码状态\n")
    parts.append(_build_repo_status_table(sessions))
    parts.append(
        f"\n生成时间：{timezone.localtime().strftime('%Y-%m-%d %H:%M:%S')}\n"
    )
    return "\n".join(parts)


def _build_affected_files_table(files: list[dict[str, Any]]) -> str:
    """渲染 markdown 表格：文件路径 / 变更类型。缺字段时降级为 '—'。"""
    rows = ["| 文件路径 | 变更类型 |", "| --- | --- |"]
    for f in files:
        if not isinstance(f, dict):
            continue
        path = (f.get("file_path") or f.get("path") or "—") or "—"
        change_type = f.get("change_type") or "—"
        rows.append(f"| {_md_escape(str(path))} | {_md_escape(str(change_type))} |")
    if len(rows) == 2:
        rows.append("| — | — |")
    return "\n".join(rows) + "\n"


def _build_repo_status_table(sessions: list[CodingSession]) -> str:
    """渲染多仓状态表：仓库 / 分支 / 状态 / PR / Commit。"""
    rows = [
        "| 仓库 | 分支 | 状态 | PR | Commit |",
        "| --- | --- | --- | --- | --- |",
    ]
    for s in sessions:
        repo_name = getattr(s.repository, "name", "") or "—"
        branch = s.branch_name or "—"
        label = _STATUS_LABEL.get(s.status, s.status or "—")
        pr_cell = f"[PR]({s.pr_url})" if s.pr_url else "—"
        sha = _session_commit_sha(s)
        commit = sha[:7] if sha else "—"
        rows.append(
            f"| {_md_escape(str(repo_name))} | {_md_escape(branch)} | "
            f"{label} | {pr_cell} | {commit} |"
        )
    if len(rows) == 2:
        rows.append("| — | — | — | — | — |")
    return "\n".join(rows) + "\n"


def _md_escape(text: str) -> str:
    """对 markdown 表格 cell 做最小转义，避免 | 截断列。"""
    return text.replace("|", "\\|").replace("\n", " ")
