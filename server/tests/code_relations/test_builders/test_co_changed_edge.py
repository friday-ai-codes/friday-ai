"""CoChangedEdgeBuilder 单元测试（per Phase/20/21/22）。
覆盖：
- mock asyncio.create_subprocess_exec：流式喂 commit / file 行
- min_support=3 过滤；max_count 归一；0.5 chunk 折扣
- chunk 笛卡尔积 + 大文件保护（n > 50 → 仅取前 5）
- git returncode != 0 / clone_path 不存在 → 返回 （不抛错）
"""
from __future__ import annotations
import uuid
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from asgiref.sync import sync_to_async
from django.test import override_settings
from code_relations.builders.co_changed_edge import CoChangedEdgeBuilder
from code_relations.constants import CO_CHANGED_WINDOW_COMMITS
from code_relations.models import ChunkRegistry, EdgeType
def _make_mock_proc(stdout_lines: list[bytes], returncode: int = 0) -> MagicMock:
 """构造 mock ``asyncio.subprocess.Process``：readline 逐行 yield，wait/stderr 异步。"""
 iter_lines: Iterator[bytes] = iter([*stdout_lines, b""])
 mock_stdout = MagicMock
 mock_stdout.readline = AsyncMock(side_effect=lambda: next(iter_lines))
 mock_stderr = MagicMock
 mock_stderr.read = AsyncMock(return_value=b"")
 proc = MagicMock
 proc.stdout = mock_stdout
 proc.stderr = mock_stderr
 proc.wait = AsyncMock(return_value=returncode)
 proc.returncode = returncode
 return proc
@pytest.fixture
def repo_with_clone(repository, tmp_path):
 """复用 conftest.repository fixture，注入临时 clone_path（attr 注入；模型无该字段）。"""
 clone_dir = tmp_path / "clone" / str(repository.id)
 clone_dir.mkdir(parents=True)
 repository.clone_path = str(clone_dir)
 return repository
@sync_to_async
def _create_chunks_for_file(repository, file_path: str, n: int) -> list[uuid.UUID]:
 """批量创建 n 个 chunk for 单文件，返回 chunk_id 列表（递增 chunk_index）。"""
 objs = [
 ChunkRegistry(
 chunk_id=uuid.uuid4,
 content_hash="x" * 64,
 repository=repository,
 file_path=file_path,
 chunk_index=i,
 )
 for i in range(n)
 ]
 ChunkRegistry.objects.bulk_create(objs)
 return [o.chunk_id for o in objs]
@override_settings(CODEGRAPH_COCHANGE_MIN_SUPPORT=3)
@pytest.mark.django_db(transaction=True)
async def test_basic_co_change_min_support_filter(repo_with_clone) -> None:
 """5 commits：(a.py,b.py) co-change 4 次 / (c.py,d.py) 2 次，仅前者过 min_support=3。
 Phase B3：默认 min_support 已降为 2（per Pitfall 7），用 override_settings
 锁定旧 min_support=3 契约。
 """
 lines = [
 b"COMMIT c1\n", b"src/a.py\n", b"src/b.py\n",
 b"COMMIT c2\n", b"src/a.py\n", b"src/b.py\n", b"src/c.py\n",
 b"COMMIT c3\n", b"src/a.py\n", b"src/b.py\n",
 b"COMMIT c4\n", b"src/a.py\n", b"src/b.py\n", b"src/c.py\n", b"src/d.py\n",
 b"COMMIT c5\n", b"src/c.py\n", b"src/d.py\n",
 ]
 await _create_chunks_for_file(repo_with_clone, "src/a.py", 1)
 await _create_chunks_for_file(repo_with_clone, "src/b.py", 1)
 await _create_chunks_for_file(repo_with_clone, "src/c.py", 1)
 await _create_chunks_for_file(repo_with_clone, "src/d.py", 1)
 with patch(
 "asyncio.create_subprocess_exec",
 AsyncMock(return_value=_make_mock_proc(lines)),
 ):
 edges = await CoChangedEdgeBuilder.build(repo_with_clone, )
 assert len(edges) == 1
 e = edges[0]
 assert e.edge_type == EdgeType.CO_CHANGED
 assert e.weight == pytest.approx(0.5) # file_weight=4/4=1.0, *0.5 折扣
 assert e.metadata["co_change_count"] == 4
 assert e.metadata["file_a"] == "src/a.py"
 assert e.metadata["file_b"] == "src/b.py"
 assert len(e.metadata["commit_hashes"]) <= 5
 assert "c1" in e.metadata["commit_hashes"]
@pytest.mark.django_db(transaction=True)
async def test_chunk_cartesian_product(repo_with_clone) -> None:
 """a.py 2 chunks × b.py 3 chunks → 笛卡尔积 6 边（ 方案 A）。"""
 lines = [
 b"COMMIT c1\n", b"a.py\n", b"b.py\n",
 b"COMMIT c2\n", b"a.py\n", b"b.py\n",
 b"COMMIT c3\n", b"a.py\n", b"b.py\n",
 ]
 await _create_chunks_for_file(repo_with_clone, "a.py", 2)
 await _create_chunks_for_file(repo_with_clone, "b.py", 3)
 with patch(
 "asyncio.create_subprocess_exec",
 AsyncMock(return_value=_make_mock_proc(lines)),
 ):
 edges = await CoChangedEdgeBuilder.build(repo_with_clone, )
 assert len(edges) == 6
 for e in edges:
 assert e.weight == pytest.approx(0.5)
 assert str(e.source_chunk_id) < str(e.target_chunk_id)
@pytest.mark.django_db(transaction=True)
async def test_large_file_protection(repo_with_clone) -> None:
 """a.py 100 chunks (>50 阈值，仅取前 5) × b.py 3 chunks → 5×3 = 15 边（ + ）。"""
 lines = [
 b"COMMIT c1\n", b"a.py\n", b"b.py\n",
 b"COMMIT c2\n", b"a.py\n", b"b.py\n",
 b"COMMIT c3\n", b"a.py\n", b"b.py\n",
 ]
 await _create_chunks_for_file(repo_with_clone, "a.py", 100)
 await _create_chunks_for_file(repo_with_clone, "b.py", 3)
 with patch(
 "asyncio.create_subprocess_exec",
 AsyncMock(return_value=_make_mock_proc(lines)),
 ):
 edges = await CoChangedEdgeBuilder.build(repo_with_clone, )
 assert len(edges) == 15
@pytest.mark.django_db(transaction=True)
async def test_git_returncode_nonzero_returns_empty(repo_with_clone) -> None:
 """git proc.returncode != 0 + counter 不足 min_support → log warning +
 返回 （partial 保留但下游 filter 仍空）。"""
 await _create_chunks_for_file(repo_with_clone, "a.py", 1)
 await _create_chunks_for_file(repo_with_clone, "b.py", 1)
 proc = _make_mock_proc([b"COMMIT c1\n", b"a.py\n", b"b.py\n"], returncode=128)
 with patch(
 "asyncio.create_subprocess_exec",
 AsyncMock(return_value=proc),
 ):
 edges = await CoChangedEdgeBuilder.build(repo_with_clone, )
 assert edges ==
@pytest.mark.django_db(transaction=True)
async def test_git_returncode_nonzero_preserves_partial_data(repo_with_clone) -> None:
 """ 回归：returncode != 0 但已采集 ≥ min_support 的 partial counter →
 保留 partial 数据生成 edges（不丢弃 N-1 commit 的真实贡献）。"""
 lines = [
 b"COMMIT c1\n", b"a.py\n", b"b.py\n",
 b"COMMIT c2\n", b"a.py\n", b"b.py\n",
 b"COMMIT c3\n", b"a.py\n", b"b.py\n",
 ]
 await _create_chunks_for_file(repo_with_clone, "a.py", 1)
 await _create_chunks_for_file(repo_with_clone, "b.py", 1)
 proc = _make_mock_proc(lines, returncode=128)
 with patch(
 "asyncio.create_subprocess_exec",
 AsyncMock(return_value=proc),
 ):
 edges = await CoChangedEdgeBuilder.build(repo_with_clone, )
 assert len(edges) == 1
 assert edges[0].metadata["co_change_count"] == 3
@pytest.mark.django_db(transaction=True)
async def test_stderr_drained_concurrently_does_not_deadlock(
 repo_with_clone,
) -> None:
 """ 回归：mock 子进程 stderr 喷 100KB（超 64KB pipe buffer），并发 drain
 正常退出 → 不卡死（asyncio.wait_for 5s 超时即视为死锁）。"""
 import asyncio as _asyncio
 stdout_lines = [
 b"COMMIT c1\n", b"a.py\n", b"b.py\n",
 b"COMMIT c2\n", b"a.py\n", b"b.py\n",
 b"COMMIT c3\n", b"a.py\n", b"b.py\n",
 ]
 iter_stdout: Iterator[bytes] = iter([*stdout_lines, b""])
 mock_stdout = MagicMock
 mock_stdout.readline = AsyncMock(side_effect=lambda: next(iter_stdout))
 big_chunk = b"X" * 4096
 stderr_total = 100 * 1024 # 100KB > pipe buffer 64KB
 stderr_chunks = [big_chunk] * (stderr_total // len(big_chunk)) + [b""]
 iter_stderr: Iterator[bytes] = iter(stderr_chunks)
 mock_stderr = MagicMock
 mock_stderr.read = AsyncMock(side_effect=lambda *_a, **_kw: next(iter_stderr))
 proc = MagicMock
 proc.stdout = mock_stdout
 proc.stderr = mock_stderr
 proc.wait = AsyncMock(return_value=0)
 proc.returncode = 0
 await _create_chunks_for_file(repo_with_clone, "a.py", 1)
 await _create_chunks_for_file(repo_with_clone, "b.py", 1)
 with patch(
 "asyncio.create_subprocess_exec", AsyncMock(return_value=proc)
 ):
 edges = await _asyncio.wait_for(
 CoChangedEdgeBuilder.build(repo_with_clone, ), timeout=5.0
 )
 assert len(edges) == 1
@pytest.mark.django_db(transaction=True)
async def test_no_clone_path_returns_empty(repository, tmp_path) -> None:
 """clone_path 不存在 → 直接返回 （不抛 FileNotFoundError）。"""
 repository.clone_path = str(tmp_path / "does-not-exist-xyz")
 edges = await CoChangedEdgeBuilder.build(repository, )
 assert edges ==
@override_settings(CODEGRAPH_COCHANGE_MIN_SUPPORT=3)
@pytest.mark.django_db(transaction=True)
async def test_below_min_support_no_edges(repo_with_clone) -> None:
 """(a.py,b.py) 共变更 2 次 < min_support=3 → 0 边。
 Phase B3：默认 min_support 已降为 2（per Pitfall 7），override_settings 锁旧契约。
 """
 lines = [
 b"COMMIT c1\n", b"a.py\n", b"b.py\n",
 b"COMMIT c2\n", b"a.py\n", b"b.py\n",
 ]
 await _create_chunks_for_file(repo_with_clone, "a.py", 1)
 await _create_chunks_for_file(repo_with_clone, "b.py", 1)
 with patch(
 "asyncio.create_subprocess_exec",
 AsyncMock(return_value=_make_mock_proc(lines)),
 ):
 edges = await CoChangedEdgeBuilder.build(repo_with_clone, )
 assert edges ==
@pytest.mark.django_db(transaction=True)
async def test_empty_git_log(repo_with_clone) -> None:
 """空 stdout → 0 边。"""
 with patch(
 "asyncio.create_subprocess_exec",
 AsyncMock(return_value=_make_mock_proc),
 ):
 edges = await CoChangedEdgeBuilder.build(repo_with_clone, )
 assert edges ==
@override_settings(CODEGRAPH_COCHANGE_MIN_SUPPORT=3)
@pytest.mark.django_db(transaction=True)
async def test_max_count_normalization(repo_with_clone) -> None:
 """两对 pair：(a.py,b.py) co-change 6 次（max）/ (a.py,c.py) co-change 3 次。
 a.py max_count=6 → file_weight_ab=6/6=1.0, edge_weight_ab=0.5；
 file_weight_ac=3/6=0.5, edge_weight_ac=0.25。
 Phase B3：override_settings 锁旧 min_support=3 契约（per Pitfall 7）。
 """
 lines: list[bytes] =
 for i in range(6):
 lines.extend([f"COMMIT c{i}\n".encode, b"a.py\n", b"b.py\n"])
 for i in range(3):
 lines.extend([f"COMMIT d{i}\n".encode, b"a.py\n", b"c.py\n"])
 await _create_chunks_for_file(repo_with_clone, "a.py", 1)
 await _create_chunks_for_file(repo_with_clone, "b.py", 1)
 await _create_chunks_for_file(repo_with_clone, "c.py", 1)
 with patch(
 "asyncio.create_subprocess_exec",
 AsyncMock(return_value=_make_mock_proc(lines)),
 ):
 edges = await CoChangedEdgeBuilder.build(repo_with_clone, )
 by_pair = {
 tuple(sorted([e.metadata["file_a"], e.metadata["file_b"]])): e
 for e in edges
 }
 assert by_pair[("a.py", "b.py")].weight == pytest.approx(0.5)
 assert by_pair[("a.py", "c.py")].weight == pytest.approx(0.25)
# =============================================================================
# Phase 三重 bug 修复（ "0 条" 根因）守门测试
# =============================================================================
@pytest.mark.django_db(transaction=True)
async def test_no_clone_path_emits_diagnostic_fields(repository, tmp_path) -> None:
 """Phase B1：clone_path 不存在 → log warning 含 attr_clone_path /
 settings_repo_clone_dir / decision 三诊断字段（让 prod 0 条根因可定位）。"""
 import structlog
 repository.clone_path = str(tmp_path / "does-not-exist-xyz")
 with structlog.testing.capture_logs as caps:
 edges = await CoChangedEdgeBuilder.build(repository, )
 assert edges ==
 warnings = [
 e for e in caps if e.get("event") == "co_changed_skip_no_clone_path"
 ]
 assert len(warnings) >= 1
 log = warnings[-1]
 assert "attr_clone_path" in log
 assert "settings_repo_clone_dir" in log
 assert log.get("decision") == "skip_builder"
@pytest.mark.django_db(transaction=True)
async def test_git_uses_max_count_not_since(repo_with_clone) -> None:
 """Phase B2：git args 必须含 --max-count={CO_CHANGED_WINDOW_COMMITS}，
 不含 --since={anything}（让 constants.CO_CHANGED_WINDOW_COMMITS 字面承诺真生效）。"""
 await _create_chunks_for_file(repo_with_clone, "a.py", 1)
 await _create_chunks_for_file(repo_with_clone, "b.py", 1)
 captured_args: list[tuple] =
 async def _spy_create(*args, **kwargs):
 captured_args.append(args)
 return _make_mock_proc(
 [b"COMMIT c1\n", b"a.py\n", b"b.py\n", b"COMMIT c2\n", b"a.py\n", b"b.py\n"]
 )
 with patch("asyncio.create_subprocess_exec", _spy_create):
 await CoChangedEdgeBuilder.build(repo_with_clone, )
 assert captured_args, "git log subprocess never invoked"
 git_args = captured_args[0]
 expected = f"--max-count={CO_CHANGED_WINDOW_COMMITS}"
 assert expected in git_args, f"expected {expected!r} in {git_args}"
 for a in git_args:
 assert not (isinstance(a, str) and a.startswith("--since=")), (
 f"--since=... 不应出现：{a}"
 )
@override_settings(CODEGRAPH_COCHANGE_MIN_SUPPORT=2)
@pytest.mark.django_db(transaction=True)
async def test_min_support_settings_override_two(repo_with_clone) -> None:
 """Phase B3：override min_support=2 时，2 次 co-change 即可建边。"""
 lines = [
 b"COMMIT c1\n", b"a.py\n", b"b.py\n",
 b"COMMIT c2\n", b"a.py\n", b"b.py\n",
 ]
 await _create_chunks_for_file(repo_with_clone, "a.py", 1)
 await _create_chunks_for_file(repo_with_clone, "b.py", 1)
 with patch(
 "asyncio.create_subprocess_exec",
 AsyncMock(return_value=_make_mock_proc(lines)),
 ):
 edges = await CoChangedEdgeBuilder.build(repo_with_clone, )
 assert len(edges) == 1
 assert edges[0].metadata["co_change_count"] == 2
