"""专项画像模块单测（Phase 128-01，PROF-01/02/03）。"""

from __future__ import annotations

import json
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.process_runtime.initiative_profile import (
    InitiativeProfile,
    build_profile,
    select_profile_corpus,
)


def _feature_list_with_summaries() -> dict:
    return {
        "modules": [
            {
                "name": "提分看板",
                "summary": "高三提分专项的看板与任务流转总览",
                "features": [
                    {
                        "name": "任务分发",
                        "description": "按班级分发提分任务",
                        "acceptance": ["给定班级列表，当分发时，则每人收到任务"],
                    }
                ],
            }
        ],
        "features_flat": [
            {
                "name": "任务分发",
                "description": "按班级分发提分任务",
                "module": "提分看板",
                "acceptance": ["给定班级列表，当分发时，则每人收到任务"],
            }
        ],
        "flow_summary": "教师发布 → 学生完成 → 统计回传",
    }


def _feature_list_acceptance_only() -> dict:
    return {
        "modules": [
            {
                "name": "操作手册",
                "features": [
                    {
                        "name": "点按钮",
                        "acceptance": [
                            "打开页面",
                            "点击确认",
                            "看到成功提示",
                        ],
                    }
                ],
            }
        ],
        "features_flat": [
            {
                "name": "点按钮",
                "acceptance": ["打开页面", "点击确认", "看到成功提示"],
            }
        ],
    }


# ── corpus / clarify / shape ───────────────────────────────────────────────


def test_select_profile_corpus_includes_summary_excludes_acceptance():
    corpus = select_profile_corpus(_feature_list_with_summaries())
    joined = "\n".join(corpus.texts)
    assert "高三提分专项的看板与任务流转总览" in joined
    assert "按班级分发提分任务" in joined
    assert "教师发布" in joined
    assert "给定班级列表" not in joined
    assert corpus.sufficient is True


def test_select_profile_corpus_acceptance_only_insufficient():
    corpus = select_profile_corpus(_feature_list_acceptance_only())
    assert corpus.sufficient is False
    joined = "\n".join(corpus.texts)
    assert "打开页面" not in joined or corpus.sufficient is False


@pytest.mark.asyncio
async def test_build_profile_clarify_on_insufficient_corpus():
    result = await build_profile(feature_list=_feature_list_acceptance_only())
    assert result["status"] == "clarify"
    assert result["clarify_reason"] == "insufficient_profile_corpus"
    assert result.get("profile") in (None, {})


def test_initiative_profile_shape_json_serializable():
    profile = InitiativeProfile(
        product_form="web",
        domains=["education"],
        change_kind="brownfield",
        capability_clusters=["task_dispatch"],
        non_goals=["不改计费"],
        reuse_summary="复用既有看板",
    )
    payload = asdict(profile)
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "brownfield" in encoded
    assert set(payload) >= {
        "product_form",
        "domains",
        "change_kind",
        "capability_clusters",
        "non_goals",
        "reuse_summary",
    }


# ── LLM ok / degrade ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_build_profile_ok_from_mock_llm():
    llm_json = {
        "product_form": "web_app",
        "domains": ["gaosan", "score"],
        "change_kind": "brownfield",
        "capability_clusters": ["board", "dispatch"],
        "non_goals": ["不做移动端"],
        "reuse_summary": "复用班级任务服务",
    }
    model = MagicMock()
    model.ainvoke = AsyncMock(
        return_value=SimpleNamespace(content=json.dumps(llm_json, ensure_ascii=False))
    )
    resolved = SimpleNamespace(extra={"default_model": "test-model"})

    with (
        patch(
            "services.provider_config.ProviderConfigService.aresolve",
            new=AsyncMock(return_value=resolved),
        ),
        patch(
            "agents.llm_factory.build_chat_model",
            return_value=model,
        ),
    ):
        result = await build_profile(
            feature_list=_feature_list_with_summaries(),
            request_id="req-1",
            run_id="run-1",
            initiated_by_user_id="u1",
        )

    assert result["status"] == "ok"
    profile = result["profile"]
    assert profile["change_kind"] == "brownfield"
    assert profile["product_form"] == "web_app"
    assert "board" in profile["capability_clusters"]
    assert result.get("degrade_reason", "") in ("", None)


@pytest.mark.asyncio
async def test_build_profile_degraded_on_llm_error():
    resolved = SimpleNamespace(extra={"default_model": "test-model"})
    model = MagicMock()
    model.ainvoke = AsyncMock(
        side_effect=RuntimeError("upstream boom sk-abcdefghijklmnopqrstuvwxyz")
    )

    with (
        patch(
            "services.provider_config.ProviderConfigService.aresolve",
            new=AsyncMock(return_value=resolved),
        ),
        patch(
            "agents.llm_factory.build_chat_model",
            return_value=model,
        ),
    ):
        result = await build_profile(feature_list=_feature_list_with_summaries())

    assert result["status"] == "degraded"
    assert result.get("degrade_reason")
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in str(result.get("degrade_reason"))


@pytest.mark.asyncio
async def test_build_profile_degraded_on_invalid_json():
    resolved = SimpleNamespace(extra={"default_model": "test-model"})
    model = MagicMock()
    model.ainvoke = AsyncMock(return_value=SimpleNamespace(content="not-json {{{"))

    with (
        patch(
            "services.provider_config.ProviderConfigService.aresolve",
            new=AsyncMock(return_value=resolved),
        ),
        patch(
            "agents.llm_factory.build_chat_model",
            return_value=model,
        ),
    ):
        result = await build_profile(feature_list=_feature_list_with_summaries())

    assert result["status"] in ("degraded", "clarify")
    assert result.get("degrade_reason") or result.get("clarify_reason")
