"""OIDC 服务：Discovery、Token Exchange、UserInfo、JIT Provisioning。"""

import secrets
from urllib.parse import urlencode

import httpx
import structlog
from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing

from accounts.models import UserSource
from common.encryption import decrypt_value
from identity.models import OIDCIdentity, OIDCProvider, OIDCProviderKind

logger = structlog.get_logger(__name__)

User = get_user_model()


async def fetch_oidc_discovery(issuer_url: str) -> dict[str, str]:
    """从 .well-known/openid-configuration 获取 Provider 配置。

    Args:
        issuer_url: OIDC Provider 的 Issuer URL

    Returns:
        包含 authorization_endpoint, token_endpoint, userinfo_endpoint 的字典

    Raises:
        ValueError: Discovery 请求失败
    """
    discovery_url = f"{issuer_url.rstrip('/')}/.well-known/openid-configuration"
    logger.info("oidc_discovery_fetch", discovery_url=discovery_url)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(discovery_url)
            response.raise_for_status()
            config = response.json()
    except httpx.HTTPStatusError as e:
        logger.error("oidc_discovery_failed", status=e.response.status_code, url=discovery_url)
        raise ValueError(f"Discovery 请求失败: HTTP {e.response.status_code}") from e
    except httpx.RequestError as e:
        logger.error("oidc_discovery_error", error=str(e), url=discovery_url)
        raise ValueError(f"Discovery 请求错误: {e}") from e

    return {
        "authorization_endpoint": config.get("authorization_endpoint", ""),
        "token_endpoint": config.get("token_endpoint", ""),
        "userinfo_endpoint": config.get("userinfo_endpoint", ""),
    }


def generate_state() -> str:
    """生成 32 字节随机 state 值。"""
    return secrets.token_urlsafe(32)


def create_signed_state(state: str, redirect_uri: str, provider_id: str) -> str:
    """创建签名的 state 数据。"""
    return signing.dumps({
        "state": state,
        "redirect_uri": redirect_uri,
        "provider_id": provider_id,
    })


def verify_signed_state(signed_value: str, max_age: int = 600) -> dict[str, str]:
    """验证签名的 state 数据。

    Args:
        signed_value: 签名的 state 字符串
        max_age: 最大有效期（秒），默认 600（10 分钟）

    Returns:
        解码后的 state 数据字典

    Raises:
        signing.BadSignature: 签名无效
        signing.SignatureExpired: 签名已过期
    """
    return signing.loads(signed_value, max_age=max_age)


def build_authorize_url(
    provider: OIDCProvider,
    state: str,
    callback_url: str,
    prompt: str | None = None,
) -> str:
    """构造 OIDC Provider 授权 URL。

    Args:
        provider: OIDC Provider 实例
        state: CSRF state 值
        callback_url: 回调 URL
        prompt: OIDC `prompt` 参数（如 `login` / `consent` / `select_account`）。
            用于强制 IdP 重新交互，典型场景是用户主动退出后下一次登录，
            避免 SSO 静默放行带来的"点退出无效"观感。

    Returns:
        完整的授权 URL
    """
    params: dict[str, str] = {
        "client_id": provider.client_id,
        "response_type": "code",
        "scope": provider.scopes,
        "redirect_uri": callback_url,
        "state": state,
    }
    if prompt:
        params["prompt"] = prompt
    return f"{provider.authorization_endpoint}?{urlencode(params)}"


def _request_base_url(request: object) -> str:
    """从当前请求推断站点基础 URL（scheme://host[:port]）。

    依赖 Host 头（经 nginx 代理时为 proxy_set_header 透传的原始访问地址）。
    推断失败（无 request / Host 非法）返回空串，由调用方继续回退。
    """
    build = getattr(request, "build_absolute_uri", None)
    if build is None:
        return ""
    try:
        return str(build("/")).rstrip("/")
    except Exception:
        return ""


async def aresolve_site_base_url(fallback: str, request: object | None = None) -> str:
    """解析站点基础 URL：站点 Host 设置 → 当前请求 Host → 给定回退值。

    1. 「站点 Host」（site_host）系统设置：管理员显式配置的外部访问地址
       （如 https://friday.example.com），优先级最高。
    2. 当前请求的 Host：未配置时直接取用户实际访问的地址，开箱即用。
    3. fallback：无请求上下文时回退 env（FRIDAY_BASE_URL / FRIDAY_FRONTEND_URL）。

    site_host 归一化：去首尾空白、去尾斜杠；无 scheme 时补 http://（用户在
    输入框常省略 scheme，缺 scheme 的 redirect_uri 会被 IdP 拒绝或当相对路径解析）。
    """
    from system.models import SettingKeys
    from system.settings_service import aget_setting

    site_host = (await aget_setting(SettingKeys.SITE_HOST, "")).strip().rstrip("/")
    if site_host and "://" not in site_host:
        site_host = f"http://{site_host}"
    if site_host:
        return site_host

    request_base = _request_base_url(request) if request is not None else ""
    return request_base or fallback


async def build_callback_url(request: object) -> str:
    """构建 OIDC 回调 URL（redirect_uri）。

    站点 Host 设置 → 当前请求 Host → FRIDAY_BASE_URL 配置。
    """
    base_url = await aresolve_site_base_url(
        getattr(settings, "FRIDAY_BASE_URL", "http://localhost:8000"),
        request=request,
    )
    return f"{base_url}/api/oidc/callback/"


async def exchange_code_for_tokens(
    provider: OIDCProvider, code: str, redirect_uri: str
) -> dict[str, object]:
    """用授权码换取 token。

    Args:
        provider: OIDC Provider 实例
        code: 授权码
        redirect_uri: 回调 URL

    Returns:
        Token 响应 JSON

    Raises:
        ValueError: Token 交换失败
    """
    # 解密 client_secret
    client_secret = ""
    if provider.client_secret_encrypted:
        client_secret = decrypt_value(provider.client_secret_encrypted)

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": provider.client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }

    logger.info("oidc_token_exchange", provider=provider.name, token_endpoint=provider.token_endpoint)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                provider.token_endpoint,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        error_body = e.response.text
        logger.error(
            "oidc_token_exchange_failed",
            status=e.response.status_code,
            body=error_body,
            provider=provider.name,
        )
        raise ValueError(f"Token 交换失败: HTTP {e.response.status_code}") from e
    except httpx.RequestError as e:
        logger.error("oidc_token_exchange_error", error=str(e), provider=provider.name)
        raise ValueError(f"Token 交换请求错误: {e}") from e


async def fetch_userinfo(
    provider: OIDCProvider, access_token: str
) -> dict[str, object]:
    """获取 OIDC 用户信息。

    Args:
        provider: OIDC Provider 实例
        access_token: Provider 颁发的 access_token

    Returns:
        UserInfo JSON

    Raises:
        ValueError: UserInfo 请求失败
    """
    if not provider.userinfo_endpoint:
        logger.warning("oidc_no_userinfo_endpoint", provider=provider.name)
        return {}

    logger.info("oidc_userinfo_fetch", provider=provider.name)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                provider.userinfo_endpoint,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(
            "oidc_userinfo_failed",
            status=e.response.status_code,
            provider=provider.name,
        )
        raise ValueError(f"UserInfo 请求失败: HTTP {e.response.status_code}") from e
    except httpx.RequestError as e:
        logger.error("oidc_userinfo_error", error=str(e), provider=provider.name)
        raise ValueError(f"UserInfo 请求错误: {e}") from e


_PROVIDER_KIND_TO_USER_SOURCE: dict[str, str] = {
    OIDCProviderKind.FEISHU.value: UserSource.FEISHU.value,
    OIDCProviderKind.GOOGLE.value: UserSource.GOOGLE.value,
    OIDCProviderKind.GITHUB.value: UserSource.GITHUB.value,
    OIDCProviderKind.OTHER.value: UserSource.OIDC_OTHER.value,
}


def _provider_kind_to_user_source(kind: str) -> str:
    """OIDC Provider 类型 → 用户来源 source。"""
    return _PROVIDER_KIND_TO_USER_SOURCE.get(kind, UserSource.OIDC_OTHER.value)


async def _find_unique_username(base_username: str) -> str:
    """查找不冲突的用户名，必要时加数字后缀。"""
    username = base_username
    suffix = 2
    while await sync_to_async(User.objects.filter(username=username).exists)():
        username = f"{base_username}_{suffix}"
        suffix += 1
    return username


async def jit_provision_user(
    provider: OIDCProvider, userinfo: dict[str, object]
) -> tuple[object, bool]:
    """JIT（Just-In-Time）用户创建/关联。

    查找逻辑：
    1. 已有 OIDCIdentity 映射 → 直接返回关联用户
    2. 已有同 email 用户 → 关联到已有用户
    3. 全新用户 → 创建用户 + 建立映射

    Args:
        provider: OIDC Provider 实例
        userinfo: OIDC UserInfo 数据

    Returns:
        (user, is_new_user) 元组
    """
    sub = str(userinfo.get("sub", ""))
    email = str(userinfo.get("email", ""))

    logger.info("oidc_jit_provision", provider=provider.name, sub=sub, email=email)

    # 1. 查找已有 OIDC 身份映射
    identity = await (
        OIDCIdentity.objects.filter(provider=provider, sub=sub)
        .select_related("user")
        .afirst()
    )
    if identity:
        logger.info("oidc_existing_identity", user=str(identity.user))
        return identity.user, False

    # 2. 查找同 email 用户
    user = None
    if email:
        user = await sync_to_async(
            User.objects.filter(email=email).first
        )()

    is_new_user = False
    if not user:
        # 3. 创建新用户
        preferred_username = str(userinfo.get("preferred_username", ""))
        base_username = preferred_username or email.split("@")[0] if email else f"oidc_{sub[:8]}"
        username = await _find_unique_username(base_username)
        display_name = str(userinfo.get("name", ""))

        user = await sync_to_async(User.objects.create_user)(
            username=username,
            email=email,
            display_name=display_name,
            source=_provider_kind_to_user_source(provider.kind),
        )
        # OIDC 用户无密码
        user.set_unusable_password()
        await user.asave(update_fields=["password"])
        is_new_user = True
        logger.info("oidc_user_created", username=username, email=email)
    else:
        logger.info("oidc_email_matched", user=str(user), email=email)

    # 建立 OIDC 身份映射
    await OIDCIdentity.objects.acreate(
        user=user,
        provider=provider,
        sub=sub,
        email=email,
        raw_claims=userinfo,
    )

    return user, is_new_user
