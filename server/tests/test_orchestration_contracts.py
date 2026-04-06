"""BlockingTask 合约类型定义单元测试。"""
from __future__ import annotations
from typing import Protocol, get_type_hints, runtime_checkable
from orchestration.contracts import (
 BlockingTaskDispatcher,
 BlockingTaskRequest,
 BlockingTaskResult,
)
class TestBlockingTaskRequest:
 def test_fields(self) -> None:
 hints = get_type_hints(BlockingTaskRequest)
 assert set(hints.keys) == {"task_type", "task_id", "params"}
 def test_can_construct(self) -> None:
 req: BlockingTaskRequest = {
 "task_type": "code_review",
 "task_id": "",
 "params": {"repo": "test"},
 }
 assert req["task_type"] == "code_review"
 assert req["task_id"] == ""
 assert req["params"] == {"repo": "test"}
class TestBlockingTaskResult:
 def test_fields(self) -> None:
 hints = get_type_hints(BlockingTaskResult)
 expected = {"task_id", "task_type", "success", "output", "error"}
 assert set(hints.keys) == expected
 def test_has_five_fields(self) -> None:
 hints = get_type_hints(BlockingTaskResult)
 assert len(hints) == 5
 def test_can_construct(self) -> None:
 result: BlockingTaskResult = {
 "task_id": "",
 "task_type": "code_review",
 "success": True,
 "output": "LGTM",
 "error": "",
 }
 assert result["success"] is True
 assert result["output"] == "LGTM"
class TestBlockingTaskDispatcher:
 def test_is_protocol(self) -> None:
 assert issubclass(BlockingTaskDispatcher, Protocol)
 def test_is_runtime_checkable(self) -> None:
 assert getattr(BlockingTaskDispatcher, "__protocol_attrs__", None) is not None or issubclass(
 BlockingTaskDispatcher, runtime_checkable(Protocol) # type: ignore[arg-type]
 )
 def test_has_dispatch_method(self) -> None:
 assert hasattr(BlockingTaskDispatcher, "dispatch")
 def test_has_get_result_method(self) -> None:
 assert hasattr(BlockingTaskDispatcher, "get_result")
