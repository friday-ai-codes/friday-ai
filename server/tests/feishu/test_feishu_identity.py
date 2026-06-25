"""飞书身份映射守护测试：手动/JIT 绑定 + 未映射 fail-soft（Phase 77，IDENT-01）。"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from feishu.models import FeishuBindingSource, FeishuUserBinding
from feishu.services import bind_feishu_user, resolve_feishu_user

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


@sync_to_async
def _user(username) -> object:
    return User.objects.create_user(username=username, password="x")


async def test_resolve_unmapped_returns_none_fail_soft() -> None:
    """未映射 fail-soft 返回 None，不抛、不阻断。"""
    assert await resolve_feishu_user(feishu_user_key="nobody") is None
    assert await resolve_feishu_user(open_id="ou_nobody") is None
    assert await resolve_feishu_user() is None  # 都不传也安全返回 None


async def test_manual_binding_resolves() -> None:
    u = await _user("alice")
    await bind_feishu_user(user=u, feishu_user_key="uk_alice")
    resolved = await resolve_feishu_user(feishu_user_key="uk_alice")
    assert resolved is not None
    assert resolved.id == u.id


async def test_jit_binding_resolves_by_open_id() -> None:
    u = await _user("bob")
    binding = await bind_feishu_user(
        user=u, open_id="ou_bob", source=FeishuBindingSource.JIT
    )
    assert binding.source == FeishuBindingSource.JIT
    resolved = await resolve_feishu_user(open_id="ou_bob")
    assert resolved is not None and resolved.id == u.id


async def test_manual_preferred_over_jit() -> None:
    """同一 user_key 同时存在 manual 与 jit 绑定时，解析优先返回 manual 绑定的用户。"""
    manual_user = await _user("manual_u")
    jit_user = await _user("jit_u")
    await bind_feishu_user(
        user=jit_user, feishu_user_key="shared", source=FeishuBindingSource.JIT
    )
    await bind_feishu_user(
        user=manual_user, feishu_user_key="shared", source=FeishuBindingSource.MANUAL
    )
    resolved = await resolve_feishu_user(feishu_user_key="shared")
    assert resolved.id == manual_user.id


async def test_bind_idempotent() -> None:
    u = await _user("carol")
    b1 = await bind_feishu_user(user=u, feishu_user_key="uk_carol")
    b2 = await bind_feishu_user(user=u, feishu_user_key="uk_carol")
    assert b1.id == b2.id
    assert (
        await FeishuUserBinding.objects.filter(
            feishu_user_key="uk_carol", user=u
        ).acount()
        == 1
    )


async def test_bind_requires_some_identifier() -> None:
    u = await _user("dave")
    with pytest.raises(ValueError):
        await bind_feishu_user(user=u)
