"""SymbolChunkResolver 测试（per initial implementation contract）。"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from code_relations.symbol_lookup import SymbolChunkResolver


def _make_point(point_id: str, file_path: str | None, ls: int | None, le: int | None) -> MagicMock:
    p = MagicMock()
    p.id = point_id
    payload: dict = {}
    if file_path is not None:
        payload["file_path"] = file_path
    if ls is not None:
        payload["start_line"] = ls
    if le is not None:
        payload["end_line"] = le
    p.payload = payload
    return p


CID_A = "11111111-1111-1111-1111-111111111111"
CID_B = "22222222-2222-2222-2222-222222222222"
CID_C = "33333333-3333-3333-3333-333333333333"


def _scroll_factory(points: list[MagicMock]) -> MagicMock:
    """返回 mock client 单次 scroll 拿全部 points。"""
    client = MagicMock()
    client.scroll.return_value = (points, None)
    return client


async def test_resolve_basic_bisect_hits() -> None:
    points = [
        _make_point(CID_A, "src/a.py", 1, 20),
        _make_point(CID_B, "src/a.py", 21, 40),
        _make_point(CID_C, "src/a.py", 41, 60),
    ]
    mock_client = _scroll_factory(points)
    with patch("code_relations.symbol_lookup.QdrantService.get_client", return_value=mock_client), patch(
        "code_relations.symbol_lookup.get_effective_collection_name", return_value="repo_x"
    ):
        resolver = SymbolChunkResolver("repo-uuid")
        assert await resolver.resolve("src/a.py", 10) == uuid.UUID(CID_A)
        assert await resolver.resolve("src/a.py", 30) == uuid.UUID(CID_B)
        assert await resolver.resolve("src/a.py", 50) == uuid.UUID(CID_C)
        assert await resolver.resolve("src/a.py", 100) is None
        assert await resolver.resolve("missing.py", 1) is None


async def test_resolve_lazy_load_and_cache() -> None:
    """连续 100 次 resolve 调用，scroll 仅触发一次（lazy + cache）。"""
    points = [_make_point(CID_A, "src/a.py", 1, 20)]
    mock_client = _scroll_factory(points)
    with patch("code_relations.symbol_lookup.QdrantService.get_client", return_value=mock_client), patch(
        "code_relations.symbol_lookup.get_effective_collection_name", return_value="repo_x"
    ):
        resolver = SymbolChunkResolver("repo-uuid")
        for _ in range(100):
            await resolver.resolve("src/a.py", 5)
        assert mock_client.scroll.call_count == 1


async def test_resolve_no_call_before_first_resolve() -> None:
    """实例化不立即调 scroll；首次 resolve 才触发。"""
    points: list[MagicMock] = []
    mock_client = _scroll_factory(points)
    with patch("code_relations.symbol_lookup.QdrantService.get_client", return_value=mock_client), patch(
        "code_relations.symbol_lookup.get_effective_collection_name", return_value="repo_x"
    ):
        resolver = SymbolChunkResolver("repo-uuid")
        assert mock_client.scroll.call_count == 0
        await resolver.resolve("src/a.py", 1)
        assert mock_client.scroll.call_count == 1


async def test_resolve_skip_invalid_uuid() -> None:
    """非法 UUID 的 point.id 静默 skip，不抛错。"""
    points = [
        _make_point("not-a-uuid", "src/a.py", 1, 20),
        _make_point(CID_A, "src/a.py", 1, 20),
    ]
    mock_client = _scroll_factory(points)
    with patch("code_relations.symbol_lookup.QdrantService.get_client", return_value=mock_client), patch(
        "code_relations.symbol_lookup.get_effective_collection_name", return_value="repo_x"
    ):
        resolver = SymbolChunkResolver("repo-uuid")
        assert await resolver.resolve("src/a.py", 5) == uuid.UUID(CID_A)


async def test_resolve_skip_payload_missing_fields() -> None:
    """payload 缺 start_line / end_line 的 point 被 skip。"""
    points = [
        _make_point(CID_A, "src/a.py", None, 20),  # 缺 start_line
        _make_point(CID_B, "src/a.py", 21, None),  # 缺 end_line
        _make_point(CID_C, "src/a.py", 41, 60),
    ]
    mock_client = _scroll_factory(points)
    with patch("code_relations.symbol_lookup.QdrantService.get_client", return_value=mock_client), patch(
        "code_relations.symbol_lookup.get_effective_collection_name", return_value="repo_x"
    ):
        resolver = SymbolChunkResolver("repo-uuid")
        assert await resolver.resolve("src/a.py", 50) == uuid.UUID(CID_C)
        assert await resolver.resolve("src/a.py", 30) is None  # 缺字段那条没入索引
