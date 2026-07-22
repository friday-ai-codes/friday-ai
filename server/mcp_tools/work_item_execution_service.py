"""Work item repo-task fan-out and execution orchestration for MCP tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from interactions.models import InteractionRun
from mcp_tools.execution_service import (
    ExecutionDispatchError,
    dispatch_execution,
    execution_trace_payload,
    refresh_execution_trace,
)
from mcp_tools.merge_request_service import (
    MergeRequestToolError,
    create_merge_request,
    summarize_branch,
)
from mcp_tools.models import (
    McpCodingExecutionTrace,
    McpCodingPlan,
    McpCodingPlanVersion,
    McpWorkItemRepoTask,
    McpWorkItemTechnicalPlan,
)
from repositories.models import Repository

logger = structlog.get_logger(__name__)


class WorkItemExecutionError(Exception):
    """Recoverable error while creating or executing work item repo tasks."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class RepoTaskCreationResult:
    technical_plan: McpWorkItemTechnicalPlan
    tasks: list[McpWorkItemRepoTask]


@dataclass(frozen=True)
class RepoTaskExecutionResult:
    technical_plan: McpWorkItemTechnicalPlan
    tasks: list[McpWorkItemRepoTask]
    output: dict[str, Any]


async def _resolve_technical_plan(technical_plan_id: str) -> McpWorkItemTechnicalPlan:
    technical_plan = (
        await McpWorkItemTechnicalPlan.objects.select_related("context", "space")
        .filter(id=technical_plan_id)
        .afirst()
    )
    if technical_plan is None:
        raise WorkItemExecutionError("technical_plan_not_found", "技术方案不存在")
    return technical_plan


def repo_task_payload(task: McpWorkItemRepoTask) -> dict[str, Any]:
    return {
        "task_id": str(task.id),
        "technical_plan_id": str(task.technical_plan_id),
        "repository_id": str(task.repository_id),
        "order": task.order,
        "status": task.status,
        "branch_name": task.branch_name,
        "target_branch": task.target_branch,
        "coding_plan_id": str(task.coding_plan_id or ""),
        "plan_version_id": str(task.plan_version_id or ""),
        "execution_id": str(task.execution_trace_id or ""),
        "commit_sha": task.commit_sha,
        "mr_url": task.mr_url,
        "result": task.result,
        "recovery_state": task.recovery_state,
        "error": task.error,
    }


async def create_repo_tasks_from_technical_plan(
    *,
    run: InteractionRun,
    technical_plan_id: str,
) -> RepoTaskCreationResult:
    technical_plan = await _resolve_technical_plan(technical_plan_id)
    matrix = technical_plan.repository_tasks
    if not isinstance(matrix, list) or not matrix:
        raise WorkItemExecutionError(
            "repo_task_matrix_empty",
            "技术方案没有可创建的 repository task matrix",
        )

    tasks: list[McpWorkItemRepoTask] = []
    for index, item in enumerate(matrix, start=1):
        if not isinstance(item, dict):
            continue
        repository_id = str(item.get("repository_id") or "")
        repo = await Repository.objects.filter(id=repository_id).afirst()
        if repo is None:
            raise WorkItemExecutionError(
                "repository_not_found",
                f"技术方案矩阵中的仓库不存在: {repository_id}",
            )
        order = int(item.get("order") or index)
        branch_name = str(item.get("planned_branch") or "")
        target_branch = str(item.get("base_branch") or repo.base_branch or repo.default_branch)
        task = await McpWorkItemRepoTask.objects.filter(
            technical_plan=technical_plan,
            order=order,
        ).afirst()
        if task is not None:
            task.repository = await Repository.objects.aget(id=task.repository_id)
            if task.status in {
                McpWorkItemRepoTask.Status.PENDING,
                McpWorkItemRepoTask.Status.PLANNED,
            }:
                task.repository = repo
                task.branch_name = branch_name
                task.target_branch = target_branch
                task.task_body = item
                await task.asave(
                    update_fields=[
                        "repository",
                        "branch_name",
                        "target_branch",
                        "task_body",
                        "updated_at",
                    ]
                )
            tasks.append(task)
            continue

        task = await McpWorkItemRepoTask.objects.acreate(
            technical_plan=technical_plan,
            order=order,
            run=run,
            repository=repo,
            status=McpWorkItemRepoTask.Status.PENDING,
            branch_name=branch_name,
            target_branch=target_branch,
            task_body=item,
            recovery_state={"retryable": True, "stage": "created"},
            error="",
        )
        tasks.append(task)
    return RepoTaskCreationResult(technical_plan=technical_plan, tasks=tasks)


async def _resolve_tasks(
    *,
    run: InteractionRun,
    technical_plan_id: str,
    task_ids: list[str],
    create_missing: bool,
) -> tuple[McpWorkItemTechnicalPlan, list[McpWorkItemRepoTask]]:
    if technical_plan_id and create_missing:
        creation = await create_repo_tasks_from_technical_plan(
            run=run,
            technical_plan_id=technical_plan_id,
        )
        return creation.technical_plan, creation.tasks

    if technical_plan_id:
        technical_plan = await _resolve_technical_plan(technical_plan_id)
        tasks = [
            task
            async for task in McpWorkItemRepoTask.objects.select_related(
                "repository", "technical_plan", "coding_plan", "plan_version", "execution_trace"
            )
            .filter(technical_plan=technical_plan)
            .order_by("order")
        ]
        return technical_plan, tasks

    if not task_ids:
        raise WorkItemExecutionError(
            "repo_task_required",
            "必须提供 technical_plan_id 或 task_ids",
        )
    tasks = [
        task
        async for task in McpWorkItemRepoTask.objects.select_related(
            "repository", "technical_plan", "coding_plan", "plan_version", "execution_trace"
        )
        .filter(id__in=task_ids)
        .order_by("technical_plan_id", "order")
    ]
    if len(tasks) != len(set(task_ids)):
        raise WorkItemExecutionError("repo_task_not_found", "部分 repo task 不存在")
    return tasks[0].technical_plan, tasks


def _coding_plan_body(task: McpWorkItemRepoTask) -> dict[str, Any]:
    body = task.task_body if isinstance(task.task_body, dict) else {}
    files = list(body.get("candidate_files") or [])
    # WR-01：透传最富信息的 coding_instruction 供编码代理消费——requirement/steps 在
    # change_goal/steps 缺失时回退到 coding_instruction，避免方案细节在编码链路丢失。
    coding_instruction = str(body.get("coding_instruction") or "")
    requirement = str(body.get("change_goal") or "") or coding_instruction
    steps = list(body.get("steps") or [])
    if not steps and coding_instruction:
        steps = [coding_instruction]
    return {
        "title": f"{task.repository.name}: Feishu work item task",
        "requirement": requirement,
        "problem_statement": requirement,
        "affected_files": files,
        "steps": steps,
        "test_plan": list(body.get("test_strategy") or []),
        "risks": list(body.get("risks") or []),
        "rollback": str(body.get("rollback") or ""),
    }


async def _ensure_coding_plan(
    *,
    run: InteractionRun,
    task: McpWorkItemRepoTask,
    initiated_by_user_id: str | None = None,
) -> tuple[McpCodingPlan, McpCodingPlanVersion]:
    if task.coding_plan_id and task.plan_version_id:
        plan = await McpCodingPlan.objects.select_related("repository").aget(id=task.coding_plan_id)
        version = await McpCodingPlanVersion.objects.aget(id=task.plan_version_id)
        return plan, version

    body = _coding_plan_body(task)
    plan = await McpCodingPlan.objects.acreate(
        run=run,
        repository=task.repository,
        branch=task.target_branch or task.repository.default_branch,
        requirement=str(body.get("requirement") or ""),
        title=str(body.get("title") or task.repository.name)[:240],
        current_version=1,
    )
    version = await McpCodingPlanVersion.objects.acreate(
        plan=plan,
        run=run,
        version=1,
        plan_body=body,
        affected_files=list(body.get("affected_files") or []),
        steps=list(body.get("steps") or []),
        test_plan=list(body.get("test_plan") or []),
        risks=list(body.get("risks") or []),
        evidence=[
            {
                "kind": "file",
                "source": "work_item_repo_task",
                "task_id": str(task.id),
                "technical_plan_id": str(task.technical_plan_id),
            }
        ],
        change_summary="Initial work item repo task coding plan",
        risk_delta={"added": [], "reduced": []},
    )
    task.coding_plan = plan
    task.plan_version = version
    task.status = McpWorkItemRepoTask.Status.PLANNED
    task.recovery_state = {"retryable": True, "stage": "planned"}
    await task.asave(
        update_fields=["coding_plan", "plan_version", "status", "recovery_state", "updated_at"]
    )
    from knowledge import ingestion  # lazy import 防循环

    # KNOW-03：MCP 产物入统一知识库（INV-6 唯一通路，on_commit + 后台，异常自吞不阻塞）；
    # initiated_by_user_id 由视图层透传真实触发用户（InteractionRun 无 user 字段，
    # 不可从 run 读取——101 WR-01），后台摄取日志可归因（LO-02，无触发用户缺省 system）。
    await ingestion.aschedule_ingestion(
        ingestion.IngestionRequest("mcp_coding_plan", str(plan.id), "mcp_work_item_plan_created"),
        initiated_by_user_id=initiated_by_user_id,
    )
    return plan, version


async def _load_trace(task: McpWorkItemRepoTask) -> McpCodingExecutionTrace | None:
    if not task.execution_trace_id:
        return None
    return await McpCodingExecutionTrace.objects.filter(id=task.execution_trace_id).afirst()


async def _execute_one_task(
    *,
    run: InteractionRun,
    task: McpWorkItemRepoTask,
    dispatch: bool,
    create_merge_requests: bool,
    timeout_seconds: int,
    reviewer_usernames: list[str],
    initiated_by_user_id: str | None = None,
) -> McpWorkItemRepoTask:
    task.repository = await Repository.objects.aget(id=task.repository_id)
    if task.status == McpWorkItemRepoTask.Status.COMPLETED and (
        task.mr_url or not create_merge_requests
    ):
        return task

    plan, version = await _ensure_coding_plan(
        run=run, task=task, initiated_by_user_id=initiated_by_user_id
    )
    trace = await _load_trace(task)
    if dispatch and trace is None:
        trace = await McpCodingExecutionTrace.objects.acreate(
            run=run,
            plan=plan,
            plan_version=version,
            repository=task.repository,
            branch_name=task.branch_name,
            target_branch=task.target_branch or task.repository.default_branch,
            timeout_seconds=timeout_seconds,
        )
        try:
            await dispatch_execution(
                trace=trace,
                plan=plan,
                version=version,
                branch_name=task.branch_name,
                target_branch=task.target_branch,
                timeout_seconds=timeout_seconds,
            )
        except ExecutionDispatchError as exc:
            trace.status = McpCodingExecutionTrace.Status.FAILED
            trace.error = str(exc)
            trace.recovery_state = {
                "retryable": True,
                "stage": "dispatch",
                "error": str(exc),
            }
            await trace.asave(update_fields=["status", "error", "recovery_state", "updated_at"])
        await refresh_execution_trace(trace)
        from knowledge import ingestion  # lazy import 防循环

        # KNOW-03：MCP 产物入统一知识库（INV-6 唯一通路，on_commit + 后台，异常自吞不阻塞）；
        # initiated_by_user_id 由视图层透传真实触发用户（InteractionRun 无 user 字段，
        # 不可从 run 读取——101 WR-01），后台摄取日志可归因（LO-02，无触发用户缺省 system）。
        await ingestion.aschedule_ingestion(
            ingestion.IngestionRequest(
                "mcp_execution_trace", str(trace.id), "mcp_work_item_execution_created"
            ),
            initiated_by_user_id=initiated_by_user_id,
        )
        task.execution_trace = trace

    execution_payload = execution_trace_payload(trace) if trace is not None else {}
    task.commit_sha = str(execution_payload.get("commit_sha") or "")
    task.branch_name = str(execution_payload.get("branch_name") or task.branch_name)
    task.target_branch = str(execution_payload.get("target_branch") or task.target_branch)
    task.result = {"execution": execution_payload}
    task.recovery_state = {
        "retryable": True,
        "stage": "execution",
        "execution_status": execution_payload.get("status", task.status),
    }
    task.error = ""

    if trace is not None and trace.status == McpCodingExecutionTrace.Status.FAILED:
        task.status = McpWorkItemRepoTask.Status.FAILED
        task.error = trace.error
    elif trace is not None and trace.status in {
        McpCodingExecutionTrace.Status.RUNNING,
        McpCodingExecutionTrace.Status.DISPATCHING,
        McpCodingExecutionTrace.Status.QUEUED,
    }:
        task.status = McpWorkItemRepoTask.Status.RUNNING
    elif not dispatch:
        task.status = McpWorkItemRepoTask.Status.PLANNED
    elif trace is not None and trace.status == McpCodingExecutionTrace.Status.COMPLETED:
        task.status = (
            McpWorkItemRepoTask.Status.COMPLETED
            if task.mr_url or not create_merge_requests
            else McpWorkItemRepoTask.Status.PARTIAL
        )
        if task.status == McpWorkItemRepoTask.Status.COMPLETED:
            task.recovery_state = {"retryable": False, "stage": "completed"}
    else:
        task.status = McpWorkItemRepoTask.Status.PARTIAL

    if (
        create_merge_requests
        and trace is not None
        and trace.status in {
            McpCodingExecutionTrace.Status.COMPLETED,
            McpCodingExecutionTrace.Status.PARTIAL,
        }
        and task.branch_name
        and not task.mr_url
    ):
        try:
            summary = await summarize_branch(
                repository=task.repository,
                source_branch=task.branch_name,
                target_branch=task.target_branch or task.repository.default_branch,
                max_files=50,
                trace=trace,
            )
            mr = await create_merge_request(
                repository=task.repository,
                source_branch=task.branch_name,
                target_branch=task.target_branch or task.repository.default_branch,
                title=str((summary.get("mr_draft") or {}).get("title") or ""),
                description=str((summary.get("mr_draft") or {}).get("description") or ""),
                reviewer_usernames=reviewer_usernames,
                remove_source_branch=True,
                trace=trace,
            )
            task.result = {**task.result, "branch_summary": summary, "mr": mr}
            if mr.get("success"):
                task.status = McpWorkItemRepoTask.Status.COMPLETED
                task.mr_url = str(mr.get("mr_url") or "")
                task.recovery_state = {"retryable": False, "stage": "completed"}
            else:
                task.status = McpWorkItemRepoTask.Status.PARTIAL
                task.error = str(mr.get("error") or "")
                task.recovery_state = {
                    "retryable": True,
                    "stage": "merge_request",
                    "error": task.error,
                }
        except MergeRequestToolError as exc:
            task.status = McpWorkItemRepoTask.Status.PARTIAL
            task.error = str(exc)
            task.recovery_state = {
                "retryable": True,
                "stage": "merge_request",
                "error": str(exc),
            }

    await task.asave(
        update_fields=[
            "coding_plan",
            "plan_version",
            "execution_trace",
            "status",
            "branch_name",
            "target_branch",
            "result",
            "recovery_state",
            "commit_sha",
            "mr_url",
            "error",
            "updated_at",
        ]
    )
    return task


def _repo_results(tasks: list[McpWorkItemRepoTask]):
    """把 MCP repo task 列表映射为公共回写层的中性 RepoResult（LOOP-01）。"""
    from delivery.services.coding_completion import RepoResult  # lazy import 防循环

    return [
        RepoResult(
            repo_name=task.repository.name,
            status=task.status,
            branch_name=task.branch_name,
            commit_sha=task.commit_sha,
            mr_url=task.mr_url or "",
            error=task.error or "",
        )
        for task in tasks
    ]


def _execution_results_markdown(tasks: list[McpWorkItemRepoTask]) -> str:
    """薄委托：渲染模板已迁至 delivery.services.coding_completion（LOOP-01）。"""
    from delivery.services.coding_completion import render_results_markdown  # lazy import 防循环

    return render_results_markdown(_repo_results(tasks))


async def _write_results_back(
    *,
    technical_plan: McpWorkItemTechnicalPlan,
    tasks: list[McpWorkItemRepoTask],
    markdown: str,
    initiated_by_user_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """薄包装：飞书两写委托 CompletionWritebackService，MCP 专属 plan 状态翻转留在本层。

    零回归契约（Phase 101 LOOP-01）：签名入参新增 keyword ``initiated_by_user_id``
    外不变；返回 ``(document_update, comment)`` 外形不变；``retry_state`` 仅在
    error 分支写入（成功路径不动）。

    已知边界差异（101 IN-02，当前不可达、记录在案防误修）：改造前只要
    ``technical_plan.space`` 存在就会尝试评论——``feishu_project_key`` 为空串也会
    打到飞书 API → 失败 → error → PARTIAL 翻转 + ``retry_state.retryable=True``；
    公共层则在三元组任一缺失（空 project_key / 空 work_item_type /
    ``work_item_id is None``）时记 ``writeback_skipped`` 后双 skipped 返回，
    不翻 PARTIAL、不置 retry_state。由于 ``McpWorkItemTechnicalPlan`` 三字段
    NOT NULL 且创建链路必填，MCP 现网数据下两者行为一致；未来若出现空串
    project_key 的脏数据，行为为 skipped（新语义），**这不是回归**。
    """
    document_update: dict[str, Any] = {"status": "skipped"}
    comment: dict[str, Any] = {"status": "skipped"}

    body = dict(technical_plan.plan_body or {})
    body["execution_results"] = [repo_task_payload(task) for task in tasks]
    technical_plan.plan_body = body
    technical_plan.markdown = (technical_plan.markdown or "").rstrip() + "\n\n" + markdown

    # 零回归守门：改造前 doc append / 评论两写均以 technical_plan.space 为前置条件。
    # space 为 None 时直接跳过公共 service 调用、保持双 skipped——否则 service 会经
    # feishu_project_key 反查 Space，可能命中并回写，引入改造前不存在的新行为。
    if technical_plan.space is not None:
        from delivery.services.coding_completion import (  # lazy import 防循环
            CompletionWritebackService,
        )

        document_update, comment = await CompletionWritebackService().awrite_back(
            feishu_project_key=technical_plan.feishu_project_key,
            work_item_type=technical_plan.work_item_type,
            work_item_id=technical_plan.work_item_id,
            title=technical_plan.title,
            results=_repo_results(tasks),
            space=technical_plan.space,
            feishu_document_id=technical_plan.feishu_document_id or "",
            doc_markdown=markdown,
            initiated_by_user_id=initiated_by_user_id,
        )

    technical_plan.comment_result = {
        **(technical_plan.comment_result if isinstance(technical_plan.comment_result, dict) else {}),
        "execution_comment": comment,
        "document_update": document_update,
    }
    if document_update.get("status") == "error" or comment.get("status") == "error":
        technical_plan.status = McpWorkItemTechnicalPlan.Status.PARTIAL
        retry_state = technical_plan.retry_state if isinstance(technical_plan.retry_state, dict) else {}
        technical_plan.retry_state = {
            **retry_state,
            "retryable": True,
            "failed_stage": retry_state.get("failed_stage") or "execution_writeback",
        }
        if not technical_plan.error_stage:
            technical_plan.error_stage = "execution_writeback"
        if not technical_plan.error:
            technical_plan.error = str(document_update.get("error") or comment.get("error") or "")
    await technical_plan.asave(
        update_fields=[
            "plan_body",
            "markdown",
            "comment_result",
            "status",
            "retry_state",
            "error_stage",
            "error",
            "updated_at",
        ]
    )
    return document_update, comment


async def execute_work_item_repo_tasks(
    *,
    run: InteractionRun,
    technical_plan_id: str,
    task_ids: list[str],
    create_missing: bool,
    dispatch: bool,
    create_merge_requests: bool,
    write_back: bool,
    timeout_seconds: int,
    reviewer_usernames: list[str],
    initiated_by_user_id: str | None = None,
) -> RepoTaskExecutionResult:
    technical_plan, tasks = await _resolve_tasks(
        run=run,
        technical_plan_id=technical_plan_id,
        task_ids=task_ids,
        create_missing=create_missing,
    )
    if not tasks:
        raise WorkItemExecutionError("repo_task_not_found", "没有可执行的 repo task")

    executed: list[McpWorkItemRepoTask] = []
    for task in tasks:
        executed.append(
            await _execute_one_task(
                run=run,
                task=task,
                dispatch=dispatch,
                create_merge_requests=create_merge_requests,
                timeout_seconds=timeout_seconds,
                reviewer_usernames=reviewer_usernames,
                initiated_by_user_id=initiated_by_user_id,
            )
        )

    markdown = _execution_results_markdown(executed)
    document_update = {"status": "skipped"}
    comment = {"status": "skipped"}
    if write_back:
        document_update, comment = await _write_results_back(
            technical_plan=technical_plan,
            tasks=executed,
            markdown=markdown,
            # 观测归因（CONTEXT 观测决策 / 101 WR-01）：MCP 链的真实触发用户由
            # ExecuteWorkItemRepoTasksView 经 request.user 透传（InteractionRun 无
            # user 字段）；取不到传 None → 公共层记 "system"。
            initiated_by_user_id=initiated_by_user_id,
        )

    # LOOP-03（101-03）：learning case 提炼锚点——MR 结果已知之后（_execute_one_task
    # 内已完成 MR 创建，符合 STATE 约束"不挂容器回调"）。经 run_in_background 后台
    # 调度、不 await Future；整块 fail-soft，绝不影响执行返回值（T-101-03-03）。
    try:
        from mcp_tools.learning_case_extraction import (  # lazy import 防循环
            aextract_for_session,
        )
        from services.background_runner import run_in_background

        initiated_by = initiated_by_user_id
        for task in executed:
            if task.status != McpWorkItemRepoTask.Status.COMPLETED or not task.execution_trace_id:
                continue
            session_id = (
                await McpCodingExecutionTrace.objects.filter(id=task.execution_trace_id)
                .values_list("subagent_session__session_id", flat=True)
                .afirst()
            )
            if not session_id:
                continue
            run_in_background(
                lambda sid=session_id, mr=task.mr_url or "": aextract_for_session(
                    sid,
                    requirement_text=technical_plan.title,
                    work_item_type=technical_plan.work_item_type,
                    work_item_id=technical_plan.work_item_id,
                    pr_url=mr,
                    initiated_by_user_id=initiated_by,
                ),
                name=f"learning-case-{session_id}",
                initiated_by_user_id=initiated_by,
            )
    except Exception as exc:  # noqa: BLE001 — 提炼调度 fail-soft
        logger.warning(
            "learning_case_schedule_failed",
            technical_plan_id=str(technical_plan.id),
            error=str(exc),
            category="sampling",
            component="mcp_tools",
        )

    status_values = {task.status for task in executed}
    overall = "completed" if status_values == {McpWorkItemRepoTask.Status.COMPLETED} else "partial"
    if status_values == {McpWorkItemRepoTask.Status.FAILED}:
        overall = "failed"
    if write_back and (
        document_update.get("status") == "error" or comment.get("status") == "error"
    ) and overall == "completed":
        overall = "partial"
    output = {
        "technical_plan_id": str(technical_plan.id),
        "tasks": [repo_task_payload(task) for task in executed],
        "summary": {
            "total": len(executed),
            "completed": sum(1 for task in executed if task.status == McpWorkItemRepoTask.Status.COMPLETED),
            "partial": sum(1 for task in executed if task.status == McpWorkItemRepoTask.Status.PARTIAL),
            "failed": sum(1 for task in executed if task.status == McpWorkItemRepoTask.Status.FAILED),
            "running": sum(1 for task in executed if task.status == McpWorkItemRepoTask.Status.RUNNING),
        },
        "document_update": document_update,
        "comment": comment,
        "status": overall,
        "run_id": str(run.run_id),
    }
    from knowledge import ingestion  # lazy import 防循环

    plan_id = str(technical_plan.id)
    # 101 WR-01：与同文件其余投递一致，绑定真实触发用户（缺省 None → system）。
    await ingestion.aschedule_ingestion(
        ingestion.IngestionRequest("mcp_technical_plan", plan_id, "mcp_tasks_executed"),
        initiated_by_user_id=initiated_by_user_id,
    )
    return RepoTaskExecutionResult(
        technical_plan=technical_plan,
        tasks=executed,
        output=output,
    )
