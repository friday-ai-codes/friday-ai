"""人审操作的 service 收口（Phase 114-05，FLOW-07 / CLAR-03 / CLAR-04）。

**INV-6**：视图零 ORM 写——通过 / 驳回 / finding 处置 / 澄清提醒的全部落库都在本模块
经 ``BlueprintLifecycleService`` 与 ``ArtifactService`` 完成；``blueprint_review_views``
只做入参校验、``status`` → HTTP 状态码映射与续驱接线。

**通过（approve）不做事务外二次查询**
    「无 open+blocking 线程」+「无未决 BLOCKER 审查发现」两条判据已由 114-01 收敛进
    ``_apply_transition_sync`` 的同一 ``transaction.atomic()``、以**单次 ``Q`` 查询**完成。
    视图或本模块**再查一次就是重新打开 TOCTOU 窗口**（P4）：查完到 CAS 之间新开的阻塞
    线程会被漏挡，带未决 BLOCKER 的蓝图被人审放行。本模块只调 ``transition`` 并把两类
    异常分开上报（``ValueError`` = 守卫/非法边 → ``blocked``；
    ``ConcurrentBlueprintTransitionError`` = CAS 冲突 → ``conflict``）。
    只读呈现口径请用 ``aunresolved_blocker_count``，**它绝不参与判定**。

**驳回（reject）走三步，顺序不可换**
    读 current content → ``meta.revision_round += 1`` → ``add_version`` →
    ``transition("drafting")``。先转状态会留下「状态已 ``drafting`` 而轮次未加」的窗口，
    AI 在该窗口里会拿**旧轮次**重跑，有界回退计数失真。重试前必须**重读 current
    content**（用内存副本会让同 hash 幂等失效、``revision_round`` 连加两次）。
    本相位是 ``meta.revision_round`` 的**首个写入方**（此前全仓无写入方）。

**finding 处置通道（``aresolve_finding`` / ``adismiss_finding``）是超界出口的死锁解药**
    114-03 轮次用尽后蓝图落 ``pending_review`` 并留下未决 BLOCKER finding 线程，而
    114-01 的 confirm 守卫把 ``kind=ai_review_finding & severity=blocker &
    status ∈ {open, answered}`` 一律判为「不可确认」⇒ **没有处置通道时人审只能驳回、
    永远无法通过**（超界出口自带死锁）。处置一律经 ``resolve_thread``——``resolved``
    与 ``dismissed`` 都是终态，离开守卫判据②的集合，confirm 随之放行。
    ⛔ **绝不用作答通道**（会把 ``open`` 推到 ``answered`` 的那个方法）：``answered``
    仍在守卫判据里，**根本解不开死锁**，还会留下「看着已回答其实仍阻塞」的假象。

**澄清超时提醒 best-effort：不自动作答、不改状态、不判失败**
    判据状态是 ``needs_clarification``（对齐 SC-4「blocking 澄清无人应答」，**不是**
    ``pending_review``）下的 ``open + blocking`` 线程；周期读
    ``SettingKeys.BLUEPRINT_REVIEW_CONFIG.pending_reminder_hours``（缺配置整段回落
    ``_DEFAULT_REMINDER_HOURS``）；到期锚点是 ``thread.last_reminded_at or
    thread.created_at``，提醒后写回 ``last_reminded_at`` ⇒ **同周期内不重复轰炸**。
    执行路径挂**既有 apscheduler** 的 ``remind_blueprint_clarifications`` job
    （⛔ 不新起 cron / systemd timer / 第二个 scheduler 进程）。本模块只产提醒对象名单、
    记 ``caller`` 日志、写周期锚点；实际渠道投递（飞书卡片重推 / 站内通知）由 115/116
    的通知面消费，本相位不新建推送通道、不新增事件常量。

观测：日志只记 ``artifact_id`` / ``thread_id`` / 计数 / ``duration_ms`` 等标量与关联键，
**评论正文、处置理由正文、澄清问题正文一律不进日志**（T-114-36）；异常文本走
``redact_secrets_in_text``。
"""

from __future__ import annotations

import copy
import time
from datetime import timedelta
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone

from common.logging import redact_secrets_in_text
from delivery.models import (
    BlueprintStatus,
    ThreadKind,
    ThreadStatus,
)
from delivery.services.blueprint_lifecycle_service import (
    BlueprintLifecycleService,
    ConcurrentBlueprintTransitionError,
)

logger = structlog.get_logger(__name__)

__all__ = [
    "bump_revision_round",
    "aapprove_blueprint",
    "areject_blueprint",
    "aresolve_finding",
    "adismiss_finding",
    "aremind_clarification_threads",
]

_COMPONENT = "blueprint_review_action"

# 驳回版本的归属前缀（与 114-04 的 human_edit: / ai_review_reflow: /
# human_block_restore: 并列，构成 produced_by_ref 四前缀全集）
REJECT_PREFIX = "blueprint_review_reject:"

# 驳回后会话复位的目标 stage（见 `_areopen_session_for_rework` 的取舍说明）
_REWORK_STAGE = "merge"

# 提醒周期回落值（配置缺失 / 坏值 / 非正数一律回落到它）
_DEFAULT_REMINDER_HOURS = 24
# 单次 job tick 的扫描上界（提醒是 best-effort，绝不为了「扫全」拖垮 scheduler）
_DEFAULT_SCAN_LIMIT = 100
_MAX_DETAIL_CHARS = 500


# ---------------------------------------------------------------------------
# 纯函数：revision_round 递增（无 IO / 无 ORM，恒不抛）
# ---------------------------------------------------------------------------


def bump_revision_round(content: Any) -> tuple[dict, int]:
    """``meta.revision_round + 1``，返回 ``(新 content, 新轮次)``。**恒不抛**。

    容错三档（半可信输入：content 来自 LLM 装配产物与人工编辑）：

    - content 非 dict（``None`` / 字符串 / 数字）→ 从 ``{}`` 起算；
    - 缺 ``meta`` 段或 ``meta`` 非 dict → 重建为 ``{}``；
    - 旧值非 int（字符串 / None / float）或为负 → 按 0 起算。

    ``deepcopy`` 后改：入参**绝不被原地修改**（调用方还要拿基线 content 做 diff）。
    """
    base = copy.deepcopy(content) if isinstance(content, dict) else {}
    meta = base.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        base["meta"] = meta
    old = meta.get("revision_round")
    if not isinstance(old, int) or isinstance(old, bool) or old < 0:
        old = 0
    new_round = old + 1
    meta["revision_round"] = new_round
    return base, new_round


# ---------------------------------------------------------------------------
# 内部 helper
# ---------------------------------------------------------------------------


def _user_id(user: Any, fallback: str = "system") -> str:
    uid = str(getattr(user, "id", "") or "")
    return uid or (str(fallback or "") or "system")


def _detail(text: Any) -> str:
    """异常/错因文本 → 可回显的脱敏截断串。"""
    return redact_secrets_in_text(str(text or ""))[:_MAX_DETAIL_CHARS]


def _current_status(artifact: Any) -> str:
    """**只读**取当前蓝图状态，供返回体呈现。

    返回键刻意叫 ``current_status`` 而非模型字段名：
    ``test_inv6_no_bypass_blueprint_status_field_write`` 把「模型字段名 + 等号」形态的
    赋值 / kwarg / 字典键一律判为旁路写——那条正则正是为了逮住用 ``**{…}`` 展开绕过
    CAS 的写法。本模块只读该字段、从不写它，但拿字段名当返回键会在纯读场景下触发
    那条**正确**的守卫。换个键名，守卫保持满弦、本模块也无需豁免。
    """
    return str(getattr(artifact, "blueprint_status", "") or "")


async def _alatest_version(artifact: Any) -> Any:
    """读最新版本作基线（⛔ 绝不读 ``session.current_artifact_version``——它可能落后于
    人工编辑/回灌刚落的版本，拿它当基线会静默丢掉那些改动）。"""
    from delivery.models import ArtifactVersion

    return (
        await ArtifactVersion.objects.filter(artifact_id=artifact.id)
        .order_by("-version_no")
        .afirst()
    )


async def _aadd_reviewer(lifecycle: Any, artifact: Any, user: Any, first_action: str) -> None:
    """reviewer upsert（``user`` 为 None 时跳过）。best-effort：名单写失败不该让
    已持久化的人审动作变成失败。"""
    if user is None:
        return
    try:
        await lifecycle.add_reviewer(artifact, user, first_action)
    except Exception as exc:  # noqa: BLE001 — 名单 upsert 失败绝不反噬主动作
        logger.warning(
            "blueprint_reviewer_upsert_failed",
            category="caller",
            component=_COMPONENT,
            artifact_id=str(getattr(artifact, "id", "")),
            first_action=first_action,
            error=_detail(exc),
        )


# ---------------------------------------------------------------------------
# 通过 / 驳回
# ---------------------------------------------------------------------------


async def aapprove_blueprint(
    artifact: Any,
    *,
    user: Any = None,
    initiated_by_user_id: str = "system",
    session: Any = None,
    lifecycle_service: Any = None,
) -> dict:
    """人审通过 → ``confirmed``。恒定三键 ``{status, detail, current_status}``。

    ``status`` 四态：

    - ``confirmed``：已推进（DB 重读为 ``confirmed``）；
    - ``blocked``：守卫拒绝（有 open+blocking 线程或未决 BLOCKER）**或**非法转移——
      两者都由 ``transition`` 抛 ``ValueError``，DB 不写；
    - ``conflict``：CAS 冲突（并发把状态推走了），DB 不写；
    - ``invalid``：其余异常。

    ⭐ **全程零事务外查询**：不调 ``aunresolved_blocker_count`` /
    ``ahas_open_blocking_threads``——守卫判据在 ``_apply_transition_sync`` 的事务内。
    """
    started = time.monotonic()
    lifecycle = lifecycle_service or BlueprintLifecycleService()
    initiated = _user_id(user, initiated_by_user_id)
    result = {"status": "", "detail": "", "current_status": ""}
    try:
        await lifecycle.transition(
            artifact,
            BlueprintStatus.CONFIRMED,
            initiated_by_user_id=initiated,
            acting_user=user,
            session=session,
        )
        result["status"] = "confirmed"
    except ConcurrentBlueprintTransitionError as exc:
        result["status"] = "conflict"
        result["detail"] = _detail(exc)
    except ValueError as exc:
        # 守卫拒绝与非法边共用 ValueError（114-01 的守卫文案：「存在未解决的阻塞澄清
        # 线程或未决 BLOCKER 审查发现，蓝图不可确认」）——两者都是 409 语义。
        result["status"] = "blocked"
        result["detail"] = _detail(exc)
    except Exception as exc:  # noqa: BLE001
        result["status"] = "invalid"
        result["detail"] = _detail(exc)

    result["current_status"] = _current_status(artifact)
    if result["status"] == "confirmed":
        await _aadd_reviewer(lifecycle, artifact, user, "review_approve")
    logger.info(
        "blueprint_review_approved",
        category="caller",
        component=_COMPONENT,
        artifact_id=str(getattr(artifact, "id", "")),
        status=result["status"],
        current_status=result["current_status"],
        initiated_by_user_id=initiated,
        duration_ms=round((time.monotonic() - started) * 1000, 2),
    )
    return result


async def areject_blueprint(
    artifact: Any,
    *,
    user: Any = None,
    comment: str = "",
    anchor: Any = None,
    initiated_by_user_id: str = "system",
    session: Any = None,
    artifact_service: Any = None,
    lifecycle_service: Any = None,
) -> dict:
    """人审驳回 → ``meta.revision_round + 1`` 落新版本 → ``drafting``。

    恒定七键 ``{status, version_id, version_no, revision_round, thread_id, detail,
    current_status}``；``status ∈ {rejected, unchanged, invalid, conflict}``。

    五步（顺序固定）：

    1. **重读**最新版本作基线（每次调用都重读，**不接受调用方传入的 content**——
       内存副本会让同 hash 幂等失效、轮次连加两次）；无版本 → ``invalid``。
    2. ``bump_revision_round``。
    3. ``add_version``（``produced_by_ref = blueprint_review_reject:{user_id}``）；
       ``ArtifactContentInvalid`` → ``invalid``，**绝不落半合法版本**。
    4. ``transition("drafting")``；``ValueError`` → ``invalid`` /
       ``ConcurrentBlueprintTransitionError`` → ``conflict``。⚠️ 此时**版本已落**——
       返回体里如实带上 ``version_no`` / ``revision_round``，让端点能把「版本已落但
       状态未转」这一半成功状态告诉用户，**绝不静默**。
    5. ⭐ **复位终态会话**（``_areopen_session_for_rework``）：``pending_review`` 必由
       ``ai_review`` 的两条 ``__done__`` 出边到达 ⇒ 驳回时会话必定终态，不复位则续驱
       与 ``engine.advance`` 双双短路、AI 永远不重跑（114-MJ-01）。best-effort。
    6. ``comment`` 非空 → 开一条 ``kind=human_comment`` 划线评论线程（``blocking=False``、
       ``severity=""`` ⇒ 不受 114-01 的 finding 不变式约束，也不会把蓝图钉死）。

    ⚠️ ``current_status`` 是**本 service 返回时**的取值。端点在其后还要跑续驱，而续驱的
    ``_amap_blueprint_status`` 可能据「仍有 open+blocking 线程」把它推成
    ``needs_clarification`` ⇒ **端点必须在续驱之后重读该字段**，不能直接回传本键，否则
    前端拿到的状态刷新一下就变（114-MJ-01 第二点）。
    """
    started = time.monotonic()
    from delivery.services import ArtifactService
    from delivery.services.artifact_service import ArtifactContentInvalid

    lifecycle = lifecycle_service or BlueprintLifecycleService()
    artifacts = artifact_service or ArtifactService()
    initiated = _user_id(user, initiated_by_user_id)
    result = {
        "status": "",
        "version_id": "",
        "version_no": 0,
        "revision_round": 0,
        "thread_id": "",
        "detail": "",
        "current_status": _current_status(artifact),
    }

    base = await _alatest_version(artifact)
    if base is None:
        result["status"] = "invalid"
        result["detail"] = "该蓝图尚无版本，无法驳回"
        return result

    new_content, new_round = bump_revision_round(base.content)
    try:
        version = await artifacts.add_version(
            artifact,
            new_content,
            produced_by_session_id=str(getattr(session, "id", "") or ""),
            produced_by_ref=f"{REJECT_PREFIX}{_user_id(user, initiated)}",
        )
    except ArtifactContentInvalid as exc:
        logger.warning(
            "blueprint_review_reject_invalid_content",
            category="caller",
            component=_COMPONENT,
            artifact_id=str(getattr(artifact, "id", "")),
            initiated_by_user_id=initiated,
            error=_detail(exc),
        )
        result["status"] = "invalid"
        result["detail"] = _detail(exc)
        return result

    result["version_id"] = str(getattr(version, "id", "") or "")
    result["version_no"] = int(getattr(version, "version_no", 0) or 0)
    result["revision_round"] = new_round

    try:
        await lifecycle.transition(
            artifact,
            BlueprintStatus.DRAFTING,
            initiated_by_user_id=initiated,
            acting_user=user,
            session=session,
        )
        result["status"] = "rejected"
    except ConcurrentBlueprintTransitionError as exc:
        result["status"] = "conflict"
        result["detail"] = _detail(exc)
    except ValueError as exc:
        result["status"] = "invalid"
        result["detail"] = _detail(exc)
    result["current_status"] = _current_status(artifact)

    if result["status"] == "rejected":
        # ⭐ 必须在「版本已落 + 轮次已加 + 状态已 drafting」之后才复位会话：复位让会话重新
        # 可被 advance，早一步就把「状态已 drafting 而轮次未加」的窗口暴露给 AI。
        await _areopen_session_for_rework(session, initiated_by_user_id=initiated)
        thread_id = await _aopen_reject_comment(
            lifecycle,
            artifact,
            comment=comment,
            anchor=anchor,
            version=version,
            initiated_by_user_id=initiated,
            user=user,
        )
        result["thread_id"] = thread_id
        await _aadd_reviewer(lifecycle, artifact, user, "review_reject")

    logger.info(
        "blueprint_review_rejected",
        category="caller",
        component=_COMPONENT,
        artifact_id=str(getattr(artifact, "id", "")),
        status=result["status"],
        version_no=result["version_no"],
        revision_round=new_round,
        has_comment=bool(str(comment or "").strip()),
        initiated_by_user_id=initiated,
        duration_ms=round((time.monotonic() - started) * 1000, 2),
    )
    return result


async def _areopen_session_for_rework(session: Any, *, initiated_by_user_id: str) -> bool:
    """驳回后把**终态**会话复位到融合 stage，让续驱真的能重跑（best-effort）。

    ⭐ **没有这一步驳回就是空动作**：``pending_review`` 只能由 ``ai_review`` 的
    ``review_passed`` / ``review_exhausted`` 到达，而两条出边都落 ``__done__`` ⇒ 人能点
    驳回的那一刻会话**必定**是终态，而续驱驱动器（``blueprint_resume`` 的
    ``while session.status not in terminal``）与 ``engine.advance`` 都对终态直接短路。
    结果是驳回只做了「版本 +1 + ``revision_round`` +1 + 开一条评论线程」，然后蓝图停在
    ``drafting``、**没有任何进程会再碰它**，用户写的驳回理由 AI 永远看不到，
    ``revision_round`` 也永远只会是 1（114-MJ-01）。

    复位目标取 :data:`_REWORK_STAGE`（``merge``）而不是 ``ai_review``：只回审查 stage 等于
    拿同一份内容再审一遍，必然复现同样的 findings。回 ``merge`` 与 ``ai_review`` 既有的
    ``remerge`` 出边**同目标**——「重跑融合再重审」在本 stage graph 里已是登记在案的返工
    路径，不新造语义。人工块保护（B3）挂在审查入口，重跑融合不会覆盖人工编辑。

    ⚠️ 蓝图上仍有 open+blocking 线程时，重跑会在 ``merge``/``ai_review`` 的
    ``needs_clarification`` self-loop 上停住等人处置——这是**正确**行为：人先处置未决项，
    处置端点自带续驱，闭环随之继续。

    best-effort：复位失败只记 warning，**绝不反噬已持久化的驳回**（版本与状态都已落库，
    下一次任意动作续驱时判据仍成立）。
    """
    if session is None:
        return False
    from delivery.services.convergence_session_service import ConvergenceSessionService

    try:
        return await ConvergenceSessionService().areopen_stage(
            session, stage=_REWORK_STAGE, reason="human_reject"
        )
    except Exception as exc:  # noqa: BLE001 — 复位失败绝不反噬已落库的驳回
        logger.warning(
            "blueprint_review_reject_session_reopen_failed",
            category="caller",
            component=_COMPONENT,
            session_id=str(getattr(session, "id", "")),
            initiated_by_user_id=initiated_by_user_id or "system",
            error=_detail(exc),
        )
        return False


async def _aopen_reject_comment(
    lifecycle: Any,
    artifact: Any,
    *,
    comment: str,
    anchor: Any,
    version: Any,
    initiated_by_user_id: str,
    user: Any,
) -> str:
    """驳回附带的划线评论 → 一条 ``human_comment`` 线程（best-effort，评论开不出来
    不该让「已驳回」变成失败）。**评论正文绝不进日志**。"""
    body = str(comment or "").strip()
    if not body:
        return ""
    try:
        thread = await lifecycle.open_thread(
            artifact,
            kind=ThreadKind.HUMAN_COMMENT,
            blocking=False,
            question=body,
            anchor=anchor if isinstance(anchor, dict) else None,
            created_on_version=version,
            initiated_by_user_id=initiated_by_user_id,
            return_stage=BlueprintStatus.DRAFTING,
        )
    except Exception as exc:  # noqa: BLE001 — 评论失败绝不反噬已落库的驳回
        logger.warning(
            "blueprint_review_reject_comment_failed",
            category="caller",
            component=_COMPONENT,
            artifact_id=str(getattr(artifact, "id", "")),
            initiated_by_user_id=initiated_by_user_id,
            error=_detail(exc),
        )
        return ""
    return str(getattr(thread, "id", "") or "")


# ---------------------------------------------------------------------------
# ⭐ finding 处置（B2：超界死锁的唯一正向出口）
# ---------------------------------------------------------------------------


async def aresolve_finding(
    thread: Any,
    *,
    reason: str,
    user: Any = None,
    initiated_by_user_id: str = "system",
    lifecycle_service: Any = None,
) -> dict:
    """采纳并标记已修复 → 线程落 ``resolved``（离开 confirm 守卫判据②）。"""
    return await _adispose_finding(
        thread,
        reason=reason,
        user=user,
        initiated_by_user_id=initiated_by_user_id,
        lifecycle_service=lifecycle_service,
        dismissed=False,
    )


async def adismiss_finding(
    thread: Any,
    *,
    reason: str,
    user: Any = None,
    initiated_by_user_id: str = "system",
    lifecycle_service: Any = None,
) -> dict:
    """判为误报忽略 → 线程落 ``dismissed``（同样离开守卫判据②）。"""
    return await _adispose_finding(
        thread,
        reason=reason,
        user=user,
        initiated_by_user_id=initiated_by_user_id,
        lifecycle_service=lifecycle_service,
        dismissed=True,
    )


async def _adispose_finding(
    thread: Any,
    *,
    reason: str,
    user: Any,
    initiated_by_user_id: str,
    lifecycle_service: Any,
    dismissed: bool,
) -> dict:
    """finding 处置收口（``resolve`` / ``dismiss`` 共用体）。

    恒定三键 ``{status, thread_id, detail}``，``status ∈ {resolved, dismissed,
    invalid, noop}``：

    - ``reason`` 空 → ``invalid`` 且**不落库**。处置一条 BLOCKER finding 等于「人工
      判定 AI 的审查结论不成立或已修复」，无理由的处置在审计上等于凭空放行。
    - ``kind != ai_review_finding`` → ``invalid``（本通道只处置审查发现；澄清线程走
      answer 端点）。
    - 线程已是终态（``resolved`` / ``dismissed``）→ ``noop``，**不覆盖首次结论**。
    - 否则 ``resolve_thread(resolution=…, dismissed=…)``。

    ⭐ **死锁机理**：114-03 超界后蓝图落 ``pending_review`` 并留下未决 BLOCKER finding，
    而 114-01 的 confirm 守卫（事务内单次 ``Q``）把 ``status ∈ {open, answered}`` 的
    blocker finding 一律判为「不可确认」⇒ 人审只能驳回、永远无法通过。处置后
    ``_has_confirm_blockers_sync`` 的两条判据对该线程都不再命中 ⇒ approve 可放行。
    这是超界出口**唯一**的正向解法，另一条只能是驳回重跑。
    ⛔ 因此绝不能用作答通道处置：它只把线程推到 ``answered``，仍在判据②里。

    **处置人与理由都写进结论文本**——``BlueprintThreadMessage`` 无结构化「处置人」
    字段，结论文本是唯一留痕位。⚠️ 理由**正文不进日志**，只记 ``reason_len``。
    """
    started = time.monotonic()
    lifecycle = lifecycle_service or BlueprintLifecycleService()
    initiated = _user_id(user, initiated_by_user_id)
    thread_id = str(getattr(thread, "id", "") or "")
    action = "dismiss" if dismissed else "resolve"
    first_action = "finding_dismiss" if dismissed else "finding_resolve"
    text = str(reason or "").strip()

    if not text:
        return {"status": "invalid", "thread_id": thread_id, "detail": "处置理由不可为空"}
    if str(getattr(thread, "kind", "") or "") != ThreadKind.AI_REVIEW_FINDING:
        return {
            "status": "invalid",
            "thread_id": thread_id,
            "detail": "该通道只处置 AI 审查发现线程",
        }
    if str(getattr(thread, "status", "") or "") in (
        ThreadStatus.RESOLVED,
        ThreadStatus.DISMISSED,
    ):
        return {"status": "noop", "thread_id": thread_id, "detail": "该线程已处置，结论保持不变"}

    label = "误报忽略" if dismissed else "已修复"
    try:
        await lifecycle.resolve_thread(
            thread,
            resolution=f"[{label}] {text}（处置人：{initiated}）",
            initiated_by_user_id=initiated,
            dismissed=dismissed,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "blueprint_finding_dispose_failed",
            category="caller",
            component=_COMPONENT,
            thread_id=thread_id,
            action=action,
            initiated_by_user_id=initiated,
            error=_detail(exc),
        )
        return {"status": "invalid", "thread_id": thread_id, "detail": _detail(exc)}

    artifact = getattr(thread, "artifact", None)
    if artifact is not None:
        await _aadd_reviewer(lifecycle, artifact, user, first_action)

    logger.info(
        "blueprint_finding_dismissed" if dismissed else "blueprint_finding_resolved",
        category="caller",
        component=_COMPONENT,
        thread_id=thread_id,
        artifact_id=str(getattr(artifact, "id", "") or ""),
        severity=str(getattr(thread, "severity", "") or ""),
        reason_len=len(text),
        initiated_by_user_id=initiated,
        duration_ms=round((time.monotonic() - started) * 1000, 2),
    )
    return {
        "status": "dismissed" if dismissed else "resolved",
        "thread_id": thread_id,
        "detail": "",
    }


# ---------------------------------------------------------------------------
# ⭐ 澄清超时提醒执行体（B4；被 tasks/blueprint_reminder_tasks.py 的周期任务调用）
# ---------------------------------------------------------------------------


async def _aload_reminder_hours() -> int:
    """读 ``BLUEPRINT_REVIEW_CONFIG.pending_reminder_hours``。

    照 ``_aload_merge_config`` 的「配置坏了回落常量、绝不阻断」写法：缺配置 / 非 JSON /
    缺键 / 值类型错 / 非正数 ⇒ 整段回落 ``_DEFAULT_REMINDER_HOURS``。提醒周期是体验项
    不是可用性项，配置坏了不该让提醒彻底停摆。
    """
    try:
        from system.models import SettingKeys
        from system.settings_service import aget_json_setting

        cfg = await aget_json_setting(SettingKeys.BLUEPRINT_REVIEW_CONFIG, {}) or {}
        hours = int(cfg.get("pending_reminder_hours", _DEFAULT_REMINDER_HOURS))
    except Exception:  # noqa: BLE001 — 配置读失败一律回落常量
        return _DEFAULT_REMINDER_HOURS
    return hours if hours > 0 else _DEFAULT_REMINDER_HOURS


@sync_to_async
def _list_pending_threads(limit: int) -> list:
    """``needs_clarification`` 蓝图上的 ``open + blocking`` 线程（只读）。

    ⭐ 判据状态是 ``needs_clarification`` **不是** ``pending_review``（对齐 SC-4
    「blocking 澄清无人应答」）：``pending_review`` 是「等人审决策」，那不是无人应答
    的澄清，提醒它只会制造噪声。``select_related("artifact")`` 防 async 裸 lazy-FK。

    ⭐ **必须显式 ``order_by``**（114-MN-01）：``BlueprintThread.Meta`` 没有 ``ordering``，
    不排序的 ``[:limit]`` 是无 ``ORDER BY`` 的 ``LIMIT`` —— 返回哪几条由存储层决定，跨
    版本/跨引擎不稳定。更要命的是**饿死**：提醒过的线程写回 ``last_reminded_at`` 后仍满足
    过滤条件、仍占着那 ``limit`` 个名额（只是每轮记 ``skipped``），全站未应答的 blocking
    澄清线程一旦超过上界，排在后面的可能**永远**拿不到一次提醒，而 job 每小时照跑、日志
    照报 completed —— 失效完全静默。按「最该被提醒的排前面」排序（``last_reminded_at``
    升序 nulls first，同值再按 ``created_at``）⇒ 已提醒的自然沉底，扫描窗口逐轮滚动。
    """
    from django.db.models import F

    from delivery.models import BlueprintThread

    return list(
        BlueprintThread.objects.filter(
            artifact__blueprint_status=BlueprintStatus.NEEDS_CLARIFICATION,
            status=ThreadStatus.OPEN,
            blocking=True,
        )
        .select_related("artifact")
        .order_by(F("last_reminded_at").asc(nulls_first=True), "created_at")[:limit]
    )


@sync_to_async
def _list_recipients(artifact_id: Any) -> list[str]:
    """提醒对象 = ``BlueprintReviewer`` 名单 ∪ 关联蓝图会话的发起人（去重升序）。

    ⚠️ 反查会话**必须带 ``process_type="technical_blueprint"`` 过滤**：同一 artifact 上
    可能同时挂着旧 ``technical_plan`` 与蓝图两条会话（两条 process 共用同一
    ``artifact_type``），不过滤会把旧 process 的发起人当成本蓝图的相关人。
    """
    from delivery.models import BlueprintReviewer, ConvergenceSession
    from services.process_runtime.blueprint_resume import BLUEPRINT_PROCESS_TYPE

    ids = {
        str(uid)
        for uid in BlueprintReviewer.objects.filter(artifact_id=artifact_id).values_list(
            "user_id", flat=True
        )
        if uid
    }
    initiators = ConvergenceSession.objects.filter(
        current_artifact_version__artifact_id=artifact_id,
        process_type=BLUEPRINT_PROCESS_TYPE,
    ).values_list("created_by_id", flat=True)
    ids |= {str(uid) for uid in initiators if uid}
    return sorted(ids)


@sync_to_async
def _write_reminder_anchors(rows: list, now: Any) -> None:
    """一次 ``bulk_update`` 写回周期锚点。

    ⚠️ ``bulk_update`` **绕过 auto_now** ⇒ 必须显式带 ``updated_at``，否则 DB 里的
    ``updated_at`` 会永远停在上一次普通 save 的时刻（同 ``_apply_transition_sync``
    与 114-04 ``_reanchor_threads_sync`` 的既有纪律）。
    """
    from delivery.models import BlueprintThread

    for row in rows:
        row.last_reminded_at = now
        row.updated_at = now
    BlueprintThread.objects.bulk_update(rows, ["last_reminded_at", "updated_at"])


async def aremind_clarification_threads(
    *,
    hours: int | None = None,
    now: Any = None,
    limit: int = _DEFAULT_SCAN_LIMIT,
    initiated_by_user_id: str = "system",
) -> dict:
    """按周期提醒未应答的 blocking 澄清线程。恒定四键 ``{scanned, due, reminded, skipped}``。

    - **扫描面**：``blueprint_status == needs_clarification`` 的 artifact 上
      ``status=open & blocking=True`` 的线程。
    - **到期判据**：``anchor = thread.last_reminded_at or thread.created_at``；
      ``now - anchor >= timedelta(hours=hours)`` 才算 ``due``，否则 ``skipped``。
      ⇒ **同一线程在同一周期内不会被再次提醒**。
    - ⭐ **``reminded`` 的口径是「周期锚点已写回」**：计数与逐条
      ``blueprint_clarification_reminded`` 事件都在 ``_write_reminder_anchors`` **成功之后**
      才落。写回失败时 ``due`` 如实保留、``reminded`` 归零、一条事件都不发——否则运维看到
      「本轮提醒了 N 条」，实际是「一条锚点都没落、下一轮再提醒同样这 N 条」（114-MN-04）。
    - ``hours`` 形参优先，缺省读配置；``now`` 形参**只为可测**（测试注入推进后的时间，
      不 monkeypatch 全局 ``timezone.now``）。
    - ⛔ **不自动作答、不改蓝图状态、不判失败、不新建线程**：本函数除
      ``last_reminded_at`` / ``updated_at`` 外**零写**。
    - 单线程失败 ``try/except`` 隔离；整体再包一层 → warning + 返回已积累计数
      （提醒失败绝不反噬人审、绝不打断 scheduler 主循环）。
    """
    started = time.monotonic()
    counts = {"scanned": 0, "due": 0, "reminded": 0, "skipped": 0}
    try:
        window = timedelta(hours=hours if hours and hours > 0 else await _aload_reminder_hours())
        moment = now or timezone.now()
        threads = await _list_pending_threads(max(int(limit or 0), 0) or _DEFAULT_SCAN_LIMIT)
        counts["scanned"] = len(threads)

        due_rows: list = []
        recipient_counts: dict[str, int] = {}
        for thread in threads:
            try:
                anchor = thread.last_reminded_at or thread.created_at
                if anchor is None or (moment - anchor) < window:
                    counts["skipped"] += 1
                    continue
                counts["due"] += 1
                recipients = await _list_recipients(thread.artifact_id)
                recipient_counts[str(thread.id)] = len(recipients)
                due_rows.append(thread)
            except Exception as exc:  # noqa: BLE001 — 单线程异常隔离，绝不阻断整批
                counts["skipped"] += 1
                logger.warning(
                    "blueprint_clarification_remind_thread_failed",
                    category="sampling",
                    component=_COMPONENT,
                    thread_id=str(getattr(thread, "id", "")),
                    error=_detail(exc),
                )

        if due_rows:
            # ⭐ 计数与逐条事件都在**锚点写回成功之后**才发（114-MN-04）：写回抛异常时被外层
            # except 接住并原样 return，若在此之前累加/发事件，对运维呈现的是「本轮提醒了 N
            # 条」+ N 条 `blueprint_clarification_reminded`，而实际是「一条锚点都没落、下一轮
            # 会把同样这 N 条再提醒一遍」。写回失败时 `due` 如实保留（确实到期了）、
            # `reminded` 保持 0，且一条提醒事件都不发。
            await _write_reminder_anchors(due_rows, moment)
            counts["reminded"] = len(due_rows)
            for thread in due_rows:
                # ⚠️ 问题正文与 recipients 明细绝不进日志，只记计数。
                logger.info(
                    "blueprint_clarification_reminded",
                    category="caller",
                    component=_COMPONENT,
                    thread_id=str(thread.id),
                    artifact_id=str(thread.artifact_id),
                    recipient_count=recipient_counts.get(str(thread.id), 0),
                    hours=int(window.total_seconds() // 3600),
                    initiated_by_user_id=initiated_by_user_id or "system",
                )
    except Exception as exc:  # noqa: BLE001 — 提醒整体 best-effort，绝不上抛
        logger.warning(
            "blueprint_clarification_remind_failed",
            category="caller",
            component=_COMPONENT,
            initiated_by_user_id=initiated_by_user_id or "system",
            error=_detail(exc),
        )
        return counts

    logger.info(
        "blueprint_clarification_remind_completed",
        category="caller",
        component=_COMPONENT,
        initiated_by_user_id=initiated_by_user_id or "system",
        duration_ms=round((time.monotonic() - started) * 1000, 2),
        **counts,
    )
    return counts
