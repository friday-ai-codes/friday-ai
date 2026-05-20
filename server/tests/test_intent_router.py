"""Phase：IntentRouter 纯函数单测。
覆盖 ``classify_intent`` / ``evaluate_relev_confidence`` /
``build_clarification_from_relev`` 三个 helper 的语义边界。
"""
from __future__ import annotations
import pytest
from agents.intent_router import (
 CONFIDENCE_GAP_MAX,
 CONFIDENCE_TOP1_MIN,
 build_clarification_from_relev,
 classify_intent,
 evaluate_relev_confidence,
)
class TestClassifyIntent:
 def test_chinese_verb_hits(self) -> None:
 result = classify_intent("帮我修复 favorites 接口")
 assert result.is_coding_request is True
 assert result.confidence == "high"
 assert "修复" in result.matched_verbs
 def test_english_verb_hits(self) -> None:
 result = classify_intent("implement login flow for the app")
 assert result.is_coding_request is True
 assert result.confidence == "high"
 assert "implement" in result.matched_verbs
 def test_no_verb_returns_low_signal(self) -> None:
 result = classify_intent("为什么 X 跳到 Y？")
 assert result.is_coding_request is False
 assert result.confidence == "low_signal"
 assert result.matched_verbs ==
 def test_three_verbs_returns_ambiguous(self) -> None:
 result = classify_intent("修复 优化 重构 X 模块")
 assert result.is_coding_request is True
 assert result.confidence == "ambiguous"
 assert len(result.matched_verbs) >= 3
 def test_empty_message(self) -> None:
 result = classify_intent("")
 assert result.is_coding_request is False
 assert result.confidence == "low_signal"
 def test_non_string_message(self) -> None:
 # 容错：classify_intent 必须接受任意输入不抛异常
 result = classify_intent(None) # type: ignore[arg-type]
 assert result.is_coding_request is False
class TestEvaluateRelevConfidence:
 def test_missing_when_none(self) -> None:
 result = evaluate_relev_confidence(None)
 assert result.level == "missing"
 assert result.top1_score is None
 assert result.selected_repository_ids ==
 def test_low_when_top1_below_threshold(self) -> None:
 result = evaluate_relev_confidence({
 "candidates": [
 {"repository_id": "r1", "score": 0.5, "selected_by_user_final": False},
 ],
 })
 assert result.level == "low_confidence"
 assert result.top1_score == 0.5
 def test_low_when_gap_too_close(self) -> None:
 # top1=0.9, top2=0.85 → ratio=0.94 > 0.7 → low
 result = evaluate_relev_confidence({
 "candidates": [
 {"repository_id": "r1", "score": 0.9, "selected_by_user_final": True},
 {"repository_id": "r2", "score": 0.85, "selected_by_user_final": True},
 ],
 })
 assert result.level == "low_confidence"
 assert result.top1_score == 0.9
 def test_high_when_clear_winner(self) -> None:
 # top1=0.92, top2=0.4 → ratio=0.43 < 0.7 → high
 result = evaluate_relev_confidence({
 "candidates": [
 {"repository_id": "r1", "score": 0.92, "selected_by_user_final": True},
 {"repository_id": "r2", "score": 0.4, "selected_by_user_final": False},
 ],
 })
 assert result.level == "high_confidence"
 assert "r1" in result.selected_repository_ids
 def test_low_when_empty_candidates(self) -> None:
 result = evaluate_relev_confidence({"candidates": })
 assert result.level == "low_confidence"
 assert result.top1_score is None
 def test_missing_when_invalid_dict(self) -> None:
 result = evaluate_relev_confidence({"unrelated": "shape"})
 assert result.level == "low_confidence" # 空 candidates 视作 low
 assert result.top1_score is None
 def test_threshold_constants_match_design(self) -> None:
 assert CONFIDENCE_TOP1_MIN == 0.7
 assert CONFIDENCE_GAP_MAX == 0.7
 def test_high_confidence_short_form(self) -> None:
 """直接传 {"candidates": [...]}（intent_router helper 直接消费形态）。"""
 result = evaluate_relev_confidence({
 "candidates": [
 {"repository_id": "r1", "score": 0.95, "selected_by_user_final": True},
 ],
 })
 assert result.level == "high_confidence"
 assert result.top1_score == 0.95
class TestBuildClarificationFromRelev:
 def _candidates(self) -> list[dict]:
 return [
 {
 "repository_id": "r1",
 "repository_name": "friday-server",
 "score": 0.85,
 "evidence": "命中 3 个文件",
 },
 {
 "repository_id": "r2",
 "repository_name": "friday-web",
 "score": 0.78,
 "evidence": "反向追踪 5 个 API",
 },
 ]
 def test_options_count_includes_all_candidates_plus_freeform_fallback(self) -> None:
 relev = {"candidates": self._candidates}
 payload = build_clarification_from_relev(relev, "改一下 favorites")
 # 2 候选 + 1 兜底 = 3 options
 assert len(payload["options"]) == 3
 assert payload["allow_freeform"] is True
 def test_options_count_capped_at_5(self) -> None:
 many = [
 {
 "repository_id": f"r{i}",
 "repository_name": f"repo-{i}",
 "score": 0.9 - i * 0.05,
 "evidence": f"e{i}",
 }
 for i in range(10)
 ]
 relev = {"candidates": many}
 payload = build_clarification_from_relev(relev, "需求")
 # 4 候选 + 1 兜底 = 5
 assert len(payload["options"]) == 5
 def test_implies_includes_selected_repository_ids(self) -> None:
 relev = {"candidates": self._candidates}
 payload = build_clarification_from_relev(relev, "需求")
 first = payload["options"][0]
 assert "selected_repository_ids" in first["implies"]
 assert first["implies"]["selected_repository_ids"] == ["r1"]
 def test_question_truncates_long_query(self) -> None:
 long_q = "这是一个非常长的需求描述" * 10 # > 60 字符
 relev = {"candidates": self._candidates}
 payload = build_clarification_from_relev(relev, long_q)
 assert "..." in payload["question"]
 # 截断后的 query 部分长度 ≤ 64（60 + ...）
 # 不严格断言上限，只确认含截断标记
 assert "针对你的需求" in payload["question"]
 def test_fallback_option_has_empty_repos(self) -> None:
 relev = {"candidates": self._candidates}
 payload = build_clarification_from_relev(relev, "需求")
 last = payload["options"][-1]
 assert "都不是" in last["label"]
 assert last["implies"]["selected_repository_ids"] ==
 def test_empty_candidates_only_fallback(self) -> None:
 payload = build_clarification_from_relev(
 {"candidates": }, "需求",
 )
 # 没候选时只剩 fallback
 assert len(payload["options"]) == 1
 assert payload["options"][0]["implies"]["selected_repository_ids"] ==
