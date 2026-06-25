"""exposure 序列化与 parse_as_of 测试（Phase 16-01）。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from django.utils import timezone

from knowledge.exposure import (
    format_search_results_markdown,
    parse_as_of,
    serialize_search_result,
    serialize_search_results,
)
from knowledge.retrieval_types import EntityMetadata, ProvenanceLinks, SearchResultDTO

pytestmark = pytest.mark.django_db


def test_parse_as_of_aware_datetime() -> None:
    dt = parse_as_of("2026-05-01T00:00:00+08:00")
    assert dt is not None
    assert dt.tzinfo is not None


def test_parse_as_of_none_passthrough() -> None:
    assert parse_as_of(None) is None
    assert parse_as_of("") is None


def test_parse_as_of_invalid_raises() -> None:
    with pytest.raises(ValueError, match="ISO8601"):
        parse_as_of("not-a-date")


def test_parse_as_of_naive_raises() -> None:
    with pytest.raises(ValueError, match="aware"):
        parse_as_of("2026-05-01T00:00:00")


def _sample_result() -> SearchResultDTO:
    entity_id = uuid.uuid4()
    meta = EntityMetadata(
        entity_id=entity_id,
        entity_kind="work_item",
        version=1,
        title="测试需求",
        valid_at=timezone.now(),
        invalid_at=None,
        source_kind="feishu_work_item",
        source_id="wi-1",
        origin="feishu",
        event_time=timezone.now(),
        space_id="p1",
        repository_id=None,
        provenance=ProvenanceLinks(feishu_url="https://feishu.cn/wi/1", mr_url=None),
    )
    return SearchResultDTO(
        score=0.85,
        vector_score=0.9,
        recency_score=0.7,
        entity=meta,
    )


def test_serialize_search_result_fields() -> None:
    sample = _sample_result()
    payload = serialize_search_result(sample)
    assert payload["entity_id"] == str(sample.entity.entity_id)
    assert payload["kind"] == "work_item"
    assert payload["title"] == "测试需求"
    assert payload["score"] == 0.85
    assert payload["provenance"]["feishu_url"] == "https://feishu.cn/wi/1"
    assert "mr_url" in payload["provenance"]


def test_serialize_search_results_list() -> None:
    results = serialize_search_results([_sample_result()])
    assert len(results) == 1
    assert results[0]["title"] == "测试需求"


def test_format_search_results_markdown_nonempty() -> None:
    md = format_search_results_markdown([_sample_result()])
    assert "## 相似历史交付" in md
    assert "测试需求" in md
    assert "飞书" in md or "feishu" in md.lower()
