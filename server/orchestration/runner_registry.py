"""全局 runner 注册表 — 用于 interrupt API 查找活跃 SDK runner。
从 conversation_service 提取为独立模块，消除 chat ↔ orchestration 循环依赖。
graph executing_node 注册，send_message_stream finally 注销。
"""
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
 from agents.sdk.runner import SDKAgentRunner
_active_runners: dict[str, "SDKAgentRunner"] = {}
def register_runner(conversation_id: str, runner: "SDKAgentRunner") -> None:
 """注册活跃 runner（executing_node 进入时调用）。"""
 _active_runners[conversation_id] = runner
def unregister_runner(conversation_id: str) -> None:
 """注销 runner（executing_node 退出时调用）。"""
 _active_runners.pop(conversation_id, None)
def get_active_runner(conversation_id: str) -> "SDKAgentRunner | None":
 """获取对话的活跃 runner（供 interrupt API 调用）。"""
 return _active_runners.get(conversation_id)
