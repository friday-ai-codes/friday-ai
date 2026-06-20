"""run_worker `--graceful-timeout` arg 透传守护（DEPLOY-01）。

纯 mock 单测（不连真实 Postgres）：mock `procrastinate.contrib.django.app`
（含 `connector.get_worker_connector` 与同步 `replace_connector` 上下文管理器）
+ mock `use_procrastinate_backend` 返回 True，断言 `run_worker_async` 被调用时
kwargs 含 `shutdown_graceful_timeout`（传 `--graceful-timeout 110` → 110.0；
不传 → None）且 `listen_notify=False` 保持显式不变。

真实 SIGTERM drain E2E 不在自动化范围（见 63-VALIDATION Manual-Only，human_needed）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.core.management import call_command


def _build_app_mock() -> tuple[MagicMock, AsyncMock]:
    """构造 mock 的 procrastinate app：返回 (app_mock, run_worker_async_mock)。"""
    run_worker_async = AsyncMock()
    worker_app = MagicMock()
    worker_app.run_worker_async = run_worker_async

    # replace_connector 是同步 contextmanager：__enter__ 返回 worker_app。
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=worker_app)
    cm.__exit__ = MagicMock(return_value=False)

    app_mock = MagicMock()
    app_mock.connector.get_worker_connector = MagicMock(return_value=MagicMock())
    app_mock.replace_connector = MagicMock(return_value=cm)
    return app_mock, run_worker_async


@pytest.mark.parametrize(
    ("cli_args", "expected_timeout"),
    [
        (["--graceful-timeout", "110"], 110.0),
        ([], None),
    ],
)
def test_graceful_timeout_passed_to_run_worker_async(cli_args, expected_timeout) -> None:
    """--graceful-timeout 透传为 run_worker_async(shutdown_graceful_timeout=...)。"""
    app_mock, run_worker_async = _build_app_mock()

    with (
        patch("durable.service.use_procrastinate_backend", return_value=True),
        patch("procrastinate.contrib.django.app", app_mock),
    ):
        call_command("run_worker", *cli_args)

    run_worker_async.assert_awaited_once()
    kwargs = run_worker_async.await_args.kwargs
    assert kwargs["shutdown_graceful_timeout"] == expected_timeout
    # listen_notify 必须保持显式 False（锁定决策，零回归）。
    assert kwargs["listen_notify"] is False
