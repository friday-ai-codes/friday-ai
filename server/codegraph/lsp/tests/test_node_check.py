"""implementation: node_check 单元测试（mock subprocess + 9 场景覆盖）。

per implementation plan Task 2 acceptance：
- Node 22 / 18 / 16 三档版本 + 缺 binary + subprocess raise
- vue-language-server 缺失 + 可达
- discover_tsdk 三探针 hit / 全失败
- 缓存命中 + force_refresh
"""

from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from codegraph.lsp import node_check
from codegraph.lsp.node_check import (
    NodeCheckResult,
    check_node_runtime,
    discover_tsdk,
)


@pytest.fixture(autouse=True)
def _reset_node_check_cache() -> None:
    """每测试前重置模块级 _CACHE，避免跨 test 污染。"""
    node_check._CACHE = None


def _mk_completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def test_check_node_runtime_returns_available_on_node_22(monkeypatch: pytest.MonkeyPatch) -> None:
    """node v22 + vue-language-server 可达 → available=True / reason='ok'。"""
    monkeypatch.setattr(
        node_check.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in ("node", "vue-language-server") else None,
    )
    monkeypatch.setattr(
        node_check.subprocess,
        "run",
        mock.Mock(return_value=_mk_completed(stdout="v22.10.0\n")),
    )
    result = check_node_runtime(force_refresh=True)
    assert result.available is True
    assert result.reason == "ok"
    assert result.node_version == "v22.10.0"
    assert result.vue_language_server_available is True


def test_check_node_runtime_accepts_node_18(monkeypatch: pytest.MonkeyPatch) -> None:
    """Node 18 在下界（≥ 18）可接受。"""
    monkeypatch.setattr(
        node_check.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in ("node", "vue-language-server") else None,
    )
    monkeypatch.setattr(
        node_check.subprocess,
        "run",
        mock.Mock(return_value=_mk_completed(stdout="v18.20.0\n")),
    )
    result = check_node_runtime(force_refresh=True)
    assert result.available is True


def test_check_node_runtime_rejects_node_16(monkeypatch: pytest.MonkeyPatch) -> None:
    """Node 16 < v18 → available=False + reason 含 '< v18'。"""
    monkeypatch.setattr(
        node_check.shutil,
        "which",
        lambda name: "/usr/bin/node" if name == "node" else None,
    )
    monkeypatch.setattr(
        node_check.subprocess,
        "run",
        mock.Mock(return_value=_mk_completed(stdout="v16.20.0\n")),
    )
    result = check_node_runtime(force_refresh=True)
    assert result.available is False
    assert "< v18" in result.reason


def test_check_node_runtime_rejects_missing_node_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    """node 不在 PATH → available=False + reason 含 '未在 PATH'。"""
    monkeypatch.setattr(node_check.shutil, "which", lambda name: None)
    result = check_node_runtime(force_refresh=True)
    assert result.available is False
    assert "未在 PATH" in result.reason


def test_check_node_runtime_rejects_node_subprocess_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """subprocess.run raise OSError → available=False + reason 含 '调用失败'。"""
    monkeypatch.setattr(
        node_check.shutil, "which", lambda name: "/usr/bin/node"
    )

    def _raise(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise OSError("boom")

    monkeypatch.setattr(node_check.subprocess, "run", _raise)
    result = check_node_runtime(force_refresh=True)
    assert result.available is False
    assert "调用失败" in result.reason


def test_check_node_runtime_rejects_missing_vue_language_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """node 可达但 vue-language-server 缺失 → available=False + reason 含 'npm i -g'。"""
    monkeypatch.setattr(
        node_check.shutil,
        "which",
        lambda name: "/usr/bin/node" if name == "node" else None,
    )
    monkeypatch.setattr(
        node_check.subprocess,
        "run",
        mock.Mock(return_value=_mk_completed(stdout="v22.10.0\n")),
    )
    result = check_node_runtime(force_refresh=True)
    assert result.available is False
    assert result.vue_language_server_available is False
    assert "npm i -g" in result.reason


def test_check_node_runtime_cache_hit_does_not_reprobe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """连续两次调 check_node_runtime → subprocess.run 只被调一次（缓存命中）。"""
    monkeypatch.setattr(
        node_check.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in ("node", "vue-language-server") else None,
    )
    run_mock = mock.Mock(return_value=_mk_completed(stdout="v22.10.0\n"))
    monkeypatch.setattr(node_check.subprocess, "run", run_mock)

    first = check_node_runtime(force_refresh=True)
    second = check_node_runtime()
    assert first is second
    # 第二次调用走缓存：subprocess.run 总调用次数 = 第一次的次数
    first_call_count = run_mock.call_count
    third = check_node_runtime(force_refresh=True)
    assert third is not None
    assert run_mock.call_count > first_call_count


def test_discover_tsdk_npm_root_global_hits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """mock npm root -g 返目录 + Path.exists True → discover_tsdk 命中第一探针。"""
    fake_root = tmp_path / "lib" / "node_modules"
    target = fake_root / "typescript" / "lib"
    target.mkdir(parents=True)

    monkeypatch.setattr(
        node_check.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name == "npm" else None,
    )
    monkeypatch.setattr(
        node_check.subprocess,
        "run",
        mock.Mock(return_value=_mk_completed(stdout=str(fake_root) + "\n", returncode=0)),
    )
    result = discover_tsdk()
    assert result == target


def test_discover_tsdk_all_probes_fail_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """三探针全失败（npm/tsc 不在 PATH + cwd 无 node_modules）→ 返 None。"""
    monkeypatch.setattr(node_check.shutil, "which", lambda name: None)
    monkeypatch.setattr(node_check.Path, "cwd", classmethod(lambda cls: tmp_path))
    result = discover_tsdk()
    assert result is None


def test_node_check_result_is_frozen_dataclass() -> None:
    """NodeCheckResult frozen=True：实例属性不可改。"""
    r = NodeCheckResult(
        available=True,
        node_version="v22.10.0",
        vue_language_server_available=True,
        tsdk_path=Path("/x"),
        reason="ok",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.available = False  # type: ignore[misc]
