"""CodingSession dispatch service -- 从 CodingSessionConfirmView 提取的共享逻辑。
提供 check_runner_online / build_dispatch_metadata / create_sub_session / dispatch_coding_task
四个 async 函数，供 CodingSessionConfirmView 和后续 CodingSession graph 节点复用。
Phase：追加 `create_sessions_for_plan` 批量创建业务函数，
封装 per-repo 校验 + 独立事务 + 失败收集语义。
"""
from __future__ import annotations
import asyncio
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
from chat.models import CodingSession
if TYPE_CHECKING:
 from chat.models import CodingPlan
logger = structlog.get_logger(__name__)
# ----------------------------------------------------------------------------
# Phase /：active 状态枚举常量
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
async def check_runner_online -> bool:
 """检查是否有在线 Runner（重试 3 次，每次等 2 秒）。
 Returns:
 True 如果找到在线 Runner，False 否则。
 """
 from django.utils import timezone as tz
 from runners.models import Runner
 for attempt in range(3):
 heartbeat_threshold = tz.now - timedelta(seconds=120)
 online_count = await Runner.objects.filter(
 status="online",
 last_heartbeat__gte=heartbeat_threshold,
 ).acount
 if online_count > 0:
 logger.debug("runner_online_check_passed", attempt=attempt + 1)
 return True
 if attempt < 2:
 await asyncio.sleep(2)
 logger.warning("runner_online_check_failed", attempts=3)
 return False
async def build_dispatch_metadata(
 repository: Any,
 coding_session: CodingSession,
) -> tuple[dict[str, str], str]:
 """构建 dispatch 所需的 metadata 和处理后的 repo_url。
 包含: API key、Git 凭据、分支名注入。
 Args:
 repository: Repository 模型实例。
 coding_session: CodingSession 模型实例。
 Returns:
 (env_metadata, repo_url) 元组。
 """
 from common.encryption import decrypt_value
 from repositories.models import GitCredential
 from services.provider_config import aget_legacy_anthropic_config
 # Phase Plan：SettingKeys.ANTHROPIC_* 硬删后走
 # ProviderCredential(scope=system, name=default, provider_type=anthropic)
 legacy = await aget_legacy_anthropic_config
 api_key = legacy["api_key"]
 base_url = legacy["base_url"]
 system_model = legacy["default_model"]
 small_model = legacy["small_model"]
 env_metadata: dict[str, str] = {
 "repository_id": str(repository.id),
 "env_FRIDAY_TASK_CLAUDE_API_KEY": api_key,
 "env_FRIDAY_TASK_CLAUDE_BASE_URL": base_url,
 "env_FRIDAY_TASK_CLAUDE_MODEL": system_model,
 "env_FRIDAY_TASK_CLAUDE_SMALL_MODEL": small_model,
 }
 repo_url = repository.git_url
 # Git 凭据
 try:
 cred = await GitCredential.objects.aget(repository=repository)
 if cred.encrypted_token:
 token = decrypt_value(cred.encrypted_token)
 env_metadata["env_FRIDAY_TASK_GIT_ACCESS_TOKEN"] = token
 env_metadata["env_FRIDAY_TASK_GIT_AUTH_TYPE"] = "token"
 env_metadata["env_FRIDAY_TASK_GIT_SSL_VERIFY"] = "false"
 # SSH URL -> HTTPS（token 认证需要 HTTPS）
 if repo_url.startswith("git@"):
 m = re.match(r"git@([^:]+):(.+?)(?:\.git)?$", repo_url)
 if m:
 repo_url = f"https://{m.group(1)}/{m.group(2)}.git"
 except GitCredential.DoesNotExist:
 pass
 # 功能分支名通过 env_ 前缀注入容器环境变量
 env_metadata["env_FRIDAY_TASK_BRANCH_STRATEGY"] = coding_session.branch_name
 return env_metadata, repo_url
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
 project = coding_session.conversation.project
 session_id_str = f"coding-{uuid_mod.uuid4.hex[:12]}"
 agent_session = await AgentSession.objects.acreate(
 session_id=f"agent-{session_id_str}",
 project=project,
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
 from common.encryption import decrypt_value
 from repositories.models import GitCredential
 from runners.dispatcher import DispatchTask, get_dispatcher
 from services.git_platform import get_git_platform_client
 repo = coding_session.repository
 # 1. Runner 在线检查
 if not await check_runner_online:
 raise RuntimeError("没有可用的 Runner")
 # 2. 创建 session
 _agent_session, sub_session = await create_sub_session(
 coding_session, task_type=task_type,
 )
 # 3. 关联 SubAgentSession FK（dispatch 前保存，防竞态）
 coding_session.subagent_session = sub_session
 await coding_session.asave(update_fields=["subagent_session", "updated_at"])
 # 4. 构建 metadata
 env_metadata, repo_url = await build_dispatch_metadata(repo, coding_session)
 # 合并 extra_metadata
 if extra_metadata:
 env_metadata.update(extra_metadata)
 # 5. 分支名校验
 git_client = None
 try:
 cred = await GitCredential.objects.aget(repository=repo)
 if cred.encrypted_token:
 token = decrypt_value(cred.encrypted_token)
 git_client = get_git_platform_client(repo, token)
 except GitCredential.DoesNotExist:
 pass
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
 # 6. 构建 DispatchTask 并 dispatch
 target_branch = repo.default_branch
 dispatch_task = DispatchTask(
 task_id=sub_session.session_id,
 task_type=task_type,
 tags=,
 image="",
 repo_url=repo_url,
 branch=repo.default_branch,
 target_branch=target_branch,
 prompt=prompt,
 timeout=3600,
 node_execution_id="",
 session_id=sub_session.session_id,
 metadata=env_metadata,
 )
 await get_dispatcher.dispatch(dispatch_task)
 logger.info(
 "coding_task_dispatched",
 coding_session_id=str(coding_session.id),
 session_id=sub_session.session_id,
 task_type=task_type,
 )
 return sub_session.session_id
# ============================================================================
# Phase：批量创建 CodingSession（CodingPlan 上 fan-out）
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
 plan: CodingPlan,
 repo_name: str,
 branch_template: str,
) -> str:
 """按模板渲染分支名；模板为空则按 plan.tech_plan 推断 + 自动追加 repo 后缀。
 - 模板为空 → 按 ``generate_default_branch_name(plan.tech_plan)`` 推断默认前缀，
 并自动追加 ``.<repo>`` 后缀（确保多 repo fan-out 时分支名彼此唯一，避免被
 ``validate_branch_name`` 的 DB 唯一性校验拦截）。
 - 模板含 ``${repo}`` 占位符 → ``Template.safe_substitute(repo=...)`` 渲染；
 由调用方保证占位符存在。
 - 模板不含占位符 → 直接返回模板（多 repo 共享同名分支会被 unique 约束
 或分支名校验阻止，由调用方收集 failed 时给出可读 error）。
 """
 from chat.branch_service import generate_default_branch_name
 safe_repo = _sanitize_repo_name_for_branch(repo_name)
 if branch_template:
 return Template(branch_template).safe_substitute(repo=safe_repo)
 default_branch, _branch_type, _short_desc = generate_default_branch_name(
 plan.tech_plan
 )
 return f"{default_branch}.{safe_repo}"
async def create_sessions_for_plan(
 plan: CodingPlan,
 repository_ids: list[UUID],
 branch_template: str = "",
) -> CodingSessionsBatchResult:
 """：在已有 CodingPlan 上批量创建 N 个 CodingSession（DRAFT 态）。
 per-repository 独立校验 + 独立 ``transaction.atomic``，部分失败不阻塞其他仓库。
 校验链（per repo）：
 1. repository_id 属于 ``plan.conversation.project.repositories``
 2. 不在 ``(plan, repo)`` 既有 active sessions 中（ 约束前置应用层校验）
 3. ``validate_branch_name`` 校验通过
 4. ``transaction.atomic`` 内 ``acreate``；捕获 IntegrityError 兜底（race）
 """
 from chat.branch_service import validate_branch_name
 from chat.models import CodingPlan as _CodingPlan # noqa: F401 (类型 hint)
 result = CodingSessionsBatchResult
 if not repository_ids:
 return result
 # 1) 一次性拉所有合法 repository（属于 plan.conversation.project）
 project = plan.conversation.project
 valid_repos = [
 r
 async for r in project.repositories.filter(id__in=repository_ids)
 ]
 valid_repo_map = {repo.id: repo for repo in valid_repos}
 # 不在项目下的 repo → failed
 for rid in repository_ids:
 if rid not in valid_repo_map:
 result.failed.append(
 SessionFailedItem(repository_id=rid, error="仓库不存在或无权访问")
 )
 if not valid_repo_map:
 return result
 # 2) 预检：plan 上已有 active session 的 repo
 active_existing_ids: set[UUID] = {
 rid
 async for rid in CodingSession.objects.filter(
 coding_plan=plan,
 repository_id__in=list(valid_repo_map.keys),
 status__in=ACTIVE_STATUSES,
 ).values_list("repository_id", flat=True)
 }
 for rid in list(valid_repo_map.keys):
 if rid in active_existing_ids:
 result.failed.append(
 SessionFailedItem(
 repository_id=rid, error="该仓库已有进行中的编码会话"
 )
 )
 valid_repo_map.pop(rid, None)
 # 3) 逐仓库创建（独立事务）
 for rid, repo in valid_repo_map.items:
 try:
 branch_name = _build_branch_name_for_repo(
 plan=plan, repo_name=repo.name, branch_template=branch_template
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
 error="；".join(validation.errors)
 if validation.errors
 else "分支名校验失败",
 )
 )
 continue
 @sync_to_async
 def _atomic_create(repo_obj: Any = repo, br: str = branch_name) -> Any:
 with transaction.atomic:
 return CodingSession.objects.create(
 conversation=plan.conversation,
 coding_plan=plan,
 repository=repo_obj,
 tech_plan=plan.tech_plan,
 affected_files=plan.affected_files,
 branch_name=br,
 status=CodingSession.Status.DRAFT,
 )
 try:
 session = await _atomic_create
 except IntegrityError:
 # unique 约束兜底（理论上预检后不应到这里，但有竞态保护）
 result.failed.append(
 SessionFailedItem(
 repository_id=rid, error="该仓库已有进行中的编码会话"
 )
 )
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
 return result
