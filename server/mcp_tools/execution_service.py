"""Execution bridge for MCP coding plans."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from chat.branch_service import generate_default_branch_name, validate_branch_name
from chat.coding_session_service import dispatch_coding_task
from chat.models import CodingPlan, CodingSession, Conversation
from mcp_tools.models import (
    McpCodingExecutionTrace,
    McpCodingPlan,
    McpCodingPlanVersion,
)
from projects.models import Space
from subagent.models import SubAgentSession, TaskResult


class ExecutionDispatchError(Exception):
    """Input or setup error before an execution can be dispatched."""


@dataclass(frozen=True)
class ExecutionResponse:
    trace: McpCodingExecutionTrace
    coding_session: CodingSession | None


def _plan_body_to_markdown(version: McpCodingPlanVersion) -> str:
    body = version.plan_body if isinstance(version.plan_body, dict) else {}
    title = str(body.get("title") or "MCP coding plan")
    requirement = str(body.get("requirement") or body.get("problem_statement") or "")
    steps = body.get("steps") if isinstance(body.get("steps"), list) else []
    tests = body.get("test_plan") if isinstance(body.get("test_plan"), list) else []
    risks = body.get("risks") if isinstance(body.get("risks"), list) else []
    lines = [f"# {title}", "", "## Requirement", requirement or version.plan.requirement]
    if steps:
        lines.extend(["", "## Steps"])
        for step in steps:
            if isinstance(step, dict):
                lines.append(
                    f"- {step.get('order', '')}. {step.get('title', '')}: {step.get('detail', '')}"
                )
            else:
                lines.append(f"- {step}")
    if tests:
        lines.extend(["", "## Tests"])
        lines.extend(f"- {item}" for item in tests)
    if risks:
        lines.extend(["", "## Risks"])
        lines.extend(f"- {item}" for item in risks)
    return "\n".join(lines).strip()


def _affected_files_for_chat(version: McpCodingPlanVersion) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    for item in version.affected_files or []:
        if isinstance(item, dict):
            path = str(item.get("file_path") or item.get("path") or "")
            change_type = str(item.get("change_type") or "modify")
        else:
            path = str(item)
            change_type = "modify"
        if path:
            files.append({"file_path": path, "change_type": change_type})
    return files


def _generate_branch_name(version: McpCodingPlanVersion) -> str:
    markdown = _plan_body_to_markdown(version)
    branch_name, _branch_type, _short_desc = generate_default_branch_name(markdown)
    return f"{branch_name}.mcp-{uuid.uuid4().hex[:6]}"


async def _find_project_for_repository(repository_id: uuid.UUID | str) -> Space | None:
    return await Space.objects.filter(repositories__id=repository_id).order_by("created_at").afirst()


async def _create_bridge_session(
    *,
    project: Space,
    plan: McpCodingPlan,
    version: McpCodingPlanVersion,
    branch_name: str,
    created_by=None,
) -> tuple[Conversation, CodingPlan, CodingSession]:
    tech_plan = _plan_body_to_markdown(version)
    affected_files = _affected_files_for_chat(version)

    @sync_to_async
    def _create() -> tuple[Conversation, CodingPlan, CodingSession]:
        with transaction.atomic():
            # created_by 透传（Phase 103 AGENT-01）：桥接 Conversation 携带发起用户，
            # 使 MCP 链在 dispatch_coding_task 内天然走任务 token mint 路径（可归因，
            # T-103-04）；None 时行为与现状一致（created_by 可空 SET_NULL，不 mint）。
            conversation = Conversation.objects.create(
                space=project,
                title=f"MCP execution: {plan.title}"[:200],
                status=Conversation.Status.RUNNING,
                created_by=created_by,
            )
            chat_plan = CodingPlan.objects.create(
                conversation=conversation,
                title=plan.title[:200],
                tech_plan=tech_plan,
                affected_files=affected_files,
                recommended_repository_ids=[str(plan.repository_id)],
            )
            coding_session = CodingSession.objects.create(
                conversation=conversation,
                coding_plan=chat_plan,
                repository=plan.repository,
                tech_plan=tech_plan,
                affected_files=affected_files,
                branch_name=branch_name,
                status=CodingSession.Status.DRAFT,
            )
            return conversation, chat_plan, coding_session

    return await _create()


async def dispatch_execution(
    *,
    trace: McpCodingExecutionTrace,
    plan: McpCodingPlan,
    version: McpCodingPlanVersion,
    branch_name: str,
    target_branch: str,
    timeout_seconds: int,
    initiating_user=None,
) -> ExecutionResponse:
    """派发 MCP coding plan 执行。

    ``initiating_user``（User | None，Phase 103 AGENT-01）：发起用户 ORM 实例，
    透传为桥接 Conversation.created_by → dispatch_coding_task 据此 mint 任务级
    短 TTL token。None 时保持现状（不 mint，降级不注入 token env）。与 Phase 101
    的 ``initiated_by_user_id``（字符串，观测归因）并行不混用。
    """
    project = await _find_project_for_repository(plan.repository_id)
    if project is None:
        raise ExecutionDispatchError("仓库未关联任何项目，无法创建 CodingSession")

    effective_branch = branch_name.strip() if branch_name else _generate_branch_name(version)
    validation = await validate_branch_name(
        branch_name=effective_branch,
        repository_id=plan.repository_id,
        git_client=None,
    )
    if not validation.valid:
        raise ExecutionDispatchError(
            "分支名校验失败: "
            + ("；".join(validation.errors) if validation.errors else "invalid branch")
        )

    _conversation, chat_plan, coding_session = await _create_bridge_session(
        project=project,
        plan=plan,
        version=version,
        branch_name=effective_branch,
        created_by=initiating_user,
    )
    await coding_session.aconfirm()
    trace.status = McpCodingExecutionTrace.Status.DISPATCHING
    trace.coding_session = coding_session
    trace.branch_name = effective_branch
    trace.target_branch = target_branch or plan.repository.default_branch
    trace.timeout_seconds = timeout_seconds
    trace.dispatch_payload = {
        "chat_plan_id": str(chat_plan.id),
        "coding_session_id": str(coding_session.id),
        "target_branch": trace.target_branch,
        "timeout_seconds": timeout_seconds,
    }
    trace.recovery_state = {
        "retryable": True,
        "status": trace.status,
        "branch_name": effective_branch,
        "coding_session_id": str(coding_session.id),
    }
    await trace.asave(
        update_fields=[
            "status",
            "coding_session",
            "branch_name",
            "target_branch",
            "timeout_seconds",
            "dispatch_payload",
            "recovery_state",
            "updated_at",
        ]
    )

    prompt = (
        f"Execute MCP coding plan {plan.id} version {version.version}.\n\n"
        f"{_plan_body_to_markdown(version)}"
    )
    try:
        session_id = await dispatch_coding_task(
            coding_session,
            task_type="coding",
            prompt=prompt,
            extra_metadata={
                "env_FRIDAY_TASK_TIMEOUT_SECONDS": str(timeout_seconds),
                "mcp_execution_id": str(trace.id),
                "mcp_plan_id": str(plan.id),
                "mcp_plan_version_id": str(version.id),
            },
        )
        await sync_to_async(coding_session.refresh_from_db)()
        sub_session = None
        if coding_session.subagent_session_id:
            sub_session = await SubAgentSession.objects.filter(
                id=coding_session.subagent_session_id
            ).afirst()
        await coding_session.amark_running(
            subagent_session_id=coding_session.subagent_session_id,
        )
        trace.status = McpCodingExecutionTrace.Status.RUNNING
        trace.subagent_session = sub_session
        trace.dispatch_payload = {
            **trace.dispatch_payload,
            "subagent_session_id": session_id,
            "status": "dispatched",
        }
        trace.recovery_state = {
            "retryable": True,
            "status": trace.status,
            "branch_name": effective_branch,
            "coding_session_id": str(coding_session.id),
            "subagent_session_id": session_id,
        }
        await trace.asave(
            update_fields=[
                "status",
                "subagent_session",
                "dispatch_payload",
                "recovery_state",
                "updated_at",
            ]
        )
    except Exception as exc:  # noqa: BLE001 - dispatch failures must be persisted.
        await coding_session.amark_failed(str(exc))
        trace.status = McpCodingExecutionTrace.Status.FAILED
        trace.error = str(exc)
        trace.recovery_state = {
            "retryable": True,
            "status": trace.status,
            "branch_name": effective_branch,
            "coding_session_id": str(coding_session.id),
            "error": str(exc),
        }
        trace.completed_at = timezone.now()
        await trace.asave(
            update_fields=["status", "error", "recovery_state", "completed_at", "updated_at"]
        )

    return ExecutionResponse(trace=trace, coding_session=coding_session)


async def refresh_execution_trace(trace: McpCodingExecutionTrace) -> McpCodingExecutionTrace:
    coding_session = None
    if trace.coding_session_id:
        coding_session = await CodingSession.objects.filter(id=trace.coding_session_id).afirst()
    sub_session = None
    if trace.subagent_session_id:
        sub_session = await SubAgentSession.objects.filter(id=trace.subagent_session_id).afirst()
    elif coding_session and coding_session.subagent_session_id:
        sub_session = await SubAgentSession.objects.filter(
            id=coding_session.subagent_session_id
        ).afirst()

    task_result = None
    if sub_session is not None:
        task_result = await TaskResult.objects.filter(session=sub_session).afirst()

    logs: list[Any] = []
    if sub_session is not None and isinstance(sub_session.last_output, dict):
        raw_logs = sub_session.last_output.get("logs")
        logs = raw_logs if isinstance(raw_logs, list) else []

    if task_result is not None:
        trace.commit_sha = task_result.commit_sha
        trace.file_changes = task_result.modified_files or []
        output = task_result.raw_output if isinstance(task_result.raw_output, dict) else {}
        trace.push_result = dict(output.get("push_result") or {})
        if not trace.push_result and task_result.commit_sha:
            trace.push_result = {
                "pushed": True,
                "branch_name": task_result.branch_name or trace.branch_name,
                "commit_sha": task_result.commit_sha,
            }
        trace.last_diff = dict(output.get("diff_summary") or {})
        trace.test_results = list(output.get("test_results") or [])
        if task_result.commit_sha:
            trace.status = McpCodingExecutionTrace.Status.COMPLETED
            trace.completed_at = trace.completed_at or timezone.now()

    if coding_session is not None:
        if not trace.last_diff and isinstance(coding_session.diff_summary, dict):
            trace.last_diff = coding_session.diff_summary
        if coding_session.status == CodingSession.Status.FAILED:
            trace.status = McpCodingExecutionTrace.Status.FAILED
            trace.error = coding_session.error_message or trace.error
            trace.completed_at = trace.completed_at or timezone.now()

    if sub_session is not None:
        if sub_session.status in {
            SubAgentSession.Status.ERROR,
            SubAgentSession.Status.TIMEOUT,
            SubAgentSession.Status.CANCELLED,
        }:
            trace.status = McpCodingExecutionTrace.Status.FAILED
            trace.error = sub_session.last_error or sub_session.failure_reason or trace.error
            trace.completed_at = trace.completed_at or timezone.now()
        trace.runner_logs = logs

    trace.recovery_state = {
        "retryable": trace.status == McpCodingExecutionTrace.Status.FAILED,
        "status": trace.status,
        "branch_name": trace.branch_name,
        "target_branch": trace.target_branch,
        "coding_session_id": str(trace.coding_session_id or ""),
        "subagent_session_id": getattr(sub_session, "session_id", ""),
        "commit_sha": trace.commit_sha,
        "error": trace.error,
    }
    await trace.asave(
        update_fields=[
            "status",
            "commit_sha",
            "file_changes",
            "test_results",
            "push_result",
            "last_diff",
            "runner_logs",
            "recovery_state",
            "error",
            "completed_at",
            "updated_at",
        ]
    )
    return trace


def execution_trace_payload(trace: McpCodingExecutionTrace) -> dict[str, Any]:
    recovery_state = trace.recovery_state if isinstance(trace.recovery_state, dict) else {}
    return {
        "execution_id": str(trace.id),
        "plan_id": str(trace.plan_id),
        "version_id": str(trace.plan_version_id),
        "repository_id": str(trace.repository_id),
        "status": trace.status,
        "branch_name": trace.branch_name,
        "target_branch": trace.target_branch,
        "coding_session_id": str(trace.coding_session_id or ""),
        "subagent_session_id": str(
            recovery_state.get("subagent_session_id") or trace.subagent_session_id or ""
        ),
        "commit_sha": trace.commit_sha,
        "file_changes": trace.file_changes,
        "test_results": trace.test_results,
        "push_result": trace.push_result,
        "last_diff": trace.last_diff,
        "branch_summary": trace.branch_summary,
        "mr_result": trace.mr_result,
        "runner_logs": trace.runner_logs,
        "recovery_state": trace.recovery_state,
        "dispatch_payload": trace.dispatch_payload,
        "error": trace.error,
        "retry_of_execution_id": str(trace.retry_of_id or ""),
        "retry_count": trace.retry_count,
        "created_at": trace.created_at.isoformat() if trace.created_at else "",
        "updated_at": trace.updated_at.isoformat() if trace.updated_at else "",
        "completed_at": trace.completed_at.isoformat() if trace.completed_at else "",
    }


def compact_execution_json(trace: McpCodingExecutionTrace) -> str:
    return json.dumps(execution_trace_payload(trace), ensure_ascii=False, sort_keys=True)
