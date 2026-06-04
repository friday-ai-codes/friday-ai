"""Chat assistant message ``parts`` 数据模型与 builder（Quick Task）。
对齐业界标准：
- Anthropic Messages API ``content`` 是 ``Array<TextBlock | ToolUseBlock | ThinkingBlock>``；
 streaming 事件按 ``content_block_start / content_block_delta / content_block_stop``
 推进，遇到下一个 block 时上一个 block 必须封口。
- Vercel AI SDK v4+ ``UIMessage.parts``、assistant-ui 也采用同样的有序 parts 数组。
本模块仅做后端 builder / Pydantic schema，不绑定 ORM。``Message.parts``
仍是 ``JSONField`` 透传 ``list[dict]``；本模块的 Pydantic 类提供 D1
schema versioning 的强类型入口（前端 hydrate 与未来扩展 image/citation
等 type 的基线）。
设计决策见 ``project-docs/quick/-chat-message-parts-refactor/PLAN.md``
§3.1 数据契约 / §4 D1 / D2 / D5。
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Union, cast
import structlog
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
logger = structlog.get_logger(__name__)
# parts 数组元素 schema 版本号；新增 type 时（image / citation / code_execution）
# 同步升 version 并保留旧分支（additive 策略，见 PLAN §4 D1）。
PARTS_SCHEMA_VERSION: Literal[2] = 2
class _PartBase(BaseModel):
 """Pydantic 公共字段。"""
 model_config = ConfigDict(extra="forbid")
 id: str = Field(..., description="客户端稳定:key（uuid 或 server 给）")
 index: int = Field(..., ge=0, description="0-based 渲染顺序")
class TextPart(_PartBase):
 """正文文本 part；与 markdown 一致渲染。"""
 type: Literal["text"] = "text"
 text: str = ""
 state: Literal["streaming", "done"] = "streaming"
class ToolUsePart(_PartBase):
 """工具调用 part；状态机覆盖 running → done | error。"""
 type: Literal["tool_use"] = "tool_use"
 tool_call_id: str
 name: str
 input: dict[str, Any] = Field(default_factory=dict)
 status: Literal["running", "done", "error"] = "running"
 # 始终 string —— 与 SSE ``tool_use_result.result`` / ``chat_runner.py``
 # ``_tool_result_to_content`` 路径一致；dict 在到达本模块前已 ``json.dumps``。
 result: str | None = None
 batch_id: str | None = None
class ThinkingPart(_PartBase):
 """模型思考链；与 text 同级 sibling，渲染时折叠展示。"""
 type: Literal["thinking"] = "thinking"
 text: str = ""
 state: Literal["streaming", "done"] = "streaming"
class ImagePart(_PartBase):
 """图片 part；只保存受控引用，不把二进制或 data URL 写入 content。"""
 type: Literal["image"] = "image"
 mime_type: str
 size_bytes: int = Field(..., ge=1)
 width: int | None = Field(default=None, ge=1)
 height: int | None = Field(default=None, ge=1)
 detail: Literal["auto", "low", "high"] = "auto"
 storage_ref: str = ""
 source_url: str = ""
 alt_text: str = ""
# discriminated union — Pydantic v2 通过 ``type`` 字面值判别。
# 前端 ``MessagePart`` 联合类型必须与此处保持同源（ 输出）。
Part = Annotated[
 Union[TextPart, ToolUsePart, ThinkingPart, ImagePart],
 Field(discriminator="type"),
]
_PartAdapter: TypeAdapter[Part] = TypeAdapter(Part)
def part_to_dict(part: Part) -> dict[str, Any]:
 """Pydantic → JSON-ready dict（落库 / SSE payload 共用）。"""
 return cast(dict[str, Any], _PartAdapter.dump_python(part, mode="json"))
def part_from_dict(data: dict[str, Any]) -> Part:
 """JSON dict → Pydantic（防御输入：未知 type 在调用方处理 fallback）。"""
 return _PartAdapter.validate_python(data)
def _new_part_id -> str:
 return f"p_{uuid.uuid4.hex[:12]}"
@dataclass
class PartsCollector:
 """``chat_runner.stream`` 内的 parts 状态机持有者（D2）。
 所有 ``append_text / append_thinking / start_tool_use / complete_tool_use /
 flush_all`` 都是单 task 内同步调用，不需要 ``asyncio.Lock``：``chat_runner``
 本身是 async generator，所有 yield 之间天然串行。
 生命周期不变量（major #1 ERROR 路径 parts 契约）：
 - 主流程结束（正常 ``message_complete`` / max_turns 用尽 graceful degrade /
 ``CancelledError`` / ``ContextWindowExceededError`` / generic ``Exception``）
 **统一**调 ``flush_all`` 后再读 ``to_message_payload``。
 - 未完成的 ``tool_use`` part 在 ``flush_all`` 下 ``status: 'running' →
 'error'``、``result='cancelled'``（与 R1 缓解一致，不能错误标 done）。
 """
 parts: list[dict[str, Any]] = field(default_factory=list)
 _current_streaming_id: str | None = None
 _current_streaming_type: Literal["text", "thinking"] | None = None
 _next_index: int = 0
 # tool_call_id → part index，O(1) 反查 complete_tool_use
 _tool_index_by_call_id: dict[str, int] = field(default_factory=dict)
 # ------------------------------------------------------------------ helpers
 def _close_current_streaming(self) -> None:
 """把当前 streaming text/thinking 标 done（仅文本类）。"""
 if self._current_streaming_id is None:
 return
 for part in self.parts:
 if part.get("id") == self._current_streaming_id and part.get("type") in {"text", "thinking"}:
 part["state"] = "done"
 break
 self._current_streaming_id = None
 self._current_streaming_type = None
 def _allocate_index(self) -> int:
 idx = self._next_index
 self._next_index += 1
 return idx
 # ------------------------------------------------------------------ text
 def append_text(self, text: str) -> tuple[str, int, bool]:
 """append 当前 streaming text part；如不存在则新建。
 Returns:
 ``(part_id, index, is_new_part)`` —— ``is_new_part=True`` 时调用方
 需先发 ``part_started`` 再发 ``part_delta``，否则直接发 ``part_delta``。
 """
 if self._current_streaming_type == "text" and self._current_streaming_id is not None:
 for part in self.parts:
 if part.get("id") == self._current_streaming_id:
 part["text"] = part.get("text", "") + text
 return cast(str, part["id"]), cast(int, part["index"]), False
 # 新开 text part
 part_id = _new_part_id
 idx = self._allocate_index
 new_part: dict[str, Any] = {
 "type": "text",
 "id": part_id,
 "index": idx,
 "text": text,
 "state": "streaming",
 }
 self.parts.append(new_part)
 self._current_streaming_id = part_id
 self._current_streaming_type = "text"
 return part_id, idx, True
 # ------------------------------------------------------------------ thinking
 def append_thinking(self, text: str) -> tuple[str, int, bool]:
 """同 ``append_text`` 但作用于 thinking part。
 thinking 与 text 切换**互不封口**：text streaming 时 append_thinking
 新开 thinking part，但 text part 状态保持 streaming（后续 text_delta
 会继续 append 该 text part）。
 """
 if self._current_streaming_type == "thinking" and self._current_streaming_id is not None:
 for part in self.parts:
 if part.get("id") == self._current_streaming_id:
 part["text"] = part.get("text", "") + text
 return cast(str, part["id"]), cast(int, part["index"]), False
 part_id = _new_part_id
 idx = self._allocate_index
 new_part: dict[str, Any] = {
 "type": "thinking",
 "id": part_id,
 "index": idx,
 "text": text,
 "state": "streaming",
 }
 self.parts.append(new_part)
 self._current_streaming_id = part_id
 self._current_streaming_type = "thinking"
 return part_id, idx, True
 # ------------------------------------------------------------------ tool_use
 def start_tool_use(
 self,
 *,
 tool_call_id: str,
 name: str,
 input: dict[str, Any],
 batch_id: str | None,
 ) -> tuple[str, int, int | None]:
 """开 tool_use part；**先**封口当前 streaming text/thinking。
 Returns:
 ``(part_id, index, prev_closed_index)`` —— ``prev_closed_index`` 是
 被封口的 text/thinking part 的 index（None 表示无 streaming 文本被封口）。
 调用方据此发 ``part_completed``（针对被封口的）+ ``part_started``
 （针对新 tool_use）。
 """
 prev_closed_index: int | None = None
 if self._current_streaming_id is not None and self._current_streaming_type in {"text", "thinking"}:
 for part in self.parts:
 if part.get("id") == self._current_streaming_id:
 prev_closed_index = cast(int, part["index"])
 break
 self._close_current_streaming
 part_id = _new_part_id
 idx = self._allocate_index
 new_part: dict[str, Any] = {
 "type": "tool_use",
 "id": part_id,
 "index": idx,
 "tool_call_id": tool_call_id,
 "name": name,
 "input": dict(input or {}),
 "status": "running",
 "result": None,
 "batch_id": batch_id,
 }
 self.parts.append(new_part)
 self._tool_index_by_call_id[tool_call_id] = idx
 # tool_use 不算 streaming text/thinking；不切换当前 streaming 持有者
 # （后续 text_delta 仍会"开新 text part" —— Anthropic 原生语义）。
 self._current_streaming_id = None
 self._current_streaming_type = None
 return part_id, idx, prev_closed_index
 def complete_tool_use(
 self,
 *,
 tool_call_id: str,
 success: bool,
 result: str,
 ) -> int | None:
 """标记 tool_use 完成（``running → done | error``）。
 未知 ``tool_call_id`` 不抛异常（防御主流程），返回 None。
 """
 idx = self._tool_index_by_call_id.get(tool_call_id)
 if idx is None:
 logger.warning(
 "parts_collector_unknown_tool_call_id",
 tool_call_id=tool_call_id,
 )
 return None
 for part in self.parts:
 if part.get("type") == "tool_use" and part.get("index") == idx:
 part["status"] = "done" if success else "error"
 part["result"] = result
 return idx
 return None
 # ------------------------------------------------------------------ flush
 def flush_all(self) -> None:
 """收尾：标所有 streaming text/thinking → done；running tool_use → error+cancelled。
 ERROR / Cancelled / max_turns 路径统一调用，保证 ``to_message_payload``
 输出的 parts 不残留 streaming 状态（前端不再"挂载 streaming spinner"）。
 遍历**所有** parts（不仅 ``_current_streaming_id``）：``thinking`` 与
 ``text`` 互不封口的语义会让早期开的 text part 在中间被 thinking 抢走
 ``current_streaming`` 持有者；它的 ``state`` 仍是 ``streaming`` 必须在
 flush 时一并收尾。
 ``tool_use`` 在收尾时仍是 ``running`` 表示用户中断了执行；按 R1 缓解
 策略标 ``error`` + ``result='cancelled'``，**不**标 ``done``，避免数据失真。
 """
 for part in self.parts:
 ptype = part.get("type")
 if ptype in {"text", "thinking"} and part.get("state") == "streaming":
 part["state"] = "done"
 elif ptype == "tool_use" and part.get("status") == "running":
 part["status"] = "error"
 if not part.get("result"):
 part["result"] = "cancelled"
 self._current_streaming_id = None
 self._current_streaming_type = None
 # ------------------------------------------------------------------ derive
 def to_message_payload(self) -> dict[str, Any]:
 """生成 ``{parts, content, tool_calls}`` 三同源 dict。
 - ``content`` = 所有 text part ``.text`` 拼接（向后兼容字段，
 强同源契约）。
 - ``tool_calls`` = 所有 tool_use part 抽 ``{id, name, input, result,
 status}``（与历史 ``Message.tool_calls`` schema 兼容）。
 """
 text_parts = [p for p in self.parts if p.get("type") == "text"]
 tool_parts = [p for p in self.parts if p.get("type") == "tool_use"]
 content = "".join(str(p.get("text", "")) for p in text_parts)
 tool_calls = [
 {
 "id": p.get("tool_call_id"),
 "name": p.get("name"),
 "input": p.get("input") or {},
 "result": p.get("result"),
 "status": p.get("status"),
 }
 for p in tool_parts
 ]
 return {
 "parts": list(self.parts),
 "content": content,
 "tool_calls": tool_calls,
 }
