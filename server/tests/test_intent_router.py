"""IntentRouter 纯函数单测。

覆盖 ``classify_intent`` / ``evaluate_relev_confidence`` /
``build_clarification_from_relev`` 三个 helper 的语义边界。
"""
from __future__ import annotations

import pytest

from agents.intent_router import (
    CONFIDENCE_ABS_GAP_MIN,
    CONFIDENCE_GAP_MAX,
    CONFIDENCE_TOP1_MIN,
    build_clarification_from_relev,
    classify_intent,
    classify_solution_intent,
    evaluate_relev_confidence,
    normalize_task_category,
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
        assert result.matched_verbs == ()

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
        result = classify_intent(None)  # type: ignore[arg-type]
        assert result.is_coding_request is False


class TestSolutionIntent:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (None, None),
            ("", None),
            (" coding_change ", "coding_change"),
            ("needs_clarification", "needs_clarification"),
            ("FEATURE_SOLUTION", "feature_solution"),
            ("full_tech_plan", "full_tech_plan"),
            ("unexpected", None),
        ],
    )
    def test_normalize_task_category(self, raw: object, expected: object) -> None:
        assert normalize_task_category(raw) == expected

    @pytest.mark.parametrize(
        "message",
        [
            "帮我生成技术方案",
            "创建整体方案",
            "Please produce a feature list",
            "给出全部 12 个模块的规划",
        ],
    )
    def test_strong_project_solution_intent(self, message: str) -> None:
        assert classify_solution_intent(message, bound_project_id="project-1") == "feature_solution"

    def test_solution_intent_requires_bound_project(self) -> None:
        assert classify_solution_intent("生成技术方案", bound_project_id="") is None

    def test_weak_coding_change_is_not_solution(self) -> None:
        assert classify_solution_intent("改一下登录", bound_project_id="project-1") is None


class TestEvaluateRelevConfidence:
    def test_missing_when_none(self) -> None:
        result = evaluate_relev_confidence(None)
        assert result.level == "missing"
        assert result.top1_score is None
        assert result.selected_repository_ids == ()

    def test_low_when_top1_below_threshold(self) -> None:
        result = evaluate_relev_confidence({
            "candidates": [
                {"repository_id": "r1", "score": 0.5, "selected_by_user_final": False},
            ],
        })
        assert result.level == "low_confidence"
        assert result.top1_score == 0.5

    def test_high_when_clear_winner(self) -> None:
        # top1=0.92, top2=0.4 → ratio=0.43 < 0.92 → high
        result = evaluate_relev_confidence({
            "candidates": [
                {"repository_id": "r1", "score": 0.92, "selected_by_user_final": True},
                {"repository_id": "r2", "score": 0.4, "selected_by_user_final": False},
            ],
        })
        assert result.level == "high_confidence"
        assert "r1" in result.selected_repository_ids

    def test_high_when_moderate_gap_no_longer_triggers_low(self) -> None:
        """coding-plan workflow hotfix #1 回归保护（284 DEBUG）：

        在 0.7 阈值下 top2/top1 ≈ 0.85 会被误判为 low_confidence。0.92 阈值放过
        此场景 —— 这类「主仓 ~95%，次仓 ~80%」的多仓召回是日常 RELEV 输出形态，
        不应强制澄清。
        """
        # top1=0.95, top2=0.80 → ratio=0.842 < 0.92 → high
        result = evaluate_relev_confidence({
            "candidates": [
                {"repository_id": "r1", "score": 0.95, "selected_by_user_final": True},
                {"repository_id": "r2", "score": 0.80, "selected_by_ai": False},
            ],
        })
        assert result.level == "high_confidence"
        assert result.top1_score == 0.95

    def test_high_when_abs_gap_decisive_despite_high_ratio(self) -> None:
        """coding-plan workflow hotfix #2 回归保护（UAT 复测发现）：

        真实生产数据：top1=0.82, top2=0.78, ratio=0.95 > 0.92，但绝对差
        0.04 已是清晰决策（4 个百分点）。新逻辑：绝对差 >= 0.03 时即便 ratio
        高也不视作歧义。
        """
        # top1=0.8214, top2=0.7841: ratio=0.9546, gap=0.0373 → high（gap >= 0.03）
        result = evaluate_relev_confidence({
            "candidates": [
                {"repository_id": "example-app", "score": 0.8214, "selected_by_ai": True},
                {"repository_id": "onion-learning", "score": 0.7841, "selected_by_ai": True},
                {"repository_id": "example-practice", "score": 0.7797, "selected_by_ai": True},
            ],
        })
        assert result.level == "high_confidence"
        assert result.top1_score == pytest.approx(0.8214)

    def test_high_when_abs_gap_decisive_at_lower_top1_range(self) -> None:
        """coding-plan workflow hotfix #2：另一组实测数据。

        top1=0.7826, top2=0.7703: ratio=0.9843, gap=0.0123 < 0.03 → 临界 case
        本测试用 gap=0.04 的清晰组以确保 high。
        """
        # top1=0.78, top2=0.74: ratio=0.949, gap=0.04 → high
        result = evaluate_relev_confidence({
            "candidates": [
                {"repository_id": "r1", "score": 0.78, "selected_by_ai": True},
                {"repository_id": "r2", "score": 0.74, "selected_by_ai": True},
            ],
        })
        assert result.level == "high_confidence"

    def test_low_when_both_ratio_high_and_abs_gap_tiny(self) -> None:
        """coding-plan workflow hotfix #2 真歧义判定：284 DEBUG 实测数据。

        top1=0.7765 / top2=0.7704: ratio=0.992 > 0.92, gap=0.0061 < 0.03
        → 真正"无法区分主仓"的歧义，必须 low_confidence
        """
        result = evaluate_relev_confidence({
            "candidates": [
                {"repository_id": "r1", "score": 0.7765, "selected_by_ai": True},
                {"repository_id": "r2", "score": 0.7704, "selected_by_ai": True},
                {"repository_id": "r3", "score": 0.7602, "selected_by_ai": True},
                {"repository_id": "r4", "score": 0.7567, "selected_by_ai": True},
            ],
        })
        assert result.level == "low_confidence"
        assert result.top1_score == pytest.approx(0.7765)

    def test_low_when_extreme_close_at_high_top1(self) -> None:
        """coding-plan workflow hotfix #2：高分区间也能识别真歧义。

        top1=0.95, top2=0.94: ratio=0.989, gap=0.01 < 0.03 → low
        （高分但极接近，仍是真歧义）
        """
        result = evaluate_relev_confidence({
            "candidates": [
                {"repository_id": "r1", "score": 0.95, "selected_by_ai": True},
                {"repository_id": "r2", "score": 0.94, "selected_by_ai": True},
            ],
        })
        assert result.level == "low_confidence"

    def test_low_when_empty_candidates(self) -> None:
        result = evaluate_relev_confidence({"candidates": []})
        assert result.level == "low_confidence"
        assert result.top1_score is None

    def test_missing_when_invalid_dict(self) -> None:
        result = evaluate_relev_confidence({"unrelated": "shape"})
        assert result.level == "low_confidence"  # 空 candidates 视作 low
        assert result.top1_score is None

    def test_threshold_constants_match_design(self) -> None:
        # coding-plan workflow hotfix #1 (2026-05-21)：CONFIDENCE_GAP_MAX 0.7 → 0.92
        # coding-plan workflow hotfix #2 (2026-05-21 UAT 复测)：新增 CONFIDENCE_ABS_GAP_MIN = 0.03
        # 详见 project docs
        assert CONFIDENCE_TOP1_MIN == 0.7
        assert CONFIDENCE_GAP_MAX == 0.92
        assert CONFIDENCE_ABS_GAP_MIN == 0.03

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
        relev = {"candidates": self._candidates()}
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
        relev = {"candidates": self._candidates()}
        payload = build_clarification_from_relev(relev, "需求")
        first = payload["options"][0]
        assert "selected_repository_ids" in first["implies"]
        assert first["implies"]["selected_repository_ids"] == ["r1"]

    def test_question_truncates_long_query(self) -> None:
        long_q = "这是一个非常长的需求描述" * 10  # > 60 字符
        relev = {"candidates": self._candidates()}
        payload = build_clarification_from_relev(relev, long_q)
        assert "..." in payload["question"]
        # 截断后的 query 部分长度 ≤ 64（60 + ...）
        # 不严格断言上限，只确认含截断标记
        assert "针对你的需求" in payload["question"]

    def test_fallback_option_has_empty_repos(self) -> None:
        relev = {"candidates": self._candidates()}
        payload = build_clarification_from_relev(relev, "需求")
        last = payload["options"][-1]
        assert "都不是" in last["label"]
        assert last["implies"]["selected_repository_ids"] == []

    def test_empty_candidates_only_fallback(self) -> None:
        payload = build_clarification_from_relev(
            {"candidates": []}, "需求",
        )
        # 没候选时只剩 fallback
        assert len(payload["options"]) == 1
        assert payload["options"][0]["implies"]["selected_repository_ids"] == []
