"""start_feature_solution chat agent 工具 —— feature list 技术方案的对话入口。

与 ``plan_research_tools.start_plan_research`` 是**同一套编排**（technical_plan process、
同一 ``ConvergenceSession``、同一澄清与调研回流机制），差别只在入口形态：

- ``start_plan_research``：入参是一段自然语言需求。
- 本工具：入参是 **feature list**（项目已录入的 / 当前分支关联项目的 / 用户贴的原文），
  额外跑「功能点新增 vs 改造已有」分类，并**强制**让用户确认关联仓库。

因为底层 session 同型，挂起 / 续推完全复用既有 chat HITL：澄清用
``PLAN_CLARIFICATION_RENDER_MARKER``（前端 plan 多题卡，收答经
``POST /conversations/{id}/plan-clarification/answer/``），调研在途用
``__blocking_task__`` marker（容器完成后 ``_schedule_chat_plan_resume`` 自动续驱 + barrier
回灌）——**一行都不重实现**。

薄封装铁律：本工具不写编排逻辑，只做「调 ``FeatureSolutionService`` → 挂起 / 终态映射」。
"""

from __future__ import annotations

from typing import Any

import structlog

from agents.tools.base import ToolResult, tool
from agents.tools.plan_research_tools import PLAN_CLARIFICATION_RENDER_MARKER

logger = structlog.get_logger(__name__)

__all__ = ["start_feature_solution"]


@tool(
    name="start_feature_solution",
    description=(
        "由 feature list（成批功能点 / 需求清单）生成技术方案。当用户给出一份 feature list、"
        "需求清单，或明确说要「创建 / 生成技术方案」时调用。\n"
        "本工具会：① 判定每个功能点是**新增功能**还是**改造已有功能**（结合代码检索证据）；"
        "② 给出关联仓库建议；③ **暂停并让用户确认**关联仓库与分类判定；"
        "④ 确认后调研并产出「分仓方案 + 整体方案」（含落点文件与伪代码）。\n"
        "注意：确认环节是强制的——即便仓库路由十分确定也会问一次，这是产品约束，"
        "不要试图绕过。单个零散需求请改用 start_plan_research。"
    ),
    category="PROJECT",
    parameters={
        "type": "object",
        "properties": {
            "feature_list_text": {
                "type": "string",
                "description": (
                    "feature list 原文（用户贴的需求清单 / 功能点列表）。"
                    "当前会话已绑定项目且要用项目里已录入的 feature list 时可不传。"
                ),
            },
            "branch_name": {
                "type": "string",
                "description": "可选：按 git 分支反查已绑定的项目并取其 feature list。",
            },
            "include_repos": {
                "type": "array",
                "items": {"type": "string"},
                "description": "可选：收窄候选仓库 UUID 列表（最终选仓仍由用户确认）。",
            },
            "space_id": {
                "type": "string",
                "description": "空间 UUID (auto-injected)",
            },
            "conversation_id": {
                "type": "string",
                "description": "会话 UUID (auto-injected)",
            },
        },
        "required": ["space_id", "conversation_id"],
    },
)
async def start_feature_solution(
    space_id: str,
    conversation_id: str,
    feature_list_text: str = "",
    branch_name: str = "",
    include_repos: list[str] | None = None,
) -> ToolResult:
    """对话入口薄封装：取 feature list → 建 chat 会话 → 驱动到强制确认挂起 / 终态。"""
    from initiatives.services.feature_solution_service import (
        FeatureSolutionError,
        FeatureSolutionService,
    )

    actor, bound_project_id = await _resolve_conversation_context(conversation_id)
    if not feature_list_text.strip() and not branch_name.strip() and not bound_project_id:
        return ToolResult(
            success=False,
            error=(
                "缺少 feature list 来源：请提供 feature_list_text（贴出功能点清单），"
                "或把会话绑定到已录入 feature list 的项目，或提供 branch_name。"
            ),
        )

    filtered_repos = await _filter_repos_in_space(space_id, include_repos)

    logger.info(
        "start_feature_solution_requested",
        category="caller",
        component="agents",
        space_id=space_id,
        conversation_id=conversation_id,
        has_text=bool(feature_list_text.strip()),
        has_branch=bool(branch_name.strip()),
        bound_project=bool(bound_project_id),
    )

    try:
        state = await FeatureSolutionService().start(
            # 会话已绑定项目时默认用项目的 feature list；显式给了文本/分支则优先。
            project_id=None
            if (feature_list_text.strip() or branch_name.strip())
            else bound_project_id,
            branch_name=branch_name,
            feature_list_text=feature_list_text,
            repository_ids=filtered_repos,
            entrypoint="chat",
            actor=actor,
            initiated_by_user_id=getattr(actor, "id", "") or "",
            # 必传：前端 plan 澄清卡由 runtime 按 conversation_id 反查会话驱动，
            # 收答专路由同理——不传则确认卡渲染不出来、也无法作答。
            conversation_id=conversation_id,
        )
    except FeatureSolutionError as exc:
        return ToolResult(success=False, error=exc.detail)

    return await _map_state(state, conversation_id)


async def _map_state(state: Any, conversation_id: str) -> ToolResult:
    """FeatureSolutionState → chat 挂起 marker / 终态输出（复用既有 HITL 通道）。"""
    from initiatives.services.feature_solution_service import (
        STATUS_AWAITING_CONFIRMATION,
        STATUS_COMPLETED,
        STATUS_FAILED,
        STATUS_RESEARCHING,
    )

    if state.status == STATUS_AWAITING_CONFIRMATION:
        # 复用 plan 多题澄清卡（前端据 session_id + clarification_id 渲染，收答走 91-04 专路由）。
        return ToolResult(
            success=True,
            output={
                "clarification_id": state.clarification_id,
                "pending": True,
                "marker": PLAN_CLARIFICATION_RENDER_MARKER,
                "question": _summarize_questions(state),
                "options": [],
                "allow_freeform": True,
                "session_id": state.session_id,
                "classification": state.classification,
                "feature_count": state.feature_count,
            },
        )

    if state.status == STATUS_RESEARCHING:
        from agents.tools.blocking_task_registry import register_blocking_task

        blocking_info: dict[str, Any] = {
            "task_id": state.session_id,
            "task_type": "plan_research",
            "params": {"session_id": state.session_id},
        }
        await register_blocking_task(conversation_id, blocking_info)
        return ToolResult(
            success=True,
            output={
                "__blocking_task__": True,
                "task_type": "plan_research",
                "task_id": state.session_id,
                "session_id": state.session_id,
                "params": {"session_id": state.session_id},
                "placeholder": (
                    f"已发起 feature list 技术方案编排（session={state.session_id}）；"
                    "深入调研进行中，完成后将自动融合并返回分仓 + 整体方案。"
                ),
            },
        )

    if state.status == STATUS_COMPLETED:
        return ToolResult(
            success=True,
            output={
                "session_id": state.session_id,
                "status": "done",
                "artifact_version_id": state.artifact_version_id,
                "markdown": state.markdown,
                "classification_summary": (state.classification or {}).get("summary", {}),
                "message": "feature list 技术方案已生成（含分仓方案与整体方案）。",
            },
        )

    if state.status == STATUS_FAILED:
        error = state.error or {}
        return ToolResult(
            success=False,
            error=str(error.get("message") or error.get("reason") or "方案编排失败"),
            # 110-HI-01：与 plan_research_tools._map_terminal 同一条纪律 —— 失败出口也必须
            # 带定位键，否则失败气泡只能回退 store 的全局活跃会话，重跑时改播新一轮进度。
            metadata={"session_id": str(state.session_id)},
        )

    return ToolResult(
        success=True,
        output={"session_id": state.session_id, "status": state.status},
    )


def _summarize_questions(state: Any) -> str:
    """把待确认题压成一句话摘要（前端卡片有结构化题目，这里只作文本兜底）。"""
    summary = (state.classification or {}).get("summary") or {}
    head = (
        f"已分析 {state.feature_count} 个功能点"
        f"（新增 {summary.get('new', 0)} · 改造 {summary.get('modify', 0)}"
        f" · 待定 {summary.get('unclear', 0)}）。"
    )
    return head + "请确认关联仓库与功能点分类后继续。"


async def _resolve_conversation_context(conversation_id: str) -> tuple[Any, Any]:
    """从会话解析发起用户与绑定项目（async 安全，不裸访问 lazy-FK）。"""
    if not conversation_id:
        return None, None
    from chat.models import Conversation

    row = (
        await Conversation.objects.filter(id=conversation_id)
        .values("created_by", "bound_project")
        .afirst()
    )
    if not row:
        return None, None
    actor = None
    if row.get("created_by"):
        from accounts.models import User

        actor = await User.objects.filter(id=row["created_by"]).afirst()
    return actor, row.get("bound_project")


async def _filter_repos_in_space(space_id: str, include_repos: list[str] | None) -> list[str]:
    """include_repos best-effort 过滤到属于 space 的仓库（对齐 start_plan_research）。"""
    if not include_repos:
        return []
    from repositories.models import Repository

    try:
        return [
            str(rid)
            async for rid in Repository.objects.filter(
                id__in=include_repos, spaces__id=space_id, is_deleted=False
            ).values_list("id", flat=True)
        ]
    except Exception:  # noqa: BLE001 — best-effort 过滤，非法 UUID 等降级为空
        logger.warning("start_feature_solution_repo_filter_failed", space_id=space_id)
        return []
