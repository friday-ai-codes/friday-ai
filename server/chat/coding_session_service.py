"""CodingSession dispatch service -- 从 CodingSessionConfirmView 提取的共享逻辑。

提供 check_runner_online / build_dispatch_metadata / create_sub_session / dispatch_coding_task
四个 async 函数，供 CodingSessionConfirmView 和后续 CodingSession graph 节点复用。

追加 `create_sessions_for_plan` 批量创建业务函数，
封装 per-repo 校验 + 独立事务 + 失败收集语义。
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid as uuid_mod
from dataclasses import dataclass, field
from datetime import timedelta
from string import Template
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog
from asgiref.sync import sync_to_async
from django.db import IntegrityError, transaction

from chat.models import CodingPlanProvenance, CodingSession

if TYPE_CHECKING:
    from chat.models import CodingPlan

logger = structlog.get_logger(__name__)

# ----------------------------------------------------------------------------
# implementation / active 状态枚举常量
# 与 chat.models.CodingSession.Meta.constraints.unique_active_plan_repo 字面一致。
# ----------------------------------------------------------------------------
ACTIVE_STATUSES: frozenset[str] = frozenset(
    {
        CodingSession.Status.DRAFT,
        CodingSession.Status.CONFIRMED,
        CodingSession.Status.RUNNING,
        CodingSession.Status.AWAITING_CONFIRMATION,
    }
)

# 共享 error 文案常量，避免 service / view / 兼容性命令多处硬编码漂移。
ERROR_REPO_ACTIVE_BUSY = "该仓库已有进行中的编码会话"

# RELY-01 草稿送编码防护（fail-closed 在服务端）。
# `code` 是给客户端分支用的**稳定机器码**：前端按 code 判定、绝不匹配 detail 文案，
# 否则一次文案微调就让前端的错误分支静默失效。两个常量放在此处而非 view 内，
# 避免 service / view / 测试三处各写一份字面量后漂移。
ERROR_CODE_DRAFT_REQUIRES_CONFIRM = "draft_requires_explicit_confirm"
ERROR_DRAFT_REQUIRES_CONFIRM = "草稿方案需显式确认后才能送编码"

# 落库脱敏键名单（103 审查 WR-03）：31u 起唯一定义点迁到 ``runners.dispatcher``
# （快照剔除与重建 rehydrate 同处一模块），此处保留同名 re-export 维持既有
# ``from chat.coding_session_service import CREDENTIAL_ENV_KEYS`` 调用方零改动。
# chat→runners 方向 import 无循环（runners.dispatcher 顶层不 import chat）。
from runners.dispatcher import CREDENTIAL_ENV_KEYS  # noqa: E402, F401  — re-export


class DraftPlanRequiresConfirmError(Exception):
    """草稿方案未经显式确认就尝试送编码（RELY-01 服务端 gate）。

    由 `create_sessions_for_plan` 在**创建任何 session 之前**抛出，调用方（fan-out
    视图）据 `code` 映射为 400 响应。异常而非返回值：gate 的语义是「整批拒绝、DB 零
    写入」，塞进 `CodingSessionsBatchResult.failed` 会让它看起来像 per-repo 失败，
    调用方可能继续往下走。
    """

    code = ERROR_CODE_DRAFT_REQUIRES_CONFIRM

    def __init__(self, message: str = ERROR_DRAFT_REQUIRES_CONFIRM) -> None:
        super().__init__(message)


def _plan_requires_unresearched_confirm(plan: CodingPlan) -> bool:
    """该 plan 送编码是否需要显式确认。

    判定采**允许清单**：只有 `provenance == orchestrated` 免确认，`draft` / 未知取值 /
    空值一律按需确认。用拒绝清单（`== draft` 才拦）会让任何新增来源枚举值默认放行，
    与前端保守默认（UI-SPEC §B.1）口径也不一致。
    """
    provenance = str(getattr(plan, "provenance", "") or "")
    return provenance != CodingPlanProvenance.ORCHESTRATED


def _context_user_id() -> str:
    """从请求 / 任务上下文取触发用户 id；取不到记 `system`。"""
    try:
        raw = str(structlog.contextvars.get_contextvars().get("user_id") or "").strip()
    except Exception:  # noqa: BLE001 — 取上下文绝不反噬业务
        return "system"
    return raw or "system"


def _log_draft_coding_gate(
    *,
    event: str,
    plan_id: str,
    repo_count: int | None = None,
    reason: str = "",
    actor_user_id: str = "",
) -> None:
    """草稿送编码的确认 / 拒绝留痕（best-effort，绝不反噬业务）。

    两条路径都要留痕：只记拒绝会让「谁在什么时候用草稿送了编码」不可追溯（RELY-01
    的 Repudiation 面）。字段无凭证、无正文，无脱敏义务。

    ``actor_user_id`` 优先于 contextvars（109-REVIEW MN-06）：fan-out 视图手上就有
    ``request.user``，显式传比绕一圈 contextvars 更可靠 —— 后者一旦哪个入口漏绑，
    这条审计线就会静默退化成 ``system``，而它正是「草稿是有防护的应急路径」这个
    设计里唯一的问责凭据。
    """
    try:
        fields: dict[str, Any] = {
            "category": "caller",
            "component": "chat",
            "coding_plan_id": plan_id,
            "user_id": str(actor_user_id or "").strip() or _context_user_id(),
        }
        if repo_count is not None:
            fields["repo_count"] = repo_count
        if reason:
            fields["reason"] = reason
        logger.warning(event, **fields)
    except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬业务
        pass


@dataclass(frozen=True)
class CodingExecutionSpec:
    """编码任务下发给 Runner/容器的结构化执行契约。"""

    repository_id: str
    repository_name: str
    repo_url: str
    base_branch: str
    work_branch: str
    target_branch: str
    affected_files: list[dict[str, Any]]
    # 该方案未经完整编排调研（`CodingPlan.provenance != orchestrated`），下游容器可据
    # 此调整策略（本 phase 只保证标志出现在 dispatch payload 里，容器侧消费与否留后续）。
    # 必须带默认值：frozen dataclass 新增无默认字段会破坏既有构造点。
    unresearched: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "repository_id": self.repository_id,
            "repository_name": self.repository_name,
            "repo_url": self.repo_url,
            "base_branch": self.base_branch,
            "work_branch": self.work_branch,
            "target_branch": self.target_branch,
            "affected_files": self.affected_files,
            "unresearched": self.unresearched,
        }


async def check_runner_online() -> bool:
    """检查是否有在线 Runner（重试 3 次，每次等 2 秒）。

    Returns:
        True 如果找到在线 Runner，False 否则。
    """
    from django.utils import timezone as tz

    from runners.models import Runner

    for attempt in range(3):
        heartbeat_threshold = tz.now() - timedelta(seconds=120)
        online_count = await Runner.objects.filter(
            status="online",
            last_heartbeat__gte=heartbeat_threshold,
        ).acount()
        if online_count > 0:
            logger.debug("runner_online_check_passed", attempt=attempt + 1)
            return True
        if attempt < 2:
            await asyncio.sleep(2)

    logger.warning("runner_online_check_failed", attempts=3)
    return False


async def build_coding_execution_spec(
    repository: Any,
    coding_session: CodingSession,
) -> CodingExecutionSpec:
    """从 CodingSession 固化一次容器执行所需的 repo/branch/files 契约。"""
    affected_files = list(coding_session.affected_files or [])
    coding_plan_id = getattr(coding_session, "coding_plan_id", None)
    # 允许清单：仅 orchestrated 视为经过调研。历史 session 未迁移（coding_plan_id 为
    # 空）时取不到来源标志 ⇒ 走保守分支 True，而不是默认「可信」。async 上下文只用
    # `*_id` 标量与显式查询，不裸访问 lazy FK。
    unresearched = True
    if coding_plan_id:
        from chat.models import CodingPlan

        plan = await CodingPlan.objects.only("affected_files", "provenance").aget(id=coding_plan_id)
        affected_files = list(plan.affected_files or [])
        unresearched = str(plan.provenance or "") != CodingPlanProvenance.ORCHESTRATED

    from chat.branch_service import DEFAULT_TARGET_BRANCH

    default_branch = repository.default_branch
    # base_branch 是容器 clone 的基线分支（仓库默认分支）；target_branch 是 PR 合并
    # 目标，取用户在启动编码时选定的值，未选时回退默认 develop。
    target_branch = (coding_session.target_branch or "").strip() or DEFAULT_TARGET_BRANCH
    return CodingExecutionSpec(
        repository_id=str(repository.id),
        repository_name=repository.name,
        repo_url=repository.git_url,
        base_branch=default_branch,
        work_branch=coding_session.branch_name,
        target_branch=target_branch,
        affected_files=affected_files,
        unresearched=unresearched,
    )


async def build_dispatch_metadata(
    repository: Any,
    coding_session: CodingSession,
) -> tuple[dict[str, Any], str]:
    """构建 dispatch 所需的 metadata 和处理后的 repo_url。

    包含: API key、Git 凭据、分支名注入。

    Args:
        repository: Repository 模型实例。
        coding_session: CodingSession 模型实例。

    Returns:
        (env_metadata, repo_url) 元组。
    """
    from services.git_credentials import aresolve_git_token
    from services.provider_config import aget_claude_code_runtime_config

    # Claude Code 编码容器配置：优先读 Claude Code 专属配置（选定凭证 + opus/sonnet/haiku
    # 三档映射）；未配置 credential_id 时 runtime_config 内部回退系统默认 anthropic 凭证。
    cc = await aget_claude_code_runtime_config()
    api_key = cc["api_key"]
    base_url = cc["base_url"]
    opus_model = cc["opus_model"]
    sonnet_model = cc["sonnet_model"]
    haiku_model = cc["haiku_model"]
    # 主模型兜底：sonnet 档 > 凭证 default_model；小模型兜底：haiku 档
    main_model = cc["default_model"] or sonnet_model
    small_model = haiku_model

    env_metadata: dict[str, Any] = {
        "repository_id": str(repository.id),
        "env_FRIDAY_TASK_CLAUDE_API_KEY": api_key,
        "env_FRIDAY_TASK_CLAUDE_BASE_URL": base_url,
        # 兼容既有两档 env（容器旧逻辑仍读取）
        "env_FRIDAY_TASK_CLAUDE_MODEL": main_model,
        "env_FRIDAY_TASK_CLAUDE_SMALL_MODEL": small_model,
        # workflow update：cc-switch 三档映射（容器据此设 ANTHROPIC_DEFAULT_*_MODEL）
        "env_FRIDAY_TASK_CLAUDE_OPUS_MODEL": opus_model,
        "env_FRIDAY_TASK_CLAUDE_SONNET_MODEL": sonnet_model,
        "env_FRIDAY_TASK_CLAUDE_HAIKU_MODEL": haiku_model,
    }

    repo_url = repository.git_url

    # Git 凭据（Phase 26 REPO-01：统一经解析器取 token，无 per-repo token 时按 host 用实例凭证）
    token = await aresolve_git_token(repository)
    if token:
        env_metadata["env_FRIDAY_TASK_GIT_ACCESS_TOKEN"] = token
        env_metadata["env_FRIDAY_TASK_GIT_AUTH_TYPE"] = "token"
        env_metadata["env_FRIDAY_TASK_GIT_SSL_VERIFY"] = "false"
        # SSH URL -> HTTPS（token 认证需要 HTTPS）
        if repo_url.startswith("git@"):
            m = re.match(r"git@([^:]+):(.+?)(?:\.git)?$", repo_url)
            if m:
                repo_url = f"https://{m.group(1)}/{m.group(2)}.git"

    execution_spec = await build_coding_execution_spec(repository, coding_session)

    # 功能分支名通过 env_ 前缀注入容器环境变量 (contract)
    env_metadata["execution_spec"] = execution_spec.as_dict()
    env_metadata["env_FRIDAY_TASK_BRANCH_STRATEGY"] = execution_spec.work_branch
    env_metadata["env_FRIDAY_TASK_TARGET_BRANCH"] = execution_spec.target_branch
    env_metadata["env_FRIDAY_TASK_AFFECTED_FILES"] = json.dumps(
        execution_spec.affected_files,
        ensure_ascii=False,
    )

    # 排除规则下传（Phase 22-04 / EXCL-02 容器读取面，T-22-13/14）：编码容器内 agent
    # 直接读真实工作树，必须在容器侧 clone 后按规则物理删除被排除文件。这里无条件下传
    # 有效规则（即便仅 builtin），不下传 = 容器面裸奔。仅下传规则模式，不含任何凭证。
    from services.exclusion import serialize_rules_for_repo

    exclude_rules = await serialize_rules_for_repo(str(repository.id))
    env_metadata["env_FRIDAY_TASK_EXCLUDE_PATTERNS"] = json.dumps(exclude_rules, ensure_ascii=False)

    # 固定容器 workspace cwd（HOOK-04）：SDK transcript 目录按 cwd realpath 派生，
    # 跨容器 resume 须 cwd 一致才能命中同一 transcript。dispatch 显式下发约定 cwd，
    # 供 SessionStore.assert_cwd_consistent 校验 resume 一致性（cwd 漂移即回退新 session）。
    from chat.session_store import WORKSPACE_CWD

    env_metadata["env_FRIDAY_TASK_WORKSPACE_CWD"] = WORKSPACE_CWD

    return env_metadata, repo_url


async def _resolve_project_context_for_dispatch(coding_session: CodingSession) -> str:
    """派发前按绑定项目召回项目上下文（pack_project_context + RetrievalTrace + 脱敏）。

    定位项目：优先 ``conversation.bound_project``；否则按 ``(repository, branch)`` 反查
    ``ProjectBranch`` 显式绑定（共享 helper ``aresolve_project_for_repo_branch``）。
    命中后经 ``apack_dispatch_context`` 召回（packer 内置 visibility fail-closed +
    写 RetrievalTrace + ``redact_secrets_in_text`` 脱敏，不绕过）。

    无绑定 / 召回空 / 任何异常 → 返回 ""（fail-soft，派发与现状逐字一致，绝不阻断编码）。
    """
    from services.project_context_packer import (
        apack_dispatch_context,
        aresolve_project_for_repo_branch,
    )

    try:
        cs = await CodingSession.objects.select_related(
            "conversation",
            "conversation__bound_project",
            "conversation__created_by",
        ).aget(id=coding_session.id)
        conversation = cs.conversation
        project = conversation.bound_project
        user = conversation.created_by  # 触发用户（归因）；匿名会话可为 None

        if project is None:
            project = await aresolve_project_for_repo_branch(
                repository_id=coding_session.repository_id,
                branch_name=coding_session.branch_name or "",
            )
        if project is None:
            return ""

        return await apack_dispatch_context(
            project,
            user,
            query=coding_session.branch_name or "",
            conversation_id=str(conversation.id),
        )
    except Exception as exc:  # noqa: BLE001 — 召回 fail-soft，绝不阻断派发主流程
        logger.warning(
            "dispatch_project_context_failed",
            coding_session_id=str(getattr(coding_session, "id", "")),
            error_type=type(exc).__name__,
            component="chat",
            category="sampling",
        )
        return ""


async def create_sub_session(
    coding_session: CodingSession,
    task_type: str = "coding",
) -> tuple[Any, Any]:
    """创建 AgentSession + SubAgentSession。

    Args:
        coding_session: CodingSession 模型实例。
        task_type: 任务类型，"coding" 或 "coding_commit"。

    Returns:
        (agent_session, sub_session) 元组。
    """
    from agents.models import AgentSession
    from subagent.models import SubAgentSession

    repo = coding_session.repository
    project = coding_session.conversation.space

    session_id_str = f"coding-{uuid_mod.uuid4().hex[:12]}"
    agent_session = await AgentSession.objects.acreate(
        session_id=f"agent-{session_id_str}",
        space=project,
        status=AgentSession.Status.RUNNING,
        metadata={
            "source": "coding_session_confirm",
            "conversation_id": str(coding_session.conversation_id),
            "coding_session_id": str(coding_session.id),
        },
    )

    # 映射 task_type 字符串到 SubAgentSession.TaskType 枚举
    task_type_enum = SubAgentSession.TaskType.CODING

    sub_session = await SubAgentSession.objects.acreate(
        session_id=session_id_str,
        main_session=agent_session,
        task_type=task_type_enum,
        status=SubAgentSession.Status.PENDING,
        repo_url=repo.git_url,
        last_output={
            "task_type": task_type,
            "source": "coding_session_confirm",
            "space_id": str(project.id),
            "conversation_id": str(coding_session.conversation_id),
            "coding_session_id": str(coding_session.id),
        },
    )

    return agent_session, sub_session


async def dispatch_coding_task(
    coding_session: CodingSession,
    task_type: str = "coding",
    extra_metadata: dict[str, str] | None = None,
    prompt: str = "",
) -> str:
    """构建 DispatchTask 并 dispatch 到 Runner。返回 session_id。

    完整流程: Runner 在线检查 -> 创建 session -> 构建 metadata -> 分支名校验 -> dispatch。

    Args:
        coding_session: CodingSession 模型实例（需预先 select_related repository, conversation__project）。
        task_type: 任务类型，"coding" 或 "coding_commit"。
        extra_metadata: 额外 metadata（如 Phase 的 commit_message）。
        prompt: 编码 prompt 内容。

    Returns:
        sub_session 的 session_id 字符串。

    Raises:
        RuntimeError: Runner 不在线时抛出。
        ValueError: 分支名校验失败时抛出。
    """
    from chat.branch_service import validate_branch_name
    from runners.dispatcher import DispatchTask, get_dispatcher
    from services.git_credentials import aresolve_git_token
    from services.git_platform import get_git_platform_client

    repo = coding_session.repository

    # 1. Runner 在线检查
    if not await check_runner_online():
        raise RuntimeError("没有可用的 Runner")

    # 2. 构建 metadata
    env_metadata, repo_url = await build_dispatch_metadata(repo, coding_session)

    # SDK resume 续跑：仅对真正跑 SDK 编码的 coding 任务注入（coding_commit 仅 amend+push，
    # 不跑 SDK，注入 transcript 既无用又徒增 ARG_MAX 压力）。默认安全：草稿/全新会话 sdk
    # 字段为空 → build_resume_dispatch_env 返回 {}，dispatch 行为与现状逐字一致。
    if task_type != "coding_commit":
        from chat.sdk_resume import build_resume_dispatch_env

        env_metadata.update(build_resume_dispatch_env(coding_session))

    # 派发携带项目上下文（HOOK-04）：经绑定项目召回（pack_project_context）注入容器
    # 执行 prompt/metadata，让容器侧编码代理一上来即有项目上下文。仅 coding 任务注入
    # （coding_commit 仅 amend+push 不跑 SDK）；召回空 → 不注入，派发与现状逐字一致。
    if task_type != "coding_commit":
        from services.project_context_packer import prepend_project_context

        project_context = await _resolve_project_context_for_dispatch(coding_session)
        if project_context:
            env_metadata["env_FRIDAY_TASK_PROJECT_CONTEXT"] = project_context
            prompt = prepend_project_context(prompt, project_context)

    # 合并 extra_metadata
    if extra_metadata:
        env_metadata.update(extra_metadata)

    # 3. 分支名校验 (work item)
    #
    # coding 阶段要求远程不能已有同名工作分支；coding_commit 阶段则正好相反：
    # 它复用 Phase 已 push 的工作分支执行 amend + force-with-lease。此时如果继续
    # 做 remote uniqueness 校验，会把正确存在的工作分支误判为冲突。
    git_client = None
    if task_type != "coding_commit":
        # Phase 26 REPO-01：统一经解析器取 token（per-repo 优先 → 同 host 实例凭证池 fallback）
        token = await aresolve_git_token(repo)
        if token:
            git_client = get_git_platform_client(repo, token)

    # 排除自己：当前 coding_session 已经是 active 状态（confirm 阶段已切到
    # CONFIRMED；未来 dispatch_coding_task 在 DRAFT 期被调时也会撞自己），
    # 不剔除就会被识别成"分支名已被活跃的编码会话使用"。
    validation = await validate_branch_name(
        branch_name=coding_session.branch_name,
        repository_id=repo.id,
        git_client=git_client,
        exclude_session_id=coding_session.id,
    )
    if not validation.valid:
        raise ValueError(f"分支名校验失败: {validation.errors}")

    # 4. 创建 session
    _agent_session, sub_session = await create_sub_session(
        coding_session,
        task_type=task_type,
    )

    # 4.5 任务级短 TTL token + 知识端点注入（Phase 103 AGENT-01/02）：
    # 仅对真正跑 SDK 的 coding 任务注入（coding_commit 仅 amend+push 不跑 SDK）。
    # 发起用户从 conversation.created_by_id 解析（conversation 已 select_related，
    # 本地字段异步安全；MCP 链经桥接会话透传 created_by 后同走此路径）。
    # user 不可解析 → 不注入 token env（降级，dispatch 行为与现状一致）。
    # PAT-02：mint 是新签发，明文仅本函数内存直进 env_metadata，绝不落盘/进日志。
    if task_type != "coding_commit":
        from django.conf import settings

        from access_tokens.services import mint_task_token

        user_id = coding_session.conversation.created_by_id
        user = None
        if user_id is not None:
            from accounts.models import User

            user = await User.objects.filter(id=user_id).afirst()
        if user is not None:
            plaintext = await mint_task_token(
                user,
                sub_session.session_id,
                3600,  # 对齐下方 DispatchTask 硬编码 timeout
            )
            env_metadata["env_FRIDAY_TASK_USER_TOKEN"] = plaintext
            # 31u：**非敏感**的发起用户 id 随快照落库（不是凭证）。派发经 durable 队列后
            # 任务体只按快照重建，rehydrate 据此键重铸 USER_TOKEN——不落则首派容器
            # 挂不上知识工具（回归）。断连重派路径同样受益。
            env_metadata["task_token_user_id"] = str(user.id)
        # 知识端点（AGENT-02 服务端注入面）：base 不带路径，task 侧自行拼
        # /api/mcp/tools/{name}/；空 FRIDAY_BASE_URL 不注入（镜像 workflow tools_env 契约）。
        knowledge_base = getattr(settings, "FRIDAY_BASE_URL", "").rstrip("/")
        if knowledge_base:
            env_metadata["env_FRIDAY_TASK_KNOWLEDGE_ENDPOINT"] = knowledge_base
        logger.info(
            "coding_dispatch_task_token",
            coding_session_id=str(coding_session.id),
            session_id=sub_session.session_id,
            has_user_token=user is not None,
            category="caller",
            component="chat",
        )

    # 5. 关联 SubAgentSession FK（dispatch 前保存，防竞态）
    coding_session.subagent_session = sub_session
    await coding_session.asave(update_fields=["subagent_session", "updated_at"])

    # 6. 构建 DispatchTask 并 dispatch
    execution_spec = env_metadata.get("execution_spec")
    if isinstance(execution_spec, dict):
        base_branch = str(execution_spec.get("base_branch") or repo.default_branch)
        target_branch = str(execution_spec.get("target_branch") or repo.default_branch)
    else:
        base_branch = repo.default_branch
        target_branch = repo.default_branch
    dispatch_task = DispatchTask(
        task_id=sub_session.session_id,
        task_type=task_type,
        tags=[],
        image="",
        repo_url=repo_url,
        branch=base_branch,
        target_branch=target_branch,
        prompt=prompt,
        timeout=3600,
        node_execution_id="",
        session_id=sub_session.session_id,
        metadata=env_metadata,
    )

    last_output = sub_session.last_output if isinstance(sub_session.last_output, dict) else {}
    # 泄漏防线（Phase 103 T-103-01 / 审查 WR-03）：落库副本统一剔除 CREDENTIAL_ENV_KEYS
    # 全部凭证明文键（任务 token / Git token / API key）——last_output 是持久化数据，
    # 凭证明文绝不落盘（PAT-02 同族纪律）。剔除逻辑统一走 dispatcher 的
    # ``build_dispatch_snapshot``（31u：⛔ 不留两份剔除逻辑）。重建（durable 首派任务体 /
    # runner 断连恢复）按 ``_redacted_env_keys`` 标记重解析补回 Git token / API key
    # （权威源：aresolve_git_token / provider 配置）；USER_TOKEN 按上方落库的
    # ``task_token_user_id`` 重铸补回。
    from runners.dispatcher import build_dispatch_snapshot

    sub_session.last_output = {
        **last_output,
        "dispatch": build_dispatch_snapshot(dispatch_task),
    }
    await sub_session.asave(update_fields=["last_output", "updated_at"])

    try:
        await get_dispatcher().dispatch(dispatch_task)
    except Exception:
        # IN-01（103 审查）：dispatch 失败无终态回调兜底吊销 → best-effort 立即吊销
        # 已铸任务 token，不再带全量权限存活至 timeout+余量自然过期
        # （arevoke_task_tokens 自身吞异常不反噬；未 mint 时幂等 count=0）。
        from access_tokens.services import arevoke_task_tokens

        await arevoke_task_tokens(sub_session.session_id)
        raise

    logger.info(
        "coding_task_dispatched",
        coding_session_id=str(coding_session.id),
        session_id=sub_session.session_id,
        task_type=task_type,
    )

    return sub_session.session_id


# ============================================================================
# 批量创建 CodingSession（CodingPlan 上 fan-out）
# ============================================================================


@dataclass
class SessionCreatedItem:
    """单条成功创建的 CodingSession 摘要。"""

    session_id: UUID
    repository_id: UUID
    branch_name: str


@dataclass
class SessionFailedItem:
    """单条创建失败的仓库 + 中文 error_message。"""

    repository_id: UUID
    error: str


@dataclass
class CodingSessionsBatchResult:
    """`create_sessions_for_plan` 返回的批量结果。"""

    created: list[SessionCreatedItem] = field(default_factory=list)
    failed: list[SessionFailedItem] = field(default_factory=list)


_BRANCH_SAFE_RE = re.compile(r"[^A-Za-z0-9._\-/]+")


def _sanitize_repo_name_for_branch(repo_name: str) -> str:
    """将 repo.name 规范化为分支名安全片段（仅 [A-Za-z0-9._\\-/]）。"""
    safe = _BRANCH_SAFE_RE.sub("-", repo_name).strip("-")
    return safe or "repo"


def _build_branch_name_for_repo(
    *,
    repo_name: str,
    branch_template: str,
    shared_branch_name: str,
) -> str:
    """渲染单仓分支名。

    - 模板含 ``${repo}`` 占位符 → ``Template.safe_substitute(repo=...)`` 渲染（per-repo
      不同名，兼容旧用法）。
    - 模板不含占位符（含为空）→ 返回 ``shared_branch_name``：一次技术方案的所有仓库
      统一使用同一个分支名（``{type}/{yymmdd}.{中文名}``）。唯一性按 (repo, branch)
      维度保证，不再追加 ``.<repo>`` 后缀。
    """
    if branch_template and "${repo}" in branch_template:
        safe_repo = _sanitize_repo_name_for_branch(repo_name)
        return Template(branch_template).safe_substitute(repo=safe_repo)
    if branch_template:
        return branch_template
    return shared_branch_name


async def create_sessions_for_plan(
    plan: CodingPlan,
    repository_ids: list[UUID],
    branch_template: str = "",
    target_branch: str = "",
    acknowledge_unresearched: bool = False,
    actor_user_id: str = "",
) -> CodingSessionsBatchResult:
    """在已有 CodingPlan 上批量创建 N 个 CodingSession（DRAFT 态）。

    per-repository 独立校验 + 独立 ``transaction.atomic()``，部分失败不阻塞其他仓库。

    **草稿 gate（RELY-01）**：``acknowledge_unresearched`` 默认 ``False``，只有布尔
    ``True`` 视为确认。gate 落在本函数最前面（任何 session 创建之前）而不是视图内 ——
    只在前端/视图做防护等于没做：任何脚本直接调 service 或打端点就能绕过。
    ``provenance == orchestrated`` 时该入参被**忽略**，编排方案零摩擦。
    ``actor_user_id`` 只用于 gate 留痕的问责字段（不参与任何授权判定，授权在视图层
    已完成）；调用方取不到触发用户时留空，留痕回退 contextvars / ``system``。

    校验链（per repo）：
      1. repository_id 属于 ``plan.conversation.space.repositories``
      2. 不在 ``(plan, repo)`` 既有 active sessions 中（work item 约束前置应用层校验）
      3. ``validate_branch_name`` 本地 + DB 唯一性校验通过（``git_client=None``
         跳过远程 refs 检查，远程检查由后续 confirm 流程的 dispatch_coding_task
         补做，避免本批量 endpoint 对每个 repo 都串行调用 Git API）
      4. ``transaction.atomic()`` 内 ``acreate``；捕获 IntegrityError 兜底（race）

    **调用方约束**：``plan`` 必须预先 ``select_related("conversation",
    "conversation__space")``，否则 ``plan.conversation.space`` 会触发同步
    DB 访问报错（async context）。
    """
    from chat.branch_service import DEFAULT_TARGET_BRANCH, validate_branch_name

    # 0) 草稿 gate（RELY-01）—— 必须在任何 session 创建之前，拒绝时 DB 零写入。
    if _plan_requires_unresearched_confirm(plan):
        if acknowledge_unresearched is not True:
            _log_draft_coding_gate(
                event="draft_plan_coding_rejected",
                plan_id=str(plan.id),
                reason=ERROR_CODE_DRAFT_REQUIRES_CONFIRM,
                actor_user_id=actor_user_id,
            )
            raise DraftPlanRequiresConfirmError()
        _log_draft_coding_gate(
            event="draft_plan_coding_confirmed",
            plan_id=str(plan.id),
            repo_count=len(repository_ids or []),
            actor_user_id=actor_user_id,
        )

    # PR 目标分支：本次 fan-out 统一应用到所有仓库，用户未选时回退默认 develop。
    resolved_target = (target_branch or "").strip() or DEFAULT_TARGET_BRANCH

    result = CodingSessionsBatchResult()
    if not repository_ids:
        return result

    # 1) 一次性拉所有合法 repository（属于 plan.conversation.space）
    project = plan.conversation.space
    valid_repos = [r async for r in project.repositories.filter(id__in=repository_ids)]
    valid_repo_map = {repo.id: repo for repo in valid_repos}

    # 不在项目下的 repo → failed
    for rid in repository_ids:
        if rid not in valid_repo_map:
            result.failed.append(SessionFailedItem(repository_id=rid, error="仓库不存在或无权访问"))

    if not valid_repo_map:
        return result

    # 2) 预检：plan 上已有 active session 的 repo
    active_existing_ids: set[UUID] = {
        rid
        async for rid in CodingSession.objects.filter(
            coding_plan=plan,
            repository_id__in=list(valid_repo_map.keys()),
            status__in=ACTIVE_STATUSES,
        ).values_list("repository_id", flat=True)
    }

    for rid in list(valid_repo_map.keys()):
        if rid in active_existing_ids:
            result.failed.append(SessionFailedItem(repository_id=rid, error=ERROR_REPO_ACTIVE_BUSY))
            valid_repo_map.pop(rid, None)

    # 生成本次 fan-out 统一默认分支名（多仓共用 {type}/{yymmdd}.{简短中文名}）。
    # 仅在未提供模板时调用 LLM 生成中文名；模板模式按模板渲染（兼容 ${repo}）。
    shared_branch_name = ""
    if not branch_template:
        from chat.branch_service import agenerate_default_branch_name

        shared_branch_name, _bt, _sd = await agenerate_default_branch_name(plan.tech_plan)

    # 3) 逐仓库创建（独立事务）
    for rid, repo in valid_repo_map.items():
        try:
            branch_name = _build_branch_name_for_repo(
                repo_name=repo.name,
                branch_template=branch_template,
                shared_branch_name=shared_branch_name,
            )
        except Exception as exc:
            result.failed.append(
                SessionFailedItem(
                    repository_id=rid,
                    error=f"分支名生成失败：{exc!s}",
                )
            )
            continue

        validation = await validate_branch_name(
            branch_name=branch_name,
            repository_id=rid,
            git_client=None,
            exclude_session_id=None,
        )
        if not validation.valid:
            result.failed.append(
                SessionFailedItem(
                    repository_id=rid,
                    error="；".join(validation.errors) if validation.errors else "分支名校验失败",
                )
            )
            continue

        @sync_to_async
        def _atomic_create(
            repo_obj: Any = repo, br: str = branch_name, tb: str = resolved_target
        ) -> Any:
            with transaction.atomic():
                return CodingSession.objects.create(
                    conversation=plan.conversation,
                    coding_plan=plan,
                    repository=repo_obj,
                    tech_plan=plan.tech_plan,
                    affected_files=plan.affected_files,
                    branch_name=br,
                    target_branch=tb,
                    status=CodingSession.Status.DRAFT,
                )

        try:
            session = await _atomic_create()
        except IntegrityError:
            # work item unique 约束兜底（理论上预检后不应到这里，但有竞态保护）
            result.failed.append(SessionFailedItem(repository_id=rid, error=ERROR_REPO_ACTIVE_BUSY))
            logger.warning(
                "coding_sessions.batch_failed",
                plan_id=str(plan.id),
                repo_id=str(rid),
                error="unique_active_plan_repo race",
            )
            continue

        result.created.append(
            SessionCreatedItem(
                session_id=session.id,
                repository_id=rid,
                branch_name=branch_name,
            )
        )
        logger.info(
            "coding_sessions.batch_created",
            plan_id=str(plan.id),
            session_id=str(session.id),
            repo_id=str(rid),
            branch_name=branch_name,
        )

    if result.created:
        from knowledge import ingestion  # lazy import 防循环

        await ingestion.aschedule_ingestion(
            ingestion.IngestionRequest("coding_plan", str(plan.id), "chat_coding_started")
        )
    return result
