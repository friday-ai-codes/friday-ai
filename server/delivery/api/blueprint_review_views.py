"""阶段 4 人审操作面 REST（Phase 114-05，FLOW-07 / CLAR-03 / CLAR-04）。

七个端点（``IsAuthenticated``，与 delivery/repositories 既有 view 同级——「项目成员皆可
确认/评论/编辑」的低门槛决策），一动作一 View、不发明 ``action`` 分派：

- ``GET  artifacts/<uuid>/blueprint-review/``                        —— 只读快照
- ``POST artifacts/<uuid>/blueprint-review/approve/``                —— 通过 → confirmed
- ``POST artifacts/<uuid>/blueprint-review/reject/``                 —— 驳回 → drafting
- ``POST artifacts/<uuid>/blueprint-review/edit-blocks/``            —— 直接改 block
- ``POST artifacts/<uuid>/blueprint-review/threads/<uuid>/answer/``  —— 回答澄清 + 回灌
- ``POST artifacts/<uuid>/blueprint-review/threads/<uuid>/resolve/`` —— finding 已修复
- ``POST artifacts/<uuid>/blueprint-review/threads/<uuid>/dismiss/`` —— finding 误报忽略

**为什么新建文件而不塞进 ``blueprint_gate_views.py``**：后者已有八个 View 与确认门专属
helper，再塞语义不同的 View 会让「阶段 1 确认门」这个文件同时承担两个门的语义。URL 前缀
也刻意区分——``blueprint-gate/`` = 阶段 1 仓库确认门，``blueprint-review/`` = 阶段 4 人审。

写入纪律（INV-6）：**视图零 ORM 写**——通过/驳回/finding 处置委托
``delivery.services.blueprint_review_action``，block 编辑委托 114-04 的
``aapply_block_edit``，作答与回灌委托 ``BlueprintLifecycleService.record_answer`` +
114-04 的澄清答案回灌入口；读路径允许视图直查，``.data`` 一律 ``sync_to_async``。

⭐ **approve 绝不在事务外补「未决 BLOCKER」二次查询**：两条守卫判据已由 114-01 收敛进
``_apply_transition_sync`` 的同一 ``transaction.atomic()`` 单次 ``Q`` 查询。视图再查一次
就是重新打开 TOCTOU 窗口（查完到 CAS 之间新开的阻塞线程会被漏挡）。本文件只按 service
返回的 ``status`` 映射状态码；``aunresolved_blocker_count`` **仅用于呈现**（GET 快照与
409 响应体的未决清单），**绝不作为前置判据**。

⭐ **``record_answer`` 只属于 answer 端点**（人类回答澄清线程是它的正当用法）。finding
处置一律走 ``aresolve_finding`` / ``adismiss_finding`` → ``resolve_thread``：作答通道只把
线程推到 ``answered``，而 ``answered`` 仍在 confirm 守卫判据里，**用它处置根本解不开
超界死锁**，还会留下「看着已回答其实仍阻塞」的假象。
⛔ 因此 answer 端点**按 ``kind`` 分流**：``ai_review_finding`` 一律 400（114-CR-01）——
本端点在作答之后同一请求内接了回灌，而回灌链落版本成功后会无条件 ``resolve_thread``，
不分流就等于开了一条「回一句话即处置 BLOCKER」的后门（无 ``reason``、无
``[已修复]``/``[误报忽略]`` 语义、无处置人留痕）。回灌链侧的 ``REFLOW_KINDS`` 是同一条
不变式的第二道闸（fail-closed，不依赖调用方自觉）。

**续驱接线**：六个改状态/改线程的端点在动作**持久化成功之后**调
``blueprint_resume.aresume_after_gate_action``——端点只落库不推进 stage，没有这一步
pause 判据的变化不会被消费。失败隔离在 helper 内（自带 ``try/except`` 全兜）：视图
**不重复包 try**、也**不因续驱结果改响应码**。``GET`` 只读快照**不接续驱**，也
⛔ **不在此触发提醒**——GET 是伪挂载点（没人来看就没有请求，提醒永不触发），提醒的
真实挂载点是既有 apscheduler 的 ``remind_blueprint_clarifications`` job。

观测：每端点一条 ``caller`` 结构化事件（``component="blueprint_review_api"``，含
``artifact_id`` / ``status`` / ``duration_ms`` / ``initiated_by_user_id`` 等标量）。
**评论正文、block 正文、答案正文、处置理由正文一律不进日志**（T-114-36）。
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

logger = structlog.get_logger(__name__)

_COMPONENT = "blueprint_review_api"

# 中性 404 文案（照 112：不泄露资源存在性——未授权者不该靠状态码枚举出哪些 id 存在）
_ARTIFACT_MISSING_DETAIL = {"detail": "artifact 不存在"}
_SESSION_MISSING_DETAIL = {"detail": "该 artifact 没有蓝图编排会话"}
_THREAD_MISSING_DETAIL = {"detail": "线程不存在"}
# 审查发现不走作答通道（114-CR-01）：作答链会经回灌把线程推到 resolved 终态，
# 那等于让 AI 的一句「答案已回灌」冒充人的裁决。
_FINDING_NOT_ANSWERABLE_DETAIL = (
    "审查发现不可通过作答通道处置，请走 resolve/（已修复）或 dismiss/（误报忽略）并填写理由"
)

# service `status` → 中文 detail（键对齐 blueprint_review_action 与 114-04 的取值）
_ACTION_ERROR_MESSAGES = {
    "blocked": "存在未解决的阻塞澄清线程或未决 BLOCKER 审查发现，蓝图不可确认",
    "conflict": "蓝图状态已被其它操作并发推进，请刷新后重试",
    "invalid": "请求不合法或蓝图当前状态不允许该操作",
    "rejected": "部分编辑操作不合法，未落版本",
}

_MAX_UNRESOLVED_IDS = 50


# ── 只读装配 helper（视图零 ORM 写；读路径允许直查）──────────────────────────


async def _aload_artifact(artifact_id: Any) -> Any:
    from delivery.models import Artifact

    return await Artifact.objects.filter(id=artifact_id).afirst()


async def _aload_session(artifact_id: Any) -> Any:
    """按 artifact 反查其**蓝图**编排会话（取最近一条）。

    ``process_type="technical_blueprint"`` 过滤**不可省**：蓝图链刻意复用
    ``technical_plan`` 这个 ``artifact_type``，同一 artifact 上完全可能同时挂着
    ``technical_plan`` 与 ``technical_blueprint`` 两条会话。不带此条件时「最近一条」
    可能是旧链会话，随后被蓝图 engine 驱动 → 旧链 handler 取不到对应 deps → engine
    把那条无关会话落 FAILED，而 REST 仍回 2xx（**静默跨 process 污染**，112 已发生
    过一次的 CRITICAL）。
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


async def _aload_thread(artifact_id: Any, thread_id: Any) -> Any:
    """线程必须**属于该 artifact**（URL 里的 artifact 约束操作范围）。

    不加 ``artifact_id`` 约束时，任意登录用户可用任意合法 artifact_id + 别人的
    thread_id 去处置/回答不属于该蓝图的线程。查不到一律中性 404。
    """
    from delivery.models import BlueprintThread

    return await (
        BlueprintThread.objects.filter(id=thread_id, artifact_id=artifact_id)
        .select_related("artifact")
        .afirst()
    )


async def _acurrent_status(artifact_id: Any) -> str:
    """**续驱之后**重读蓝图状态（响应体绝不与 DB 打架）。

    service 返回的 ``current_status`` 是它自己那一刻的取值，而端点在其后还要跑续驱——
    ``blueprint_resume._amap_blueprint_status`` 会据「仍有 open+blocking 线程」把状态推成
    ``needs_clarification``。直接回传 service 那个值会让前端拿到 ``drafting``、刷新一下
    变 ``needs_clarification``（114-MJ-01 第二点）。**只读**，不写。
    """
    from delivery.models import Artifact

    return str(
        await Artifact.objects.filter(id=artifact_id)
        .values_list("blueprint_status", flat=True)
        .afirst()
        or ""
    )


async def _alatest_content(artifact: Any) -> dict:
    from delivery.models import ArtifactVersion

    content = await (
        ArtifactVersion.objects.filter(artifact_id=artifact.id)
        .order_by("-version_no")
        .values_list("content", flat=True)
        .afirst()
    )
    return content if isinstance(content, dict) else {}


def _thread_row(thread: Any) -> dict:
    """线程 → 快照条目。**带 ``thread_id``**：前端据此直接调处置/作答端点。"""
    return {
        "thread_id": str(thread.id),
        "kind": str(thread.kind or ""),
        "severity": str(thread.severity or ""),
        "status": str(thread.status or ""),
        "blocking": bool(thread.blocking),
        "anchor_status": str(thread.anchor_status or ""),
        "anchor": thread.anchor if isinstance(thread.anchor, dict) else None,
        "return_stage": str(thread.return_stage or ""),
        "created_at": thread.created_at.isoformat() if thread.created_at else "",
    }


@sync_to_async
def _load_thread_rows(artifact_id: Any) -> list[dict]:
    from delivery.models import BlueprintThread

    return [
        _thread_row(row)
        for row in BlueprintThread.objects.filter(artifact_id=artifact_id).order_by("created_at")
    ]


async def _aunresolved_blocker_ids(artifact_id: Any) -> list[str]:
    """未决 BLOCKER finding 的 thread_id 清单（**仅供呈现**）。

    approve 409 时回给前端，好让人知道「该去处置哪几条」——那正是死锁的解药入口。
    ⛔ 绝不作为 approve 的前置判据（判据在 ``_apply_transition_sync`` 事务内）。
    """
    from delivery.models import BlueprintThread, ThreadKind, ThreadSeverity, ThreadStatus

    return [
        str(tid)
        async for tid in BlueprintThread.objects.filter(
            artifact_id=artifact_id,
            kind=ThreadKind.AI_REVIEW_FINDING,
            severity=ThreadSeverity.BLOCKER,
            status__in=[ThreadStatus.OPEN, ThreadStatus.ANSWERED],
        )
        .order_by("created_at")
        .values_list("id", flat=True)[:_MAX_UNRESOLVED_IDS]
    ]


def _log(event: str, request: Any, artifact_id: Any, started: float, **fields: Any) -> None:
    """端点级 caller 事件（只记标量与关联键；**任何用户正文都不进来**）。"""
    logger.info(
        event,
        category="caller",
        component=_COMPONENT,
        artifact_id=str(artifact_id),
        initiated_by_user_id=str(getattr(request.user, "id", "") or "system"),
        duration_ms=round((time.monotonic() - started) * 1000, 2),
        **fields,
    )


async def _aresume(session: Any, request: Any) -> None:
    """动作**持久化成功之后**的续驱。

    失败隔离已在 ``aresume_after_gate_action`` 内（整段 try/except 全兜）——视图
    **不重复包 try**、**不因续驱失败改响应码**：动作已落库，续驱失败只落 caller 事件，
    下一次任意动作或容器回调续驱时判据仍成立，不丢事。
    """
    if session is None:
        return
    from services.process_runtime import blueprint_resume

    await blueprint_resume.aresume_after_gate_action(
        session, initiated_by_user_id=str(getattr(request.user, "id", "") or "system")
    )


def _error(action_status: str, detail: str = "", **extra: Any) -> Response:
    """service ``status`` → 状态码分层（``conflict`` / ``blocked`` → 409，其余 400）。"""
    code = (
        status.HTTP_409_CONFLICT
        if action_status in ("blocked", "conflict")
        else status.HTTP_400_BAD_REQUEST
    )
    body = {"detail": detail or _ACTION_ERROR_MESSAGES.get(action_status, "请求不合法")}
    body.update(extra)
    return Response(body, status=code)


async def _aload_action_context(artifact_id: Any) -> tuple[Any, Any, Any]:
    """``(error_response | None, artifact, session)``。

    拿不到蓝图会话**不**直接 404：驳回/编辑/处置这些动作本身只依赖 artifact，会话缺失
    只意味着「没得续驱」。唯一必需的是 artifact 存在。
    """
    artifact = await _aload_artifact(artifact_id)
    if artifact is None:
        return Response(_ARTIFACT_MISSING_DETAIL, status=status.HTTP_404_NOT_FOUND), None, None
    return None, artifact, await _aload_session(artifact_id)


# ── 1. 只读快照（不接续驱、不触发提醒）──────────────────────────────────────


class BlueprintReviewSnapshotView(APIView):
    """GET .../blueprint-review/ —— 人审只读快照。

    含：findings 线程按 ``severity`` 分组（每条带 ``thread_id``）、澄清线程、
    **失锚列表**（``anchor_status == "orphaned"``，CLAR-02 明令批注不得静默消失）、
    ``stage_state["ai_review"]`` 的未决清单、未决 BLOCKER 计数与 id 清单（呈现用）、
    ``meta.revision_round``。

    **不接续驱**（只读端点不改状态，续驱必为 no-op）；⛔ **不在此触发提醒**——GET 是
    伪挂载点，提醒挂在既有 apscheduler 的 job 上。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request: Any, artifact_id: Any) -> Response:
        from delivery.models import ThreadAnchorStatus, ThreadKind
        from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService

        started = time.monotonic()
        artifact = await _aload_artifact(artifact_id)
        if artifact is None:
            return Response(_ARTIFACT_MISSING_DETAIL, status=status.HTTP_404_NOT_FOUND)

        session = await _aload_session(artifact_id)
        rows = await _load_thread_rows(artifact_id)
        content = await _alatest_content(artifact)
        meta = content.get("meta") if isinstance(content.get("meta"), dict) else {}
        stage_state = getattr(session, "stage_state", None) or {}
        bucket = stage_state.get("ai_review") if isinstance(stage_state, dict) else None

        findings: dict[str, list[dict]] = {"blocker": [], "warning": [], "info": []}
        for row in rows:
            if row["kind"] == ThreadKind.AI_REVIEW_FINDING:
                findings.setdefault(row["severity"] or "info", []).append(row)

        payload = {
            "artifact_id": str(artifact.id),
            "session_id": str(getattr(session, "id", "") or ""),
            "current_status": str(getattr(artifact, "blueprint_status", "") or ""),
            "revision_round": int(meta.get("revision_round") or 0)
            if isinstance(meta.get("revision_round"), int)
            else 0,
            "findings": findings,
            "clarifications": [row for row in rows if row["kind"] == ThreadKind.AI_CLARIFICATION],
            "comments": [row for row in rows if row["kind"] == ThreadKind.HUMAN_COMMENT],
            "orphaned_threads": [
                row for row in rows if row["anchor_status"] == ThreadAnchorStatus.ORPHANED
            ],
            "unresolved": list((bucket or {}).get("unresolved") or [])
            if isinstance(bucket, dict)
            else [],
            "review_round": int((bucket or {}).get("round") or 0)
            if isinstance(bucket, dict)
            else 0,
            "unresolved_blocker_count": await BlueprintLifecycleService().aunresolved_blocker_count(
                artifact
            ),
            "unresolved_blocker_thread_ids": await _aunresolved_blocker_ids(artifact_id),
        }
        _log(
            "blueprint_review_snapshot_read",
            request,
            artifact_id,
            started,
            thread_count=len(rows),
            orphaned_count=len(payload["orphaned_threads"]),
        )
        return Response(payload)


# ── 2. approve（守卫在事务内；视图零预查询）──────────────────────────────────


class BlueprintReviewApproveView(APIView):
    """POST .../blueprint-review/approve/ —— 人审通过 → ``confirmed``。

    ⭐ **零 TOCTOU**：不做任何「先查未决 BLOCKER 再 transition」的事务外预查询——
    两条守卫判据已由 114-01 收敛进 ``_apply_transition_sync`` 的单一事务单次 ``Q``。
    本视图只调 service 并按 ``status`` 映射状态码。

    ``blocked``（守卫拒绝/非法边）与 ``conflict``（CAS 冲突）都是 **409**，且 ``blocked``
    的响应体带上未决 BLOCKER 的 ``thread_id`` 清单——那是**处置端点的入口**，没有它
    人审只会看到一句「不可确认」而不知道该去处置什么（超界死锁的体验面）。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request: Any, artifact_id: Any) -> Response:
        from delivery.services.blueprint_review_action import aapprove_blueprint

        started = time.monotonic()
        error, artifact, session = await _aload_action_context(artifact_id)
        if error is not None:
            return error

        result = await aapprove_blueprint(
            artifact,
            user=request.user,
            initiated_by_user_id=str(request.user.id),
            session=session,
        )
        _log(
            "blueprint_review_approve_requested",
            request,
            artifact_id,
            started,
            status=result["status"],
        )
        if result["status"] != "confirmed":
            extra: dict[str, Any] = {}
            if result["status"] == "blocked":
                # 呈现用（非判据）：告诉人审「去处置这几条」——resolve/dismiss 是唯一出口。
                ids = await _aunresolved_blocker_ids(artifact_id)
                extra = {"unresolved_blocker_thread_ids": ids, "unresolved_blocker_count": len(ids)}
            return _error(result["status"], result["detail"], **extra)

        await _aresume(session, request)
        return Response(
            {
                "status": result["status"],
                # 续驱后重读（不用 service 那一刻的快照）：见 `_acurrent_status`
                "current_status": await _acurrent_status(artifact_id),
                "artifact_id": str(artifact_id),
            }
        )


# ── 3. reject（先落版本再转状态）─────────────────────────────────────────────


class BlueprintReviewRejectView(APIView):
    """POST .../blueprint-review/reject/ —— 驳回 → ``drafting`` 且 ``revision_round + 1``。

    入参 ``{comment?, anchor?}``：``comment`` 非空时额外开一条 ``human_comment``
    划线评论线程（``blocking=False`` ⇒ 不会把蓝图钉死）。

    顺序是「**先落版本再转状态**」：反过来会留下「状态已 ``drafting`` 而轮次未加」的
    窗口，AI 在该窗口里拿旧轮次重跑，有界回退计数失真。``conflict``（版本已落、状态
    未转）如实回 409 并带上 ``version_no``，绝不静默。

    ⭐ **驳回的回边由 service 侧的会话复位承担**（``_areopen_session_for_rework``）：
    ``pending_review`` 必由 ``ai_review`` 的两条 ``__done__`` 出边到达 ⇒ 驳回时会话必定
    终态，只接 ``_aresume`` 不复位等于零 advance（114-MJ-01）。``current_status``
    **在续驱之后重读**，不回传 service 那一刻的快照。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request: Any, artifact_id: Any) -> Response:
        from delivery.services.blueprint_review_action import areject_blueprint

        started = time.monotonic()
        error, artifact, session = await _aload_action_context(artifact_id)
        if error is not None:
            return error

        body = request.data if isinstance(request.data, dict) else {}
        anchor = body.get("anchor")
        result = await areject_blueprint(
            artifact,
            user=request.user,
            comment=str(body.get("comment") or ""),
            anchor=anchor if isinstance(anchor, dict) else None,
            initiated_by_user_id=str(request.user.id),
            session=session,
        )
        _log(
            "blueprint_review_reject_requested",
            request,
            artifact_id,
            started,
            status=result["status"],
            version_no=result["version_no"],
        )
        if result["status"] != "rejected":
            return _error(
                result["status"],
                result["detail"],
                version_no=result["version_no"],
                revision_round=result["revision_round"],
            )

        await _aresume(session, request)
        return Response(
            {
                "status": result["status"],
                "version_id": result["version_id"],
                "version_no": result["version_no"],
                "revision_round": result["revision_round"],
                "thread_id": result["thread_id"],
                # 续驱后重读（不用 service 那一刻的快照）：见 `_acurrent_status`
                "current_status": await _acurrent_status(artifact_id),
            }
        )


# ── 4. edit-blocks（委托 114-04）────────────────────────────────────────────


class BlueprintReviewEditBlocksView(APIView):
    """POST .../blueprint-review/edit-blocks/ —— 人工直接改 block（CLAR-03）。

    入参 ``{ops: [...]}``（``replace`` / ``insert`` / ``delete`` 三 op）；``ops`` 非 list
    → 400。委托 114-04 的 ``aapply_block_edit``：``rejected`` 与 ``invalid`` 都 **400 且
    版本数不变**（半合法内容绝不落版本），``unchanged`` 是 200（同 content_hash 不翻版本，
    重放安全）。成功版本 ``produced_by_ref == "human_edit:{user_id}"``，编辑者进
    ``BlueprintReviewer``——这两条是 ``human_edit_volume`` 统计与审计归属的唯一依据。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request: Any, artifact_id: Any) -> Response:
        from delivery.services.blueprint_block_edit import aapply_block_edit

        started = time.monotonic()
        error, artifact, session = await _aload_action_context(artifact_id)
        if error is not None:
            return error

        body = request.data if isinstance(request.data, dict) else {}
        ops = body.get("ops")
        if not isinstance(ops, list):
            return Response({"detail": "ops 必须是列表"}, status=status.HTTP_400_BAD_REQUEST)

        result = await aapply_block_edit(
            artifact,
            ops,
            user=request.user,
            initiated_by_user_id=str(request.user.id),
            session_id=str(getattr(session, "id", "") or ""),
        )
        _log(
            "blueprint_review_block_edit_requested",
            request,
            artifact_id,
            started,
            status=result["status"],
            op_count=len(ops),
            rejected_count=len(result.get("rejected") or []),
        )
        if result["status"] in ("rejected", "invalid"):
            return _error(
                result["status"], result.get("detail") or "", rejected=result.get("rejected") or []
            )

        await _aresume(session, request)
        return Response(
            {
                "status": result["status"],
                "version_id": result["version_id"],
                "version_no": result["version_no"],
                "rejected": result.get("rejected") or [],
                "reanchor": result.get("reanchor") or {},
            }
        )


# ── 5. threads answer（⭐ 作答通道的唯一正当用法 + B1 回灌接线）───────────────


class BlueprintReviewThreadAnswerView(APIView):
    """POST .../blueprint-review/threads/<uuid>/answer/ —— 人类回答澄清线程。

    ⭐ **这里才是 ``record_answer`` 的正当用法**（人类作答本就该把 ``open`` 推到
    ``answered``）。作答之后**同一请求内**调 114-04 的 ``aapply_thread_answers`` 消费
    答案产新版本（``section_writer`` 不传 ⇒ 走生产实现）——没有这一步，答案只会停在
    线程里、蓝图正文永不更新，SC-2/SC-3 成孤儿。

    ⚠️ **回灌失败绝不回滚、绝不改响应码**：``record_answer`` 已持久化，端点必须 2xx；
    回灌结果原样放进响应体的 ``reflow`` 键（含 ``status``），失败/冲突**如实上报**，
    绝不静默。

    ⛔ **``kind == ai_review_finding`` 一律 400**（114-CR-01）：本端点在 ``record_answer``
    之后**同一请求内**接了回灌，而回灌链落版本成功后会对被消费线程无条件
    ``resolve_thread`` ⇒ 在一条 BLOCKER finding 上回一句任意文本就把它推到终态、解开
    confirm 门，同时绕开 ``reason`` 必填 / ``[已修复]``-``[误报忽略]`` 的语义区分 /
    「处置人：{uid}」的归因留痕。finding 只能走 resolve / dismiss。分流在此与回灌链
    的 ``REFLOW_KINDS`` **双重堵**：端点给可回显的中文错因，回灌链自身 fail-closed。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request: Any, artifact_id: Any, thread_id: Any) -> Response:
        from delivery.models import ThreadAuthorType, ThreadKind
        from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService
        from services.process_runtime.blueprint_reflow import aapply_thread_answers

        started = time.monotonic()
        error, artifact, session = await _aload_action_context(artifact_id)
        if error is not None:
            return error
        thread = await _aload_thread(artifact_id, thread_id)
        if thread is None:
            return Response(_THREAD_MISSING_DETAIL, status=status.HTTP_404_NOT_FOUND)
        if str(getattr(thread, "kind", "") or "") == ThreadKind.AI_REVIEW_FINDING:
            return Response(
                {"detail": _FINDING_NOT_ANSWERABLE_DETAIL},
                status=status.HTTP_400_BAD_REQUEST,
            )

        body = request.data if isinstance(request.data, dict) else {}
        answer = str(body.get("body") or "").strip()
        if not answer:
            return Response({"detail": "回答内容不可为空"}, status=status.HTTP_400_BAD_REQUEST)

        lifecycle = BlueprintLifecycleService()
        await lifecycle.record_answer(
            thread,
            body=answer,
            author=request.user,
            author_type=ThreadAuthorType.HUMAN,
            initiated_by_user_id=str(request.user.id),
        )
        try:
            reflow = await aapply_thread_answers(
                artifact,
                threads=[thread],
                session=session,
                initiated_by_user_id=str(request.user.id),
            )
        except Exception as exc:  # noqa: BLE001 — 作答已持久化：回灌异常不回滚、不回 5xx
            from common.logging import redact_secrets_in_text

            logger.warning(
                "blueprint_review_answer_reflow_failed",
                category="caller",
                component=_COMPONENT,
                artifact_id=str(artifact_id),
                thread_id=str(thread_id),
                initiated_by_user_id=str(request.user.id),
                error=redact_secrets_in_text(str(exc)),
            )
            reflow = {"status": "failed", "detail": "回灌执行异常，答案已保存"}

        await lifecycle.add_reviewer(artifact, request.user, "thread_answer")
        _log(
            "blueprint_review_thread_answered",
            request,
            artifact_id,
            started,
            thread_id=str(thread_id),
            reflow_status=str(reflow.get("status") or ""),
        )
        await _aresume(session, request)
        return Response(
            {
                "status": "answered",
                "thread_id": str(thread_id),
                "reflow": {
                    "status": str(reflow.get("status") or ""),
                    "version_id": str(reflow.get("version_id") or ""),
                    "version_no": int(reflow.get("version_no") or 0),
                    "conflict_block_ids": list(reflow.get("conflict_block_ids") or []),
                    "thread_id": str(reflow.get("thread_id") or ""),
                    "detail": str(reflow.get("detail") or ""),
                },
            }
        )


# ── 6-7. ⭐ finding 处置（B2：超界死锁的唯一正向出口）────────────────────────


async def _adispose_view(request: Any, artifact_id: Any, thread_id: Any, *, dismissed: bool):
    """resolve / dismiss 两个 View 的共用体（一动作一 View，仅实现复用）。

    ``reason`` 空 → 400 且不落库；线程不属该 artifact / 不存在 → 中性 404；
    ``kind`` 非 ``ai_review_finding`` → 400（该通道只处置审查发现）；已终态 → 200
    ``noop`` 且**不覆盖首次结论**。

    处置成功后接续驱：处置清掉了阻塞线程，pause 判据随之变化，需要推一把。
    """
    from delivery.services.blueprint_review_action import adismiss_finding, aresolve_finding

    started = time.monotonic()
    error, artifact, session = await _aload_action_context(artifact_id)
    if error is not None:
        return error
    thread = await _aload_thread(artifact_id, thread_id)
    if thread is None:
        return Response(_THREAD_MISSING_DETAIL, status=status.HTTP_404_NOT_FOUND)

    body = request.data if isinstance(request.data, dict) else {}
    dispose = adismiss_finding if dismissed else aresolve_finding
    result = await dispose(
        thread,
        reason=str(body.get("reason") or ""),
        user=request.user,
        initiated_by_user_id=str(request.user.id),
    )
    _log(
        "blueprint_review_finding_disposed",
        request,
        artifact_id,
        started,
        thread_id=str(thread_id),
        action="dismiss" if dismissed else "resolve",
        status=result["status"],
    )
    if result["status"] == "invalid":
        return _error("invalid", result["detail"])

    await _aresume(session, request)
    return Response({"status": result["status"], "thread_id": result["thread_id"]})


class BlueprintReviewFindingResolveView(APIView):
    """POST .../blueprint-review/threads/<uuid>/resolve/ —— finding 采纳并标记已修复。

    ⭐ **B2 死锁出口**。114-03 轮次用尽后蓝图落 ``pending_review`` 并留下未决 BLOCKER
    finding，而 114-01 的 confirm 守卫把 ``status ∈ {open, answered}`` 的 blocker finding
    一律判为「不可确认」⇒ 人审只能驳回、永远无法通过。本端点经 ``resolve_thread`` 把
    线程推到 ``resolved`` 终态，离开守卫判据集合 ⇒ 全部未决清空后 approve 放行。

    ⛔ **不用作答通道**：它只推到 ``answered``，仍在判据里，解不开锁。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request: Any, artifact_id: Any, thread_id: Any) -> Response:
        return await _adispose_view(request, artifact_id, thread_id, dismissed=False)


class BlueprintReviewFindingDismissView(APIView):
    """POST .../blueprint-review/threads/<uuid>/dismiss/ —— finding 判为误报忽略。

    与 resolve 同一条死锁出口，语义不同：``dismissed`` = 人工裁定 AI 的审查结论**不
    成立**（规则误报、章程已授权等）。同样是终态，同样离开 confirm 守卫判据集合。
    理由必填并写进结论文本——无理由的处置在审计上等于凭空放行。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request: Any, artifact_id: Any, thread_id: Any) -> Response:
        return await _adispose_view(request, artifact_id, thread_id, dismissed=True)
