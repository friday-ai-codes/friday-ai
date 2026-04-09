"""CodingSession 专用 LangGraph StateGraph -- 三阶段 dispatch 编排。
拓扑: START -> dispatch_coding -> wait_coding_complete(interrupt)
 -> await_commit_confirm(interrupt) -> conflict_check -> dispatch_commit
 -> wait_commit_complete(interrupt)
 -> (conditional: failed->END, success->generate_pr_draft)
 -> generate_pr_draft -> await_pr_confirm(interrupt)
 -> create_pr_or_skip -> (conditional) -> END
Phase: 编码 dispatch + 等待完成
Phase: commit message 确认 + conflict_check 冲突预检 + commit dispatch + 等待完成
Phase: PR 草稿生成（LLM） + PR 确认/跳过 + PR 创建
每个 wait/await 节点使用 interrupt 暂停 graph，通过 Command(resume=...) 恢复。
interrupt 前只做幂等操作（UPDATE 同值），避免 resume 时重放副作用。
"""
from __future__ import annotations
import json
from typing import Any
import anthropic
import structlog
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from chat.coding_session_service import dispatch_coding_task
from chat.models import CodingSession
from orchestration.coding_state import CodingSessionState
logger = structlog.get_logger(__name__)
async def _get_coding_session(state: CodingSessionState) -> CodingSession:
 """从 state 中的 coding_session_id 查询 CodingSession（含 select_related）。"""
 return await CodingSession.objects.select_related(
 "repository", "conversation__project",
 ).aget(id=state["coding_session_id"])
async def dispatch_coding_node(state: CodingSessionState) -> dict[str, Any]:
 """Phase: dispatch 编码任务到 Runner。
 从 state 提取 coding_session_id，查询 CodingSession，
 构建 prompt 调用 dispatch_coding_task，返回 phase1_session_id。
 """
 coding_session = await _get_coding_session(state)
 project = coding_session.conversation.project
 repo = coding_session.repository
 prompt = (
 f"你正在对项目「{project.name}」的代码仓库「{repo.name}」执行编码任务。\n\n"
 f"技术方案：\n{coding_session.tech_plan}\n\n"
 f"请根据以上技术方案进行编码实现。"
 f"完成编码后执行 git add + git commit (使用临时 commit message) + git push，但不要创建 PR。"
 )
 session_id = await dispatch_coding_task(
 coding_session, task_type="coding", prompt=prompt,
 )
 logger.info(
 "coding_graph_dispatch_coding",
 coding_session_id=state["coding_session_id"],
 phase1_session_id=session_id,
 )
 return {"phase": "waiting_coding", "phase1_session_id": session_id}
async def wait_coding_complete_node(state: CodingSessionState) -> dict[str, Any]:
 """Phase 等待: interrupt 暂停，等待容器完成回调 resume。
 resume 值为 {"success": True/False, "suggested_commit_message": "..."} 或 {"success": False, "error": "..."}。
 成功时同步 CodingSession DB 状态为 awaiting_confirmation。
 失败时同步 CodingSession DB 状态为 failed。
 """
 result = interrupt({
 "waiting_for": "coding_complete",
 "coding_session_id": state["coding_session_id"],
 })
 coding_session = await _get_coding_session(state)
 if result.get("success"):
 suggested_msg = result.get("suggested_commit_message", "")
 await coding_session.amark_awaiting_confirmation("commit_message", suggested_msg)
 logger.info(
 "coding_graph_phase1_success",
 coding_session_id=state["coding_session_id"],
 suggested_commit_message=suggested_msg,
 )
 return {
 "phase": "awaiting_commit_confirm",
 "suggested_commit_message": suggested_msg,
 }
 error = result.get("error", "未知错误")
 await coding_session.amark_failed(error)
 logger.warning(
 "coding_graph_phase1_failed",
 coding_session_id=state["coding_session_id"],
 error=error,
 )
 return {"phase": "failed", "error": error}
async def await_commit_confirm_node(state: CodingSessionState) -> dict[str, Any]:
 """等待用户确认 commit message: interrupt 暂停等待用户确认。
 先同步 DB 状态为 awaiting_confirmation（幂等 UPDATE，resume 时重放安全）。
 resume 值为 confirmed_commit_message 字符串。
 resume 后同步 CodingSession DB 状态为 running。
 """
 confirmed_msg: str = interrupt({
 "waiting_for": "commit_confirm",
 "suggested_commit_message": state.get("suggested_commit_message", ""),
 })
 coding_session = await _get_coding_session(state)
 await coding_session.aresume_running
 logger.info(
 "coding_graph_commit_confirmed",
 coding_session_id=state["coding_session_id"],
 confirmed_commit_message=confirmed_msg,
 )
 return {"phase": "committing", "confirmed_commit_message": confirmed_msg}
async def conflict_check_node(state: CodingSessionState) -> dict[str, Any]:
 """冲突预检节点 -- 检查功能分支与 base 分支的潜在冲突（per ）。
 非阻断性: 任何错误都不阻止后续 dispatch_commit 流程（per ）。
 一次 compare 调用同时产出冲突预检和 diff 摘要数据（per ）。
 结果持久化到 CodingSession.conflict_check_result 和 diff_summary（per, ）。
 """
 coding_session = await _get_coding_session(state)
 repo = coding_session.repository
 try:
 from common.encryption import decrypt_value
 from repositories.models import GitCredential
 from services.git_platform import get_git_platform_client
 cred = await GitCredential.objects.filter(repository=repo).afirst
 if cred is None or not cred.encrypted_token:
 logger.info("conflict_check_no_credential", coding_session_id=state["coding_session_id"])
 return {"phase": "committing"}
 token = decrypt_value(cred.encrypted_token)
 client = get_git_platform_client(repo, token)
 result = await client.compare_branches(
 source_branch=coding_session.branch_name,
 target_branch=repo.default_branch,
 )
 if result.success:
 from django.utils import timezone
 suggestion = ""
 if result.has_potential_conflicts:
 suggestion = f"以下 {len(result.conflicting_files)} 个文件同时被修改，可能存在合并冲突，建议在 push 前本地解决"
 elif result.behind_by > 0:
 suggestion = f"目标分支有 {result.behind_by} 个新 commit，但未修改相同文件，预计可自动合并"
 conflict_data = {
 "has_conflicts": result.has_potential_conflicts,
 "conflicting_files": result.conflicting_files,
 "behind_by": result.behind_by,
 "suggestion": suggestion,
 "checked_at": timezone.now.isoformat,
 }
 coding_session.conflict_check_result = conflict_data
 diff_data = {
 "files": [
 {
 "path": f.path,
 "additions": f.additions,
 "deletions": f.deletions,
 "change_type": f.change_type,
 }
 for f in result.files
 ],
 "total_additions": result.total_additions,
 "total_deletions": result.total_deletions,
 "truncated": result.truncated,
 }
 coding_session.diff_summary = diff_data
 await coding_session.asave(update_fields=[
 "conflict_check_result", "diff_summary", "updated_at",
 ])
 logger.info(
 "conflict_check_completed",
 coding_session_id=state["coding_session_id"],
 has_conflicts=result.has_potential_conflicts,
 behind_by=result.behind_by,
 file_count=len(result.files),
 )
 else:
 logger.warning(
 "conflict_check_api_error",
 coding_session_id=state["coding_session_id"],
 error=result.error,
 )
 except Exception:
 logger.exception(
 "conflict_check_error",
 coding_session_id=state["coding_session_id"],
 )
 return {"phase": "committing"}
async def dispatch_commit_node(state: CodingSessionState) -> dict[str, Any]:
 """Phase: dispatch commit 修正任务到 Runner。
 使用 coding_commit task_type，通过 extra_metadata 传递用户确认的 commit message。
 容器 checkout 编码分支后执行 git commit --amend + git push --force-with-lease。
 """
 coding_session = await _get_coding_session(state)
 confirmed_msg = state["confirmed_commit_message"]
 prompt = (
 f"请 checkout 编码分支，执行以下操作：\n"
 f"1. git commit --amend -m \"{confirmed_msg}\"\n"
 f"2. git push --force-with-lease\n"
 f"3. 创建 PR\n"
 )
 session_id = await dispatch_coding_task(
 coding_session,
 task_type="coding_commit",
 extra_metadata={"env_FRIDAY_TASK_COMMIT_MESSAGE": confirmed_msg},
 prompt=prompt,
 )
 logger.info(
 "coding_graph_dispatch_commit",
 coding_session_id=state["coding_session_id"],
 phase2_session_id=session_id,
 )
 return {"phase": "waiting_commit", "phase2_session_id": session_id}
async def wait_commit_complete_node(state: CodingSessionState) -> dict[str, Any]:
 """Phase 等待: interrupt 暂停，等待 commit 容器完成回调 resume。
 resume 值为 {"success": True/False}。
 成功时保持 running 状态（后续 generate_pr_draft 处理）。
 失败时同步 CodingSession DB 状态为 failed。
 """
 result = interrupt({
 "waiting_for": "commit_complete",
 "coding_session_id": state["coding_session_id"],
 })
 coding_session = await _get_coding_session(state)
 if result.get("success"):
 # 成功时不再调用 amark_completed，保持 running 状态让后续 generate_pr_draft 处理
 logger.info(
 "coding_graph_phase2_success",
 coding_session_id=state["coding_session_id"],
 )
 return {"phase": "pr_pending"}
 error = result.get("error", "未知错误")
 await coding_session.amark_failed(error)
 logger.warning(
 "coding_graph_phase2_failed",
 coding_session_id=state["coding_session_id"],
 error=error,
 )
 return {"phase": "failed", "error": error}
# ---------------------------------------------------------------------------
# Phase: PR 草稿生成 + 确认 + 创建/跳过
# ---------------------------------------------------------------------------
async def _call_llm_for_pr_draft(
 coding_session: CodingSession,
 confirmed_commit_message: str,
) -> tuple[str, str]:
 """调用 LLM 生成 PR 标题和描述。
 Returns:
 (title, description) 元组。
 """
 from chat.services import aget_setting_value
 from system.models import SettingKeys
 api_key = await aget_setting_value(SettingKeys.ANTHROPIC_API_KEY)
 base_url = await aget_setting_value(SettingKeys.ANTHROPIC_BASE_URL)
 model = await aget_setting_value(SettingKeys.ANTHROPIC_MODEL) or "claude-sonnet-4-20250514"
 if not api_key:
 raise ValueError("Anthropic API key 未配置")
 if base_url:
 client = anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url)
 else:
 client = anthropic.AsyncAnthropic(api_key=api_key)
 # 构建 prompt
 affected_files_str = ""
 if coding_session.affected_files:
 affected_files_str = "\n".join(
 f"- {f.get('path', '')} ({f.get('change_type', '')})"
 for f in coding_session.affected_files[:20]
 )
 prompt = (
 "根据以下编码任务信息，生成一个 Pull Request 的标题和描述。\n\n"
 f"## 技术方案\n{coding_session.tech_plan}\n\n"
 f"## Commit Message\n{confirmed_commit_message}\n\n"
 f"## 影响文件\n{affected_files_str}\n\n"
 "请以 JSON 格式返回，格式如下：\n"
 '{"title": "简洁的 PR 标题（不超过 100 字符）", "description": "详细的 PR 描述（Markdown 格式）"}\n\n'
 "只返回 JSON，不要其他文字。"
 )
 response = await client.messages.create(
 model=model,
 max_tokens=1000,
 messages=[{"role": "user", "content": prompt}],
 )
 text = response.content[0].text.strip # type: ignore[union-attr]
 # 尝试 JSON 解析
 try:
 data = json.loads(text)
 return data.get("title", "")[:200], data.get("description", "")
 except (json.JSONDecodeError, KeyError):
 # 尝试从文本提取
 lines = text.strip.split("\n")
 title = lines[0][:200] if lines else ""
 description = "\n".join(lines[1:]) if len(lines) > 1 else ""
 return title, description
def build_branch_url(git_url: str, git_platform: str, branch_name: str) -> str:
 """构建分支 URL。"""
 from services.git_platform import extract_github_owner_repo, extract_gitlab_url, extract_project_path
 if git_platform == "github":
 try:
 owner, repo = extract_github_owner_repo(git_url)
 return f"https://github.com/{owner}/{repo}/tree/{branch_name}"
 except ValueError:
 return ""
 elif git_platform == "gitlab":
 try:
 base_url = extract_gitlab_url(git_url)
 project_path = extract_project_path(git_url)
 return f"{base_url}/{project_path}/-/tree/{branch_name}"
 except ValueError:
 return ""
 return ""
async def generate_pr_draft_node(state: CodingSessionState) -> dict[str, Any]:
 """Phase 步骤 1: 使用 LLM 生成 PR 草稿标题和描述。
 幂等检查: 如果 CodingSession.suggested_pr_title 已有值则跳过 LLM 调用。
 LLM 失败时使用 fallback 模板（不标记 failed）。
 """
 coding_session = await _get_coding_session(state)
 confirmed_msg = state.get("confirmed_commit_message", "")
 # 幂等检查
 if coding_session.suggested_pr_title:
 title = coding_session.suggested_pr_title
 description = coding_session.suggested_pr_description
 logger.info(
 "coding_graph_pr_draft_idempotent",
 coding_session_id=state["coding_session_id"],
 )
 else:
 try:
 title, description = await _call_llm_for_pr_draft(coding_session, confirmed_msg)
 if not title:
 raise ValueError("LLM 返回空标题")
 except Exception:
 logger.exception(
 "coding_graph_pr_draft_llm_failed",
 coding_session_id=state["coding_session_id"],
 )
 # fallback: commit message 第一行作为 title，tech_plan 前 500 字符作为 description
 first_line = confirmed_msg.split("\n")[0] if confirmed_msg else "PR"
 title = first_line[:200]
 description = (coding_session.tech_plan or "")[:500]
 # 持久化到 DB
 coding_session.suggested_pr_title = title
 coding_session.suggested_pr_description = description
 await coding_session.asave(update_fields=[
 "suggested_pr_title", "suggested_pr_description", "updated_at",
 ])
 # 标记等待 PR 确认
 await coding_session.amark_awaiting_confirmation("pr_review")
 logger.info(
 "coding_graph_pr_draft_generated",
 coding_session_id=state["coding_session_id"],
 title=title[:50],
 )
 return {
 "phase": "awaiting_pr_confirm",
 "suggested_pr_title": title,
 "suggested_pr_description": description,
 "target_branch": coding_session.repository.default_branch,
 }
async def await_pr_confirm_node(state: CodingSessionState) -> dict[str, Any]:
 """Phase 步骤 2: interrupt 等待用户确认 PR 操作（创建 or 跳过）。
 resume 值为 dict:
 - skip_pr=True: 跳过 PR 创建
 - skip_pr=False: 创建 PR，包含 title/description/target_branch
 """
 result: dict[str, Any] = interrupt({
 "waiting_for": "pr_confirm",
 "suggested_pr_title": state.get("suggested_pr_title", ""),
 "suggested_pr_description": state.get("suggested_pr_description", ""),
 })
 coding_session = await _get_coding_session(state)
 if result.get("skip_pr"):
 return {"phase": "skipping_pr", "skip_pr": True}
 await coding_session.aresume_running
 return {
 "phase": "creating_pr",
 "skip_pr": False,
 "confirmed_pr_title": result["title"],
 "confirmed_pr_description": result["description"],
 "target_branch": result.get("target_branch", state.get("target_branch", "")),
 }
async def create_pr_or_skip_node(state: CodingSessionState) -> dict[str, Any]:
 """Phase 步骤 3: 根据用户选择创建 PR 或跳过。
 Skip 路径: 标记 completed + 返回 branch_url + 调用 store_coding_complete_to_message
 创建 PR 路径: 通过 GitPlatformClient 创建 PR
 """
 from chat.coding_events import store_coding_complete_to_message
 from common.encryption import decrypt_value
 from repositories.models import GitCredential
 from services.git_platform import get_git_platform_client
 from services.git_platform.models import MRCreateRequest
 coding_session = await _get_coding_session(state)
 repo = coding_session.repository
 if state.get("skip_pr"):
 # Skip 路径
 branch_url = build_branch_url(
 repo.git_url, repo.git_platform, coding_session.branch_name,
 )
 await coding_session.amark_completed(pr_url="")
 await store_coding_complete_to_message(coding_session, branch_url=branch_url)
 logger.info(
 "coding_graph_pr_skipped",
 coding_session_id=state["coding_session_id"],
 branch_url=branch_url,
 )
 return {"phase": "completed", "branch_url": branch_url}
 # 创建 PR 路径
 try:
 cred = await GitCredential.objects.aget(repository=repo)
 token = decrypt_value(cred.encrypted_token or "")
 except GitCredential.DoesNotExist:
 error_msg = "Git 凭据未配置，无法创建 PR"
 await coding_session.amark_failed(error_msg)
 logger.warning(
 "coding_graph_pr_no_credential",
 coding_session_id=state["coding_session_id"],
 )
 return {"phase": "failed", "error": error_msg}
 client = get_git_platform_client(repo, token)
 mr_request = MRCreateRequest(
 source_branch=coding_session.branch_name,
 target_branch=state.get("target_branch", repo.default_branch),
 title=state["confirmed_pr_title"],
 description=state["confirmed_pr_description"],
 )
 result = await client.create_merge_request(mr_request)
 if result.success:
 await coding_session.amark_completed(pr_url=result.mr_url)
 await store_coding_complete_to_message(coding_session)
 logger.info(
 "coding_graph_pr_created",
 coding_session_id=state["coding_session_id"],
 pr_url=result.mr_url,
 )
 return {"phase": "completed", "pr_url": result.mr_url}
 await coding_session.amark_failed(result.error)
 logger.warning(
 "coding_graph_pr_creation_failed",
 coding_session_id=state["coding_session_id"],
 error=result.error,
 )
 return {"phase": "failed", "error": result.error}
# ---------------------------------------------------------------------------
# 条件路由
# ---------------------------------------------------------------------------
def route_after_coding(state: CodingSessionState) -> str:
 """条件路由: Phase 失败 -> END, 否则 -> await_commit_confirm。"""
 if state.get("phase") == "failed":
 return END
 return "await_commit_confirm"
def route_after_commit(state: CodingSessionState) -> str:
 """条件路由: Phase 失败 -> END, 成功 -> generate_pr_draft。"""
 if state.get("phase") == "failed":
 return END
 return "generate_pr_draft"
def route_after_pr(state: CodingSessionState) -> str:
 """条件路由: PR 创建/跳过后 -> END。"""
 return END
def build_coding_graph -> StateGraph:
 """构建 CodingSession 编排 StateGraph builder。
 拓扑（三阶段）:
 START -> dispatch_coding -> wait_coding_complete
 -> (conditional: failed->END, success->await_commit_confirm)
 -> await_commit_confirm -> conflict_check -> dispatch_commit -> wait_commit_complete
 -> (conditional: failed->END, success->generate_pr_draft)
 -> generate_pr_draft -> await_pr_confirm -> create_pr_or_skip
 -> (conditional) -> END
 """
 builder: StateGraph = StateGraph(CodingSessionState)
 # Phase + 2 原有节点
 builder.add_node("dispatch_coding", dispatch_coding_node)
 builder.add_node("wait_coding_complete", wait_coding_complete_node)
 builder.add_node("await_commit_confirm", await_commit_confirm_node)
 builder.add_node("conflict_check", conflict_check_node)
 builder.add_node("dispatch_commit", dispatch_commit_node)
 builder.add_node("wait_commit_complete", wait_commit_complete_node)
 # Phase 新增节点
 builder.add_node("generate_pr_draft", generate_pr_draft_node)
 builder.add_node("await_pr_confirm", await_pr_confirm_node)
 builder.add_node("create_pr_or_skip", create_pr_or_skip_node)
 # Phase 边
 builder.add_edge(START, "dispatch_coding")
 builder.add_edge("dispatch_coding", "wait_coding_complete")
 builder.add_conditional_edges("wait_coding_complete", route_after_coding)
 # Phase 边
 builder.add_edge("await_commit_confirm", "conflict_check")
 builder.add_edge("conflict_check", "dispatch_commit")
 builder.add_edge("dispatch_commit", "wait_commit_complete")
 builder.add_conditional_edges("wait_commit_complete", route_after_commit)
 # Phase 边
 builder.add_edge("generate_pr_draft", "await_pr_confirm")
 builder.add_edge("await_pr_confirm", "create_pr_or_skip")
 builder.add_conditional_edges("create_pr_or_skip", route_after_pr)
 return builder
