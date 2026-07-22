"""任务级短 TTL token 生命周期测试（Phase 103 AGENT-01）。

覆盖：
- mint_task_token：明文前缀 / DB 只存 sha256 / kind=task / session_id / expires_at 余量
- 认证零改动复用：minted 明文经 AccessTokenAuthentication 认证通过，request.auth.kind=="task"
- 过期 / 吊销：is_valid 语义 + arevoke_task_tokens 幂等
- 存量兼容：不带 kind 的创建路径（views.py / make_access_token）恒 personal + session_id None

（Task 3 追加：三链派发集成 / 泄漏防线扫描 / MCP 链覆盖 / 终态吊销双路径。）
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from runners.models import hash_token

pytestmark = pytest.mark.django_db(transaction=True)


@sync_to_async
def _make_user(username: str) -> Any:
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username=username, password="x")


# =========================================================================
# mint：新签发语义（明文仅内存返回一次，DB 只存 sha256）
# =========================================================================


@pytest.mark.asyncio
async def test_mint_returns_plaintext_and_persists_hash_only() -> None:
    from access_tokens.models import AccessToken
    from access_tokens.services import mint_task_token

    user = await _make_user("mint-user")
    before = timezone.now()
    plaintext = await mint_task_token(user, "sess-mint-001", 1800)

    assert plaintext.startswith("friday_pat_")

    token = await AccessToken.objects.aget(kind="task", session_id="sess-mint-001")
    assert token.token_hash == hash_token(plaintext)
    assert token.kind == "task"
    assert token.session_id == "sess-mint-001"
    assert token.created_by_id == user.id
    # expires_at ≈ now + timeout + 600s 余量（±60s 容差）
    expected = before + timedelta(seconds=1800 + 600)
    assert abs((token.expires_at - expected).total_seconds()) < 60

    # 明文绝不出现在该行任何具体字段（PAT-02）；用 attname（FK 取 *_id）避免
    # async 上下文触发关系对象同步查询。
    for field in token._meta.concrete_fields:
        assert plaintext not in str(getattr(token, field.attname))


@pytest.mark.asyncio
async def test_mint_is_new_issue_each_call() -> None:
    """PAT-02 语义：mint 是新签发——同一用户两次 mint 得到不同明文/不同 DB 行。"""
    from access_tokens.models import AccessToken
    from access_tokens.services import mint_task_token

    user = await _make_user("mint-twice-user")
    p1 = await mint_task_token(user, "sess-twice-a", 600)
    p2 = await mint_task_token(user, "sess-twice-b", 600)

    assert p1 != p2
    assert await AccessToken.objects.filter(kind="task", created_by=user).acount() == 2


# =========================================================================
# 认证零改动复用：minted 明文可直接过 AccessTokenAuthentication
# =========================================================================


@pytest.mark.asyncio
async def test_minted_token_authenticates_with_kind_task() -> None:
    from access_tokens.authentication import AccessTokenAuthentication
    from access_tokens.services import mint_task_token

    user = await _make_user("mint-auth-user")
    plaintext = await mint_task_token(user, "sess-auth-001", 1800)

    request = APIRequestFactory().get("/", HTTP_AUTHORIZATION=f"Bearer {plaintext}")
    result = await sync_to_async(AccessTokenAuthentication().authenticate)(request)
    assert result is not None
    auth_user, auth_token = result
    assert auth_user == user
    assert auth_token.kind == "task"
    assert auth_token.session_id == "sess-auth-001"


# =========================================================================
# 过期 / 吊销 / 幂等
# =========================================================================


@pytest.mark.asyncio
async def test_expired_task_token_is_invalid() -> None:
    from access_tokens.models import AccessToken
    from access_tokens.services import mint_task_token

    user = await _make_user("mint-expire-user")
    await mint_task_token(user, "sess-expire-001", 60)

    token = await AccessToken.objects.aget(kind="task", session_id="sess-expire-001")
    assert token.is_valid is True
    # 回拨 expires_at 模拟过期
    token.expires_at = timezone.now() - timedelta(seconds=1)
    await token.asave(update_fields=["expires_at"])
    assert token.is_valid is False


@pytest.mark.asyncio
async def test_revoke_task_tokens_idempotent() -> None:
    from access_tokens.models import AccessToken
    from access_tokens.services import arevoke_task_tokens, mint_task_token

    user = await _make_user("mint-revoke-user")
    await mint_task_token(user, "sess-revoke-001", 600)

    count = await arevoke_task_tokens("sess-revoke-001")
    assert count == 1
    token = await AccessToken.objects.aget(kind="task", session_id="sess-revoke-001")
    assert token.is_valid is False
    assert token.revoked_at is not None
    first_revoked_at = token.revoked_at

    # 二次调用幂等：count=0，revoked_at 保留首次时间戳
    count2 = await arevoke_task_tokens("sess-revoke-001")
    assert count2 == 0
    await token.arefresh_from_db()
    assert token.revoked_at == first_revoked_at


@pytest.mark.asyncio
async def test_revoke_unknown_session_returns_zero() -> None:
    from access_tokens.services import arevoke_task_tokens

    assert await arevoke_task_tokens("sess-nonexistent") == 0


# =========================================================================
# 存量兼容：不带 kind 的创建路径恒 personal
# =========================================================================


def test_legacy_creation_defaults_to_personal(
    make_access_token: Callable[..., tuple[Any, str]],
) -> None:
    token, _plaintext = make_access_token(name="legacy-token")
    assert token.kind == "personal"
    assert token.session_id is None
