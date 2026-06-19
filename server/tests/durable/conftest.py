"""durable 测试目录共享 fixture（本 plan 仅 SQLite / fallback 用）。

顶层 ``tests/conftest.py`` 的 autouse ``_reset_background_runner`` 已负责每测试后
等 in-flight 任务落地并重建 worker 线程；这里只补 durable 专用项：清空
``durable.backends`` 的进程内 job 状态注册表，避免跨测试泄漏。

Postgres 专用 fixture（socket 放行 / procrastinate app）留 Plan 60-03 叠加，
本 plan 不放。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from durable.service import DurableTaskService


@pytest.fixture(autouse=True)
def _reset_durable_inprocess_jobs() -> Iterator[None]:
    """每测试后清空 in-process 后端的 job 状态注册表。"""
    yield
    from durable import backends

    backends._reset_for_tests()


@pytest.fixture
def durable_service() -> type[DurableTaskService]:
    """返回 DurableTaskService（静态方法门面，无需实例化）。"""
    return DurableTaskService
