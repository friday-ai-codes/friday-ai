"""进程角色门禁（DURABLE-02）守护测试。

覆盖：
- ``durable.roles.should_run_startup_side_effects`` 真值表 + 短路 info 日志
- 三处 ``AppConfig.ready()`` 在 worker/migrate 角色下短路（不调度对应 daemon 线程），
  web（默认）角色仍执行（零回归）
- handler / backend 注册与 role 无关（任意角色都注册）

纯单元：通过 monkeypatch ``threading.Thread`` 拦截线程构造、mock 注册入口，
不触达 Postgres（无 SocketBlockedError）、不带 ``postgres_queue`` marker。
"""

from __future__ import annotations

import sys
from unittest import mock

import pytest
from django.apps import apps as django_apps

from durable.roles import current_role, should_run_startup_side_effects

# ---------------------------------------------------------------------------
# roles helper：真值表 + 归一化 + 短路日志
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ("web", True),
        (None, True),  # 未设 env → 缺省 web
        ("worker", False),
        ("scheduler", False),
        ("migrate", False),
        ("test", False),
    ],
)
def test_should_run_truth_table(
    monkeypatch: pytest.MonkeyPatch, env: str | None, expected: bool
) -> None:
    if env is None:
        monkeypatch.delenv("FRIDAY_PROCESS_ROLE", raising=False)
    else:
        monkeypatch.setenv("FRIDAY_PROCESS_ROLE", env)
    assert should_run_startup_side_effects(job="probe") is expected


def test_current_role_normalizes_case_and_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRIDAY_PROCESS_ROLE", "  WORKER  ")
    assert current_role() == "worker"


def test_skip_logs_info_with_role_and_job(monkeypatch: pytest.MonkeyPatch) -> None:
    """worker 短路时记一条 info 日志（含 role + job 名），不静默。"""
    monkeypatch.setenv("FRIDAY_PROCESS_ROLE", "worker")
    with mock.patch("durable.roles.logger") as mock_logger:
        result = should_run_startup_side_effects(job="reset_stuck_indexing")
    assert result is False
    mock_logger.info.assert_called_once_with(
        "startup_side_effect_skipped_by_role",
        role="worker",
        job="reset_stuck_indexing",
    )


def test_allowed_runs_without_log(monkeypatch: pytest.MonkeyPatch) -> None:
    """web（allowed）执行时不应记短路日志。"""
    monkeypatch.setenv("FRIDAY_PROCESS_ROLE", "web")
    with mock.patch("durable.roles.logger") as mock_logger:
        assert should_run_startup_side_effects(job="reset_stuck_indexing") is True
    mock_logger.info.assert_not_called()


# ---------------------------------------------------------------------------
# repositories：RepositoriesConfig.ready() role 门禁
# ---------------------------------------------------------------------------


def test_repositories_web_starts_reset_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRIDAY_PROCESS_ROLE", raising=False)  # 默认 web
    cfg = django_apps.get_app_config("repositories")
    with mock.patch("threading.Thread") as mock_thread:
        cfg.ready()
    assert mock_thread.called


def test_repositories_worker_skips_reset_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRIDAY_PROCESS_ROLE", "worker")
    cfg = django_apps.get_app_config("repositories")
    with mock.patch("threading.Thread") as mock_thread:
        cfg.ready()
    assert not mock_thread.called


def test_repositories_migrate_skips_reset_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRIDAY_PROCESS_ROLE", "migrate")
    cfg = django_apps.get_app_config("repositories")
    with mock.patch("threading.Thread") as mock_thread:
        cfg.ready()
    assert not mock_thread.called


# ---------------------------------------------------------------------------
# resumable：ResumableConfig.ready() role 门禁（handler 注册与 role 无关）
# ---------------------------------------------------------------------------


def test_resumable_worker_skips_recovery_keeps_handlers(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    settings.RESUMABLE_RECOVERY_ON_STARTUP = True
    monkeypatch.setenv("FRIDAY_PROCESS_ROLE", "worker")
    cfg = django_apps.get_app_config("resumable")
    with (
        mock.patch("resumable.handlers.register_default_handlers") as mock_register,
        mock.patch("threading.Thread") as mock_thread,
    ):
        cfg.ready()
    assert mock_register.called  # handler 注册与 role 无关
    assert not mock_thread.called  # worker 不调度补扫线程


def test_resumable_web_schedules_recovery_thread(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    settings.RESUMABLE_RECOVERY_ON_STARTUP = True
    monkeypatch.delenv("FRIDAY_PROCESS_ROLE", raising=False)  # 默认 web
    # 绕过既有 argv 兜底嗅探（pytest argv0 含 "pytest" 会短路），驱动 web 执行分支。
    monkeypatch.setattr(sys, "argv", ["uvicorn"])
    cfg = django_apps.get_app_config("resumable")
    with (
        mock.patch("resumable.handlers.register_default_handlers") as mock_register,
        mock.patch("threading.Thread") as mock_thread,
    ):
        cfg.ready()
    assert mock_register.called
    assert mock_thread.called


# ---------------------------------------------------------------------------
# codegraph：galaxy warm + orphan reconcile role 门禁（backend 注册与 role 无关）
# ---------------------------------------------------------------------------


def _force_codegraph_startup_settings(settings) -> None:
    settings.VOLAR_BACKEND_ENABLED = True
    settings.GOPLS_BACKEND_ENABLED = False
    settings.GALAXY_CACHE_ENABLED = True
    settings.GALAXY_CACHE_WARM_ON_STARTUP = True
    settings.GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP = True


def test_codegraph_worker_skips_threads_keeps_backend(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    _force_codegraph_startup_settings(settings)
    monkeypatch.setenv("FRIDAY_PROCESS_ROLE", "worker")
    cfg = django_apps.get_app_config("codegraph")
    with (
        mock.patch.object(type(cfg), "_register_volar_backends") as mock_volar,
        mock.patch("threading.Thread") as mock_thread,
    ):
        cfg.ready()
    assert mock_volar.called  # backend 注册与 role 无关
    assert not mock_thread.called  # galaxy warm + orphan reconcile 均不调度


def test_codegraph_web_schedules_two_threads(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    _force_codegraph_startup_settings(settings)
    monkeypatch.delenv("FRIDAY_PROCESS_ROLE", raising=False)  # 默认 web
    monkeypatch.setattr(sys, "argv", ["uvicorn"])  # 绕过 argv 兜底嗅探
    cfg = django_apps.get_app_config("codegraph")
    with (
        mock.patch.object(type(cfg), "_register_volar_backends") as mock_volar,
        mock.patch("threading.Thread") as mock_thread,
    ):
        cfg.ready()
    assert mock_volar.called
    # galaxy warm + orphan reconcile 两处各起一个 daemon 线程。
    assert mock_thread.call_count == 2
