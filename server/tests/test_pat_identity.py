"""IDENT-01/02/05 锁名测试桩：PAT 身份 + 前缀闸门 + PAT/JWT 共存（Nyquist Wave 0）。

在实现代码（07-02 认证改造 + settings 顺序、07-03 MCP 收紧）落地前，先用锁名测试把
「令牌即用户身份」契约固定下来：

- IDENT-01：有效 ``friday_pat_`` token → ``authenticate`` 返回 ``(token.created_by, token)``，
  ``request.user`` 为 owner（真实 User）。
- IDENT-02：``friday_pat_`` 前缀闸门——非 ``friday_pat_`` 的 Bearer（如 JWT）一律
  ``return None`` 让行给下一个认证类，绝不 raise（否则会吞掉 JWT）；已知前缀但不存在的
  token 则 ``raise AuthenticationFailed``（拒绝，而非静默放行）。
- IDENT-02（共存）：PAT 类排首位时，合法 JWT Bearer 仍能经 CookieJWT 认证（互不吞）。
- IDENT-05：吊销 token 经完整 DRF 链路返回 401。

集成用例不 mock 认证类——打实际受 ``IsAuthenticated`` 保护的 ``/me`` 端点，让 07-02
的 settings 认证类顺序成为被验证对象。

预期 RED（owner / 共存断言）直到 07-02 落地；JWT-only 与 401 断言可能已 GREEN。
任何状态下都不应出现 collection / import error。
"""

from __future__ import annotations

from typing import Any, Callable

import pytest

pytest.importorskip("access_tokens.authentication")

from access_tokens.models import PAT_PREFIX  # noqa: E402
from rest_framework.exceptions import AuthenticationFailed  # noqa: E402
from rest_framework.test import APIClient, APIRequestFactory  # noqa: E402

from access_tokens.authentication import AccessTokenAuthentication  # noqa: E402

pytestmark = pytest.mark.django_db


def test_valid_pat_authenticates_as_owner(
    make_access_token: Callable[..., tuple[Any, str]],
) -> None:
    """IDENT-01（unit）：有效 friday_pat_ token → 返回 (owner, token)。"""
    token, plaintext = make_access_token(name="owner-pat")
    assert plaintext.startswith(PAT_PREFIX)

    request = APIRequestFactory().get(
        "/", HTTP_AUTHORIZATION=f"Bearer {plaintext}"
    )
    result = AccessTokenAuthentication().authenticate(request)

    assert result is not None
    user, auth = result
    # request.user 应是令牌所有者（真实 User），request.auth 仍是 AccessToken（审计链不断）。
    assert user == token.created_by
    assert auth.token_hash == token.token_hash


def test_non_pat_bearer_falls_through() -> None:
    """IDENT-02（unit）：非 friday_pat_ 前缀的 Bearer → return None（让行 JWT，绝不 raise）。"""
    request = APIRequestFactory().get(
        "/", HTTP_AUTHORIZATION="Bearer not_a_friday_pat_value"
    )
    # 前缀闸门：PAT 类对非己前缀必须让行（返回 None），否则会吞掉后续 JWT 认证类。
    assert AccessTokenAuthentication().authenticate(request) is None


def test_unknown_pat_is_rejected_not_passed_through() -> None:
    """IDENT-02/IDENT-05（unit）：已知前缀但不存在的 token → raise（拒绝，非静默放行）。"""
    request = APIRequestFactory().get(
        "/", HTTP_AUTHORIZATION=f"Bearer {PAT_PREFIX}deadbeefdoesnotexist000000",
    )
    # friday_pat_ 前缀命中闸门 → 走 DB 查询 → 不存在 → 一律拒绝，绝不让行给 JWT。
    with pytest.raises(AuthenticationFailed):
        AccessTokenAuthentication().authenticate(request)


def test_pat_authenticates_protected_endpoint_as_owner(
    make_access_token: Callable[..., tuple[Any, str]],
    urls: Any,
) -> None:
    """IDENT-01/IDENT-02（integration）：有效 PAT 经完整 DRF 链路认证 /me 为 owner。"""
    token, plaintext = make_access_token(name="me-pat")

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {plaintext}")
    response = client.get(urls.me)

    # owner 身份经 IsAuthenticated 自然放行，返回该用户自身信息。
    assert response.status_code == 200
    assert response.data["username"] == token.created_by.username


def test_jwt_bearer_still_authenticates_with_pat_class_first(
    user: Any,
    urls: Any,
) -> None:
    """IDENT-02（integration）：PAT 类排首位时，合法 JWT Bearer 仍能被 CookieJWT 认证。"""
    from rest_framework_simplejwt.tokens import AccessToken as JWTAccessToken

    token_str = str(JWTAccessToken.for_user(user))

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_str}")
    response = client.get(urls.me)

    # PAT 类对非 friday_pat_ 前缀 return None 让行，CookieJWT 接住 JWT（PAT/JWT 互不吞）。
    assert response.status_code == 200
    assert response.data["username"] == user.username


def test_revoked_pat_rejected_through_chain(
    make_access_token: Callable[..., tuple[Any, str]],
    urls: Any,
) -> None:
    """IDENT-05（integration）：吊销 token 经完整链路调用受保护端点 → 401。"""
    _token, plaintext = make_access_token(name="revoked-pat", revoked=True)

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {plaintext}")
    response = client.get(urls.me)

    assert response.status_code == 401


def test_inactive_owner_pat_is_rejected(
    make_access_token: Callable[..., tuple[Any, str]],
) -> None:
    """CR-01（unit）：有效但所有者已停用的 PAT → raise AuthenticationFailed，

    且 best-effort 记一条 reason=owner_inactive 的 DENIED InteractionRun（与 JWT 路径
    simplejwt CHECK_USER_IS_ACTIVE 对齐，fail-closed）。
    """
    from interactions.models import InteractionRun

    token, plaintext = make_access_token(name="inactive-owner-pat")
    # token 本身非吊销/非过期（is_valid=True），仅把所有者停用。
    owner = token.created_by
    owner.is_active = False
    owner.save(update_fields=["is_active"])

    request = APIRequestFactory().get(
        "/", HTTP_AUTHORIZATION=f"Bearer {plaintext}"
    )
    with pytest.raises(AuthenticationFailed):
        AccessTokenAuthentication().authenticate(request)

    # best-effort 审计：记录一条 owner_inactive 的 DENIED run（fingerprint 为 hash）。
    denied = InteractionRun.objects.filter(
        token_fingerprint=token.token_hash,
        status=InteractionRun.Status.DENIED,
    )
    assert denied.exists()
    assert denied.latest("created_at").raw_request.get("reason") == "owner_inactive"


def test_inactive_owner_pat_rejected_through_chain(
    make_access_token: Callable[..., tuple[Any, str]],
    urls: Any,
) -> None:
    """CR-01（integration）：所有者已停用的有效 PAT 经完整 DRF 链路 → 401。"""
    token, plaintext = make_access_token(name="inactive-owner-chain")
    owner = token.created_by
    owner.is_active = False
    owner.save(update_fields=["is_active"])

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {plaintext}")
    response = client.get(urls.me)

    assert response.status_code == 401
