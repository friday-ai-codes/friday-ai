"""共享 MCP delegate 核心（UNIFY-03）——MCP 入口归一到统一编排底座。

把 MCP 工具的「方案生成」从各自确定性 seam 收口到 ``process_runtime`` 统一编排：
建 ``PlanSession``（entrypoint=workflow）→ ``build_orchestration_engine(skip_clarification=True)``
→ ``adrive`` 续驱到终态/挂起 → 取 canonical ``PlanVersion.content``（§7 MergedPlan）→ 终态/
挂起映射为 ``DelegateResult``。**绝不在 MCP 层重写拆分/路由/调研/融合**（只调共享 helper，落
CONTEXT「最大化复用，严禁重复造」）。

挂起态语义（Open Q1 决议）：MCP 入口注入「跳过交互澄清」policy（best-effort 用现有上下文），
编排若仍挂起 ``RESEARCHING``/``CLARIFYING``（容器在途、MCP 无 resume 通路）则返回
``status="partial"`` + ``session``（调用方据 ``session.id`` 后续经会话/工作流续推）。

**async ORM 防裸 lazy-FK**：全程用 ``current_plan_version`` 标量 / ``afirst``，绝不裸访问
``session`` 的同步 lazy-FK。观测：进出口 best-effort 埋点（category=caller、component=
mcp_tools、duration_ms、status）；编排内部 LLM/召回埋点由 process_runtime adapters 承担
（call_source 链路完整，无需 MCP 层重复赋值）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from repositories.models import Repository

logger = structlog.get_logger(__name__)

__all__ = ["DelegateResult", "delegate_process_runtime", "map_canonical_to_coding_plan"]


@dataclass(frozen=True)
class DelegateResult:
    """MCP delegate 编排结果（终态/挂起统一外形）。

    - ``session``：底层 ``PlanSession``（调用方取 ``session.id`` 作 partial 续推钥匙 / 落库锚）。
    - ``status``：``completed`` | ``partial`` | ``failed``（映射自 PlanSession 终态/挂起态）。
    - ``content``：canonical §7 ``MergedPlan`` content（DONE 取 ``PlanVersion.content``；
      partial best-effort 当前版本或 ``{}``；failed 恒 ``{}``）。
    - ``plan_version_id``：canonical ``PlanVersion.id``（无则 None）。
    - ``markdown``：``render_merged_plan_markdown(content)`` 结构化渲染（复用 94-01 共享 helper）。
    - ``model_usage``：本次编排聚合的模型用量（WR-03，best-effort）。编排 adapters 经
      ``arecord_llm_usage`` 落用量行但不挂 MCP run，故 delegate 把本次驱动窗口内的 token/
      duration 聚合回传，由 MCP view 落到自身 run 维度，避免 token/成本归因回退（空则 ``{}``）。
    - ``error_detail``（116-03，**纯追加、缺省空串**）：可直接回显给调用方的**中性**失败文案
      （当前唯一来源是蓝图分支「推不出 ``meta.project_id`` ⇒ 拒绝发起」）。⛔ 不含内部路径 /
      异常原文。既有调用方不读它 ⇒ 响应外形零破坏；把它接进 MCP 响应体归 **116-06**。
    """

    session: Any
    status: str
    content: dict
    plan_version_id: str | None
    markdown: str
    model_usage: dict = field(default_factory=dict)
    error_detail: str = ""


async def _load_canonical(session: Any) -> tuple[str | None, dict, str]:
    """best-effort 取 session 当前 canonical content + 渲染 markdown（async 防裸 lazy-FK）。

    用 ``current_plan_version`` 标量 + ``afirst`` 取 ``PlanVersion``；content 非 dict 时回退
    ``{}`` / 空串（防御性，对齐 render/merged_plan fail-safe）。

    ⭐ **蓝图会话换渲染器**（同步点 2 / G3 的 markdown 那一半）：
    ``render_merged_plan_markdown`` 读的是 v0 ``MergedPlan`` 的顶层键，对 blueprint/v1
    会渲染出一篇**结构合法而内容为空**的文档 —— 而这篇 markdown 正是写进飞书文档的那份。
    蓝图走 ``render_blueprint_markdown``（水印由它按 ``blueprint_status`` 无条件加）。
    """
    from delivery.models import ArtifactVersion
    from services.process_runtime import render_merged_plan_markdown
    from services.process_runtime.blueprint_observation import is_blueprint_session

    av_id = (
        str(session.current_artifact_version_id) if session.current_artifact_version_id else None
    )
    if not av_id:
        return None, {}, ""
    av = await ArtifactVersion.objects.filter(id=av_id).afirst()
    if av is None or not isinstance(av.content, dict):
        return av_id, {}, ""
    if is_blueprint_session(session):
        return av_id, av.content, await _arender_blueprint(session, av.content)
    return av_id, av.content, render_merged_plan_markdown(av.content)


async def _arender_blueprint(session: Any, content: dict) -> str:
    """blueprint/v1 content → markdown（水印按真实 ``blueprint_status`` 渲染）。

    取不到状态时传空串 —— ``render_blueprint_markdown`` 的白名单是**闭合集合**，空串落在
    集合外 ⇒ 当作「未确认」渲染水印，方向恰好是 fail-safe。整段吞异常回空串：markdown 是
    响应装饰，⛔ 渲染失败不废掉主载荷（主载荷的正确性由 G3 的派生投影单独保证）。
    """
    try:
        from services.process_runtime.blueprint_observation import (
            ablueprint_observation,
            render_observed_blueprint,
        )

        observation = await ablueprint_observation(session, with_threads=False)
        return render_observed_blueprint(content, observation.current_status)
    except Exception:  # noqa: BLE001 — 渲染是装饰，绝不废掉主载荷
        logger.warning(
            "mcp_blueprint_markdown_render_failed",
            category="sampling",
            component="mcp_tools",
            session_id=str(getattr(session, "id", "")),
        )
        return ""


async def _aggregate_orchestration_usage(start_dt: Any) -> dict[str, Any]:
    """best-effort 聚合本次编排驱动窗口内的模型用量（WR-03）。

    编排 adapters（research / architect_merge 等）经 ``arecord_llm_usage(run=None, call_source
    =...)`` 落用量行——挂在各自 call_source 维度但**不挂 MCP run**。为避免 MCP run 维度 token/
    成本归因回退，按 ``created_at`` 窗口聚合本次驱动内 ``run`` 未绑定的用量行，回传 view 落到
    MCP run（call_source 维度记录仍在原行保留，不重复 / 不互相复制）。

    最小窗口聚合（``created_at >= start_dt`` 且 ``run__isnull``）：观测 best-effort，写库异常 /
    无用量恒返回 ``{}``，绝不反噬主流程。
    """
    try:
        from django.db.models import Sum

        from interactions.models import ModelUsageRecord

        agg = await ModelUsageRecord.objects.filter(
            run__isnull=True, created_at__gte=start_dt
        ).aaggregate(
            prompt=Sum("prompt_tokens"),
            completion=Sum("completion_tokens"),
            total=Sum("total_tokens"),
            duration=Sum("duration_ms"),
        )
    except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬业务
        return {}
    prompt = int(agg.get("prompt") or 0)
    completion = int(agg.get("completion") or 0)
    total = int(agg.get("total") or 0)
    if prompt <= 0 and completion <= 0 and total <= 0:
        return {}
    return {
        "provider": "process_runtime",
        "model": "aggregate",
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total or (prompt + completion),
        "duration_ms": int(agg.get("duration") or 0),
    }


async def _amaybe_start_blueprint_session(
    *,
    requirement_text: str,
    work_item: Any,
    created_by: Any,
    include_repos: list[str] | None,
    extra_evidence: list[dict] | None,
    work_item_context: Any,
    assumptions_tier: str = "",
    project_id: str = "",
) -> Any:
    """``mcp`` 开关切到蓝图时建 ``technical_blueprint`` 会话；否则返回 ``None`` 走旧链。

    ⭐ **``entrypoint`` 实参一字不改**仍是 ``"workflow"``（本模块 ``:4`` / ``:131`` 逐字写明
    的既有约定，且它进 ``ConvergenceSession.entrypoint`` 列、有既有消费方）；静态身份走
    ``entry_key="mcp"``。两者是两回事，⛔ 绝不互相代入。

    ⭐ **``project_id`` 必过 ``aresolve_project_id``**（P-8）：⛔ 绝不把
    ``work_item_context.space_id`` 当 project id 透传。推不出即抛 ``BlueprintIntakeRejected``
    并**在建会话之前**中止（⛔ 不建 session、不建 artifact），由调用方映射成失败 delegate 结果。

    ⛔ **不透传 ``skip_clarification``**：蓝图链没有 ``clarify`` dep；旧链那条
    「MCP 单次同步入口跳过交互澄清」的 policy 在蓝图链无对应面，移植它等于原地复活
    GATE-01 要消灭的「跳过澄清」。

    ``assumptions_tier``（116-REVIEW MJ-02）：调用方指定的 assumptions 档位，原样透传给
    ``start_blueprint_orchestration``（它按「非空且在三档内才写键」落进 ``stage_state``）。
    ⭐ 档位只调「问不问的阈值与轮数」，⛔ **绝不跳过 spec_gate stage** —— 那与上一条同源。
    """
    from services.process_runtime.blueprint_entry_switch import aresolve_entry_process_type
    from services.process_runtime.blueprint_intake import aresolve_project_id
    from services.process_runtime.entrypoint import start_blueprint_orchestration

    if await aresolve_entry_process_type("mcp") != "technical_blueprint":
        return None

    project_id = await aresolve_project_id(
        entry="mcp",
        feature_meta={"project_id": project_id} if project_id else None,
        work_item_context=work_item_context,
    )
    return await start_blueprint_orchestration(
        entrypoint="workflow",
        requirement_text=requirement_text,
        work_item=work_item,
        created_by=created_by,
        include_repos=include_repos,
        extra_evidence=extra_evidence,
        project_id=project_id,
        entry_key="mcp",
        assumptions_tier=assumptions_tier,
    )


async def delegate_process_runtime(
    *,
    requirement_text: str,
    work_item: Any = None,
    include_repos: list[str] | None = None,
    created_by: Any = None,
    extra_evidence: list[dict] | None = None,
    work_item_context: Any = None,
    assumptions_tier: str = "",
    project_id: str = "",
) -> DelegateResult:
    """delegate 到 ``process_runtime`` 统一编排，产 canonical MergedPlan/PlanVersion。

    流程（仅调共享 helper，绝不在 MCP 层重写编排）：
    ``start_orchestration(entrypoint="workflow")`` → ``build_orchestration_engine(
    skip_clarification=True)`` → ``adrive_convergence_session_to_pause_or_terminal`` → 终态/挂起映射。

    ``extra_evidence``（UNIFY-02）：调用方补充的编排输入证据（如 repository analysis
    summary），原样透传 ``start_orchestration`` 写入 stage_state，merge 阶段消费。

    ``work_item_context``（116-03，**纯追加、缺省 None**）：``McpWorkItemContext``。仅在
    ``mcp`` 开关切到 ``technical_blueprint`` 时被读，用来推导 ``meta.project_id``。
    ⭐ **``McpWorkItemContext.space`` 是 ``projects.Space`` FK 不是 Project id**（P-8）：
    ``technical_plan_service.py:488`` 把 ``space_id`` 当 ``"project_id"`` 键回给调用方，直接
    透传即落一份「20 个端点恒不可用、图谱恒不入、导出恒不可用」且**没有补救入口**的蓝图。
    故推导一律经 ``blueprint_intake.aresolve_project_id``（内部过 ``_aresolve_project``），
    ⛔ 本模块绝不自己把 ``context.space_id`` 当 project id 用。
    ⚠️ 调用方接线（``technical_plan_service`` / ``views``）与 MCP 响应体追加三键归 **116-06**。

    ``assumptions_tier``（116-REVIEW MJ-02，**纯追加、缺省空串**）：本次会话的 assumptions
    档位。⭐ **仅在 ``mcp`` 开关切到 ``technical_blueprint`` 时被读**（旧链无此维度）；
    空串 / 非三档之一一律回落默认档 ⇒ 不传时行为与改动前逐字相同。

    终态/挂起映射（mirror ``plan_research._map_terminal``）：
    - ``DONE`` → ``status="completed"``，取 ``PlanVersion.content`` + 渲染 markdown。
    - ``RESEARCHING``/``CLARIFYING``（仍挂起，MCP 无 resume 通路）→ ``status="partial"``，
      best-effort 当前 canonical content（通常 {}）+ ``session`` 供续推。
    - ``FAILED`` → ``status="failed"``，content={}。
    """
    from django.utils import timezone

    from delivery.models import ConvergenceSessionStatus
    from services.process_runtime import start_orchestration
    from services.process_runtime.blueprint_intake import BlueprintIntakeRejected
    from services.process_runtime.entrypoint import build_engine_for_session

    started_at = time.perf_counter()
    start_dt = timezone.now()
    try:
        logger.info(
            "mcp_plan_delegate_started",
            category="caller",
            component="mcp_tools",
            include_repo_count=len(include_repos or []),
            extra_evidence_count=len(extra_evidence or []),
        )
    except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬业务
        pass

    # IN-03：delegate 外层异常护栏——start_orchestration（create_session/DB）、PlanSession.aget、
    # _load_canonical 的 PlanVersion 查询、advance 中 NotImplementedError re-raise 等仍可抛穿。
    # 与工作流引擎「异常 → failed 终态」对称：把未预期异常映射为 failed DelegateResult（best-effort
    # 埋 mcp_plan_delegate_failed），杜绝 MCP 入口 5xx 回退。
    session: Any = None
    try:
        # 116-03：按 per-entry 运行时开关分派。⛔ 开关实参必须是**字面量常量** "mcp" ——
        # ⛔ 绝不写 session.entrypoint / 本模块传给 start_orchestration 的 "workflow"
        # （见 :4 / :131 docstring：那是既有约定），反推会让打开 workflow 键把 MCP 一起切走。
        # 蓝图分支在此建会话，旧链分支保持 None ⇒ 下面那次 start_orchestration 逐字不变地执行。
        session = await _amaybe_start_blueprint_session(
            requirement_text=requirement_text,
            work_item=work_item,
            created_by=created_by,
            include_repos=include_repos,
            extra_evidence=extra_evidence,
            work_item_context=work_item_context,
            assumptions_tier=assumptions_tier,
            project_id=project_id,
        )
        session = session or await start_orchestration(
            entrypoint="workflow",
            requirement_text=requirement_text,
            work_item=work_item,
            created_by=created_by,
            include_repos=include_repos,
            extra_evidence=extra_evidence,
            entry_key="mcp",
        )
        # ⭐ 116-03：engine 与 driver 一起经分派器按 session.process_type 取。
        # skip_clarification 照原样传给分派器（它只在旧链分支透传给 build_orchestration_engine；
        # 蓝图链没有 clarify dep，分派器会丢弃并落一条 blueprint_engine_ignored_legacy_flag）
        # ⇒ 旧链行为逐字不变，蓝图分支自动免疫。⛔ 不在本调用点判 process_type。
        #
        # ⛔ 首驱不入队（116 收尾评估结论，31u）：本入口是同步契约——调用方
        # （technical_plan_service / MCP views）在同一次调用内消费
        # DelegateResult(completed/partial/failed) 与 content/markdown/model_usage，
        # partial 的既定语义即「MCP 无 resume 通路」；首驱改 defer 会让所有响应退化为
        # 无 content 的 partial，等价于破坏同步契约。蓝图链的容错由确认门动作链
        # （aresume_after_gate_action）与恢复扫描（arecover_stalled_blueprint_sessions）
        # 承担，本入口保持内联驱动。
        engine, adrive = build_engine_for_session(session, skip_clarification=True)
        session = await adrive(engine, session)

        model_usage = await _aggregate_orchestration_usage(start_dt)
        if session.status == ConvergenceSessionStatus.DONE:
            pv_id, content, markdown = await _load_canonical(session)
            result = DelegateResult(
                session=session,
                status="completed",
                content=content,
                plan_version_id=pv_id,
                markdown=markdown,
                model_usage=model_usage,
            )
        elif session.status == ConvergenceSessionStatus.FAILED:
            result = DelegateResult(
                session=session,
                status="failed",
                content={},
                plan_version_id=None,
                markdown="",
                model_usage=model_usage,
            )
        else:
            # RESEARCHING / CLARIFYING 仍挂起（容器在途 / MCP 无 resume 通路）→ partial best-effort。
            pv_id, content, markdown = await _load_canonical(session)
            result = DelegateResult(
                session=session,
                status="partial",
                content=content,
                plan_version_id=pv_id,
                markdown=markdown,
                model_usage=model_usage,
            )
    except BlueprintIntakeRejected as exc:
        # ⭐ 推不出 meta.project_id ⇒ **拒绝发起**（此刻 ⛔ 会话与 artifact 都尚未建立）。
        # 回中性 detail：⛔ 不含内部路径 / 异常原文。⚠️ 这是**业务失败**，如实回 failed ——
        # ⛔ 绝不吞成「空方案的 200」（Phase 115 MJ-04：best-effort 只适用于观测）。
        try:
            logger.warning(
                "mcp_plan_delegate_blueprint_rejected",
                category="caller",
                component="mcp_tools",
                reason=exc.reason,
            )
        except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬业务
            pass
        result = DelegateResult(
            session=SimpleNamespace(id=""),
            status="failed",
            content={},
            plan_version_id=None,
            markdown="",
            model_usage={},
            error_detail=exc.detail,
        )
    except Exception as exc:  # noqa: BLE001 — 异常 → failed 终态对称护栏（IN-03）
        try:
            logger.warning(
                "mcp_plan_delegate_failed",
                category="caller",
                component="mcp_tools",
                error=str(exc),
            )
        except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬业务
            pass
        # session 可能未建/未达终态：回退 best-effort 用量 + 空 id session 占位（调用方 str(.id) 安全）。
        model_usage = await _aggregate_orchestration_usage(start_dt)
        result = DelegateResult(
            session=session if session is not None else SimpleNamespace(id=""),
            status="failed",
            content={},
            plan_version_id=None,
            markdown="",
            model_usage=model_usage,
        )

    try:
        duration_ms = max(int((time.perf_counter() - started_at) * 1000), 0)
        logger.info(
            "mcp_plan_delegate_completed",
            category="caller",
            component="mcp_tools",
            duration_ms=duration_ms,
            status=result.status,
            session_id=str(getattr(result.session, "id", "")),
        )
    except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬业务
        pass

    return result


def map_canonical_to_coding_plan(
    *,
    content: dict[str, Any],
    repository: Repository,
    branch: str,
    requirement: str,
) -> dict[str, Any]:
    """canonical §7 MergedPlan content → 旧单仓 coding plan payload（UNIFY-04，外形兼容）。

    单仓约束（``include_repos=[repository_id]``，Open Q2 决议）下编排只跑该仓，从 canonical
    ``execution_plan`` 中**筛该 repository_id 的 task**（取首个匹配；无匹配回退首项；空则最小
    结构），**显式映射回旧字段**（T-94-04-INFO：绝不透传 content 内部键，他仓 task 不进单仓
    响应）：

    - ``affected_files`` ← 该 task ``files[].path``（缺则空 list）。
    - ``steps`` ← ``coding_instruction`` 拆解为最小步骤结构（缺则空 list）。
    - ``test_plan`` ← canonical 无 per-task 测试字段，best-effort 空 list（缺则空 list）。
    - ``risks`` ← content ``risks`` / ``compat_risks``（best-effort）。
    - ``title`` ← content ``title`` 或 ``repository.name``。

    缺字段填空不抛（半可信 LLM 产物防御）；附带保留 ``repository_id`` / ``repository_name`` /
    ``branch`` / ``requirement`` 旧键以维持响应外形。
    """
    repo_id = str(repository.id)
    raw_plan = content.get("execution_plan") if isinstance(content, dict) else None
    execution_plan: list[Any] = raw_plan if isinstance(raw_plan, list) else []

    task: dict[str, Any] = {}
    for item in execution_plan:
        if isinstance(item, dict) and str(item.get("repository_id") or "") == repo_id:
            task = item
            break
    if not task and execution_plan and isinstance(execution_plan[0], dict):
        # 单仓约束下编排理应仅产该仓 task；无精确匹配时 best-effort 取首项（防御性）。
        task = execution_plan[0]

    raw_files = task.get("files")
    files = raw_files if isinstance(raw_files, list) else []
    affected_files = [
        str(f.get("path") or "") for f in files if isinstance(f, dict) and f.get("path")
    ]

    coding_instruction = str(task.get("coding_instruction") or "")
    task_name = str(task.get("name") or task.get("description") or "")
    steps: list[dict[str, Any]] = []
    if coding_instruction or task_name:
        steps.append(
            {
                "order": 1,
                "title": task_name or "实现编码指令",
                "detail": coding_instruction or task_name,
                "files": affected_files,
            }
        )

    risks_raw = content.get("risks") if isinstance(content, dict) else None
    if not isinstance(risks_raw, list) or not risks_raw:
        risks_raw = content.get("compat_risks") if isinstance(content, dict) else None
    risks = [str(item) for item in risks_raw] if isinstance(risks_raw, list) else []

    title = (
        str(content.get("title") or "") if isinstance(content, dict) else ""
    ) or repository.name

    return {
        "title": title,
        "repository_id": repo_id,
        "repository_name": repository.name,
        "branch": branch,
        "requirement": requirement,
        "affected_files": affected_files,
        "steps": steps,
        "test_plan": [],
        "risks": risks,
    }
