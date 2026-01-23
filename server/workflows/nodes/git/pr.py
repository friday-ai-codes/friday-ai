"""Git Pull Request operations nodes."""
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
class CreatePRNode(BaseNode):
 """创建 Pull Request 节点
 使用 GitHub CLI (gh) 创建 Pull Request。
 """
 node_type = "create_pr"
 display_name = "创建 PR"
 description = "创建 GitHub Pull Request"
 icon = "git-pull-request"
 category = NodeCategory.ACTION
 config_schema = {
 "type": "object",
 "properties": {
 "repository_path": {
 "type": "string",
 "title": "仓库路径",
 "description": "Git 仓库的本地路径",
 },
 "title": {
 "type": "string",
 "title": "PR 标题",
 "description": "Pull Request 标题，支持模板变量",
 },
 "body": {
 "type": "string",
 "title": "PR 描述",
 "description": "Pull Request 描述内容，支持模板变量",
 "default": "",
 },
 "base_branch": {
 "type": "string",
 "title": "目标分支",
 "description": "合并到哪个分支",
 "default": "main",
 },
 "head_branch": {
 "type": "string",
 "title": "源分支",
 "description": "从哪个分支合并，留空使用当前分支",
 "default": "",
 },
 "draft": {
 "type": "boolean",
 "title": "草稿 PR",
 "default": False,
 },
 "labels": {
 "type": "array",
 "title": "标签",
 "items": {"type": "string"},
 "default":,
 },
 "reviewers": {
 "type": "array",
 "title": "审核人",
 "items": {"type": "string"},
 "default":,
 },
 },
 "required": ["repository_path", "title"],
 }
 inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
 outputs = [
 NodePort(name="default", label="成功", port_type=PortType.OBJECT),
 NodePort(name="error", label="失败", port_type=PortType.OBJECT),
 ]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 config = context.node_config
 repo_path = context.render_template(config.get("repository_path", ""))
 title = context.render_template(config.get("title", ""))
 body = context.render_template(config.get("body", ""))
 base_branch = config.get("base_branch", "main")
 head_branch = config.get("head_branch", "")
 draft = config.get("draft", False)
 labels = config.get("labels", )
 reviewers = config.get("reviewers", )
 if not repo_path or not title:
 return NodeResult(
 status="failed",
 error="仓库路径和 PR 标题不能为空",
 next_handle="error",
 )
 try:
 # Build gh pr create command
 cmd = [
 "gh", "pr", "create",
 "--title", title,
 "--base", base_branch,
 ]
 if body:
 cmd.extend(["--body", body])
 if head_branch:
 cmd.extend(["--head", head_branch])
 if draft:
 cmd.append("--draft")
 for label in labels:
 cmd.extend(["--label", label])
 for reviewer in reviewers:
 cmd.extend(["--reviewer", reviewer])
 result = subprocess.run(
 cmd,
 cwd=repo_path,
 check=True,
 capture_output=True,
 text=True,
 )
 # Parse PR URL from output
 pr_url = result.stdout.strip
 return NodeResult(
 status="completed",
 output={
 "pr_url": pr_url,
 "title": title,
 "base_branch": base_branch,
 "head_branch": head_branch or "current",
 "draft": draft,
 },
 next_handle="default",
 )
 except subprocess.CalledProcessError as e:
 return NodeResult(
 status="failed",
 error=f"创建 PR 失败: {e.stderr or str(e)}",
 next_handle="error",
 )
 except Exception as e:
 return NodeResult(
 status="failed",
 error=str(e),
 next_handle="error",
 )
@register_node
class MergePRNode(BaseNode):
 """合并 Pull Request 节点
 使用 GitHub CLI (gh) 合并 Pull Request。
 """
 node_type = "merge_pr"
 display_name = "合并 PR"
 description = "合并 GitHub Pull Request"
 icon = "git-merge"
 category = NodeCategory.ACTION
 config_schema = {
 "type": "object",
 "properties": {
 "repository_path": {
 "type": "string",
 "title": "仓库路径",
 "description": "Git 仓库的本地路径",
 },
 "pr_number": {
 "type": ["integer", "string"],
 "title": "PR 编号",
 "description": "要合并的 PR 编号，支持模板变量",
 },
 "merge_method": {
 "type": "string",
 "title": "合并方式",
 "enum": ["merge", "squash", "rebase"],
 "default": "squash",
 },
 "delete_branch": {
 "type": "boolean",
 "title": "删除源分支",
 "default": True,
 },
 "auto_merge": {
 "type": "boolean",
 "title": "自动合并",
 "description": "当所有检查通过后自动合并",
 "default": False,
 },
 },
 "required": ["repository_path", "pr_number"],
 }
 inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
 outputs = [
 NodePort(name="default", label="成功", port_type=PortType.OBJECT),
 NodePort(name="error", label="失败", port_type=PortType.OBJECT),
 ]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 config = context.node_config
 repo_path = context.render_template(config.get("repository_path", ""))
 pr_number = context.render_template(str(config.get("pr_number", "")))
 merge_method = config.get("merge_method", "squash")
 delete_branch = config.get("delete_branch", True)
 auto_merge = config.get("auto_merge", False)
 if not repo_path or not pr_number:
 return NodeResult(
 status="failed",
 error="仓库路径和 PR 编号不能为空",
 next_handle="error",
 )
 try:
 if auto_merge:
 # Enable auto-merge
 cmd = [
 "gh", "pr", "merge", pr_number,
 "--auto",
 f"--{merge_method}",
 ]
 else:
 # Direct merge
 cmd = [
 "gh", "pr", "merge", pr_number,
 f"--{merge_method}",
 ]
 if delete_branch:
 cmd.append("--delete-branch")
 result = subprocess.run(
 cmd,
 cwd=repo_path,
 check=True,
 capture_output=True,
 text=True,
 )
 return NodeResult(
 status="completed",
 output={
 "pr_number": pr_number,
 "merge_method": merge_method,
 "deleted_branch": delete_branch,
 "auto_merge": auto_merge,
 "message": result.stdout.strip,
 },
 next_handle="default",
 )
 except subprocess.CalledProcessError as e:
 return NodeResult(
 status="failed",
 error=f"合并 PR 失败: {e.stderr or str(e)}",
 next_handle="error",
 )
 except Exception as e:
 return NodeResult(
 status="failed",
 error=str(e),
 next_handle="error",
 )
