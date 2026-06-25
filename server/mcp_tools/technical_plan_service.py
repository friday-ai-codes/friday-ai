"""Technical-plan generation and Feishu writeback for work item MCP flows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, cast

from django.db.models import Q

from agents.tools.feishu_doc_tools import create_feishu_doc_client_for_project
from interactions.models import InteractionRun
from mcp_tools.learning_case_service import search_learning_cases
from mcp_tools.models import McpWorkItemContext, McpWorkItemTechnicalPlan
from repositories.models import FileIndex, IndexStatus, Repository
from services.feishu import create_feishu_client_for_project
from services.feishu_doc import FeishuDocAPIError, PermissionDeniedError, RateLimitError


class TechnicalPlanError(Exception):
    """Recoverable setup error while generating a work item technical plan."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class TechnicalPlanResult:
    artifact: McpWorkItemTechnicalPlan
    output: dict[str, Any]
    traces: list[tuple[str, dict[str, Any]]]


_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


def _slug(value: str) -> str:
    cleaned = _SLUG_RE.sub("-", value.lower()).strip("-")
    return cleaned[:60] or "work-item"


def _preview(value: str, limit: int = 500) -> str:
    text = value.strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def _table_cell(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("|", "\\|").replace("`", "\\`").replace("\n", "<br>").strip()


def _work_item_text(context: McpWorkItemContext) -> str:
    parts = [
        context.name,
        context.description,
        str(context.fields or {}),
        str(context.relations or []),
        " ".join(str(doc.get("content") or "") for doc in context.documents or []),
    ]
    return "\n".join(part for part in parts if part)


async def _resolve_context(context_id: str) -> McpWorkItemContext:
    context = (
        await McpWorkItemContext.objects.select_related("space")
        .filter(id=context_id)
        .afirst()
    )
    if context is None:
        raise TechnicalPlanError("work_item_context_not_found", "工作项上下文快照不存在")
    return context


async def _resolve_repositories(
    *,
    repository_ids: list[str],
    repo_hints: list[str],
    limit: int,
) -> list[Repository]:
    if repository_ids:
        repos_by_id: dict[str, Repository] = {}
        async for repo in Repository.objects.filter(id__in=repository_ids).aiterator():
            repos_by_id[str(repo.id)] = repo
        missing = [repo_id for repo_id in repository_ids if repo_id not in repos_by_id]
        if missing:
            raise TechnicalPlanError(
                "repository_not_found",
                f"仓库不存在: {', '.join(missing)}",
            )
        return [repos_by_id[repo_id] for repo_id in repository_ids]

    query = Q(index_status=IndexStatus.INDEXED)
    if repo_hints:
        hint_q = Q()
        for hint in repo_hints:
            hint_q |= Q(name__icontains=hint) | Q(description__icontains=hint)
        query &= hint_q
    repos = [repo async for repo in Repository.objects.filter(query).order_by("name")[:limit]]
    if repos or not repo_hints:
        return repos
    return [
        repo
        async for repo in Repository.objects.filter(index_status=IndexStatus.INDEXED)
        .order_by("name")[:limit]
    ]


async def _candidate_files(repo: Repository, context_chunks: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    repo_id = str(repo.id)
    for chunk in context_chunks:
        if str(chunk.get("repository_id") or repo_id) != repo_id:
            continue
        path = str(chunk.get("file_path") or "").strip()
        if path and path not in seen:
            paths.append(path)
            seen.add(path)
    async for item in FileIndex.objects.filter(repository=repo).order_by("file_path")[:8].aiterator():
        if item.file_path not in seen:
            paths.append(item.file_path)
            seen.add(item.file_path)
    return paths[:8]


def _evidence_from_context(
    *,
    context: McpWorkItemContext,
    context_chunks: list[dict[str, Any]],
    similar_cases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = [
        {
            "kind": "file",
            "source": "feishu_work_item_context",
            "context_id": str(context.id),
            "work_item_id": context.work_item_id,
            "work_item_type": context.work_item_type,
            "name": context.name,
        }
    ]
    for doc in context.documents or []:
        evidence.append(
            {
                "kind": "file",
                "source": "feishu_document",
                "document_id": doc.get("document_id", ""),
                "url": doc.get("url", ""),
                "status": doc.get("status", ""),
                "preview": _preview(str(doc.get("content") or ""), 300),
            }
        )
    for chunk in context_chunks:
        evidence.append(
            {
                "kind": "chunk",
                "source": "graphrag_chunk",
                "chunk_id": str(chunk.get("chunk_id") or ""),
                "repository_id": str(chunk.get("repository_id") or ""),
                "file_path": str(chunk.get("file_path") or ""),
                "score": chunk.get("score"),
                "preview": _preview(str(chunk.get("content") or ""), 300),
            }
        )
    for case in similar_cases:
        evidence.append(
            {
                "kind": "file",
                "source": "learning_case",
                "case_id": str(case.get("case_id") or case.get("id") or ""),
                "title": str(case.get("title") or ""),
                "outcome": str(case.get("outcome") or ""),
                "reuse_judgement": str(case.get("reuse_judgement") or "needs_review"),
            }
        )
    return evidence


async def _build_repo_task_matrix(
    *,
    context: McpWorkItemContext,
    repositories: list[Repository],
    context_chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    matrix: list[dict[str, Any]] = []
    item_slug = _slug(f"{context.work_item_type}-{context.work_item_id}-{context.name}")
    for index, repo in enumerate(repositories, start=1):
        branch = f"feat/feishu-{context.work_item_type}-{context.work_item_id}-{_slug(repo.name)}"
        files = await _candidate_files(repo, context_chunks)
        matrix.append(
            {
                "order": index,
                "repository_id": str(repo.id),
                "repository_name": repo.name,
                "base_branch": repo.base_branch or repo.default_branch,
                "planned_branch": branch[:200],
                "change_goal": f"根据 Feishu 工作项 {context.work_item_type}#{context.work_item_id} 实现或修复 {context.name}",
                "candidate_files": files,
                "steps": [
                    "确认工作项、关联文档和代码证据是否一致。",
                    "在候选文件附近完成最小可验证修改。",
                    "补充或更新覆盖该工作项行为的测试。",
                    "运行仓库相关测试并记录结果。",
                ],
                "test_strategy": [
                    "优先运行受影响模块的单元测试。",
                    "若变更跨服务，补充接口或集成级验证。",
                ],
                "risks": [
                    "候选文件来自现有索引和输入证据，执行前仍需读取最新分支代码确认。",
                    "Feishu 文档可能存在权限或内容截断，缺失信息需要在 PR/MR 描述中标明。",
                ],
                "rollback": f"回滚分支 `{branch[:200]}` 或 revert 该仓库对应 PR/MR commit。",
                "routing_reason": f"repo task {index} for {item_slug}",
            }
        )
    return matrix


def render_technical_plan_markdown(plan: dict[str, Any]) -> str:
    raw_work_item = plan.get("work_item")
    work_item = cast(dict[str, Any], raw_work_item) if isinstance(raw_work_item, dict) else {}
    repo_tasks = plan.get("repository_task_matrix")
    repo_tasks = repo_tasks if isinstance(repo_tasks, list) else []
    evidence = plan.get("evidence")
    evidence = evidence if isinstance(evidence, list) else []
    similar_cases = plan.get("similar_cases")
    similar_cases = similar_cases if isinstance(similar_cases, list) else []

    lines = [
        f"# {plan.get('title') or 'Feishu 工作项技术方案'}",
        "",
        "## 工作项",
        "",
        f"- 类型：{work_item.get('work_item_type', '')}",
        f"- ID：{work_item.get('work_item_id', '')}",
        f"- 名称：{work_item.get('name', '')}",
        f"- 状态：{work_item.get('status', '')}",
        "",
        "## 方案摘要",
        "",
        str(plan.get("summary") or ""),
        "",
        "## 仓库任务矩阵",
        "",
        "| 仓库 | 分支 | 修改目标 | 候选文件 | 测试 | 风险 |",
        "|---|---|---|---|---|---|",
    ]
    if repo_tasks:
        for task in repo_tasks:
            files = (
                "<br>".join(_table_cell(path) for path in task.get("candidate_files", [])[:6])
                or "待执行前确认"
            )
            tests = "<br>".join(_table_cell(item) for item in task.get("test_strategy", [])[:4])
            risks = "<br>".join(_table_cell(item) for item in task.get("risks", [])[:4])
            lines.append(
                "| {repo} | `{branch}` | {goal} | {files} | {tests} | {risks} |".format(
                    repo=_table_cell(task.get("repository_name", "")),
                    branch=_table_cell(task.get("planned_branch", "")),
                    goal=_table_cell(task.get("change_goal", "")),
                    files=files,
                    tests=tests,
                    risks=risks,
                )
            )
    else:
        lines.append("| 待路由 | 待生成 | 需要补充 repository_ids 或 repo_hints | 待确认 | 待确认 | repo routing 未命中 |")
    lines.extend(["", "## 执行步骤", ""])
    for task in repo_tasks:
        lines.append(f"### {task.get('repository_name', '')}")
        for step in task.get("steps", []):
            lines.append(f"- {step}")
        lines.append("")
    lines.extend(["## 相似案例", ""])
    if similar_cases:
        for case in similar_cases:
            lines.append(
                f"- {case.get('title') or case.get('case_id') or case.get('id')}: "
                f"{case.get('reuse_judgement') or 'needs_review'}"
            )
    else:
        lines.append("- 暂无已召回相似案例。")
    lines.extend(["", "## 证据", ""])
    for item in evidence[:20]:
        label = item.get("source", "evidence")
        target = item.get("file_path") or item.get("document_id") or item.get("case_id") or item.get("context_id")
        lines.append(f"- {label}: {target}")
    lines.extend(["", "## 回滚", ""])
    if repo_tasks:
        for task in repo_tasks:
            lines.append(f"- {task.get('repository_name', '')}: {task.get('rollback', '')}")
    else:
        lines.append("- 未创建 repo task 前无需代码回滚。")
    return "\n".join(lines).strip() + "\n"


async def _create_feishu_document(
    *,
    context: McpWorkItemContext,
    title: str,
    markdown: str,
    folder_token: str,
) -> tuple[dict[str, Any], str, str]:
    project = context.space
    if project is None:
        return {}, "document_writeback", "工作项上下文未关联 Friday 项目"
    target_folder = folder_token or getattr(project, "feishu_doc_folder_token", "") or ""
    if not target_folder:
        return {}, "document_writeback", "未配置 Feishu 文档文件夹 token"
    try:
        doc_client = await create_feishu_doc_client_for_project(project)
        result = await doc_client.create_document(
            title=title,
            folder_token=target_folder,
            content=markdown,
        )
    except ValueError as exc:
        return {}, "document_writeback", str(exc)
    except (FeishuDocAPIError, PermissionDeniedError, RateLimitError) as exc:
        return {}, "document_writeback", str(exc)
    return {
        "document_id": result.get("document_id", ""),
        "url": result.get("url", ""),
        "folder_token": target_folder,
    }, "", ""


async def _write_work_item_comment(
    *,
    context: McpWorkItemContext,
    plan_title: str,
    document_url: str,
    repository_tasks: list[dict[str, Any]],
) -> tuple[dict[str, Any], str, str]:
    project = context.space
    if project is None:
        return {}, "work_item_comment", "工作项上下文未关联 Friday 项目"
    lines = [
        f"Friday 已生成技术方案：{plan_title}",
        "",
        f"方案文档：{document_url or '未创建或创建失败，详见 Friday 记录'}",
        "",
        "仓库任务：",
    ]
    for task in repository_tasks:
        lines.append(
            f"- {task.get('repository_name', '')}: `{task.get('planned_branch', '')}` - "
            f"{task.get('change_goal', '')}"
        )
    try:
        client = create_feishu_client_for_project(project)
        ok = await client.add_comment(
            context.feishu_project_key,
            context.work_item_id,
            context.work_item_type,
            "\n".join(lines),
        )
    except Exception as exc:  # noqa: BLE001 - upstream Feishu failures are persisted as partial.
        return {}, "work_item_comment", str(exc)
    if not ok:
        return {}, "work_item_comment", "Feishu 工作项评论写入失败"
    return {"written": True, "document_url": document_url}, "", ""


async def build_work_item_technical_plan(
    *,
    run: InteractionRun,
    context_id: str,
    repository_ids: list[str],
    repo_hints: list[str],
    context_chunks: list[dict[str, Any]],
    similar_cases: list[dict[str, Any]],
    title: str,
    folder_token: str,
    create_document: bool,
    write_comment: bool,
) -> TechnicalPlanResult:
    context = await _resolve_context(context_id)
    repositories = await _resolve_repositories(
        repository_ids=repository_ids,
        repo_hints=repo_hints,
        limit=5,
    )
    effective_similar_cases = similar_cases
    if not effective_similar_cases:
        effective_similar_cases = await search_learning_cases(
            query=_work_item_text(context),
            work_item_type=context.work_item_type,
            repo_hints=repo_hints,
            file_hints=[
                str(chunk.get("file_path") or "")
                for chunk in context_chunks
                if isinstance(chunk, dict)
            ],
            symbol_hints=[],
            limit=5,
        )
    repository_tasks = await _build_repo_task_matrix(
        context=context,
        repositories=repositories,
        context_chunks=context_chunks,
    )
    plan_title = title.strip() or f"{context.name or context.work_item_type} 技术方案"
    evidence = _evidence_from_context(
        context=context,
        context_chunks=context_chunks,
        similar_cases=effective_similar_cases,
    )
    work_item = {
        "context_id": str(context.id),
        "project_key": context.feishu_project_key,
        "work_item_type": context.work_item_type,
        "work_item_id": context.work_item_id,
        "name": context.name,
        "status": context.work_item_status,
        "source": (context.context or {}).get("work_item", {}).get("source", {}),
    }
    plan_body = {
        "title": plan_title,
        "summary": (
            f"基于 Feishu 工作项、关联文档和代码证据，计划按 {len(repository_tasks)} 个仓库任务执行。"
            if repository_tasks
            else "尚未命中仓库任务，需要补充 repository_ids、repo_hints 或 GraphRAG 证据。"
        ),
        "work_item": work_item,
        "repository_task_matrix": repository_tasks,
        "linked_documents": context.documents,
        "similar_cases": effective_similar_cases,
        "evidence": evidence,
        "context_preview": _preview(_work_item_text(context), 1200),
    }
    markdown = render_technical_plan_markdown(plan_body)

    status = McpWorkItemTechnicalPlan.Status.COMPLETED
    error_stage = ""
    error = ""
    retry_state: dict[str, Any] = {
        "retryable": False,
        "document_created": False,
        "comment_written": False,
        "failed_stage": "",
    }

    feishu_document: dict[str, Any] = {"status": "skipped"}
    if create_document:
        doc_payload, stage, doc_error = await _create_feishu_document(
            context=context,
            title=plan_title,
            markdown=markdown,
            folder_token=folder_token,
        )
        if stage:
            status = McpWorkItemTechnicalPlan.Status.PARTIAL
            error_stage = stage
            error = doc_error
            retry_state.update({"retryable": True, "failed_stage": stage})
            feishu_document = {"status": "error", "error": doc_error}
        else:
            feishu_document = {"status": "created", **doc_payload}
            retry_state["document_created"] = True

    comment_result: dict[str, Any] = {"status": "skipped"}
    if write_comment:
        comment_payload, stage, comment_error = await _write_work_item_comment(
            context=context,
            plan_title=plan_title,
            document_url=str(feishu_document.get("url") or ""),
            repository_tasks=repository_tasks,
        )
        if stage:
            status = McpWorkItemTechnicalPlan.Status.PARTIAL
            if not error_stage:
                error_stage = stage
                error = comment_error
            retry_state.update({"retryable": True, "failed_stage": retry_state.get("failed_stage") or stage})
            comment_result = {"status": "error", "error": comment_error}
        else:
            comment_result = {"status": "written", **comment_payload}
            retry_state["comment_written"] = True

    if not repository_tasks:
        status = McpWorkItemTechnicalPlan.Status.PARTIAL
        if not error_stage:
            error_stage = "repository_routing"
            error = "未生成仓库任务矩阵"
        retry_state.update({"retryable": True, "failed_stage": retry_state.get("failed_stage") or "repository_routing"})

    artifact = await McpWorkItemTechnicalPlan.objects.acreate(
        run=run,
        context=context,
        space=context.space,
        feishu_project_key=context.feishu_project_key,
        work_item_type=context.work_item_type,
        work_item_id=context.work_item_id,
        title=plan_title[:240],
        status=status,
        plan_body=plan_body,
        markdown=markdown,
        repository_tasks=repository_tasks,
        evidence=evidence,
        similar_cases=effective_similar_cases,
        feishu_document_id=str(feishu_document.get("document_id") or ""),
        feishu_document_url=str(feishu_document.get("url") or ""),
        comment_result=comment_result,
        retry_state=retry_state,
        error_stage=error_stage,
        error=error,
    )
    output = {
        "technical_plan_id": str(artifact.id),
        "context_id": str(context.id),
        "project_id": str(context.space_id) if context.space_id else "",
        "plan": plan_body,
        "markdown": markdown,
        "repository_tasks": repository_tasks,
        "evidence": evidence,
        "feishu_document": feishu_document,
        "comment": comment_result,
        "status": status,
        "retry_state": retry_state,
        "run_id": str(run.run_id),
    }
    from knowledge import ingestion  # lazy import 防循环

    await ingestion.aschedule_ingestion(
        ingestion.IngestionRequest("mcp_technical_plan", str(artifact.id), "mcp_plan_created")
    )
    traces = [(str(item.get("kind") or "file"), item) for item in evidence]
    return TechnicalPlanResult(artifact=artifact, output=output, traces=traces)
