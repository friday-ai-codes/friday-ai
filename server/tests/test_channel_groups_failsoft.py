"""``common/channel_groups.py`` fail-soft helper 行为守护（Q86L-03）。

守的是「Redis 抖动不得把 WS 打崩」这条硬约束：``safe_group_add`` / ``safe_group_discard``
必须吞掉 uvloop ``RuntimeError`` / ``redis.exceptions.*`` / ``asyncio.TimeoutError``，
但 ``asyncio.CancelledError`` 必须原样穿透（否则任务取消语义被吞、掩盖真实的关闭流程）。

日志断言用 ``structlog.testing.capture_logs()``——它**绕过** processor 链，所以
``redact_credentials`` 不生效；脱敏必须发生在埋点处，本文件的脱敏断言正是它的门禁。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
import redis.exceptions
import structlog

from common.channel_groups import safe_group_add, safe_group_discard

# uvloop 在已关闭 transport 上抛的真实文本形态（根因小节 3：redis-py 不会把它映射成
# ConnectionError，故 Retry 永不重试、直穿 connect()）。
_UVLOOP_ERROR = RuntimeError(
    "unable to perform operation on <TCPTransport closed=True reading=False>; the handler is closed"
)


def _make_layer() -> MagicMock:
    """造一个只有 group_add / group_discard 的假 channel layer。"""
    layer = MagicMock()
    layer.group_add = AsyncMock()
    layer.group_discard = AsyncMock()
    return layer


# === safe_group_add ===


async def test_group_add_success_returns_true_without_failure_event():
    """一次成功 → True、只调用 1 次、不发任何失败/恢复事件（D1 成功路径不刷日志）。"""
    layer = _make_layer()

    with structlog.testing.capture_logs() as captured:
        assert await safe_group_add(layer, "g1", "c1", component="runners") is True

    assert layer.group_add.await_count == 1
    assert [e for e in captured if str(e.get("event", "")).startswith("ws_group_")] == []


async def test_group_add_retries_once_and_reports_recovered():
    """首次 uvloop RuntimeError、第二次成功 → True + ws_group_add_recovered（依据 A）。"""
    layer = _make_layer()
    layer.group_add.side_effect = [_UVLOOP_ERROR, None]

    with structlog.testing.capture_logs() as captured:
        assert await safe_group_add(layer, "g1", "c1", component="runners") is True

    assert layer.group_add.await_count == 2
    events = [e for e in captured if e.get("event") == "ws_group_add_recovered"]
    assert events, f"未捕获 ws_group_add_recovered；captured={captured}"
    event = events[0]
    assert event["log_level"] == "info"
    assert event["category"] == "sampling"
    assert event["attempt"] == 2
    assert event["previous_error_type"] == "RuntimeError"
    assert isinstance(event["duration_ms"], int)


async def test_group_add_all_attempts_fail_returns_false():
    """两次都抛 RuntimeError → False、不抛、恰好 2 次尝试、发 ws_group_add_failed。"""
    layer = _make_layer()
    layer.group_add.side_effect = _UVLOOP_ERROR

    with structlog.testing.capture_logs() as captured:
        assert await safe_group_add(layer, "g1", "c1", component="runners") is False

    assert layer.group_add.await_count == 2
    assert [e for e in captured if e.get("event") == "ws_group_add_failed"]


async def test_group_add_swallows_redis_connection_error():
    """redis.exceptions.ConnectionError 同样被吞（不止 uvloop RuntimeError）。"""
    layer = _make_layer()
    layer.group_add.side_effect = redis.exceptions.ConnectionError("Connection reset by peer")

    assert await safe_group_add(layer, "g1", "c1", component="workflows") is False
    assert layer.group_add.await_count == 2


async def test_group_add_bounded_by_timeout(monkeypatch: pytest.MonkeyPatch):
    """group_add 永久挂住 → asyncio.wait_for 兜底，返回 False 且快速返回（T-86L-02）。"""
    monkeypatch.setattr("common.channel_groups._GROUP_OP_TIMEOUT_SECONDS", 0.01)
    layer = _make_layer()

    async def _hang(*_args, **_kwargs):
        await asyncio.sleep(60)

    layer.group_add.side_effect = _hang

    started = asyncio.get_running_loop().time()
    assert await safe_group_add(layer, "g1", "c1", component="chat") is False
    # 2 次尝试 × 0.01s 上界；给足调度余量仍必须远小于 60s 的挂起时长。
    assert asyncio.get_running_loop().time() - started < 5


async def test_group_add_propagates_cancelled_error():
    """CancelledError 必须穿透——任务取消语义不许被 fail-soft 吞掉。"""
    layer = _make_layer()
    layer.group_add.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await safe_group_add(layer, "g1", "c1", component="runners")


async def test_group_add_failed_event_field_contract():
    """ws_group_add_failed 字段契约：category/component/error_type/duration_ms/source/用户。"""
    layer = _make_layer()
    layer.group_add.side_effect = _UVLOOP_ERROR

    with structlog.testing.capture_logs() as captured:
        await safe_group_add(
            layer,
            "notifications_user_7",
            "c1",
            component="notifications",
            initiated_by_user_id="7",
        )

    events = [e for e in captured if e.get("event") == "ws_group_add_failed"]
    assert events, f"未捕获 ws_group_add_failed；captured={captured}"
    event = events[0]
    assert event["log_level"] == "warning"
    assert event["category"] == "caller"
    assert event["component"] == "notifications"
    assert event["group"] == "notifications_user_7"
    assert event["source"] == "ws"
    assert event["initiated_by_user_id"] == "7"
    assert event["attempts"] == 2
    assert event["error_type"] == "RuntimeError"
    assert isinstance(event["duration_ms"], int)


async def test_group_add_failed_event_redacts_credentials():
    """异常文本夹带的凭证在埋点处即被脱敏（T-86L-01：日志/落库绝不留明文）。"""
    layer = _make_layer()
    layer.group_add.side_effect = RuntimeError("boom token=sk-ant-api03-DEADBEEFDEADBEEF")

    with structlog.testing.capture_logs() as captured:
        await safe_group_add(layer, "g1", "c1", component="runners")

    events = [e for e in captured if e.get("event") == "ws_group_add_failed"]
    assert events
    logged_error = events[0]["error"]
    assert "sk-ant-" not in logged_error
    assert "REDACTED" in logged_error


# === safe_group_discard ===


async def test_group_discard_swallows_runtime_error():
    """断连清理绝不反噬：group_discard 抛 RuntimeError → 返回 None、不抛。"""
    layer = _make_layer()
    layer.group_discard.side_effect = _UVLOOP_ERROR

    with structlog.testing.capture_logs() as captured:
        assert await safe_group_discard(layer, "g1", "c1", component="runners") is None

    events = [e for e in captured if e.get("event") == "ws_group_discard_failed"]
    assert events, f"未捕获 ws_group_discard_failed；captured={captured}"
    event = events[0]
    assert event["log_level"] == "debug"
    assert event["category"] == "sampling"
    assert event["error_type"] == "RuntimeError"
    assert event["source"] == "ws"
    assert isinstance(event["duration_ms"], int)


async def test_group_discard_propagates_cancelled_error():
    """CancelledError 在退订路径同样穿透。"""
    layer = _make_layer()
    layer.group_discard.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await safe_group_discard(layer, "g1", "c1", component="runners")
