"""EdgeType.API_CALLS + ChunkEdge.target_repository_id 测试（work item）。"""
from __future__ import annotations

import uuid

import pytest

from code_relations.models import ChunkEdge, EdgeType


def test_api_calls_in_edge_type_values() -> None:
    assert "API_CALLS" in EdgeType.values


def test_api_calls_value_and_label() -> None:
    assert EdgeType.API_CALLS == "API_CALLS"
    assert EdgeType.API_CALLS.label == "API Calls"


def test_all_8_edge_types() -> None:
    expected = {
        "CALL",
        "IMPORT",
        "SAME_FILE",
        "TEST_OF",
        "CO_CHANGED",
        "SEMANTIC",
        "IMPLEMENTS",
        "API_CALLS",
    }
    assert set(EdgeType.values) == expected


def test_chunkedge_has_target_repository_id_field() -> None:
    field = ChunkEdge._meta.get_field("target_repository_id")
    assert field.null is True
    assert field.blank is True


@pytest.mark.django_db
def test_chunkedge_api_calls_with_target_repository_id(repository) -> None:
    """API_CALLS 边可以写入 target_repository_id（跨仓场景；UUID 类型）。"""
    target_repo_id = uuid.uuid4()
    edge = ChunkEdge.objects.create(
        source_chunk_id=uuid.uuid4(),
        target_chunk_id=uuid.uuid4(),
        edge_type=EdgeType.API_CALLS,
        weight=1.0,
        metadata={"direction": "calls"},
        repository=repository,
        target_repository_id=target_repo_id,
    )
    edge.refresh_from_db()
    assert edge.target_repository_id == target_repo_id
    assert edge.edge_type == "API_CALLS"


@pytest.mark.django_db
def test_chunkedge_v24_edge_target_repository_id_null(repository) -> None:
    """v24 既有边 target_repository_id = NULL（backward compat）。"""
    edge = ChunkEdge.objects.create(
        source_chunk_id=uuid.uuid4(),
        target_chunk_id=uuid.uuid4(),
        edge_type="CALL",
        weight=0.8,
        metadata={},
        repository=repository,
    )
    edge.refresh_from_db()
    assert edge.target_repository_id is None


@pytest.mark.django_db
def test_api_calls_edge_type_accepted_by_check_constraint(repository) -> None:
    """API_CALLS 通过 DB 层 CheckConstraint chunkedge_edge_type_valid。"""
    edge = ChunkEdge.objects.create(
        source_chunk_id=uuid.uuid4(),
        target_chunk_id=uuid.uuid4(),
        edge_type="API_CALLS",
        weight=0.7,
        metadata={},
        repository=repository,
    )
    assert edge.pk is not None
