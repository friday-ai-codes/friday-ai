"""`IndexerService._upsert_chunk_registry_batch` ChunkRegistry upsert 集成测试。

per contract / contract：
- 新行 → created=True，返回 content_hash_changed=False
- 同 chunk_id 不同 content_hash → created=False，content_hash_changed=True，updated_at 推进
- 同 chunk_id 同 content_hash → created=False，content_hash_changed=False
- 同三元组 generate_chunk_id 命中 update 路径（chunk_id 不漂移）
"""

from __future__ import annotations

import pytest

from code_relations.models import ChunkRegistry
from code_relations.utils import generate_chunk_id
from services.indexer import IndexerService

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


def _make_row(
    *,
    chunk_id,
    repository_id: str,
    content_hash: str,
    file_path: str = "src/a.py",
    chunk_index: int = 0,
    branch_name: str = "",
    line_start: int | None = None,
    line_end: int | None = None,
) -> dict:
    return {
        "chunk_id": chunk_id,
        "content_hash": content_hash,
        "repository_id": repository_id,
        "file_path": file_path,
        "chunk_index": chunk_index,
        "branch_name": branch_name,
        "line_start": line_start,
        "line_end": line_end,
    }


async def test_upsert_registry_batch_creates_new_rows(repository) -> None:
    """3 行新 chunk_id → 全部 created=True，content_hash_changed=False；DB 内 3 条。"""
    indexer = IndexerService(repository_id=str(repository.id))
    rows = [
        _make_row(
            chunk_id=generate_chunk_id(str(repository.id), f"f{i}.py", 0),
            repository_id=str(repository.id),
            content_hash=f"{'a' * 63}{i}",
            file_path=f"f{i}.py",
        )
        for i in range(3)
    ]
    results = await indexer._upsert_chunk_registry_batch(rows)

    assert len(results) == 3
    assert all(changed is False for _, changed in results)
    assert await ChunkRegistry.objects.acount() == 3


async def test_upsert_registry_batch_same_chunk_id_diff_content_hash(repository) -> None:
    """同 chunk_id 两次调用，content_hash 变化 → 第二次 content_hash_changed=True，

    DB 内只剩一行（同 chunk_id 不漂移，per contract），updated_at 推进。
    """
    indexer = IndexerService(repository_id=str(repository.id))
    cid = generate_chunk_id(str(repository.id), "src/foo.py", 0)
    h1 = "a" * 64
    h2 = "b" * 64

    row_v1 = _make_row(
        chunk_id=cid,
        repository_id=str(repository.id),
        content_hash=h1,
        file_path="src/foo.py",
    )
    results1 = await indexer._upsert_chunk_registry_batch([row_v1])
    assert results1[0][1] is False

    obj_before = await ChunkRegistry.objects.aget(chunk_id=cid)
    created_at_before = obj_before.created_at
    updated_at_before = obj_before.updated_at

    row_v2 = _make_row(
        chunk_id=cid,
        repository_id=str(repository.id),
        content_hash=h2,
        file_path="src/foo.py",
    )
    results2 = await indexer._upsert_chunk_registry_batch([row_v2])
    assert results2[0][1] is True
    assert results2[0][0] == str(cid)

    assert await ChunkRegistry.objects.acount() == 1
    obj_after = await ChunkRegistry.objects.aget(chunk_id=cid)
    assert obj_after.content_hash == h2
    assert obj_after.created_at == created_at_before
    assert obj_after.updated_at > updated_at_before


async def test_upsert_registry_batch_same_chunk_id_same_content_hash(repository) -> None:
    """同 chunk_id 两次调用，content_hash 不变 → 第二次 content_hash_changed=False。"""
    indexer = IndexerService(repository_id=str(repository.id))
    cid = generate_chunk_id(str(repository.id), "src/foo.py", 0)
    h1 = "c" * 64
    row = _make_row(
        chunk_id=cid, repository_id=str(repository.id), content_hash=h1,
    )

    await indexer._upsert_chunk_registry_batch([row])
    results2 = await indexer._upsert_chunk_registry_batch([row])
    assert results2[0][1] is False
    assert await ChunkRegistry.objects.acount() == 1


async def test_upsert_registry_batch_chunk_id_stability_via_generate_chunk_id(
    repository,
) -> None:
    """重切分场景：同 (repo_id, file_path, chunk_index) 生成的 chunk_id 必命中 update 路径。

    第一次 generate_chunk_id 写入；第二次相同三元组生成的 chunk_id 应当与第一次完全相等，
    update_or_create 命中 update 而非 create。
    """
    indexer = IndexerService(repository_id=str(repository.id))

    triplet = (str(repository.id), "src/stable.py", 3)
    cid_first = generate_chunk_id(*triplet)
    cid_second = generate_chunk_id(*triplet)
    assert cid_first == cid_second

    rows1 = [_make_row(chunk_id=cid_first, repository_id=triplet[0], content_hash="d" * 64, file_path=triplet[1], chunk_index=triplet[2])]
    res1 = await indexer._upsert_chunk_registry_batch(rows1)
    rows2 = [_make_row(chunk_id=cid_second, repository_id=triplet[0], content_hash="e" * 64, file_path=triplet[1], chunk_index=triplet[2])]
    res2 = await indexer._upsert_chunk_registry_batch(rows2)

    assert res1[0][0] == res2[0][0]
    assert res2[0][1] is True
    assert await ChunkRegistry.objects.acount() == 1
