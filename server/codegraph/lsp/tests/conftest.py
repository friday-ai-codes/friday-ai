"""initial implementation: LSP 集成测试 fixtures（per work item / work item / Pitfall P6 / P7 / P10）。

提供 3 个 fixture + wait_until helper：

- ``lsp_settings``：monkeypatch settings 加速健康检查 / 超时 + 注入 echo stub
  配置；teardown 显式 shutdown_all_supervisors（防 zombie，per Pitfall P7）
- ``echo_server_command``：返回 ``[sys.executable, str(echo_server.py)]``
- ``lsp_supervisor_factory``：构造 supervisor + 自动 cleanup
- ``wait_until``：模块级 helper（避免裸 sleep，per Pitfall P6）
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from codegraph.lsp import shutdown_all_supervisors
from codegraph.lsp.supervisor import LspSupervisor

ECHO_SERVER_PATH: Path = Path(__file__).parent / "echo_server.py"


async def wait_until(
    predicate: Callable[[], bool] | Callable[[], Awaitable[bool]],
    *,
    timeout: float = 5.0,
    interval: float = 0.05,
) -> bool:
    """轮询 predicate 直到为真 / 超时（避免裸 sleep race）。

    Args:
        predicate: sync 或 async callable，返 bool。
        timeout: 总等待秒数。
        interval: 轮询间隔。

    Returns:
        True 表示 predicate 在 timeout 前为真；False 表示超时。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if asyncio.iscoroutine(result):
            result = await result
        if result:
            return True
        await asyncio.sleep(interval)
    final = predicate()
    if asyncio.iscoroutine(final):
        final = await final
    return bool(final)


@pytest.fixture
def lsp_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[None]:
    """加速 LSP 健康检查 / 超时 + 注入 echo stub 配置；teardown shutdown_all。"""
    from django.conf import settings as dj_settings

    monkeypatch.setattr(
        dj_settings, "LSP_HEALTH_CHECK_INTERVAL_SECONDS", 0.05, raising=False
    )
    monkeypatch.setattr(
        dj_settings, "LSP_HEALTH_CHECK_TIMEOUT_SECONDS", 1.0, raising=False
    )
    monkeypatch.setattr(
        dj_settings, "LSP_REQUEST_TIMEOUT_SECONDS", 2.0, raising=False
    )
    monkeypatch.setattr(
        dj_settings, "LSP_STARTUP_TIMEOUT_SECONDS", 5.0, raising=False
    )
    monkeypatch.setattr(
        dj_settings, "LSP_MAX_RESTART_ATTEMPTS", 3, raising=False
    )
    monkeypatch.setattr(
        dj_settings,
        "LSP_SERVERS",
        {
            "echo": {
                "command": [sys.executable, str(ECHO_SERVER_PATH)],
                "language_ids": ["plaintext"],
                "workspace_root": str(tmp_path),
            },
        },
        raising=False,
    )

    # 清空 _SUPERVISORS 缓存，避免跨 test 污染
    import codegraph.lsp as lsp_pkg

    monkeypatch.setattr(lsp_pkg, "_SUPERVISORS", {})

    yield

    # teardown：显式 shutdown_all（per Pitfall P7 防 zombie）
    try:
        shutdown_all_supervisors(timeout=2.0)
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture
def echo_server_command() -> list[str]:
    """返回启动 echo server 的 subprocess 命令。"""
    return [sys.executable, str(ECHO_SERVER_PATH)]


@pytest.fixture
def lsp_supervisor_factory(
    lsp_settings: None, tmp_path: Path
) -> Iterator[Callable[..., LspSupervisor]]:
    """构造 LspSupervisor 实例 + 自动 cleanup（per Pitfall P7）。

    用法::

        sup = lsp_supervisor_factory(name="echo")            # 默认 echo
        sup2 = lsp_supervisor_factory(
            name="echo",
            command=[sys.executable, "-c", "import sys; sys.exit(99)"],
        )                                                     # 覆盖命令
    """
    supervisors: list[LspSupervisor] = []

    def _factory(
        name: str = "echo",
        command: list[str] | None = None,
        language_ids: list[str] | None = None,
        max_restart_attempts: int = 3,
        initialization_options: dict[str, Any] | None = None,
        workspace_root: Path | None = None,
    ) -> LspSupervisor:
        sup = LspSupervisor(
            name=name,
            command=command if command is not None else [sys.executable, str(ECHO_SERVER_PATH)],
            workspace_root=workspace_root if workspace_root is not None else tmp_path,
            language_ids=language_ids if language_ids is not None else ["plaintext"],
            initialization_options=initialization_options,
            max_restart_attempts=max_restart_attempts,
        )
        supervisors.append(sup)
        return sup

    yield _factory

    # teardown：吞所有异常，确保 zombie 进程被清理
    for sup in supervisors:
        try:
            sup.call_async_in_loop(sup.stop, timeout=2.0)
        except Exception:  # noqa: BLE001
            pass


__all__ = ["wait_until", "ECHO_SERVER_PATH"]
