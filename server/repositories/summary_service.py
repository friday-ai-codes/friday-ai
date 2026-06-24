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
    session_id = f"reposummary-{uuid.uuid4().hex[:12]}"

    # 1. 创建 AgentSession + SubAgentSession
    agent_session = await AgentSession.objects.acreate(
        session_id=f"agent-{session_id}",
        project=None,
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
    cutoff = timezone.now() - timedelta(minutes=_STRANDED_MINUTES)
    recovered = 0
    seen_repos: set[str] = set()

    stranded = SubAgentSession.objects.filter(
        task_type=SubAgentSession.TaskType.REPO_SUMMARY,
        status__in=[
            SubAgentSession.Status.PENDING,
            SubAgentSession.Status.RUNNING,
        ],
        updated_at__lt=cutoff,
    ).order_by("-created_at")

    async for session in stranded:
        if recovered >= limit:
            break
        raw = session.last_output if isinstance(session.last_output, dict) else {}
        repo_id = raw.get("repository_id")
        if not repo_id or repo_id in seen_repos:
            continue
        seen_repos.add(repo_id)

        repo = await Repository.objects.filter(id=repo_id, is_deleted=False).afirst()
        if repo is None:
            # 仓库已删：收尾搁浅会话，避免僵尸 pending 永久残留。
            await SubAgentSession.objects.filter(
                task_type=SubAgentSession.TaskType.REPO_SUMMARY,
                last_output__repository_id=repo_id,
                status__in=[
                    SubAgentSession.Status.PENDING,
                    SubAgentSession.Status.RUNNING,
                ],
            ).aupdate(
                status=SubAgentSession.Status.TIMEOUT,
                failure_reason="仓库已删除，搁浅会话收尾",
            )
            continue

        # 已完成 / 真实失败的仓库无需恢复（失败是执行后的真实结果，不应被无限重试）。
        if repo.ai_summary_status not in (
            AISummaryStatus.PENDING,
            AISummaryStatus.RUNNING,
        ):
            continue

        # 把该仓所有未终态旧会话标 TIMEOUT（不调 _update_repository_on_summary_fail，
        # 避免把仓库误置 failed —— 随后 dispatch_repo_summary 会重新置 PENDING），
        # 再重新派发出一个全新会话。
        await SubAgentSession.objects.filter(
            task_type=SubAgentSession.TaskType.REPO_SUMMARY,
            last_output__repository_id=repo_id,
            status__in=[
                SubAgentSession.Status.PENDING,
                SubAgentSession.Status.RUNNING,
            ],
        ).aupdate(
            status=SubAgentSession.Status.TIMEOUT,
            failure_reason="搁浅重派（容器死亡 / Runner 重启导致派发丢失）",
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
