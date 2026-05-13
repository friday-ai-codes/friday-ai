"""Chat 场景工具调用预算控制（致敬 Claude Code issue #30150 的 loop 收敛方案）。
Agent loop 非终止（model 反复用相同 / 近似参数调同一工具）是 LLM agent 框架
普遍存在的 #2 bug。本模块为 ChatAnthropicRunner 提供 4 条互补策略：
1. **DEDUP**：完全相同 ``(tool_name, args)`` 第 2 次起拦截，返回 cached
 结果 + 警告，让 LLM 感知到「这个调用没有新信息」。
2. **FILE_LIMIT**：``browse_file_content`` 对同一 ``(repository_id, file_path)``
 的累计调用上限。突破后直接拒绝并暗示模型换工具（``search_repository_code``）。
3. **BUDGET_INJECT**：每个 ToolMessage 末尾追加 ``[预算: X/Y 轮]`` 让 LLM
 实时感知剩余。剩余 ≤ ``BUDGET_WARN_AT`` 时升级为强警告。LangGraph
 的 ``RemainingSteps`` 只暴露给 graph state，LLM 看不到 —— 必须注入到
 tool result content 才能让模型据此决策。
4. **FORCE_FINAL**：剩余 ≤ 1 轮时调用方应停止 ``bind_tools``，强制 LLM
 基于已有信息出答案，避免硬抛 ``MaxTurnsExceeded``。
策略 1/2 设计参考：https://github.com/anthropics/claude-code/issues/30150
策略 3 设计参考：LangGraph ``RemainingSteps`` managed value
策略 4 设计参考：OpenAI Agents SDK ``MaxTurnsExceeded`` 的反模式（直接抛错
 丢弃中间产出，UX 差），改为 graceful degrade。
线程模型：每个 ``stream`` 调用持有一个独立 ``_ToolBudget`` 实例，
不跨 conversation / 不跨 session 持久化 —— 与 ChatAnthropicRunner 一一对应。
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import structlog
from agents.tools.base import ToolResult
logger = structlog.get_logger(__name__)
# ---------------------------------------------------------------------------
# Tuning constants — 与 ChatRunnerConfig.max_turns=50 联动设计
# ---------------------------------------------------------------------------
FILE_READ_HARD_LIMIT: int = 3
"""单个 ``(repository_id, file_path)`` 在一个 stream 内最多被 browse_file_content 调用的次数。
设为 3 是经验值：第 1 次抓全文，第 2 次重读某一段，第 3 次还看不出名堂就该换思路。
"""
BUDGET_WARN_AT: int = 5
"""剩余轮次 ≤ 该值时，ToolMessage 注入的预算提示升级为强警告。"""
BUDGET_FORCE_FINAL_AT: int = 1
"""剩余轮次 ≤ 该值时，调用方应跳过 bind_tools 强制 LLM 出最终回答。"""
# ---------------------------------------------------------------------------
# Decision types
# ---------------------------------------------------------------------------
class _DecisionKind(str, Enum):
 """precheck 的 3 种决策。"""
 ALLOW = "allow"
 DEDUP_HIT = "dedup_hit"
 FILE_LIMIT_HIT = "file_limit_hit"
@dataclass
class BudgetDecision:
 """``_ToolBudget.precheck`` 的返回值。
 Attributes:
 kind: 决策类型。
 intercepted_result: 当 kind != ALLOW 时，是一个伪造的 ``ToolResult``
 供 caller 直接当作工具执行结果使用（不会真实执行工具）。
 reason: 命中拦截时的人类可读原因，用于日志 / 事件 metadata。
 """
 kind: _DecisionKind
 intercepted_result: ToolResult | None = None
 reason: str = ""
 @property
 def intercepted(self) -> bool:
 return self.kind != _DecisionKind.ALLOW
# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------
def _stable_fingerprint(tool_name: str, arguments: dict[str, Any]) -> str:
 """生成 (tool_name, args) 的稳定指纹。
 使用 ``sort_keys=True`` 保证 key 顺序无关；``ensure_ascii=False`` 避免中文
 字符串被 escape 后指纹错配。遇到不可 JSON 序列化的值回退 ``repr``，保证
 永远不抛异常 —— 指纹算错只会导致去重失效而非系统崩溃。
 """
 try:
 return f"{tool_name}:{json.dumps(arguments, sort_keys=True, ensure_ascii=False)}"
 except (TypeError, ValueError):
 try:
 sorted_items = sorted(arguments.items)
 except TypeError:
 sorted_items = list(arguments.items)
 return f"{tool_name}:{sorted_items!r}"
@dataclass
class _ToolBudget:
 """单次 stream 的工具调用预算簿记。
 所有方法 thread-unsafe，但因每个 ``ChatAnthropicRunner.stream`` 串行
 驱动 LLM ↔ tool 来回，无并发冲突。
 """
 max_turns: int
 turn_used: int = 0
 _call_cache: dict[str, tuple[int, ToolResult]] = field(default_factory=dict)
 _file_reads: dict[tuple[str, str], int] = field(default_factory=dict)
 def remaining(self) -> int:
 return max(0, self.max_turns - self.turn_used)
 def on_turn_complete(self) -> None:
 """LLM ↔ tools 完整 round-trip 一次（无论调几个工具）算 1 轮。"""
 self.turn_used += 1
 def should_force_final(self) -> bool:
 """``True`` 表示下一轮 astream 应跳过 bind_tools，强制出最终回答。"""
 return self.remaining <= BUDGET_FORCE_FINAL_AT
 # ------------------------------------------------------------------
 # Precheck — 决定一个工具调用是否真实执行
 # ------------------------------------------------------------------
 def precheck(self, tool_name: str, arguments: dict[str, Any]) -> BudgetDecision:
 """工具执行前做预算 / 重复检查。
 判定顺序（重要）：先 FILE_LIMIT 后 DEDUP —— FILE_LIMIT 是硬上限的
 硬拒绝，DEDUP 只是软警告 + cached return。把硬上限放前面避免 dedup
 命中先返 cached output 误导模型「再试一次也许就好」。
 """
 if tool_name == "browse_file_content":
 repo_id = str(arguments.get("repository_id", ""))
 file_path = str(arguments.get("file_path", ""))
 if repo_id and file_path:
 count = self._file_reads.get((repo_id, file_path), 0)
 if count >= FILE_READ_HARD_LIMIT:
 return BudgetDecision(
 kind=_DecisionKind.FILE_LIMIT_HIT,
 intercepted_result=ToolResult(
 success=False,
 error=(
 f"[系统拒绝] 该文件已被 browse_file_content 调用 {count} 次，"
 f"达到单文件硬上限 {FILE_READ_HARD_LIMIT}。"
 f"请基于已收集到的内容直接作答，或改用 search_repository_code "
 f"缩小目标范围，不要再读同一个文件。"
 ),
 ),
 reason=f"file_read_limit:{repo_id}:{file_path}:{count}",
 )
 fp = _stable_fingerprint(tool_name, arguments)
 cached = self._call_cache.get(fp)
 if cached is not None:
 count, cached_result = cached
 warn = (
 f"[去重命中] 你已用完全相同参数调用过 {tool_name} {count} 次，"
 f"系统未真实执行、返回上次结果。请勿继续重复，"
 f"基于现有信息作答或换不同参数 / 工具。\n\n"
 )
 if cached_result.success:
 intercepted = ToolResult(
 success=True,
 output=cached_result.output,
 error=warn.rstrip,
 metadata={**cached_result.metadata, "dedup_hit_count": count},
 )
 else:
 intercepted = ToolResult(
 success=False,
 error=warn + (cached_result.error or "上次调用失败"),
 metadata={**cached_result.metadata, "dedup_hit_count": count},
 )
 return BudgetDecision(
 kind=_DecisionKind.DEDUP_HIT,
 intercepted_result=intercepted,
 reason=f"dedup_hit:{tool_name}:{count}",
 )
 return BudgetDecision(kind=_DecisionKind.ALLOW)
 # ------------------------------------------------------------------
 # Record — 真实执行后登记
 # ------------------------------------------------------------------
 def record(
 self, tool_name: str, arguments: dict[str, Any], result: ToolResult,
 ) -> None:
 """登记一次真实执行（拦截命中的不应调此方法，避免污染计数）。"""
 fp = _stable_fingerprint(tool_name, arguments)
 prev = self._call_cache.get(fp)
 count = (prev[0] + 1) if prev else 1
 self._call_cache[fp] = (count, result)
 if tool_name == "browse_file_content":
 repo_id = str(arguments.get("repository_id", ""))
 file_path = str(arguments.get("file_path", ""))
 if repo_id and file_path:
 key = (repo_id, file_path)
 self._file_reads[key] = self._file_reads.get(key, 0) + 1
 # ------------------------------------------------------------------
 # Annotate — 把预算注入到 ToolMessage content
 # ------------------------------------------------------------------
 def annotate(self, content: str | list[Any]) -> str | list[Any]:
 """在 ToolMessage content 末尾追加预算提示。
 - 剩余 > BUDGET_WARN_AT：简短状态行
 - 剩余 ≤ BUDGET_WARN_AT：升级为强警告
 - 剩余 ≤ BUDGET_FORCE_FINAL_AT：明确告知「下一轮无工具，立即收束」
 """
 rem = self.remaining
 unique_files = len(self._file_reads)
 unique_calls = len(self._call_cache)
 if rem <= BUDGET_FORCE_FINAL_AT:
 suffix = (
 f"\n\n[预算: {rem}/{self.max_turns} 轮 | 已调用 {unique_calls} 种 / 读 {unique_files} 文件]"
 f"\n⚠️ 工具预算即将耗尽，下一轮将不再提供工具，请立即基于已收集信息作答。"
 )
 elif rem <= BUDGET_WARN_AT:
 suffix = (
 f"\n\n[预算: {rem}/{self.max_turns} 轮 | 已调用 {unique_calls} 种 / 读 {unique_files} 文件]"
 f"\n⚠️ 剩余预算 ≤ {BUDGET_WARN_AT}，请停止探索性检索，立即收束作答。"
 )
 else:
 suffix = (
 f"\n\n[预算: {rem}/{self.max_turns} 轮 | 已调用 {unique_calls} 种 / 读 {unique_files} 文件]"
 )
 if isinstance(content, str):
 return content + suffix
 return [*content, {"type": "text", "text": suffix}]
