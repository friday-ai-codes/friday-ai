"""Q86L-01 守护：channel layer 的 Redis 连接加固配置 + InMemory 默认不回退。

直接测纯函数 ``_build_channel_layer_host``——不触 env / 不重载 settings 模块。
重点守 ``socket_timeout`` 的 10s 下限：redis-py 把它直接用于阻塞 ``BZPOPMIN`` 的
``read_response``，取值 <= channels_redis 的 ``brpop_timeout``(5s) 会让空闲 channel
每 5s 假超时、把正常的 WS 收发打断（T-86L-05：加固不得反过来制造故障）。
"""

from django.conf import settings

from friday.settings import _build_channel_layer_host


def _build(**overrides):
    kwargs = {
        "address": "redis://127.0.0.1:6379/0",
        "health_check_interval": 30,
        "socket_connect_timeout": 5,
        "socket_timeout": 15,
        "socket_keepalive": True,
        "retry_on_timeout": True,
    }
    kwargs.update(overrides)
    return _build_channel_layer_host(**kwargs)


def test_host_dict_carries_address_and_tuning_keys():
    """正常入参 → dict 含 address 与 5 个连接调优键，值与入参一致。"""
    host = _build()

    assert host == {
        "address": "redis://127.0.0.1:6379/0",
        "health_check_interval": 30,
        "socket_keepalive": True,
        "socket_connect_timeout": 5,
        "socket_timeout": 15,
        "retry_on_timeout": True,
    }


def test_socket_timeout_clamped_to_floor():
    """socket_timeout=3 → 被夹到 >= 10s（守 brpop_timeout 下限，防未来被人调小）。"""
    assert _build(socket_timeout=3)["socket_timeout"] >= 10


def test_socket_timeout_above_floor_preserved():
    """socket_timeout=30 → 保持 30（夹取只设下限、不设上限）。"""
    assert _build(socket_timeout=30)["socket_timeout"] == 30


def test_default_channel_layer_stays_in_memory():
    """USE_REDIS_CHANNEL_LAYER 默认 false → 仍为 InMemoryChannelLayer（本地裸跑不回退）。"""
    assert settings.CHANNEL_LAYERS["default"]["BACKEND"] == "channels.layers.InMemoryChannelLayer"
