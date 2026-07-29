"""阶段 1 出口确认门 REST（Phase 112-05，FLOW-03 / FLOW-04 / CHARTER-03）。

八个端点（``IsAuthenticated``，与 delivery/repositories 既有 view 同级——§6.4「项目成员
皆可确认」的低门槛决策），一动作一 View、不发明 action 分派：

- ``GET  artifacts/<uuid>/blueprint-gate/``                   —— 只读快照
- ``POST artifacts/<uuid>/blueprint-gate/confirm/``           —— 确认锁定
- ``POST artifacts/<uuid>/blueprint-gate/remove-repo/``       —— 移除仓
- ``POST artifacts/<uuid>/blueprint-gate/add-repo/``          —— 手动加仓（触发新仓调研）
- ``POST artifacts/<uuid>/blueprint-gate/reclassify-role/``   —— 改判 direct/indirect
- ``POST artifacts/<uuid>/blueprint-gate/edit-responsibility/`` —— 修改职责
- ``POST artifacts/<uuid>/blueprint-gate/rejected-to-boundary/`` —— rejected 一键沉淀
- ``POST artifacts/<uuid>/blueprint-gate/upgrade-research/``  —— indirect 升级深调研

写入纪律（INV-6）：**视图零 ORM 写**——五动作与升级深调研全部委托
``BlueprintLifecycleService``，锁定委托 ``BlueprintConfirmGateAdapter.alock``，章程草案
委托 ``charter_draft_writeback.asubmit_charter_draft``；读路径允许视图直查。serializer
``.data`` 一律 ``sync_to_async`` 包裹。action 白名单/角色枚举归一在 service 层，视图只
透传并把错误码映射成状态码。

**续驱接线（SC-4 的生产调用方）**：六个**改状态**的动作端点在动作持久化成功之后
（``confirm`` 在 ``alock`` 之后）调 ``blueprint_resume`` 的动作侧续驱入口——
动作端点只落库不推进 stage，没有这一步 ``research_required`` 回边永远不会被触发。
失败隔离在 helper 内（自带 ``try/except`` 全兜）：视图**不重复包 try**、也**不因续驱
结果改响应码**——动作已持久化，续驱失败只落 caller 事件，标记留待下次触发。
只读快照 ``GET`` 与 ``rejected-to-boundary`` **不接续驱**：前者不改状态，后者只写章程
草案（不碰 ``stage_state`` / 线程 / task 状态），续驱必为 no-op。
"""

from __future__ import annotations

from typing import Any

import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

logger = structlog.get_logger(__name__)

# 错误码 → 中文中性消息（码由 BlueprintLifecycleService 抛出，视图只做映射）
_GATE_ERROR_MESSAGES = {
    "unknown_action": "不支持的确认门动作",
    "missing_repository_id": "缺少 repository_id",
    "invalid_role": "role 只能是 direct 或 indirect",
    "empty_snapshot": "确认门快照为空，无可确认的仓库",
    "repository_not_found": "仓库不存在",
    "repository_not_in_snapshot": "该仓库不在确认门快照内",
    "gate_not_open": "确认门未开启",
}
_GATE_NOT_OPEN_DETAIL = {"detail": "确认门未开启"}
_ARTIFACT_MISSING_DETAIL = {"detail": "artifact 不存在"}
_SESSION_MISSING_DETAIL = {"detail": "该 artifact 没有蓝图编排会话"}

# alock 拒绝落锁的 409 文案（码由 blueprint_confirm_gate 给，视图只做映射）
_LOCK_DEFAULT = "蓝图内容校验未通过，确认未生效"
_LOCK_BLOCKED_MESSAGES = {
    "pending_research": "有仓库正在调研，暂不能确认，请等待调研完成后重试",
    "snapshot_changed": "确认门快照已被其它操作更新，请刷新后重新确认",
}

_MAX_BOUNDARY_RULE_CHARS = 500


# ── 只读装配 helper（视图零 ORM 写；读路径允许直查）──────────────────────────


async def _aload_artifact(artifact_id: Any) -> Any:
    from delivery.models import Artifact

    return await Artifact.objects.filter(id=artifact_id).afirst()


async def _aload_session(artifact_id: Any) -> Any:
    """按 artifact 反查其**蓝图**编排会话（取最近一条；续驱与 task 写入都需要它）。

    ``process_type`` 过滤不可省：蓝图链刻意复用 ``technical_plan`` 这个 ``artifact_type``
    （见 ``builtin_processes`` 第三次注册），同一 artifact 上完全可能同时挂着
    ``technical_plan`` 与 ``technical_blueprint`` 两条会话。不带此条件时「最近一条」可能是
    旧链会话，随后被蓝图 engine 驱动 → 旧链 handler 取不到 ``deps.router`` → engine 把那条
    无关会话落 FAILED，而 REST 仍回 2xx（静默污染）。
    """
    from delivery.models import ConvergenceSession
    from services.process_runtime.blueprint_resume import BLUEPRINT_PROCESS_TYPE

    return await (
        ConvergenceSession.objects.filter(
            current_artifact_version__artifact_id=artifact_id,
            process_type=BLUEPRINT_PROCESS_TYPE,
        )
        .order_by("-created_at")
        .afirst()
    )


async def _aload_gate_context(artifact_id: Any) -> tuple[Any, Any, Any]:
    """``(artifact, session, thread)``；缺失位为 ``None``（调用方分层回 404）。"""
    from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService

    artifact = await _aload_artifact(artifact_id)
    if artifact is None:
        return None, None, None
    session = await _aload_session(artifact_id)
    thread = await BlueprintLifecycleService().aload_gate_thread(artifact)
    return artifact, session, thread


async def _aserialize_snapshot(artifact: Any, session: Any, thread: Any) -> dict:
    from delivery.api.artifact_serializers import BlueprintGateSnapshotSerializer
    from services.process_runtime.blueprint_confirm_gate import (
        acollect_pending_research_repos,
        iter_snapshot_repos,
    )

    repos = iter_snapshot_repos(getattr(thread, "options", None))
    pending = await acollect_pending_research_repos(session) if session is not None else []
    payload = {
        "artifact_id": str(getattr(artifact, "id", "")),
        "session_id": str(getattr(session, "id", "") or ""),
        "thread_id": str(getattr(thread, "id", "") or ""),
        "thread_status": str(getattr(thread, "status", "") or ""),
        "current_stage": str(getattr(session, "current_stage", "") or ""),
        "repo_count": len(repos),
        "pending_research_repository_ids": pending,
        "repos": repos,
    }
    return await sync_to_async(lambda: BlueprintGateSnapshotSerializer(payload).data)()


async def _aserialize_action(payload: dict) -> dict:
    from delivery.api.artifact_serializers import BlueprintGateActionResultSerializer

    return await sync_to_async(lambda: BlueprintGateActionResultSerializer(payload).data)()


def _action_payload(action: str, result: dict, **extra: Any) -> dict:
    return {
        "action": action,
        "repository_id": result.get("repository_id") or "",
        "thread_id": result.get("thread_id") or "",
        "requires_research": bool(result.get("requires_research")),
        "ready_to_lock": bool(result.get("ready_to_lock")),
        "locked": bool(extra.get("locked")),
        "upgraded": bool(extra.get("upgraded")),
        "locked_repo_count": int(extra.get("locked_repo_count") or 0),
    }


def _gate_error_response(exc: ValueError) -> Response:
    """service 错误码 → 状态码分层（不存在类 404，其余入参类 400）。"""
    from delivery.services.blueprint_lifecycle_service import GATE_NOT_FOUND_ERRORS

    code = str(exc.args[0]) if exc.args else ""
    detail = _GATE_ERROR_MESSAGES.get(code, "请求参数不合法")
    if code in GATE_NOT_FOUND_ERRORS:
        return Response({"detail": detail}, status=status.HTTP_404_NOT_FOUND)
    return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)


async def _aapply_action(request: Any, artifact_id: Any, action: str) -> tuple[Any, dict, Any]:
    """四个「改快照」动作的共用前置：装配上下文 → 委托 service → 归一错误。

    Returns:
        ``(error_response | None, result, session)``——``error_response`` 非 None 时
        调用方直接返回它（视图仍各自负责续驱接线与响应组装）。
    """
    from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService

    artifact, session, thread = await _aload_gate_context(artifact_id)
    if artifact is None:
        return Response(_ARTIFACT_MISSING_DETAIL, status=status.HTTP_404_NOT_FOUND), {}, None
    if thread is None:
        return Response(_GATE_NOT_OPEN_DETAIL, status=status.HTTP_404_NOT_FOUND), {}, None
    if session is None:
        # 拿不到蓝图会话就明确 404——绝不退化成「取别的 process 的会话」继续动作与续驱。
        return Response(_SESSION_MISSING_DETAIL, status=status.HTTP_404_NOT_FOUND), {}, None
    body = request.data if isinstance(request.data, dict) else {}
    try:
        result = await BlueprintLifecycleService().apply_gate_action(
            artifact,
            thread=thread,
            action=action,
            payload=body,
            acting_user=request.user,
            initiated_by_user_id=str(request.user.id),
            session=session,
        )
    except ValueError as exc:
        return _gate_error_response(exc), {}, session
    return None, result, session


# ── 1. 只读快照（不接续驱：不改状态）───────────────────────────────────────


class BlueprintGateSnapshotView(APIView):
    """GET artifacts/<uuid:artifact_id>/blueprint-gate/ —— 确认门只读快照。

    无门 → 404 中性消息（``{"detail": "确认门未开启"}"``）。**不接续驱**：只读端点
    不改任何状态，续驱必为 no-op。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request: Any, artifact_id: Any) -> Response:
        artifact, session, thread = await _aload_gate_context(artifact_id)
        if artifact is None:
            return Response(_ARTIFACT_MISSING_DETAIL, status=status.HTTP_404_NOT_FOUND)
        if thread is None:
            return Response(_GATE_NOT_OPEN_DETAIL, status=status.HTTP_404_NOT_FOUND)
        return Response(await _aserialize_snapshot(artifact, session, thread))


# ── 2. confirm（续驱在 alock 之后）─────────────────────────────────────────


class BlueprintGateConfirmView(APIView):
    """POST .../blueprint-gate/confirm/ —— 确认锁定仓库集与职责。

    前置校验经 ``apply_gate_action(action="confirm")``；通过后由
    ``BlueprintConfirmGateAdapter.alock`` 落蓝图新版本（``confirmed_at_gate`` /
    ``decided_by=human`` / ``responsibility`` + ``decision_log``）并把确认者
    upsert 进 ``BlueprintReviewer``。存在未决阻塞澄清线程 → 409；蓝图内容校验
    未过（fail-closed，不落 failed）→ 409。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request: Any, artifact_id: Any) -> Response:
        from services.process_runtime import blueprint_resume
        from services.process_runtime.blueprint_confirm_gate import BlueprintConfirmGateAdapter

        error, result, session = await _aapply_action(request, artifact_id, "confirm")
        if error is not None:
            return error
        if result.get("blocked_reason") == "pending_clarification":
            return Response({"detail": "存在未解决的阻塞澄清线程"}, status=status.HTTP_409_CONFLICT)
        if session is None:
            return Response(_GATE_NOT_OPEN_DETAIL, status=status.HTTP_404_NOT_FOUND)

        lock = await BlueprintConfirmGateAdapter().alock(session, acting_user=request.user)
        if lock.get("event") != "confirmed":
            # fail-closed：内容非法 / 并发未收敛时不放行、不落 failed，等下一次重试。
            return Response(
                {
                    "detail": _LOCK_BLOCKED_MESSAGES.get(
                        str(lock.get("reason") or ""), _LOCK_DEFAULT
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )
        await blueprint_resume.aresume_after_gate_action(
            session, initiated_by_user_id=str(request.user.id)
        )
        return Response(
            await _aserialize_action(
                _action_payload(
                    "confirm", result, locked=True, locked_repo_count=lock.get("repo_count") or 0
                )
            )
        )


# ── 3-6. 四个改快照动作（各自接续驱）───────────────────────────────────────


class BlueprintGateRemoveRepoView(APIView):
    """POST .../blueprint-gate/remove-repo/ —— 移除仓（**不**触发重调研）。

    只收窄仓库集，既有调研结论不失效；被移除仓不进锁定后的 ``repo_associations``，
    其移除理由产 ``boundaries`` 草案。续驱在无待调研仓时于 pause 短路处零 advance。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request: Any, artifact_id: Any) -> Response:
        from services.process_runtime import blueprint_resume

        error, result, session = await _aapply_action(request, artifact_id, "remove_repo")
        if error is not None:
            return error
        await blueprint_resume.aresume_after_gate_action(
            session, initiated_by_user_id=str(request.user.id)
        )
        return Response(await _aserialize_action(_action_payload("remove_repo", result)))


class BlueprintGateAddRepoView(APIView):
    """POST .../blueprint-gate/add-repo/ —— 手动补仓（**触发新仓调研**）。

    service 侧同时打 ``pending_research`` 标记并把该仓 ``RepoResearchTask`` 建成
    ``PENDING``；容器由续驱经 ``_h_bp_repo_research`` 增量派发——**起容器 ≠ 等容器**，
    视图绝不等待容器完成、不读容器结果。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request: Any, artifact_id: Any) -> Response:
        from services.process_runtime import blueprint_resume

        error, result, session = await _aapply_action(request, artifact_id, "add_repo")
        if error is not None:
            return error
        await blueprint_resume.aresume_after_gate_action(
            session, initiated_by_user_id=str(request.user.id)
        )
        return Response(await _aserialize_action(_action_payload("add_repo", result)))


class BlueprintGateReclassifyRoleView(APIView):
    """POST .../blueprint-gate/reclassify-role/ —— 改判 direct/indirect。

    仅 ``indirect → direct`` 触发重调研（深调研结论是轻量合成的超集）；反向与同角色
    改判不触发。非法 role → 400。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request: Any, artifact_id: Any) -> Response:
        from services.process_runtime import blueprint_resume

        error, result, session = await _aapply_action(request, artifact_id, "reclassify_role")
        if error is not None:
            return error
        await blueprint_resume.aresume_after_gate_action(
            session, initiated_by_user_id=str(request.user.id)
        )
        return Response(await _aserialize_action(_action_payload("reclassify_role", result)))


class BlueprintGateEditResponsibilityView(APIView):
    """POST .../blueprint-gate/edit-responsibility/ —— 修改职责。

    职责文本变化是否改变调研范围无法机械判定 → 默认**不**重调研；只有调用方显式
    传 ``{"rerun": true}``（用户在 UI 勾选「重新调研该仓」）才触发。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request: Any, artifact_id: Any) -> Response:
        from services.process_runtime import blueprint_resume

        error, result, session = await _aapply_action(request, artifact_id, "edit_responsibility")
        if error is not None:
            return error
        await blueprint_resume.aresume_after_gate_action(
            session, initiated_by_user_id=str(request.user.id)
        )
        return Response(await _aserialize_action(_action_payload("edit_responsibility", result)))


# ── 7. rejected 一键沉淀（不接续驱：只写章程草案）────────────────────────────


class BlueprintRejectedToBoundaryView(APIView):
    """POST .../blueprint-gate/rejected-to-boundary/ —— rejected 候选一键沉淀为禁区候选。

    读 ``RepoAssociation.status == rejected`` 的候选（读路径），把其 ``routed_reason``
    组装成 ``boundaries`` 草案后经 ``charter_draft_writeback.asubmit_charter_draft``
    落 ``source=ai_draft``（对 ``human_confirmed`` 章程只写 ``draft_content``）。

    项目范围：body 的 ``project_id`` 优先，缺省取蓝图 ``meta.project_id``；两者都不是
    合法 UUID 时须显式给 ``repository_id``，否则 400（绝不跨项目全表沉淀）。
    全部草案写入失败 → 503（依赖不可用）。

    **不接续驱**：本端点不碰 ``stage_state`` / 线程 / task 状态，续驱必为 no-op。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request: Any, artifact_id: Any) -> Response:
        from repositories.services.charter_draft_writeback import asubmit_charter_draft

        artifact = await _aload_artifact(artifact_id)
        if artifact is None:
            return Response(_ARTIFACT_MISSING_DETAIL, status=status.HTTP_404_NOT_FOUND)
        body = request.data if isinstance(request.data, dict) else {}
        project_id = str(body.get("project_id") or "").strip() or await _ablueprint_project_id(
            artifact
        )
        repository_id = str(body.get("repository_id") or "").strip()
        if not _is_uuid(project_id) and not repository_id:
            return Response(
                {"detail": "无法确定项目范围：请提供 project_id 或 repository_id"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        grouped = await _aload_rejected_reasons(project_id, repository_id)
        if not grouped:
            return Response({"candidate_count": 0, "draft_count": 0, "repository_count": 0})

        drafted = 0
        for rid, reasons in grouped.items():
            charter = await asubmit_charter_draft(
                rid,
                {"boundaries": [_boundary_entry(reason) for reason in reasons]},
                initiated_by_user_id=str(request.user.id),
            )
            if charter is not None:
                drafted += 1
        candidate_count = sum(len(reasons) for reasons in grouped.values())
        if drafted == 0:
            return Response(
                {"detail": "章程草案写入暂不可用，请稍后重试"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        logger.info(
            "blueprint_rejected_to_boundary_submitted",
            category="caller",
            component="blueprint_gate_api",
            artifact_id=str(artifact_id),
            candidate_count=candidate_count,
            repository_count=len(grouped),
            draft_count=drafted,
            initiated_by_user_id=str(request.user.id),
        )
        return Response(
            {
                "candidate_count": candidate_count,
                "draft_count": drafted,
                "repository_count": len(grouped),
            }
        )


# ── 8. upgrade-research（接续驱：与 add_repo 同一条增量派发链）────────────────


class BlueprintGateUpgradeResearchView(APIView):
    """POST .../blueprint-gate/upgrade-research/ —— indirect 候选升级为深调研（FLOW-04）。

    经 ``BlueprintLifecycleService.aupgrade_repo_research`` 收口（快照标
    ``pending_research`` + ``role_suggestion="direct"`` → 留痕 → emit → 调 112-04 的
    ``aupgrade_to_deep``）。缺 ``repository_id`` → 400；仓不在快照内 / 门未开 → 404；
    ``aupgrade_to_deep`` 返 ``False``（依赖不可用）→ 503。**视图零 ORM 写、不等容器**。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request: Any, artifact_id: Any) -> Response:
        from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService
        from services.process_runtime import blueprint_resume

        artifact, session, thread = await _aload_gate_context(artifact_id)
        if artifact is None:
            return Response(_ARTIFACT_MISSING_DETAIL, status=status.HTTP_404_NOT_FOUND)
        if thread is None:
            return Response(_GATE_NOT_OPEN_DETAIL, status=status.HTTP_404_NOT_FOUND)
        if session is None:
            return Response(_SESSION_MISSING_DETAIL, status=status.HTTP_404_NOT_FOUND)
        body = request.data if isinstance(request.data, dict) else {}
        try:
            result = await BlueprintLifecycleService().aupgrade_repo_research(
                artifact,
                repository_id=str(body.get("repository_id") or ""),
                acting_user=request.user,
                initiated_by_user_id=str(request.user.id),
                session=session,
            )
        except ValueError as exc:
            return _gate_error_response(exc)
        await blueprint_resume.aresume_after_gate_action(
            session, initiated_by_user_id=str(request.user.id)
        )
        if not result.get("upgraded"):
            return Response(
                {"detail": "升级深调研暂不可用：调研依赖不可用或该仓无可派发任务"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(
            await _aserialize_action(
                _action_payload(
                    "upgrade_research",
                    {
                        "repository_id": result.get("repository_id"),
                        "thread_id": str(getattr(thread, "id", "")),
                        "requires_research": True,
                    },
                    upgraded=True,
                )
            )
        )


# ── 只读装配（rejected 沉淀专用）─────────────────────────────────────────────


def _is_uuid(value: str) -> bool:
    import uuid as _uuid

    try:
        _uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return False
    return True


async def _ablueprint_project_id(artifact: Any) -> str:
    """从蓝图当前版本 ``meta.project_id`` 取项目范围（读不到返空串）。"""
    from delivery.models import ArtifactVersion

    version_id = getattr(artifact, "current_version_id", None)
    if not version_id:
        return ""
    content = await (
        ArtifactVersion.objects.filter(id=version_id).values_list("content", flat=True).afirst()
    )
    meta = (content or {}).get("meta") if isinstance(content, dict) else None
    return str((meta or {}).get("project_id") or "") if isinstance(meta, dict) else ""


@sync_to_async
def _aload_rejected_reasons(project_id: str, repository_id: str) -> dict[str, list[str]]:
    """按仓聚合 rejected 候选的 ``routed_reason``（只读；范围外一律不查）。"""
    from initiatives.models import RepoAssociation, RepoAssociationStatus

    queryset = RepoAssociation.objects.filter(status=RepoAssociationStatus.REJECTED)
    if repository_id:
        queryset = queryset.filter(repository_id=repository_id)
    if _is_uuid(project_id):
        queryset = queryset.filter(project_id=project_id)
    grouped: dict[str, list[str]] = {}
    try:
        rows = list(queryset.values("repository_id", "routed_reason")[:200])
    except Exception:  # noqa: BLE001 — 非法 uuid 等一律按「无候选」处理
        return {}
    for row in rows:
        grouped.setdefault(str(row["repository_id"]), []).append(str(row["routed_reason"] or ""))
    return grouped


def _boundary_entry(reason: str) -> dict:
    text = str(reason or "").strip()
    rule = f"本类需求不落此仓（关联被判定为 rejected{('：' + text) if text else ''}）"
    return {"rule": rule[:_MAX_BOUNDARY_RULE_CHARS], "decided_by": "human", "citations": []}
