"""LLM grader 测试（Phase 15-05）。"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.test import override_settings

from knowledge.llm_grader import _truncate, grade_search_results
from knowledge.retrieval_types import EntityMetadata, ProvenanceLinks, SearchResultDTO

pytestmark = pytest.mark.django_db


def _result(title: str = "t") -> SearchResultDTO:
    eid = uuid.uuid4()
    meta = EntityMetadata(
        entity_id=eid,
        entity_kind="work_item",
        version=1,
        title=title,
        valid_at=None,
        invalid_at=None,
        source_kind="feishu_work_item",
        source_id="s1",
        origin="feishu",
        event_time=None,
        space_id="p1",
        repository_id="r1",
        provenance=ProvenanceLinks(),
    )
    return SearchResultDTO(score=0.9, vector_score=0.9, recency_score=1.0, entity=meta)


@override_settings(KNOWLEDGE_RETRIEVAL_LLM_RERANK_ENABLED=True)
async def test_llm_grader_fills_fields():
    r = _result("用户登录")
    fake_response = MagicMock()
    fake_response.content = (
        f'[{{"entity_id": "{r.entity.entity_id}", "grade": "duplicate", "reason": "同类需求"}}]'
    )
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(return_value=fake_response)
    resolved = MagicMock(default_model="gpt-4o-mini")

    with patch(
        "services.provider_config.ProviderConfigService.aresolve_or_error",
        AsyncMock(return_value=resolved),
    ), patch("agents.llm_factory.build_chat_model", return_value=fake_model):
        results = await grade_search_results("登录", [r])
    assert results[0].llm_grade == "duplicate"
    assert results[0].llm_reason == "同类需求"


@override_settings(KNOWLEDGE_RETRIEVAL_LLM_RERANK_ENABLED=True)
async def test_llm_grader_failure_degrades():
    with patch(
        "services.provider_config.ProviderConfigService.aresolve_or_error",
        AsyncMock(side_effect=RuntimeError("boom")),
    ):
        original = [_result()]
        out = await grade_search_results("q", original)
    assert len(out) == 1
    assert out[0].llm_grade is None


def test_snippet_truncated():
    assert len(_truncate("x" * 600)) == 500


@override_settings(KNOWLEDGE_RETRIEVAL_LLM_RERANK_ENABLED=False)
async def test_llm_disabled_skips_provider():
    with patch(
        "services.provider_config.ProviderConfigService.aresolve_or_error",
        AsyncMock(),
    ) as mock_resolve:
        await grade_search_results("q", [_result()])
        mock_resolve.assert_not_called()
