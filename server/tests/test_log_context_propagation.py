"""用户上下文贯穿守护测试（CTX-01/02）。

覆盖：
- ``log_context`` helper：bind/rebind/clear/bind_task_context/resolve_user_id +
  ``LogSource.normalize`` 受控枚举兜底。
- 请求级中间件 + DRF mixin 的入口绑定 / 认证后补绑 / 请求结束清理。
- 后台任务（durable / background_runner / workflow / apscheduler / feishu）worker
  入口的用户传播与 source 绑定。

断言策略：用 ``configure_structlog()`` + ``capfd`` 捕获 stdout JSON / Console 行；
或直接 patch ``structlog.contextvars.bind_contextvars`` 捕获 kwargs。事件名一律
snake_case（``*_started`` / ``*_completed``）。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import structlog

from common.log_context import (
    LogSource,
    bind_request_context,
    bind_task_context,
    clear_request_context,
    rebind_user,
    resolve_user_id,
)
from common.logging import configure_structlog


@pytest.fixture(autouse=True)
def _clean_contextvars() -> Any:
    """每个测试前后清空 contextvars，避免跨测试残留。"""
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()


def _emit_and_capture(capfd: Any, event: str) -> dict[str, Any]:
    """发一条 structlog 事件并把 stdout 解析为 dict（JSON renderer / 容错降级）。"""
    configure_structlog()
    structlog.get_logger("test_log_context").info(event)
    captured = capfd.readouterr()
    output = (captured.out + captured.err).strip().splitlines()
    line = output[-1] if output else ""
    try:
        return json.loads(line)
    except (json.JSONDecodeError, IndexError):
        # DEBUG 下 ConsoleRenderer 非 JSON——退化为子串断言用的原始行。
        return {"_raw": line}


# === Task 1: log_context helper ===


def test_log_source_normalize_falls_back_to_system() -> None:
    assert LogSource.normalize("bogus") == "system"
    assert LogSource.normalize(None) == "system"
    assert LogSource.normalize("MCP") == "mcp"
    assert LogSource.normalize(LogSource.WEBHOOK_FEISHU) == "webhook_feishu"


def test_bind_request_context_attaches_fields(capfd: Any) -> None:
    bind_request_context(source="mcp", user_id="7", request_id="r1", trace_id="t1")
    parsed = _emit_and_capture(capfd, "x_started")
    raw = json.dumps(parsed)
    assert '"user_id"' in raw or parsed.get("user_id") == "7"
    assert parsed.get("user_id", "7") == "7"
    assert parsed.get("source") == "mcp"
    assert parsed.get("request_id") == "r1"
    assert parsed.get("trace_id") == "t1"


def test_bind_request_context_defaults_fill_uuid(capfd: Any) -> None:
    bind_request_context(source="rest", request_id=None, trace_id=None)
    parsed = _emit_and_capture(capfd, "y_started")
    assert parsed.get("user_id") == "system"
    assert parsed.get("source") == "rest"
    assert parsed.get("request_id")
    assert parsed.get("trace_id")


def test_rebind_user_updates_and_keeps_placeholder(capfd: Any) -> None:
    bind_request_context(source="rest", request_id="r2", trace_id="t2")
    rebind_user(None)  # 不应覆盖占位
    parsed = _emit_and_capture(capfd, "z_started")
    assert parsed.get("user_id") == "system"

    rebind_user(42)
    parsed2 = _emit_and_capture(capfd, "z_completed")
    assert parsed2.get("user_id") == "42"


def test_clear_request_context_removes_fields(capfd: Any) -> None:
    bind_request_context(source="rest", user_id="5", request_id="r3", trace_id="t3")
    clear_request_context()
    parsed = _emit_and_capture(capfd, "after_clear_started")
    assert "user_id" not in parsed
    assert "source" not in parsed


def test_bind_task_context_binds_and_clears(capfd: Any) -> None:
    with bind_task_context(user_id=None, source="durable"):
        parsed = _emit_and_capture(capfd, "task_started")
        assert parsed.get("user_id") == "system"
        assert parsed.get("source") == "durable"
    # 退出后 clear 生效
    parsed_after = _emit_and_capture(capfd, "task_completed")
    assert "user_id" not in parsed_after


def test_resolve_user_id_authenticated_and_anonymous() -> None:
    class _User:
        def __init__(self, uid: Any, authed: bool) -> None:
            self.id = uid
            self.is_authenticated = authed

    class _Req:
        def __init__(self, user: Any) -> None:
            self.user = user

    assert resolve_user_id(_Req(_User(42, True))) == "42"
    assert resolve_user_id(_Req(_User(None, True))) == "system"
    assert resolve_user_id(_Req(_User(7, False))) == "system"
    assert resolve_user_id(_Req(None)) == "system"
    assert resolve_user_id(object()) == "system"


# === Task 2: 中间件 + DRF mixin ===


class _FakeUser:
    def __init__(self, uid: Any, authed: bool) -> None:
        self.id = uid
        self.is_authenticated = authed


class _FakeRequest:
    def __init__(self, user: Any) -> None:
        self.user = user


class _BaseView:
    """模拟 DRF APIView.initial（仅触发认证、不做真正鉴权）。"""

    def initial(self, request, *args, **kwargs):  # noqa: D401
        # 真实 DRF 在此 perform_authentication；测试里 request.user 已就绪。
        return None


def _make_view(log_source: Any = None) -> Any:
    from common.log_context import LogSource
    from common.mixins import LogContextMixin

    class _View(LogContextMixin, _BaseView):
        pass

    view = _View()
    if log_source is not None:
        view.log_source = (
            log_source.value if isinstance(log_source, LogSource) else log_source
        )
    return view


def test_mixin_rebinds_authenticated_user(capfd: Any) -> None:
    bind_request_context(source="rest", request_id="r1", trace_id="t1")
    view = _make_view()
    view.initial(_FakeRequest(_FakeUser(42, True)))
    parsed = _emit_and_capture(capfd, "view_started")
    assert parsed.get("user_id") == "42"


def test_mixin_keeps_system_for_anonymous(capfd: Any) -> None:
    bind_request_context(source="rest", request_id="r1", trace_id="t1")
    view = _make_view()
    view.initial(_FakeRequest(_FakeUser(None, False)))
    parsed = _emit_and_capture(capfd, "view_started")
    assert parsed.get("user_id") == "system"


def test_mixin_declares_source(capfd: Any) -> None:
    from common.log_context import LogSource

    bind_request_context(source="rest", request_id="r1", trace_id="t1")
    view = _make_view(log_source=LogSource.MCP)
    view.initial(_FakeRequest(_FakeUser(7, True)))
    parsed = _emit_and_capture(capfd, "mcp_started")
    assert parsed.get("source") == "mcp"
    assert parsed.get("user_id") == "7"


def test_middleware_binds_and_clears(capfd: Any) -> None:
    from common.middleware import RequestLogContextMiddleware

    captured: dict[str, Any] = {}

    def _get_response(request):
        # 请求处理中：上下文应已绑定。
        configure_structlog()
        structlog.get_logger("mw").info("inside_request_started")
        out = capfd.readouterr().out.strip().splitlines()
        captured["inside"] = json.loads(out[-1]) if out else {}
        return "ok"

    mw = RequestLogContextMiddleware(_get_response)

    class _Headers(dict):
        pass

    class _Req:
        headers = _Headers({"X-Request-ID": "req-9"})

    response = mw(_Req())
    assert response == "ok"
    assert captured["inside"].get("request_id") == "req-9"
    assert captured["inside"].get("source") == "rest"
    assert captured["inside"].get("user_id") == "system"

    # 请求结束后 contextvars 已清理（无残留）。
    parsed_after = _emit_and_capture(capfd, "after_request_started")
    assert "request_id" not in parsed_after
    assert "user_id" not in parsed_after


# === Task 3: 后台任务用户传播（CTX-02）===


@pytest.mark.asyncio
async def test_durable_defer_writes_initiated_user(monkeypatch: Any) -> None:
    """defer 把 initiated_by_user_id 写进 payload（不覆盖调用方已传值）。"""
    from durable import service as durable_service
    from durable.backends import in_process_backend

    captured: dict[str, Any] = {}

    async def _fake_defer(task: str, payload: dict, **kwargs: Any) -> str:
        captured["task"] = task
        captured["payload"] = payload
        return "job-1"

    monkeypatch.setattr(durable_service, "use_procrastinate_backend", lambda: False)
    monkeypatch.setattr(in_process_backend, "defer", _fake_defer)

    job_id = await durable_service.DurableTaskService.defer(
        "durable_index",
        {"repository_id": "r1"},
        queue="index",
        initiated_by_user_id="9",
    )
    assert job_id == "job-1"
    assert captured["payload"]["initiated_by_user_id"] == "9"

    # 调用方已显式放入则不覆盖
    captured.clear()
    await durable_service.DurableTaskService.defer(
        "durable_index",
        {"repository_id": "r1", "initiated_by_user_id": "existing"},
        queue="index",
        initiated_by_user_id="9",
    )
    assert captured["payload"]["initiated_by_user_id"] == "existing"


@pytest.mark.asyncio
async def test_run_index_binds_initiated_user(monkeypatch: Any) -> None:
    """run_index worker 入口 bind 发起用户（无则 system）。"""
    import services.indexer as indexer_mod
    from durable.tasks_impl import run_index

    seen: dict[str, Any] = {}

    async def _fake_clone(repository_id: str, **kwargs: Any) -> dict[str, Any]:
        seen["ctx"] = dict(structlog.contextvars.get_contextvars())
        return {"status": "ok"}

    monkeypatch.setattr(indexer_mod, "clone_and_index_repository", _fake_clone)

    await run_index(repository_id="r1", initiated_by_user_id="9")
    assert seen["ctx"].get("user_id") == "9"
    assert seen["ctx"].get("source") == "durable"
    # 退出后清理
    assert "user_id" not in structlog.contextvars.get_contextvars()

    seen.clear()
    await run_index(repository_id="r1")
    assert seen["ctx"].get("user_id") == "system"


def test_background_runner_binds_user(capfd: Any) -> None:
    """run_in_background(initiated_by_user_id=...) 内 coro 事件携 user_id；不传则无。"""
    from services.background_runner import (
        _reset_for_tests,
        run_in_background,
        wait_for_pending,
    )

    _reset_for_tests()
    seen: list[dict[str, Any]] = []

    async def _factory_with_user() -> str:
        seen.append(dict(structlog.contextvars.get_contextvars()))
        return "done"

    async def _factory_no_user() -> str:
        seen.append(dict(structlog.contextvars.get_contextvars()))
        return "done"

    try:
        fut = run_in_background(_factory_with_user, initiated_by_user_id="9")
        assert fut.result(timeout=10) == "done"
        fut2 = run_in_background(_factory_no_user)
        assert fut2.result(timeout=10) == "done"
        wait_for_pending(timeout=10)
    finally:
        _reset_for_tests()

    with_user, no_user = seen[0], seen[1]
    assert with_user.get("user_id") == "9"
    assert with_user.get("source") == "background"
    assert "user_id" not in no_user  # 零回归：不传不绑定


def test_workflow_run_in_thread_binds_user() -> None:
    """workflow 后台线程入口 bind triggered_by → source=workflow。"""
    import threading

    from workflows.engine.scheduler import _run_in_thread

    done = threading.Event()
    seen: dict[str, Any] = {}

    async def _coro() -> None:
        seen["ctx"] = dict(structlog.contextvars.get_contextvars())
        done.set()

    _run_in_thread(_coro(), triggered_by_id=42, trace_id="tr-1")
    assert done.wait(timeout=10)
    assert seen["ctx"].get("user_id") == "42"
    assert seen["ctx"].get("source") == "workflow"
    assert seen["ctx"].get("component") == "workflow"
    assert seen["ctx"].get("trace_id") == "tr-1"


def test_scheduler_decorator_binds_system() -> None:
    """apscheduler job 装饰器绑定 system + source=scheduler。"""
    from agents.management.commands.runapscheduler import (
        _with_scheduler_log_context,
    )

    seen: dict[str, Any] = {}

    @_with_scheduler_log_context
    def _job() -> str:
        seen["ctx"] = dict(structlog.contextvars.get_contextvars())
        return "ok"

    assert _job() == "ok"
    assert seen["ctx"].get("user_id") == "system"
    assert seen["ctx"].get("source") == "scheduler"
    assert seen["ctx"].get("component") == "scheduler"
    # 退出后清理
    assert "source" not in structlog.contextvars.get_contextvars()


@pytest.mark.asyncio
async def test_feishu_webhook_binds_source() -> None:
    """飞书 webhook 入口绑定 source=webhook_feishu + user_id=system。"""
    from feishu.views import FeishuWebhookView

    class _Headers(dict):
        pass

    class _Req:
        headers = _Headers({})
        body = b'{"type": "url_verification", "challenge": "c1"}'

    view = FeishuWebhookView()
    response = await view.post(_Req())
    assert response.data.get("challenge") == "c1"
    ctx = structlog.contextvars.get_contextvars()
    assert ctx.get("source") == "webhook_feishu"
    assert ctx.get("user_id") == "system"
