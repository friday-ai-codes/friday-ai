"""Phase — _ToolBudget 单元测试。
覆盖 4 条策略 + 边界：
- DEDUP：相同 args 命中
- FILE_LIMIT：browse_file_content 单文件硬上限
- BUDGET_INJECT：剩余 > / ≤ BUDGET_WARN_AT / ≤ BUDGET_FORCE_FINAL_AT 三档提示
- FORCE_FINAL：should_force_final 边界
"""
from __future__ import annotations
from agents.tool_budget import (
 BUDGET_FORCE_FINAL_AT,
 BUDGET_WARN_AT,
 FILE_READ_HARD_LIMIT,
 BudgetDecision,
 _DecisionKind,
 _stable_fingerprint,
 _ToolBudget,
)
from agents.tools.base import ToolResult
# ---------------------------------------------------------------------------
# Fingerprint stability
# ---------------------------------------------------------------------------
def test_fingerprint_stable_across_arg_order -> None:
 """同名工具 + 等价 args（key 顺序不同）应得到相同指纹。"""
 fp1 = _stable_fingerprint("browse_file_content", {"a": 1, "b": "x"})
 fp2 = _stable_fingerprint("browse_file_content", {"b": "x", "a": 1})
 assert fp1 == fp2
def test_fingerprint_preserves_chinese -> None:
 """中文 args 不应被 escape 后导致指纹错配。"""
 fp = _stable_fingerprint("search", {"query": "书房入口"})
 assert "书房入口" in fp
def test_fingerprint_handles_unserializable_gracefully -> None:
 """遇到不可 JSON 序列化的值，应回退 repr 而非抛异常。"""
 class _Weird:
 pass
 weird = _Weird
 fp = _stable_fingerprint("x", {"obj": weird})
 assert fp.startswith("x:")
# ---------------------------------------------------------------------------
# Remaining / turn accounting
# ---------------------------------------------------------------------------
def test_remaining_counts_down_per_turn -> None:
 budget = _ToolBudget(max_turns=5)
 assert budget.remaining == 5
 budget.on_turn_complete
 assert budget.remaining == 4
 for _ in range(10):
 budget.on_turn_complete
 assert budget.remaining == 0
def test_should_force_final_at_threshold -> None:
 budget = _ToolBudget(max_turns=3)
 assert budget.should_force_final is False
 budget.on_turn_complete
 assert budget.should_force_final is False
 budget.on_turn_complete
 assert budget.remaining == 1 == BUDGET_FORCE_FINAL_AT
 assert budget.should_force_final is True
 budget.on_turn_complete
 assert budget.remaining == 0
 assert budget.should_force_final is True
# ---------------------------------------------------------------------------
# DEDUP — 完全相同 args 命中
# ---------------------------------------------------------------------------
def test_precheck_first_call_allowed -> None:
 budget = _ToolBudget(max_turns=10)
 decision = budget.precheck("search_repository_code", {"query": "foo"})
 assert decision.kind is _DecisionKind.ALLOW
 assert decision.intercepted is False
def test_dedup_second_call_returns_cached_with_warning -> None:
 budget = _ToolBudget(max_turns=10)
 args = {"query": "foo", "repository_id": "r1"}
 original = ToolResult(success=True, output={"matches": ["a.py", "b.py"]})
 first = budget.precheck("search_repository_code", args)
 assert first.kind is _DecisionKind.ALLOW
 budget.record("search_repository_code", args, original)
 second = budget.precheck("search_repository_code", args)
 assert second.kind is _DecisionKind.DEDUP_HIT
 assert second.intercepted_result is not None
 assert second.intercepted_result.success is True
 assert second.intercepted_result.output == {"matches": ["a.py", "b.py"]}
 assert "去重命中" in (second.intercepted_result.error or "")
 assert second.intercepted_result.metadata.get("dedup_hit_count") == 1
def test_dedup_counts_increment -> None:
 budget = _ToolBudget(max_turns=10)
 args = {"query": "foo"}
 budget.record("search", args, ToolResult(success=True, output={}))
 d2 = budget.precheck("search", args)
 # precheck 命中后 caller 不会再调 record，第 3、4 次 precheck 命中
 # 的 count 仍是 1 — 这是预期行为：count 只反映真实执行次数。
 assert d2.intercepted_result is not None
 assert d2.intercepted_result.metadata.get("dedup_hit_count") == 1
def test_dedup_preserves_failure_state -> None:
 """上次失败的调用被去重命中时，intercepted_result 仍应是失败的，避免模型误以为修好了。"""
 budget = _ToolBudget(max_turns=10)
 args = {"query": "foo"}
 budget.record(
 "search", args, ToolResult(success=False, error="qdrant down"),
 )
 d = budget.precheck("search", args)
 assert d.intercepted_result is not None
 assert d.intercepted_result.success is False
 assert "qdrant down" in (d.intercepted_result.error or "")
 assert "去重命中" in (d.intercepted_result.error or "")
# ---------------------------------------------------------------------------
# FILE_LIMIT — browse_file_content 单文件硬上限
# ---------------------------------------------------------------------------
def test_file_limit_allows_up_to_hard_limit -> None:
 budget = _ToolBudget(max_turns=20)
 args = {"repository_id": "r1", "file_path": "apps/foo.ts"}
 for i in range(FILE_READ_HARD_LIMIT):
 decision = budget.precheck("browse_file_content", args)
 assert decision.kind is _DecisionKind.ALLOW, f"iter {i} should ALLOW"
 # 模拟真实执行：用稍微不同的 start_line 避免 dedup 命中
 budget.record(
 "browse_file_content",
 {**args, "start_line": i * 10},
 ToolResult(success=True, output={"chunks": }),
 )
 # 第 (HARD_LIMIT + 1) 次：硬拒绝
 decision = budget.precheck("browse_file_content", args)
 assert decision.kind is _DecisionKind.FILE_LIMIT_HIT
 assert decision.intercepted_result is not None
 assert decision.intercepted_result.success is False
 err = decision.intercepted_result.error or ""
 assert "系统拒绝" in err
 assert "search_repository_code" in err # 暗示换工具
def test_file_limit_isolated_per_file -> None:
 """不同文件的计数应独立。"""
 budget = _ToolBudget(max_turns=20)
 for _ in range(FILE_READ_HARD_LIMIT):
 budget.record(
 "browse_file_content",
 {"repository_id": "r1", "file_path": "a.ts"},
 ToolResult(success=True, output={}),
 )
 # a.ts 已达上限
 d_a = budget.precheck("browse_file_content", {"repository_id": "r1", "file_path": "a.ts"})
 assert d_a.kind is _DecisionKind.FILE_LIMIT_HIT
 # b.ts 还允许
 d_b = budget.precheck("browse_file_content", {"repository_id": "r1", "file_path": "b.ts"})
 assert d_b.kind is _DecisionKind.ALLOW
def test_file_limit_isolated_per_repo -> None:
 """同名文件在不同 repo 应独立计数。"""
 budget = _ToolBudget(max_turns=20)
 for _ in range(FILE_READ_HARD_LIMIT):
 budget.record(
 "browse_file_content",
 {"repository_id": "r1", "file_path": "a.ts"},
 ToolResult(success=True, output={}),
 )
 d = budget.precheck("browse_file_content", {"repository_id": "r2", "file_path": "a.ts"})
 assert d.kind is _DecisionKind.ALLOW
def test_file_limit_only_applies_to_browse_file_content -> None:
 """search_repository_code 不应触发文件硬上限。"""
 budget = _ToolBudget(max_turns=20)
 for _ in range(FILE_READ_HARD_LIMIT + 2):
 budget.record(
 "search_repository_code",
 {"repository_id": "r1", "file_path": "a.ts"},
 ToolResult(success=True, output={}),
 )
 # 用 distinct args 避免 dedup 命中，验证 file_limit 不会误伤
 d = budget.precheck("search_repository_code", {"repository_id": "r1", "file_path": "a.ts", "query": "x"})
 assert d.kind is _DecisionKind.ALLOW
def test_file_limit_takes_precedence_over_dedup -> None:
 """同时满足 dedup + file_limit 条件时，应优先返回 FILE_LIMIT_HIT
 (硬拒绝)，而非 DEDUP_HIT (软警告 + cached output)。
 后者会让模型误以为「再试一次也许就好了」。"""
 budget = _ToolBudget(max_turns=20)
 args = {"repository_id": "r1", "file_path": "a.ts"}
 for _ in range(FILE_READ_HARD_LIMIT):
 budget.record("browse_file_content", args, ToolResult(success=True, output={}))
 d = budget.precheck("browse_file_content", args)
 assert d.kind is _DecisionKind.FILE_LIMIT_HIT
# ---------------------------------------------------------------------------
# BUDGET_INJECT — annotate
# ---------------------------------------------------------------------------
def test_annotate_str_normal_remaining -> None:
 """剩余 > BUDGET_WARN_AT：简短状态行，无 ⚠️。"""
 budget = _ToolBudget(max_turns=50)
 out = budget.annotate("file contents")
 assert isinstance(out, str)
 assert "[预算: 50/50 轮" in out
 assert "⚠️" not in out
def test_annotate_str_warning_remaining -> None:
 """剩余 ≤ BUDGET_WARN_AT 且 > BUDGET_FORCE_FINAL_AT：升级强警告。"""
 budget = _ToolBudget(max_turns=10)
 # 消耗到剩余 == BUDGET_WARN_AT
 for _ in range(10 - BUDGET_WARN_AT):
 budget.on_turn_complete
 assert budget.remaining == BUDGET_WARN_AT
 out = budget.annotate("x")
 assert isinstance(out, str)
 assert "⚠️" in out
 assert "立即收束" in out
def test_annotate_str_force_final -> None:
 """剩余 ≤ BUDGET_FORCE_FINAL_AT：明确告知下一轮无工具。"""
 budget = _ToolBudget(max_turns=3)
 for _ in range(2):
 budget.on_turn_complete
 assert budget.remaining == 1
 out = budget.annotate("x")
 assert isinstance(out, str)
 assert "下一轮将不再提供工具" in out
def test_annotate_includes_file_and_call_counts -> None:
 budget = _ToolBudget(max_turns=50)
 budget.record(
 "browse_file_content",
 {"repository_id": "r1", "file_path": "a.ts"},
 ToolResult(success=True, output={}),
 )
 budget.record(
 "search_repository_code",
 {"query": "x"},
 ToolResult(success=True, output={}),
 )
 out = budget.annotate("x")
 assert isinstance(out, str)
 assert "已调用 2 种" in out
 assert "读 1 文件" in out
def test_annotate_list_content_appends_text_block -> None:
 """multimodal content (list) 应追加一个 text block 而非 concat 字符串。"""
 budget = _ToolBudget(max_turns=50)
 original = [{"type": "text", "text": "hello"}]
 out = budget.annotate(original)
 assert isinstance(out, list)
 assert len(out) == 2
 assert out[0] == {"type": "text", "text": "hello"}
 assert out[1]["type"] == "text"
 assert "[预算:" in out[1]["text"]
# ---------------------------------------------------------------------------
# BudgetDecision API surface
# ---------------------------------------------------------------------------
def test_budget_decision_intercepted_flag -> None:
 allow = BudgetDecision(kind=_DecisionKind.ALLOW)
 assert allow.intercepted is False
 dedup = BudgetDecision(
 kind=_DecisionKind.DEDUP_HIT,
 intercepted_result=ToolResult(success=True),
 )
 assert dedup.intercepted is True
 file_hit = BudgetDecision(
 kind=_DecisionKind.FILE_LIMIT_HIT,
 intercepted_result=ToolResult(success=False, error="limit"),
 )
 assert file_hit.intercepted is True
# ---------------------------------------------------------------------------
# 综合场景：模拟问题对话（kimi 反复读两个文件）
# ---------------------------------------------------------------------------
def test_repro_kimi_loop_now_intercepted -> None:
 """复现 user-reported bug：kimi 反复读 router/index.ts + entry.tsx 15 次。
 在 _ToolBudget 保护下，第 4 次起被 FILE_LIMIT 硬拒绝，模型必须换思路。
 """
 budget = _ToolBudget(max_turns=50)
 args_router = {"repository_id": "studyRoom", "file_path": "apps/studyRoom/src/router/index.ts"}
 args_entry = {"repository_id": "wrongBook", "file_path": "plugins/wrongBook/src/entry.tsx"}
 intercepted_count = 0
 for i in range(15):
 # 用稍微不同的 start_line 避免 dedup 提前命中，模拟 LLM "换个 range 再读一次" 的真实模式
 args_r = {**args_router, "start_line": i}
 args_e = {**args_entry, "start_line": i}
 d_r = budget.precheck("browse_file_content", args_r)
 d_e = budget.precheck("browse_file_content", args_e)
 if d_r.intercepted:
 intercepted_count += 1
 else:
 budget.record("browse_file_content", args_r, ToolResult(success=True, output={}))
 if d_e.intercepted:
 intercepted_count += 1
 else:
 budget.record("browse_file_content", args_e, ToolResult(success=True, output={}))
 budget.on_turn_complete
 # 每个文件前 HARD_LIMIT 次允许，后 (15 - HARD_LIMIT) 次拦截，两个文件
 expected_intercepted = (15 - FILE_READ_HARD_LIMIT) * 2
 assert intercepted_count == expected_intercepted
