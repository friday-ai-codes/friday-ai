"""`code_relations.utils.generate_chunk_id` 确定性与分散性单测（Pitfall 1 防御）。"""
from __future__ import annotations
import uuid
import pytest
from code_relations.constants import NAMESPACE_REPO
from code_relations.utils import generate_chunk_id
def test_generate_chunk_id_deterministic_same_triplet -> None:
 """同三元组两次调用必须返回完全相等的 UUID（per 确定性）。"""
 cid1 = generate_chunk_id("repo-A", "src/foo.py", 0)
 cid2 = generate_chunk_id("repo-A", "src/foo.py", 0)
 assert cid1 == cid2
@pytest.mark.parametrize(
 ("repo_a", "repo_b"),
 [("repo-A", "repo-B"), ("uuid-1111", "uuid-2222")],
)
def test_generate_chunk_id_differs_by_repo_id(repo_a: str, repo_b: str) -> None:
 """相同 (file_path, chunk_index) 但不同 repo_id 必须产出不同 UUID。"""
 cid_a = generate_chunk_id(repo_a, "src/foo.py", 0)
 cid_b = generate_chunk_id(repo_b, "src/foo.py", 0)
 assert cid_a != cid_b
def test_generate_chunk_id_differs_by_file_path -> None:
 """相同 (repo_id, chunk_index) 但不同 file_path 必须产出不同 UUID。"""
 cid_a = generate_chunk_id("repo-A", "src/a.py", 0)
 cid_b = generate_chunk_id("repo-A", "src/b.py", 0)
 assert cid_a != cid_b
def test_generate_chunk_id_differs_by_chunk_index -> None:
 """相同 (repo_id, file_path) 但不同 chunk_index（0/1/99）必须三个互不相同。"""
 cid_0 = generate_chunk_id("repo-A", "src/foo.py", 0)
 cid_1 = generate_chunk_id("repo-A", "src/foo.py", 1)
 cid_99 = generate_chunk_id("repo-A", "src/foo.py", 99)
 assert cid_0 != cid_1
 assert cid_0 != cid_99
 assert cid_1 != cid_99
def test_namespace_repo_literal_locked -> None:
 """Pitfall 1 防御性断言：NAMESPACE_REPO 字面值不允许被无意改动（per ）。
 任何对此常量的修改都会导致历史全量 chunk_id 漂移，Qdrant payload 与
 ChunkRegistry 全军覆没；此测试是常量字面值的最后一道护栏。
 """
 assert NAMESPACE_REPO == uuid.UUID("00000000-0000-5000-a000-000000000001")
def test_generate_chunk_id_returns_uuid_instance -> None:
 """返回类型必须是 uuid.UUID 实例而非 str（调用方按需 str(cid) 自行转字符串）。"""
 cid = generate_chunk_id("repo-A", "src/foo.py", 0)
 assert isinstance(cid, uuid.UUID)
 assert not isinstance(cid, str)
