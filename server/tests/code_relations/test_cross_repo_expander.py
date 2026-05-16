"""Phase: cross_repo_expander wave 扩散测试。"""
from __future__ import annotations
import pytest
@pytest.mark.asyncio
async def test_expand_cross_repo_empty_items -> None:
 """空 rag_items → 立即返回，零 SQL。"""
 from code_relations.cross_repo_expander import expand_cross_repo
 result = await expand_cross_repo(
 rag_items=,
 repo_ids=["repo1"],
 reason_fn=lambda edge_type, **kw: "test",
 )
 assert result ==
@pytest.mark.asyncio
async def test_expand_cross_repo_no_file_paths -> None:
 """rag_items 无 file_path 字段 → 返回 。"""
 from code_relations.cross_repo_expander import expand_cross_repo
 result = await expand_cross_repo(
 rag_items=[{"id": "abc", "content": "no file_path here"}],
 repo_ids=["repo1"],
 reason_fn=lambda edge_type, **kw: "test",
 )
 assert result ==
@pytest.mark.django_db
@pytest.mark.asyncio
async def test_expand_cross_repo_no_cross_calls(repository) -> None:
 """没有 CrossRepoApiCall 数据时，两个方向都返回 。"""
 from code_relations.cross_repo_expander import expand_cross_repo
 result = await expand_cross_repo(
 rag_items=[{"file_path": "some/api.ts", "id": "fake-chunk-id"}],
 repo_ids=[str(repository.id)],
 reason_fn=lambda edge_type, **kw: "test",
 )
 assert result ==
@pytest.mark.django_db
@pytest.mark.asyncio
async def test_expand_cross_repo_exclude_chunks(repository) -> None:
 """exclude_chunk_ids 可以排除特定 chunk_id（不应报错）。"""
 from code_relations.cross_repo_expander import expand_cross_repo
 # 无 CrossRepoApiCall 数据，exclude 不应报错
 result = await expand_cross_repo(
 rag_items=[{"file_path": "src/api.ts"}],
 repo_ids=[str(repository.id)],
 reason_fn=lambda edge_type, **kw: "test",
 exclude_chunk_ids=frozenset({"some-excluded-chunk"}),
 )
 assert isinstance(result, list)
