"""Phase: conversation_service 8 fragment 独立渲染测试。"""
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
 assert "策略一 - 快速检索" in prompt
 assert "用户已开启「深度分析」" not in prompt
 async def test_strategy_deep_analysis_selected_when_force(
 self,
 disable_all_chat_slugs: None,
 ) -> None:
 prompt = await _build_system_prompt(
 "P1", "proj-1", role="developer", force_deep_analysis=True
 )
 assert "用户已开启「深度分析」" in prompt
 assert "策略一 - 快速检索" not in prompt
 async def test_coding_guidance_always_included(
 self,
 disable_all_chat_slugs: None,
 ) -> None:
 prompt = await _build_system_prompt("P1", "proj-1", role="developer")
 assert "编码任务识别：" in prompt
 assert "create_coding_plan" in prompt
 async def test_force_deep_analysis_spy_only_deep_slug(
 self,
 disable_all_chat_slugs: None,
 ) -> None:
 """T-R-07: 条件分支不同时渲染两个 strategy slug（防并行 bug）。"""
 calls: list[str] =
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
