"""CodingSession dispatch service -- 从 CodingSessionConfirmView 提取的共享逻辑。
提供 check_runner_online / build_dispatch_metadata / create_sub_session / dispatch_coding_task
四个 async 函数，供 CodingSessionConfirmView 和后续 CodingSession graph 节点复用。
"""
from __future__ import annotations
import asyncio
import re
import uuid as uuid_mod
from datetime import timedelta
from typing import Any
import structlog
from chat.models import CodingSession
logger = structlog.get_logger(__name__)
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
 validation = await validate_branch_name(
 branch_name=coding_session.branch_name,
 repository_id=repo.id,
 git_client=git_client,
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
