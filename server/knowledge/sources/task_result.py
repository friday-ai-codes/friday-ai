"""TaskResult → [tech_plan 锚, code_change] 双事件 normalizer（Plan 14-06 / INGEST-02 + KMOD-05 + ENH-01）。

normalizer 即 DiffArchiver 的后台执行体：触发点（编码完成三锚点）只投
``IngestionRequest("task_result", session_id, trigger)``，全部重 IO（拉 diff /
解析 / 压缩归档 / 符号对齐）经 ``diff_archive.archive_code_change`` 在
background worker 内完成。

锁定语义（14-06 规划定案）：

- **时序防线（Pitfall 1）**：diff 归档挂 MR/PR 创建之后——容器回调主路径不投递，
  因此本模块运行时刻 mr_url 权威源已就绪。
- **mr_url 权威源三路（checker blocker 修订定案）**：``TaskResult.pr_url`` 在
  两条主路径几乎恒为空串（PR/MR 由 server 侧在容器回调之后创建）——
  ① chat（trigger 前缀 ``chat_coding_``）= ``CodingSession.pr_url``
  （skip 路径空串属预期，归档走 branch diff）；
  ② workflow（``workflow_coding_completed``）= ``node_execution.output_data``
  持久化的 ``mr_results``（Task 2 投递前写入）按 repository 匹配，缺失时回退读
  引擎覆盖后的 ``merge_requests``（``_build_output`` 落点，封竞态窗口）；
  ③ 仅旧兼容路径（``legacy_coding_completed``，容器内建 MR 的历史模式）以
  ``task_result.pr_url`` 为源。
- **归属权威（T-14-22）**：repository / 方案恒从服务端权威 FK 取
  （``CodingSession.repository`` / ``session.node_execution``）；
  session 上由容器回写的输出 JSON 字段可被 runner 篡改，本模块零接触。
- **边方向**：``IMPLEMENTED_BY = 方案→代码变更``，EdgeSpec 挂 **tech_plan 锚事件**
  （target=code_change 实体 id，经 ``generate_entity_id`` 唯一入口）；
  MODIFIES_CHUNK chunk EdgeSpec 挂 **code_change 事件**（ArchiveResult 原样转挂）。
  锚事件短路重摄无害——skipped 事件仍执行边阶段（13-02 契约）。
- **payload 纪律（T-14-24）**：code_change payload 恒带 project_id/repository_id
  与 archive_id/commit_sha/mr_url 摘要，diff 原文绝不进 payload。
"""

from __future__ import annotations

import json

import structlog
from django.utils import timezone

from knowledge import diff_archive
from knowledge.ingestion import EdgeSpec, IngestionEvent, IngestionRequest
from knowledge.models import EdgeRelation, EntityKind, EntityOrigin, generate_entity_id

logger = structlog.get_logger(__name__)

__all__ = ["normalize"]


def _mr_id_from_url(mr_url: str) -> str:
    """从 mr_url 尾段解析 MR/PR 编号（``.../merge_requests/7`` / ``.../pull/1`` → ``"7"/"1"``）。"""
    tail = mr_url.rstrip("/").rpartition("/")[2]
    return tail if tail.isdigit() else ""


def _resolve_workflow_mr(output_data: dict, repository_id: str) -> tuple[str, str] | None:
    """从 node_execution.output_data 取本仓库的 (mr_url, mr_id)。

    主源 ``mr_results``（Task 2 投递前持久化形态）；缺失时回退
    ``merge_requests``（节点完成后引擎以 ``_build_output`` 覆盖 output_data 的
    落点，每项同样有 repository_id/mr_url/mr_id——封掉覆盖竞态窗口）。
    """
    items = output_data.get("mr_results") or output_data.get("merge_requests") or []
    for item in items:
        if isinstance(item, dict) and str(item.get("repository_id", "")) == repository_id:
            mr_url = str(item.get("mr_url") or "")
            mr_id = str(item.get("mr_id") or "") or _mr_id_from_url(mr_url)
            return mr_url, mr_id
    return None


async def normalize(request: IngestionRequest) -> list[IngestionEvent]:
    """TaskResult → 双事件；源/仓库缺失或归档失败均空列表 + warning，不 raise。"""
    from chat.models import CodingSession
    from subagent.models import TaskResult
    from workflows.models.execution import NodeExecution, NodeExecutionStatus

    task_result = (
        await TaskResult.objects.select_related(
            "session",
            "session__node_execution",
            "session__node_execution__workflow_execution",
        )
        .filter(session__session_id=request.source_id)
        .order_by("-created_at")
        .afirst()
    )
    if task_result is None:
        logger.warning(
            "knowledge_normalize_source_missing",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
        )
        return []
    session = task_result.session
    node_execution = session.node_execution

    # ---- 归属解析（T-14-22：只走服务端权威 FK，容器回写输出零接触）----
    coding_session = (
        await CodingSession.objects.select_related(
            "repository", "coding_plan", "conversation", "conversation__space"
        )
        .filter(subagent_session=session)
        .afirst()
    )
    repository = None
    space_id: str | None = None
    if coding_session is not None:
        repository = coding_session.repository
        project_id = (
            str(coding_session.conversation.space_id)
            if coding_session.conversation.space_id
            else None
        )
    elif node_execution is not None:
        execution = node_execution.workflow_execution
        project_id = str(execution.space_id) if execution.space_id else None
        # 仓库归属：output_data.pending_sessions（dispatch 时服务端写入）按 session_id 匹配
        from repositories.models import Repository

        output_data = node_execution.output_data or {}
        repository_id = next(
            (
                str(item.get("repository_id", ""))
                for item in output_data.get("pending_sessions") or []
                if isinstance(item, dict) and item.get("session_id") == request.source_id
            ),
            "",
        )
        if repository_id:
            repository = await Repository.objects.filter(id=repository_id).afirst()
        if repository is None and session.repo_url:
            # 兜底：dispatch 时同样由服务端写入的 repo_url（防引擎覆盖 output_data）
            repository = await Repository.objects.filter(git_url=session.repo_url).afirst()
    if repository is None:
        logger.warning(
            "knowledge_normalize_repository_missing",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
        )
        return []

    # ---- mr_url / mr_id 解析（权威源三路定案；除 legacy 分支不读 task_result.pr_url）----
    if request.trigger == "workflow_coding_completed":
        resolved = _resolve_workflow_mr(
            (node_execution.output_data or {}) if node_execution else {}, str(repository.id)
        )
        if resolved is None:
            logger.warning(
                "knowledge_normalize_mr_result_missing",
                source_kind=request.source_kind,
                source_id=request.source_id,
                trigger=request.trigger,
                repository_id=str(repository.id),
            )
            mr_url, mr_id = "", ""
        else:
            mr_url, mr_id = resolved
    elif request.trigger == "legacy_coding_completed":
        # 历史模式：容器内建 MR，TaskResult 自带 pr_url（唯一允许读它的分支）
        mr_url = task_result.pr_url
        mr_id = _mr_id_from_url(mr_url)
    else:
        # chat_coding_* 前缀（skip 路径空串属预期 → 归档走 branch diff）
        mr_url = coding_session.pr_url if coding_session is not None else ""
        mr_id = _mr_id_from_url(mr_url)

    # ---- DiffArchiver（唯一重 IO 调用；normalizer 即后台执行体）----
    completed_at = session.completed_at or task_result.created_at
    event_time = (
        timezone.make_aware(completed_at) if timezone.is_naive(completed_at) else completed_at
    )
    result = await diff_archive.archive_code_change(
        source_kind="task_result",
        source_id=request.source_id,
        repository=repository,
        branch_name=task_result.branch_name,
        base_branch=repository.default_branch,
        commit_sha=task_result.commit_sha,
        mr_url=mr_url,
        mr_id=mr_id,
        event_time=event_time,
    )
    if result is None:
        logger.warning(
            "knowledge_normalize_archive_failed",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
            repository_id=str(repository.id),
        )
        return []

    origin = EntityOrigin.WORKFLOW if coding_session is None else EntityOrigin.CHAT
    code_change_event = IngestionEvent(
        kind=EntityKind.CODE_CHANGE,
        origin=origin,
        source_kind="task_result",
        source_id=request.source_id,
        title=f"{repository.name} @ {task_result.commit_sha[:8]}",
        content=result.content,
        # 摘要纪律（T-14-24）：archive_id/commit_sha/mr_url + 统计，diff 原文不进 payload
        payload={
            "archive_id": str(result.archive.id),
            "commit_sha": task_result.commit_sha,
            "mr_url": mr_url,
            "branch_name": task_result.branch_name,
            "repository_id": str(repository.id),
            "file_count": result.archive.file_count,
            "total_additions": result.archive.total_additions,
            "total_deletions": result.archive.total_deletions,
        },
        space_id=project_id,
        repository_id=str(repository.id),
        event_time=event_time,
        edges=tuple(result.edge_specs),
    )

    # ---- tech_plan 锚事件（短路重摄同源拼法 + IMPLEMENTED_BY 出边挂锚）----
    implemented_by = (
        EdgeSpec(
            relation=EdgeRelation.IMPLEMENTED_BY,
            target_entity_id=generate_entity_id("code_change", "task_result", request.source_id),
        ),
    )
    anchor_event: IngestionEvent | None = None
    coding_plan = coding_session.coding_plan if coding_session is not None else None
    if coding_plan is not None:
        # chat：coding_plan normalizer 同款拼法（OQ-3 锁定：title + 空行 + tech_plan）
        first_line = coding_plan.tech_plan.splitlines()[0] if coding_plan.tech_plan else ""
        anchor_event = IngestionEvent(
            kind=EntityKind.TECH_PLAN,
            origin=EntityOrigin.CHAT,
            source_kind="coding_plan",
            source_id=str(coding_plan.id),
            title=coding_plan.title or first_line[:200],
            content=f"{coding_plan.title}\n\n{coding_plan.tech_plan}",
            payload={
                "title": coding_plan.title,
                "affected_files": coding_plan.affected_files,
                "recommended_repository_ids": coding_plan.recommended_repository_ids,
            },
            space_id=project_id,
            repository_id=None,
            event_time=event_time,
            edges=implemented_by,
        )
    elif node_execution is not None:
        # workflow：同 execution 的 ai_plan_generation 节点（14-04 同款查询）→ 生成节点 key
        generation = (
            await NodeExecution.objects.filter(
                workflow_execution_id=node_execution.workflow_execution_id,
                node__node_type="ai_plan_generation",
                status=NodeExecutionStatus.COMPLETED,
            )
            .exclude(output_data={})
            .order_by("-completed_at")
            .afirst()
        )
        plan_dict = (generation.output_data or {}).get("plan") if generation else None
        if generation is not None and isinstance(plan_dict, dict):
            title = str(plan_dict.get("title") or "技术方案")
            summary = str(plan_dict.get("summary") or "")
            execution_plan = plan_dict.get("execution_plan") or []
            if isinstance(execution_plan, str):
                execution_plan_text = execution_plan
            else:
                execution_plan_text = json.dumps(execution_plan, ensure_ascii=False, indent=2)
            anchor_event = IngestionEvent(
                kind=EntityKind.TECH_PLAN,
                origin=EntityOrigin.WORKFLOW,
                source_kind="workflow_plan",
                # workflow_plan normalizer 同款 key：{execution_id}:{node_id}（OQ-2 定案）
                source_id=f"{node_execution.workflow_execution_id}:{generation.node_id}",
                title=title,
                content=f"# {title}\n\n## 摘要\n{summary}\n\n## 执行计划\n{execution_plan_text}",
                payload={
                    "title": title,
                    "execution_id": str(node_execution.workflow_execution_id),
                    "node_id": str(generation.node_id),
                },
                space_id=project_id,
                repository_id=None,
                event_time=event_time,
                edges=implemented_by,
            )

    if anchor_event is None:
        # 无方案降级：边随锚缺席，code_change 单事件仍入图（chunk 边不受影响）
        logger.warning(
            "knowledge_normalize_anchor_plan_missing",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
        )
        return [code_change_event]
    return [anchor_event, code_change_event]
