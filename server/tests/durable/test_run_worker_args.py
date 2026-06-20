"""DEPLOY-01：run_worker ``--graceful-timeout`` 透传 ``shutdown_graceful_timeout`` 守护。

纯 mock 单测（不连真实 Postgres）：把 ``procrastinate.contrib.django.app`` 换成假对象
（含 ``connector.get_worker_connector`` 与同步 ``replace_connector`` 上下文管理器 + AsyncMock
``run_worker_async``），并把 ``use_procrastinate_backend`` 假成 True，断言 ``--graceful-timeout``
的值原样透传到 ``run_worker_async(shutdown_graceful_timeout=...)``、不传时为 ``None``，且
``listen_notify`` 始终显式 False（锁定决策）。优雅 drain 由 Procrastinate 内置
``install_signal_handlers`` 提供，本测仅守护 arg 透传，不验证真实信号/drain（见 63-VALIDATION
Manual-Only，标 human_needed）。
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from unittest import mock

import pytest
from django.core.management import call_command


def _make_fake_app() -> tuple[mock.MagicMock, mock.AsyncMock]:
    """构造假的 procrastinate app：connector + 同步 replace_connector(CM) + AsyncMock run_worker_async。"""
    run_worker_async = mock.AsyncMock(return_value=None)

    worker_app = mock.MagicMock()
    worker_app.run_worker_async = run_worker_async

    @contextlib.contextmanager
    def _replace_connector(_connector: object) -> Iterator[mock.MagicMock]:
        # replace_connector 是同步 contextmanager（仅 __enter__/__exit__）——镜像真实实现，
        # 防止误用 async with 的回归（CR-02）。
        yield worker_app

    fake_app = mock.MagicMock()
    fake_app.connector.get_worker_connector.return_value = mock.MagicMock()
    fake_app.replace_connector.side_effect = _replace_connector

    return fake_app, run_worker_async


@pytest.fixture
def fake_run_worker_async() -> Iterator[mock.AsyncMock]:
    """patch procrastinate app + use_procrastinate_backend，返回被 await 的 run_worker_async mock。"""
    fake_app, run_worker_async = _make_fake_app()
    with (
        mock.patch("procrastinate.contrib.django.app", fake_app),
        mock.patch("durable.service.use_procrastinate_backend", return_value=True),
    ):
        yield run_worker_async


def test_graceful_timeout_passed_through(fake_run_worker_async: mock.AsyncMock) -> None:
    """--graceful-timeout 110 → run_worker_async(shutdown_graceful_timeout=110.0)。"""
    call_command("run_worker", "--queues", "maintenance", "--graceful-timeout", "110")

    fake_run_worker_async.assert_awaited_once()
    _, kwargs = fake_run_worker_async.call_args
    assert kwargs["shutdown_graceful_timeout"] == 110.0
    # listen_notify 始终显式 False（v1 polling 锁定决策，零回归）。
    assert kwargs["listen_notify"] is False


def test_graceful_timeout_defaults_to_none(fake_run_worker_async: mock.AsyncMock) -> None:
    """不传 --graceful-timeout → run_worker_async(shutdown_graceful_timeout=None)（无限等到完成）。"""
    call_command("run_worker", "--queues", "maintenance")

    fake_run_worker_async.assert_awaited_once()
    _, kwargs = fake_run_worker_async.call_args
    assert kwargs["shutdown_graceful_timeout"] is None
    assert kwargs["listen_notify"] is False
