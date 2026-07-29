from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import StreamWriter, interrupt

from agents.chat_runner import ChatAnthropicRunner, ChatRunnerConfig
from agents.core.events import (
    ERROR,
    MESSAGE_COMPLETE,
    PHASE_TRANSITION,
    TASK_PROGRESS,
    TEXT_DELTA,
    THINKING,
    TOOL_USE_RESULT,
    TOOL_USE_START,
)
from orchestration.checkpointer import get_checkpointer
from orchestration.runner_registry import register_runner, unregister_runner
from orchestration.state import RunPhase, WorkflowState

logger = structlog.get_logger(__name__)


async def _persist_run_phase(run_id: str, phase: str) -> None:
    """将 phase 写入 OrchestrationRun — SSE 推流前调用，确保 DB >= SSE。"""
    try:
        from orchestration.models import OrchestrationRun

        await OrchestrationRun.objects.filter(run_id=run_id).aupdate(phase=phase)
    except Exception:
        logger.warning("persist_run_phase_failed", run_id=run_id, phase=phase, exc_info=True)


# SSE 是单向无状态流，浏览器刷新会让 fetch reader 断开，前端内存里的流式渲染
# （text / thinking / tool_calls / timeline）全部丢失。`_StreamingSnapshot` 镜像
# 前端 `handleSSEEvent` 的状态机，把累积态节流写入 `OrchestrationRun.metadata
# ['streaming_snapshot']`，让 polling 拿到 runtime 时可以从快照 restore 前端
# streaming state——避免「刷新后只剩一个空气泡 + 正在整理回答」的窒息体验。
class _StreamingSnapshot:
    """累积 SSE 流期间产生的内容，节流写入 OrchestrationRun.metadata。

    数据结构与前端 store 的 streaming state / `StreamTimelineItem` 一一对应，
    前端拿到后可直接覆盖 `streamingPendingText / streamingThinking /
    streamingToolCalls / streamingNarrations / streamingTimeline`，无需重建。

    flush 触发条件（取或）：
    - 关键事件：tool_use_start / tool_use_result / message_complete /
      phase_transition —— 立即 flush，让用户在刷新瞬间能看到最新进度。
    - 距上次 flush ≥ ``FLUSH_INTERVAL_SECONDS`` —— 节流，避免每个 text_delta
      都写 DB（典型 LLM 流 50-200 chunks/秒）。
    """

    FLUSH_INTERVAL_SECONDS = 0.5
    _FORCE_FLUSH_TYPES = frozenset({
        TOOL_USE_START,
        TOOL_USE_RESULT,
        MESSAGE_COMPLETE,
        PHASE_TRANSITION,
    })

    def __init__(self, run_id: str) -> None:
        self._run_id = run_id
        self._pending_text = ""
        self._thinking = ""
        self._tool_calls: dict[str, dict[str, Any]] = {}
        self._tool_order: list[str] = []
        self._narrations: list[str] = []
        self._timeline: list[dict[str, Any]] = []
        self._last_flush_ts = 0.0
        self._dirty = False

    @staticmethod
    def _new_id() -> str:
        # timeline thinking/narration 节点没有自然 id；用短 uuid，仅作前端 v-for key
        return uuid.uuid4().hex[:12]

    def _append_timeline_text(self, kind: str, text: str) -> None:
        if not text:
            return
        if self._timeline and self._timeline[-1].get("kind") == kind:
            self._timeline[-1]["text"] = self._timeline[-1].get("text", "") + text
            return
        self._timeline.append({
            "id": self._new_id(),
            "kind": kind,
            "text": text,
        })

    def _flush_pending_narration_to_timeline(self) -> None:
        text = self._pending_text
        if not text.strip():
            return
        self._append_timeline_text("narration", text)
        self._narrations.append(text)
        self._pending_text = ""

    def ingest(self, event_type: str, data: dict[str, Any]) -> None:
        """根据事件类型更新累积态——镜像前端 handleSSEEvent 状态机。"""
        if event_type == TEXT_DELTA:
            text = data.get("text", "") or ""
            if text:
                self._pending_text += text
                self._dirty = True
            return

        if event_type == THINKING:
            thinking = data.get("thinking", "") or ""
            if thinking:
                self._thinking += thinking
                self._append_timeline_text("thinking", thinking)
                self._dirty = True
            return

        if event_type == TOOL_USE_START:
            self._flush_pending_narration_to_timeline()
            tool_id = str(data.get("tool_call_id", "") or self._new_id())
            tool_name = data.get("tool_name", "") or ""
            tool_input = data.get("input") or {}
            batch_id = data.get("batch_id") or None
            existing = self._tool_calls.get(tool_id)
            if existing is None:
                entry = {
                    "id": tool_id,
                    "name": tool_name,
                    "input": tool_input if isinstance(tool_input, dict) else {},
                    "result": None,
                    "status": "running",
                    "batch_id": batch_id,
                }
                self._tool_calls[tool_id] = entry
                self._tool_order.append(tool_id)
            else:
                if tool_name:
                    existing["name"] = tool_name
                if isinstance(tool_input, dict) and tool_input:
                    existing["input"] = tool_input
                if batch_id and not existing.get("batch_id"):
                    existing["batch_id"] = batch_id
            self._upsert_timeline_tool(tool_id, tool_name, tool_input, batch_id, status="running")
            self._dirty = True
            return

        if event_type == TOOL_USE_RESULT:
            tool_id = str(data.get("tool_call_id", "") or "")
            if not tool_id:
                return
            tool_name = data.get("tool_name", "") or ""
            tool_input = data.get("input") or {}
            raw_result = data.get("result")
            result_str = _coerce_snapshot_result(raw_result)
            batch_id = data.get("batch_id") or None
            result_entry = self._tool_calls.get(tool_id)
            if result_entry is None:
                result_entry = {
                    "id": tool_id,
                    "name": tool_name,
                    "input": tool_input if isinstance(tool_input, dict) else {},
                    "result": result_str,
                    "status": "done",
                    "batch_id": batch_id,
                }
                self._tool_calls[tool_id] = result_entry
                self._tool_order.append(tool_id)
            else:
                if tool_name and not result_entry.get("name"):
                    result_entry["name"] = tool_name
                if isinstance(tool_input, dict) and tool_input:
                    result_entry["input"] = tool_input
                if result_str is not None:
                    result_entry["result"] = result_str
                result_entry["status"] = "done"
                if batch_id and not result_entry.get("batch_id"):
                    result_entry["batch_id"] = batch_id
            timeline_name = str(result_entry.get("name") or tool_name or "")
            timeline_batch = result_entry.get("batch_id")
            if not isinstance(timeline_batch, str):
                timeline_batch = None
            timeline_result = result_entry.get("result")
            if timeline_result is not None:
                timeline_result = str(timeline_result)
            self._upsert_timeline_tool(
                tool_id,
                timeline_name,
                result_entry.get("input", {}),
                timeline_batch,
                status="done",
                result=timeline_result,
            )
            self._dirty = True
            return

        # MESSAGE_COMPLETE / PHASE_TRANSITION / others：不动累积态，只触发 force flush。

    def _upsert_timeline_tool(
        self,
        tool_id: str,
        tool_name: str,
        tool_input: Any,
        batch_id: str | None,
        *,
        status: str,
        result: str | None = None,
    ) -> None:
        for item in self._timeline:
            if item.get("kind") == "tool" and item.get("id") == tool_id:
                if tool_name:
                    item["name"] = tool_name
                if isinstance(tool_input, dict) and tool_input:
                    item["input"] = tool_input
                if batch_id and not item.get("batch_id"):
                    item["batch_id"] = batch_id
                if result is not None:
                    item["result"] = result
                item["status"] = status
                return
        self._timeline.append({
            "id": tool_id,
            "kind": "tool",
            "name": tool_name,
            "input": tool_input if isinstance(tool_input, dict) else {},
            "result": result,
            "status": status,
            "batch_id": batch_id,
        })

    def snapshot_payload(self) -> dict[str, Any]:
        return {
            "pending_text": self._pending_text,
            "thinking": self._thinking,
            "tool_calls": [self._tool_calls[tid] for tid in self._tool_order],
            "narrations": list(self._narrations),
            "timeline": list(self._timeline),
        }

    def should_flush(self, event_type: str) -> bool:
        if not self._dirty:
            return False
        if event_type in self._FORCE_FLUSH_TYPES:
            return True
        return (time.monotonic() - self._last_flush_ts) >= self.FLUSH_INTERVAL_SECONDS

    async def flush(self) -> None:
        if not self._dirty:
            return
        payload = self.snapshot_payload()
        try:
            from orchestration.models import OrchestrationRun

            run = await OrchestrationRun.objects.filter(run_id=self._run_id).afirst()
            if run is None:
                return
            metadata = dict(run.metadata or {})
            metadata["streaming_snapshot"] = payload
            await OrchestrationRun.objects.filter(run_id=self._run_id).aupdate(metadata=metadata)
            self._last_flush_ts = time.monotonic()
            self._dirty = False
        except Exception:
            logger.warning(
                "streaming_snapshot_flush_failed",
                run_id=self._run_id,
                exc_info=True,
            )


def _coerce_snapshot_result(raw: Any) -> str | None:
    """把 tool_use_result.data['result'] 还原成 str（与前端 ToolItem.result 类型对齐）。"""
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw
    try:
        import json

        return json.dumps(raw, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(raw)


async def _clear_streaming_snapshot(run_id: str) -> None:
    """workflow 收尾 / 出错时清掉 snapshot，避免下次拉到陈旧数据。"""
    if not run_id:
        return
    try:
        from orchestration.models import OrchestrationRun

        run = await OrchestrationRun.objects.filter(run_id=run_id).afirst()
        if run is None:
            return
        metadata = dict(run.metadata or {})
        if "streaming_snapshot" not in metadata:
            return
        metadata.pop("streaming_snapshot", None)
        await OrchestrationRun.objects.filter(run_id=run_id).aupdate(metadata=metadata)
    except Exception:
        logger.warning(
            "streaming_snapshot_clear_failed",
            run_id=run_id,
            exc_info=True,
        )


async def planning_node(state: WorkflowState, writer: StreamWriter) -> dict[str, Any]:
    """接收用户消息，决定执行策略。发射 PHASE_TRANSITION executing。"""
    await _persist_run_phase(state.get("run_id", ""), RunPhase.EXECUTING.value)
    writer({"type": PHASE_TRANSITION, "data": {"phase": "executing"}})
    return {"phase": RunPhase.EXECUTING.value}


async def executing_node(
    state: WorkflowState,
    config: RunnableConfig,
    writer: StreamWriter,
) -> dict[str, Any]:
    """驱动 ChatAnthropicRunner — 支持首次运行和 blocking_results 注入两种模式。

    模式 A（首次）：正常运行 SDK，提取 __blocking_task__ 标记。
    模式 B（二次）：注入 blocking_results 作为上下文再运行 SDK 生成最终回答。

    首次进入时把 ``classify_intent`` 结果写入
    ``result_metadata.intent_classification``，下游 finalize / evaluation 路径可
    读取该字段做后续分析。
    """
    blocking_results = state.get("blocking_results")
    if blocking_results:
        return await _execute_with_results(state, config, writer, blocking_results)
    return await _execute_first_run(state, config, writer)


def _annotate_intent_classification(
    state: WorkflowState,
    result_metadata: dict[str, Any],
) -> dict[str, Any]:
    """把 ``classify_intent`` 结果写入 result_metadata。

    纯函数，不写 DB / 不发 SSE；executing_node 收尾时调用一次即可（首次进入）。
    返回新的 result_metadata dict（含 intent_classification 字段）。
    """
    from agents.intent_router import classify_intent

    classification = classify_intent(state.get("user_message", ""))
    annotated = dict(result_metadata) if result_metadata else {}
    annotated["intent_classification"] = {
        "is_coding_request": classification.is_coding_request,
        "matched_verbs": list(classification.matched_verbs),
        "confidence": classification.confidence,
    }
    return annotated


async def _build_chat_runner(
    config: RunnableConfig,
) -> tuple[ChatAnthropicRunner, str] | dict[str, Any]:
    """从 config 构建 ChatAnthropicRunner，返回 (runner, agent_session_id) 或 error dict。"""
    cfg = config.get("configurable", {})
    api_key = cfg.get("api_key", "")
    if not api_key:
        return {
            "phase": RunPhase.ERROR.value,
            "result_metadata": {"error": "api_key 未配置"},
        }

    agent_session = None
    agent_session_id = cfg.get("agent_session_id", "")
    if agent_session_id:
        from agents.models import AgentSession

        try:
            agent_session = await AgentSession.objects.aget(id=agent_session_id)
        except AgentSession.DoesNotExist:
            pass

    dsb = cfg.get("default_search_branch")
    default_search_branch: str | None = None
    if isinstance(dsb, str):
        s = dsb.strip()
        if s:
            default_search_branch = s

    runner_config = ChatRunnerConfig(
        system_prompt=cfg.get("system_prompt", ""),
        model=cfg.get("model", ""),
        space_id=cfg.get("space_id", ""),
        session_id=cfg.get("session_id", ""),
        conversation_id=cfg.get("conversation_id", ""),
        # 项目级对话：透传绑定项目 id，否则 _get_tool_names 拿不到项目只读工具，
        # system_prompt 已宣传 get_project_overview 等却未绑定 → 模型调用报「未知工具」。
        bound_project_id=cfg.get("bound_project_id", ""),
        api_key=api_key,
        api_base_url=cfg.get("api_base_url", ""),
        max_turns=30,
        timeout_seconds=0,
        agent_session=agent_session,
        max_budget_usd=cfg.get("max_budget_usd"),
        default_search_branch=default_search_branch,
        # 透传前端「深度分析」开关 —— 否则 _build_tool_specs 拿不到 deep_analysis
        # 工具，LLM 看不见就不会调用，开关形同虚设。
        force_deep_analysis=bool(cfg.get("force_deep_analysis", False)),
        # 绑定模型的能力清单：图片块构建的模态门控以此为准，缺失会让自定义
        # vision 模型（如 mimo-v2.5）被误判为 text-only。必须由 graph_config
        # 透传（executing_node 从 cfg 重建 ChatRunnerConfig，不复用 sdk_config 对象）。
        available_models=cfg.get("available_models"),
    )
    return ChatAnthropicRunner(runner_config), agent_session_id


def _user_facing_runner_error(exc: BaseException) -> str:
    """把 chat runner 异常转成可直接展示给用户的文案。

    仅对用户可读的领域异常（如图片不被模型支持）透传原文，其余降级为通用文案，
    避免把内部 traceback / 实现细节泄漏到前端。
    """
    from chat.multimodal import ImageValidationError

    if isinstance(exc, ImageValidationError):
        return str(exc)
    return "服务内部错误，请稍后重试"


async def _run_chat_stream(
    runner: ChatAnthropicRunner,
    prompt: str,
    writer: StreamWriter,
    run_id: str,
    input_parts: list[dict[str, Any]] | None = None,
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """运行 Chat runner stream，返回 (accumulated_thinking, tool_calls_by_id)。

    中断时通过 writer 推送 phase_transition interrupted 确认事件后重新抛出。
    同步维护 ``_StreamingSnapshot`` 写入 OrchestrationRun.metadata，供前端
    刷新后从 runtime polling restore 流式内容（详见类 docstring）。
    """
    accumulated_thinking: list[str] = []
    tool_calls_by_id: dict[str, dict[str, Any]] = {}
    blocking_marker_seen = False
    snapshot = _StreamingSnapshot(run_id) if run_id else None

    try:
        async for event in runner.stream(prompt, input_parts=input_parts):
            if event.type == THINKING:
                thinking_text = event.data.get("thinking", "")
                if thinking_text:
                    accumulated_thinking.append(thinking_text)
            elif event.type == TOOL_USE_START:
                tool_id = str(event.data.get("tool_call_id", ""))
                if tool_id and tool_id not in tool_calls_by_id:
                    tool_calls_by_id[tool_id] = {
                        "id": tool_id,
                        "name": event.data.get("tool_name", ""),
                        "input": event.data.get("input", {}),
                        "result": None,
                        "status": "done",
                    }
            elif event.type == TOOL_USE_RESULT:
                tool_id = str(event.data.get("tool_call_id", ""))
                if tool_id:
                    entry = tool_calls_by_id.setdefault(
                        tool_id,
                        {
                            "id": tool_id,
                            "name": event.data.get("tool_name", ""),
                            "input": {},
                            "result": None,
                            "status": "done",
                        },
                    )
                    if event.data.get("tool_name"):
                        entry["name"] = event.data["tool_name"]
                    if "result" in event.data:
                        entry["result"] = event.data["result"]
                        if isinstance(event.data["result"], dict) and event.data["result"].get("__blocking_task__"):
                            blocking_marker_seen = True

            should_forward = True
            if blocking_marker_seen and event.type in {THINKING, TEXT_DELTA, MESSAGE_COMPLETE}:
                should_forward = False

            if should_forward:
                writer({"type": event.type, "data": event.data})

            if snapshot is not None:
                snapshot.ingest(event.type, event.data)
                if snapshot.should_flush(event.type):
                    await snapshot.flush()
    except asyncio.CancelledError:
        try:
            await _persist_run_phase(run_id, "interrupted")
            writer({"type": PHASE_TRANSITION, "data": {"phase": "interrupted"}})
        except Exception:
            pass
        # 中断时也尽力把最后状态 flush 出去，让 polling 能拿到中断前的进度
        if snapshot is not None:
            try:
                await snapshot.flush()
            except Exception:
                pass
        raise

    if snapshot is not None:
        # 流正常结束最后再 flush 一次，保证 polling 能看到最完整的快照
        try:
            await snapshot.flush()
        except Exception:
            pass

    return accumulated_thinking, tool_calls_by_id


async def _extract_blocking_tasks(
    tool_calls_by_id: dict[str, dict[str, Any]],
    conversation_id: str,
) -> list[dict[str, Any]]:
    """从 tool_calls 结果中提取 __blocking_task__ 标记，并 drain fallback registry。"""
    from agents.tools.blocking_task_registry import drain_blocking_tasks

    blocking_tasks: list[dict[str, Any]] = []
    for tc in tool_calls_by_id.values():
        result = tc.get("result")
        if isinstance(result, dict) and result.get("__blocking_task__"):
            blocking_tasks.append({
                "task_type": result["task_type"],
                "task_id": result["task_id"],
                "params": result.get("params", {}),
            })

    fallback_tasks = await drain_blocking_tasks(conversation_id)
    seen_ids = {t["task_id"] for t in blocking_tasks}
    for ft in fallback_tasks:
        if ft["task_id"] not in seen_ids:
            blocking_tasks.append(ft)
            seen_ids.add(ft["task_id"])

    return blocking_tasks


def _extract_pending_clarification(
    tool_calls_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """从 tool_calls 提取 ``ask_clarification`` 调用产生的 pending payload。

    ``ask_clarification`` 工具的 ToolResult.output 形如
    ``{"clarification_id": ..., "pending": True, "marker": "ask_clarification",
       "question": ..., "options": [...], "allow_freeform": ...}``。
    chat_runner 会把 dict 序列化成 JSON 字符串再放到 tc["result"]，因此
    本 helper 同时尝试 dict 与 str(JSON) 两种形态——同 deep_analysis blocking
    marker 的处理方式（见上方 ``_run_chat_stream`` blocking_marker 分支）。
    """
    for tc in tool_calls_by_id.values():
        if tc.get("name") != "ask_clarification":
            continue
        raw = tc.get("result")
        payload: dict[str, Any] | None = None
        if isinstance(raw, dict):
            payload = raw
        elif isinstance(raw, str) and raw:
            try:
                import json

                parsed = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if isinstance(parsed, dict):
                payload = parsed
        if not isinstance(payload, dict):
            continue
        if not payload.get("pending"):
            continue
        if payload.get("marker") != "ask_clarification":
            continue
        return {
            "clarification_id": payload.get("clarification_id", ""),
            "question": payload.get("question", ""),
            "options": payload.get("options", []),
            "allow_freeform": bool(payload.get("allow_freeform", True)),
        }
    return None


def _build_result_metadata(runner: ChatAnthropicRunner) -> dict[str, Any]:
    """从 runner.result 构建 result_metadata。"""
    result = runner.result
    result_metadata: dict[str, Any] = {
        "status": result.status if result else "unknown",
    }
    if result and result.metadata:
        result_metadata["cost_usd"] = result.metadata.get("cost_usd", 0)
    if result and result.usage:
        result_metadata["input_tokens"] = result.usage.get("input_tokens", 0)
        result_metadata["output_tokens"] = result.usage.get("output_tokens", 0)
    return result_metadata


async def _execute_first_run(
    state: WorkflowState,
    config: RunnableConfig,
    writer: StreamWriter,
) -> dict[str, Any]:
    """首次运行 Chat runner：正常执行并提取 blocking task 标记。"""
    build_result = await _build_chat_runner(config)
    if isinstance(build_result, dict):
        return build_result
    runner, agent_session_id = build_result

    cfg = config.get("configurable", {})
    conv_id = cfg.get("conversation_id", "")
    run_id = state.get("run_id", "")

    from agents.feature_solution_dispatch import dispatch_feature_solution
    from agents.intent_router import classify_solution_intent, normalize_task_category

    inferred = (state.get("result_metadata") or {}).get("inferred_intent") or {}
    inferred_category = normalize_task_category(
        inferred.get("task_category") if isinstance(inferred, dict) else None
    )
    bound_project_id = cfg.get("bound_project_id", "")
    solution_category = classify_solution_intent(
        state.get("user_message", ""),
        bound_project_id=bound_project_id,
    )
    if bound_project_id and (
        solution_category is not None
        or inferred_category in {"feature_solution", "full_tech_plan"}
    ):
        patch = await dispatch_feature_solution(
            conversation_id=conv_id,
            bound_project_id=bound_project_id,
            user_message=state.get("user_message", ""),
            initiated_by_user_id=cfg.get("initiated_by_user_id") or cfg.get("user_id") or "system",
            run_id=run_id,
            writer=writer,
        )
        await _persist_run_phase(run_id, str(patch.get("phase") or RunPhase.ERROR.value))
        return patch

    await _persist_run_phase(run_id, RunPhase.EXECUTING.value)
    writer({"type": PHASE_TRANSITION, "data": {"phase": "executing"}})

    accumulated_thinking: list[str] = []
    tool_calls_by_id: dict[str, dict[str, Any]] = {}

    if conv_id:
        register_runner(conv_id, runner)
    try:
        input_parts = state.get("user_parts")
        if not isinstance(input_parts, list):
            input_parts = None
        accumulated_thinking, tool_calls_by_id = await _run_chat_stream(
            runner, state.get("user_message", ""), writer, run_id, input_parts,
        )
    except Exception as exc:
        logger.exception(
            "executing_node_chat_runner_error",
            session_id=cfg.get("session_id", ""),
        )
        # error 路径直接 END，不经过 finalizing_node —— 必须自行清掉 snapshot，
        # 否则前端 polling 会一直看到陈旧的 streaming_snapshot。
        await _clear_streaming_snapshot(run_id)
        # 关键：向前端补发一个 SSE error 事件。否则 ERROR phase 直接 route END，
        # SSE 流静默关闭、前端一个有内容的事件都收不到 —— 表现为「发出去没有任何
        # 返回」。透传可读文案（如「当前模型不支持图片」）让用户能看到具体原因。
        user_error = _user_facing_runner_error(exc)
        writer({"type": ERROR, "data": {"message": user_error}})
        result = runner.result
        # parts contract：error 路径也要把 collector 已收集 parts
        # 透出供 finalize 落库（major #1 ERROR 路径 parts 携带契约）。
        err_parts = (result.metadata or {}).get("parts", []) if result else []
        return {
            "phase": RunPhase.ERROR.value,
            "final_answer": (result.final_answer if result else None) or "",
            "accumulated_thinking": accumulated_thinking,
            "tool_calls": list(tool_calls_by_id.values()),
            "parts": err_parts,
            "result_metadata": {"error": user_error},
            "agent_session_id": agent_session_id,
        }
    finally:
        if conv_id:
            unregister_runner(conv_id)

    # coding-plan workflow hotfix（2026-05-21）：blocking_tasks 检测必须优先于 pending_clarification。
    #
    # 原因：blocking_tasks（如 deep_analysis）派发已经产生副作用（SubAgentSession
    # 已 acreate、容器已派发），graph 必须负责注册 barrier 等回灌结果；
    # 否则容器即便完成 callback，BarrierManager 里找不到 barrier，task_completed
    # 静默返回 False —— deep_analysis_completion trace 永不写入。
    #
    # 反例（已修）：曾经 pending_clarification（work item 自动构造）写死在
    # blocking_tasks 之前 → RELEV 低置信触发时 deep_analysis 副作用被孤立。
    # 详见 project docs。
    blocking_tasks = await _extract_blocking_tasks(
        tool_calls_by_id, cfg.get("conversation_id", ""),
    )

    if blocking_tasks:
        logger.info(
            "executing_node_blocking_tasks_detected",
            count=len(blocking_tasks),
            task_ids=[t["task_id"] for t in blocking_tasks],
        )
        writer({"type": TASK_PROGRESS, "data": {"completed_count": 0, "total_count": len(blocking_tasks)}})
        await _persist_run_phase(run_id, RunPhase.WAITING.value)
        writer({"type": PHASE_TRANSITION, "data": {"phase": "waiting", "blocking_task_count": len(blocking_tasks)}})
        return {
            "phase": RunPhase.WAITING.value,
            "accumulated_thinking": accumulated_thinking,
            "tool_calls": list(tool_calls_by_id.values()),
            "blocking_tasks": blocking_tasks,
            "agent_session_id": agent_session_id,
        }

    # 是否需要向用户澄清，完全由 LLM 自行决定（调 ask_clarification 工具，
    # 类似 Cursor —— 模型遇到歧义时主动单选/多选提问）。编排层不再基于
    # analyze_repository_relevance 的低置信分数强制插入「选仓库」澄清：
    # 那条硬约束会无视 LLM 的实际回复（哪怕它已给出 1/2/3 的引导）强行抢话，
    # 造成答非所问 + 顶/底两套重复的选仓库 UI。
    pending_clarification = _extract_pending_clarification(tool_calls_by_id)

    if pending_clarification is not None:
        logger.info(
            "executing_node_pending_clarification_detected",
            clarification_id=pending_clarification.get("clarification_id"),
            options_count=len(pending_clarification.get("options", [])),
        )
        await _persist_run_phase(run_id, RunPhase.WAITING_CLARIFICATION.value)
        # PHASE_TRANSITION 直接携带 question / options / allow_freeform，让前端
        # 无需依赖 tool_use_result(ask_clarification) 兜底即可渲染 ClarificationCard。
        writer({
            "type": PHASE_TRANSITION,
            "data": {
                "phase": "waiting_clarification",
                "clarification_id": pending_clarification.get("clarification_id"),
                "question": pending_clarification.get("question", ""),
                "options": pending_clarification.get("options", []),
                "allow_freeform": pending_clarification.get("allow_freeform", True),
            },
        })
        return {
            "phase": RunPhase.WAITING_CLARIFICATION.value,
            "accumulated_thinking": accumulated_thinking,
            "tool_calls": list(tool_calls_by_id.values()),
            "pending_clarification": pending_clarification,
            "agent_session_id": agent_session_id,
        }

    result_metadata = _build_result_metadata(runner)
    # 写入 intent_classification 供下游 evaluation 用
    result_metadata = _annotate_intent_classification(state, result_metadata)
    result = runner.result
    final_answer = (result.final_answer if result else None) or ""
    # parts contract：从 runner.result.metadata 取 collector 已收集
    # parts，注入 state 供 conversation_service → finalize 落库强同源。
    parts_payload = (result.metadata or {}).get("parts", []) if result else []

    await _persist_run_phase(run_id, RunPhase.FINALIZING.value)
    writer({"type": PHASE_TRANSITION, "data": {"phase": "finalizing"}})
    return {
        "phase": RunPhase.FINALIZING.value,
        "final_answer": final_answer,
        "accumulated_thinking": accumulated_thinking,
        "tool_calls": list(tool_calls_by_id.values()),
        "parts": parts_payload,
        "result_metadata": result_metadata,
        "agent_session_id": agent_session_id,
    }


async def _execute_with_results(
    state: WorkflowState,
    config: RunnableConfig,
    writer: StreamWriter,
    blocking_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """二次运行 Chat runner：注入 blocking_results 作为上下文生成最终回答。"""
    build_result = await _build_chat_runner(config)
    if isinstance(build_result, dict):
        return build_result
    runner, agent_session_id = build_result

    cfg = config.get("configurable", {})
    conv_id = cfg.get("conversation_id", "")
    run_id = state.get("run_id", "")
    loop_count = state.get("wait_execute_loops", 0)

    # 防止 LLM 在阻塞任务失败后无限重试相同工具
    if loop_count >= 2:
        error_msg = "分析任务多次尝试后仍失败，请稍后重试。"
        await _persist_run_phase(run_id, RunPhase.ERROR.value)
        return {
            "phase": RunPhase.ERROR.value,
            "final_answer": error_msg,
            "accumulated_thinking": state.get("accumulated_thinking", []),
            "tool_calls": state.get("tool_calls", []),
            "result_metadata": {"error": error_msg, "status": "error"},
            "agent_session_id": agent_session_id,
            "blocking_results": [],
        }

    await _persist_run_phase(run_id, RunPhase.EXECUTING.value)
    writer({"type": PHASE_TRANSITION, "data": {"phase": "executing"}})

    results_text = "\n\n".join(
        f"=== {r.get('task_type', 'unknown')} (task_id: {r.get('task_id', '?')}) ===\n"
        + (r.get("output", "") if r.get("success") else f"失败: {r.get('error', '未知错误')}")
        for r in blocking_results
    )
    prompt = (
        f"用户原始问题: {state.get('user_message', '')}\n\n"
        f"你之前发起了以下分析任务，现在所有结果已返回：\n\n"
        f"{results_text}\n\n"
        f"请根据这些分析结果，综合回答用户的问题。"
        f"\n\n重要提示：所有需要的分析数据已经在上方提供，请直接基于这些结果回答，"
        f"不要再调用任何工具或发起新的分析任务。"
    )

    if conv_id:
        register_runner(conv_id, runner)
    try:
        accumulated_thinking, tool_calls_by_id = await _run_chat_stream(
            runner, prompt, writer, run_id,
        )
    except Exception as exc:
        logger.exception(
            "executing_node_chat_runner_error_second_run",
            session_id=cfg.get("session_id", ""),
        )
        await _clear_streaming_snapshot(run_id)
        # 同首次运行：补发 SSE error 事件，避免二次运行异常时前端静默无响应。
        user_error = _user_facing_runner_error(exc)
        writer({"type": ERROR, "data": {"message": user_error}})
        result = runner.result
        return {
            "phase": RunPhase.ERROR.value,
            "final_answer": (result.final_answer if result else None) or "",
            "accumulated_thinking": state.get("accumulated_thinking", []),
            "tool_calls": state.get("tool_calls", []),
            "result_metadata": {"error": user_error},
            "agent_session_id": agent_session_id,
            "blocking_results": [],
        }
    finally:
        if conv_id:
            unregister_runner(conv_id)

    all_thinking = state.get("accumulated_thinking", []) + accumulated_thinking
    all_tool_calls = state.get("tool_calls", []) + list(tool_calls_by_id.values())

    new_blocking = await _extract_blocking_tasks(
        tool_calls_by_id, cfg.get("conversation_id", ""),
    )
    if new_blocking:
        logger.info(
            "executing_node_blocking_tasks_in_second_run",
            count=len(new_blocking),
        )
        writer({"type": TASK_PROGRESS, "data": {"completed_count": 0, "total_count": len(new_blocking)}})
        await _persist_run_phase(run_id, RunPhase.WAITING.value)
        writer({"type": PHASE_TRANSITION, "data": {"phase": "waiting", "blocking_task_count": len(new_blocking)}})
        return {
            "phase": RunPhase.WAITING.value,
            "accumulated_thinking": all_thinking,
            "tool_calls": all_tool_calls,
            "blocking_tasks": new_blocking,
            "agent_session_id": agent_session_id,
            "blocking_results": [],
        }

    # 与 _execute_first_run 对齐：阻塞任务（如 deep_analysis）完成后，二次运行
    # 里 LLM 仍可能调 ask_clarification 向用户澄清。此前本函数缺这段处理，导致
    # 澄清被静默丢弃、直接落 finalizing —— run 不进 waiting_clarification、卡片
    # 不弹、ConversationIntentTrace 不落，是「深度分析后追问无卡可答」的根因。
    pending_clarification = _extract_pending_clarification(tool_calls_by_id)
    if pending_clarification is not None:
        logger.info(
            "executing_node_pending_clarification_in_second_run",
            clarification_id=pending_clarification.get("clarification_id"),
            options_count=len(pending_clarification.get("options", [])),
        )
        await _persist_run_phase(run_id, RunPhase.WAITING_CLARIFICATION.value)
        writer({
            "type": PHASE_TRANSITION,
            "data": {
                "phase": "waiting_clarification",
                "clarification_id": pending_clarification.get("clarification_id"),
                "question": pending_clarification.get("question", ""),
                "options": pending_clarification.get("options", []),
                "allow_freeform": pending_clarification.get("allow_freeform", True),
            },
        })
        return {
            "phase": RunPhase.WAITING_CLARIFICATION.value,
            "accumulated_thinking": all_thinking,
            "tool_calls": all_tool_calls,
            "pending_clarification": pending_clarification,
            "agent_session_id": agent_session_id,
            "blocking_results": [],
        }

    result_metadata = _build_result_metadata(runner)
    result = runner.result
    final_answer = (result.final_answer if result else None) or ""
    # contract：与 _execute_first_run 对齐，把 collector 已收集 parts 透出
    parts_payload = (result.metadata or {}).get("parts", []) if result else []

    await _persist_run_phase(run_id, RunPhase.FINALIZING.value)
    writer({"type": PHASE_TRANSITION, "data": {"phase": "finalizing"}})
    return {
        "phase": RunPhase.FINALIZING.value,
        "final_answer": final_answer,
        "accumulated_thinking": all_thinking,
        "tool_calls": all_tool_calls,
        "parts": parts_payload,
        "result_metadata": result_metadata,
        "agent_session_id": agent_session_id,
        "blocking_results": [],
    }


async def waiting_node(state: WorkflowState) -> dict[str, Any]:
    """等待阻塞任务完成，resume 后回到 executing 继续推理。

    interrupt() 暂停 graph 并将 blocking_tasks 作为 payload 保存。
    resume 值为 list[BlockingTaskResult]，作为 interrupt() 的返回值传入。
    不在 interrupt() 前放置副作用 — 避免 resume 时重放。
    """
    results = interrupt(state.get("blocking_tasks", []))
    blocking_results = results if isinstance(results, list) else [results]
    loop_count = state.get("wait_execute_loops", 0)
    return {
        "phase": RunPhase.EXECUTING.value,
        "blocking_results": blocking_results,
        "blocking_tasks": [],
        "wait_execute_loops": loop_count + 1,
    }


async def wait_clarification_node(
    state: WorkflowState,
    config: RunnableConfig,
) -> dict[str, Any]:
    """等待用户对 ``ask_clarification`` 的回复（implementation）。

    interrupt() 暂停 graph，payload 是 ``pending_clarification`` 内容；
    resume 值由 ``ClarificationAnswerView`` 触发，结构::

        {
            "clarification_id": str,
            "selected_option_id": str | None,
            "selected_option_label": str | None,
            "freeform_text": str | None,
            "implies": dict,  # endpoint 已 merge 后的 inferred state
        }

    **关键约束**：interrupt 前后不做任何 DB 写副作用——trace 写入在 endpoint
    一次性完成，避免 resume 时重放。``user_message`` 在 resume 后被改写成
    用户答复（freeform 优先、否则用 selected_option_label），让下一轮 LLM
    自然看到「用户的选择」作为 user turn。
    """
    pending = state.get("pending_clarification") or {}
    result = interrupt({
        "waiting_for": "clarification",
        "clarification_id": pending.get("clarification_id"),
        "question": pending.get("question", ""),
        "options": pending.get("options", []),
        "allow_freeform": pending.get("allow_freeform", True),
    })

    if not isinstance(result, dict):
        result = {}

    inferred = result.get("implies") or {}
    if not isinstance(inferred, dict):
        inferred = {}
    freeform = result.get("freeform_text") or ""
    selected_label = result.get("selected_option_label") or ""
    reply_text = freeform or selected_label or ""

    existing_metadata = state.get("result_metadata") or {}
    new_metadata = {
        **existing_metadata,
        "inferred_intent": inferred,
        "last_clarification_id": result.get("clarification_id", ""),
    }

    from agents.intent_router import normalize_task_category

    category = normalize_task_category(inferred.get("task_category"))
    cfg = config.get("configurable", {})
    bound_project_id = cfg.get("bound_project_id", "")
    if category in {"feature_solution", "full_tech_plan"} and bound_project_id:
        from agents.feature_solution_dispatch import dispatch_feature_solution

        patch = await dispatch_feature_solution(
            conversation_id=cfg.get("conversation_id", ""),
            bound_project_id=bound_project_id,
            user_message=reply_text,
            initiated_by_user_id=cfg.get("initiated_by_user_id") or cfg.get("user_id") or "system",
            run_id=state.get("run_id", ""),
        )
        return {
            **patch,
            "pending_clarification": {},
            "result_metadata": {
                **new_metadata,
                **(patch.get("result_metadata") or {}),
            },
        }

    return {
        "phase": RunPhase.EXECUTING.value,
        "user_message": reply_text,
        "pending_clarification": {},
        "result_metadata": new_metadata,
    }


async def finalizing_node(state: WorkflowState) -> dict[str, Any]:
    """收尾节点，标记 workflow 完成。"""
    # workflow 完成后清掉 streaming_snapshot —— message 已落库，下次拉 runtime
    # 应直接走 hydrateMessages 路径，不能再 restore 老快照导致 bubble 重影。
    await _clear_streaming_snapshot(state.get("run_id", ""))
    return {"phase": RunPhase.COMPLETED.value}


def route_after_executing(state: WorkflowState) -> str:
    """条件路由：error 直接结束，有 blocking_tasks 走 waiting（含循环计数保护），否则走 finalizing。

    implementation 新增：``phase=waiting_clarification`` 走专属
    ``wait_clarification`` 节点 ``interrupt()`` 等用户答复。
    """
    if state.get("phase") == RunPhase.ERROR.value:
        return END
    # 协商分支放在 blocking_tasks 之前判定；ask_clarification 工具调用
    # 通过 pending_clarification 字段非空 + phase=waiting_clarification 双标记驱动。
    if state.get("phase") == RunPhase.WAITING_CLARIFICATION.value:
        return "wait_clarification"
    if state.get("blocking_tasks"):
        loop_count = state.get("wait_execute_loops", 0)
        if loop_count >= 2:
            return "finalizing"
        # 二次运行后（loop_count >= 1）不再允许进入 waiting 循环，
        # 避免 LLM 重复调用阻塞工具导致无限循环。
        if loop_count >= 1:
            return "finalizing"
        return "waiting"
    return "finalizing"


def route_after_wait_clarification(state: WorkflowState) -> str:
    """方案类 resume 已直驱正式编排时，不再回 executing 重跑 LLM。"""
    phase = state.get("phase")
    if phase == RunPhase.EXECUTING.value:
        return "executing"
    if phase == RunPhase.WAITING.value:
        return "waiting"
    if phase == RunPhase.FINALIZING.value:
        return "finalizing"
    if phase == RunPhase.WAITING_CLARIFICATION.value:
        return "wait_clarification"
    return END


def build_graph() -> StateGraph:
    """构建编排 StateGraph builder。

    拓扑: START → planning → executing → (conditional) → finalizing → END
                                   ↘ waiting → executing（循环）↗
                                   ↘ wait_clarification → executing（work item）↗
    """
    builder: StateGraph = StateGraph(WorkflowState)

    builder.add_node("planning", planning_node)
    builder.add_node("executing", executing_node)
    builder.add_node("waiting", waiting_node)
    # 协商暂停节点
    builder.add_node("wait_clarification", wait_clarification_node)
    builder.add_node("finalizing", finalizing_node)

    builder.add_edge(START, "planning")
    builder.add_edge("planning", "executing")
    builder.add_conditional_edges("executing", route_after_executing)
    builder.add_edge("waiting", "executing")
    builder.add_conditional_edges("wait_clarification", route_after_wait_clarification)
    builder.add_edge("finalizing", END)

    return builder


async def get_compiled_graph() -> Any:
    """编译 graph 并绑定持久化 checkpointer（生产用 AsyncSqliteSaver）。"""
    checkpointer = await get_checkpointer()
    return build_graph().compile(checkpointer=checkpointer)
