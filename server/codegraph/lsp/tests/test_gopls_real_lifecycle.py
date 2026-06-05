"""implementation 集成测试：真实 spawn gopls serve lifecycle 验证。

@pytest.mark.integration：CI 默认 pytest -m "not integration" 跳过
@pytest.mark.skipif：本地未装 gopls 时跳过

启用：研发本地 go install golang.org/x/tools/gopls@latest + pytest -m integration

per CONTEXT work item / work item：双重保护（integration marker + skipif binary）。
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_GOPLS_BIN: str | None = shutil.which("gopls")
_FIXTURE_ROOT: Path = (
    Path(__file__).parent / "fixtures" / "gopls_smoke"
).resolve()


@pytest.mark.skipif(
    _GOPLS_BIN is None,
    reason="gopls 未在 PATH（需 go install golang.org/x/tools/gopls@latest）",
)
@pytest.mark.skipif(
    not _FIXTURE_ROOT.exists(),
    reason="gopls_smoke fixture 不存在",
)
class TestGoplsRealLifecycle:
    """真实 gopls serve 启动 / 健康检查 / shutdown 全链路。"""

    def test_go_check_runtime_passes(self) -> None:
        """check_go_runtime 在本地装 gopls 时返 available=True。"""
        from codegraph.lsp.go_check import check_go_runtime

        result = check_go_runtime(force_refresh=True)
        assert result.available is True
        assert result.gopls_version is not None
        assert result.go_version is not None

    def test_gopls_supervisor_starts_and_pings(self, request: pytest.FixtureRequest) -> None:
        """真实 spawn gopls serve + ensure_started 通过（gopls_smoke/ fixture，stdlib only）。

        使用 LspSupervisor 直接实例化（get_or_create_supervisor 读 settings.LSP_SERVERS；
        测试用独立实例绕开全局缓存）。
        """
        import services.background_runner as _bg
        _bg._ensure_worker_loop()  # 内部私有 API；implementation 切换时需关注是否有公开替代

        from codegraph.lsp.gopls_backend import _GoplsLazyBackend
        from codegraph.lsp.supervisor import LspSupervisor, LspSupervisorStatus

        supervisor = LspSupervisor(
            name="gopls-smoke-test",
            command=list(_GoplsLazyBackend.command),
            workspace_root=_FIXTURE_ROOT,
            language_ids=list(_GoplsLazyBackend.language_ids),
            initialization_options=dict(_GoplsLazyBackend.initialization_options),
            max_restart_attempts=1,
        )

        start = time.monotonic()
        try:
            supervisor.call_async_in_loop(supervisor.ensure_started, timeout=60.0)
            elapsed = time.monotonic() - start
            print(f"gopls startup elapsed: {elapsed:.1f}s")
            # advisory：启动 ≤ 90s（per Pitfall P-checkpoint）
            assert elapsed < 90.0, f"启动耗时 {elapsed:.1f}s 超 90s 上限"
            assert supervisor._status == LspSupervisorStatus.READY
        finally:
            request.addfinalizer(
                lambda: supervisor.call_async_in_loop(supervisor.stop, timeout=5.0)
            )

    def test_gopls_supervisor_shutdown_cleans_up(self, request: pytest.FixtureRequest) -> None:
        """shutdown 后 status == STOPPED。"""
        import services.background_runner as _bg
        _bg._ensure_worker_loop()  # 内部私有 API；implementation 切换时需关注是否有公开替代

        from codegraph.lsp.gopls_backend import _GoplsLazyBackend
        from codegraph.lsp.supervisor import LspSupervisor, LspSupervisorStatus

        supervisor = LspSupervisor(
            name="gopls-smoke-shutdown-test",
            command=list(_GoplsLazyBackend.command),
            workspace_root=_FIXTURE_ROOT,
            language_ids=list(_GoplsLazyBackend.language_ids),
            initialization_options=dict(_GoplsLazyBackend.initialization_options),
            max_restart_attempts=1,
        )
        supervisor.call_async_in_loop(supervisor.ensure_started, timeout=60.0)
        supervisor.call_async_in_loop(supervisor.stop, timeout=10.0)
        assert supervisor._status == LspSupervisorStatus.STOPPED
