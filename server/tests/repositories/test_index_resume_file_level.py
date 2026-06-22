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
async def repository() -> Repository:
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
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(diff_output, b""))
    proc.returncode = 0
    return proc


class TestFileLevelResume:
    async def test_partial_failure_persists_completed_files_to_file_index(
        self, repository: Repository
    ) -> None:
        """git_diff 中第 3 个文件 upsert 失败 → 前 2 个文件的 hash 写到 FileIndex。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            for fname in ["file_a.py", "file_b.py", "file_c.py"]:
                with open(os.path.join(tmpdir, fname), "w") as f:
                    f.write(f"# {fname}\n")

            indexer = IndexerService(str(repository.id))
            diff_output = b"A\tfile_a.py\nA\tfile_b.py\nA\tfile_c.py\n"

            upsert_calls: list[int] = []

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
                    "parse_file_dual",
                    side_effect=lambda full, base_path, repository_id="": (
                        _mk_chunks_for_file(os.path.relpath(full, base_path), 1),
                        None,
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

        with tempfile.TemporaryDirectory() as tmpdir:
            for fname in ["file_a.py", "file_b.py", "file_c.py"]:
                with open(os.path.join(tmpdir, fname), "w") as f:
                    f.write(f"# {fname}\n")

            indexer = IndexerService(str(repository.id))
            diff_output = b"A\tfile_a.py\nA\tfile_b.py\nA\tfile_c.py\n"

            embed_calls: list[list[str]] = []

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
                    "parse_file_dual",
                    side_effect=lambda full, base_path, repository_id="": (
                        _mk_chunks_for_file(os.path.relpath(full, base_path), 1),
                        None,
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


class TestFullIndexResume:
    """contract：run_full_index 重构为按文件批 _flush_batch 后的续传契约。

    关键不变量：
      - 中断后 FileIndex 保留已 flush 的文件锚点。
      - 再次进入 run_full_index 时，hash 命中的文件直接 skip，
        ``indexed_files_processed`` 从 skip 数起步（百分比续接而非归零）。
      - embedding 不被重复触发，避免重复消耗 token。
    """

    async def test_partial_failure_persists_completed_files_to_file_index(
        self, repository: Repository
    ) -> None:
        """run_full_index 第 3 个文件 upsert 失败 → 前 2 个的 hash 已在 FileIndex。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            for fname in ["file_a.py", "file_b.py", "file_c.py"]:
                with open(os.path.join(tmpdir, fname), "w") as f:
                    f.write(f"# {fname}\n")

            indexer = IndexerService(str(repository.id))
            scanned = [os.path.join(tmpdir, n) for n in ["file_a.py", "file_b.py", "file_c.py"]]
            upsert_calls: list[int] = []

            async def fake_upsert(repo_id: str, points: list[dict]) -> bool:
                upsert_calls.append(len(points))
                if len(upsert_calls) == 3:
                    raise RuntimeError("qdrant 502")
                return True

            def fake_compute_hash(full_path: str) -> str:
                return f"hash-{os.path.basename(full_path)}"

            with (
                patch("services.indexer.scan_directory", return_value=scanned),
                patch("services.indexer.compute_file_hash", side_effect=fake_compute_hash),
                patch(
                    "services.indexer.get_files_last_commit",
                    new_callable=AsyncMock,
                    return_value={},
                ),
                patch(
                    "services.indexer.qdrant_upsert_vectors", side_effect=fake_upsert,
                ),
                patch.object(
                    indexer.parser,
                    "parse_file_dual",
                    side_effect=lambda full, base_path, repository_id="": (
                        _mk_chunks_for_file(os.path.relpath(full, base_path), 1),
                        None,
                    ),
                ),
                patch(
                    "services.indexer.EmbeddingService.generate_embeddings_batch",
                    new_callable=AsyncMock,
                    return_value=[[0.1, 0.2, 0.3]],
                ),
            ):
                with pytest.raises(RuntimeError):
                    await indexer.run_full_index(tmpdir)

        completed_paths = sorted(
            [
                fp
                async for fp in FileIndex.objects.filter(
                    repository_id=repository.id
                ).values_list("file_path", flat=True)
            ]
        )
        assert completed_paths == ["file_a.py", "file_b.py"], (
            f"前 2 个文件应已 flush 到 FileIndex（续传锚点），实际：{completed_paths}"
        )

    async def test_full_index_progress_advances_in_lockstep_with_flushes(
        self, repository: Repository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_full_index 进度必须随 batch flush 同步推进，
        不能"先 parse 完所有文件 → processed=total → UI 立刻 100% 然后僵死"。
        """
        from services import indexer as ix

        # threshold=2 让 5 文件至少触发 3 次 flush
        monkeypatch.setattr(ix, "FILE_BATCH_CHUNK_THRESHOLD", 2)

        with tempfile.TemporaryDirectory() as tmpdir:
            names = ["a.py", "b.py", "c.py", "d.py", "e.py"]
            for fname in names:
                with open(os.path.join(tmpdir, fname), "w") as f:
                    f.write(f"# {fname}\n")

            indexer = IndexerService(str(repository.id))
            scanned = [os.path.join(tmpdir, n) for n in names]

            def fake_compute_hash(full_path: str) -> str:
                return f"hash-{os.path.basename(full_path)}"

            progress_calls: list[dict[str, Any]] = []

            async def fake_update_current(
                repo_id: str,
                *,
                file_path: str | None = None,
                processed: int | None = None,
                total: int | None = None,
            ) -> None:
                progress_calls.append(
                    {"file_path": file_path, "processed": processed, "total": total}
                )

            with (
                patch("services.indexer.scan_directory", return_value=scanned),
                patch("services.indexer.compute_file_hash", side_effect=fake_compute_hash),
                patch(
                    "services.indexer.get_files_last_commit",
                    new_callable=AsyncMock,
                    return_value={},
                ),
                patch(
                    "services.indexer.qdrant_upsert_vectors",
                    new_callable=AsyncMock,
                    return_value=True,
                ),
                patch(
                    "services.indexer.update_current_indexing_file",
                    side_effect=fake_update_current,
                ),
                patch.object(
                    indexer.parser,
                    "parse_file_dual",
                    side_effect=lambda full, base_path, repository_id="": (
                        _mk_chunks_for_file(os.path.relpath(full, base_path), 1),
                        None,
                    ),
                ),
                patch(
                    "services.indexer.EmbeddingService.generate_embeddings_batch",
                    new_callable=AsyncMock,
                    return_value=[[0.1, 0.2, 0.3]] * 2,
                ),
            ):
                result = await indexer.run_full_index(tmpdir)

        assert result["status"] == "success"

        processed_seq = [
            c["processed"] for c in progress_calls if c["processed"] is not None
        ]
        # 关键不变量：进度必须出现 0 < p < total 的中间值（即 flush 推进），
        # 而不是 [0, 5, 5, 5, 5, 5]（直接跳满）
        intermediate = sorted({p for p in processed_seq if 0 < p < 5})
        assert intermediate, (
            f"flush 阶段必须推进 processed 中间值，实际进度序列={processed_seq}"
        )

    async def test_qdrant_upsert_failure_reports_stage_and_batch_context(
        self, repository: Repository
    ) -> None:
        """Qdrant 写入失败时，错误必须说明具体阶段、文件和 batch 位置。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            fname = "file_a.py"
            with open(os.path.join(tmpdir, fname), "w") as f:
                f.write(f"# {fname}\n")

            indexer = IndexerService(str(repository.id))
            scanned = [os.path.join(tmpdir, fname)]

            def fake_compute_hash(full_path: str) -> str:
                return f"hash-{os.path.basename(full_path)}"

            with (
                patch("services.indexer.scan_directory", return_value=scanned),
                patch("services.indexer.compute_file_hash", side_effect=fake_compute_hash),
                patch(
                    "services.indexer.get_files_last_commit",
                    new_callable=AsyncMock,
                    return_value={},
                ),
                patch(
                    "services.indexer.qdrant_upsert_vectors",
                    new_callable=AsyncMock,
                    return_value=False,
                ),
                patch.object(
                    indexer.parser,
                    "parse_file_dual",
                    side_effect=lambda full, base_path, repository_id="": (
                        _mk_chunks_for_file(os.path.relpath(full, base_path), 1),
                        None,
                    ),
                ),
                patch(
                    "services.indexer.EmbeddingService.generate_embeddings_batch",
                    new_callable=AsyncMock,
                    return_value=[[0.1, 0.2, 0.3]],
                ),
            ):
                with pytest.raises(RuntimeError) as exc_info:
                    await indexer.run_full_index(tmpdir)

        message = str(exc_info.value)
        assert "写入向量库" in message
        assert "file_a.py" in message
        assert "batch 1/1" in message

    async def test_retry_skips_already_completed_files_and_resumes_progress(
        self, repository: Repository
    ) -> None:
        """重试 run_full_index 时：FileIndex 命中的文件被跳过、进度从 skip 数起步。"""
        # 模拟上次已 flush 的两个文件
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

        with tempfile.TemporaryDirectory() as tmpdir:
            for fname in ["file_a.py", "file_b.py", "file_c.py"]:
                with open(os.path.join(tmpdir, fname), "w") as f:
                    f.write(f"# {fname}\n")

            indexer = IndexerService(str(repository.id))
            scanned = [os.path.join(tmpdir, n) for n in ["file_a.py", "file_b.py", "file_c.py"]]

            embed_calls: list[list[str]] = []

            async def fake_embed(texts: list[str], **kw: Any) -> list[list[float]]:
                embed_calls.append(texts)
                return [[0.1, 0.2, 0.3]] * len(texts)

            def fake_compute_hash(full_path: str) -> str:
                return f"hash-{os.path.basename(full_path)}"

            # 捕获 update_current_indexing_file 调用，验证 processed 从 skip 数起步
            file_progress_calls: list[dict[str, Any]] = []

            async def fake_update_current(
                repo_id: str,
                *,
                file_path: str | None = None,
                processed: int | None = None,
                total: int | None = None,
            ) -> None:
                file_progress_calls.append(
                    {"file_path": file_path, "processed": processed, "total": total}
                )

            with (
                patch("services.indexer.scan_directory", return_value=scanned),
                patch("services.indexer.compute_file_hash", side_effect=fake_compute_hash),
                patch(
                    "services.indexer.get_files_last_commit",
                    new_callable=AsyncMock,
                    return_value={},
                ),
                # resume skip 需 Qdrant 实际确认：collection 里确有 file_a/file_b 同 hash 向量
                patch(
                    "services.indexer.qdrant_get_stored_file_hashes",
                    new_callable=AsyncMock,
                    return_value={
                        "file_a.py": "hash-file_a.py",
                        "file_b.py": "hash-file_b.py",
                    },
                ),
                patch(
                    "services.indexer.qdrant_upsert_vectors",
                    new_callable=AsyncMock,
                    return_value=True,
                ),
                patch(
                    "services.indexer.update_current_indexing_file",
                    side_effect=fake_update_current,
                ),
                patch.object(
                    indexer.parser,
                    "parse_file_dual",
                    side_effect=lambda full, base_path, repository_id="": (
                        _mk_chunks_for_file(os.path.relpath(full, base_path), 1),
                        None,
                    ),
                ),
                patch(
                    "services.indexer.EmbeddingService.generate_embeddings_batch",
                    side_effect=fake_embed,
                ),
            ):
                result = await indexer.run_full_index(tmpdir)

        # 仅 file_c 被 embed（file_a/b 因 hash 命中跳过）
        embedded_count = sum(len(call) for call in embed_calls)
        assert embedded_count == 1, (
            f"仅未索引的 file_c 应被 embed，实际 chunks={embedded_count}: {embed_calls}"
        )

        # 进度回放：必须有一次 processed=2 (skip baseline) 的调用，
        # 表示百分比从 2/3 起步而非 0/3
        baseline_calls = [
            c for c in file_progress_calls if c.get("processed") == 2 and c.get("total") == 3
        ]
        assert baseline_calls, (
            f"应从已 skip 的 2 个文件作为 baseline 上报进度，实际调用序列：{file_progress_calls}"
        )

        assert result["status"] == "success"
        # files_processed 是本次扫描的总数（向后兼容契约）
        assert result["files_processed"] == 3
        # 实际 upsert 的 chunk 数仅来自 file_c
        assert result["chunks_indexed"] == 1

    async def test_stale_file_index_with_empty_qdrant_forces_full_reindex(
        self, repository: Repository
    ) -> None:
        """回归（数据源一致性根治）：FileIndex 残留锚点 + Qdrant collection 为空时，
        run_full_index 必须忽略 FileIndex skip，对全部文件重新索引。

        复现的真实 bug：collection 被清空/重建（如启用 hybrid 命名向量）但 FileIndex
        锚点残留，旧逻辑仅凭 FileIndex hash 跳过这些文件 → 向量库永久残缺、且因 commit
        已标记完成无法靠"重新构建"自愈。
        """
        # 模拟"DB 锚点齐全但 Qdrant 实际为空"：3 个文件都有 FileIndex 锚点
        for fname in ["file_a.py", "file_b.py", "file_c.py"]:
            await FileIndex.objects.acreate(
                repository_id=repository.id,
                file_path=fname,
                file_hash=f"hash-{fname}",
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            for fname in ["file_a.py", "file_b.py", "file_c.py"]:
                with open(os.path.join(tmpdir, fname), "w") as f:
                    f.write(f"# {fname}\n")

            indexer = IndexerService(str(repository.id))
            scanned = [
                os.path.join(tmpdir, n)
                for n in ["file_a.py", "file_b.py", "file_c.py"]
            ]

            embed_calls: list[list[str]] = []

            async def fake_embed(texts: list[str], **kw: Any) -> list[list[float]]:
                embed_calls.append(texts)
                return [[0.1, 0.2, 0.3]] * len(texts)

            def fake_compute_hash(full_path: str) -> str:
                return f"hash-{os.path.basename(full_path)}"

            with (
                patch("services.indexer.scan_directory", return_value=scanned),
                patch("services.indexer.compute_file_hash", side_effect=fake_compute_hash),
                patch(
                    "services.indexer.get_files_last_commit",
                    new_callable=AsyncMock,
                    return_value={},
                ),
                # Qdrant collection 实际为空 → FileIndex 锚点全部不可信
                patch(
                    "services.indexer.qdrant_get_stored_file_hashes",
                    new_callable=AsyncMock,
                    return_value={},
                ),
                patch(
                    "services.indexer.qdrant_upsert_vectors",
                    new_callable=AsyncMock,
                    return_value=True,
                ),
                patch.object(
                    indexer.parser,
                    "parse_file_dual",
                    side_effect=lambda full, base_path, repository_id="": (
                        _mk_chunks_for_file(os.path.relpath(full, base_path), 1),
                        None,
                    ),
                ),
                patch(
                    "services.indexer.EmbeddingService.generate_embeddings_batch",
                    side_effect=fake_embed,
                ),
            ):
                result = await indexer.run_full_index(tmpdir)

        # 三个文件全部重新 embed（不再因残留 FileIndex 锚点被错误跳过）
        embedded_count = sum(len(call) for call in embed_calls)
        assert embedded_count == 3, (
            f"Qdrant 为空时应对全部 3 个文件重新索引，实际 embed chunks={embedded_count}"
        )
        assert result["status"] == "success"
        assert result["chunks_indexed"] == 3
