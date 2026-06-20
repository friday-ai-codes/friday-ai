"""DEPLOY-03 守护：多副本 / 多 worker 无 Redis channel layer 的运行期 fail-closed。

直接测纯函数 ``_require_redis_for_multi_replica``——不触 env / 不重载 settings 模块，
仅断言 expect_multi × use_redis 真值表行为。
"""

import pytest
from django.core.exceptions import ImproperlyConfigured

from friday.settings import _require_redis_for_multi_replica


def test_multi_replica_without_redis_raises():
    """声明多副本 / 多 worker 且未启用 Redis channel layer → fail-closed。"""
    with pytest.raises(ImproperlyConfigured):
        _require_redis_for_multi_replica(expect_multi=True, use_redis=False)


def test_multi_replica_with_redis_ok():
    """多副本 + Redis channel layer → 放行（返回 None）。"""
    assert _require_redis_for_multi_replica(expect_multi=True, use_redis=True) is None


def test_single_replica_without_redis_ok():
    """单副本单 worker 无 Redis → 允许内存 channel layer（返回 None）。"""
    assert _require_redis_for_multi_replica(expect_multi=False, use_redis=False) is None


def test_single_replica_with_redis_ok():
    """单副本即便启用 Redis 也不报错（返回 None）。"""
    assert _require_redis_for_multi_replica(expect_multi=False, use_redis=True) is None
