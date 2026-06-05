"""implementation: go_check.py 单元测试（≥ 9 场景 mock subprocess）。

per Pitfall P-checkpoint：每测试前后重置 _CACHE 避免测试间污染。
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, call

import pytest


@pytest.fixture(autouse=False)
def reset_go_check_cache():
    """每测试前重置 go_check._CACHE 避免污染。"""
    import codegraph.lsp.go_check as _mod
    _mod._CACHE = None
    yield
    _mod._CACHE = None


def _make_proc(stdout: str = "", stderr: str = "", returncode: int = 0) -> MagicMock:
    """创建 subprocess.run mock 返回值。"""
    proc = MagicMock()
    proc.stdout = stdout
    proc.stderr = stderr
    proc.returncode = returncode
    return proc


class TestCheckGoRuntimeAvailable:
    def test_check_go_runtime_returns_available_on_v15_go122(
        self, reset_go_check_cache, monkeypatch
    ):
        """gopls v0.15.3 + go 1.22 → available=True + reason='ok'。"""
        from codegraph.lsp.go_check import check_go_runtime

        monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
        gopls_proc = _make_proc(stdout="golang.org/x/tools/gopls v0.15.3 linux/amd64")
        go_proc = _make_proc(stdout="go version go1.22.3 linux/amd64")
        mock_run = MagicMock(side_effect=[gopls_proc, go_proc])
        monkeypatch.setattr("subprocess.run", mock_run)

        result = check_go_runtime()
        assert result.available is True
        assert result.reason == "ok"
        assert result.gopls_version is not None
        assert "0.15" in result.gopls_version or "15" in result.gopls_version
        assert result.go_version is not None
        assert "1.22" in result.go_version or "22" in result.go_version

    def test_check_go_runtime_accepts_gopls_v14(
        self, reset_go_check_cache, monkeypatch
    ):
        """gopls v0.14.0 接受（边界版本）。"""
        from codegraph.lsp.go_check import check_go_runtime

        monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
        gopls_proc = _make_proc(stdout="golang.org/x/tools/gopls v0.14.0 linux/amd64")
        go_proc = _make_proc(stdout="go version go1.21.0 linux/amd64")
        mock_run = MagicMock(side_effect=[gopls_proc, go_proc])
        monkeypatch.setattr("subprocess.run", mock_run)

        result = check_go_runtime()
        assert result.available is True


class TestCheckGoRuntimeRejected:
    def test_check_go_runtime_rejects_gopls_v13(
        self, reset_go_check_cache, monkeypatch
    ):
        """gopls v0.13.0 → available=False + reason 含 '< v0.14'。"""
        from codegraph.lsp.go_check import check_go_runtime

        monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
        gopls_proc = _make_proc(stdout="golang.org/x/tools/gopls v0.13.0 linux/amd64")
        mock_run = MagicMock(return_value=gopls_proc)
        monkeypatch.setattr("subprocess.run", mock_run)

        result = check_go_runtime()
        assert result.available is False
        assert "< v0.14" in result.reason

    def test_check_go_runtime_rejects_missing_gopls(
        self, reset_go_check_cache, monkeypatch
    ):
        """shutil.which('gopls') 返 None → available=False + reason 含 '未在 PATH'。"""
        from codegraph.lsp.go_check import check_go_runtime

        def mock_which(name: str) -> str | None:
            if name == "gopls":
                return None
            return f"/usr/bin/{name}"

        monkeypatch.setattr("shutil.which", mock_which)
        result = check_go_runtime()
        assert result.available is False
        assert "未在 PATH" in result.reason
        assert result.gopls_version is None

    def test_check_go_runtime_rejects_missing_go(
        self, reset_go_check_cache, monkeypatch
    ):
        """gopls ok 但 shutil.which('go') 返 None → available=False + reason 含 '未在 PATH'。"""
        from codegraph.lsp.go_check import check_go_runtime

        def mock_which(name: str) -> str | None:
            if name == "go":
                return None
            return f"/usr/bin/{name}"

        monkeypatch.setattr("shutil.which", mock_which)
        gopls_proc = _make_proc(stdout="golang.org/x/tools/gopls v0.15.3 linux/amd64")
        mock_run = MagicMock(return_value=gopls_proc)
        monkeypatch.setattr("subprocess.run", mock_run)

        result = check_go_runtime()
        assert result.available is False
        assert "未在 PATH" in result.reason
        assert result.go_version is None

    def test_check_go_runtime_rejects_go_118(
        self, reset_go_check_cache, monkeypatch
    ):
        """go 1.18 < 1.20 → available=False + reason 含 '< 1.20'。"""
        from codegraph.lsp.go_check import check_go_runtime

        monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
        gopls_proc = _make_proc(stdout="golang.org/x/tools/gopls v0.15.3 linux/amd64")
        go_proc = _make_proc(stdout="go version go1.18.10 linux/amd64")
        mock_run = MagicMock(side_effect=[gopls_proc, go_proc])
        monkeypatch.setattr("subprocess.run", mock_run)

        result = check_go_runtime()
        assert result.available is False
        assert "< 1.20" in result.reason

    def test_check_go_runtime_rejects_subprocess_timeout(
        self, reset_go_check_cache, monkeypatch
    ):
        """subprocess.run raise TimeoutExpired → available=False + reason 含 '调用失败'。"""
        from codegraph.lsp.go_check import check_go_runtime

        monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(
            "subprocess.run",
            MagicMock(side_effect=subprocess.TimeoutExpired("gopls", 10.0)),
        )

        result = check_go_runtime()
        assert result.available is False
        assert "调用失败" in result.reason


class TestCheckGoRuntimeCaching:
    def test_check_go_runtime_cache_hit_does_not_reprobe(
        self, reset_go_check_cache, monkeypatch
    ):
        """连续两次调用：第 2 次走缓存不重调 subprocess（call_count == 2）。"""
        from codegraph.lsp.go_check import check_go_runtime

        monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
        gopls_proc = _make_proc(stdout="golang.org/x/tools/gopls v0.15.3 linux/amd64")
        go_proc = _make_proc(stdout="go version go1.22.3 linux/amd64")
        mock_run = MagicMock(side_effect=[gopls_proc, go_proc])
        monkeypatch.setattr("subprocess.run", mock_run)

        check_go_runtime()
        check_go_runtime()  # 第 2 次走缓存
        assert mock_run.call_count == 2  # gopls + go 各一次；第 2 次无 subprocess

    def test_check_go_runtime_force_refresh_bypasses_cache(
        self, reset_go_check_cache, monkeypatch
    ):
        """force_refresh=True 绕过缓存，再次调 subprocess（call_count == 4）。"""
        from codegraph.lsp.go_check import check_go_runtime

        monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
        gopls_proc1 = _make_proc(stdout="golang.org/x/tools/gopls v0.15.3 linux/amd64")
        go_proc1 = _make_proc(stdout="go version go1.22.3 linux/amd64")
        gopls_proc2 = _make_proc(stdout="golang.org/x/tools/gopls v0.15.3 linux/amd64")
        go_proc2 = _make_proc(stdout="go version go1.22.3 linux/amd64")
        mock_run = MagicMock(
            side_effect=[gopls_proc1, go_proc1, gopls_proc2, go_proc2]
        )
        monkeypatch.setattr("subprocess.run", mock_run)

        check_go_runtime()  # 首次探针（2 次 subprocess）
        check_go_runtime(force_refresh=True)  # 强制刷新（再 2 次 subprocess）
        assert mock_run.call_count == 4
