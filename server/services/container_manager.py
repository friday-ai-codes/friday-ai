"""统一容器管理器 — 替代 ContainerExecutor + TaskScheduler 双轨系统。
组合 ContainerExecutor 底层 Docker 操作，新增：
- 数据库持久化容器映射（解决 C1: 内存态映射丢失）
- UUID 容器命名（解决 C3: 容器名碰撞）
- 重复提交检测 + 安全重执行
- Docker daemon 可用性检测
- /workspace/.friday/ 文件通信协议集成
Phase 核心交付物。
"""
import asyncio
import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Any
import docker
import structlog
from django.utils import timezone
from services.container_executor import ContainerExecutor, ExecutionRequest
from services.protocols import (
 CONTAINER_PROTOCOL_DIR,
 CONTEXT_FILE,
 ENV_CALLBACK_TOKEN,
 ENV_CALLBACK_URL,
 ENV_PROTOCOL_DIR,
 ENV_SESSION_ID,
 ENV_TASK_TYPE,
 ContextPayload,
)
from subagent.models import SubAgentSession
logger = structlog.get_logger(__name__)
@dataclass
class ContainerConfig:
 """容器启动配置。"""
 session_id: str
 """唯一会话标识（由 generate_execution_id 生成）"""
 task_type: str
 """任务类型: coding | plan | explore | ask"""
 image: str = "friday-task:latest"
 # 任务输入
 prompt: str = ""
 context: dict[str, Any] = field(default_factory=dict)
 # Git 配置
 repo_url: str = ""
 branch: str = ""
 target_branch: str | None = None
 git_credentials: dict[str, str] = field(default_factory=dict)
 # 资源限制
 mem_limit: str = "2g"
 cpu_quota: int = 100000 # 1 CPU
 timeout: int = 1800 # 默认 30min
 # 元数据标签
 labels: dict[str, str] = field(default_factory=dict)
 # 关联信息
 work_item_id: str = ""
 main_session_id: str = ""
 node_execution_id: str = ""
 # Claude 配置
 claude_api_key: str = ""
 claude_base_url: str = ""
class ContainerManager:
 """统一容器管理器。
 在 ContainerExecutor 基础上增加：
 - 数据库持久化容器映射（解决 C1）
 - UUID 幂等执行（解决 C2/C3）
 - /workspace/.friday/ 文件通信协议
 - Docker daemon 可用性检测
 公开接口：
 - start(config) -> container_id # 启动容器（幂等）
 - stop(session_id, force) -> bool # 停止容器
 - get_status(session_id) -> dict # 获取状态
 - get_logs(session_id, tail) -> str # 获取日志
 - cleanup(older_than_hours) -> int # 清理已完成容器
 - restart(config) -> container_id # 安全重执行
 """
 def __init__(self) -> None:
 self._executor = ContainerExecutor
 self._verify_docker_daemon
 def _verify_docker_daemon(self) -> None:
 """启动时检测 Docker daemon 连接 。"""
 try:
 self._executor.client.ping
 info = self._executor.client.info
 logger.info(
 "docker_daemon_connected",
 version=info.get("ServerVersion"),
 containers_running=info.get("ContainersRunning"),
 )
 except docker.errors.DockerException as e:
 logger.error("docker_daemon_unavailable", error=str(e))
 raise RuntimeError(
 f"Docker daemon 不可用: {e}. "
 "请确认 Docker Desktop 已启动或 dockerd 正在运行。"
 ) from e
 @staticmethod
 def _generate_container_name -> str:
 """生成不可碰撞的容器名 (, C3)。"""
 return f"friday-exec-{uuid.uuid4.hex[:12]}"
 def _build_environment(self, config: ContainerConfig) -> dict[str, str]:
 """构建容器环境变量（统一 FRIDAY_* 前缀）。"""
 env: dict[str, str] = {
 # 协议核心
 ENV_SESSION_ID: config.session_id,
 ENV_TASK_TYPE: config.task_type,
 ENV_PROTOCOL_DIR: CONTAINER_PROTOCOL_DIR,
 # 回调（Phase 实现处理逻辑）
 ENV_CALLBACK_URL: self._executor._build_callback_url,
 ENV_CALLBACK_TOKEN: "", # TODO: Phase 内部认证
 # Git 配置
 "FRIDAY_GIT_REPO_URL": config.repo_url,
 "FRIDAY_GIT_BRANCH": config.branch,
 }
 if config.target_branch:
 env["FRIDAY_GIT_TARGET_BRANCH"] = config.target_branch
 # Git 认证
 if config.git_credentials.get("ssh_key"):
 env["FRIDAY_GIT_AUTH_TYPE"] = "ssh"
 env["FRIDAY_GIT_SSH_KEY"] = config.git_credentials["ssh_key"]
 elif config.git_credentials.get("access_token"):
 env["FRIDAY_GIT_AUTH_TYPE"] = "token"
 env["FRIDAY_GIT_ACCESS_TOKEN"] = config.git_credentials["access_token"]
 # SSL 验证
 git_ssl_verify = config.git_credentials.get("ssl_verify", "false")
 env["FRIDAY_GIT_SSL_VERIFY"] = str(git_ssl_verify).lower
 # Claude 配置
 if config.claude_api_key:
 env["FRIDAY_CLAUDE_API_KEY"] = config.claude_api_key
 if config.claude_base_url:
 env["FRIDAY_CLAUDE_BASE_URL"] = config.claude_base_url
 # Proxy（从 SystemSetting 读取，同步安全 — 在 async 方法中通过 sync_to_async 调用）
 env["FRIDAY_GIT_HTTP_PROXY"] = os.environ.get("FRIDAY_GIT_HTTP_PROXY", "")
 return env
 def _prepare_transfer_dir(self, session_id: str) -> str:
 """准备传输目录，返回宿主机侧 .friday 目录路径。"""
 friday_dir = os.path.join(
 self._executor.transfers_dir, session_id, ".friday"
 )
 os.makedirs(friday_dir, exist_ok=True)
 return friday_dir
 def _write_context_file(self, friday_dir: str, config: ContainerConfig) -> None:
 """写入 context.json 到传输目录。"""
 payload = ContextPayload(
 session_id=config.session_id,
 task_type=config.task_type,
 prompt=config.prompt,
 project=config.context.get("project", {}),
 work_item=config.context.get("work_item", {}),
 repo_url=config.repo_url,
 branch=config.branch,
 target_branch=config.target_branch,
 )
 context_path = os.path.join(friday_dir, CONTEXT_FILE)
 with open(context_path, "w") as f:
 from dataclasses import asdict
 json.dump(asdict(payload), f, ensure_ascii=False, indent=2)
 async def _get_or_create_session(
 self, config: ContainerConfig
 ) -> SubAgentSession:
 """创建或更新 SubAgentSession 记录，状态设为 PENDING。"""
 defaults: dict[str, Any] = {
 "status": SubAgentSession.Status.PENDING,
 "task_type": config.task_type,
 "repo_url": config.repo_url,
 "work_item_id": config.work_item_id,
 "target_branch": config.target_branch or "",
 }
 if config.main_session_id:
 from agents.models import AgentSession
 main_session = await AgentSession.objects.filter(
 session_id=config.main_session_id
 ).afirst
 if main_session:
 defaults["main_session"] = main_session
 if config.node_execution_id:
 from workflows.models import NodeExecution
 node_exec = await NodeExecution.objects.filter(
 id=config.node_execution_id
 ).afirst
 if node_exec:
 defaults["node_execution"] = node_exec
 session, created = await SubAgentSession.objects.aupdate_or_create(
 session_id=config.session_id,
 defaults=defaults,
 )
 logger.info(
 "session_prepared",
 session_id=config.session_id,
 created=created,
 status=session.status,
 )
 return session
 async def start(self, config: ContainerConfig) -> str:
 """启动容器（幂等）。: 重复提交检测 — 已有 RUNNING 任务时返回已有 container_id。: 容器创建 + 共享卷 + 环境变量注入。
 Args:
 config: 容器启动配置
 Returns:
 Docker 容器 ID
 Raises:
 RuntimeError: 容器启动失败
 """
 #: 重复提交检测
 duplicate = await self._check_duplicate(
 config.work_item_id, config.task_type, config.target_branch or "",
 )
 if duplicate:
 logger.info(
 "returning_existing_session",
 existing_session_id=duplicate.session_id,
 container_id=duplicate.container_id,
 )
 return duplicate.container_id
 return await self._start_container(config)
 async def _start_container(self, config: ContainerConfig) -> str:
 """实际容器启动逻辑（start 和 restart 共用）。"""
 session = await self._get_or_create_session(config)
 container_name = self._generate_container_name
 # 准备传输目录 + context.json
 friday_dir = self._prepare_transfer_dir(config.session_id)
 self._write_context_file(friday_dir, config)
 # 构建 ExecutionRequest
 env = self._build_environment(config)
 request = ExecutionRequest(
 execution_id=config.session_id,
 node_execution_id=config.node_execution_id or config.session_id,
 image=config.image,
 environment=env,
 volumes={
 friday_dir: {
 "bind": CONTAINER_PROTOCOL_DIR,
 "mode": "rw",
 },
 },
 timeout=config.timeout,
 callback_url=env.get(ENV_CALLBACK_URL, ""),
 mem_limit=config.mem_limit,
 cpu_quota=config.cpu_quota,
 container_name_prefix="friday-exec",
 labels={
 "friday.session_id": config.session_id,
 "friday.task_type": config.task_type,
 "friday.work_item_id": config.work_item_id,
 **config.labels,
 },
 )
 # 预删除同名容器 (C3)
 await self._executor._remove_container_by_name(container_name)
 try:
 container_id = await self._executor.start_execution(request)
 # 持久化到数据库 (C1)
 session.mark_running(container_id, container_name)
 logger.info(
 "container_started",
 session_id=config.session_id,
 container_id=container_id[:12],
 container_name=container_name,
 )
 return container_id
 except Exception as e:
 session.mark_failed(str(e))
 logger.error(
 "container_start_failed",
 session_id=config.session_id,
 error=str(e),
 )
 raise
 async def stop(self, session_id: str, force: bool = False) -> bool:
 """停止容器。
 Args:
 session_id: 会话 ID
 force: 是否强制终止
 Returns:
 True 如果容器已停止
 """
 container_id = await self._resolve_container_id(session_id)
 if not container_id:
 logger.warning("stop_no_container_found", session_id=session_id)
 return False
 stopped = await self._executor.stop_execution(container_id, force=force)
 if stopped:
 # 更新数据库状态
 session = await SubAgentSession.objects.filter(
 session_id=session_id
 ).afirst
 if session and session.status in (
 SubAgentSession.Status.PENDING,
 SubAgentSession.Status.RUNNING,
 ):
 if force:
 session.mark_cancelled
 else:
 session.mark_cancelled
 logger.info(
 "container_stopped",
 session_id=session_id,
 container_id=container_id[:12],
 force=force,
 )
 return stopped
 async def get_status(self, session_id: str) -> dict[str, Any] | None:
 """获取容器状态（数据库 + Docker 双源合并）。
 Args:
 session_id: 会话 ID
 Returns:
 状态字典或 None
 """
 session = await SubAgentSession.objects.filter(
 session_id=session_id
 ).afirst
 if not session:
 return None
 result: dict[str, Any] = {
 "session_id": session.session_id,
 "status": session.status,
 "task_type": session.task_type,
 "container_id": session.container_id,
 "container_name": session.container_name,
 "started_at": session.started_at.isoformat if session.started_at else None,
 "completed_at": session.completed_at.isoformat if session.completed_at else None,
 "duration_ms": session.duration_ms,
 }
 # 补充 Docker 实时状态
 if session.container_id:
 docker_status = await self._executor.get_status(session.container_id)
 if docker_status:
 result["docker_status"] = docker_status.get("status")
 result["docker_state"] = docker_status.get("state")
 return result
 async def get_logs(self, session_id: str, tail: int = 200) -> str:
 """获取容器日志。
 Args:
 session_id: 会话 ID
 tail: 返回行数
 Returns:
 日志内容
 """
 container_id = await self._resolve_container_id(session_id)
 if not container_id:
 return ""
 return await self._executor.get_logs(container_id, tail=tail)
 async def cleanup(self, older_than_hours: int = 24) -> int:
 """清理已完成容器。
 Args:
 older_than_hours: 仅清理超过此时长的容器
 Returns:
 清理数量
 """
 cutoff = timezone.now - timezone.timedelta(hours=older_than_hours)
 terminal_statuses = [
 SubAgentSession.Status.COMPLETED,
 SubAgentSession.Status.ERROR,
 SubAgentSession.Status.TIMEOUT,
 SubAgentSession.Status.CANCELLED,
 ]
 sessions = SubAgentSession.objects.filter(
 status__in=terminal_statuses,
 completed_at__lt=cutoff,
 container_id__gt="", # 有容器 ID 的
 )
 removed = 0
 async for session in sessions:
 try:
 container = await asyncio.to_thread(
 self._executor.client.containers.get, session.container_id
 )
 await asyncio.to_thread(container.remove, force=True)
 removed += 1
 logger.debug(
 "container_removed",
 session_id=session.session_id,
 container_id=session.container_id[:12],
 )
 except docker.errors.NotFound:
 pass # 容器已不存在
 except Exception as e:
 logger.warning(
 "container_remove_failed",
 session_id=session.session_id,
 error=str(e),
 )
 # 同时清理无数据库记录的孤儿容器
 orphan_count = await self._executor.cleanup_finished_containers(older_than_hours)
 total = removed + orphan_count
 if total:
 logger.info("cleanup_completed", db_removed=removed, orphan_removed=orphan_count)
 return total
 async def restart(self, config: ContainerConfig) -> str:
 """安全重执行：新容器 + 新卷 + 新 session_id 。
 与 start 的区别：跳过重复检测，始终创建新执行。
 旧的同 work_item_id 的 RUNNING 任务会被先停止。
 Args:
 config: 容器启动配置
 Returns:
 新容器 ID
 """
 # 停止同 work_item_id 的旧任务
 if config.work_item_id:
 old_sessions = SubAgentSession.objects.filter(
 work_item_id=config.work_item_id,
 task_type=config.task_type,
 status__in=[
 SubAgentSession.Status.PENDING,
 SubAgentSession.Status.RUNNING,
 ],
 )
 async for old_session in old_sessions:
 logger.info(
 "stopping_old_session_for_restart",
 old_session_id=old_session.session_id,
 )
 await self.stop(old_session.session_id, force=False)
 # 生成新 session_id（确保不碰撞）
 from subagent.models import generate_execution_id
 config.session_id = generate_execution_id
 # 跳过重复检测，直接启动
 return await self._start_container(config)
 # === 私有辅助方法 ===
 async def _check_duplicate(
 self,
 work_item_id: str,
 task_type: str,
 target_branch: str,
 ) -> SubAgentSession | None:
 """基于 (work_item_id, task_type, target_branch) 检测重复提交 。
 Returns:
 已有的 RUNNING/PENDING session，或 None。
 """
 if not work_item_id:
 return None
 existing = await SubAgentSession.objects.filter(
 work_item_id=work_item_id,
 task_type=task_type,
 target_branch=target_branch,
 status__in=[
 SubAgentSession.Status.PENDING,
 SubAgentSession.Status.RUNNING,
 ],
 ).afirst
 if not existing:
 return None
 # 验证容器是否真的在运行（防止数据库状态与 Docker 不一致）
 if existing.container_id:
 docker_status = await self.get_status(existing.session_id)
 if docker_status and docker_status.get("docker_status") == "running":
 logger.info(
 "duplicate_task_detected",
 session_id=existing.session_id,
 work_item_id=work_item_id,
 task_type=task_type,
 )
 return existing
 else:
 # 容器已不在运行，修正数据库状态
 existing.mark_failed("容器已退出但状态未更新")
 return None
 # PENDING 状态（容器还没启动）也算重复
 return existing
 async def _resolve_container_id(self, session_id: str) -> str | None:
 """从数据库或 Docker label 解析容器 ID（双源恢复）。"""
 # 优先从数据库查
 session = await SubAgentSession.objects.filter(
 session_id=session_id
 ).afirst
 if session and session.container_id:
 return session.container_id
 # 回退：通过 Docker label 查找
 try:
 containers = await asyncio.to_thread(
 self._executor.client.containers.list,
 all=True,
 filters={"label": f"friday.session_id={session_id}"},
 )
 if containers:
 container_id = str(containers[0].id)
 logger.info(
 "container_resolved_via_label",
 session_id=session_id,
 container_id=container_id[:12],
 )
 return container_id
 except Exception as e:
 logger.warning(
 "container_label_lookup_failed",
 session_id=session_id,
 error=str(e),
 )
 return None
# Singleton
_manager: ContainerManager | None = None
def get_container_manager -> ContainerManager:
 """获取 ContainerManager 单例。"""
 global _manager
 if _manager is None:
 _manager = ContainerManager
 return _manager
