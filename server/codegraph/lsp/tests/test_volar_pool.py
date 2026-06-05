"""implementation: VolarPool 单元测试（LRU + Vue 2.6- 防御 + 单例 + 并发，≥ 8 测试）。

per implementation plan Task 2 acceptance：
- 池未满 / 命中 move_to_end / 池满 popitem(last=False) 驱逐 + stop
- vue_version="2.6.14" raise LspUnhealthyError 含 "vue<2.7"
- node_check.available=False raise LspUnhealthyError 含 "volar 不可用"
- shutdown_all 串行 stop + 吞异常 + 清池
- get_volar_pool 模块级单例
- threading.Thread × 4 并发 get → _build_supervisor 单次构造
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from codegraph.lsp import volar_pool
from codegraph.lsp.exceptions import LspUnhealthyError
from codegraph.lsp.node_check import NodeCheckResult
from codegraph.lsp.supervisor import LspSupervisor
from codegraph.lsp.volar_pool import VolarPool, get_volar_pool


@pytest.fixture(autouse=True)
def _reset_volar_pool_singleton() -> None:
    """每测试前后重置模块级单例 + node_check 缓存，避免污染。"""
    volar_pool._VOLAR_POOL = None
    from codegraph.lsp import node_check

    node_check._CACHE = None


@pytest.fixture
def mock_node_check_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """mock check_node_runtime 返 available=True，让 pool.get 流程进入 LRU 路径。"""

    def _ok(*, force_refresh: bool = False) -> NodeCheckResult:  # noqa: ARG001
        return NodeCheckResult(
            available=True,
            node_version="v22.10.0",
            vue_language_server_available=True,
            tsdk_path=None,
            reason="ok",
        )

    monkeypatch.setattr(volar_pool, "check_node_runtime", _ok)
    monkeypatch.setattr(volar_pool, "discover_tsdk", lambda: None)


@pytest.fixture
def supervisor_factory(monkeypatch: pytest.MonkeyPatch) -> list[MagicMock]:
    """patch VolarPool._build_supervisor 返 MagicMock(spec=LspSupervisor)。

    返 list 让测试可访问历次构造的 mock 实例。
    """
    created: list[MagicMock] = []

    def _build(self: VolarPool, sub_project_path: Path) -> MagicMock:  # noqa: ARG001
        sup = MagicMock(spec=LspSupervisor)
        sup.name = f"volar:{sub_project_path.name}"
        created.append(sup)
        return sup

    monkeypatch.setattr(VolarPool, "_build_supervisor", _build)
    return created


def test_pool_init_creates_empty_ordered_dict() -> None:
    """VolarPool(max_concurrent=4)._pool 是空 OrderedDict。"""
    pool = VolarPool(max_concurrent=4)
    assert isinstance(pool._pool, OrderedDict)
    assert len(pool._pool) == 0


def test_pool_init_rejects_zero_capacity() -> None:
    """max_concurrent <= 0 应 raise ValueError。"""
    with pytest.raises(ValueError, match="必须 > 0"):
        VolarPool(max_concurrent=0)


def test_get_caches_per_sub_project(
    mock_node_check_available: None, supervisor_factory: list[MagicMock], tmp_path: Path
) -> None:
    """连续两次 get(sub_a, vue=2.7.14) → _build_supervisor 仅调一次 + 第二次走缓存。"""
    pool = VolarPool(max_concurrent=4)
    sub_a = tmp_path / "sub_a"
    sub_a.mkdir()

    first = pool.get(sub_a, vue_version="2.7.14")
    second = pool.get(sub_a, vue_version="2.7.14")
    assert first is second
    assert len(supervisor_factory) == 1


def test_get_move_to_end_on_hit(
    mock_node_check_available: None,
    supervisor_factory: list[MagicMock],  # noqa: ARG001
    tmp_path: Path,
) -> None:
    """命中后 OrderedDict 顺序：访问 sub_a 后顺序变 [sub_b, sub_c, sub_a]。"""
    pool = VolarPool(max_concurrent=4)
    sub_a = tmp_path / "a"
    sub_b = tmp_path / "b"
    sub_c = tmp_path / "c"
    for sub in (sub_a, sub_b, sub_c):
        sub.mkdir()
        pool.get(sub, vue_version="2.7.14")
    pool.get(sub_a, vue_version="2.7.14")  # hit + move_to_end
    keys_in_order = list(pool._pool.keys())
    assert keys_in_order == [sub_b.resolve(), sub_c.resolve(), sub_a.resolve()]


def test_pool_full_evicts_oldest_and_stops_supervisor(
    mock_node_check_available: None,
    supervisor_factory: list[MagicMock],
    tmp_path: Path,
) -> None:
    """max_concurrent=4 池满时第 5 个 get 驱逐 sub_a + 调 sub_a.call_async_in_loop(stop)。"""
    pool = VolarPool(max_concurrent=4)
    subs = []
    for name in "abcd":
        sub = tmp_path / name
        sub.mkdir()
        subs.append(sub)
        pool.get(sub, vue_version="2.7.14")
    sub_e = tmp_path / "e"
    sub_e.mkdir()
    pool.get(sub_e, vue_version="2.7.14")

    evicted_sup = supervisor_factory[0]  # sub_a
    evicted_sup.call_async_in_loop.assert_called_once()
    args, _kwargs = evicted_sup.call_async_in_loop.call_args
    assert args[0] is evicted_sup.stop

    assert subs[0].resolve() not in pool._pool
    assert sub_e.resolve() in pool._pool
    assert len(pool._pool) == 4


def test_get_raises_on_vue_26(
    mock_node_check_available: None,
    supervisor_factory: list[MagicMock],
    tmp_path: Path,
) -> None:
    """vue_version=2.6.14 → raise LspUnhealthyError 含 'vue<2.7'；不构造 supervisor。"""
    pool = VolarPool(max_concurrent=4)
    sub = tmp_path / "vue26"
    sub.mkdir()
    with pytest.raises(LspUnhealthyError, match="vue<2.7"):
        pool.get(sub, vue_version="2.6.14")
    assert len(supervisor_factory) == 0


def test_get_raises_on_none_vue_version(
    mock_node_check_available: None,  # noqa: ARG001
    supervisor_factory: list[MagicMock],
    tmp_path: Path,
) -> None:
    """vue_version=None → 防御性 raise（保守走 tree-sitter）。"""
    pool = VolarPool(max_concurrent=4)
    sub = tmp_path / "no_vue"
    sub.mkdir()
    with pytest.raises(LspUnhealthyError):
        pool.get(sub, vue_version=None)
    assert len(supervisor_factory) == 0


def test_get_raises_on_node_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """check_node_runtime.available=False → raise LspUnhealthyError 含 'volar 不可用'。"""

    def _bad(*, force_refresh: bool = False) -> NodeCheckResult:  # noqa: ARG001
        return NodeCheckResult(
            available=False,
            node_version=None,
            vue_language_server_available=False,
            tsdk_path=None,
            reason="node missing",
        )

    monkeypatch.setattr(volar_pool, "check_node_runtime", _bad)
    pool = VolarPool(max_concurrent=4)
    sub = tmp_path / "x"
    sub.mkdir()
    with pytest.raises(LspUnhealthyError, match="volar 不可用"):
        pool.get(sub, vue_version="2.7.14")


def test_shutdown_all_stops_all_and_clears_pool(
    mock_node_check_available: None,
    supervisor_factory: list[MagicMock],
    tmp_path: Path,
) -> None:
    """shutdown_all 串行调每 supervisor.call_async_in_loop(stop) + 清空 pool。"""
    pool = VolarPool(max_concurrent=4)
    for name in "abc":
        sub = tmp_path / name
        sub.mkdir()
        pool.get(sub, vue_version="2.7.14")
    pool.shutdown_all(timeout=2.0)
    for sup in supervisor_factory:
        sup.call_async_in_loop.assert_called_once()
    assert len(pool._pool) == 0


def test_shutdown_all_swallows_exceptions(
    mock_node_check_available: None,
    supervisor_factory: list[MagicMock],
    tmp_path: Path,
) -> None:
    """supervisor.call_async_in_loop raise → shutdown_all 不抛 + log warning。"""
    pool = VolarPool(max_concurrent=4)
    sub = tmp_path / "boom"
    sub.mkdir()
    pool.get(sub, vue_version="2.7.14")
    supervisor_factory[0].call_async_in_loop.side_effect = RuntimeError("background loop dead")
    pool.shutdown_all(timeout=2.0)
    assert len(pool._pool) == 0


def test_get_volar_pool_is_singleton() -> None:
    """连续两次 get_volar_pool() 返同一实例（id 相等）。"""
    first = get_volar_pool()
    second = get_volar_pool()
    assert first is second


def test_concurrent_get_no_double_build(
    mock_node_check_available: None,
    supervisor_factory: list[MagicMock],
    tmp_path: Path,
) -> None:
    """4 个 thread 同时 get(sub_a) → _build_supervisor 仅调一次（threading.Lock 守门）。"""
    pool = VolarPool(max_concurrent=4)
    sub = tmp_path / "race"
    sub.mkdir()
    barrier = threading.Barrier(4)
    results: list[object] = []
    lock = threading.Lock()

    def _worker() -> None:
        barrier.wait()
        sup = pool.get(sub, vue_version="2.7.14")
        with lock:
            results.append(sup)

    threads = [threading.Thread(target=_worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert len(results) == 4
    assert all(r is results[0] for r in results)
    assert len(supervisor_factory) == 1
