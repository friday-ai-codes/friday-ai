"""Friday Access Token 自定义认证（可被 work-item 外部入口复用）。
设计要点：
- 保持同步 ``authenticate`` + 同步 ORM（与 RunnerTokenAuthentication 一致），
 可被任意 view 直接挂 ``authentication_classes``。
- 有效 token 即放行，返回 ``(None, token)``；**不做任何 scope/项目/allowlist 校验**
 （ single token，）。
- 吊销/过期/不存在 token 一律 ``raise AuthenticationFailed``，并 best-effort 记一条
 DENIED ``InteractionRun``（仅存 fingerprint，绝不含明文，；）。
- ``last_used_at`` 节流更新（空或距今 >60s 才写），best-effort 不阻塞认证（Pitfall 3）。
注：DENIED 的完整事件级 ledger wiring（脱敏 helper / 子事件）由 接入；本类
仅做不依赖 的最小直写（interactions.models 来自 ）。
"""
from __future__ import annotations
from datetime import timedelta
import structlog
from django.utils import timezone
from interactions.models import InteractionRun
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request
from runners.models import hash_token
from .models import AccessToken
logger = structlog.get_logger(__name__)
# last_used_at 节流窗口：同一 token 60s 内只写一次，避免每请求写放大。
_LAST_USED_THROTTLE = timedelta(seconds=60)
class AccessTokenAuthentication(BaseAuthentication):
 """通过 Bearer token 认证 Friday Access Token。
 返回 ``(None, token)`` —— request.user 为 None，request.auth 为 AccessToken 实例。
 """
 def authenticate(self, request: Request) -> tuple[None, AccessToken] | None:
 auth_header = request.META.get("HTTP_AUTHORIZATION", "")
 if not auth_header.startswith("Bearer "):
 return None
 plaintext = auth_header[7:]
 if not plaintext:
 return None
 fingerprint = hash_token(plaintext)
 try:
 token = AccessToken.objects.get(token_hash=fingerprint)
 except AccessToken.DoesNotExist:
 self._record_denial(request, fingerprint="", reason="not_found")
 raise AuthenticationFailed("无效的 Friday Access Token")
 if not token.is_valid:
 self._record_denial(
 request, fingerprint=token.token_hash, reason="revoked_or_expired"
 )
 raise AuthenticationFailed("Token 已吊销或已过期")
 #：有效即放行，不做任何 scope/项目/allowlist 校验。
 self._touch_last_used(token)
 return (None, token)
 def _touch_last_used(self, token: AccessToken) -> None:
 """节流更新 last_used_at（best-effort，失败不阻塞认证返回，Pitfall 3）。"""
 now = timezone.now
 if token.last_used_at is not None and now - token.last_used_at < _LAST_USED_THROTTLE:
 return
 try:
 token.last_used_at = now
 token.save(update_fields=["last_used_at"])
 except Exception:
 logger.warning("access_token_touch_last_used_failed", fingerprint=token.token_hash)
 def _record_denial(self, request: Request, *, fingerprint: str, reason: str) -> None:
 """best-effort 记录被拒认证：structlog warning + DENIED InteractionRun。
 绝不含明文（仅存 fingerprint）；包 try/except 不抛，不阻塞 AuthenticationFailed。
 完整事件级 ledger wiring 由 替换（本实现仅依赖 的 interactions.models）。
 """
 logger.warning("access_token_denied", reason=reason, fingerprint=fingerprint)
 try:
 InteractionRun.objects.create(
 token_fingerprint=fingerprint,
 source="access_token_auth",
 status=InteractionRun.Status.DENIED,
 # raw_request 不含明文（仅 reason + 请求路径）。
 raw_request={"reason": reason, "path": request.path},
 )
 except Exception:
 logger.warning("access_token_denial_record_failed", reason=reason)
