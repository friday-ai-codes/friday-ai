"""项目级方案意图到 FeatureSolutionService 的服务端直驱适配器。"""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog

from agents.core.events import PHASE_TRANSITION
from agents.tools.feature_solution_tools import (
    _map_state,
    _resolve_conversation_context,
)
from agents.tools.plan_research_tools import PLAN_CLARIFICATION_RENDER_MARKER
from common.logging import redact_secrets_in_text
from orchestration.state import RunPhase

logger = structlog.get_logger(__name__)

__all__ = ["dispatch_feature_solution"]


def _observe(event: str, **fields: Any) -> None:
    """观测失败不得反噬方案路由主流程。"""
    try:
        logger.info(event, category="caller", component="agents", **fields)
    except Exception:
        pass


async def dispatch_feature_solution(
    *,
    conversation_id: str,
    bound_project_id: Any,
    user_message: str = "",
    initiated_by_user_id: Any = "",
    run_id: str = "",
    writer: Any = None,
) -> dict[str, Any]:
    """幂等启动或复用项目 feature solution，并映射为 WorkflowState patch。"""
    from delivery.models import ConvergenceSession, ConvergenceSessionStatus
    from initiatives.services.feature_solution_service import FeatureSolutionService

    started = time.perf_counter()
    trigger_user = str(initiated_by_user_id or "system")
    common_fields = {
        "conversation_id": str(conversation_id or ""),
        "bound_project_id": str(bound_project_id or ""),
        "initiated_by_user_id": trigger_user,
        "run_id": str(run_id or ""),
    }
    _observe("solution_intent_detected", **common_fields)

    try:
        actor, resolved_project_id = await _resolve_conversation_context(conversation_id)
        project_id = resolved_project_id or bound_project_id
        active = (
            await ConvergenceSession.objects.filter(
                conversation_id=conversation_id,
                stage_state__decomposition__mode="feature_list",
            )
            .exclude(
                status__in=[
                    ConvergenceSessionStatus.DONE,
                    ConvergenceSessionStatus.FAILED,
                ]
            )
            .order_by("-created_at")
            .afirst()
        )
        service = FeatureSolutionService()
        if active is not None:
            state = await service.get(session_id=active.id, actor=actor)
        else:
            state = await service.start(
                project_id=project_id,
                entrypoint="chat",
                actor=actor,
                initiated_by_user_id=trigger_user,
                conversation_id=conversation_id,
            )

        tool_result = await _map_state(state, conversation_id)
        patch = _tool_result_to_patch(tool_result, state)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        _observe(
            "solution_intent_dispatched",
            **common_fields,
            duration_ms=duration_ms,
            session_id=str(state.session_id),
            status=str(state.status),
            reused_session=active is not None,
        )
        if writer is not None:
            try:
                writer(
                    {
                        "type": PHASE_TRANSITION,
                        "data": {"phase": patch["phase"]},
                    }
                )
            except Exception:
                pass
        return patch
    except Exception as exc:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        safe_error = redact_secrets_in_text(str(exc))[:500]
        _observe(
            "solution_intent_dispatch_failed",
            **common_fields,
            duration_ms=duration_ms,
            error=safe_error,
        )
        return {
            "phase": RunPhase.ERROR.value,
            "final_answer": f"技术方案编排启动失败：{safe_error or '请稍后重试'}",
            "pending_clarification": {},
            "result_metadata": {
                "status": "error",
                "error": safe_error,
                "task_category": "feature_solution",
            },
        }


def _tool_result_to_patch(tool_result: Any, state: Any) -> dict[str, Any]:
    """把 plan_clarification/blocking/终态映射到 graph，禁止退回单题澄清。"""
    output = tool_result.output if isinstance(tool_result.output, dict) else {}
    metadata = {
        "status": state.status,
        "session_id": str(state.session_id),
        "task_category": "feature_solution",
    }

    if output.get("marker") == PLAN_CLARIFICATION_RENDER_MARKER:
        tool_id = f"solution-{uuid.uuid4().hex[:12]}"
        return {
            "phase": RunPhase.FINALIZING.value,
            "final_answer": str(output.get("question") or "请确认方案范围后继续。"),
            "pending_clarification": {},
            "blocking_tasks": [],
            "tool_calls": [
                {
                    "id": tool_id,
                    "name": "start_feature_solution",
                    "input": {},
                    "result": output,
                    "status": "done",
                }
            ],
            "result_metadata": metadata,
        }

    if output.get("__blocking_task__"):
        return {
            "phase": RunPhase.WAITING.value,
            "pending_clarification": {},
            "blocking_tasks": [
                {
                    "task_id": str(output.get("task_id") or state.session_id),
                    "task_type": str(output.get("task_type") or "plan_research"),
                    "params": output.get("params") or {"session_id": str(state.session_id)},
                }
            ],
            "result_metadata": metadata,
        }

    if tool_result.success and output.get("status") == "done":
        return {
            "phase": RunPhase.FINALIZING.value,
            "final_answer": str(output.get("markdown") or output.get("message") or ""),
            "pending_clarification": {},
            "blocking_tasks": [],
            "result_metadata": metadata,
        }

    if not tool_result.success:
        safe_error = redact_secrets_in_text(str(tool_result.error or "方案编排失败"))[:500]
        return {
            "phase": RunPhase.ERROR.value,
            "final_answer": safe_error,
            "pending_clarification": {},
            "blocking_tasks": [],
            "result_metadata": {**metadata, "error": safe_error},
        }

    return {
        "phase": RunPhase.WAITING.value,
        "pending_clarification": {},
        "blocking_tasks": [
            {
                "task_id": str(state.session_id),
                "task_type": "plan_research",
                "params": {"session_id": str(state.session_id)},
            }
        ],
        "result_metadata": metadata,
    }
