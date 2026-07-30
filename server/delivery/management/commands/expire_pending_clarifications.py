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
- **出口必须真的推进**：``transition("clarified")`` 只把会话推到 ``research`` / ``running``，
  之后没有任何周期任务会扫 ``status=running`` 的会话——只做状态转移等于把「停在
  ``waiting_clarification``」换成「停在 ``research``」，RELY-02 要的「带未澄清假设**继续推进**」
  并未达成，而且 ``running`` 在看板上与正常运行不可区分、更难发现。故 resume 出口在事务外
  复用既有续驱 helper ``adrive_convergence_session_to_pause_or_terminal``（与 ``answer_resume``
  同源，不新造 engine 工厂）把会话推到重挂起短路点或终态。
- **best-effort**：单条会话失败只记 ``logger.exception``，其余照常处理，命令退出码恒 0
  （绝不因单条失败打断 scheduler 主循环）。
- **「未澄清假设」只写会话 ``stage_state``**（D-6）：不改任何受 DEPTH 冻结的渲染文件。

Usage: python manage.py expire_pending_clarifications [--dry-run] [--limit N] [--session-id UUID]
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
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
_REASON_DELIVERY_FAILED = "delivery_failed"
_REASON_WORKFLOW_TIMEOUT = "workflow_timeout"

# 澄清卡未送达的展示态标记（107-04 落的 container_status 新取值；该轮仍算 pending）。
_CONTAINER_DELIVERY_FAILED = "delivery_failed"

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
            self._observe_chat_clarifications(now, timeout_seconds)
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
        self._observe_chat_clarifications(now, timeout_seconds)

    @staticmethod
    def _observe_chat_clarifications(now: Any, timeout_seconds: float) -> None:
        """统计超期未答的 chat 协商卡数量（D-5：只观测，不出口）。

        出口机制只覆盖 ``delivery.Clarification``。chat 单题澄清走的是另一套中断/恢复
        语义（与 stage graph 完全不同），混做会让改动面不可控，故本命令只统计数量并记一条
        采样日志，出口留给后续 phase。
        """
        # 只读计数：绝不改任何 ConversationIntentTrace 行、绝不触碰 LangGraph 的 interrupt
        # 恢复路径（D-5 边界）。
        try:
            from chat.models import ConversationIntentTrace

            cutoff = now - timedelta(seconds=timeout_seconds)
            count = ConversationIntentTrace.objects.filter(
                answered_at__isnull=True, created_at__lt=cutoff
            ).count()
            logger.info(
                "chat_clarification_unanswered_observed",
                category="sampling",
                component="delivery",
                count=count,
                timeout_hours=timeout_seconds / 3600,
            )
        except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬扫描主流程
            pass

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
        """判定单个会话是否需出口；返回目标元组（同步读，须在事务内调用）。

        三条件取或（受控 reason 枚举，便于后续时间线区分出口成因）：

        1. 等满超时 → ``no_answer_timeout``（正常到期）；
        2. 该轮澄清卡未送达 → ``delivery_failed``（用户根本没看到卡，等满 24h 毫无意义；
           107-04 已保证该标记与「仍算 pending」并存）；
        3. 会话关联的工作流侧已判 TIMEOUT 而会话仍在等 → ``workflow_timeout``（D-4 纵深防御：
           任何时刻都不得存在「工作流已判超时而会话仍在等」的窗口，兜住携带旧 60 分钟到期
           时间的存量订阅行）。
        """
        round_meta = self._pending_round(session.id)
        if round_meta is None:
            return None
        # 起算时间取 pending 轮的 ``Clarification.created_at``（auto_now_add，不会被刷新）。
        # 绝不用 session.updated_at —— _apply_transition_sync 每次转移都写它，任何无关
        # 转移都会把它推到现在，超时永不到达（Pitfall 7）。
        waited_seconds = max((now - round_meta["created_at"]).total_seconds(), 0.0)
        if waited_seconds >= timeout_seconds:
            reason = _REASON_NO_ANSWER
        elif round_meta["container_status"] == _CONTAINER_DELIVERY_FAILED:
            reason = _REASON_DELIVERY_FAILED
        elif self._workflow_timed_out(session):
            reason = _REASON_WORKFLOW_TIMEOUT
        else:
            return None
        return {
            "session_id": str(session.id),
            "clarification_id": str(round_meta["id"]),
            "round_no": round_meta["round_no"],
            "waited_seconds": waited_seconds,
            "reason": reason,
        }

    @staticmethod
    def _workflow_timed_out(session: ConvergenceSession) -> bool:
        """工作流侧是否已判超时（D-4 纵深条件）。

        关联路径 ``ConvergenceSession.node_execution_id`` → ``NodeExecution.status`` 或其
        ``workflow_execution.status``。关联缺失（chat / MCP 入口无 node_execution，或行已被
        清理）→ 条件不成立，不报错。跨 app 读用函数级 import，保持 delivery→workflows 的
        依赖为惰性。
        """
        if not session.node_execution_id:
            return False
        from workflows.models.execution import (
            ExecutionStatus,
            NodeExecution,
            NodeExecutionStatus,
        )

        row = (
            NodeExecution.objects.filter(id=session.node_execution_id)
            .values("status", "workflow_execution__status")
            .first()
        )
        if row is None:
            return False
        return (
            row["status"] == NodeExecutionStatus.TIMEOUT
            or row["workflow_execution__status"] == ExecutionStatus.TIMEOUT
        )

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
                # transition 之后必须真的推一步，否则会话停在 research/running 无人驱动
                # （全仓没有任何周期任务扫 status=running 的 ConvergenceSession）。
                session = await self._aredrive(session, log)
        except ConcurrentTransitionError:
            # 幂等 no-op：已被并发扫描或用户真实作答推进（CAS 命中 0 行）。
            log.info("clarification_timeout_exit_noop_concurrent", category="sampling")
            return "noop"
        except ValueError as exc:
            # 会话停在非 clarify stage（stage graph 无该转移）→ 记警告跳过，绝不抛。
            # 异常文本统一过脱敏：同一条纪律不因「这条风险低」而开口子。
            log.warning(
                "clarification_timeout_exit_unsupported_stage",
                error=redact_secrets_in_text(str(exc)),
            )
            return "noop"

        await self._aemit_timed_out(service, session, exit_marker)
        log.info(
            "clarification_timeout_exit",
            round_no=target["round_no"],
            waited_seconds=exit_marker["waited_seconds"],
            unclarified_count=len(unclarified),
            # 续驱后的落点：出口是否真的把会话推离中间态，只能靠这两个字段在生产核对
            # （BL-01 的可观测面：停在 research/running 与推到终态在看板上不可区分）。
            final_status=str(session.status),
            final_stage=str(session.current_stage),
        )
        return "exited"

    @staticmethod
    async def _aredrive(session: ConvergenceSession, log: Any) -> ConvergenceSession:
        """resume 出口的引擎续驱（事务外）：把会话推到重挂起短路点或终态后返回。

        复用 ``answer_resume`` / ``plan_research`` 同源的 ``build_orchestration_engine`` +
        ``adrive_convergence_session_to_pause_or_terminal``——**不新造第二个 engine 工厂**。
        helper 自带 ``waiting_clarification`` / ``waiting_event`` 短路与 ``max_steps`` 保护，
        不会死循环。

        续驱失败不回退状态（``transition`` 已幂等落地，回退会破坏「单向推进」）：记
        ``exception`` 后按已出口计，返回续驱前的 session。
        """
        try:
            from services.process_runtime import (
                adrive_convergence_session_to_pause_or_terminal,
                build_orchestration_engine,
            )

            engine = build_orchestration_engine(
                node_execution_id=str(session.node_execution_id or "")
            )
            return await adrive_convergence_session_to_pause_or_terminal(engine, session)
        except Exception:  # noqa: BLE001 — 续驱 best-effort，绝不打断出口主流程
            log.exception("clarification_timeout_exit_redrive_failed")
            return session

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
