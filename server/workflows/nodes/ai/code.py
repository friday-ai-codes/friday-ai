"""Code implementation node."""
import structlog
from services.container_executor import (
 ExecutionRequest,
 get_container_executor,
)
from workflows.nodes.base import (
 BaseNode,
 ExecutionContext,
 NodeCategory,
 NodePort,
 NodeResult,
 PortType,
)
from workflows.nodes.registry import register_node
logger = structlog.get_logger
@register_node
class CodeImplementNode(BaseNode):
 """代码实现节点
 基于技术方案，在 Docker 容器中执行代码实现。
 对应原 Task 系统的 EXECUTING 状态，复用 Docker 执行器。
 """
 node_type = "code_implement"
 display_name = "代码实现"
 description = "在容器中执行代码实现任务"
 icon = "code"
 category = NodeCategory.AI
 # 需要 Docker 容器执行
 requires_container = True
 supports_retry = True
 config_schema = {
 "type": "object",
 "properties": {
 "plan": {
 "type": "string",
 "title": "技术方案",
 "description": "要实现的技术方案，支持模板变量",
 },
 "repository_path": {
 "type": "string",
 "title": "仓库路径",
 "description": "代码仓库的路径",
 },
 "branch_name": {
 "type": "string",
 "title": "分支名称",
 "description": "在哪个分支上实现",
 "default": "",
 },
 "execution_mode": {
 "type": "string",
 "title": "执行模式",
 "enum": ["auto", "interactive", "dry_run"],
 "default": "auto",
 "description": "auto=全自动, interactive=需要确认, dry_run=仅预览",
 },
 "max_iterations": {
 "type": "integer",
 "title": "最大迭代次数",
 "description": "AI 自我修正的最大次数",
 "default": 5,
 "minimum": 1,
 "maximum": 20,
 },
 "run_tests": {
 "type": "boolean",
 "title": "运行测试",
 "description": "实现后自动运行测试",
 "default": True,
 },
 "auto_commit": {
 "type": "boolean",
 "title": "自动提交",
 "description": "完成后自动提交代码",
 "default": True,
 },
 "container_image": {
 "type": "string",
 "title": "容器镜像",
 "description": "执行环境的 Docker 镜像",
 "default": "friday-agent:latest",
 },
 "timeout": {
 "type": "integer",
 "title": "超时时间(秒)",
 "default": 1800,
 "minimum": 60,
 "maximum": 7200,
 },
 },
 "required": ["plan", "repository_path"],
 }
 inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
 outputs = [
 NodePort(name="default", label="成功", port_type=PortType.OBJECT),
 NodePort(name="error", label="失败", port_type=PortType.OBJECT),
 NodePort(name="needs_review", label="需要审核", port_type=PortType.OBJECT),
 ]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 config = context.node_config
 plan = context.render_template(config.get("plan", ""))
 repository_path = context.render_template(config.get("repository_path", ""))
 branch_name = context.render_template(config.get("branch_name", ""))
 execution_mode = config.get("execution_mode", "auto")
 max_iterations = config.get("max_iterations", 5)
 run_tests = config.get("run_tests", True)
 auto_commit = config.get("auto_commit", True)
 if not plan or not repository_path:
 return NodeResult(
 status="failed",
 error="技术方案和仓库路径不能为空",
 next_handle="error",
 )
 try:
 # Dry run mode - only preview
 if execution_mode == "dry_run":
 return NodeResult(
 status="completed",
 output={
 "mode": "dry_run",
 "plan": plan,
 "repository_path": repository_path,
 "preview": "Dry run - no changes made",
 },
 next_handle="default",
 )
 # Execute code implementation in container
 # TODO: Integrate with services/docker_executor.py
 execution_result = await self._execute_in_container(
 plan=plan,
 repository_path=repository_path,
 branch_name=branch_name,
 max_iterations=max_iterations,
 run_tests=run_tests,
 auto_commit=auto_commit,
 container_image=config.get("container_image", "friday-agent:latest"),
 timeout=config.get("timeout", 1800),
 context=context,
 )
 if execution_result.get("needs_review"):
 return NodeResult(
 status="completed",
 output=execution_result,
 next_handle="needs_review",
 )
 if execution_result.get("success"):
 return NodeResult(
 status="completed",
 output=execution_result,
 next_handle="default",
 )
 else:
 return NodeResult(
 status="failed",
 output=execution_result,
 error=execution_result.get("error", "Unknown error"),
 next_handle="error",
 )
 except Exception as e:
 return NodeResult(
 status="failed",
 error=str(e),
 next_handle="error",
 )
 async def _execute_in_container(
 self,
 plan: str,
 repository_path: str,
 branch_name: str,
 max_iterations: int,
 run_tests: bool,
 auto_commit: bool,
 container_image: str,
 timeout: int,
 context: ExecutionContext,
 ) -> dict:
 """在 Docker 容器中执行代码实现
 Uses ContainerExecutor to run code implementation in an isolated container.
 The container will call back when execution completes.
 """
 executor = get_container_executor
 # Build environment variables for the container
 environment = {
 "FRIDAY_TASK_MODE": context.node_config.get("execution_mode", "auto"),
 "FRIDAY_TASK_MAX_ITERATIONS": str(max_iterations),
 "FRIDAY_TASK_REPOSITORY_PATH": repository_path,
 "FRIDAY_TASK_PLAN": plan,
 "FRIDAY_TASK_BRANCH_NAME": branch_name,
 "FRIDAY_TASK_RUN_TESTS": str(run_tests).lower,
 "FRIDAY_TASK_AUTO_COMMIT": str(auto_commit).lower,
 }
 # Add project context if available
 workflow_context = context.workflow_context or {}
 if workflow_context.get("project_id"):
 environment["FRIDAY_PROJECT_ID"] = str(workflow_context["project_id"])
 # Build volume mounts
 volumes = {}
 if repository_path:
 # Mount the repository into the container
 volumes[repository_path] = {"bind": "/workspace", "mode": "rw"}
 # Create execution request
 request = ExecutionRequest(
 execution_id=context.execution_id,
 node_execution_id=context.node_id,
 image=container_image,
 environment=environment,
 volumes=volumes,
 timeout=timeout,
 )
 try:
 # Start container execution
 container_id = await executor.start_execution(request)
 logger.info(
 "code_implement_container_started",
 container_id=container_id[:12],
 execution_id=context.execution_id,
 node_id=context.node_id,
 )
 # Return waiting status - the container will callback when done
 # The workflow engine will handle the callback and resume execution
 return {
 "success": True,
 "waiting_callback": True,
 "container_id": container_id,
 "message": "Container started, waiting for callback",
 }
 except Exception as e:
 logger.error(
 "code_implement_container_failed",
 error=str(e),
 execution_id=context.execution_id,
 )
 return {
 "success": False,
 "error": str(e),
 }
 async def on_cancel(self, context: ExecutionContext) -> None:
 """取消时停止容器"""
 container_id = context.get_state("container_id")
 if container_id:
 executor = get_container_executor
 await executor.stop_execution(container_id, force=False)
 logger.info("code_implement_container_cancelled", container_id=container_id[:12])
 async def on_timeout(self, context: ExecutionContext) -> None:
 """超时时停止容器"""
 container_id = context.get_state("container_id")
 if container_id:
 executor = get_container_executor
 await executor.stop_execution(container_id, force=True)
 logger.info("code_implement_container_timeout", container_id=container_id[:12])
