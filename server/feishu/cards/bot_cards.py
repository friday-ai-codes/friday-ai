"""Card builders for Feishu bot lifecycle messages."""
from __future__ import annotations
from typing import Any
def _markdown_block(content: str) -> dict[str, Any]:
 return {"tag": "markdown", "content": content}
def _reference_lines(references: list[dict[str, Any]]) -> str:
 if not references:
 return "- 未引用具体代码上下文，仅基于项目概览回答"
 lines: list[str] =
 for ref in references[:5]:
 repo = ref.get("repository") or ref.get("repo") or "未知仓库"
 path = ref.get("path") or ref.get("file") or ""
 line = ref.get("line") or ref.get("lines") or ""
 summary = ref.get("summary") or ref.get("text") or ""
 suffix = f" ({line})" if line else ""
 location = f"`{repo}:{path}`{suffix}" if path else f"`{repo}`"
 lines.append(f"- {location} {summary}".strip)
 return "\n".join(lines)
def build_welcome_card -> dict[str, Any]:
 return {
 "config": {"wide_screen_mode": True},
 "header": {
 "title": {"tag": "plain_text", "content": "Friday Bot 已加入群聊"},
 "template": "blue",
 },
 "elements": [
 _markdown_block(
 "直接在群里 **@Friday** 提问即可。\n\n"
 "我会先识别项目/仓库，再检索上下文并给出回答；"
 "如果信息不够明确，我会先发澄清卡。"
 ),
 ],
 }
def build_processing_card(question: str, progress_state: str = "项目识别中", thread_hint: str = "") -> dict[str, Any]:
 hint = f"\n\n话题线索：{thread_hint}" if thread_hint else ""
 return {
 "config": {"wide_screen_mode": True},
 "header": {
 "title": {"tag": "plain_text", "content": "Friday 正在处理中"},
 "template": "blue",
 },
 "elements": [
 _markdown_block(f"**原问题**\n{question}{hint}"),
 {"tag": "hr"},
 _markdown_block(
 "**处理进度**\n"
 f"- 当前阶段：{progress_state}\n"
 "- 项目识别中\n"
 "- 上下文检索中\n"
 "- 回答生成中"
 ),
 ],
 }
def build_clarification_card(question: str, candidates: list[str]) -> dict[str, Any]:
 candidate_lines = "\n".join(f"- {candidate}" for candidate in candidates) or "- 请补充项目、仓库或引用上下文"
 return {
 "config": {"wide_screen_mode": True},
 "header": {
 "title": {"tag": "plain_text", "content": "需要更多上下文"},
 "template": "orange",
 },
 "elements": [
 _markdown_block(f"**原问题**\n{question}"),
 {"tag": "hr"},
 _markdown_block(
 "我还不能稳定判断项目归属或上下文范围。\n\n"
 f"**可选线索**\n{candidate_lines}"
 ),
 ],
 }
def build_answer_card(question: str, answer: str, references: list[dict[str, Any]]) -> dict[str, Any]:
 return {
 "config": {"wide_screen_mode": True},
 "header": {
 "title": {"tag": "plain_text", "content": "Friday 已生成回答"},
 "template": "green",
 },
 "elements": [
 _markdown_block(f"**原问题**\n{question}"),
 {"tag": "hr"},
 _markdown_block(f"**回答**\n{answer}"),
 {"tag": "hr"},
 _markdown_block(f"**已参考上下文**\n{_reference_lines(references)}"),
 ],
 }
def build_error_card(question: str, hint_text: str) -> dict[str, Any]:
 hint = hint_text or "请稍后重试，并尽量补充项目/仓库信息。"
 return {
 "config": {"wide_screen_mode": True},
 "header": {
 "title": {"tag": "plain_text", "content": "Friday 处理失败"},
 "template": "red",
 },
 "elements": [
 _markdown_block(f"**原问题**\n{question}"),
 {"tag": "hr"},
 _markdown_block(
 "处理过程中出现异常。\n\n"
 f"{hint}\n"
 "- 可补充项目/仓库名称后重试\n"
 "- 若持续失败，请联系管理员排查"
 ),
 ],
 }
