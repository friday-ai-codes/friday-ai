"""文件级断点续传：FileIndex 在每个文件批 upsert 后立即 flush。
核心契约：
- run_git_diff_index 处理多个文件期间，若某次 upsert 失败抛异常，
 则之前已成功 upsert 的文件应在 FileIndex 中存下其 hash；
 只有未上传完毕的文件不在 FileIndex 中。
- 配合 git_diff 入口的 FileIndex hash 过滤 —— 重试时这些"已成功"
 文件被自然跳过，避免重新 embedding 浪费 token。
"""
from __future__ import annotations
import os
import tempfile
from typing import Any
from unittest.mock import AsyncMock, patch
import pytest
from repositories.models import FileIndex, Repository
from services.code_parser import CodeChunk
from services.indexer import IndexerService
pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]
@pytest.fixture(autouse=True)
def _stub_qdrant_and_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
 """stub Qdrant 调用 + 把 batch threshold 调到 1（每文件一批，便于精确控制）。"""
 from services import indexer as ix
 monkeypatch.setattr(ix, "qdrant_create_collection", AsyncMock(return_value=True))
 monkeypatch.setattr(ix, "qdrant_delete_by_file_path", AsyncMock(return_value=True))
 monkeypatch.setattr(ix, "qdrant_update_file_path", AsyncMock(return_value=True))
 monkeypatch.setattr(ix, "FILE_BATCH_CHUNK_THRESHOLD", 1)
 async def _noop_ensure(self: object, *a: object, **kw: object) -> None:
 return None
 async def _noop_graph(self: object, *a: object, **kw: object) -> None:
 return None
 async def _noop_branch_record(self: object, *a: object, **kw: object) -> None:
 return None
 monkeypatch.setattr(ix.IndexerService, "_ensure_collection", _noop_ensure)
 monkeypatch.setattr(ix.IndexerService, "_extract_and_write_graph", _noop_graph)
 monkeypatch.setattr(
 ix.IndexerService, "_update_branch_index_record", _noop_branch_record
 )
@pytest.fixture
async def repository -> Repository:
 return await Repository.objects.acreate(
 name="resume-repo",
 git_url="https://github.com/test/resume.git",
 git_platform="github",
 default_branch="main",
 )
def _mk_chunks_for_file(file_path: str, count: int = 1) -> list[CodeChunk]:
 return [
 CodeChunk(
 content=f"chunk {i} of {file_path}",
 file_path=file_path,
 file_hash=f"hash-{file_path}",
 language="python",
 start_line=i * 10,
 end_line=i * 10 + 5,
 node_type="function",
 context_header=f"# {file_path}",
 )
 for i in range(count)
 ]
def _diff_subprocess(diff_output: bytes) -> AsyncMock:
 proc = AsyncMock
 proc.communicate = AsyncMock(return_value=(diff_output, b""))
 proc.returncode = 0
 return proc
class TestFileLevelResume:
 async def test_partial_failure_persists_completed_files_to_file_index(
 self, repository: Repository
 ) -> None:
 """git_diff 中第 3 个文件 upsert 失败 → 前 2 个文件的 hash 写到 FileIndex。"""
 with tempfile.TemporaryDirectory as tmpdir:
 for fname in ["file_a.py", "file_b.py", "file_c.py"]:
 with open(os.path.join(tmpdir, fname), "w") as f:
 f.write(f"# {fname}\n")
 indexer = IndexerService(str(repository.id))
 diff_output = b"A\tfile_a.py\nA\tfile_b.py\nA\tfile_c.py\n"
 upsert_calls: list[int] =
 async def fake_upsert(repo_id: str, points: list[dict]) -> bool:
 upsert_calls.append(len(points))
 if len(upsert_calls) == 3:
 raise RuntimeError("embedding service 502")
 return True
 with (
 patch(
 "services.indexer.asyncio.create_subprocess_exec",
 return_value=_diff_subprocess(diff_output),
 ),
 patch(
 "services.indexer.asyncio.wait_for",
 new_callable=AsyncMock,
 return_value=(diff_output, b""),
 ),
 patch(
 "services.indexer.qdrant_upsert_vectors",
 side_effect=fake_upsert,
 ),
 patch.object(
 indexer.parser,
 "parse_file",
 side_effect=lambda full, base_path: _mk_chunks_for_file(
 os.path.relpath(full, base_path), 1
 ),
 ),
 patch(
 "services.indexer.EmbeddingService.generate_embeddings_batch",
 new_callable=AsyncMock,
 return_value=[[0.1, 0.2, 0.3]],
 ),
 ):
 with pytest.raises(RuntimeError):
 await indexer.run_git_diff_index(
 repo_path=tmpdir,
 from_sha="from",
 to_sha="to",
 )
 # 已成功完成的两个文件应写入 FileIndex
 completed_paths = [
 fp
 async for fp in FileIndex.objects.filter(
 repository_id=repository.id
 ).values_list("file_path", flat=True)
 ]
 assert sorted(completed_paths) == ["file_a.py", "file_b.py"], (
 f"前 2 个文件应已 flush 到 FileIndex，实际：{completed_paths}"
 )
 async def test_retry_skips_already_completed_files(
 self, repository: Repository
 ) -> None:
 """重试 git_diff 时，FileIndex 中 hash 一致的文件被跳过（不调用 embedding）。"""
 # 模拟"上次中断"：file_a/b 已写入 FileIndex
 await FileIndex.objects.acreate(
 repository_id=repository.id,
 file_path="file_a.py",
 file_hash="hash-file_a.py",
 )
 await FileIndex.objects.acreate(
 repository_id=repository.id,
 file_path="file_b.py",
 file_hash="hash-file_b.py",
 )
 with tempfile.TemporaryDirectory as tmpdir:
 for fname in ["file_a.py", "file_b.py", "file_c.py"]:
 with open(os.path.join(tmpdir, fname), "w") as f:
 f.write(f"# {fname}\n")
 indexer = IndexerService(str(repository.id))
 diff_output = b"A\tfile_a.py\nA\tfile_b.py\nA\tfile_c.py\n"
 embed_calls: list[list[str]] =
 async def fake_embed(texts: list[str], **kw: Any) -> list[list[float]]:
 embed_calls.append(texts)
 return [[0.1, 0.2, 0.3]] * len(texts)
 def fake_compute_hash(full_path: str) -> str:
 return f"hash-{os.path.basename(full_path)}"
 with (
 patch(
 "services.indexer.asyncio.create_subprocess_exec",
 return_value=_diff_subprocess(diff_output),
 ),
 patch(
 "services.indexer.asyncio.wait_for",
 new_callable=AsyncMock,
 return_value=(diff_output, b""),
 ),
 patch(
 "services.indexer.qdrant_upsert_vectors",
 new_callable=AsyncMock,
 return_value=True,
 ),
 patch(
 "services.indexer.compute_file_hash",
 side_effect=fake_compute_hash,
 ),
 patch.object(
 indexer.parser,
 "parse_file",
 side_effect=lambda full, base_path: _mk_chunks_for_file(
 os.path.relpath(full, base_path), 1
 ),
 ),
 patch(
 "services.indexer.EmbeddingService.generate_embeddings_batch",
 side_effect=fake_embed,
 ),
 ):
 result = await indexer.run_git_diff_index(
 repo_path=tmpdir,
 from_sha="from",
 to_sha="to",
 )
 # 仅 file_c.py 被实际 embed（file_a/b 因 hash 一致跳过）
 embedded_count = sum(len(call) for call in embed_calls)
 assert embedded_count == 1, (
 f"应只 embed 1 个 chunk（file_c），实际 {embedded_count}: {embed_calls}"
 )
 # 整体仍然 success；返回值 added 应反映实际新增计数（3 — 来自 git diff 解析）
 # 但 embedding 跳过了 2 个 = 节省 token
 assert result["status"] == "success"
