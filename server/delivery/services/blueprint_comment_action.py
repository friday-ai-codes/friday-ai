"""选区评论的 service 收口（Phase 115-01，CLAR-01 后半句）。

**INV-6**：视图零 ORM 写——线程与首条消息的落库都在本模块经
``BlueprintLifecycleService.open_thread`` 完成（全仓唯一合法开线程入口）；
``delivery.api.blueprint_doc_views`` 只做入参校验、状态闸与 ``status`` → HTTP 状态码映射。

⭐ **与 ``blueprint_review_action._aopen_reject_comment`` 的关键语义差异**：那一支是**驳回
的副作用**（best-effort，开不出线程也返空串、绝不反噬已落库的驳回）；本函数是**主动作**
⇒ ``open_thread`` 抛异常必须如实回错（``status="invalid"`` + 脱敏截断的 ``detail``），
⛔ **绝不吞**——吞了用户会看到「评论成功」而侧栏永远不出现那条评论。

线程形态：``kind=human_comment``、``blocking=False``、``severity=""`` ⇒ 评论不受 114-01 的
finding 不变式约束（``blocking == (severity == blocker)`` 只管审查发现）、也不会把蓝图钉死
——**评论不该阻塞确认**。``created_on_version`` 取当前最新版本，它回答「这条评论是针对哪
一版提的」。本函数**不改蓝图状态**，``current_status`` 只是原样回传供前端对齐「以响应体
``current_status`` 为准」的纪律。

观测：一条 ``caller`` 事件只记 ``artifact_id`` / ``thread_id`` / ``body_len`` /
``has_anchor`` / ``duration_ms`` 等标量——**评论正文与 ``anchor.quoted_text`` 都绝不进
日志**（T-114-36）；异常文本一律过 :func:`_detail`（``redact_secrets_in_text`` + 截断）。
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from common.logging import redact_secrets_in_text
from delivery.models import BlueprintStatus, ThreadKind
from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService

logger = structlog.get_logger(__name__)

__all__ = ["aopen_selection_comment"]

_COMPONENT = "blueprint_comment_action"
_MAX_DETAIL_CHARS = 500

# 空正文错因（与端点侧前置校验的文案同一句，避免同一条件出现两种回显）
_EMPTY_BODY_DETAIL = "评论内容不可为空"


# ---------------------------------------------------------------------------
# 内部 helper（体例照 blueprint_review_action:131-162）
# ---------------------------------------------------------------------------


def _user_id(user: Any, fallback: str = "system") -> str:
    uid = str(getattr(user, "id", "") or "")
    return uid or (str(fallback or "") or "system")


def _detail(text: Any) -> str:
    """异常/错因文本 → 可回显的脱敏截断串。"""
    return redact_secrets_in_text(str(text or ""))[:_MAX_DETAIL_CHARS]


def _current_status(artifact: Any) -> str:
    """**只读**取当前蓝图状态，供返回体呈现。

    返回键刻意叫 ``current_status`` 而非模型字段名（口径同
    ``blueprint_review_action._current_status``）：INV-6 的字段级守卫把「模型字段名 + 等号 /
    字典键 / ``setattr``」三种形态一律判为旁路写——那三条正则正是为了逮住绕过 CAS 的写法。
    本模块只读该字段、从不写它，但拿字段名当返回键会在纯读场景下触发那道**正确**的守卫。
    换个键名，守卫保持满弦、本模块也无需豁免。
    """
    return str(getattr(artifact, "blueprint_status", "") or "")


async def _alatest_version(artifact: Any) -> Any:
    """读最新版本作评论的归属版本（⛔ 绝不读 ``session.current_artifact_version``——它可能
    落后于人工编辑/回灌刚落的版本，拿它会让评论挂到旧版本上）。"""
    from delivery.models import ArtifactVersion

    return (
        await ArtifactVersion.objects.filter(artifact_id=artifact.id)
        .order_by("-version_no")
        .afirst()
    )


# ---------------------------------------------------------------------------
# 唯一公开入口
# ---------------------------------------------------------------------------


async def aopen_selection_comment(
    artifact: Any,
    *,
    body: str,
    anchor: Any = None,
    user: Any = None,
    initiated_by_user_id: str = "system",
    lifecycle_service: Any = None,
) -> dict:
    """按选区开一条 ``human_comment`` 线程。恒定四键
    ``{status, thread_id, detail, current_status}``。

    ``status`` 两态：

    - ``created``：线程与首条消息已同事务落库，``thread_id`` 非空；
    - ``invalid``：正文空（**不落库**）或 ``open_thread`` 抛异常（如非法 ``anchor`` 形状 /
      DB 异常），``detail`` 是脱敏截断后的错因，端点映射 **400**。

    ``anchor`` 非 dict 一律归一 ``None``（= 全局/段级评论，模型允许 ``anchor`` 为空）。
    """
    started = time.monotonic()
    lifecycle = lifecycle_service or BlueprintLifecycleService()
    initiated = _user_id(user, initiated_by_user_id)
    result = {
        "status": "",
        "thread_id": "",
        "detail": "",
        "current_status": _current_status(artifact),
    }

    text = str(body or "").strip()
    if not text:
        result["status"] = "invalid"
        result["detail"] = _EMPTY_BODY_DETAIL
        return result

    version = await _alatest_version(artifact)
    try:
        thread = await lifecycle.open_thread(
            artifact,
            kind=ThreadKind.HUMAN_COMMENT,
            blocking=False,
            severity="",
            question=text,
            anchor=anchor if isinstance(anchor, dict) else None,
            created_on_version=version,
            initiated_by_user_id=initiated,
            return_stage=BlueprintStatus.DRAFTING,
        )
    except Exception as exc:  # noqa: BLE001 — 主动作：如实回错，⛔ 绝不吞成「评论成功」
        logger.warning(
            "blueprint_selection_comment_failed",
            category="caller",
            component=_COMPONENT,
            artifact_id=str(getattr(artifact, "id", "") or ""),
            initiated_by_user_id=initiated,
            body_len=len(text),
            has_anchor=isinstance(anchor, dict),
            error=_detail(exc),
        )
        result["status"] = "invalid"
        result["detail"] = _detail(exc)
        return result

    result["status"] = "created"
    result["thread_id"] = str(getattr(thread, "id", "") or "")
    logger.info(
        "blueprint_selection_comment_created",
        category="caller",
        component=_COMPONENT,
        artifact_id=str(getattr(artifact, "id", "") or ""),
        thread_id=result["thread_id"],
        initiated_by_user_id=initiated,
        # ⛔ 评论正文与 anchor.quoted_text 都不进日志，只记长度与是否带锚点
        body_len=len(text),
        has_anchor=isinstance(anchor, dict),
        duration_ms=round((time.monotonic() - started) * 1000, 2),
    )
    return result
