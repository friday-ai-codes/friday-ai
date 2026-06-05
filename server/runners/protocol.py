"""Runner WebSocket 消息协议定义。"""

import enum
import uuid


class MessageType(str, enum.Enum):
    """所有 Runner <-> Server 消息类型。"""

    # Runner -> Server
    RUNNER_HELLO = "runner.hello"
    RUNNER_HEARTBEAT = "runner.heartbeat"
    RUNNER_BYE = "runner.bye"
    TASK_ACCEPTED = "task.accepted"
    TASK_REJECTED = "task.rejected"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_LOG = "task.log"
    TASK_PROGRESS = "task.progress"
    TASK_QUESTION = "task.question"
    TASK_TOKEN_USAGE = "task.token_usage"

    # Server -> Runner
    TASK_ASSIGN = "task.assign"
    TASK_CANCEL = "task.cancel"
    QUESTION_ANSWER = "question.answer"
    TOOL_CALL = "tool.call"
    TOOL_RESULT = "tool.result"


def make_message(type: str, payload: dict, id: str | None = None) -> dict:
    """构造消息。"""
    msg: dict = {"type": type, "payload": payload}
    if id is not None:
        msg["id"] = id
    return msg


def make_request(type: str, payload: dict) -> dict:
    """构造带自动生成 ID 的请求消息。"""
    return make_message(type, payload, id=str(uuid.uuid4()))


def make_response(request_id: str, type: str, payload: dict) -> dict:
    """构造关联原始请求的响应消息。"""
    msg = make_message(type, payload)
    msg["ref"] = request_id
    return msg
