from __future__ import annotations

from typing import Any, Protocol, TypedDict


class BlockingTaskRequest(TypedDict):
    """发起阻塞任务的请求结构 — 作为 interrupt() 的 payload。"""

    task_type: str
    task_id: str
    params: dict[str, Any]


class BlockingTaskResult(TypedDict):
    """阻塞任务完成后的结果 — 作为 Command(resume=...) 的值。"""

    task_id: str
    task_type: str
    success: bool
    output: str
    error: str


class BlockingTaskDispatcher(Protocol):
    """阻塞任务分发器协议 — 定义统一的任务分发接口。"""

    async def dispatch(self, request: BlockingTaskRequest) -> str:
        """分发任务，返回任务标识。"""
        ...

    async def get_result(self, task_id: str) -> BlockingTaskResult | None:
        """查询任务结果，未完成返回 None。"""
        ...
