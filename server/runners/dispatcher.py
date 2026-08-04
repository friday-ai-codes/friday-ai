"""任务分发器 — 标签匹配 + 最少任务优先；派发动作经 durable 队列持久化。

31u 收尾：``dispatch()`` 不再内联试派 + 内存队列兜底（进程重启即丢、无自动重派），
改为「快照持久化 + 入队 durable 派发任务」两步——DB（``SubAgentSession.last_output``
的 dispatch 快照 + ``RunnerTaskAssignment`` 状态）是唯一真相源：

- 派发执行例程 ``_try_assign``（标签匹配 / 幂等守卫 / 监控事件）原样保留，由 durable
  worker 的任务体（``durable.tasks_impl.run_runner_dispatch``）调用；
- 无可用 runner / 无空槽时由任务体按退避 re-defer（run_at），runner 恢复后自动派出，
  不再依赖「runner 上线 / 槽位释放」事件触发 drain（内存队列语义整体退役）；
- 同一 session 的合法重派由任务体状态守卫（终态 / active assignment → no-op）保证
  幂等，防重复容器 / 重复 commit，而不是禁止重派。
"""

from dataclasses import dataclass, field
from datetime import timedelta

import structlog
from channels.layers import get_channel_layer
from django.utils import timezone

from runners.protocol import MessageType, make_request

logger = structlog.get_logger()

# 心跳超时阈值（秒）：3 倍心跳间隔（Runner 每 30 秒心跳）
HEARTBEAT_STALE_SECONDS = 90

# 落库脱敏键名单（103 审查 WR-03，31u 起以 dispatcher 为唯一定义点，chat 侧保留同名
# re-export）：dispatch metadata 中凭证明文键——持久化副本
# （SubAgentSession.last_output.dispatch.metadata）统一剔除，绝不落 DB。
# 重建（首派任务体 / 断连恢复）时按 ``_redacted_env_keys`` 标记由
# ``_rehydrate_dispatch_credentials`` 从权威源重解析补回：Git token / API key 直接
# 重解析；USER_TOKEN 仅当 metadata 带非敏感键 ``task_token_user_id`` 时按原发起用户
# 重铸（否则降级不挂知识工具，fail-soft）。
CREDENTIAL_ENV_KEYS: frozenset[str] = frozenset(
    {
        "env_FRIDAY_TASK_USER_TOKEN",
        "env_FRIDAY_TASK_GIT_ACCESS_TOKEN",
        "env_FRIDAY_TASK_CLAUDE_API_KEY",
    }
)

# 快照里整体剔除的非 env 凭证容器键：workflow 编码链的 nested ``git_credentials``
# （含 access_token 明文）只是历史零回归保留（runner 只读顶层 env_ 键、容器不消费），
# 落库即泄漏且重建不需要它 —— 快照直接丢弃，不进 ``_redacted_env_keys`` 标记
# （rehydrate 无需也不会补回，Git token 走顶层 env 键的重解析）。
_SNAPSHOT_DROP_KEYS: frozenset[str] = frozenset({"git_credentials"})

# 会话终态集合（与 runners.consumers._TERMINAL_STATUSES 同口径；字面量避免互相 import）。
TERMINAL_SESSION_STATUSES: frozenset[str] = frozenset(
    {"completed", "error", "timeout", "cancelled"}
)

# USER_TOKEN 重铸 TTL（秒）：与首派 dispatch_coding_task 的 3600 对齐。
_REMINT_TOKEN_TTL_SECONDS = 3600

# stranded 派发恢复扫描：滞留窗口与单轮扫描上界（形状照 blueprint_resume 的恢复扫描）。
_STRANDED_DISPATCH_MINUTES = 15
_STRANDED_DISPATCH_BATCH_LIMIT = 20


@dataclass
class DispatchTask:
    task_id: str
    task_type: str
    tags: list[str]
    image: str
    repo_url: str
    branch: str
    target_branch: str
    prompt: str
    timeout: int
    node_execution_id: str
    session_id: str
    metadata: dict = field(default_factory=dict)


def build_dispatch_snapshot(task: DispatchTask) -> dict:
    """DispatchTask → 可落库的 redacted 派发快照（``last_output["dispatch"]`` 的值）。

    唯一的「DispatchTask → 快照」实现：``chat.coding_session_service.dispatch_coding_task``
    的落库段与 ``TaskDispatcher.dispatch`` 的统一补齐都调本函数，⛔ 不留两份剔除逻辑。
    剔除 ``CREDENTIAL_ENV_KEYS`` 凭证明文键（记 ``_redacted_env_keys`` 标记供重建时
    重解析）与 ``_SNAPSHOT_DROP_KEYS``（runner 不消费的 nested 凭证容器）。
    ``image`` 不进快照：所有生产调用方恒传空串（runner 回退部署配置的默认镜像），
    重建时同样恒空，与断连恢复重建（consumers）的既有行为一致。
    """
    redacted_env_keys = sorted(CREDENTIAL_ENV_KEYS & task.metadata.keys())
    persisted_metadata = {
        k: v
        for k, v in task.metadata.items()
        if k not in CREDENTIAL_ENV_KEYS and k not in _SNAPSHOT_DROP_KEYS
    }
    if redacted_env_keys:
        persisted_metadata["_redacted_env_keys"] = redacted_env_keys
    return {
        "task_type": task.task_type,
        "tags": task.tags,
        "repo_url": task.repo_url,
        "branch": task.branch,
        "target_branch": task.target_branch,
        "prompt": task.prompt,
        "timeout": task.timeout,
        "node_execution_id": task.node_execution_id,
        "metadata": persisted_metadata,
    }


async def _rehydrate_dispatch_credentials(metadata: dict, session_id: str) -> dict:
    """重建前从权威源补回落库时剔除的凭证键（103 审查 WR-03；31u 移为模块级共享）。

    落库副本（last_output.dispatch.metadata）统一剔除 CREDENTIAL_ENV_KEYS 凭证
    明文键，剔除清单记在 ``_redacted_env_keys`` 标记里（见 ``build_dispatch_snapshot``）。
    首派任务体与断连恢复重建都按标记重解析：

    - env_FRIDAY_TASK_GIT_ACCESS_TOKEN：repository_id → ``aresolve_git_token``
      （与首派同一权威源），保证重建后 clone 行为与首派一致。
    - env_FRIDAY_TASK_CLAUDE_API_KEY：``aget_claude_code_runtime_config``
      （provider 配置权威源）。
    - env_FRIDAY_TASK_USER_TOKEN：**按 ``task_token_user_id`` 重铸**（31u）——派发经
      durable 队列后内存 metadata 不再直达容器，不重铸则编码/调研容器首派就挂不上
      知识工具。metadata 无该键（历史行 / 无触发用户降级链）→ 不重铸，容器降级不挂
      知识工具（fail-soft，与 user 不可解析降级语义一致）。

    best-effort：任一重解析失败只记 warning 跳过该键（容器对应能力降级），
    绝不阻断重建主流程。无标记（历史行）→ 原样返回。
    """
    redacted = metadata.pop("_redacted_env_keys", None)
    if not redacted:
        return metadata
    if "env_FRIDAY_TASK_GIT_ACCESS_TOKEN" in redacted and metadata.get("repository_id"):
        try:
            from repositories.models import Repository
            from services.git_credentials import aresolve_git_token

            repository = await Repository.objects.filter(id=metadata["repository_id"]).afirst()
            token = await aresolve_git_token(repository) if repository else ""
            if token:
                metadata["env_FRIDAY_TASK_GIT_ACCESS_TOKEN"] = token
        except Exception as exc:  # noqa: BLE001 — best-effort，失败降级不阻断重建
            logger.warning(
                "dispatch_credential_rehydrate_failed",
                session_id=session_id,
                key="git_access_token",
                error_type=type(exc).__name__,
                initiated_by_user_id="system",
                category="caller",
                component="runners",
            )
    if "env_FRIDAY_TASK_CLAUDE_API_KEY" in redacted:
        try:
            from services.provider_config import aget_claude_code_runtime_config

            cc = await aget_claude_code_runtime_config()
            if cc.get("api_key"):
                metadata["env_FRIDAY_TASK_CLAUDE_API_KEY"] = cc["api_key"]
        except Exception as exc:  # noqa: BLE001 — best-effort，失败降级不阻断重建
            logger.warning(
                "dispatch_credential_rehydrate_failed",
                session_id=session_id,
                key="claude_api_key",
                error_type=type(exc).__name__,
                initiated_by_user_id="system",
                category="caller",
                component="runners",
            )
    if "env_FRIDAY_TASK_USER_TOKEN" in redacted and metadata.get("task_token_user_id"):
        try:
            from access_tokens.services import mint_task_token
            from accounts.models import User

            user = await User.objects.filter(id=metadata["task_token_user_id"]).afirst()
            if user is not None:
                metadata["env_FRIDAY_TASK_USER_TOKEN"] = await mint_task_token(
                    user, session_id, _REMINT_TOKEN_TTL_SECONDS
                )
            else:
                logger.warning(
                    "dispatch_credential_rehydrate_failed",
                    session_id=session_id,
                    key="user_token",
                    error_type="user_not_found",
                    initiated_by_user_id="system",
                    category="caller",
                    component="runners",
                )
        except Exception as exc:  # noqa: BLE001 — 重铸失败 fail-soft 跳过该键（降级不挂知识工具）
            logger.warning(
                "dispatch_credential_rehydrate_failed",
                session_id=session_id,
                key="user_token",
                error_type=type(exc).__name__,
                initiated_by_user_id="system",
                category="caller",
                component="runners",
            )
    return metadata


async def arebuild_dispatch_task_from_session(
    session,
    *,
    fallback_tags: list[str] | None = None,
    require_snapshot: bool = True,
) -> DispatchTask | None:
    """从 ``session.last_output["dispatch"]`` 快照重建 DispatchTask（不绑 runner/assignment）。

    形状照断连恢复重建（consumers._rebuild_dispatch_task），供 durable 派发任务体
    首派 / 重派共用；consumers 侧也委托本实现（⛔ 不留拷贝）。

    Args:
        session: ``SubAgentSession`` 实例。
        fallback_tags: 快照无 tags 时的回退（断连恢复链传 runner.tags；首派链传 None）。
        require_snapshot: True（任务体）→ 快照缺失返回 None（理论不可达：``dispatch()``
            先持久化后入队）；False（断连恢复的历史行兼容）→ 用 session 字段兜底重建。
    """
    last_output = session.last_output if isinstance(session.last_output, dict) else {}
    dispatch_payload = last_output.get("dispatch")
    if require_snapshot and not isinstance(dispatch_payload, dict):
        return None
    dispatch = dispatch_payload if isinstance(dispatch_payload, dict) else {}
    metadata = await _rehydrate_dispatch_credentials(
        dict(dispatch.get("metadata") or {}), session.session_id
    )
    return DispatchTask(
        task_id=session.session_id,
        task_type=str(dispatch.get("task_type") or last_output.get("task_type") or "coding"),
        tags=list(dispatch.get("tags") or fallback_tags or []),
        image="",
        repo_url=str(dispatch.get("repo_url") or session.repo_url or ""),
        branch=str(dispatch.get("branch") or ""),
        target_branch=str(dispatch.get("target_branch") or ""),
        prompt=str(dispatch.get("prompt") or ""),
        timeout=int(dispatch.get("timeout") or 600),
        node_execution_id=str(dispatch.get("node_execution_id") or ""),
        session_id=session.session_id,
        metadata=metadata,
    )


def _context_initiator() -> str | None:
    """best-effort 从请求上下文取触发用户 id（中间件已 bind）；取不到返 None → worker 记 system。"""
    try:
        raw = str(structlog.contextvars.get_contextvars().get("user_id") or "").strip()
    except Exception:  # noqa: BLE001 — 取上下文绝不反噬派发
        return None
    return raw or None


class TaskDispatcher:
    """任务分发器 — 编码/调研/摘要等容器任务的唯一派发入口。

    ``dispatch()`` = 快照持久化 + defer durable 派发任务（「已受理」语义）；真正的
    标签匹配与 channels send 在 durable worker 的 ``_try_assign`` 执行。
    """

    def __init__(self) -> None:
        self._log = structlog.get_logger()

    async def dispatch(self, task: DispatchTask) -> None:
        """派发一次任务：① redacted 快照落库（DB 为真相源）② 入 durable 队列。

        ⛔ 不再先 ``_try_assign`` 内联试派——派发动作本身必须先持久化才谈得上可靠
        （内联试派成功但进程随后崩溃，与"内存队列丢任务"是同一失败面的两半）。

        ⛔ 不带 ``idempotency_key``：同 session 的合法重派发（rejected 重排 / 断连恢复 /
        stranded 扫描）不能被 todo 去重吃掉；防重的职责在任务体状态守卫（终态 /
        active assignment → no-op）。``lock=dispatch-{session_id}`` 使同 session 派发
        串行、守卫判据无并发窗口。

        defer / 快照落库抛异常时**向上抛**（既有调用方契约：``dispatch_coding_task``
        依赖异常触发任务 token 吊销）。
        """
        await self._apersist_snapshot(task)

        from durable.queues import QUEUE_DISPATCH
        from durable.service import DurableTaskService

        initiated = _context_initiator()
        job_id = await DurableTaskService.defer(
            "durable_runner_dispatch",
            {"session_id": task.session_id, "attempt": 0},
            queue=QUEUE_DISPATCH,
            lock=f"dispatch-{task.session_id}",
            initiated_by_user_id=initiated,
        )
        self._log.info(
            "runner_dispatch_enqueued",
            task_id=task.task_id,
            session_id=task.session_id,
            task_type=task.task_type,
            job_id=str(job_id),
            initiated_by_user_id=initiated or "system",
            category="caller",
            component="runners",
        )

    async def _apersist_snapshot(self, task: DispatchTask) -> None:
        """快照统一补齐：``last_output`` 尚无 ``"dispatch"`` 键时写入 redacted 快照。

        编码链已在 ``dispatch_coding_task`` 落过（逐字保留其行为）→ 跳过；
        非编码链（调研 / 摘要 / deep_analysis / repo_verify）此前不落快照，由此统一补齐
        —— durable 任务体只按快照重建，没有快照就没有可靠派发。
        """
        from subagent.models import SubAgentSession

        session = await SubAgentSession.objects.filter(session_id=task.session_id).afirst()
        if session is None:
            # 理论不可达：所有调用方都先建 session 再 dispatch。缺行时不落快照，
            # 任务体将按 not_found no-op，如实留痕。
            self._log.warning(
                "dispatch_snapshot_session_missing",
                task_id=task.task_id,
                session_id=task.session_id,
                category="caller",
                component="runners",
            )
            return
        last_output = session.last_output if isinstance(session.last_output, dict) else {}
        if isinstance(last_output.get("dispatch"), dict):
            return
        session.last_output = {**last_output, "dispatch": build_dispatch_snapshot(task)}
        await session.asave(update_fields=["last_output", "updated_at"])

    async def _try_assign(self, task: DispatchTask) -> bool:
        runners = await self._find_matching_runners(task.tags)
        if not runners:
            return False

        from tools.registry import RemoteToolRegistry

        remote_tools = await RemoteToolRegistry.aget_tools_payload()

        for runner in runners:
            if runner.current_tasks < runner.concurrent:
                # 幂等兜底：同一 session 已有 active(assigned/running) assignment 时
                # 不重复派发（多见于 WS 重连恢复 / 并发触发），避免起第二个容器导致
                # push non-fast-forward 冲突，也避免 current_tasks 被重复 +1。
                if await self._has_active_assignment(task.session_id):
                    self._log.info(
                        "dispatch_skipped_active_assignment",
                        task_id=task.task_id,
                        session_id=task.session_id,
                    )
                    return True
                channel_layer = get_channel_layer()
                await channel_layer.send(
                    runner.channel_name,
                    {
                        "type": "runner.message",
                        "message": make_request(
                            MessageType.TASK_ASSIGN,
                            {
                                "task_id": task.task_id,
                                "task_type": task.task_type,
                                "image": task.image,
                                "repo_url": task.repo_url,
                                "branch": task.branch,
                                "target_branch": task.target_branch,
                                "prompt": task.prompt,
                                "timeout": task.timeout,
                                "session_id": task.session_id,
                                "metadata": task.metadata,
                                "remote_tools": remote_tools,
                            },
                        ),
                    },
                )
                await self._increment_tasks(runner)
                await self._create_assignment(runner, task)
                self._log.info("task_dispatched", task_id=task.task_id, runner=str(runner.id))
                await channel_layer.group_send(
                    "runner_monitor",
                    {
                        "type": "monitor.event",
                        "data": {
                            "event": "task.status_changed",
                            "runner_id": str(runner.id),
                            "data": {
                                "task_id": task.task_id,
                                "session_id": task.session_id,
                                "status": "assigned",
                                "task_type": task.task_type,
                            },
                        },
                    },
                )
                await self._log_dispatch_event(runner, task)
                return True
        return False

    async def _find_matching_runners(self, tags: list[str]) -> list:
        from runners.models import Runner

        stale_threshold = timezone.now() - timedelta(seconds=HEARTBEAT_STALE_SECONDS)

        # 自动修正心跳超时但仍标记为 online 的 Runner
        await Runner.objects.filter(
            status="online",
            last_heartbeat__lt=stale_threshold,
        ).aupdate(status="offline", channel_name="")

        runners = [
            r
            async for r in Runner.objects.filter(
                status="online",
                is_active=True,
                is_paused=False,
            ).exclude(channel_name="")
        ]
        tag_set = set(tags)
        matched = [r for r in runners if tag_set.issubset(set(r.tags))]
        matched.sort(key=lambda r: r.current_tasks)
        return matched

    async def _increment_tasks(self, runner) -> None:
        from django.db import models as db_models

        from runners.models import Runner

        await Runner.objects.filter(id=runner.id).aupdate(
            current_tasks=db_models.F("current_tasks") + 1
        )

    async def _has_active_assignment(self, session_id: str) -> bool:
        """该 session 是否已有 assigned/running 的 assignment（派发幂等判据）。"""
        from runners.models import RunnerTaskAssignment

        return await RunnerTaskAssignment.objects.filter(
            session__session_id=session_id,
            status__in=[
                RunnerTaskAssignment.Status.ASSIGNED,
                RunnerTaskAssignment.Status.RUNNING,
            ],
        ).aexists()

    async def _create_assignment(self, runner: object, task: DispatchTask) -> None:
        from runners.models import RunnerTaskAssignment
        from subagent.models import SubAgentSession

        session = await SubAgentSession.objects.filter(session_id=task.session_id).afirst()
        if session:
            await RunnerTaskAssignment.objects.acreate(runner=runner, session=session)  # type: ignore[misc]
            session.runner = runner  # type: ignore[assignment]
            await session.asave(update_fields=["runner", "updated_at"])

    async def _log_dispatch_event(self, runner: object, task: DispatchTask) -> None:
        from runners.models import RunnerEvent

        await RunnerEvent.objects.acreate(
            runner=runner,  # type: ignore[misc]
            event_type="task_assigned",
            detail={"task_id": task.task_id, "session_id": task.session_id},
        )

    async def cancel(self, task_id: str) -> bool:
        """向 Runner 发送取消信号。通过 RunnerTaskAssignment 找到 Runner 的 channel。

        Returns:
            True 表示取消信号已发送，False 表示未找到 assignment。
        """
        from runners.models import RunnerTaskAssignment

        assignment = await (
            RunnerTaskAssignment.objects.filter(
                session__session_id=task_id,
                status__in=[
                    RunnerTaskAssignment.Status.ASSIGNED,
                    RunnerTaskAssignment.Status.RUNNING,
                ],
            )
            .select_related("runner")
            .afirst()
        )
        if not assignment or not assignment.runner.channel_name:
            self._log.warning("cancel_no_assignment", task_id=task_id)
            return False

        channel_layer = get_channel_layer()
        await channel_layer.send(
            assignment.runner.channel_name,
            {
                "type": "runner.message",
                "message": make_request(
                    MessageType.TASK_CANCEL,
                    {"task_id": task_id},
                ),
            },
        )
        self._log.info(
            "task_cancel_sent",
            task_id=task_id,
            runner_id=str(assignment.runner.id),
        )
        return True


_dispatcher: TaskDispatcher | None = None


def get_dispatcher() -> TaskDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = TaskDispatcher()
    return _dispatcher


# ── stranded 派发恢复扫描（apscheduler 保险丝）─────────────────────────────────


async def arecover_stranded_dispatch_sessions(*, now=None, limit: int = 0) -> dict:
    """扫描滞留的「待派发」会话并重新入队 durable 派发任务，返回恒定四键计数。

    定位是**保险丝而不是主路径**（只走 apscheduler、⛔ 不加 durable periodic）：
    procrastinate 路径的「无 runner 等待」已被任务体 re-defer backoff 全覆盖；唯一漏网
    是 in-process fallback（SQLite dev）重启丢 job，以及「入队成功但 job 链意外中断」
    的极端窗口——这正是 apscheduler 保险丝的定位（与 ``tasks/blueprint_recovery_tasks``
    完全同构，两个环境都跑）。

    判据与安全边界：

    - 扫描面：``status == PENDING`` 且 ``updated_at`` 早于 15 分钟且 ``last_output``
      含 ``"dispatch"`` 快照的 ``SubAgentSession``，按最旧优先取 ``limit`` 条。
    - **编码任务也纳入**（用户确认方向）：重派幂等由任务体状态守卫（终态 / active
      assignment → no-op）承担，不再像 ``recover_stranded_repo_summaries`` 那样以
      「防重复 commit」为由把 coding 排除在自动重派之外。
    - 逐条守卫复查（active assignment → 跳过）后 defer ``durable_runner_dispatch``
      （归因 ``system``）；单条 try/except 隔离 + 恒定计数返回，绝不打断 scheduler。

    Returns:
        ``{"scanned": n, "skipped_active": n, "requeued": n, "failed": n}``。
    """
    import time

    started = time.perf_counter()
    counts = {"scanned": 0, "skipped_active": 0, "requeued": 0, "failed": 0}
    try:
        from durable.queues import QUEUE_DISPATCH
        from durable.service import DurableTaskService
        from subagent.models import SubAgentSession

        moment = now or timezone.now()
        cutoff = moment - timedelta(minutes=_STRANDED_DISPATCH_MINUTES)
        batch = max(int(limit or 0), 0) or _STRANDED_DISPATCH_BATCH_LIMIT

        dispatcher = get_dispatcher()
        candidates = [
            session
            async for session in SubAgentSession.objects.filter(
                status=SubAgentSession.Status.PENDING,
                updated_at__lt=cutoff,
                last_output__has_key="dispatch",
            ).order_by("updated_at")[:batch]
        ]

        for session in candidates:
            counts["scanned"] += 1
            try:
                # 守卫复查：已派出 / 在跑的不重新入队（任务体还会再查一次，双保险）。
                if await dispatcher._has_active_assignment(session.session_id):
                    counts["skipped_active"] += 1
                    continue
                await DurableTaskService.defer(
                    "durable_runner_dispatch",
                    {"session_id": session.session_id, "attempt": 0},
                    queue=QUEUE_DISPATCH,
                    lock=f"dispatch-{session.session_id}",
                    initiated_by_user_id="system",
                )
                counts["requeued"] += 1
            except Exception as exc:  # noqa: BLE001 — 单条隔离，绝不打断整批
                counts["failed"] += 1
                from common.logging import redact_secrets_in_text

                logger.warning(
                    "stranded_dispatch_recover_failed",
                    category="caller",
                    component="runners",
                    initiated_by_user_id="system",
                    session_id=str(getattr(session, "session_id", "")),
                    error=redact_secrets_in_text(str(exc)),
                )
    except Exception as exc:  # noqa: BLE001 — 恢复整体 best-effort，绝不上抛
        from common.logging import redact_secrets_in_text

        logger.warning(
            "stranded_dispatch_recovery_failed",
            category="caller",
            component="runners",
            initiated_by_user_id="system",
            error=redact_secrets_in_text(str(exc)),
        )
        return counts

    logger.info(
        "stranded_dispatch_recovery_tick",
        category="caller",
        component="runners",
        initiated_by_user_id="system",
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
        **counts,
    )
    return counts
