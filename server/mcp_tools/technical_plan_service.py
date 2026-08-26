"""Technical-plan generation and Feishu writeback for work item MCP flows.

UNIFY-03：方案生成已从独立确定性 ``_build_repo_task_matrix`` seam **改为 delegate 到
``process_runtime`` 统一编排**（经 ``delegate_process_runtime`` 产 canonical §7
MergedPlan/PlanVersion），再**显式映射回旧 MCP 响应字段**（外形兼容，调用方不破坏），并
继续落 ``McpWorkItemTechnicalPlan`` 保兼容。飞书文档/评论 writeback 逻辑保留（喂 delegate
产的 markdown + 映射后的 repository_tasks）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from agents.tools.feishu_doc_tools import create_feishu_doc_client_for_project
from interactions.models import InteractionRun
from mcp_tools.learning_case_service import search_learning_cases
from mcp_tools.models import McpWorkItemContext, McpWorkItemTechnicalPlan
from mcp_tools.orchestration_delegate import delegate_process_runtime
from services.feishu import create_feishu_client_for_project
from services.feishu_doc import FeishuDocAPIError, PermissionDeniedError, RateLimitError

logger = structlog.get_logger(__name__)


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


_STATUS_MAP: dict[str, McpWorkItemTechnicalPlan.Status] = {
    "completed": McpWorkItemTechnicalPlan.Status.COMPLETED,
    "partial": McpWorkItemTechnicalPlan.Status.PARTIAL,
    "failed": McpWorkItemTechnicalPlan.Status.FAILED,
}


def _map_status(delegate_status: str) -> McpWorkItemTechnicalPlan.Status:
    """delegate 三态 → McpWorkItemTechnicalPlan.Status（未知态保守落 PARTIAL）。"""
    return _STATUS_MAP.get(delegate_status, McpWorkItemTechnicalPlan.Status.PARTIAL)


async def _ablueprint_response_extras(delegate: Any) -> dict[str, Any]:
    """mcp 入口开关切到蓝图时的三个追加响应键（GATE-01，Phase 116-06）。

    ⭐ **开关关闭时返回空 dict ⇒ 响应与改动前逐字相同**（既有 12 个键一个不多不少）。
    ⛔ 开关实参必须是**字面量常量** ``"mcp"``：写成 ``session.entrypoint``（蓝图 MCP 会话
    的 ``entrypoint`` 是既有约定的 ``"workflow"``）会让打开 workflow 键把 MCP 一起切走
    （116-01 的 ``ast`` 守卫覆盖本调用点）。

    五键语义：``blueprint_artifact_id``（蓝图 artifact，**后续一切续取/作答的寻址键**）、
    ``blueprint_current_status``（⚠️ 键名刻意不叫 ``blueprint_status``——那会命中 INV-6 的
    字段级旁路守卫 ``_RE_FIELD_DICT_KEY``）、当前 artifact 版本的 ``blueprint_artifact_version_id`` /
    ``blueprint_content_hash``，以及 ``pending_clarifications[]``（待人回答的阻塞线程，形状与
    ``get_technical_blueprint`` **共享同一份装配**）。版本键只用于展示当前快照；编码交接必须
    等待最终 approve 后另行持久化的 approved_* 键。

    整段 ``try/except`` 回空 dict：⭐ 这是**响应装饰**而非业务主体——读不出蓝图侧信息时
    调用方仍能拿到既有 12 键的完整方案响应，⛔ 绝不因为附加信息读失败而废掉整次调用。
    """
    from services.process_runtime.blueprint_entry_switch import aresolve_entry_process_type

    try:
        if await aresolve_entry_process_type("mcp") != "technical_blueprint":
            return {}
        from delivery.models import Artifact, ArtifactVersion
        from mcp_tools.views import _aload_pending_clarifications

        version_id = getattr(delegate.session, "current_artifact_version_id", None)
        if not version_id:
            return {}
        version_row = (
            await ArtifactVersion.objects.filter(id=version_id)
            .values("artifact_id", "content_hash")
            .afirst()
        )
        artifact_id = str((version_row or {}).get("artifact_id") or "")
        if not artifact_id:
            return {}
        current_status = str(
            await Artifact.objects.filter(id=artifact_id)
            .values_list("blueprint_status", flat=True)
            .afirst()
            or ""
        )
        return {
            "blueprint_artifact_id": artifact_id,
            "blueprint_current_status": current_status,
            "blueprint_artifact_version_id": str(version_id),
            "blueprint_content_hash": str((version_row or {}).get("content_hash") or ""),
            "pending_clarifications": await _aload_pending_clarifications(artifact_id),
        }
    except Exception:  # noqa: BLE001 — 响应装饰读失败不废掉既有 12 键的方案响应
        return {}


async def _ablueprint_artifact_id_or_fail(delegate: Any) -> str:
    """蓝图会话必须能持久化其 artifact 归属，绝不静默降级成可执行 legacy plan。

    ``_ablueprint_response_extras`` 是兼容性装饰，按历史契约允许失败回空；但编码交接的
    artifact 关联是安全判据，不能复用这个 fail-soft 分支。真正进入 technical_blueprint
    会话却解析不到 artifact 时，宁可整次 MCP plan 创建失败，也不能留下无 gate 的记录。
    """
    session = getattr(delegate, "session", None)
    if str(getattr(session, "process_type", "") or "") != "technical_blueprint":
        return ""
    version_id = getattr(session, "current_artifact_version_id", None)
    if not version_id:
        raise TechnicalPlanError("blueprint_identity_unavailable", "技术蓝图未返回可交接版本")
    from delivery.models import ArtifactVersion

    artifact_id = str(
        await ArtifactVersion.objects.filter(id=version_id)
        .values_list("artifact_id", flat=True)
        .afirst()
        or ""
    )
    if not artifact_id:
        raise TechnicalPlanError("blueprint_identity_unavailable", "技术蓝图未返回可交接版本")
    return artifact_id


def _str_list(value: Any) -> list[str]:
    """半可信 LLM 产物 → 去空白后的 ``list[str]``（非 list 恒空 list，防御性）。"""
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _project_canonical_for_legacy_mapping(content: dict[str, Any]) -> dict[str, Any]:
    """blueprint/v1 content → 旧响应映射器认得的 v0 投影（同步点 2，审计 §4.1 的 G3）。

    ⭐ **这是 G3 的修法本体**。既有映射链读的是 v0 ``MergedPlan`` 的三个顶层键
    （``title`` / ``summary`` / ``execution_plan``），而 blueprint/v1 **一个都没有**：
    标题与摘要在 ``meta`` 下，``execution_plan`` 是「确认后确定性派生」的**可选**段
    （``blueprint_schema`` ``:741``，required 键表 ``:123-134`` 不含它）。⇒ 直接把
    blueprint content 喂给 ``_map_execution_plan_to_repository_tasks`` 恒返回 ``[]``：
    响应的十二键**结构合法、语义为空**，调用方读不出任何一个仓库任务却也拿不到任何错误
    信号 —— 静默降级。

    做法是**确定性派生**（⛔ 不是补一个空壳）：``implementation_overview.items`` 本就是
    ``execution_plan`` 的派生源，``blueprint_execution.derive_execution_plan`` 是既有的
    权威派生器（纯函数、同输入逐字节一致、产物过 ``validate_technical_plan``）——直接复用，
    ⛔ 本模块不写第二份派生逻辑。

    ⭐ **非 blueprint/v1 恒等返回**：旧链 content 原样穿过，映射链逐字不变（零回归）。
    """
    from services.process_runtime.blueprint_execution import derive_execution_plan
    from services.process_runtime.blueprint_schema import BLUEPRINT_SCHEMA_VERSION

    if not isinstance(content, dict) or content.get("schema_version") != BLUEPRINT_SCHEMA_VERSION:
        return content if isinstance(content, dict) else {}

    meta = content.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    return {
        "title": str(meta.get("title") or ""),
        "summary": _blocks_to_plain_text(meta.get("summary")),
        "execution_plan": derive_execution_plan(content),
    }


def _log_blueprint_payload_projection(
    delegate: Any,
    content: dict[str, Any],
    legacy_view: dict[str, Any],
    repository_tasks: list[dict[str, Any]],
) -> None:
    """蓝图主载荷派生的埋点（**只在蓝图分支落**，best-effort）。

    ⭐ 存在的理由是让「派生出来还是空」这件事**可查**：G3 之所以能跨六个相位不被发现，
    正是因为空载荷不打任何信号。派生结果为空而蓝图确实有实现项时落 ``warning``（那是
    真异常：``repo_associations`` 与 ``items`` 的 repository_id 对不上，派生器会整批丢弃）；
    正常派生落 ``sampling`` 级 info。⛔ 不落任何正文内容，只落计数。
    """
    try:
        if content is legacy_view:  # 旧链恒等穿过 ⇒ 不打蓝图埋点（避免旧链日志噪声）
            return
        overview = content.get("implementation_overview")
        item_count = len((overview or {}).get("items") or []) if isinstance(overview, dict) else 0
        fields = {
            "category": "sampling",
            "component": "mcp_tools",
            "session_id": str(getattr(getattr(delegate, "session", None), "id", "") or ""),
            "blueprint_item_count": item_count,
            "derived_task_count": len(legacy_view.get("execution_plan") or []),
            "repository_task_count": len(repository_tasks),
        }
        if item_count > 0 and not repository_tasks:
            logger.warning("mcp_blueprint_payload_projection_empty", **fields)
        else:
            logger.info("mcp_blueprint_payload_projected", **fields)
    except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬业务
        pass


def _blocks_to_plain_text(blocks: Any) -> str:
    """Block[] → 纯文本摘要（只取 paragraph/list 的 ``text``，⛔ 不渲染代码/表格）。

    用途仅是把 blueprint ``meta.summary`` 塞进旧响应的 ``summary`` 字符串位；富渲染归
    ``markdown`` 那一位（走 ``render_blueprint_markdown``），两者不重复。
    """
    if not isinstance(blocks, list):
        return ""
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, list):
            entries = [str(entry) for entry in text if isinstance(entry, str) and entry]
            if entries:
                parts.append("\n".join(f"- {entry}" for entry in entries))
        elif isinstance(text, str) and text:
            parts.append(text)
    return "\n\n".join(parts)


def _map_execution_plan_to_repository_tasks(content: dict[str, Any]) -> list[dict[str, Any]]:
    """canonical §7 ``execution_plan[]`` → 旧 ``repository_tasks`` 矩阵形态（外形兼容）。

    **显式字段映射白名单**（T-94-03-INFO：绝不透传 content 内部键），逐项 best-effort
    取 ``repository_id`` / ``repository_name`` / ``coding_instruction`` / ``branch_strategy``
    （→ planned_branch）/ ``files[].path``（→ candidate_files）/ ``dependencies`` /
    ``base_branch``（IN-02：canonical 含基线分支则透传，缺则下游回退仓库默认分支）。

    WR-01：下游 ``work_item_execution_service._coding_plan_body`` 从 ``task_body`` 读取
    ``steps`` / ``test_strategy`` / ``risks`` / ``rollback``，故这些键必须映射进每项（canonical
    task 含同名字段则直取；缺 ``steps`` 时把最富信息的 ``coding_instruction`` 落为单步，避免
    编码代理拿到空步骤而丢失方案细节）。``coding_instruction`` 始终透传供下游消费。缺字段填空
    不抛（半可信 LLM 产物防御）。
    """
    raw_plan = content.get("execution_plan") if isinstance(content, dict) else None
    if not isinstance(raw_plan, list):
        return []
    execution_plan: list[Any] = raw_plan
    tasks: list[dict[str, Any]] = []
    for index, item in enumerate(execution_plan, start=1):
        if not isinstance(item, dict):
            continue
        raw_files = item.get("files")
        files = raw_files if isinstance(raw_files, list) else []
        candidate_files = [
            str(f.get("path") or "") for f in files if isinstance(f, dict) and f.get("path")
        ]
        coding_instruction = str(item.get("coding_instruction") or "")
        change_goal = (
            str(item.get("description") or "") or coding_instruction or str(item.get("name") or "")
        )
        dependencies = item.get("dependencies")
        dependencies = dependencies if isinstance(dependencies, list) else []
        # WR-01：steps 缺失时把 coding_instruction 落为单步，保证编码代理拿到方案细节。
        steps = _str_list(item.get("steps"))
        if not steps and coding_instruction:
            steps = [coding_instruction]
        tasks.append(
            {
                "order": index,
                "repository_id": str(item.get("repository_id") or ""),
                "repository_name": str(item.get("repository_name") or ""),
                "planned_branch": str(item.get("branch_strategy") or ""),
                # IN-02：canonical 含 base_branch 则透传（缺则下游回退仓库默认分支）。
                "base_branch": str(item.get("base_branch") or ""),
                "change_goal": change_goal,
                "coding_instruction": coding_instruction,
                "candidate_files": candidate_files,
                "dependencies": [str(dep) for dep in dependencies],
                # WR-01：下游 _coding_plan_body 读取的方案细节键（含 coding_instruction 兜底）。
                "steps": steps,
                "test_strategy": _str_list(item.get("test_strategy")),
                "risks": _str_list(item.get("risks")),
                "rollback": str(item.get("rollback") or ""),
            }
        )
    return tasks


def _map_plan_payload(
    *,
    content: dict[str, Any],
    context: McpWorkItemContext,
    plan_title: str,
    repository_tasks: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    similar_cases: list[dict[str, Any]],
    summary: str | None = None,
) -> dict[str, Any]:
    """canonical content → 旧 ``plan`` / ``plan_body`` 外形（WR-02，外形兼容）。

    UNIFY-03 曾把嵌套 ``plan`` / 落库 ``plan_body`` 整体替换为 canonical §7 content，破坏读
    ``plan.repository_task_matrix`` / ``plan.work_item`` / ``plan.summary`` 的旧调用方（且与
    ``repository_tasks`` 的「显式白名单、绝不透传 content 内部键」原则自相矛盾）。本函数把
    canonical 显式映射回旧关键键，保持响应/落库外形兼容；canonical content 仍以独立
    ``canonical_content`` 键保留（不丢信息、可追踪）。

    ``summary``（同步点 2 / G3，**纯追加、缺省 None**）：调用方给定的摘要。blueprint/v1 的
    摘要在 ``meta.summary``（Block[]）而不是顶层 ``summary``，由调用方经
    :func:`_project_canonical_for_legacy_mapping` 取好后传进来。⛔ 不传时逐字回退读
    ``content["summary"]`` ⇒ 旧链行为不变。
    """
    if summary is None:
        summary = str(content.get("summary") or "") if isinstance(content, dict) else ""
    linked_documents = [
        {
            "document_id": str(doc.get("document_id") or ""),
            "url": str(doc.get("url") or ""),
            "status": str(doc.get("status") or ""),
        }
        for doc in context.documents or []
    ]
    return {
        "title": plan_title,
        "summary": summary,
        "work_item": {
            "feishu_project_key": context.feishu_project_key,
            "work_item_type": context.work_item_type,
            "work_item_id": context.work_item_id,
            "name": context.name,
            "work_item_status": context.work_item_status,
        },
        "repository_task_matrix": repository_tasks,
        "linked_documents": linked_documents,
        "similar_cases": similar_cases,
        "evidence": evidence,
        "context_preview": _preview(_work_item_text(context), 500),
        # canonical §7 content 保留（不丢信息、可追踪；旧外形键见上）。
        "canonical_content": content,
    }


def _preview(value: str, limit: int = 500) -> str:
    text = value.strip()
    return text[:limit] + ("..." if len(text) > limit else "")


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
        await McpWorkItemContext.objects.select_related("space").filter(id=context_id).afirst()
    )
    if context is None:
        raise TechnicalPlanError("work_item_context_not_found", "工作项上下文快照不存在")
    return context


async def _resolve_delivery_work_item(context: McpWorkItemContext) -> Any:
    """按飞书三元组解析 canonical delivery ``WorkItem`` 作 delegate 编排锚（INV-2 可空）。

    ``afirst`` 取（无则 None，编排以「自然语言需求」continue，文档化降级）；async 防裸
    lazy-FK：用标量三元组过滤、不裸访问 FK。
    """
    from delivery.models import WorkItem

    return await WorkItem.objects.filter(
        feishu_project_key=context.feishu_project_key,
        work_item_type=context.work_item_type,
        work_item_id=context.work_item_id,
    ).afirst()


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
    return (
        {
            "document_id": result.get("document_id", ""),
            "url": result.get("url", ""),
            "folder_token": target_folder,
        },
        "",
        "",
    )


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
    actor: Any = None,
    assumptions_tier: str = "",
) -> TechnicalPlanResult:
    """delegate 到 ``process_runtime`` 产 canonical 方案 → 映射回旧响应外形 + 落库（UNIFY-03）。

    ``actor`` 为发起编排的用户（从 view 透传 request.user，可空）：delegate 经
    ``start_orchestration(created_by=actor)`` 传入，召回 stage 据此作权限 actor；为 None 时
    下游 ``search_similar`` fail-closed 空召回（不泄漏越权数据，T-94-03-ELEV 文档化降级）。

    ``assumptions_tier``（116-REVIEW MJ-02，**纯追加、缺省空串**）：MCP 面向调用方开放的
    「交互密度」旋钮（``strict`` / ``balanced`` / ``assume_more``），原样透传 delegate。
    ⭐ **仅在 mcp 开关切到蓝图时生效**；不传 / 旧链一律与改动前逐字相同。
    """
    context = await _resolve_context(context_id)
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
            # 权限主体 = 发起编排的用户（可空）：None 时 search_similar fail-closed
            # 空召回，不泄漏越权数据（T-94-03-ELEV 同款文档化降级）。
            user=actor,
        )

    # UNIFY-03：方案生成 delegate 到统一编排（绝不在 MCP 层重写拆分/路由/调研/融合）。
    work_item = await _resolve_delivery_work_item(context)
    delegate = await delegate_process_runtime(
        requirement_text=_work_item_text(context),
        work_item=work_item,
        include_repos=repository_ids,
        created_by=actor,
        # 116-06：接上 116-03 交接的 `work_item_context` 形参。⛔ 不传即「推不出
        # meta.project_id ⇒ 拒绝发起」——mcp 开关打开时蓝图链会**恒不可用**。
        work_item_context=context,
        # 116-REVIEW MJ-02：档位从 MCP 请求透传到 stage_state，⇒ spec_gate 真的读得到。
        assumptions_tier=assumptions_tier,
    )
    # 116-06（GATE-01）：开关切到蓝图时的三个追加响应键（关闭时为空 dict）。
    blueprint_extras = await _ablueprint_response_extras(delegate)
    # 蓝图真实入口的归属是编码门禁事实源；响应 extras 失败时也必须 fail-closed，不能让
    # 后续 create_work_item_repo_tasks 把它误认成历史 legacy plan。
    blueprint_artifact_id = await _ablueprint_artifact_id_or_fail(delegate)
    content = delegate.content if isinstance(delegate.content, dict) else {}
    # 同步点 2 / G3：blueprint/v1 先确定性派生成 v0 投影，再走既有映射链（映射器逐字不变；
    # 旧链 content 恒等穿过 ⇒ 零回归）。⛔ canonical 仍以原始 content 落 canonical_content。
    legacy_view = _project_canonical_for_legacy_mapping(content)
    # canonical → 旧响应字段显式映射（外形兼容，绝不透传 content 内部键，T-94-03-INFO）。
    repository_tasks = _map_execution_plan_to_repository_tasks(legacy_view)
    _log_blueprint_payload_projection(delegate, content, legacy_view, repository_tasks)
    markdown = delegate.markdown or ""
    plan_title = (
        title.strip()
        or str(legacy_view.get("title") or "")
        or f"{context.name or context.work_item_type} 技术方案"
    )
    evidence = _evidence_from_context(
        context=context,
        context_chunks=context_chunks,
        similar_cases=effective_similar_cases,
    )
    # WR-02：旧 plan/plan_body 外形（repository_task_matrix/work_item/summary 等）映射自
    # canonical，保持响应/落库外形兼容（canonical content 仍以 canonical_content 键保留）。
    plan_payload = _map_plan_payload(
        content=content,
        context=context,
        plan_title=plan_title,
        repository_tasks=repository_tasks,
        evidence=evidence,
        similar_cases=effective_similar_cases,
        summary=str(legacy_view.get("summary") or ""),
    )

    # 终态/挂起 → 落库 status 基线（编排在途 partial / 失败 failed），writeback 失败再降级。
    status = _map_status(delegate.status)
    error_stage = ""
    error = ""
    retry_state: dict[str, Any] = {
        "retryable": False,
        "document_created": False,
        "comment_written": False,
        "failed_stage": "",
    }
    if blueprint_extras:
        # ⭐ 蓝图的 DONE 语义是「等人审」而不是「方案已终结」⇒ 对 MCP 调用方一律回
        # `partial`（既有三态之一，`retry_state` 形态照旧 ⇒ 调用方零破坏），据
        # `pending_clarifications` 逐条作答、再用 `get_technical_blueprint` 续取终稿。
        status = McpWorkItemTechnicalPlan.Status.PARTIAL
        retry_state.update({"retryable": True, "failed_stage": "blueprint_pending"})
    if delegate.status == "partial":
        # 编排挂起（RESEARCHING/CLARIFYING 在途，MCP 无 resume 通路）：调用方据 session_id 续推。
        retry_state.update({"retryable": True, "failed_stage": "orchestration_pending"})
    elif delegate.status == "failed":
        # ⭐ 116-REVIEW MJ-03：区分「拒绝发起」与「编排跑了但没产出」两类失败。
        #
        # `error_detail` 非空 = 蓝图 intake 在**建会话之前**就如实拒绝了（当前唯一来源是
        # 「推不出 meta.project_id」）。这是**确定性**失败——Space→Project 换算不出来，
        # 重试一百次结果一样 ⇒ ⛔ 绝不置 `retryable: True` 诱导调用方重试；同时把 116-03
        # 一路保住的**中性** detail 如实回显（⛔ 不含内部路径 / 异常原文），
        # ⛔ 不要再用「编排未产出 canonical 方案」这句**错的原因**盖掉它。
        rejected = bool(str(getattr(delegate, "error_detail", "") or ""))
        error_stage = "blueprint_intake" if rejected else "orchestration"
        retry_state.update({"retryable": not rejected, "failed_stage": error_stage})
        error = str(getattr(delegate, "error_detail", "") or "") or "编排未产出 canonical 方案"

    # writeback 仅在编排产出方案（非 failed）时进行（喂 delegate markdown + 映射后矩阵）。
    feishu_document: dict[str, Any] = {"status": "skipped"}
    if create_document and delegate.status != "failed":
        doc_payload, stage, doc_error = await _create_feishu_document(
            context=context,
            title=plan_title,
            markdown=markdown,
            folder_token=folder_token,
        )
        if stage:
            status = McpWorkItemTechnicalPlan.Status.PARTIAL
            if not error_stage:
                error_stage = stage
                error = doc_error
            retry_state.update(
                {"retryable": True, "failed_stage": retry_state.get("failed_stage") or stage}
            )
            feishu_document = {"status": "error", "error": doc_error}
        else:
            feishu_document = {"status": "created", **doc_payload}
            retry_state["document_created"] = True

    comment_result: dict[str, Any] = {"status": "skipped"}
    if write_comment and delegate.status != "failed":
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
            retry_state.update(
                {"retryable": True, "failed_stage": retry_state.get("failed_stage") or stage}
            )
            comment_result = {"status": "error", "error": comment_error}
        else:
            comment_result = {"status": "written", **comment_payload}
            retry_state["comment_written"] = True

    # McpWorkItemTechnicalPlan 继续落库（plan_body=旧外形映射 WR-02，字段全保留兼容 A5）。
    artifact = await McpWorkItemTechnicalPlan.objects.acreate(
        run=run,
        context=context,
        space=context.space,
        feishu_project_key=context.feishu_project_key,
        work_item_type=context.work_item_type,
        work_item_id=context.work_item_id,
        title=plan_title[:240],
        status=status,
        plan_body=plan_payload,
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
        blueprint_artifact_id=blueprint_artifact_id,
    )
    # 响应外形兼容：保留全部既有键 + 新增可选 session_id（partial 时供调用方续推）。
    output = {
        "technical_plan_id": str(artifact.id),
        "context_id": str(context.id),
        "project_id": str(context.space_id) if context.space_id else "",
        "plan": plan_payload,
        "markdown": markdown,
        "repository_tasks": repository_tasks,
        "evidence": evidence,
        "feishu_document": feishu_document,
        "comment": comment_result,
        "status": status,
        "retry_state": retry_state,
        "run_id": str(run.run_id),
        "session_id": str(delegate.session.id),
        # ⭐ 116-REVIEW MJ-03：失败原因必须**回传**而不是只落 McpWorkItemTechnicalPlan 行。
        # 回退前 agent 拿到的响应体里一个字的解释都没有（`retry_state` 只有一个布尔），
        # 而它读的正是响应体。恒写两键（成功时为空串，形态与 feature 方案三工具的 `error`
        # 键同款）：⛔ 中性文案，不含内部路径 / 异常原文。
        "error": error,
        "error_stage": error_stage,
        # 116-06：⭐ 纯追加三键，**仅在 mcp 开关切到蓝图时非空**（见
        # `_ablueprint_response_extras`）；开关关闭时本行展开为零键 ⇒ 响应逐字不变。
        **blueprint_extras,
    }
    from knowledge import ingestion  # lazy import 防循环

    await ingestion.aschedule_ingestion(
        ingestion.IngestionRequest("mcp_technical_plan", str(artifact.id), "mcp_plan_created")
    )
    traces = [(str(item.get("kind") or "file"), item) for item in evidence]
    return TechnicalPlanResult(artifact=artifact, output=output, traces=traces)


async def pin_approved_blueprint_handoff(
    *,
    technical_plan_id: str,
    artifact_id: str,
    artifact_version_id: str,
    content_hash: str,
) -> dict[str, Any]:
    """把已确认 Friday 蓝图的**当前不可变版本**写入下游编码交接。

    这里不做审批状态迁移：调用方必须先经 ``aapprove_blueprint`` 成功。此函数只把与该
    审批同一版本的 canonical content 确定性映射到既有 repository_tasks，再保存版本 id /
    hash。下游将再次核验这四个值，因此任何一次返工或新版本都会 fail-closed 阻止编码。
    """
    from delivery.models import Artifact, ArtifactVersion, BlueprintStatus
    from services.process_runtime.blueprint_render import render_blueprint_markdown

    technical_plan = await McpWorkItemTechnicalPlan.objects.filter(id=technical_plan_id).afirst()
    if technical_plan is None:
        raise TechnicalPlanError("technical_plan_not_found", "技术方案不存在")
    if technical_plan.blueprint_artifact_id != artifact_id:
        raise TechnicalPlanError("blueprint_handoff_mismatch", "技术方案不属于该技术蓝图")

    artifact = (
        await Artifact.objects.select_related("current_version").filter(id=artifact_id).afirst()
    )
    if (
        artifact is None
        or str(getattr(artifact, "blueprint_status", "") or "") != BlueprintStatus.CONFIRMED
    ):
        raise TechnicalPlanError("blueprint_not_confirmed", "技术蓝图尚未确认，不能交接编码")
    version = await ArtifactVersion.objects.filter(
        id=artifact_version_id, artifact_id=artifact_id
    ).afirst()
    if (
        version is None
        or str(getattr(artifact, "current_version_id", "") or "") != artifact_version_id
        or str(getattr(version, "content_hash", "") or "") != content_hash
    ):
        raise TechnicalPlanError("blueprint_handoff_stale", "技术蓝图版本已变化，请重新读取并确认")

    content = version.content if isinstance(version.content, dict) else {}
    legacy_view = _project_canonical_for_legacy_mapping(content)
    repository_tasks = _map_execution_plan_to_repository_tasks(legacy_view)
    if not repository_tasks:
        raise TechnicalPlanError("blueprint_handoff_empty", "已确认蓝图没有可交接的仓库任务")

    plan_body = dict(technical_plan.plan_body) if isinstance(technical_plan.plan_body, dict) else {}
    plan_body["canonical_content"] = content
    plan_body["repository_task_matrix"] = repository_tasks
    plan_body["summary"] = str(legacy_view.get("summary") or plan_body.get("summary") or "")
    technical_plan.plan_body = plan_body
    technical_plan.repository_tasks = repository_tasks
    technical_plan.markdown = render_blueprint_markdown(
        content, blueprint_status=BlueprintStatus.CONFIRMED
    )
    technical_plan.approved_blueprint_version_id = artifact_version_id
    technical_plan.approved_blueprint_version_no = int(getattr(version, "version_no", 0) or 0)
    technical_plan.approved_blueprint_content_hash = content_hash
    technical_plan.status = McpWorkItemTechnicalPlan.Status.COMPLETED
    technical_plan.retry_state = {
        **(technical_plan.retry_state if isinstance(technical_plan.retry_state, dict) else {}),
        "retryable": False,
        "failed_stage": "",
        "blueprint_handoff": "approved",
    }
    await technical_plan.asave(
        update_fields=[
            "plan_body",
            "markdown",
            "repository_tasks",
            "approved_blueprint_version_id",
            "approved_blueprint_version_no",
            "approved_blueprint_content_hash",
            "status",
            "retry_state",
            "updated_at",
        ]
    )
    return {
        "technical_plan_id": str(technical_plan.id),
        "artifact_id": artifact_id,
        "artifact_version_id": artifact_version_id,
        "version_no": int(version.version_no),
        "content_hash": content_hash,
        "markdown": technical_plan.markdown,
        "repository_task_count": len(repository_tasks),
    }
