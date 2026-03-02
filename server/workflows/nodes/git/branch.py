"""Git branch operations node."""
from __future__ import annotations
import asyncio
import subprocess
from typing import TYPE_CHECKING, Any
import structlog
from friday.settings import DATA_DIR
if TYPE_CHECKING:
 from repositories.models import Repository
from workflows.nodes.base import (
 BaseNode,
 ExecutionContext,
 NodeCategory,
 NodePort,
 NodeResult,
 PortType,
 normalize_repositories,
)
from workflows.nodes.registry import register_node
logger = structlog.get_logger(__name__)
@register_node
class CreateBranchNode(BaseNode):
 """创建 Git 分支节点
 在指定仓库中创建新分支，支持多仓库并行执行。
 """
 node_type = "create_branch"
 display_name = "创建分支"
 description = "在 Git 仓库中创建新分支，支持多仓库并行"
 icon = "git-branch"
 category = NodeCategory.ACTION
 execution_mode = "server_local"
 config_schema = {
 "type": "object",
 "properties": {
 "repositories": {
 "oneOf": [
 {
 "type": "array",
 "title": "仓库列表",
 "description": "代码仓库 ID 列表或模板变量",
 "items": {"type": "string"},
 },
 {
 "type": "string",
 "title": "仓库引用",
 "description": "单个仓库 ID 或模板变量如 {{global.repositories}}",
 },
 ],
 },
 "repository_path": {
 "type": "string",
 "title": "仓库路径 (已弃用)",
 "description": "Git 仓库的本地路径，建议使用 repositories 字段",
 },
 "branch_name": {
 "type": "string",
 "title": "分支名称",
 "description": "新分支的名称，支持模板变量，对所有仓库统一",
 },
 "base_branch": {
 "type": "string",
 "title": "基础分支",
 "description": "基于哪个分支创建，默认 main",
 "default": "main",
 },
 "checkout": {
 "type": "boolean",
 "title": "切换到新分支",
 "default": True,
 },
 "push": {
 "type": "boolean",
 "title": "推送到远程",
 "default": False,
 },
 },
 "required": ["branch_name"],
 }
 inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
 outputs = [
 NodePort(name="default", label="成功", port_type=PortType.OBJECT),
 NodePort(name="error", label="失败", port_type=PortType.OBJECT),
 ]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 config = context.node_config
 branch_name = context.render_template(config.get("branch_name", ""))
 base_branch = config.get("base_branch", "main")
 checkout = config.get("checkout", True)
 push = config.get("push", False)
 if not branch_name:
 return NodeResult(
 status="failed",
 error="分支名称不能为空",
 next_handle="error",
 )
 # 规范化仓库配置（支持单个/列表、模板变量）
 repo_configs = normalize_repositories(config, context)
 # 向后兼容：如果没有 repositories 配置但有 repository_path，使用旧逻辑
 if not repo_configs:
 repo_path = context.render_template(config.get("repository_path", ""))
 if repo_path:
 return await self._execute_single_repo_legacy(
 repo_path, branch_name, base_branch, checkout, push
 )
 return NodeResult(
 status="failed",
 error="必须指定 repositories 或 repository_path",
 next_handle="error",
 )
 # 解析仓库 ID 并验证存在性
 from repositories.models import Repository
 valid_repos: list[Repository] =
 invalid_ids: list[str] =
 for repo_info in repo_configs:
 repo_id = repo_info.get("id") or repo_info.get("name")
 if not repo_id:
 continue
 # 查找仓库
 repo = await Repository.objects.filter(
 id=repo_id, is_deleted=False
 ).afirst
 if repo is None:
 repo = await Repository.objects.filter(name=repo_id, is_deleted=False).afirst
 if repo:
 valid_repos.append(repo)
 else:
 invalid_ids.append(str(repo_id))
 # 记录无效仓库警告
 if invalid_ids:
 logger.warning(
 "skipped_invalid_repositories",
 invalid_ids=invalid_ids,
 valid_count=len(valid_repos),
 )
 # 处理全部无效的情况
 if not valid_repos:
 return NodeResult(
 status="failed",
 error=f"所有仓库都无效: {invalid_ids}",
 next_handle="error",
 )
 logger.info(
 "batch_create_branch_start",
 branch_name=branch_name,
 base_branch=base_branch,
 repository_count=len(valid_repos),
 push=push,
 )
 # 并行创建分支
 results = await self._create_branches_parallel(
 valid_repos, branch_name, base_branch, checkout, push
 )
 # 分离成功和失败结果
 succeeded: list[dict[str, Any]] =
 failed: list[dict[str, Any]] =
 for result in results:
 if result["status"] == "success":
 succeeded.append({
 "repository_id": result["repository_id"],
 "repository_name": result["repository_name"],
 "branch_name": result["branch_name"],
 })
 else:
 failed.append({
 "repository_id": result["repository_id"],
 "repository_name": result["repository_name"],
 "error": result.get("error", "Unknown error"),
 })
 # 添加被跳过的无效仓库到失败列表
 for invalid_id in invalid_ids:
 failed.append({
 "repository_id": invalid_id,
 "repository_name": invalid_id,
 "error": "仓库不存在或已删除",
 })
 logger.info(
 "batch_create_branch_completed",
 branch_name=branch_name,
 succeeded_count=len(succeeded),
 failed_count=len(failed),
 )
 output: dict[str, Any] = {
 "branch_name": branch_name,
 "base_branch": base_branch,
 "total": len(repo_configs),
 "succeeded": succeeded,
 "failed": failed,
 "all_succeeded": len(failed) == 0,
 }
 # 即使有部分失败也返回成功，让工作流继续
 return NodeResult(
 status="completed",
 output=output,
 next_handle="default",
 )
 async def _execute_single_repo_legacy(
 self,
 repo_path: str,
 branch_name: str,
 base_branch: str,
 checkout: bool,
 push: bool,
 ) -> NodeResult:
 """向后兼容：使用 repository_path 的单仓库模式"""
 try:
 # Fetch latest
 await asyncio.to_thread(
 subprocess.run,
 ["git", "fetch", "origin"],
 cwd=repo_path,
 check=True,
 capture_output=True,
 )
 # Checkout base branch
 await asyncio.to_thread(
 subprocess.run,
 ["git", "checkout", base_branch],
 cwd=repo_path,
 check=True,
 capture_output=True,
 )
 # Pull latest
 await asyncio.to_thread(
 subprocess.run,
 ["git", "pull", "origin", base_branch],
 cwd=repo_path,
 check=True,
 capture_output=True,
 )
 # Create new branch
 if checkout:
 await asyncio.to_thread(
 subprocess.run,
 ["git", "checkout", "-b", branch_name],
 cwd=repo_path,
 check=True,
 capture_output=True,
 )
 else:
 await asyncio.to_thread(
 subprocess.run,
 ["git", "branch", branch_name],
 cwd=repo_path,
 check=True,
 capture_output=True,
 )
 # Push to remote if requested
 if push:
 await asyncio.to_thread(
 subprocess.run,
 ["git", "push", "-u", "origin", branch_name],
 cwd=repo_path,
 check=True,
 capture_output=True,
 )
 return NodeResult(
 status="completed",
 output={
 "branch_name": branch_name,
 "base_branch": base_branch,
 "repository_path": repo_path,
 "pushed": push,
 },
 next_handle="default",
 )
 except subprocess.CalledProcessError as e:
 return NodeResult(
 status="failed",
 error=f"Git 操作失败: {e.stderr.decode if e.stderr else str(e)}",
 next_handle="error",
 )
 except Exception as e:
 return NodeResult(
 status="failed",
 error=str(e),
 next_handle="error",
 )
 async def _create_branch_for_repository(
 self,
 repository: "Repository",
 branch_name: str,
 base_branch: str,
 checkout: bool,
 push: bool,
 ) -> dict[str, Any]:
 """Create branch for a single repository.
 Returns a dict with repository_id, repository_name, status, branch_name, and error (if any).
 """
 repo_id = str(repository.id)
 repo_name = repository.name
 try:
 # Get repository local path from DATA_DIR/repos/{repo_id}
 repo_path = DATA_DIR / "repos" / repo_id
 if not repo_path.exists:
 return {
 "repository_id": repo_id,
 "repository_name": repo_name,
 "status": "error",
 "branch_name": branch_name,
 "error": "仓库本地路径不存在，请先克隆仓库",
 }
 repo_path_str = str(repo_path)
 # Fetch latest
 await asyncio.to_thread(
 subprocess.run,
 ["git", "fetch", "origin"],
 cwd=repo_path_str,
 check=True,
 capture_output=True,
 )
 # Checkout base branch
 await asyncio.to_thread(
 subprocess.run,
 ["git", "checkout", base_branch],
 cwd=repo_path_str,
 check=True,
 capture_output=True,
 )
 # Pull latest
 await asyncio.to_thread(
 subprocess.run,
 ["git", "pull", "origin", base_branch],
 cwd=repo_path_str,
 check=True,
 capture_output=True,
 )
 # Create new branch
 if checkout:
 await asyncio.to_thread(
 subprocess.run,
 ["git", "checkout", "-b", branch_name],
 cwd=repo_path_str,
 check=True,
 capture_output=True,
 )
 else:
 await asyncio.to_thread(
 subprocess.run,
 ["git", "branch", branch_name],
 cwd=repo_path_str,
 check=True,
 capture_output=True,
 )
 # Push to remote if requested
 if push:
 await asyncio.to_thread(
 subprocess.run,
 ["git", "push", "-u", "origin", branch_name],
 cwd=repo_path_str,
 check=True,
 capture_output=True,
 )
 return {
 "repository_id": repo_id,
 "repository_name": repo_name,
 "status": "success",
 "branch_name": branch_name,
 }
 except subprocess.CalledProcessError as e:
 error_msg = e.stderr.decode if e.stderr else str(e)
 return {
 "repository_id": repo_id,
 "repository_name": repo_name,
 "status": "error",
 "branch_name": branch_name,
 "error": f"Git 操作失败: {error_msg}",
 }
 except Exception as e:
 return {
 "repository_id": repo_id,
 "repository_name": repo_name,
 "status": "error",
 "branch_name": branch_name,
 "error": str(e),
 }
 async def _create_branches_parallel(
 self,
 repositories: list["Repository"],
 branch_name: str,
 base_branch: str,
 checkout: bool,
 push: bool,
 ) -> list[dict[str, Any]]:
 """Create branches in all repositories in parallel.
 Uses asyncio.gather with return_exceptions=True to ensure all tasks complete.
 Any unexpected exceptions are converted to error dicts.
 """
 tasks = [
 self._create_branch_for_repository(
 repo, branch_name, base_branch, checkout, push
 )
 for repo in repositories
 ]
 # gather with return_exceptions=True ensures all tasks complete
 results = await asyncio.gather(*tasks, return_exceptions=True)
 # Convert any unexpected exceptions to error dicts
 processed: list[dict[str, Any]] =
 for i, result in enumerate(results):
 if isinstance(result, Exception):
 processed.append({
 "repository_id": str(repositories[i].id),
 "repository_name": repositories[i].name,
 "status": "error",
 "branch_name": branch_name,
 "error": str(result),
 })
 else:
 processed.append(result)
 return processed
