"""蓝图只读供数面 REST（Phase 115-01，VIEW-01 / CLAR-01）。

四个端点（``IsAuthenticated`` **+ 项目范围闸**，见下方 ⭐ 段），一个集合资源两个 HTTP
方法、不发明 ``action`` 分派：

- ``GET  artifacts/<uuid>/blueprint/``                 —— 结构化正文 + quality 四项
- ``GET  artifacts/<uuid>/blueprint/events/``          —— 蓝图阶段事件流（21 个常量子集）
- ``GET  artifacts/<uuid>/blueprint-review/threads/``  —— 线程详情（含 options 与多轮消息）
- ``POST artifacts/<uuid>/blueprint-review/threads/``  —— 按选区新开 ``human_comment`` 线程

⭐ **授权判据不是「登录了」**（114-MJ-03 的对称面）：四端点入口一律过
:func:`delivery.api.blueprint_review_views._aassert_project_scope`——**import 复用同源
实现，绝不复制第三份**。四条语义逐字沿用：superuser 直通 / 读不到蓝图
``meta.project_id`` → **400** fail-closed / 非 ``ProjectMember`` → **中性 404**（不泄露
存在性，403 会让未授权者靠状态码枚举出哪些 artifact 存在）。蓝图正文含项目技术细节，
越权读取即敏感信息泄露——只读面的闸与写动作面同等重要。

**为什么新建文件而不塞进 ``blueprint_review_views.py``**：后者是**人审动作面**（七端点
里六个是写路径 + 一个动作快照），本文件是**只读供数面**（前端渲染用的正文 / 阶段事件 /
线程详情）。职责不同，且把 115 的读面集中在一处便于 116 的入口收编按文件切。既有文件
本 plan **零改动**。

写入纪律（INV-6）：本文件唯一的写路径是 ``POST threads/``，其落库**全部**委托
``delivery.services.blueprint_comment_action``（其唯一写口是
``BlueprintLifecycleService.open_thread``），**View 零 ORM 写**；读路径允许视图直查，
取 FK 对象一律走 ``@sync_to_async`` 私有函数并预取，防 async 裸 lazy-FK。

观测：每端点一条 ``caller`` 结构化事件（``component="blueprint_doc_api"``，含
``artifact_id`` / ``initiated_by_user_id`` / ``duration_ms`` 等标量），**只读 GET 也记**
（``blueprint_review_snapshot_read`` 是先例：谁读过哪份蓝图必须有痕）。
**评论正文、block 正文、答案正文、处置理由正文一律不进日志**（T-114-36）；本文件另加：
线程 ``messages[].body`` 与 citation ``quote`` 同样不进日志，正文类实参只记长度。
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

# ⭐ MJ-03 的四条范围闸语义**只能有一份实现**：提取共享模块要改既有文件（115 对后端同样
# 守「能不改就不改」），复制会产生可漂移的第三份副本 ⇒ 直接 import 私有符号并在此登记。
# ``_ARTIFACT_MISSING_DETAIL`` 一并 import 是硬要求：非成员的中性 404 响应体由闸内产出，
# 本模块「artifact 不存在」的 404 必须与它**逐字相同**，否则存在性仍可被枚举（T-115-02）。
from delivery.api.blueprint_review_views import (
    _ARTIFACT_MISSING_DETAIL,
    _aassert_project_scope,
    _aload_artifact,
    _aload_session,
    _thread_row,
)

logger = structlog.get_logger(__name__)

_COMPONENT = "blueprint_doc_api"

# 中性 404 / 400 文案（口径同 analog：不泄露资源存在性、错因可回显）
_VERSION_MISSING_DETAIL = {"detail": "版本不存在或不属于该 artifact"}
_VERSION_INVALID_DETAIL = {"detail": "version_id 格式无效（需为 UUID）"}
_EMPTY_BODY_DETAIL = {"detail": "评论内容不可为空"}


# ── 只读装配 helper（视图零 ORM 写；读路径允许直查）──────────────────────────


def _is_uuid(value: Any) -> bool:
    import uuid as _uuid

    try:
        _uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return False
    return True


async def _aload_version(artifact_id: Any, version_id: Any = None) -> Any:
    """取正文版本行；``version_id`` 缺省取**最新**一版。

    ⛔ **不读 ``Artifact.current_version``**：基线一律 ``order_by("-version_no").afirst()``
    （STATE 114-04 立的纪律，``_alatest_content`` 是同一口径的既有落点）——``current_version``
    与 ``session.current_artifact_version`` 都可能落后于人工编辑/回灌刚落的版本。

    带 ``version_id`` 时**必须同时约束 ``artifact_id``**：否则任意登录用户可用自己有权限的
    artifact_id 拼别人的 version_id 读到别的项目的正文（范围闸只看 URL 里的 artifact）。
    """
    from delivery.models import ArtifactVersion

    queryset = ArtifactVersion.objects.filter(artifact_id=artifact_id)
    if version_id:
        return await queryset.filter(id=version_id).afirst()
    return await queryset.order_by("-version_no").afirst()


@sync_to_async
def _collect_db_quality(artifact_id: Any) -> dict:
    """三项 DB 统计**一次性**算完（P-15）。

    ``ai_rejection_rate`` / ``human_edit_volume`` / ``clarification_rounds`` 都是**同步
    函数且函数内直接查 ORM**，在 adrf 异步 View 里直调必 ``SynchronousOnlyOperation``；
    而它们各自的 ``except Exception`` 只兜 ORM 异常、**不兜异步上下文错误**（那是在调用点
    抛的）⇒ 不包一层 ``sync_to_async`` 就是稳定 500 而不是被吞成 ``None``。

    ⭐ **``None`` 原样透传**：``None`` = 「没有数据源可算」，``0`` = 「统计到了，值为零」。
    端点侧⛔不再包 try、⛔不把 ``None`` 改写成 0——两者在人审面板是不同文案。
    """
    from services.process_runtime.blueprint_quality import (
        ai_rejection_rate,
        clarification_rounds,
        human_edit_volume,
    )

    key = str(artifact_id)
    return {
        "ai_rejection_rate": ai_rejection_rate(key),
        "human_edit_volume": human_edit_volume(key),
        "clarification_rounds": clarification_rounds(key),
    }


def _option_row(option: Any) -> dict:
    """澄清候选项归一。``options`` 是 ``JSONField(default=list)`` **无 schema 校验**
    （半可信）⇒ 逐键 ``.get`` 防御，非 dict 条目直接丢弃。"""
    return {
        "label": str(option.get("label") or ""),
        "value": str(option.get("value") or ""),
        "note": str(option.get("note") or ""),
    }


def _message_row(message: Any) -> dict:
    """线程消息 → 条目。``author`` 是 ``SET_NULL`` FK（用户被删 / AI 作者）⇒
    ``author_display`` **必须容忍 ``None``**，回落顺序 username → email → 空串。"""
    author = getattr(message, "author", None)
    return {
        "id": str(message.id),
        "author_type": str(message.author_type or ""),
        "author_user_id": str(getattr(author, "id", "") or "") or None,
        "author_display": str(
            getattr(author, "username", "") or getattr(author, "email", "") or ""
        ),
        "body": str(message.body or ""),
        "created_at": message.created_at.isoformat() if message.created_at else "",
    }


def _thread_detail_row(thread: Any) -> dict:
    """线程 → **详情**条目：``_thread_row`` 九键 + ``options`` / ``last_reminded_at`` /
    ``messages[]``。

    形态刻意是**手写 dict builder**（九键直接复用 analog 的同一实现，不重抄一份）：本
    View 家族全域零 DRF 组装层，混进来会让同一响应里出现两套 None/空串归一口径。
    """
    row = _thread_row(thread)
    options = thread.options if isinstance(thread.options, list) else []
    row["options"] = [_option_row(item) for item in options if isinstance(item, dict)]
    row["last_reminded_at"] = (
        thread.last_reminded_at.isoformat() if thread.last_reminded_at else None
    )
    # 已由 Prefetch 预取（见 `_load_thread_details`）⇒ `.all()` 命中缓存，零额外查询
    row["messages"] = [_message_row(message) for message in thread.messages.all()]
    return row


@sync_to_async
def _load_thread_details(artifact_id: Any) -> list[dict]:
    """该 artifact 的全部线程（含消息）。

    ⚠️ ``.order_by("created_at")`` **不可省**：``BlueprintThread.Meta`` 没有 ``ordering``
    （114-MN-01 专为「无 ORDER BY 的窗口」立过纪律，返回顺序由存储层决定、跨引擎不稳定）。
    消息侧 ``Prefetch`` + ``select_related("author")`` 是 N+1 防线：线程 N 条时朴素写法是
    1 + N 次消息查询 + 每条消息一次作者查询。
    """
    from django.db.models import Prefetch

    from delivery.models import BlueprintThread, BlueprintThreadMessage

    messages = Prefetch(
        "messages",
        queryset=BlueprintThreadMessage.objects.select_related("author").order_by("created_at"),
    )
    return [
        _thread_detail_row(thread)
        for thread in BlueprintThread.objects.filter(artifact_id=artifact_id)
        .order_by("created_at")
        .prefetch_related(messages)
    ]


def _event_row(row: Any) -> dict:
    """事件行 → 条目。``payload`` 是自由 ``JSONField``、键由各 emit 点自定 ⇒ **原样透传**
    （非 dict 归一 ``{}``），前端插值时每键各自兜缺省。"""
    return {
        "id": str(row.id),
        "event": str(row.event or ""),
        "payload": row.payload if isinstance(row.payload, dict) else {},
        "ts": row.ts.isoformat() if row.ts else "",
    }


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


# ── 1. 结构化正文 + quality（全相位的供数根）─────────────────────────────────


class BlueprintDocumentView(APIView):
    """GET .../blueprint/ —— 结构化正文（``content`` dict）+ 质量四项。

    可选 ``?version_id=<uuid>``（缺省取最新一版）：非 UUID → **400**；不存在或不属于该
    artifact → **中性 404**。

    ⭐ **返回结构化 ``content`` 而不是 markdown 串**：人审快照不返回 content，
    ``ArtifactTimelineView`` 只给 ``current_version_markdown``（**结构已丢**）⇒ 没有本端点，
    block 锚定与 block 级 diff 在物理上无法实现。

    ``is_current`` 判据是 ``artifact.current_version_id == version.id``，⛔ **不用
    「version_no 最大」二次推断**：并发落版本时两者会短暂不一致，而前端「回到当前版本」
    按钮依赖它。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request: Any, artifact_id: Any) -> Response:
        from services.process_runtime.blueprint_quality import citation_coverage

        started = time.monotonic()
        artifact = await _aload_artifact(artifact_id)
        if artifact is None:
            return Response(_ARTIFACT_MISSING_DETAIL, status=status.HTTP_404_NOT_FOUND)
        denied = await _aassert_project_scope(request, artifact)
        if denied is not None:
            return denied

        version_id = request.query_params.get("version_id") or ""
        if version_id and not _is_uuid(version_id):
            return Response(_VERSION_INVALID_DETAIL, status=status.HTTP_400_BAD_REQUEST)
        version = await _aload_version(artifact_id, version_id or None)
        if version is None:
            return Response(_VERSION_MISSING_DETAIL, status=status.HTTP_404_NOT_FOUND)

        content = version.content if isinstance(version.content, dict) else {}
        # quality 装配段：`citation_coverage` 是同步纯函数（入参 content dict，分母为 0 → 1.0，
        # 恒有值）；后三项经 `_collect_db_quality` 一次性算完并 **原样透传 None**。
        quality: dict[str, Any] = {"citation_coverage": citation_coverage(content)}
        quality.update(await _collect_db_quality(artifact_id))

        is_current = bool(
            artifact.current_version_id and str(artifact.current_version_id) == str(version.id)
        )
        payload = {
            "version_id": str(version.id),
            "version_no": int(getattr(version, "version_no", 0) or 0),
            "is_current": is_current,
            "produced_by_ref": str(getattr(version, "produced_by_ref", "") or ""),
            "created_at": version.created_at.isoformat() if version.created_at else "",
            "content": content,
            "quality": quality,
        }
        _log(
            "blueprint_document_read",
            request,
            artifact_id,
            started,
            version_no=payload["version_no"],
            is_current=is_current,
            # 只记标量：citation 池条目数，⛔ 不记任何正文
            citation_count=len(content.get("citations") or {}),
        )
        return Response(payload)


# ── 2. 阶段事件流（「不新建推送通道」纪律的落地形态）─────────────────────────


class BlueprintEventsView(APIView):
    """GET .../blueprint/events/ —— 蓝图阶段事件流（只读）。

    只出 ``BLUEPRINT_EVENTS`` 这 21 个常量的子集、按 ``ts`` **显式升序**、``payload``
    原样透传。

    ⭐ **无会话回 200 空结构，⛔ 绝不 404**：会话不存在是**正常态**（蓝图还没跑过编排）。
    404 会被前端的 404 分档吞成全页中性空态 ⇒ 生成中的蓝图看起来像「无权限」。

    反查会话一律走既有 ``_aload_session``（**自带 ``process_type`` 过滤**）：同一 artifact
    上可能并存 ``technical_plan`` 与 ``technical_blueprint`` 两条会话，不过滤会吐出旧链
    事件流（112 已发生过一次的 CRITICAL）。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request: Any, artifact_id: Any) -> Response:
        from delivery.models import ConvergenceSessionEvent
        from delivery.services.event_taxonomy import BLUEPRINT_EVENTS

        started = time.monotonic()
        artifact = await _aload_artifact(artifact_id)
        if artifact is None:
            return Response(_ARTIFACT_MISSING_DETAIL, status=status.HTTP_404_NOT_FOUND)
        denied = await _aassert_project_scope(request, artifact)
        if denied is not None:
            return denied

        session = await _aload_session(artifact_id)
        if session is None:
            _log(
                "blueprint_events_read",
                request,
                artifact_id,
                started,
                has_session=False,
                event_count=0,
            )
            return Response({"session_id": "", "current_stage": "", "events": []})

        # `.order_by("ts")` **显式**覆盖 `Meta.ordering = ["created_at"]`：`ts` 允许 emit 端
        # 传入 ⇒ 与 `created_at` 可以不同；显式 order 同时走上 `(session, ts)` 索引。
        events = [
            _event_row(row)
            async for row in ConvergenceSessionEvent.objects.filter(
                session_id=session.id, event__in=sorted(BLUEPRINT_EVENTS)
            ).order_by("ts")
        ]
        payload = {
            "session_id": str(getattr(session, "id", "") or ""),
            "current_stage": str(getattr(session, "current_stage", "") or ""),
            "events": events,
        }
        _log(
            "blueprint_events_read",
            request,
            artifact_id,
            started,
            has_session=True,
            event_count=len(events),
        )
        return Response(payload)


# ── 3-4. 线程详情集合（GET 读多轮 / POST 开选区评论）─────────────────────────


class BlueprintReviewThreadsView(APIView):
    """``GET`` / ``POST`` .../blueprint-review/threads/ —— 线程详情集合。

    **这不违反 112 立的「一动作一 View」**：那条禁的是 ``?action=`` / body 里带 ``action``
    的**动作分派**；``GET``/``POST`` 是同一集合资源的两个 HTTP 方法，是 REST 的标准形态。
    URL 与既有 ``threads/<uuid:thread_id>/<动作>/`` 整段不同，互不遮挡。

    - ``GET``：``_thread_row`` 九键 + ``options`` / ``last_reminded_at`` / ``messages[]``
      —— 快照的九键既无 ``options`` 也无任何消息，多轮回复根本没有数据（CLAR-01 前半句）。
    - ``POST``：全仓**第一个**「按选区主动开 ``human_comment`` 线程」的入口（此前唯一路径
      是 ``reject/`` 的副作用，CLAR-01 后半句）。⛔ **不接续驱**：选区评论是纯留痕，不改
      蓝图状态、不触发 stage 推进。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request: Any, artifact_id: Any) -> Response:
        started = time.monotonic()
        artifact = await _aload_artifact(artifact_id)
        if artifact is None:
            return Response(_ARTIFACT_MISSING_DETAIL, status=status.HTTP_404_NOT_FOUND)
        denied = await _aassert_project_scope(request, artifact)
        if denied is not None:
            return denied

        rows = await _load_thread_details(artifact_id)
        _log(
            "blueprint_threads_read",
            request,
            artifact_id,
            started,
            thread_count=len(rows),
            # 只记计数，⛔ 消息正文不进日志
            message_count=sum(len(row["messages"]) for row in rows),
        )
        return Response({"threads": rows})

    async def post(self, request: Any, artifact_id: Any) -> Response:
        from delivery.services.blueprint_comment_action import aopen_selection_comment
        from delivery.services.blueprint_lifecycle_service import (
            NOT_EDITABLE_DETAIL,
            is_blueprint_editable,
        )

        started = time.monotonic()
        artifact = await _aload_artifact(artifact_id)
        if artifact is None:
            return Response(_ARTIFACT_MISSING_DETAIL, status=status.HTTP_404_NOT_FOUND)
        denied = await _aassert_project_scope(request, artifact)
        if denied is not None:
            return denied
        # 状态闸在**任何写之前**（与 answer / edit-blocks 同一张白名单）：已 confirmed 的蓝图
        # 不该继续挂新评论线程，越界时 DB 一字未动。判据函数与文案常量一律复用，
        # ⛔ 不自造白名单、不自造文案。
        if not is_blueprint_editable(artifact):
            return Response({"detail": NOT_EDITABLE_DETAIL}, status=status.HTTP_400_BAD_REQUEST)

        payload = request.data if isinstance(request.data, dict) else {}
        text = str(payload.get("body") or "").strip()
        if not text:
            return Response(_EMPTY_BODY_DETAIL, status=status.HTTP_400_BAD_REQUEST)
        anchor = payload.get("anchor")
        anchor = anchor if isinstance(anchor, dict) else None

        result = await aopen_selection_comment(
            artifact,
            body=text,
            anchor=anchor,
            user=request.user,
            initiated_by_user_id=str(getattr(request.user, "id", "") or "system"),
        )
        _log(
            "blueprint_thread_created",
            request,
            artifact_id,
            started,
            status=result["status"],
            thread_id=result["thread_id"],
            # ⛔ 正文不进日志，只记长度
            body_len=len(text),
            has_anchor=anchor is not None,
        )
        if result["status"] != "created":
            return Response({"detail": result["detail"]}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {"thread_id": result["thread_id"], "current_status": result["current_status"]}
        )
