"""conversation_service 8 fragment 独立渲染测试。"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from chat.conversation_service import (
    ROLE_PROMPTS,
    _build_system_prompt,
)
from prompts.keys import PromptSlugs


@pytest.fixture
def disable_all_chat_slugs(monkeypatch: pytest.MonkeyPatch) -> None:
    """强制走 fallback 路径（覆盖所有 chat fragment slug）。"""
    disabled = ",".join([
        "chat.system.developer",
        "chat.system.pm",
        "chat.system.designer",
        "chat.system.qa",
        "chat.system.general",
        "chat.strategy.default",
        "chat.strategy.deep_analysis",
        "chat.coding_guidance",
    ])
    monkeypatch.setenv("PROMPT_CENTER_DISABLED_KEYS", disabled)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestFragmentRendering:
    """8 个 fragment 独立渲染语义 + 条件分支。"""

    async def test_developer_fragment_from_fallback(
        self,
        disable_all_chat_slugs: None,
    ) -> None:
        prompt = await _build_system_prompt("P1", "proj-1", role="developer")
        assert ROLE_PROMPTS["developer"] in prompt

    async def test_pm_fragment_from_fallback(
        self,
        disable_all_chat_slugs: None,
    ) -> None:
        prompt = await _build_system_prompt("P1", "proj-1", role="pm")
        assert ROLE_PROMPTS["pm"] in prompt

    async def test_designer_fragment_from_fallback(
        self,
        disable_all_chat_slugs: None,
    ) -> None:
        prompt = await _build_system_prompt("P1", "proj-1", role="designer")
        assert ROLE_PROMPTS["designer"] in prompt

    async def test_qa_fragment_from_fallback(
        self,
        disable_all_chat_slugs: None,
    ) -> None:
        prompt = await _build_system_prompt("P1", "proj-1", role="qa")
        assert ROLE_PROMPTS["qa"] in prompt

    async def test_general_fragment_from_fallback(
        self,
        disable_all_chat_slugs: None,
    ) -> None:
        prompt = await _build_system_prompt("P1", "proj-1", role="general")
        assert ROLE_PROMPTS["general"] in prompt

    async def test_strategy_default_selected_when_not_force_deep(
        self,
        disable_all_chat_slugs: None,
    ) -> None:
        prompt = await _build_system_prompt(
            "P1", "proj-1", role="developer", force_deep_analysis=False
        )
        # 默认策略只保留"快速检索"，并明确禁止主动调 deep_analysis（仅 prompt 闸门，
        # 真正的工具列表闸门见 server/agents/chat_runner.py _get_tool_names）。
        assert "回答策略 - 快速检索" in prompt
        assert "不要主动调用 deep_analysis" in prompt
        assert "用户已开启「深度分析」" not in prompt

    async def test_strategy_deep_analysis_selected_when_force(
        self,
        disable_all_chat_slugs: None,
    ) -> None:
        prompt = await _build_system_prompt(
            "P1", "proj-1", role="developer", force_deep_analysis=True
        )
        assert "用户已开启「深度分析」" in prompt
        # 强制深度分析模式不再下发"快速检索"策略段。
        assert "回答策略 - 快速检索" not in prompt

    async def test_coding_guidance_always_included(
        self,
        disable_all_chat_slugs: None,
    ) -> None:
        prompt = await _build_system_prompt("P1", "proj-1", role="developer")
        assert "编码任务识别：" in prompt
        assert "create_coding_plan" in prompt
        # 口径是「先编排产出方案版本，再投影」，不是「调工具生成方案」。
        assert "start_plan_research" in prompt

    async def test_force_deep_analysis_spy_only_deep_slug(
        self,
        disable_all_chat_slugs: None,
    ) -> None:
        """T-R-07: 条件分支不同时渲染两个 strategy slug（防并行 bug）。"""
        calls: list[str] = []
        from chat import conversation_service as cs

        original = cs.render_prompt

        async def spy(slug: str, **kwargs: Any) -> str:
            calls.append(slug)
            return await original(slug, **kwargs)

        with patch.object(cs, "render_prompt", side_effect=spy):
            await _build_system_prompt(
                "P1", "proj-1", role="developer", force_deep_analysis=True
            )

        assert PromptSlugs.CHAT_STRATEGY_DEEP_ANALYSIS in calls
        assert PromptSlugs.CHAT_STRATEGY_DEFAULT not in calls


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestIntentPriorityFragments:
    """「准确性优先」三 slug 注入语义验证。"""

    async def test_developer_role_includes_intent_priority(
        self,
        disable_all_chat_slugs: None,
    ) -> None:
        prompt = await _build_system_prompt(
            "P1", "proj-1", role="developer"
        )
        assert "准确性优先原则" in prompt
        assert "analyze_repository_relevance" in prompt
        assert "ask_clarification" in prompt

    async def test_strategy_default_includes_low_confidence_rule(
        self,
        disable_all_chat_slugs: None,
    ) -> None:
        prompt = await _build_system_prompt(
            "P1", "proj-1", role="developer", force_deep_analysis=False
        )
        assert "top1 score < 0.7" in prompt
        assert "必须调 ask_clarification" in prompt

    async def test_strategy_default_routes_code_understanding_before_local_search(
        self,
        disable_all_chat_slugs: None,
    ) -> None:
        """代码理解问答也必须先路由仓库，避免把当前仓库误判为答案所在地。"""
        prompt = await _build_system_prompt(
            "P1", "proj-1", role="developer", force_deep_analysis=False
        )
        assert "代码理解" in prompt
        assert "功能是怎么实现" in prompt
        assert "当前仓库只是入口" in prompt
        assert "先调用 analyze_repository_relevance" in prompt

    async def test_coding_guidance_includes_relev_gate(
        self,
        disable_all_chat_slugs: None,
    ) -> None:
        prompt = await _build_system_prompt(
            "P1", "proj-1", role="developer"
        )
        assert "调 create_coding_plan 之前必须有 analyze_repository_relevance" in prompt
        assert "编码动词" in prompt
        assert "recommended_repository_ids" in prompt
        # SPINE-02（109-05）：RELEV gate 之外还有一道「必须先有编排产出的方案版本」
        # 前置约束 —— 收窄后 create_coding_plan 只投影方案版本，不接受方案正文。
        assert "编排产出的方案版本" in prompt
        assert "artifact_version_id" in prompt

    async def test_coding_guidance_no_longer_teaches_model_to_author_plan_body(
        self,
        disable_all_chat_slugs: None,
    ) -> None:
        """prompt 不再诱导模型徒手撰写方案正文（SPINE-02 的配套文案守护）。

        SPINE-02 的达成手段是 schema 层收窄，本断言只守配套文案不回退 —— 若哪天有人
        把「技术方案包含：① 影响文件列表 ② 分步实现步骤」这类教模型写正文的表述加回
        prompt，模型会被引导去构造正文再撞 schema，产生一轮无意义的失败工具调用。
        """
        prompt = await _build_system_prompt("P1", "proj-1", role="developer")
        assert "分步实现步骤" not in prompt
        assert "方案正文由编排链路产出" in prompt

    async def test_force_deep_analysis_does_not_include_intent_priority_block(
        self,
        disable_all_chat_slugs: None,
    ) -> None:
        """force_deep_analysis=True → 走 strategy.deep_analysis，不含
        「准确性优先原则（必读）」字面块（work item 与 deep_analysis 模式隔离）。
        """
        prompt = await _build_system_prompt(
            "P1", "proj-1", role="developer", force_deep_analysis=True
        )
        assert "准确性优先原则（必读）" not in prompt
