"""编码遇阻 HITL：ask_user 进程内 SDK MCP 工具 + 等待回答循环（Phase 47，HITL-01a）。

编码 agent 遇阻无法自解时，经 ``ask_user`` 工具向人发起提问并**阻塞等待回答**——
复用既有 question 协议契约（``CallbackClient.report_question`` → server ``type=question``）
与既有 ``answer.json`` 共享卷回灌协议（``/workspace/.friday/answer.json``）。

设计约束（镜像 ``remote_tools.py``）：
- **向后兼容**：无 callback（standalone）→ ``build_ask_user_mcp_server`` 返回 None（不挂工具）。
- **handler 永不 raise（RTOOL-04）**：超时/异常一律返回结构化工具错误（``is_error``），
  让 agent 收到错误继续跑，不崩容器。
- **脱敏（RTOOL-03）**：question/answer 正文绝不入日志，仅记 ``has_answer``/``timeout``/状态。
- **不挂起（T-47-03）**：有界轮询 + ``timeout_minutes`` 上限；超时有 ``default_option`` 用之，
  否则抛 ``QuestionTimeout`` 由 handler 转结构化错误。**绝不**无限等、绝不触发 replan。
- **保活（关键）**：等待期持续心跳上报，使容器/SubAgentSession 保持 RUNNING——server 侧
  wave 调度（``aadvance_coding_waves``）天然视其为在途（``waiting``），不阻断下游、不 dead-end。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import TYPE_CHECKING, Any, Awaitable, Callable

import structlog
from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server

if TYPE_CHECKING:
    from core.config import TaskConfig
    from integrations.callback import CallbackClient

logger = structlog.get_logger(__name__)

ASK_USER_MCP_SERVER_NAME = "friday-ask-user"

# 容器内协议目录与回答文件（对齐 server services/protocols.py：CONTAINER_PROTOCOL_DIR / ANSWER_FILE）。
DEFAULT_PROTOCOL_DIR = "/workspace/.friday"
ANSWER_FILENAME = "answer.json"


class QuestionTimeout(Exception):
    """等待回答超时且无 default_option —— 由 ask_user handler 转结构化工具错误，绝不冒泡崩容器。"""


def _read_answer(answer_path: str) -> str:
    """读取 answer.json 的 answer 字段；不存在/不可解析 → 返回空串（容错）。"""
    try:
        with open(answer_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    answer = data.get("answer", "")
    return answer if isinstance(answer, str) else ""


async def ask_user_and_wait(
    callback: "CallbackClient",
    question: str,
    *,
    options: list[str] | None = None,
    context: str = "",
    code_snippet: str = "",
    default_option: str = "",
    timeout_minutes: int = 10,
    protocol_dir: str = DEFAULT_PROTOCOL_DIR,
    poll_interval_s: float = 3.0,
    _now: Callable[[], float] | None = None,
    _sleep: Callable[[float], Awaitable[None]] | None = None,
) -> str:
    """发起提问 → 轮询 answer.json 等回答 → 返回回答文本。

    超时（累计 > ``timeout_minutes*60``）：有 ``default_option`` 返回之（视为人选默认项续跑）；
    否则抛 ``QuestionTimeout``。**绝不**无限轮询。``_now``/``_sleep``/``poll_interval_s`` 可注入
    以便单测无需真实 sleep。
    """
    now = _now or time.monotonic
    sleep = _sleep or asyncio.sleep
    answer_path = os.path.join(protocol_dir, ANSWER_FILENAME)
    log = logger.bind(has_options=bool(options))

    # ① 发起提问（失败仅 warning，不抛——容器仍可经共享卷收到回答）。
    try:
        await callback.report_question(
            question=question,
            options=options,
            context=context,
            code_snippet=code_snippet,
            default_option=default_option,
            timeout_minutes=timeout_minutes,
        )
    except Exception:  # noqa: BLE001 — 发问失败不阻断等待（共享卷仍可回灌）
        log.warning("ask_user_report_question_failed")

    # ② 有界轮询等回答（期间心跳保活，使 SubAgentSession 保持 RUNNING）。
    deadline = now() + max(0, timeout_minutes) * 60
    while now() < deadline:
        answer = _read_answer(answer_path)
        if answer:
            # 消费后清除 answer.json，避免多轮提问时下一轮误读上一轮的陈旧回答。
            try:
                os.remove(answer_path)
            except OSError:
                pass
            log.info("ask_user_answer_received", has_answer=True)
            return answer
        # 心跳保活（失败不阻断等待）。
        try:
            await callback.report_status(status="progress", message="等待人工回答中")
        except Exception:  # noqa: BLE001 — 心跳失败不影响等待
            pass
        await sleep(poll_interval_s)

    # ③ 超时：default_option 续跑，否则抛 QuestionTimeout（不挂起、不 replan）。
    if default_option:
        log.info("ask_user_timeout_default", timeout=True)
        return default_option
    log.warning("ask_user_timeout_no_default", timeout=True)
    raise QuestionTimeout("未在限定时间内收到人工回答")


def _make_ask_user_handler(
    callback: "CallbackClient",
    protocol_dir: str,
) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    """构造 ask_user 工具 handler —— 永不 raise，超时/异常返回结构化工具错误（RTOOL-04）。"""

    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        question = str(args.get("question", "")).strip()
        if not question:
            return {
                "content": [{"type": "text", "text": "ask_user 缺少 question 参数"}],
                "is_error": True,
            }
        raw_options = args.get("options")
        options = [str(o) for o in raw_options] if isinstance(raw_options, list) else None
        try:
            answer = await ask_user_and_wait(
                callback,
                question,
                options=options,
                context=str(args.get("context", "")),
                code_snippet=str(args.get("code_snippet", "")),
                default_option=str(args.get("default_option", "")),
                timeout_minutes=int(args.get("timeout_minutes", 10) or 10),
                protocol_dir=protocol_dir,
            )
            return {"content": [{"type": "text", "text": answer}]}
        except QuestionTimeout:
            return {
                "content": [{"type": "text", "text": "未在限定时间内收到人工回答"}],
                "is_error": True,
            }
        except Exception as e:  # noqa: BLE001 — handler 永不冒泡崩容器（RTOOL-04）
            logger.warning("ask_user_handler_error", error=str(e))
            return {
                "content": [{"type": "text", "text": "ask_user 执行失败"}],
                "is_error": True,
            }

    return handler


_ASK_USER_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "question": {"type": "string", "description": "向人提出的问题（编码遇阻需要的决策/信息）"},
        "options": {
            "type": "array",
            "items": {"type": "string"},
            "description": "可选的快捷选项",
        },
        "context": {"type": "string", "description": "问题上下文"},
        "code_snippet": {"type": "string", "description": "相关代码片段或 diff"},
        "default_option": {"type": "string", "description": "超时未回答时采用的默认答案"},
        "timeout_minutes": {"type": "integer", "description": "等待回答的超时分钟数"},
    },
    "required": ["question"],
}


def build_ask_user_mcp_server(
    config: "TaskConfig",
    callback: "CallbackClient",
) -> McpSdkServerConfig | None:
    """构建 ask_user 进程内 SDK MCP server。

    向后兼容：无 ``callback_url``（standalone）→ 返回 None（不挂工具，编码行为零回归）。
    """
    if not getattr(config, "callback_url", ""):
        return None

    protocol_dir = os.environ.get("FRIDAY_PROTOCOL_DIR", DEFAULT_PROTOCOL_DIR)
    tool: SdkMcpTool[dict[str, Any]] = SdkMcpTool(
        name="ask_user",
        description=(
            "编码遇阻无法自解时向人提问并等待回答。用于需要人工决策/澄清/补充信息的场景。"
            "返回人工回答文本后据此继续编码。"
        ),
        input_schema=_ASK_USER_INPUT_SCHEMA,
        handler=_make_ask_user_handler(callback, protocol_dir),
    )
    logger.info("ask_user_mcp_server_created")
    return create_sdk_mcp_server(name=ASK_USER_MCP_SERVER_NAME, tools=[tool])


def ask_user_allowed_tools() -> list[str]:
    """ask_user 工具的 allowed_tools 名（格式 ``mcp__{server}__{tool}``）。"""
    return [f"mcp__{ASK_USER_MCP_SERVER_NAME}__ask_user"]
