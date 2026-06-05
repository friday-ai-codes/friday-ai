"""explain_neighbor —— 6 类 EdgeType reason 模板单测（per initial implementation plan Task 1）。

兑现 contract / plan must-haves："_explain_neighbor(edge_type, source_payload,
target_payload, metadata) 生成 reason 字段"——本测试覆盖 6 类正向模板 + metadata
缺失 graceful fallback + unknown edge_type fallback，共 8 条断言：

1. CALL with target_file → "caller of {target_file} via direct call"
2. CALL without target_file → "via direct call" 降级
3. IMPORT with target_file → "imports module from {target_file}"
4. SAME_FILE with source_file → "same file as {source_file}"
5. TEST_OF with target_file → "test of {target_file}"
6. CO_CHANGED with metadata.commit_count → "co-changed with {target_file} × {N} commits"
7. SEMANTIC with metadata.similarity → "semantically similar (score={X:.2f})"
8. metadata=None / 空 dict / 缺字段 → graceful（不抛 KeyError）
9. unknown edge_type → "related via {edge_type}" fallback

模板纯函数，无 ORM / Django 依赖，pytest.mark.django_db 不需要。
"""

from __future__ import annotations

import pytest

from services.retrieval.find_related import explain_neighbor


# ---------------------------------------------------------------------------
# 6 类 edge_type 正向模板
# ---------------------------------------------------------------------------


def test_call_with_target_file() -> None:
    """CALL + target_file → "caller of {target_file} via direct call"。"""
    out = explain_neighbor("CALL", target_file="src/utils.py")
    assert "caller of" in out
    assert "src/utils.py" in out
    assert "direct call" in out


def test_call_without_target_file_falls_back() -> None:
    """CALL 无 target_file → fallback "via direct call"（不含 None / KeyError）。"""
    out = explain_neighbor("CALL")
    assert "direct call" in out
    assert "None" not in out


def test_import_with_target_file() -> None:
    """IMPORT + target_file → "imports module from {target_file}"。"""
    out = explain_neighbor("IMPORT", target_file="lib/auth.py")
    assert "imports module" in out
    assert "lib/auth.py" in out


def test_import_without_target_file_falls_back() -> None:
    """IMPORT 无 target_file → "imports module" fallback。"""
    out = explain_neighbor("IMPORT")
    assert "imports module" in out
    assert "None" not in out


def test_same_file_with_source_file() -> None:
    """SAME_FILE + source_file → "same file as {source_file}"。"""
    out = explain_neighbor("SAME_FILE", source_file="src/source.py")
    assert "same file" in out
    assert "src/source.py" in out


def test_same_file_without_source_file_falls_back() -> None:
    """SAME_FILE 无 source_file → "same file group" fallback。"""
    out = explain_neighbor("SAME_FILE")
    assert "same file" in out
    assert "None" not in out


def test_test_of_with_target_file() -> None:
    """TEST_OF + target_file → "test of {target_file}"。"""
    out = explain_neighbor("TEST_OF", target_file="src/foo.py")
    assert "test of" in out
    assert "src/foo.py" in out


def test_test_of_without_target_file_falls_back() -> None:
    """TEST_OF 无 target_file → "test relationship" fallback。"""
    out = explain_neighbor("TEST_OF")
    assert "test" in out.lower()
    assert "None" not in out


def test_co_changed_with_commit_count() -> None:
    """CO_CHANGED + metadata.commit_count + target_file → "co-changed with {file} × {N} commits"。"""
    out = explain_neighbor(
        "CO_CHANGED",
        target_file="src/related.py",
        metadata={"commit_count": 7},
    )
    assert "co-changed" in out
    assert "src/related.py" in out
    assert "7" in out
    assert "commits" in out


def test_co_changed_missing_metadata_falls_back() -> None:
    """CO_CHANGED metadata 缺 commit_count → "× recent history" graceful。"""
    out = explain_neighbor("CO_CHANGED", target_file="src/x.py", metadata={})
    assert "co-changed" in out
    assert "recent history" in out
    assert "None" not in out


def test_semantic_with_similarity() -> None:
    """SEMANTIC + metadata.similarity → "semantically similar (score={X:.2f})"。"""
    out = explain_neighbor("SEMANTIC", metadata={"similarity": 0.8456})
    assert "semantically similar" in out
    assert "0.85" in out  # :.2f rounding


def test_semantic_missing_similarity_falls_back() -> None:
    """SEMANTIC metadata 缺 similarity → "semantically similar" fallback。"""
    out = explain_neighbor("SEMANTIC", metadata={})
    assert "semantically similar" in out
    assert "None" not in out


# ---------------------------------------------------------------------------
# graceful：metadata=None / 空 dict / 全字段缺失
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "edge_type",
    ["CALL", "IMPORT", "SAME_FILE", "TEST_OF", "CO_CHANGED", "SEMANTIC"],
)
def test_metadata_none_graceful(edge_type: str) -> None:
    """所有 edge_type metadata=None / source_file=None / target_file=None
    → 走 fallback，不抛 KeyError，输出非空字符串。
    """
    out = explain_neighbor(edge_type, metadata=None)
    assert isinstance(out, str)
    assert len(out) > 0
    assert "None" not in out, f"{edge_type} fallback 不应含 'None' 字面: {out!r}"


# ---------------------------------------------------------------------------
# unknown edge_type → fallback
# ---------------------------------------------------------------------------


def test_unknown_edge_type_falls_back_to_generic_template() -> None:
    """未知 edge_type → "related via {edge_type}" fallback，不抛错。"""
    out = explain_neighbor("XYZ_UNKNOWN")
    assert "XYZ_UNKNOWN" in out
    assert "related via" in out


def test_unknown_edge_type_empty_string() -> None:
    """空字符串 edge_type → fallback 不抛错。"""
    out = explain_neighbor("")
    assert isinstance(out, str)
    assert len(out) > 0
