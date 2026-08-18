"""consumer 级 fail-soft 守护：``group_add`` 失败必须关闭连接而非抛异常（Q86L-02）。

不经真实 WS，直接实例化 consumer 并注入 mock channel layer（同
``tests/workflows/test_debug_websocket.py`` 的构造手法），断言 D4 表逐行语义：
握手期订阅失败 → ``close(code=1013)`` 且**未** ``accept``（未 accept 就 close 在 ASGI 下
即「拒绝 upgrade」，1013 不会作为 close frame 落地，但异常不再逃进 ASGI 服务器才是关键收益）；
``NotificationConsumer`` 的广播组失败则只降级公告、放行连接。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import redis.exceptions

from notifications.consumers import NotificationConsumer
from runners.consumers import RunnerConsumer
from workflows.consumers import WorkflowExecutionConsumer

_UVLOOP_ERROR = RuntimeError(
    "unable to perform operation on <TCPTransport closed=True reading=False>; the handler is closed"
)


def _wire(consumer, *, group_add_side_effect=None):
    """给 consumer 注入 mock 传输层与 channel layer。"""
    consumer.channel_name = "test-channel"
    consumer.channel_layer = MagicMock()
    consumer.channel_layer.group_add = AsyncMock(side_effect=group_add_side_effect)
    consumer.channel_layer.group_discard = AsyncMock()
    consumer.accept = AsyncMock()
    consumer.close = AsyncMock()
    consumer.send_json = AsyncMock()
    consumer.send = AsyncMock()
    return consumer


async def test_runner_consumer_rejects_handshake_when_group_add_fails():
    """RunnerConsumer：group_add 恒失败 → close(1013)、不 accept、异常不外抛。"""
    consumer = _wire(RunnerConsumer(), group_add_side_effect=_UVLOOP_ERROR)
    consumer.scope = {"runner": MagicMock(id="r1", name="runner-1")}

    await consumer.connect()

    assert consumer.close.await_args.kwargs["code"] == 1013
    consumer.accept.assert_not_awaited()
    # 拒绝握手后不得起 hello 超时任务（否则留下悬挂 task）。
    assert not hasattr(consumer, "_hello_timeout")


async def test_runner_consumer_accepts_when_group_add_succeeds():
    """RunnerConsumer 正常路径不受改动影响：accept 被 await、close 未被调用。"""
    consumer = _wire(RunnerConsumer())
    consumer.scope = {"runner": MagicMock(id="r1", name="runner-1")}

    with patch.object(RunnerConsumer, "_update_channel_name", AsyncMock()):
        await consumer.connect()

    consumer.accept.assert_awaited_once()
    consumer.close.assert_not_awaited()
    consumer._hello_timeout.cancel()  # 清理挂起的握手超时任务


async def test_workflow_consumer_rejects_handshake_on_redis_connection_error():
    """WorkflowExecutionConsumer：redis ConnectionError → close(1013)、不 accept。"""
    consumer = _wire(
        WorkflowExecutionConsumer(),
        group_add_side_effect=redis.exceptions.ConnectionError("Connection reset by peer"),
    )
    consumer.scope = {"url_route": {"kwargs": {"execution_id": "e1"}}}

    await consumer.connect()

    assert consumer.close.await_args.kwargs["code"] == 1013
    consumer.accept.assert_not_awaited()


async def test_notification_consumer_degrades_when_broadcast_group_fails():
    """NotificationConsumer：用户组成功 + 广播组失败 → 放行连接，仅公告降级（D4）。"""
    consumer = _wire(
        NotificationConsumer(),
        # 用户组第一次成功、广播组两次尝试都失败。
        group_add_side_effect=[None, _UVLOOP_ERROR, _UVLOOP_ERROR],
    )
    consumer.scope = {"user": MagicMock(id="u1", is_authenticated=True)}

    with patch(
        "notifications.services.NotificationService.aunread_count",
        AsyncMock(return_value=0),
    ):
        await consumer.connect()

    consumer.accept.assert_awaited_once()
    consumer.close.assert_not_awaited()
    # 只有真正加入过的组才会被记下 → disconnect 不会误退订。
    assert hasattr(consumer, "broadcast_group") is False


async def test_notification_consumer_rejects_when_user_group_fails():
    """NotificationConsumer：个人通知组失败 → close(1013)、不 accept（不降级）。"""
    consumer = _wire(NotificationConsumer(), group_add_side_effect=_UVLOOP_ERROR)
    consumer.scope = {"user": MagicMock(id="u1", is_authenticated=True)}

    await consumer.connect()

    assert consumer.close.await_args.kwargs["code"] == 1013
    consumer.accept.assert_not_awaited()
