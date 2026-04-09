"""CodingSession 专用 LangGraph StateGraph -- 两阶段 dispatch 编排。
拓扑: START -> dispatch_coding -> wait_coding_complete(interrupt)
 -> await_commit_confirm(interrupt) -> dispatch_commit
 -> wait_commit_complete(interrupt) -> END
每个 wait/await 节点使用 interrupt 暂停 graph，通过 Command(resume=...) 恢复。
interrupt 前只做幂等操作（UPDATE 同值），避免 resume 时重放副作用。
"""
from __future__ import annotations
from typing import Any
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
 成功时同步 CodingSession DB 状态为 completed。
 失败时同步 CodingSession DB 状态为 failed。
 """
 result = interrupt({
 "waiting_for": "commit_complete",
 "coding_session_id": state["coding_session_id"],
 })
 coding_session = await _get_coding_session(state)
 if result.get("success"):
 pr_url = result.get("pr_url", "")
 await coding_session.amark_completed(pr_url=pr_url)
 logger.info(
 "coding_graph_phase2_success",
 coding_session_id=state["coding_session_id"],
 )
 return {"phase": "completed"}
 error = result.get("error", "未知错误")
 await coding_session.amark_failed(error)
 logger.warning(
 "coding_graph_phase2_failed",
 coding_session_id=state["coding_session_id"],
 error=error,
 )
 return {"phase": "failed", "error": error}
def route_after_coding(state: CodingSessionState) -> str:
 """条件路由: Phase 失败 -> END, 否则 -> await_commit_confirm。"""
 if state.get("phase") == "failed":
 return END
 return "await_commit_confirm"
def route_after_commit(state: CodingSessionState) -> str:
 """条件路由: Phase 完成或失败都 -> END。"""
 return END
def build_coding_graph -> StateGraph:
 """构建 CodingSession 编排 StateGraph builder。
 拓扑: START -> dispatch_coding -> wait_coding_complete
 -> (conditional) -> await_commit_confirm -> dispatch_commit
 -> wait_commit_complete -> (conditional) -> END
 """
 builder: StateGraph = StateGraph(CodingSessionState)
 builder.add_node("dispatch_coding", dispatch_coding_node)
 builder.add_node("wait_coding_complete", wait_coding_complete_node)
 builder.add_node("await_commit_confirm", await_commit_confirm_node)
 builder.add_node("dispatch_commit", dispatch_commit_node)
 builder.add_node("wait_commit_complete", wait_commit_complete_node)
 builder.add_edge(START, "dispatch_coding")
 builder.add_edge("dispatch_coding", "wait_coding_complete")
 builder.add_conditional_edges("wait_coding_complete", route_after_coding)
 builder.add_edge("await_commit_confirm", "dispatch_commit")
 builder.add_edge("dispatch_commit", "wait_commit_complete")
 builder.add_conditional_edges("wait_commit_complete", route_after_commit)
 return builder
