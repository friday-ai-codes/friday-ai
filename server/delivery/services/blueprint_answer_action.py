"""澄清线程作答的 service 收口（Phase 116-06，GATE-01）。

**INV-6**：本模块零 ORM 写——作答消息与线程状态推进一律经
``BlueprintLifecycleService.record_answer``（全仓唯一合法写口），评审人增补经
``add_reviewer``，回灌经 114-04 的 ``aapply_thread_answers``；本模块只做只读装配与
调用序编排。⛔ 本模块**不得**进 ``test_blueprint_inv6_guard._ALLOWED_WRITER``。

⭐ **本模块是作答调用序的唯一实现**。两个调用方共享它：

- ``delivery.api.blueprint_review_views.BlueprintReviewThreadAnswerView``（SPA / REST）；
- ``mcp_tools.views.AnswerBlueprintClarificationView``（MCP 协议面，116-06 新增）。

⛔ **绝不复刻第二份**：三道闸里最要命的那条（``ai_review_finding`` 一律拒）是
114-CR-01 的收口，一旦两份实现漂移就是**安全回归**——回灌链落版本成功后会对被消费
线程无条件 ``resolve_thread``，让 finding 进来即等于「在一条 BLOCKER 上回一句任意
文本」就解开 confirm 门，同时绕开 ``reason`` 必填、``[已修复]``/``[误报忽略]`` 的语义
区分与「处置人：{uid}」的归因留痕。

**三道闸的顺序与各自的理由**（逐字承接
``BlueprintReviewThreadAnswerView`` 类 docstring 的四条纪律）：

1. **范围闸留在调用方**。它需要 ``request``/``token owner`` 这类传输层身份，service
   不吃 ``request``。⇒ ⭐ **调用方必须在调用本函数之前过项目范围闸**
   （REST 走 ``_aassert_project_scope``，MCP 工具 import 复用**同一个**实现）。
2. ⭐ **``is_blueprint_editable(artifact)`` 在 ``record_answer`` 之前**（114-MJ-04）：
   作答会经回灌落新版本，已 ``confirmed`` / ``implementing`` / ``archived`` 的蓝图不该
   被无声改写。闸在写之前 ⇒ 越界时 **DB 一字未动**。
3. ⭐ **``kind == ai_review_finding`` 一律拒**（114-CR-01）：与回灌链自身的
   ``REFLOW_KINDS`` 构成**双重堵**——本闸给可回显的中文错因，回灌链 fail-closed 不
   依赖调用方自觉。finding 只能走 ``resolve`` / ``dismiss``。

⚠️ **回灌失败绝不回滚、绝不改 ``status``**：``record_answer`` 已持久化，作答本身就是
成功的；回灌结果**原样**放进 ``reflow`` 键（含它自己的五档 ``status``），失败如实上报、
⛔ 绝不静默。

观测：一条 ``caller`` 事件只记 ``artifact_id`` / ``thread_id`` / ``body_len`` /
``reflow_status`` / ``initiated_by_user_id`` / ``duration_ms`` 等标量——⛔ **答案正文与
澄清题正文一律不进日志**（T-114-36）；异常文本一律过 :func:`_detail`
（``redact_secrets_in_text`` + 截断）。
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from common.logging import redact_secrets_in_text
from delivery.models import ThreadAuthorType, ThreadKind
from delivery.services.blueprint_lifecycle_service import (
    NOT_EDITABLE_DETAIL,
    BlueprintLifecycleService,
    is_blueprint_editable,
)

logger = structlog.get_logger(__name__)

__all__ = ["aanswer_thread"]

_COMPONENT = "blueprint_answer_action"
_MAX_DETAIL_CHARS = 500

# ⭐ 审查发现不走作答通道的**唯一**文案定义（114-CR-01）。
# ``delivery.api.blueprint_review_views`` 原先在自己模块里定义过一份，116-06 下沉到
# 这里 ⇒ 两个调用方回显同一句话，⛔ 不留两份可漂移的副本。
_FINDING_NOT_ANSWERABLE_DETAIL = (
    "审查发现不可通过作答通道处置，请走 resolve/（已修复）或 dismiss/（误报忽略）并填写理由"
)
# 空正文错因（与既有端点的回显逐字相同，避免同一条件出现两种文案）
_EMPTY_BODY_DETAIL = "回答内容不可为空"
# 回灌整体异常时的兜底 reflow（逐字沿用既有端点的取值）
_REFLOW_FAILED_DETAIL = "回灌执行异常，答案已保存"


# ---------------------------------------------------------------------------
# 内部 helper（体例照 blueprint_comment_action:50-81）
# ---------------------------------------------------------------------------


def _user_id(user: Any, fallback: str = "system") -> str:
    uid = str(getattr(user, "id", "") or "")
    return uid or (str(fallback or "") or "system")


def _detail(text: Any) -> str:
    """异常/错因文本 → 可回显的脱敏截断串。"""
    return redact_secrets_in_text(str(text or ""))[:_MAX_DETAIL_CHARS]


async def _acurrent_status(artifact: Any) -> str:
    """**回灌之后**重读蓝图状态（只读；返回键刻意叫 ``current_status``）。

    ⛔ 返回键不用模型字段名：INV-6 的字段级守卫把「字段名 + 等号 / 字典键 / setattr」
    三种形态一律判为旁路写。本模块只读该字段、从不写它，拿字段名当返回键会在纯读场景
    下触发那道**正确**的守卫（口径同 ``blueprint_comment_action._current_status``）。

    取**回灌之后**的值而不是入口那一刻的快照：114-MJ-01 第二点——service 侧取值发生在
    续驱之前会让调用方拿到「刷新一下就变」的状态。
    """
    from delivery.models import Artifact

    return str(
        await Artifact.objects.filter(id=getattr(artifact, "id", None))
        .values_list("blueprint_status", flat=True)
        .afirst()
        or ""
    )


def _reflow_view(reflow: Any) -> dict:
    """回灌结果 → 恒定六键投影（两个调用方的响应体逐字共享这一份形状）。"""
    data = reflow if isinstance(reflow, dict) else {}
    return {
        "status": str(data.get("status") or ""),
        "version_id": str(data.get("version_id") or ""),
        "version_no": int(data.get("version_no") or 0),
        "conflict_block_ids": list(data.get("conflict_block_ids") or []),
        "thread_id": str(data.get("thread_id") or ""),
        "detail": str(data.get("detail") or ""),
    }


# ---------------------------------------------------------------------------
# 唯一公开入口
# ---------------------------------------------------------------------------


async def aanswer_thread(
    artifact: Any,
    thread: Any,
    *,
    body: str,
    user: Any = None,
    session: Any = None,
    initiated_by_user_id: str = "system",
    lifecycle_service: Any = None,
    section_writer: Any = None,
) -> dict:
    """人类回答一条澄清线程，并在**同一调用内**把答案回灌成新版本。

    ⭐ **调用方必须先过项目范围闸**（见模块 docstring 第 1 条）：本函数只认
    ``artifact`` / ``thread`` 两个已装配好的对象，不做任何身份判定。

    恒定五键返回 ``{status, thread_id, reflow, detail, current_status}``，``status``
    闭集四态（两个调用方各自映射成 HTTP 码 / MCP ``error_response``）：

    ==================  ======================================================
    status              语义
    ==================  ======================================================
    ``answered``        答案已落库；``reflow`` 带回灌五档结果（**回灌失败不改本值**）
    ``not_editable``    蓝图状态不在可编辑白名单 ⇒ **DB 一字未动**
    ``not_answerable``  ``kind == ai_review_finding`` ⇒ **线程状态一字未变**
    ``invalid``         正文 strip 后为空 ⇒ **不落库**
    ==================  ======================================================

    ``section_writer`` 不传 ⇒ 回灌走生产实现（``ablock_section_writer``）；测试要 no-op
    时**显式注入桩**，⛔ 不要靠默认值（T-114-23c）。
    """
    from services.process_runtime.blueprint_reflow import aapply_thread_answers

    started = time.monotonic()
    lifecycle = lifecycle_service or BlueprintLifecycleService()
    initiated = _user_id(user, initiated_by_user_id)
    result = {
        "status": "",
        "thread_id": str(getattr(thread, "id", "") or ""),
        "reflow": _reflow_view(None),
        "detail": "",
        "current_status": "",
    }

    # 闸②：状态闸在**任何写之前**（MJ-04）——越界时 DB 一字未动。
    if not is_blueprint_editable(artifact):
        result["status"] = "not_editable"
        result["detail"] = NOT_EDITABLE_DETAIL
        result["current_status"] = await _acurrent_status(artifact)
        return result

    # 闸③：finding 一律拒（114-CR-01）——同样在写之前，线程状态一字未变。
    if str(getattr(thread, "kind", "") or "") == ThreadKind.AI_REVIEW_FINDING:
        result["status"] = "not_answerable"
        result["detail"] = _FINDING_NOT_ANSWERABLE_DETAIL
        result["current_status"] = await _acurrent_status(artifact)
        return result

    text = str(body or "").strip()
    if not text:
        result["status"] = "invalid"
        result["detail"] = _EMPTY_BODY_DETAIL
        result["current_status"] = await _acurrent_status(artifact)
        return result

    await lifecycle.record_answer(
        thread,
        body=text,
        author=user,
        author_type=ThreadAuthorType.HUMAN,
        initiated_by_user_id=initiated,
    )

    try:
        reflow = await aapply_thread_answers(
            artifact,
            threads=[thread],
            session=session,
            initiated_by_user_id=initiated,
            section_writer=section_writer,
        )
    except Exception as exc:  # noqa: BLE001 — 作答已持久化：回灌异常不回滚、不改 status
        logger.warning(
            "blueprint_answer_reflow_failed",
            category="caller",
            component=_COMPONENT,
            artifact_id=str(getattr(artifact, "id", "") or ""),
            thread_id=result["thread_id"],
            initiated_by_user_id=initiated,
            error=_detail(exc),
        )
        reflow = {"status": "failed", "detail": _REFLOW_FAILED_DETAIL}

    if user is not None:
        await lifecycle.add_reviewer(artifact, user, "thread_answer")

    result["status"] = "answered"
    result["reflow"] = _reflow_view(reflow)
    result["current_status"] = await _acurrent_status(artifact)
    logger.info(
        "blueprint_thread_answer_completed",
        category="caller",
        component=_COMPONENT,
        artifact_id=str(getattr(artifact, "id", "") or ""),
        thread_id=result["thread_id"],
        initiated_by_user_id=initiated,
        # ⛔ 答案正文与澄清题正文都不进日志，只记长度
        body_len=len(text),
        reflow_status=result["reflow"]["status"],
        duration_ms=round((time.monotonic() - started) * 1000, 2),
    )
    return result
