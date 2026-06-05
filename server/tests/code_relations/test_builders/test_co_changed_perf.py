"""CoChangedEdgeBuilder Pitfall RSS perf gate（per initial implementation contract / contract）。

100k commits × 5 files/commit 工况下 ``tracemalloc.get_traced_memory()`` peak < 1 GB。
CI 默认 skip（pyproject ``addopts = "-m 'not perf'"``）；本地用
``uv run --group dev pytest -m perf tests/code_relations/test_builders/test_co_changed_perf.py``
主动运行。
"""

from __future__ import annotations

import random
import tracemalloc
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from code_relations.builders.co_changed_edge import CoChangedEdgeBuilder

_RSS_LIMIT_BYTES = 1024 * 1024 * 1024  # 1 GB
_NUM_COMMITS = 100_000
_FILES_PER_COMMIT = 5
_FILE_POOL = 200


def _gen_lines() -> list[bytes]:
    """生成 100k commits × 5 files/commit 的 mock stdout 行（约 600k 行 / ~12 MB raw）。"""
    rng = random.Random(42)
    all_files = [f"src/file_{i:04d}.py" for i in range(_FILE_POOL)]
    lines: list[bytes] = []
    for cidx in range(_NUM_COMMITS):
        lines.append(f"COMMIT {cidx:040x}\n".encode())
        files_in_commit = rng.sample(all_files, _FILES_PER_COMMIT)
        for f in files_in_commit:
            lines.append(f"{f}\n".encode())
    return lines


class _LightStdout:
    """轻量 readline 桩；避开 ``unittest.mock.AsyncMock`` 在 600k+ 调用下累积
    ``call_args_list`` 造成 GB 级假阳性内存（per contract measurement 隔离）。
    """

    __slots__ = ("_iter",)

    def __init__(self, lines: list[bytes]) -> None:
        self._iter: Iterator[bytes] = iter([*lines, b""])

    async def readline(self) -> bytes:
        return next(self._iter)


class _LightStderr:
    __slots__ = ()

    async def read(self) -> bytes:
        return b""


class _LightProc:
    """轻量 ``asyncio.subprocess.Process`` 桩，仅暴露 builder 调用到的属性。"""

    __slots__ = ("stdout", "stderr", "returncode")

    def __init__(self, lines: list[bytes]) -> None:
        self.stdout = _LightStdout(lines)
        self.stderr = _LightStderr()
        self.returncode = 0

    async def wait(self) -> int:
        return self.returncode


def _make_proc(lines: list[bytes]) -> _LightProc:
    return _LightProc(lines)


@pytest.mark.perf
async def test_co_changed_100k_commits_rss_under_1gb(tmp_path) -> None:
    """100k commits 流式入 builder，tracemalloc peak < 1 GB（Pitfall RSS gate contract）。"""
    from repositories.models import Repository

    clone_path = tmp_path / "fake-large-repo"
    clone_path.mkdir()
    repo = MagicMock(spec=Repository)
    repo.id = "11111111-1111-1111-1111-111111111111"
    repo.clone_path = str(clone_path)

    lines = _gen_lines()  # 在 tracemalloc 之前生成，避免把 mock 数据本身算进 peak
    proc = _make_proc(lines)

    async def _spawn(*args: object, **kwargs: object) -> _LightProc:
        return proc

    async def _empty_chunks(*args: object, **kwargs: object) -> dict[str, list]:
        return {}

    tracemalloc.start()
    try:
        with (
            patch("asyncio.create_subprocess_exec", _spawn),
            patch(
                "code_relations.builders.co_changed_edge.CoChangedEdgeBuilder._load_file_chunks",
                _empty_chunks,
            ),
        ):
            edges = await CoChangedEdgeBuilder().build(repo, [])
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert peak < _RSS_LIMIT_BYTES, (
        f"Pitfall RSS gate violation: 100k commits × {_FILES_PER_COMMIT} files peak "
        f"{peak / 1024**2:.1f} MB, required < {_RSS_LIMIT_BYTES / 1024**2:.0f} MB (per contract)"
    )
    assert isinstance(edges, list)
