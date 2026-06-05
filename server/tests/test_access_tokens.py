"""contract..04 锁名测试桩（implementation Wave）。

Nyquist Wave：在实现代码落地前先用锁名测试把 TOKEN 契约固定下来。
顶部 `pytest.importorskip("access_tokens.models")` 让模块未实现时整文件优雅 skip，
保证套件可收集、不报 collection error；checkpoint/04 实现落地后这些断言自动生效（RED→GREEN）。

覆盖需求：
- contract：创建返回一次性明文（friday_pat_ 前缀）
- contract：list/任何字段绝不含明文（contract）
- contract：有效 token 认证放行，无 scope 分权（contract single token）
- contract：吊销/过期 token 被拒并写 DENIED run
"""

from __future__ import annotations

from typing import Any, Callable

import pytest

pytest.importorskip("access_tokens.models")

from rest_framework.test import APIRequestFactory  # noqa: E402

from runners.models import hash_token  # noqa: E402


@pytest.mark.django_db
def test_create_returns_plaintext_once(
    make_access_token: Callable[..., tuple[Any, str]],
) -> None:
    """contract：创建返回一次性明文，入库只存 fingerprint，明文不入任何字段。"""
    token, plaintext = make_access_token(name="ci-token")

    assert plaintext.startswith("friday_pat_")
    # 入库的是 hash(明文)，明文本身绝不落任何字段（contract / contract）
    assert token.token_hash == hash_token(plaintext)
    assert token.token_prefix == plaintext[:12]
    assert plaintext != token.token_hash
    assert plaintext not in token.name


@pytest.mark.django_db
def test_list_never_returns_plaintext(
    make_access_token: Callable[..., tuple[Any, str]],
) -> None:
    """contract：遍历 token 全部具体字段，断言明文绝不出现（contract）。"""
    from access_tokens.models import AccessToken

    _token, plaintext = make_access_token(name="list-token")

    for obj in AccessToken.objects.all():
        for field in obj._meta.concrete_fields:
            assert plaintext not in str(getattr(obj, field.name))


@pytest.mark.django_db
def test_valid_token_passes(
    make_access_token: Callable[..., tuple[Any, str]],
) -> None:
    """contract：有效 token 认证放行（无 scope 校验，contract single token）。"""
    auth_mod = pytest.importorskip("access_tokens.authentication")

    token, plaintext = make_access_token(name="valid-token")
    assert token.is_valid is True

    request = APIRequestFactory().get(
        "/", HTTP_AUTHORIZATION=f"Bearer {plaintext}"
    )
    result = auth_mod.AccessTokenAuthentication().authenticate(request)
    assert result is not None
    user, auth_token = result
    # 仿 RunnerTokenAuthentication：返回 (None, token)
    assert user is None
    assert auth_token.token_hash == token.token_hash
    # single token：有效即拥有全部能力，模型无 scope 字段
    assert not hasattr(auth_token, "scope")


@pytest.mark.django_db
def test_revoked_expired_denied_and_logged(
    make_access_token: Callable[..., tuple[Any, str]],
) -> None:
    """contract：吊销 token 被拒，并写一条 DENIED run（fingerprint 入库，明文不入）。"""
    auth_mod = pytest.importorskip("access_tokens.authentication")
    interactions_models = pytest.importorskip("interactions.models")
    from rest_framework.exceptions import AuthenticationFailed

    token, plaintext = make_access_token(name="revoked-token", revoked=True)
    assert token.is_valid is False

    request = APIRequestFactory().get(
        "/", HTTP_AUTHORIZATION=f"Bearer {plaintext}"
    )
    with pytest.raises(AuthenticationFailed):
        auth_mod.AccessTokenAuthentication().authenticate(request)

    denied = interactions_models.InteractionRun.objects.filter(
        status=interactions_models.InteractionRun.Status.DENIED,
    )
    assert denied.exists()
    run = denied.first()
    assert run.token_fingerprint == token.token_hash
    # denial 记录里绝不含明文（raw_request 已脱敏，contract）
    assert plaintext not in str(run.raw_request)


@pytest.mark.django_db
def test_cross_user_isolation(
    make_access_token: Callable[..., tuple[Any, str]],
    django_user_model: Any,
) -> None:
    """按 created_by 隔离：A 用户的 token 不属于 B 用户。"""
    from access_tokens.models import AccessToken

    token, _plaintext = make_access_token(name="owner-token")

    other = django_user_model.objects.create_user(
        username="other_access_user",
        email="other_access@example.com",
        password="otherpassword123",
    )

    assert AccessToken.objects.filter(created_by=other).count() == 0
    assert AccessToken.objects.filter(created_by=token.created_by).count() >= 1
