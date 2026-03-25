"""AI Coding Dispatcher node for dispatching coding tasks from technical plans.
Strict Mode Implementation:
This dispatcher parses execution_plan from upstream TechnicalPlanNode output
and creates CodingTasks directly without LLM analysis. Tasks targeting the
same repository and branch strategy are merged into a single CodingTask.
"""
import asyncio
from typing import Any
import structlog
from repositories.models import Repository
from workflows.models.coding_task import CodingTask, CodingTaskStatus
from workflows.nodes.base import (
 BaseNode,
 ExecutionContext,
 NodeCategory,
 NodePort,
 NodeResult,
 PortType,
)
from workflows.nodes.registry import register_node
from workflows.schemas.technical_plan import validate_technical_plan
logger = structlog.get_logger
@register_node
class AICodingDispatcherNode(BaseNode):
 """AI 编码指派器节点 (严格模式)
 从上游 TechnicalPlanNode 解析 execution_plan，
 直接创建 CodingTask 记录，无需 LLM 分析。
 特性:
 - 验证技术方案的 execution_plan 结构
 - 合并同一仓库/分支策略的任务
 - 并行创建 CodingTask 记录
 - 支持部分成功状态
 """
 node_type = "ai_coding_dispatcher"
 display_name = "AI 编码指派器"
 description = "从技术方案创建编码任务"
 icon = "git-branch"
 category = NodeCategory.AI
 execution_mode = "server_local"
 config_schema = {
 "type": "object",
 "properties": {
 "merge_same_branch": {
 "type": "boolean",
 "title": "合并同分支任务",
 "description": "是否将目标相同仓库/分支的任务合并为单个 CodingTask",
 "default": True,
 },
 },
 }
 inputs = [
 NodePort(
 name="plan",
 label="技术方案",
 port_type=PortType.OBJECT,
 required=True,
 description="上游 TechnicalPlanNode 输出的技术方案",
 ),
 ]
 outputs = [
 NodePort(
 name="default",
 label="任务列表",
 port_type=PortType.OBJECT,
 description="创建的编码任务列表",
 ),
 NodePort(
 name="error",
 label="失败",
 port_type=PortType.OBJECT,
 description="处理失败时的错误信息",
 ),
 ]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 """解析技术方案并创建编码任务"""
 config = context.node_config
 merge_same_branch = config.get("merge_same_branch", True)
 try:
 # 1. 获取上游技术方案数据
 plan_data = self._get_plan_data(context)
 if not plan_data:
 return NodeResult(
 status="failed",
 error="缺少技术方案输入，请确保上游 TechnicalPlanNode 已执行",
 next_handle="error",
 )
 # 2. 验证技术方案结构
 is_valid, error_msg = validate_technical_plan(plan_data)
 if not is_valid:
 return NodeResult(
 status="failed",
 error=f"技术方案验证失败: {error_msg}",
 next_handle="error",
 )
 # 3. 检查 execution_plan 非空
 execution_plan = plan_data.get("execution_plan", )
 if not execution_plan:
 return NodeResult(
 status="failed",
 error="execution_plan 为空，技术方案必须包含至少一个执行项",
 next_handle="error",
 )
 # 4. 预取仓库以避免 N+1
 repo_ids = {task["repository_id"] for task in execution_plan}
 repositories = await self._fetch_repositories(repo_ids)
 # 5. 验证所有仓库存在
 missing_repos = repo_ids - set(repositories.keys)
 if missing_repos:
 return NodeResult(
 status="failed",
 error=f"仓库不存在: {', '.join(missing_repos)}",
 next_handle="error",
 )
 # 6. 分组任务
 if merge_same_branch:
 task_groups = self._group_tasks(execution_plan)
 else:
 # 每个任务单独一组
 task_groups = {
 (task["repository_id"], task["branch_strategy"]): [task]
 for task in execution_plan
 }
 # 7. 获取全局上下文
 global_context = plan_data.get("global_context", "")
 # 8. 并行创建 CodingTasks
 create_coroutines = [
 self._create_coding_task(
 context, repositories[repo_id], tasks, global_context
 )
 for (repo_id, _), tasks in task_groups.items
 ]
 results = await asyncio.gather(*create_coroutines, return_exceptions=True)
 # 9. 处理结果
 return self._process_results(results, task_groups)
 except Exception as e:
 logger.error("coding_dispatcher_failed", error=str(e))
 return NodeResult(
 status="failed",
 error=str(e),
 next_handle="error",
 )
 def _get_plan_data(self, context: ExecutionContext) -> dict[str, Any] | None:
 """从上下文获取技术方案数据"""
 # 首先尝试从输入端口获取
 plan_data = context.get_previous_output("plan")
 if plan_data and isinstance(plan_data, dict):
 return plan_data
 # 尝试从全局参数获取 (向后兼容)
 plan_data = context.get_global_param("technical_plan")
 if plan_data and isinstance(plan_data, dict):
 return plan_data
 return None
 async def _fetch_repositories(
 self, repo_ids: set[str]
 ) -> dict[str, Repository]:
 """批量获取仓库对象"""
 return {
 str(r.id): r
 async for r in Repository.objects.filter(id__in=repo_ids, is_deleted=False)
 }
 def _group_tasks(
 self, execution_plan: list[dict[str, Any]]
 ) -> dict[tuple[str, str], list[dict[str, Any]]]:
 """按 (repository_id, branch_strategy) 分组任务"""
 groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
 for task in execution_plan:
 key = (task["repository_id"], task["branch_strategy"])
 groups.setdefault(key, ).append(task)
 return groups
 async def _create_coding_task(
 self,
 context: ExecutionContext,
 repository: Repository,
 tasks: list[dict[str, Any]],
 global_context: str,
 ) -> CodingTask:
 """创建单个 CodingTask (可能合并多个执行计划任务)"""
 workflow_execution = context.workflow_execution
 if not workflow_execution:
 raise ValueError("缺少 workflow_execution 上下文")
 # 提取任务 ID 列表
 execution_plan_ids = [task["id"] for task in tasks]
 # 构建任务名称
 if len(tasks) == 1:
 name = tasks[0].get("name", "未命名任务")
 description = tasks[0].get("description", "")
 else:
 name = f"合并任务: {repository.name} ({len(tasks)} 项)"
 description = "合并的任务:\n" + "\n".join(
 f"- {task.get('name', '未命名')}" for task in tasks
 )
 # 构建编码指令 (合并多个任务的指令)
 coding_instruction = self._build_merged_instruction(tasks)
 # 构建文件列表
 files_list = self._build_files_list(tasks)
 # 组合完整 Prompt
 prompt = self._compose_prompt(global_context, coding_instruction, files_list)
 # 创建 CodingTask
 coding_task = await CodingTask.objects.acreate(
 workflow_execution=workflow_execution,
 repository=repository,
 name=name,
 prompt=prompt,
 description=description,
 status=CodingTaskStatus.PENDING,
 execution_plan_ids=execution_plan_ids,
 global_context_snapshot=global_context,
 metadata={
 "branch_strategy": tasks[0].get("branch_strategy", "feature"),
 "task_count": len(tasks),
 "estimated_hours": sum(
 task.get("estimated_hours", 0) for task in tasks
 ),
 },
 )
 logger.info(
 "coding_task_created",
 task_id=str(coding_task.id),
 repository=repository.name,
 merged_count=len(tasks),
 )
 return coding_task
 def _build_merged_instruction(self, tasks: list[dict[str, Any]]) -> str:
 """构建合并后的编码指令"""
 if len(tasks) == 1:
 return tasks[0].get("coding_instruction", "") or tasks[0].get(
 "description", ""
 )
 instructions =
 for i, task in enumerate(tasks, 1):
 task_name = task.get("name", f"任务 {i}")
 instruction = task.get("coding_instruction", "") or task.get(
 "description", ""
 )
 instructions.append(f"## 任务 {i}: {task_name}\n\n{instruction}")
 return "\n\n---\n\n".join(instructions)
 def _build_files_list(self, tasks: list[dict[str, Any]]) -> str:
 """构建涉及的文件列表"""
 files_by_action: dict[str, list[str]] = {
 "create":,
 "modify":,
 "delete":,
 }
 for task in tasks:
 for file_info in task.get("files", ):
 action = file_info.get("action", "modify")
 path = file_info.get("path", "")
 if path and action in files_by_action:
 files_by_action[action].append(path)
 if not any(files_by_action.values):
 return ""
 lines = ["## 涉及文件"]
 for action, label in [
 ("create", "创建"),
 ("modify", "修改"),
 ("delete", "删除"),
 ]:
 if files_by_action[action]:
 lines.append(f"\n### {label}")
 for path in files_by_action[action]:
 lines.append(f"- `{path}`")
 return "\n".join(lines)
 def _compose_prompt(
 self, global_context: str, coding_instruction: str, files_list: str
 ) -> str:
 """组合完整的 AI 编码 Prompt"""
 parts =
 if global_context:
 parts.append(f"# 项目背景\n\n{global_context}")
 if coding_instruction:
 parts.append(f"# 编码任务\n\n{coding_instruction}")
 if files_list:
 parts.append(files_list)
 return "\n\n---\n\n".join(parts)
 def _process_results(
 self,
 results: list[CodingTask | BaseException],
 task_groups: dict[tuple[str, str], list[dict[str, Any]]],
 ) -> NodeResult:
 """处理并行创建结果，支持部分成功"""
 successful_tasks: list[CodingTask] =
 failed_details: list[dict[str, Any]] =
 group_keys = list(task_groups.keys)
 for i, result in enumerate(results):
 repo_id, branch_strategy = group_keys[i]
 if isinstance(result, BaseException):
 failed_details.append(
 {
 "repository_id": repo_id,
 "branch_strategy": branch_strategy,
 "error": str(result),
 }
 )
 else:
 successful_tasks.append(result)
 success_count = len(successful_tasks)
 failed_count = len(failed_details)
 total_count = success_count + failed_count
 # 构建输出
 output = {
 "tasks": [
 {
 "id": str(task.id),
 "name": task.name,
 "repository_id": str(task.repository_id),
 "status": task.status,
 "execution_plan_ids": task.execution_plan_ids,
 }
 for task in successful_tasks
 ],
 "task_count": success_count,
 "success_count": success_count,
 "failed_count": failed_count,
 }
 if failed_details:
 output["failed_details"] = failed_details
 # 决定返回状态
 if failed_count == total_count:
 # 全部失败
 return NodeResult(
 status="failed",
 error=f"所有 {total_count} 个任务创建失败",
 output=output,
 next_handle="error",
 )
 elif failed_count > 0:
 # 部分成功
 logger.warning(
 "coding_tasks_partial_success",
 success_count=success_count,
 failed_count=failed_count,
 )
 return NodeResult(
 status="partial_success",
 output=output,
 next_handle="default",
 )
 else:
 # 全部成功
 logger.info(
 "coding_tasks_created",
 task_count=success_count,
 )
 return NodeResult(
 status="completed",
 output=output,
 next_handle="default",
 )
