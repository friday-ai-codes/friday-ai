"""``code_relations.symbol_chunk_binding.backfill_symbol_chunk_ids`` 单测。

mock ``SymbolChunkResolver``（避免依赖 Qdrant），验证：
- 命中的 Symbol 回填 chunk_id、未命中的保持 NULL；
- 返回本次实际绑定数；
- resolver 异常时优雅降级（不抛、返回 0）。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


async def _make_symbol(repository, name, file_path, start_line, end_line):
    from codegraph.models import Symbol

    return await Symbol.objects.acreate(
        repository=repository,
        name=name,
        symbol_type="FUNCTION",
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
    )


async def test_backfill_binds_hit_symbols_only(repository) -> None:
    from code_relations.symbol_chunk_binding import backfill_symbol_chunk_ids

    s_hit = await _make_symbol(repository, "foo", "a.py", 3, 5)
    s_miss = await _make_symbol(repository, "bar", "a.py", 100, 120)

    cid = uuid.uuid4()

    async def fake_resolve(file_path: str, line: int):
        return cid if line == 3 else None

    with patch(
        "code_relations.symbol_chunk_binding.SymbolChunkResolver"
    ) as MockResolver:
        MockResolver.return_value.resolve = AsyncMock(side_effect=fake_resolve)
        bound = await backfill_symbol_chunk_ids(str(repository.id))

    assert bound == 1
    await s_hit.arefresh_from_db()
    await s_miss.arefresh_from_db()
    assert s_hit.chunk_id == cid
    assert s_miss.chunk_id is None


async def test_backfill_skips_unchanged(repository) -> None:
    from code_relations.symbol_chunk_binding import backfill_symbol_chunk_ids

    cid = uuid.uuid4()
    sym = await _make_symbol(repository, "foo", "a.py", 3, 5)
    sym.chunk_id = cid
    await sym.asave(update_fields=["chunk_id"])

    with patch(
        "code_relations.symbol_chunk_binding.SymbolChunkResolver"
    ) as MockResolver:
        MockResolver.return_value.resolve = AsyncMock(return_value=cid)
        bound = await backfill_symbol_chunk_ids(str(repository.id))

    # chunk_id 未变化 → 不计入更新数
    assert bound == 0


async def test_backfill_graceful_on_resolver_error(repository) -> None:
    from code_relations.symbol_chunk_binding import backfill_symbol_chunk_ids

    await _make_symbol(repository, "foo", "a.py", 3, 5)

    with patch(
        "code_relations.symbol_chunk_binding.SymbolChunkResolver",
        side_effect=RuntimeError("qdrant down"),
    ):
        bound = await backfill_symbol_chunk_ids(str(repository.id))

    # 异常隔离：不抛，返回 0
    assert bound == 0
