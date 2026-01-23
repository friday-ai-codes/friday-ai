"""Git branch operations node."""
import subprocess
from workflows.nodes.base import (
 BaseNode,
 ExecutionContext,
 NodeCategory,
 NodePort,
 NodeResult,
 PortType,
)
from workflows.nodes.registry import register_node
@register_node
class CreateBranchNode(BaseNode):
 """创建 Git 分支节点
 在指定仓库中创建新分支。
 """
 node_type = "create_branch"
 display_name = "创建分支"
 description = "在 Git 仓库中创建新分支"
 icon = "git-branch"
 category = NodeCategory.ACTION
 config_schema = {
 "type": "object",
 "properties": {
 "repository_path": {
 "type": "string",
 "title": "仓库路径",
 "description": "Git 仓库的本地路径，支持模板变量",
 },
 "branch_name": {
 "type": "string",
 "title": "分支名称",
 "description": "新分支的名称，支持模板变量",
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
 "required": ["repository_path", "branch_name"],
 }
 inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
 outputs = [
 NodePort(name="default", label="成功", port_type=PortType.OBJECT),
 NodePort(name="error", label="失败", port_type=PortType.OBJECT),
 ]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 config = context.node_config
 repo_path = context.render_template(config.get("repository_path", ""))
 branch_name = context.render_template(config.get("branch_name", ""))
 base_branch = config.get("base_branch", "main")
 checkout = config.get("checkout", True)
 push = config.get("push", False)
 if not repo_path or not branch_name:
 return NodeResult(
 status="failed",
 error="仓库路径和分支名称不能为空",
 next_handle="error",
 )
 try:
 # Fetch latest
 subprocess.run(
 ["git", "fetch", "origin"],
 cwd=repo_path,
 check=True,
 capture_output=True,
 )
 # Create branch from base
 subprocess.run(
 ["git", "checkout", base_branch],
 cwd=repo_path,
 check=True,
 capture_output=True,
 )
 subprocess.run(
 ["git", "pull", "origin", base_branch],
 cwd=repo_path,
 check=True,
 capture_output=True,
 )
 # Create new branch
 if checkout:
 subprocess.run(
 ["git", "checkout", "-b", branch_name],
 cwd=repo_path,
 check=True,
 capture_output=True,
 )
 else:
 subprocess.run(
 ["git", "branch", branch_name],
 cwd=repo_path,
 check=True,
 capture_output=True,
 )
 # Push to remote if requested
 if push:
 subprocess.run(
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
