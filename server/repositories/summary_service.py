"""仓库智能描述生成 dispatch 服务（initial implementation）。

提供 dispatch_repo_summary() 函数，创建 AgentSession + SubAgentSession，
构建 DispatchTask metadata 并通过 get_dispatcher().dispatch() 分发到 Runner。
"""

from __future__ import annotations

import re
import uuid

import structlog
from django.conf import settings

from agents.models import AgentSession
from prompts.keys import PromptSlugs
from prompts.services import render_prompt
from repositories.models import AISummaryStatus, Repository
from runners.dispatcher import DispatchTask, get_dispatcher
from subagent.models import SubAgentSession

logger = structlog.get_logger(__name__)

# fallback prompt — 当 DB 中 prompt 种子不可用时降级使用
REPO_SUMMARY_FALLBACK = """\
你是一个仓库分析助手。阅读仓库源码，输出结构化 JSON 描述。
只读操作，禁止写文件/git push/网络请求。输出不超过 2000 字符。
输出 JSON: {overview, tech_stack, modules, entry_points, build_commands, testing_commands, conventions}
"""


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

    sub_session = await SubAgentSession.objects.acreate(
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

    # 3. 渲染 prompt
    prompt = await render_prompt(
        PromptSlugs.REPO_SUMMARY_GENERATOR,
        fallback=REPO_SUMMARY_FALLBACK,
    )

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

    if (
        session.status == SubAgentSession.Status.RUNNING
        and repository.ai_summary_status == AISummaryStatus.PENDING
    ):
        repository.ai_summary_status = AISummaryStatus.RUNNING
        await repository.asave(update_fields=["ai_summary_status", "updated_at"])

    return repository


async def _build_env_metadata(repository: Repository) -> dict[str, str]:
    """构建 dispatch 所需的 metadata（参照 coding_session_service.build_dispatch_metadata）。"""
    from common.encryption import decrypt_value
    from repositories.models import GitCredential
    from services.provider_config import aget_legacy_anthropic_config

    # initial implementation plan（contract/contract）：SettingKeys.ANTHROPIC_* 硬删 → 走
    # ProviderCredential(scope=system, name=default, provider_type=anthropic)
    legacy = await aget_legacy_anthropic_config()
    api_key = legacy["api_key"]
    base_url = legacy["base_url"]
    system_model = legacy["default_model"]
    small_model = legacy["small_model"]

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

    # Git 凭据
    try:
        cred = await GitCredential.objects.aget(repository=repository)
        if cred.encrypted_token:
            token = decrypt_value(cred.encrypted_token)
            env_metadata["env_FRIDAY_TASK_GIT_ACCESS_TOKEN"] = token
            env_metadata["env_FRIDAY_TASK_GIT_AUTH_TYPE"] = "token"
            env_metadata["env_FRIDAY_TASK_GIT_SSL_VERIFY"] = "false"
    except GitCredential.DoesNotExist:
        pass

    return env_metadata
