"""请求级指标采集守护测试（RATE-01 / SLA-02 / SLA-04）。

覆盖：
- ``classify_error`` 三口径（none/system/business/upstream）单一收口。
- ``record_request_metric`` 经队列 best-effort 落库 + labels 受控键过滤。
- ``enqueue`` 满队列 dropped 计数 / 落库失败 write_failed 计数（异常不反噬）。
- 各入口埋点（rest 中间件 / synthetic 隔离 / mcp / chat_sse / compat / webhook / ws）。
"""

from __future__ import annotations

import pytest

from common.request_metrics import classify_error, record_request_metric
from system import metric_sink


@pytest.fixture(autouse=True)
def _reset_metric_sink():
    """每个用例前后清空指标队列 + 计数（隔离）。"""
    metric_sink._reset_for_tests()
    yield
    metric_sink._reset_for_tests()


# === classify_error 三口径 ===


class TestClassifyError:
    def test_llm_busy_error_is_business(self) -> None:
        from agents.llm_concurrency import LLMBusyError

        assert classify_error(exc=LLMBusyError()) == "business"

    def test_drf_permission_denied_is_business(self) -> None:
        from rest_framework.exceptions import PermissionDenied

        assert classify_error(exc=PermissionDenied()) == "business"

    def test_django_permission_denied_is_business(self) -> None:
        from django.core.exceptions import PermissionDenied

        assert classify_error(exc=PermissionDenied()) == "business"

    def test_drf_validation_error_is_business(self) -> None:
        from rest_framework.exceptions import ValidationError

        assert classify_error(exc=ValidationError("bad")) == "business"

    def test_status_403_and_400_is_business(self) -> None:
        assert classify_error(status_code=403) == "business"
        assert classify_error(status_code=400) == "business"

    def test_5xx_is_system(self) -> None:
        assert classify_error(status_code=500) == "system"
        assert classify_error(status_code=503) == "system"

    def test_generic_exception_is_system(self) -> None:
        assert classify_error(exc=RuntimeError("boom")) == "system"

    def test_upstream_status_429_529_is_upstream(self) -> None:
        assert classify_error(status_code=429) == "upstream"
        assert classify_error(status_code=529) == "upstream"

    def test_upstream_exc_attr_is_upstream(self) -> None:
        exc = RuntimeError("provider failed")
        exc.upstream_status_code = 429  # type: ignore[attr-defined]
        assert classify_error(exc=exc) == "upstream"

    def test_explicit_upstream_flag(self) -> None:
        assert classify_error(status_code=500, upstream=True) == "upstream"

    def test_2xx_3xx_is_none(self) -> None:
        assert classify_error(status_code=200) == "none"
        assert classify_error(status_code=302) == "none"

    def test_no_args_is_none(self) -> None:
        assert classify_error() == "none"


# === record_request_metric 落库 + labels 过滤 ===


@pytest.mark.django_db
class TestRecordRequestMetric:
    def test_record_persists_one_row(self) -> None:
        from system.models import RequestMetric

        record_request_metric(
            source="rest",
            route="/api/projects/",
            method="GET",
            status_code=200,
            error_class="none",
            duration_ms=12,
            user_id="42",
        )
        metric_sink.flush_now()

        row = RequestMetric.objects.order_by("-id").first()
        assert row is not None
        assert row.source == "rest"
        assert row.route == "/api/projects/"
        assert row.method == "GET"
        assert row.status_code == 200
        assert row.error_class == "none"
        assert row.duration_ms == 12
        assert row.ttft_ms is None
        assert row.user_id == "42"

    def test_labels_only_allowed_keys(self) -> None:
        from system.models import RequestMetric

        record_request_metric(
            source="mcp",
            route="/mcp/",
            method="POST",
            labels={
                "call_source": "search_rag",
                "run_id": "run-123",
                # 未知键应被过滤
                "raw_query": "secret user input",
                "api_key": "sk-leak",
            },
        )
        metric_sink.flush_now()

        row = RequestMetric.objects.order_by("-id").first()
        assert row is not None
        assert row.labels == {"call_source": "search_rag", "run_id": "run-123"}
        assert "raw_query" not in row.labels
        assert "api_key" not in row.labels

    def test_user_id_from_contextvars_when_omitted(self) -> None:
        import structlog

        from system.models import RequestMetric

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(user_id="99")
        try:
            record_request_metric(source="rest", route="/x", method="GET", status_code=200)
            metric_sink.flush_now()
        finally:
            structlog.contextvars.clear_contextvars()

        row = RequestMetric.objects.order_by("-id").first()
        assert row is not None
        assert row.user_id == "99"


# === 队列背压 + 落库失败计数 ===


class TestSinkCounters:
    def test_full_queue_drops_and_counts(self) -> None:
        # 填满队列（不起线程，纯内存）
        for _ in range(metric_sink._MAXLEN):
            metric_sink.enqueue_request_metric({"source": "rest"})
        before = metric_sink.snapshot_counters()["dropped"]
        metric_sink.enqueue_request_metric({"source": "rest"})  # 满 → drop
        after = metric_sink.snapshot_counters()["dropped"]
        assert after == before + 1

    @pytest.mark.django_db
    def test_write_failure_increments_counter_no_raise(self, monkeypatch) -> None:
        from system.models import RequestMetric

        def _boom(*args, **kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr(RequestMetric.objects, "bulk_create", _boom)
        record_request_metric(source="rest", route="/x", method="GET", status_code=200)
        # flush_now 不抛（best-effort）
        metric_sink.flush_now()
        assert metric_sink.snapshot_counters()["write_failed"] >= 1

    def test_enqueue_never_raises_on_bad_entry(self) -> None:
        # enqueue 是纯内存，传入畸形 entry 也绝不抛
        metric_sink.enqueue_request_metric({"source": "rest", "labels": None})
        metric_sink.enqueue_request_metric({})


# === Task 2: HTTP 中间件 + MCP + chat SSE 入口埋点 ===


class _FakeResolverMatch:
    def __init__(self, route: str) -> None:
        self.route = route


class _FakeRequest:
    def __init__(self, path: str, method: str = "GET", route: str | None = None) -> None:
        self.path = path
        self.method = method
        self.headers: dict = {}
        self.resolver_match = _FakeResolverMatch(route) if route else None


class _FakeResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code


@pytest.mark.django_db
class TestMiddlewareMetric:
    def test_plain_rest_request_records_row(self) -> None:
        import structlog

        from common.middleware import RequestLogContextMiddleware
        from system.models import RequestMetric

        def _get_response(request):
            # 模拟 DRF mixin 认证后补绑真实 user_id
            structlog.contextvars.bind_contextvars(user_id="7")
            return _FakeResponse(200)

        mw = RequestLogContextMiddleware(_get_response)
        mw(_FakeRequest("/api/projects/", method="GET", route="api/projects/"))
        metric_sink.flush_now()

        row = RequestMetric.objects.order_by("-id").first()
        assert row is not None
        assert row.source == "rest"
        assert row.route == "api/projects/"
        assert row.method == "GET"
        assert row.status_code == 200
        assert row.error_class == "none"
        assert row.user_id == "7"
        assert row.duration_ms is not None
        assert not row.labels.get("synthetic")

    def test_health_route_marked_synthetic(self) -> None:
        from common.middleware import RequestLogContextMiddleware
        from system.models import RequestMetric

        mw = RequestLogContextMiddleware(lambda r: _FakeResponse(200))
        mw(_FakeRequest("/health", method="GET"))
        metric_sink.flush_now()

        row = RequestMetric.objects.order_by("-id").first()
        assert row is not None
        assert row.labels.get("synthetic") is True

    def test_poll_route_marked_synthetic(self) -> None:
        from common.middleware import RequestLogContextMiddleware
        from system.models import RequestMetric

        mw = RequestLogContextMiddleware(lambda r: _FakeResponse(200))
        mw(_FakeRequest("/api/runners/123/poll", method="GET"))
        metric_sink.flush_now()

        row = RequestMetric.objects.order_by("-id").first()
        assert row is not None
        assert row.labels.get("synthetic") is True

    def test_non_rest_source_skipped_by_middleware(self) -> None:
        """专用入口（source!=rest）已自行埋点 → 中间件跳过兜底，避免重复计数。"""
        import structlog

        from common.middleware import RequestLogContextMiddleware
        from system.models import RequestMetric

        def _get_response(request):
            structlog.contextvars.bind_contextvars(source="mcp")
            return _FakeResponse(200)

        mw = RequestLogContextMiddleware(_get_response)
        mw(_FakeRequest("/api/mcp/x", method="POST"))
        metric_sink.flush_now()

        assert RequestMetric.objects.count() == 0

    def test_exception_records_system_error_and_reraises(self) -> None:
        from common.middleware import RequestLogContextMiddleware
        from system.models import RequestMetric

        def _boom(request):
            raise RuntimeError("kaboom")

        mw = RequestLogContextMiddleware(_boom)
        with pytest.raises(RuntimeError):
            mw(_FakeRequest("/api/projects/", method="GET"))
        metric_sink.flush_now()

        row = RequestMetric.objects.order_by("-id").first()
        assert row is not None
        assert row.error_class == "system"
        assert row.status_code == 500


@pytest.mark.django_db(transaction=True)
class TestMcpRecordMetric:
    async def test_record_emits_mcp_metric_with_call_source(self, monkeypatch) -> None:
        from mcp_tools import views as mcp_views
        from system.models import RequestMetric

        async def _noop_tool_call(*args, **kwargs):
            return None

        async def _noop_trace(*args, **kwargs):
            return None

        monkeypatch.setattr(mcp_views, "arecord_tool_call", _noop_tool_call)
        monkeypatch.setattr(mcp_views, "arecord_retrieval_trace", _noop_trace)

        class _FakeRun:
            run_id = "run-abc"

        view = mcp_views.SearchRagChunksView()
        await view._record(
            _FakeRun(),
            input_data={},
            output_data={},
            traces=[],
            started_at=__import__("time").perf_counter(),
            call_status="ok",
        )
        from asgiref.sync import sync_to_async

        await sync_to_async(metric_sink.flush_now)()

        row = await sync_to_async(
            lambda: RequestMetric.objects.filter(source="mcp").order_by("-id").first()
        )()
        assert row is not None
        assert row.source == "mcp"
        assert row.labels.get("call_source") == "search_rag_chunks"
        assert row.labels.get("run_id") == "run-abc"


@pytest.mark.django_db(transaction=True)
class TestChatSseMetric:
    async def test_stream_events_records_ttft_and_duration(self, monkeypatch) -> None:
        import asyncio

        from agents.core.events import AgentEvent
        from chat import views as chat_views
        from chat.conversation_service import ConversationService
        from system.models import RequestMetric

        async def _fake_stream(*args, **kwargs):
            yield AgentEvent(type="text_delta", data={"text": "hi"})
            await asyncio.sleep(0.02)
            yield AgentEvent(type="message_complete", data={})

        monkeypatch.setattr(ConversationService, "send_message_stream", _fake_stream)

        import uuid as uuid_mod

        conversation_id = str(uuid_mod.uuid4())
        view = chat_views.ChatStreamView()
        chunks = [
            chunk
            async for chunk in view._stream_events(
                conversation_id,
                "hello",
                "developer",
                "42",
                metric_user_id="42",
            )
        ]
        assert chunks  # 至少产出若干 SSE 帧
        from asgiref.sync import sync_to_async

        await sync_to_async(metric_sink.flush_now)()

        row = await sync_to_async(
            lambda: RequestMetric.objects.filter(source="chat_sse").order_by("-id").first()
        )()
        assert row is not None
        assert row.source == "chat_sse"
        assert row.ttft_ms is not None
        assert row.duration_ms is not None
        assert row.ttft_ms <= row.duration_ms
        assert row.error_class == "none"
        assert row.user_id == "42"
        assert row.labels.get("conversation_id") == conversation_id


# === Task 3: compat + webhook + WS 入口埋点 ===


async def _aflush() -> None:
    from asgiref.sync import sync_to_async

    await sync_to_async(metric_sink.flush_now)()


async def _afirst(source: str):
    from asgiref.sync import sync_to_async

    from system.models import RequestMetric

    return await sync_to_async(
        lambda: RequestMetric.objects.filter(source=source).order_by("-id").first()
    )()


@pytest.mark.django_db(transaction=True)
class TestCompatMetric:
    async def test_openai_stream_records_ttft(self, monkeypatch) -> None:
        import asyncio

        from compat import views as compat_views

        async def _fake_translate(*args, **kwargs):
            yield b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
            await asyncio.sleep(0.02)
            yield b'data: {"choices":[{"delta":{"content":" there"}}]}\n\n'

        monkeypatch.setattr(
            compat_views.OpenAICompatAdapter, "translate_stream", _fake_translate
        )

        view = compat_views.ChatCompletionsView()
        chunks = [
            c
            async for c in view._stream_chunks(
                runner=None,
                lc_messages=[],
                params={},
                model_name="friday-default",
                metric_route="/v1/chat/completions",
            )
        ]
        assert chunks
        await _aflush()

        row = await _afirst("compat_openai")
        assert row is not None
        assert row.source == "compat_openai"
        assert row.ttft_ms is not None
        assert row.ttft_ms <= row.duration_ms

    async def test_anthropic_stream_records_ttft(self, monkeypatch) -> None:
        import asyncio

        from compat import views as compat_views

        async def _fake_translate(*args, **kwargs):
            yield b"event: message_start\ndata: {}\n\n"
            await asyncio.sleep(0.02)
            yield b"event: message_stop\ndata: {}\n\n"

        monkeypatch.setattr(
            compat_views.AnthropicCompatAdapter, "translate_stream", _fake_translate
        )

        view = compat_views.MessagesView()
        chunks = [
            c
            async for c in view._stream_anthropic(
                None,
                [],
                "friday-default",
                metric_route="/v1/messages",
            )
        ]
        assert chunks
        await _aflush()

        row = await _afirst("compat_anthropic")
        assert row is not None
        assert row.source == "compat_anthropic"
        assert row.ttft_ms is not None


@pytest.mark.django_db(transaction=True)
class TestWebhookMetric:
    async def test_inbound_webhook_records_system_metric(self) -> None:
        from system.webhook_recorder import record_inbound_webhook

        await record_inbound_webhook(
            kind="workflow",
            raw_body={"event": "x"},
            headers={},
            user_id="system",
            correlation={"execution_id": "exec-1", "event_uuid": "u1"},
        )
        await _aflush()

        row = await _afirst("webhook_workflow")
        assert row is not None
        assert row.source == "webhook_workflow"
        assert row.user_id == "system"
        # 受控键保留，未知键（event_uuid）被过滤
        assert row.labels.get("execution_id") == "exec-1"
        assert "event_uuid" not in row.labels

    async def test_feishu_webhook_maps_source(self) -> None:
        from system.webhook_recorder import record_inbound_webhook

        await record_inbound_webhook(
            kind="feishu",
            raw_body={"type": "event"},
            headers={},
        )
        await _aflush()

        row = await _afirst("webhook_feishu")
        assert row is not None
        assert row.source == "webhook_feishu"


@pytest.mark.django_db(transaction=True)
class TestWsMetric:
    async def test_workflow_consumer_connect_disconnect(self) -> None:
        from unittest.mock import AsyncMock

        from system.models import RequestMetric
        from workflows.consumers import WorkflowExecutionConsumer

        consumer = WorkflowExecutionConsumer()
        consumer.scope = {"url_route": {"kwargs": {"execution_id": "exec-1"}}}
        consumer.channel_layer = AsyncMock()
        consumer.channel_name = "chan-1"
        consumer.accept = AsyncMock()

        await consumer.connect()
        await consumer.disconnect(1000)
        await _aflush()

        from asgiref.sync import sync_to_async

        events = await sync_to_async(
            lambda: list(
                RequestMetric.objects.filter(source="ws")
                .order_by("id")
                .values_list("labels", flat=True)
            )
        )()
        ws_events = [e.get("ws_event") for e in events]
        assert "connect" in ws_events
        assert "disconnect" in ws_events
