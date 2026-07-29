"""扫描超期 pending 澄清并走出口（RELY-02，SC-4 后半句）。

无人应答的澄清必须有明确出口：到期后按配置默认「带未澄清假设继续推进」
（``transition(session, "clarified")`` → ``current_stage=research`` / ``status=running``）
或「如实失败并说明原因」（``transition(session, "fail")``），会话不再永久停在
``waiting_clarification``（这正是生产事故里 agent 绕道徒手编方案的前提）。

设计红线：

- **幂等不新建机制**：出口只经 ``ConvergenceSessionService.transition``（INV-6 唯一状态入口），
  其「DB 行 ``current_stage == from_stage``」条件更新即 CAS，天然只生效一次；并发第二方命中
  0 行抛 ``ConcurrentTransitionError``，本命令捕获后当 no-op。**不自建任何互斥机制**
  （无数据库咨询锁、无外部缓存锁、无进程内互斥）。
- **两段式事务纪律**（逐字镜像 ``workflows/management/commands/check_timeouts.py``）：
  ``transaction.atomic()`` + ``select_for_update(skip_locked=True)`` 块内**只做同步读、只收集**
  目标；异步引擎重驱在事务外 ``asyncio.run``（Pitfall 9：持锁事务内调异步 ORM 会长事务持锁 /
  跨线程复用连接 / ``SynchronousOnlyOperation``）。
- **best-effort**：单条会话失败只记 ``logger.exception``，其余照常处理，命令退出码恒 0
  （绝不因单条失败打断 scheduler 主循环）。
- **「未澄清假设」只写会话 ``stage_state``**（D-6）：不改任何受 DEPTH 冻结的渲染文件。

Usage: python manage.py expire_pending_clarifications [--dry-run] [--limit N] [--session-id UUID]
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from common.logging import redact_secrets_in_text
from delivery.models import (
    Clarification,
    ClarificationQuestion,
    ConvergenceSession,
    ConvergenceSessionStatus,
)
from delivery.services.convergence_session_service import (
    ConcurrentTransitionError,
    ConvergenceSessionService,
)
from delivery.services.event_taxonomy import EVENT_CLARIFICATION_TIMED_OUT
from interactions.redaction import redact_for_ledger

logger = structlog.get_logger(__name__)

# 出口动作：配置值 → 事件/标注里的语义名（**不是** ConvergenceSessionStatus 枚举值，
# 出口本身仍只经 transition 的 clarified / fail 两个事件，见 A3）。
_ACTION_RESUME = "resume_with_assumptions"
_ACTION_FAIL = "fail"
_EXIT_LABELS: dict[str, str] = {
    _ACTION_RESUME: "resumed_with_assumptions",
    _ACTION_FAIL: "failed_no_answer",
}

# 出口成因受控枚举（Phase 110 时间线据此区分「等太久」与「矛盾态」）。
_REASON_NO_ANSWER = "no_answer_timeout"

# fail 路径落在会话 error 里的稳定原因码。
_FAIL_REASON = "clarification_timeout_no_answer"


class Command(BaseCommand):
    help = "扫描超期未答的澄清轮并走超时出口（带未澄清假设继续 / 如实失败）"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="只报不改：列出将要出口的会话/轮/等待时长，零写库零 emit",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="单次扫描会话上限（默认取 settings.CLARIFICATION_EXPIRY_SCAN_LIMIT）",
        )
        parser.add_argument(
            "--session-id",
            dest="session_id",
            default=None,
            help="只处理指定会话（UAT / 定向处置用）",
        )

    def handle(self, *args: object, **options: object) -> None:
        dry_run = bool(options.get("dry_run"))
        limit = options.get("limit") or getattr(settings, "CLARIFICATION_EXPIRY_SCAN_LIMIT", 200)
        session_id = options.get("session_id") or None
        now = timezone.now()
        timeout_seconds = float(getattr(settings, "CLARIFICATION_TIMEOUT_HOURS", 24)) * 3600

        targets, scanned = self._collect(
            now, timeout_seconds, limit=int(limit), session_id=session_id
        )

        if dry_run:
            for target in targets:
                self.stdout.write(
                    f"[dry-run] session={target['session_id']} "
                    f"clarification={target['clarification_id']} "
                    f"round={target['round_no']} "
                    f"waited={round(target['waited_seconds'], 1)}s "
                    f"reason={target['reason']}"
                )
            self.stdout.write(
                f"[dry-run] 扫描 {scanned} 个等待澄清会话，命中 {len(targets)} 个出口目标（未写库）"
            )
            return

        exited = noop = failed = 0
        # 执行阶段在事务外：逐条 asyncio.run 调异步出口（Pitfall 9）。
        for target in targets:
            try:
                outcome = asyncio.run(self._aexit_one(target))
            except Exception:
                failed += 1
                logger.exception(
                    "clarification_timeout_exit_error",
                    category="caller",
                    component="delivery",
                    session_id=target["session_id"],
                    clarification_id=target["clarification_id"],
                )
                continue
            if outcome == "exited":
                exited += 1
            else:
                noop += 1

        self.stdout.write(
            f"扫描 {scanned} 个等待澄清会话；出口 {exited}，no-op {noop}，失败 {failed}"
        )
        logger.info(
            "clarification_timeout_scan_completed",
            category="caller",
            component="delivery",
            scanned=scanned,
            exited=exited,
            noop=noop,
            failed=failed,
            timeout_hours=timeout_seconds / 3600,
        )

    # ── 收集阶段（事务内，只读、只收集） ──────────────────────────────────────

    def _collect(
        self,
        now: Any,
        timeout_seconds: float,
        *,
        limit: int,
        session_id: str | None,
    ) -> tuple[list[dict[str, Any]], int]:
        """事务内 ``select_for_update(skip_locked=True)`` 收集出口目标（不写库、不调异步）。

        ``skip_locked=True`` 让并发扫描互不阻塞（T-107-08）；SQLite 下退化为 no-op，本地/CI
        的并发保护实际来自单进程 + ``max_instances=1`` + transition CAS——幂等的权威保证
        始终是 CAS，不是行锁。
        """
        targets: list[dict[str, Any]] = []
        scanned = 0
        with transaction.atomic():
            queryset = ConvergenceSession.objects.select_for_update(skip_locked=True).filter(
                status=ConvergenceSessionStatus.WAITING_CLARIFICATION
            )
            if session_id:
                queryset = queryset.filter(id=session_id)
            for session in queryset.order_by("created_at")[:limit]:
                scanned += 1
                try:
                    target = self._evaluate(session, now, timeout_seconds)
                except Exception:
                    logger.exception(
                        "clarification_timeout_scan_error",
                        category="sampling",
                        component="delivery",
                        session_id=str(session.id),
                    )
                    continue
                if target is not None:
                    targets.append(target)
        return targets, scanned

    def _evaluate(
        self, session: ConvergenceSession, now: Any, timeout_seconds: float
    ) -> dict[str, Any] | None:
        """判定单个会话是否到期需出口；返回目标元组（同步读，须在事务内调用）。"""
        round_meta = self._pending_round(session.id)
        if round_meta is None:
            return None
        # 起算时间取 pending 轮的 ``Clarification.created_at``（auto_now_add，不会被刷新）。
        # 绝不用 session.updated_at —— _apply_transition_sync 每次转移都写它，任何无关
        # 转移都会把它推到现在，超时永不到达（Pitfall 7）。
        waited_seconds = max((now - round_meta["created_at"]).total_seconds(), 0.0)
        if waited_seconds < timeout_seconds:
            return None
        return {
            "session_id": str(session.id),
            "clarification_id": str(round_meta["id"]),
            "round_no": round_meta["round_no"],
            "waited_seconds": waited_seconds,
            "reason": _REASON_NO_ANSWER,
        }

    @staticmethod
    def _pending_round(session_id: Any) -> dict[str, Any] | None:
        """取会话「最早仍未答」的澄清轮元数据（与 ahas_pending 同一谓词口径）。

        pending 的权威字段是 ``answered_at``（``container_status`` 只是送达/展示态，旧行可能
        为 NULL、新行可能是 ``delivery_failed``——按它过滤会漏掉全部旧行，见模型 docstring）。
        排序沿用 ``plan_research`` 取 pending 轮的既有范式 ``order_by("round_no", "created_at")``。
        """
        rows = (
            Clarification.objects.filter(session_id=session_id, answered_at__isnull=True)
            .order_by("round_no", "created_at")
            .values("id", "round_no", "created_at", "container_status")
        )
        for row in rows:
            children = ClarificationQuestion.objects.filter(clarification_id=row["id"])
            if children.exists() and not children.filter(answered_at__isnull=True).exists():
                # 子题已全答（容器推进因故未落地）→ 与 ahas_pending 一致视为已答，不出口。
                continue
            return row
        return None

    # ── 执行阶段（事务外，异步） ──────────────────────────────────────────────

    async def _aexit_one(self, target: dict[str, Any]) -> str:
        """单条出口：写 stage_state 标注 + 经 transition 推进 + emit + 归因日志。

        返回 ``"exited"``（本次真实推进）或 ``"noop"``（并发已推进 / 会话已消失）。
        """
        session = await ConvergenceSession.objects.filter(id=target["session_id"]).afirst()
        if session is None:
            return "noop"
        initiated_by = getattr(session, "initiated_by_user_id", "") or "system"
        action = self._exit_action()
        label = _EXIT_LABELS[action]
        unclarified = await self._acollect_unclarified_points(target["clarification_id"])
        exit_marker: dict[str, Any] = {
            "clarification_id": target["clarification_id"],
            "round_no": target["round_no"],
            "action": label,
            "reason": target["reason"],
            "waited_seconds": round(target["waited_seconds"], 1),
            "unclarified_points": unclarified,
            "at": timezone.now().isoformat(),
        }
        stage_state = dict(session.stage_state or {})
        stage_state["clarification_exit"] = exit_marker

        service = ConvergenceSessionService()
        log = logger.bind(
            category="caller",
            component="delivery",
            session_id=str(session.id),
            clarification_id=target["clarification_id"],
            exit_action=label,
            reason=target["reason"],
            initiated_by_user_id=initiated_by,
        )
        try:
            if action == _ACTION_FAIL:
                # fail 路径写入顺序：先落标注，再 transition("fail")。transition 的 fail
                # 特判只写 status/error（不接受 stage_state 参数），反序会留出「已进 failed
                # 终态但标注未落库」的窗口 → 「哪些点未澄清」不可查（T-107-04 出口必留痕）。
                # 条件写入（仍 waiting_clarification 才写）把「并发已推进却留下误导标注」
                # 的面收到最小。
                await ConvergenceSession.objects.filter(
                    id=session.id, status=ConvergenceSessionStatus.WAITING_CLARIFICATION
                ).aupdate(stage_state=stage_state)
                session.stage_state = stage_state
                await service.transition(
                    session,
                    "fail",
                    error={
                        "stage": "clarify",
                        "reason": _FAIL_REASON,
                        "clarification_id": target["clarification_id"],
                    },
                )
                if session.status != ConvergenceSessionStatus.FAILED:
                    # _fail 的 CAS 未命中（并发已推进）→ 内部静默返回，不抛；这里按 no-op 处理，
                    # 不 emit 也不记「已出口」，保「只推进一次只 emit 一次」。
                    log.info("clarification_timeout_exit_noop_concurrent", category="sampling")
                    return "noop"
            else:
                await service.transition(session, "clarified", stage_state=stage_state)
        except ConcurrentTransitionError:
            # 幂等 no-op：已被并发扫描或用户真实作答推进（CAS 命中 0 行）。
            log.info("clarification_timeout_exit_noop_concurrent", category="sampling")
            return "noop"
        except ValueError as exc:
            # 会话停在非 clarify stage（stage graph 无该转移）→ 记警告跳过，绝不抛。
            log.warning("clarification_timeout_exit_unsupported_stage", error=str(exc))
            return "noop"

        await self._aemit_timed_out(service, session, exit_marker)
        log.info(
            "clarification_timeout_exit",
            round_no=target["round_no"],
            waited_seconds=exit_marker["waited_seconds"],
            unclarified_count=len(unclarified),
        )
        return "exited"

    @staticmethod
    async def _aemit_timed_out(
        service: ConvergenceSessionService,
        session: ConvergenceSession,
        exit_marker: dict[str, Any],
    ) -> None:
        """emit ``clarification.timed_out``（payload 契约见 event_taxonomy 常量注释）。"""
        payload = {
            "clarification_id": exit_marker["clarification_id"],
            "round_no": exit_marker["round_no"],
            "exit_action": exit_marker["action"],
            "reason": exit_marker["reason"],
            "waited_seconds": exit_marker["waited_seconds"],
            "unclarified_points": exit_marker["unclarified_points"],
        }
        # 入库留痕整体再过一遍 redact_for_ledger（脱敏不可绕过，V8 双保险）。
        await service._emit_event(
            EVENT_CLARIFICATION_TIMED_OUT, session, redact_for_ledger(payload)
        )

    @staticmethod
    async def _acollect_unclarified_points(clarification_id: Any) -> list[dict[str, str]]:
        """该轮未答子题 → 「未澄清点」结构化列表（正文经既有脱敏 helper，V8）。"""
        points: list[dict[str, str]] = []
        async for row in (
            ClarificationQuestion.objects.filter(
                clarification_id=clarification_id, answered_at__isnull=True
            )
            .order_by("order")
            .values("id", "question")
        ):
            points.append(
                {
                    "question_id": str(row["id"]),
                    "question": redact_secrets_in_text(str(row["question"] or "")),
                }
            )
        return points

    @staticmethod
    def _exit_action() -> str:
        """出口动作配置读取；非法值按 ``resume_with_assumptions`` 兜底（绝不因配置错卡死）。"""
        raw = str(getattr(settings, "CLARIFICATION_TIMEOUT_EXIT_ACTION", _ACTION_RESUME) or "")
        return raw.strip() if raw.strip() in _EXIT_LABELS else _ACTION_RESUME
