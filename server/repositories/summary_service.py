"""仓库智能描述生成 dispatch 服务（implementation）。

提供 dispatch_repo_summary() 函数，创建 AgentSession + SubAgentSession，
构建 DispatchTask metadata 并通过 get_dispatcher().dispatch() 分发到 Runner。
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import structlog
from django.conf import settings
from django.utils import timezone

from agents.models import AgentSession
from prompts.keys import PromptSlugs
from prompts.services import render_prompt
from repositories.models import AISummaryStatus, Repository
from runners.dispatcher import DispatchTask, get_dispatcher
from subagent.models import SubAgentSession

logger = structlog.get_logger(__name__)

# fallback prompt — 当 DB 中 prompt 种子不可用时降级使用
REPO_SUMMARY_FALLBACK = """\
你是一个仓库分析助手。阅读仓库源码，生成层级能力树描述。
只读操作，禁止写文件/git push/网络请求。
tree 为扁平节点列表（node_id/parent_id/node_type/title/summary/keywords/paths）：
monorepo 第一层为 sub_app 节点；module 节点 paths 必须指向真实目录；
capability 叶子粒度为"一条需求能描述清楚的功能点"。树深 ≤4，总节点 ≤80。
其余字段: {overview, tech_stack, is_monorepo, entry_points, build_commands, testing_commands, conventions}
"""


# 语义分面固定维度（与前端知识树分面视角 FACET_VIEWS 对齐，键名必须一致）
SEMANTIC_FACET_DIMENSIONS = ("业务线/产品线", "服务对象", "技术形态")


async def _build_facet_vocab_section() -> str:
    """构建语义分面打标 prompt 注入段。

    - 有受控词表（FacetVocabulary）：打标只能从词表取值（防漂移）。
    - 无词表：降级为自由打标（开箱即用），维度固定、取值要求简短中文短语；
      历史上无词表时直接跳过打标，导致语义分面永远为空。
    """
    from repositories.models import FacetVocabulary

    vocabs = [v async for v in FacetVocabulary.objects.filter(is_active=True)]
    if not vocabs:
        dims = "、".join(SEMANTIC_FACET_DIMENSIONS)
        return "\n".join([
            "",
            "## 语义分面打标",
            "",
            f"在提交结果的 facets 字段中为仓库整体打标（{{维度: 取值}}），维度固定为：{dims}。",
            "取值用简短中文短语（≤10 字，如「在线教育」「C端学生」「移动端H5」）；判断不出填 \"未分类\"。",
            "",
        ])
    lines = [
        "",
        "## 分面词表（受控，打标只能从下列取值中选）",
        "",
    ]
    for vocab in vocabs:
        values = "、".join(str(v) for v in (vocab.values or []))
        lines.append(f"- {vocab.dimension}：{values}")
    lines.append("")
    lines.append("在提交结果的 facets 字段中为仓库整体打标：{维度: 取值}；选不出填 \"未分类\"。")
    return "\n".join(lines)


async def _is_empty_remote(repository: Repository) -> bool:
    """远端是否为零分支空仓（用于 dispatch 前 fail-fast）。

    探测失败（不可判定）一律返回 False（放行），绝不把鉴权/网络故障误判为空仓。
    """
    from repositories.views import build_authenticated_git_url
    from services.git_credentials import aremote_branch_count, aresolve_git_token

    token = await aresolve_git_token(repository)
    auth_url = (
        build_authenticated_git_url(repository.git_url, token)
        if token
        else repository.git_url
    )
    return await aremote_branch_count(auth_url) == 0


async def dispatch_repo_summary(repository: Repository) -> str:
    """构建 DispatchTask 并 dispatch 到 Runner。

    流程：
    1. 生成 session_id
    2. 创建 AgentSession (project=None) + SubAgentSession (REPO_SUMMARY)
    3. 构建 env_metadata（API key、Git 凭据、callback）
    4. 渲染 prompt
    5. 构建 DispatchTask 并分发
    6. 更新 repository.ai_summary_status → PENDING

    Args:
        repository: Repository 模型实例。

    Returns:
        sub_session 的 session_id 字符串。
    """
    # 空仓 fail-fast：零分支空仓没法生成描述，提前判定避免白白起容器烧 token。
    # ls-remote 探测失败（返回 -1）则放行走正常流程（绝不把不可判定误标为空仓）。
    if await _is_empty_remote(repository):
        repository.ai_summary_status = AISummaryStatus.FAILED
        repository.ai_summary_error = "仓库为空（远端无任何分支/提交），无可生成的描述。"
        await repository.asave(
            update_fields=["ai_summary_status", "ai_summary_error", "updated_at"]
        )
        logger.info("repo_summary_skipped_empty_repo", repository_id=str(repository.id))
        return ""

    session_id = f"reposummary-{uuid.uuid4().hex[:12]}"

    # 1. 创建 AgentSession + SubAgentSession
    agent_session = await AgentSession.objects.acreate(
        session_id=f"agent-{session_id}",
        space=None,
        status=AgentSession.Status.RUNNING,
        metadata={
            "source": "repo_summary",
            "repository_id": str(repository.id),
        },
    )

    await SubAgentSession.objects.acreate(
        session_id=session_id,
        main_session=agent_session,
        task_type=SubAgentSession.TaskType.REPO_SUMMARY,
        status=SubAgentSession.Status.PENDING,
        repo_url=repository.git_url,
        last_output={
            "source": "repo_summary",
            "repository_id": str(repository.id),
        },
    )

    # 2. 构建 env_metadata
    env_metadata = await _build_env_metadata(repository)

    # 3. 渲染 prompt（追加语义分面受控词表注入段）
    prompt = await render_prompt(
        PromptSlugs.REPO_SUMMARY_GENERATOR,
        fallback=REPO_SUMMARY_FALLBACK,
    )
    try:
        facet_section = await _build_facet_vocab_section()
    except Exception:  # noqa: BLE001 — 词表注入失败不阻塞描述生成
        logger.warning("facet_vocab_section_failed", exc_info=True)
        facet_section = ""
    if facet_section:
        prompt = f"{prompt}\n{facet_section}"

    # 4. 构建 DispatchTask 并分发
    dispatch_task = DispatchTask(
        task_id=session_id,
        task_type="repo_summary",
        tags=[],
        image="",
        repo_url=repository.git_url,
        branch=repository.default_branch,
        target_branch=repository.default_branch,
        prompt=prompt,
        timeout=600,
        node_execution_id="",
        session_id=session_id,
        metadata=env_metadata,
    )

    await get_dispatcher().dispatch(dispatch_task)

    # 5. 更新 repository 状态
    repository.ai_summary_status = AISummaryStatus.PENDING
    await repository.asave(update_fields=["ai_summary_status", "updated_at"])

    logger.info(
        "repo_summary_dispatched",
        repository_id=str(repository.id),
        session_id=session_id,
    )

    return session_id


async def enqueue_repo_summary(repository_id: str) -> str | None:
    """把 repo_summary 派发收进 durable 队列（替代 fire-and-forget run_in_background）。

    durable job 只负责"可靠地发起一次派发"（job 体内调用 ``dispatch_repo_summary``），
    重活仍在 Runner 容器执行。相比 ``run_in_background``：

    - **不丢**：job 落 Postgres，server/worker 重启后仍会被消费；
    - **幂等**：``idempotency_key=f"summary:{repo_id}"`` 保证同仓在途只一份；
    - **平滑**：``summary-slot`` 槽位锁限制并发派发，避免批量建仓 session 创建洪峰。

    返回 durable job id（失败返回 None，不抛——建仓 best-effort 不阻塞）。
    """
    from durable.concurrency import asummary_lock
    from durable.queues import QUEUE_REPO_SUMMARY
    from durable.service import DurableTaskService

    try:
        lock = await asummary_lock(str(repository_id))
        return await DurableTaskService.defer(
            "durable_repo_summary",
            {"repository_id": str(repository_id)},
            queue=QUEUE_REPO_SUMMARY,
            idempotency_key=f"summary:{repository_id}",
            lock=lock,
        )
    except Exception:  # noqa: BLE001 — 入队失败不阻塞建仓/触发；recover 兜底
        logger.warning("enqueue_repo_summary_failed", repository_id=str(repository_id), exc_info=True)
        return None


_TERMINAL_FAIL_STATUSES = frozenset({
    SubAgentSession.Status.ERROR,
    SubAgentSession.Status.TIMEOUT,
    SubAgentSession.Status.CANCELLED,
})

# PENDING 且从未被 Runner 接收的会话超过该时长即判定为「派发丢失」。
# 根因：dispatcher 的 _pending 是进程内存队列，server 重启（dev --reload /
# 部署）会清空队列，但 SubAgentSession 停留在非终态 PENDING，UI 永远「排队中」。
_STALE_PENDING_MINUTES = 10

# 搁浅判定阈值（recover 周期任务用）：pending/running 会话超过该时长「无进展」
# （updated_at 陈旧）即视为派发丢失（容器死亡 / Runner 重启 / server 重启清空内存
# 队列）。比 dispatch timeout（600s）留足余量，避免误杀仍在跑的慢任务。
# 注意：此处用 updated_at 陈旧度判定，**不依赖 runner_id 是否为空** —— 历史 reconcile
# 仅救 runner_id is None 的孤儿，漏掉了「已分配但容器从未真正执行」（runner_id 已设）
# 的那批，导致它们永卡 pending；本恢复机制据 updated_at 兜底，两类都能自愈。
_STRANDED_MINUTES = 15

# 单轮 recover sweep 最多重派的仓库数：防止一次性把数百个搁浅任务全灌进队列，
# 配合 5 分钟周期逐步 ramp（尤其上游 LLM 有速率上限时更平滑）。
_RECOVER_MAX_PER_SWEEP = 50

# RUNNING 会话的硬超时（分钟）：基于 started_at（而非 updated_at）的绝对上限。
# 关键：repo_summary 容器会持续回传 progress/log 刷新 updated_at，单靠 updated_at
# 陈旧判定永远抓不到「容器还活着但实际已僵死」的任务。DispatchTask.timeout=600s
# （10min），这里取 20min 留足余量，超出即判定僵死、收敛重派。
_RUNNING_HARD_TIMEOUT_MINUTES = 20


async def _available_repo_summary_runner_slots() -> int:
    """计算当前可直接派发 repo_summary 的 runner 空槽数。

    repo_summary 任务当前仍经 ``TaskDispatcher`` 派发；当 durable worker 一次重派数量
    超过 runner 空槽时，超出的任务会进入 worker 进程自己的 ``_pending`` 内存队列，
    无法被 server 进程的完成回调续派。因此 recover sweep 必须只创建能够立刻投出的
    session，剩余仓库等下一轮 durable sweep。
    """
    from runners.dispatcher import HEARTBEAT_STALE_SECONDS
    from runners.models import Runner, RunnerTaskAssignment

    stale_threshold = timezone.now() - timedelta(seconds=HEARTBEAT_STALE_SECONDS)
    slots = 0
    async for runner in Runner.objects.filter(
        status=Runner.Status.ONLINE,
        is_active=True,
        is_paused=False,
        last_heartbeat__gte=stale_threshold,
    ).exclude(channel_name=""):
        active_assignments = await RunnerTaskAssignment.objects.filter(
            runner=runner,
            status__in=[
                RunnerTaskAssignment.Status.ASSIGNED,
                RunnerTaskAssignment.Status.RUNNING,
            ],
        ).acount()
        occupied = max(int(runner.current_tasks), active_assignments)
        slots += max(int(runner.concurrent) - occupied, 0)
    return slots


async def reconcile_ai_summary_status(repository: Repository) -> Repository:
    """将 Repository.ai_summary_status 与最新 REPO_SUMMARY SubAgentSession 对齐。

    Runner WebSocket 失败路径历史上未写回 Repository，会导致 ai_summary_status
    长期停留在 pending。summary-status / generate-summary 调用前先 reconcile。
    """
    if repository.ai_summary_status not in (
        AISummaryStatus.PENDING,
        AISummaryStatus.RUNNING,
    ):
        return repository

    from subagent.api.callbacks import (
        _update_repository_on_summary_complete,
        _update_repository_on_summary_fail,
    )
    from subagent.models import SubAgentSession, TaskResult

    session = await (
        SubAgentSession.objects.filter(
            task_type=SubAgentSession.TaskType.REPO_SUMMARY,
            last_output__repository_id=str(repository.id),
        )
        .order_by("-created_at")
        .afirst()
    )
    if session is None:
        return repository

    if session.status == SubAgentSession.Status.COMPLETED:
        task_result = await TaskResult.objects.filter(session=session).afirst()
        if task_result is not None:
            await _update_repository_on_summary_complete(
                session,
                {
                    "result_type": task_result.result_type,
                    "output": task_result.raw_output
                    or {"text": task_result.text_output},
                },
            )
            await repository.arefresh_from_db()
        return repository

    if session.status in _TERMINAL_FAIL_STATUSES:
        error_msg = session.failure_reason or "AI 描述生成失败"
        await _update_repository_on_summary_fail(session, error_msg)
        await repository.arefresh_from_db()
        return repository

    # 陈旧 PENDING 兜底：派发后长时间无 Runner 接收（runner 为空），任务已随
    # server 重启从内存队列丢失，永远不会再被执行——收敛为 TIMEOUT 终态，
    # 解锁 UI 的「重新生成」按钮。
    if (
        session.status == SubAgentSession.Status.PENDING
        and session.runner_id is None
        and session.created_at
        < timezone.now() - timedelta(minutes=_STALE_PENDING_MINUTES)
    ):
        error_msg = (
            f"任务派发后超过 {_STALE_PENDING_MINUTES} 分钟未被 Runner 接收"
            "（Runner 离线或服务重启导致派发丢失），请重试。"
        )
        session.status = SubAgentSession.Status.TIMEOUT
        session.failure_reason = error_msg
        await session.asave(update_fields=["status", "failure_reason", "updated_at"])
        await _update_repository_on_summary_fail(session, error_msg)
        await repository.arefresh_from_db()
        return repository

    if (
        session.status == SubAgentSession.Status.RUNNING
        and repository.ai_summary_status == AISummaryStatus.PENDING
    ):
        repository.ai_summary_status = AISummaryStatus.RUNNING
        await repository.asave(update_fields=["ai_summary_status", "updated_at"])

    return repository


# ── AI 描述状态唯一真相派生（架构根治）────────────────────────────────────────
# 背景：Repository.ai_summary_status 历史上是把「真实状态」抄一份存进仓库表，由多个
# 写入方（dispatch→pending / WS accepted→running / 回调→completed,failed / recover 批量
# timeout）各自维护。但写 session 终态的人与写仓库列的人不是同一个，且容器回调有终态
# 门禁（session 已 timeout 时拒绝 completed/failed 回调 → _update_repository_on_summary_*
# 永不执行）——store-and-trust 必然漂移出「幻影 running」（仓库显示生成中，实际无 session
# 在跑、零 token）。根治：仓库列退化为「可自愈缓存」，所有展示读取都经下列 helper 从
# **最新 REPO_SUMMARY SubAgentSession** 派生，读时对齐。这样任何写回缺失/竞态都不再
# 造成对外撒谎，下一次读即纠正。
_SESSION_STATUS_TO_SUMMARY: dict[str, str] = {
    SubAgentSession.Status.COMPLETED: AISummaryStatus.COMPLETED,
    SubAgentSession.Status.ERROR: AISummaryStatus.FAILED,
    SubAgentSession.Status.TIMEOUT: AISummaryStatus.FAILED,
    SubAgentSession.Status.CANCELLED: AISummaryStatus.FAILED,
    SubAgentSession.Status.RUNNING: AISummaryStatus.RUNNING,
    SubAgentSession.Status.PENDING: AISummaryStatus.PENDING,
}


def derive_summary_status(session_status: str) -> str | None:
    """把 SubAgentSession 生命周期状态映射为 AI 描述状态（唯一真相侧）。

    未知/无法映射返回 None（调用方回退仓库现存列）。
    """
    return _SESSION_STATUS_TO_SUMMARY.get(session_status)


async def cancel_repo_summary(
    repository_id: str, *, initiated_by_user_id: str | None = None
) -> int:
    """终止仓库"建立知识"任务：标记在途 REPO_SUMMARY session 为 cancelled 并回退状态。

    建立知识在 Runner 容器内执行，无本地后台线程可中断；这里把权威真相侧（在途
    session）标记 cancelled —— 容器回调有终态门禁（callbacks.py），cancelled 后即便
    容器最终回调也不会把状态翻回。仓库 ``ai_summary_status`` 回退为 NOT_STARTED，
    便于用户重新触发。

    Args:
        repository_id: 仓库 ID。
        initiated_by_user_id: 触发终止的用户（system 行为传 None）。

    Returns:
        被标记 cancelled 的 session 数量。
    """
    log = logger.bind(
        category="caller",
        component="task_center",
        repository_id=str(repository_id),
        initiated_by_user_id=initiated_by_user_id or "system",
    )
    log.info("repo_summary_cancel_started")
    sessions = [
        s
        async for s in SubAgentSession.objects.filter(
            task_type=SubAgentSession.TaskType.REPO_SUMMARY,
            last_output__repository_id=str(repository_id),
            status__in=[
                SubAgentSession.Status.PENDING,
                SubAgentSession.Status.RUNNING,
            ],
        )
    ]
    for session in sessions:
        try:
            await session.amark_cancelled()
        except Exception:  # noqa: BLE001 — best-effort，单条失败不阻塞其余
            log.warning("repo_summary_cancel_session_failed", session_id=session.session_id, exc_info=True)

    await Repository.objects.filter(id=repository_id).aupdate(
        ai_summary_status=AISummaryStatus.NOT_STARTED,
        updated_at=timezone.now(),
    )
    log.info("repo_summary_cancel_completed", cancelled_count=len(sessions))
    return len(sessions)


async def aresolve_summary_status(repository: Repository) -> str:
    """从最新 REPO_SUMMARY session 派生权威 AI 描述状态，并自愈仓库缓存列。

    - 有最新 session → 以其生命周期为准；与仓库缓存不一致时写回（reconcile-on-read，
      **非巡检**：只在被读取的那一刻、对被读取的那个仓库对齐）。派生为 completed 时走
      完整内容回填（ai_summary / 能力树），而不仅翻状态。
    - 无 session → 回退仓库现存列（NOT_STARTED / 历史 completed 等）。

    Returns:
        权威 AI 描述状态字符串（AISummaryStatus 取值）。
    """
    session = await (
        SubAgentSession.objects.filter(
            task_type=SubAgentSession.TaskType.REPO_SUMMARY,
            last_output__repository_id=str(repository.id),
        )
        .order_by("-created_at")
        .afirst()
    )
    if session is None:
        return repository.ai_summary_status

    derived = derive_summary_status(session.status)
    if derived is None or derived == repository.ai_summary_status:
        return repository.ai_summary_status

    # completed：回填内容（ai_summary/tree），不只翻状态。直接走完成回写而非
    # reconcile_ai_summary_status——后者有「仅 pending/running 才处理」前置门禁，
    # 当仓库缓存误停在 failed 时会短路，无法纠正。
    if derived == AISummaryStatus.COMPLETED:
        from subagent.api.callbacks import _update_repository_on_summary_complete
        from subagent.models import TaskResult

        task_result = await TaskResult.objects.filter(session=session).afirst()
        if task_result is not None:
            await _update_repository_on_summary_complete(
                session,
                {
                    "result_type": task_result.result_type,
                    "output": task_result.raw_output or {"text": task_result.text_output},
                },
            )
            await repository.arefresh_from_db()
            return repository.ai_summary_status
        repository.ai_summary_status = AISummaryStatus.COMPLETED
        await repository.asave(update_fields=["ai_summary_status", "updated_at"])
        return AISummaryStatus.COMPLETED

    # running / pending / failed：直接自愈缓存列。
    repository.ai_summary_status = derived
    update_fields = ["ai_summary_status", "updated_at"]
    if derived == AISummaryStatus.FAILED and not repository.ai_summary_error:
        repository.ai_summary_error = (
            session.failure_reason or session.last_error or "AI 描述生成失败"
        )[:2000]
        update_fields.append("ai_summary_error")
    await repository.asave(update_fields=update_fields)
    return derived


async def recover_stranded_summaries(limit: int = _RECOVER_MAX_PER_SWEEP) -> int:
    """重派搁浅的 repo_summary 会话（durable 周期任务调用，修复派发丢失缺口）。

    背景（架构缺口）
    ================
    index/graph 已迁到 durable（Postgres Procrastinate，重启不丢），但 summary/coding
    仍走 ``runners.dispatcher.TaskDispatcher`` 的**进程内存队列**（``_pending``，非
    durable）。server / runner 重启会清空该队列，而 ``SubAgentSession`` 停留在
    ``pending`` / ``running`` 永不再被执行 —— UI 永远「排队中」。历史 reconcile 仅救
    ``runner_id is None`` 的孤儿，漏掉了「已分配但容器从未真正执行」（runner_id 已设）
    的那批，导致它们**永久卡死**。

    本函数作为 durable 兜底安全网：扫描超过 ``_STRANDED_MINUTES`` 无进展（updated_at
    陈旧）的 ``pending`` / ``running`` repo_summary 会话，对其对应仓库**重新派发**。

    安全边界
    ========
    - **只覆盖 repo_summary**（只读分析，可安全无限重试）；**coding 不在此自动重派**
      —— coding 会建分支 / 推 commit，盲目重试可能产生重复提交，必须人工介入。
    - 幂等：① ``dispatcher._has_active_assignment`` 防同会话重复派发；② 每仓只取最新
      一条、重派前把该仓所有未终态旧会话标 TIMEOUT，再起新会话（updated_at 刷新，下个
      周期 ``_STRANDED_MINUTES`` 内不会再被触碰）；③ 调用方周期任务自身 queueing_lock
      防并发重入；④ ``limit`` 每轮上限，逐步 ramp 不打爆。

    Args:
        limit: 单轮最多重派的仓库数（默认 ``_RECOVER_MAX_PER_SWEEP``）。

    Returns:
        本轮重新派发的仓库数量。
    """
    now = timezone.now()
    cutoff = now - timedelta(minutes=_STRANDED_MINUTES)
    hard_cutoff = now - timedelta(minutes=_RUNNING_HARD_TIMEOUT_MINUTES)
    available_slots = await _available_repo_summary_runner_slots()
    if available_slots <= 0:
        logger.info("repo_summary_recover_skipped_no_runner_capacity")
        return 0
    limit = min(limit, available_slots)
    recovered = 0
    seen_repos: set[str] = set()

    from django.db.models import Q

    async def _timeout_sessions(session_ids: list[int], reason: str) -> int:
        """将搁浅 summary session 与其 active assignment 一起收敛到终态。"""
        if not session_ids:
            return 0
        from runners.models import RunnerTaskAssignment

        terminal_at = timezone.now()
        count = await SubAgentSession.objects.filter(id__in=session_ids).aupdate(
            status=SubAgentSession.Status.TIMEOUT,
            failure_reason=reason,
            completed_at=terminal_at,
        )
        await RunnerTaskAssignment.objects.filter(
            session_id__in=session_ids,
            status__in=[
                RunnerTaskAssignment.Status.ASSIGNED,
                RunnerTaskAssignment.Status.RUNNING,
            ],
        ).aupdate(
            status=RunnerTaskAssignment.Status.FAILED,
            completed_at=terminal_at,
        )
        return count

    # 两类搁浅：
    # 1) PENDING 且 updated_at 陈旧（派发丢失 / 长时间未被 Runner 接收）；
    # 2) RUNNING 且 started_at 超过硬超时。RUNNING 不能再用普通 updated_at 陈旧判定：
    #    repo_summary 容器不保证刷新 SubAgentSession.updated_at，过早判定会误杀仍在跑的任务。
    stranded = (
        SubAgentSession.objects.filter(
            task_type=SubAgentSession.TaskType.REPO_SUMMARY,
            status__in=[
                SubAgentSession.Status.PENDING,
                SubAgentSession.Status.RUNNING,
            ],
        )
        .filter(
            Q(status=SubAgentSession.Status.PENDING, updated_at__lt=cutoff)
            | Q(
                status=SubAgentSession.Status.RUNNING,
                started_at__isnull=False,
                started_at__lt=hard_cutoff,
            )
            | Q(
                status=SubAgentSession.Status.RUNNING,
                started_at__isnull=True,
                updated_at__lt=hard_cutoff,
            )
        )
        .order_by("-created_at")
    )

    async for session in stranded:
        if recovered >= limit:
            break
        raw = session.last_output if isinstance(session.last_output, dict) else {}
        repo_id = raw.get("repository_id")
        if not repo_id or repo_id in seen_repos:
            continue
        seen_repos.add(repo_id)

        latest_active = await (
            SubAgentSession.objects.filter(
                task_type=SubAgentSession.TaskType.REPO_SUMMARY,
                last_output__repository_id=repo_id,
                status__in=[
                    SubAgentSession.Status.PENDING,
                    SubAgentSession.Status.RUNNING,
                ],
            )
            .order_by("-created_at")
            .afirst()
        )
        if latest_active is not None and latest_active.id != session.id:
            await _timeout_sessions(
                [session.id],
                "旧搁浅会话已被更新的在途会话取代",
            )
            logger.info(
                "repo_summary_old_stranded_session_closed",
                repository_id=repo_id,
                session_id=session.session_id,
                latest_session_id=latest_active.session_id,
            )
            continue

        repo = await Repository.objects.filter(id=repo_id, is_deleted=False).afirst()
        if repo is None:
            # 仓库已删：收尾搁浅会话，避免僵尸 pending 永久残留。
            deleted_ids = [
                s.id
                async for s in SubAgentSession.objects.filter(
                    task_type=SubAgentSession.TaskType.REPO_SUMMARY,
                    last_output__repository_id=repo_id,
                    status__in=[
                        SubAgentSession.Status.PENDING,
                        SubAgentSession.Status.RUNNING,
                    ],
                ).only("id")
            ]
            await _timeout_sessions(
                deleted_ids,
                "仓库已删除，搁浅会话收尾",
            )
            continue

        # 已完成 / 真实失败的仓库无需恢复（失败是执行后的真实结果，不应被无限重试）。
        if repo.ai_summary_status not in (
            AISummaryStatus.PENDING,
            AISummaryStatus.RUNNING,
        ):
            continue

        # 把该仓截至当前搁浅会话为止的未终态旧会话标 TIMEOUT（不调
        # _update_repository_on_summary_fail，避免把仓库误置 failed —— 随后
        # dispatch_repo_summary 会重新置 PENDING），再重新派发出一个全新会话。
        # 使用 created_at__lte 防竞态：如果本轮扫描后已有更新会话被创建，不会误杀它。
        old_ids = [
            s.id
            async for s in SubAgentSession.objects.filter(
                task_type=SubAgentSession.TaskType.REPO_SUMMARY,
                last_output__repository_id=repo_id,
                created_at__lte=session.created_at,
                status__in=[
                    SubAgentSession.Status.PENDING,
                    SubAgentSession.Status.RUNNING,
                ],
            ).only("id")
        ]
        await _timeout_sessions(
            old_ids,
            "搁浅重派（容器死亡 / Runner 重启导致派发丢失）",
        )

        try:
            await dispatch_repo_summary(repo)
            recovered += 1
            logger.info("repo_summary_recovered", repository_id=repo_id)
        except Exception:  # noqa: BLE001 — 单仓失败隔离，不阻断其余恢复
            logger.warning(
                "repo_summary_recover_failed", repository_id=repo_id, exc_info=True
            )

    if recovered:
        logger.info("repo_summary_recover_sweep", recovered=recovered)
    return recovered


async def _build_env_metadata(repository: Repository) -> dict[str, str]:
    """构建 dispatch 所需的 metadata（参照 coding_session_service.build_dispatch_metadata）。"""
    from services.git_credentials import aresolve_git_token
    from services.provider_config import aget_claude_code_runtime_config

    # Claude Code 任务容器统一凭证来源：优先读「Claude Code 编码配置」
    # （选定凭证 + opus/sonnet/haiku 三档映射）；未配置 credential_id 时
    # runtime_config 内部回退系统默认 anthropic 凭证（legacy 行为）。
    cc = await aget_claude_code_runtime_config()
    api_key = cc["api_key"]
    base_url = cc["base_url"]
    system_model = cc["default_model"]
    small_model = cc["haiku_model"]

    env_metadata: dict[str, str] = {
        "repository_id": str(repository.id),
        "env_FRIDAY_TASK_MODE": "repo_summary",
        "env_FRIDAY_TASK_CLAUDE_API_KEY": api_key,
        "env_FRIDAY_TASK_CLAUDE_BASE_URL": base_url,
        "env_FRIDAY_TASK_CLAUDE_MODEL": system_model,
        "env_FRIDAY_TASK_CLAUDE_SMALL_MODEL": small_model,
    }

    # Callback URL/Token
    friday_base_url = getattr(settings, "FRIDAY_BASE_URL", "")
    callback_token = getattr(settings, "CONTAINER_CALLBACK_TOKEN", "")
    if friday_base_url:
        env_metadata["env_FRIDAY_CALLBACK_URL"] = friday_base_url
    if callback_token:
        env_metadata["env_FRIDAY_CALLBACK_TOKEN"] = callback_token

    # Git 凭据：经统一解析器取 token（per-repo 优先 → host 实例池 fallback，D-02）
    token = await aresolve_git_token(repository)
    if token:
        env_metadata["env_FRIDAY_TASK_GIT_ACCESS_TOKEN"] = token
        env_metadata["env_FRIDAY_TASK_GIT_AUTH_TYPE"] = "token"
        env_metadata["env_FRIDAY_TASK_GIT_SSL_VERIFY"] = "false"

    return env_metadata
