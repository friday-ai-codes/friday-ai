"""Phase 集成测试：真实 spawn vue-language-server lifecycle 验证。
@pytest.mark.integration：CI 默认 ``pytest -m "not integration"`` 跳过
@pytest.mark.skipif：本地未装 vue-language-server / 无 fixture 时跳过
启用：
 研发本地 ``npm i -g @vue/language-server typescript`` 后跑
 ``cd server && pytest -m integration codegraph/lsp/tests/test_volar_real_lifecycle.py``
"""
from __future__ import annotations
import shutil
import time
from pathlib import Path
import pytest
pytestmark = pytest.mark.integration
_VLS_BIN: str | None = shutil.which("vue-language-server")
_FIXTURE_ROOT: Path = (
 Path(__file__).parent / "fixtures" / "volar_smoke"
).resolve
@pytest.mark.skipif(_VLS_BIN is None, reason="vue-language-server 未在 PATH（需 npm i -g @vue/language-server）")
@pytest.mark.skipif(not _FIXTURE_ROOT.exists, reason="volar_smoke fixture 不存在")
class TestVolarRealLifecycle:
 """真实 vue-language-server 启动 / 健康检查 / shutdown 全链路。"""
 def test_node_check_runtime_passes(self) -> None:
 """check_node_runtime 在装 vue-language-server 时返 available=True。"""
 from codegraph.lsp.node_check import check_node_runtime
 result = check_node_runtime(force_refresh=True)
 assert result.available is True
 assert result.node_version is not None
 assert result.vue_language_server_available is True
 def test_volar_supervisor_starts_and_pings(self) -> None:
 """真实 spawn vue-language-server + workspace_symbol("") ping 通过。"""
 from codegraph.lsp.supervisor import LspSupervisorStatus
 from codegraph.lsp.volar_pool import get_volar_pool
 pool = get_volar_pool
 try:
 supervisor = pool.get(_FIXTURE_ROOT, vue_version="2.7.14")
 start = time.monotonic
 supervisor.call_async_in_loop(supervisor.ensure_started, timeout=90.0)
 elapsed = time.monotonic - start
 print(f"volar startup elapsed: {elapsed:.1f}s")
 assert elapsed < 90.0, f"启动耗时 {elapsed:.1f}s 超 90s 上限"
 assert supervisor._status == LspSupervisorStatus.READY
 finally:
 pool.shutdown_all(timeout=10.0)
 def test_volar_pool_shutdown_all_cleans_up(self) -> None:
 """shutdown_all 后 pool 清空 + supervisor stop 调用。"""
 from codegraph.lsp.volar_pool import get_volar_pool
 pool = get_volar_pool
 pool.get(_FIXTURE_ROOT, vue_version="2.7.14")
 assert len(pool._pool) >= 1
 pool.shutdown_all(timeout=10.0)
 assert len(pool._pool) == 0
