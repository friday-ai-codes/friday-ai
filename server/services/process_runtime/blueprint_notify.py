"""蓝图澄清的飞书卡片送达（Phase 116-06，CLAR-04 的另一半）。

**用途**：蓝图链开出阻塞澄清线程之后，把澄清题推到项目群 —— 114-05 的提醒只到「记事件 +
写周期锚点」为止，用户收不到任何通知，CLAR-04 的用户可感知价值只兑现了一半。本模块补上
另一半。

⭐ **收敛法自述（本模块存在的首要理由）**：蓝图澄清的送达**只有这一个收口**。
**同步点 1 之后换 107 的送达设施时，只改这一个文件** —— 调用方（当前唯一接线点是
``blueprint_spec_gate._open_clarification``）只认
:func:`anotify_blueprint_clarification` 这一个模块级函数的签名，⛔ 不在四个入口各接一次、
⛔ 不把送达细节漏进 stage adapter。

⚠️ **与 analog ``plan_research._send_clarify_card`` 的两处 DIFFER**：

1. analog 是**工作流节点的方法**（吃 ``ExecutionContext`` 取 space / execution_id）；本模块
   是**独立模块级函数**（四个入口共用）⇒ ⛔ **不依赖 ``ExecutionContext``**：project 一律
   从蓝图自身的 ``meta.project_id`` 反查（那是 116-02 intake 保证非空的权威字段），
   space 取 ``project.space``；调用方也可显式传 ``space`` 走 analog 的 space→project 路径。
2. 卡片当前是**通知形态**：作答通道是 REST 人审端点 / MCP ``answer_blueprint_clarification``
   / 蓝图查看器，⛔ 卡片的 ``action`` 前缀刻意用未注册的 ``blueprint_clarify_answer``
   （``CardCallbackView`` 按 ``startswith`` 匹配、无匹配即 warning 后优雅返回，⛔ 不会抢占
   ``plan_clarify_`` 的既有路由，也不会 5xx）。把交互回调接上属于同步点 1 之后换送达设施
   的同一批改动 —— 那时**仍然只改本文件**。

**best-effort**：整段 ``try/except`` 只 log，⛔ **失败只记事件绝不反噬挂起** —— 一次 IM
抖动不该废掉整条澄清（T-116-55）。每一步「取不到就 ``return``」的早退形态。

观测：成功落一条 ``caller`` 事件 ``blueprint_clarification_card_sent``，只记
``artifact_id`` / ``session_id`` / ``question_count`` / ``recipient_count`` / ``chat_id`` /
``duration_ms`` —— ⛔ **澄清题正文绝不进日志，只记条数**（T-116-54）；题面来自 LLM
（半可信），进卡片前逐条过 ``redact_secrets_in_text``。

⭐ **五条早退各留一条痕**（116-REVIEW MN-03）：``blueprint_clarification_card_skipped``
（``sampling``）带 ``reason`` ∈ ``{no_questions, no_project, no_space, no_recipients,
no_chat_id}``。⛔ **早退不等于不留痕** —— 裸 ``return`` 会让「卡片没发出去」在日志里与
「本来就没开澄清」完全同形，而这五条恰恰是生产上最可能命中的（项目没建飞书群、
``BlueprintReviewer`` 名单为空且会话 ``created_by`` 为空、``resolve_or_create_group``
返回空 ``chat_id`` ……）。
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

__all__ = ["anotify_blueprint_clarification"]

_COMPONENT = "blueprint_notify"
# 卡片回调路由前缀（⛔ 当前未注册 handler：作答走 REST / MCP / 查看器，见模块 docstring）
_CARD_ACTION = "blueprint_clarify_answer"
# 单条题面长度上界（半可信 LLM 文本，进卡片前先截断）
_MAX_QUESTION_CHARS = 300


def _normalize_questions(questions: Any) -> list[dict[str, Any]]:
    """澄清题 → 发卡用的四键结构，**正文逐条脱敏**（形状照 analog ``:510-517``）。

    兼容两种入参键名：规格门产的 ``{text, options, citations}`` 与 analog 的
    ``{question, options, recommended}``。空题一律丢弃。
    """
    rows: list[dict[str, Any]] = []
    for item in questions or []:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("text") or item.get("question") or "").strip()
        if not raw:
            continue
        options = item.get("options")
        rows.append(
            {
                "question": redact_secrets_in_text(raw)[:_MAX_QUESTION_CHARS],
                "type": str(item.get("type") or "single"),
                "options": [
                    redact_secrets_in_text(str(opt))[:_MAX_QUESTION_CHARS]
                    for opt in options
                    if str(opt or "").strip()
                ]
                if isinstance(options, list)
                else [],
                "recommended": item.get("recommended") or [],
            }
        )
    return rows


async def _aresolve_project_from_artifact(artifact: Any) -> Any:
    """从蓝图最新版本的 ``meta.project_id`` 反查 ``initiatives.Project``（只读，取不到回 None）。

    ⭐ 口径与 ``blueprint_review_views._ablueprint_project_id`` 同源：**只从蓝图自身推导**。
    """
    from delivery.models import ArtifactVersion
    from initiatives.models import Project

    content = await (
        ArtifactVersion.objects.filter(artifact_id=getattr(artifact, "id", None))
        .order_by("-version_no")
        .values_list("content", flat=True)
        .afirst()
    )
    meta = (content or {}).get("meta") if isinstance(content, dict) else None
    project_id = str((meta or {}).get("project_id") or "") if isinstance(meta, dict) else ""
    if not project_id:
        return None
    return await Project.objects.filter(id=project_id).select_related("space").afirst()


async def _alist_recipients(artifact_id: Any) -> list[str]:
    """收件人 = ``BlueprintReviewer`` 名单 ∪ 蓝图会话发起人（去重升序）。

    ⚠️ **口径逐字抄 ``blueprint_review_action._list_recipients``**：反查会话**必须带
    ``process_type="technical_blueprint"`` 过滤** —— 同一 artifact 上可能同时挂着旧
    ``technical_plan`` 与蓝图两条会话（两条 process 共用同一 ``artifact_type``），不过滤
    会把旧 process 的发起人当成本蓝图的相关人（T-116-58）。
    """
    from delivery.models import BlueprintReviewer, ConvergenceSession
    from services.process_runtime.blueprint_resume import BLUEPRINT_PROCESS_TYPE

    ids = {
        str(uid)
        async for uid in BlueprintReviewer.objects.filter(artifact_id=artifact_id).values_list(
            "user_id", flat=True
        )
        if uid
    }
    ids |= {
        str(uid)
        async for uid in ConvergenceSession.objects.filter(
            current_artifact_version__artifact_id=artifact_id,
            process_type=BLUEPRINT_PROCESS_TYPE,
        ).values_list("created_by_id", flat=True)
        if uid
    }
    return sorted(ids)


async def anotify_blueprint_clarification(
    *,
    artifact: Any,
    session: Any = None,
    questions: list[dict] | None = None,
    space: Any = None,
    initiated_by_user_id: str = "system",
) -> None:
    """把蓝图澄清题推成项目群飞书卡片（**整段 best-effort，绝不抛**）。

    调用序逐字照 ``plan_research._send_clarify_card``：题面脱敏 → 解析 project / space →
    收件人 → ``resolve_or_create_group`` → ``FeishuIMService.create`` → ``send_card``；
    每一步「取不到就 ``return``」。

    Args:
        artifact: 蓝图 ``Artifact``（project 从它的 ``meta.project_id`` 反查）。
        session: 蓝图 ``ConvergenceSession``，**只用于留痕**（``session_id``）。
        questions: 澄清题列表（``{text|question, options?}``），空列表即早退。
        space: 可选的 ``projects.Space``；传了就走 analog 的 space→project 路径。
        initiated_by_user_id: 触发用户（无则 ``system``，观测约束）。
    """
    started = time.monotonic()
    artifact_id = str(getattr(artifact, "id", "") or "")
    session_id = str(getattr(session, "id", "") or "")
    initiated = str(initiated_by_user_id or "") or "system"

    def _skip(reason: str, **kv: Any) -> None:
        """早退留痕（116-REVIEW MN-03）：⛔ **早退不等于不留痕**。

        回退前五条早退全是裸 ``return`` ⇒ 卡片没发出去时日志里连一条记录都没有：既看不到
        ``blueprint_clarification_card_sent`` 也看不到任何失败记录，运维只能靠「没有 sent
        事件」反推，而那与「本来就没开澄清」同形。⛔ 仍然只记标量，题面正文不进日志。
        """
        logger.info(
            "blueprint_clarification_card_skipped",
            category="sampling",
            component=_COMPONENT,
            reason=reason,
            artifact_id=artifact_id,
            session_id=session_id,
            initiated_by_user_id=initiated,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            **kv,
        )

    try:
        rows = _normalize_questions(questions)
        if not rows:
            _skip("no_questions", question_count=0)
            return

        project = None
        if space is not None:
            from workflows.nodes.integrations.board_split_review import _aresolve_project

            project = await _aresolve_project(space)
        if project is None:
            project = await _aresolve_project_from_artifact(artifact)
        if project is None:
            _skip("no_project", question_count=len(rows))
            return
        target_space = space if space is not None else getattr(project, "space", None)
        if target_space is None:
            _skip("no_space", question_count=len(rows))
            return

        recipients = await _alist_recipients(artifact_id)
        if not recipients:
            _skip("no_recipients", question_count=len(rows), recipient_count=0)
            return

        from feishu.cards.chat_question_card import build_clarification_card
        from initiatives.services.project_service import ProjectService
        from services.feishu_im import FeishuIMService

        chat_id = await ProjectService().resolve_or_create_group(
            project=project,
            member_ids=recipients,
            initiated_by_user_id=initiated,
        )
        if not chat_id:
            _skip("no_chat_id", question_count=len(rows), recipient_count=len(recipients))
            return

        card = build_clarification_card(
            rows,
            "",
            "",
            clarification_id=artifact_id,
            action=_CARD_ACTION,
            title="技术蓝图澄清",
            reason="蓝图编排需要你补充以下信息后才能继续；可在蓝图查看器或经 MCP 工具作答。",
        )
        im_service = await FeishuIMService.create(target_space)
        await im_service.send_card(receive_id=chat_id, receive_id_type="chat_id", card=card)
        logger.info(
            "blueprint_clarification_card_sent",
            category="caller",
            component=_COMPONENT,
            artifact_id=artifact_id,
            session_id=session_id,
            # ⛔ 题面正文不进日志，只记条数
            question_count=len(rows),
            recipient_count=len(recipients),
            chat_id=str(chat_id),
            initiated_by_user_id=initiated,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
    except Exception as exc:  # noqa: BLE001 — 发卡 best-effort，绝不反噬挂起
        logger.warning(
            "blueprint_clarification_card_failed",
            category="caller",
            component=_COMPONENT,
            artifact_id=artifact_id,
            session_id=session_id,
            initiated_by_user_id=initiated,
            error=redact_secrets_in_text(str(exc))[:500],
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
