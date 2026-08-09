"""``QdrantService._build_filter`` 的 ``must_not`` / ``CODE_SEARCH_EXCLUDE`` 契约。"""

from __future__ import annotations

from services.qdrant_service import QdrantService


def test_exclude_key_becomes_must_not() -> None:
    f = QdrantService._build_filter(
        {"repository_id": ["r1"], QdrantService.EXCLUDE_KEY: {"kind": "commit"}}
    )
    assert f is not None
    assert f.must is not None and len(f.must) == 1
    assert f.must_not is not None and len(f.must_not) == 1
    assert f.must_not[0].key == "kind"
    assert f.must_not[0].match.value == "commit"


def test_exclude_list_uses_match_any() -> None:
    f = QdrantService._build_filter(
        {QdrantService.EXCLUDE_KEY: {"kind": ["commit", "doc"]}}
    )
    assert f is not None
    assert f.must is None
    assert f.must_not is not None
    assert set(f.must_not[0].match.any) == {"commit", "doc"}


def test_empty_exclude_dict_is_noop() -> None:
    f = QdrantService._build_filter(
        {"repository_id": "r1", QdrantService.EXCLUDE_KEY: {}}
    )
    assert f is not None
    assert f.must is not None
    assert f.must_not is None


def test_code_search_exclude_constant() -> None:
    assert QdrantService.CODE_SEARCH_EXCLUDE == {"kind": "commit"}
