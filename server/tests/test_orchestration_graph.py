from __future__ import annotations
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from orchestration.graph import build_graph
@pytest.mark.asyncio
async def test_graph_compiles -> None:
 """: StateGraph 可编译为可运行 workflow。"""
 graph = build_graph.compile(checkpointer=MemorySaver)
 assert graph is not None
@pytest.mark.asyncio
async def test_normal_flow_without_blocking -> None:
 """: 无阻塞任务时 graph 完整执行 planning → executing → finalizing。"""
 graph = build_graph.compile(checkpointer=MemorySaver)
 config = {"configurable": {"thread_id": "test-normal-1"}}
 result = await graph.ainvoke(
 {"user_message": "hello", "run_id": "test-run-1"},
 config=config,
 )
 assert result["phase"] == "completed"
 assert "hello" in result["final_answer"]
@pytest.mark.asyncio
async def test_interrupt_pauses_on_blocking_tasks -> None:
 """: 有阻塞任务时 graph 在 waiting 节点暂停。"""
 graph = build_graph.compile(checkpointer=MemorySaver)
 config = {"configurable": {"thread_id": "test-interrupt-1"}}
 blocking = [{"task_type": "code_review", "task_id": "", "params": {}}]
 result = await graph.ainvoke(
 {"user_message": "review this", "run_id": "run-int-1", "blocking_tasks": blocking},
 config=config,
 )
 assert result["phase"] == "waiting"
 state = await graph.aget_state(config)
 assert "waiting" in state.next
 assert any(t.interrupts for t in state.tasks)
@pytest.mark.asyncio
async def test_resume_continues_after_interrupt -> None:
 """: Command(resume=...) 恢复 graph 并传入结果。"""
 graph = build_graph.compile(checkpointer=MemorySaver)
 config = {"configurable": {"thread_id": "test-resume-1"}}
 blocking = [{"task_type": "code_review", "task_id": "", "params": {}}]
 await graph.ainvoke(
 {"user_message": "review this", "run_id": "run-res-1", "blocking_tasks": blocking},
 config=config,
 )
 result = await graph.ainvoke(
 Command(resume={"task_id": "", "output": "review approved"}),
 config=config,
 )
 assert result["phase"] == "completed"
 assert result["final_answer"] == "review approved"
 assert result["blocking_tasks"] ==
@pytest.mark.asyncio
async def test_phase_transitions -> None:
 """: graph state 中 phase 字段在每个节点正确转换。"""
 graph = build_graph.compile(checkpointer=MemorySaver)
 config = {"configurable": {"thread_id": "test-phases-1"}}
 result = await graph.ainvoke(
 {"user_message": "hello", "run_id": "run-Phase"},
 config=config,
 )
 assert result["phase"] == "completed"
 phases_seen: list[str] =
 async for snapshot in graph.aget_state_history(config):
 p = snapshot.values.get("phase")
 if p and (not phases_seen or phases_seen[-1] != p):
 phases_seen.append(p)
 phases_seen.reverse
 assert phases_seen == ["executing", "finalizing", "completed"]
@pytest.mark.asyncio
async def test_graph_state_is_authoritative -> None:
 """: graph checkpoint 保存的 state 为 authoritative source。"""
 graph = build_graph.compile(checkpointer=MemorySaver)
 config = {"configurable": {"thread_id": "test-auth-1"}}
 await graph.ainvoke(
 {"user_message": "hello", "run_id": "run-auth-1"},
 config=config,
 )
 state = await graph.aget_state(config)
 assert state.values["phase"] == "completed"
 assert state.values["run_id"] == "run-auth-1"
 assert state.values["user_message"] == "hello"
