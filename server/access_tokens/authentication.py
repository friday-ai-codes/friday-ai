"""Friday Access Token 自定义认证（可被 work-item 外部入口复用）。
设计要点：
- 保持同步 ``authenticate`` + 同步 ORM（与 RunnerTokenAuthentication 一致），
 可被任意 view 直接挂 ``authentication_classes``。
- 有效 token 即放行，返回 ``(None, token)``；**不做任何 scope/项目/allowlist 校验**
 （ single token，）。
- 吊销/过期 token（**存在但 is_valid=False**）→ best-effort 记一条 DENIED
 ``InteractionRun`` + 一条 ``error`` 事件（仅存 fingerprint，绝不含明文，；），再 ``raise AuthenticationFailed``。
- **不存在** token（DoesNotExist）→ **不建 run**，仅 structlog warning，避免乱 token
 灌爆审计表（work-item Open Question 1：高熵 token 难枚举，best-effort 限范围）。
- ``last_used_at`` 节流更新（空或距今 >60s 才写），best-effort 不阻塞认证（Pitfall 3）。
注：denial 写入走 的 ``interactions.ledger`` 同步入口（``create_interaction_run``
/ ``record_event``）—— 认证类是同步上下文，必须用同步 ORM（Pitfall 2），且 ledger
内部写库前已统一过 ``redact_for_ledger`` 脱敏。
"""
from __future__ import annotations
from datetime import timedelta
import structlog
from django.utils import timezone
from interactions.ledger import create_interaction_run, record_event
from interactions.models import InteractionEvent, InteractionRun
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
 # 不存在 token 不建 run，仅 warning，防乱 token 灌爆审计表（Open Question 1）。
 logger.warning("access_token_denied", reason="not_found")
 raise AuthenticationFailed("无效的 Friday Access Token")
 if not token.is_valid:
 # 存在但吊销/过期：可审计的「废 token 调用」，写 DENIED run。
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
 """best-effort 记录「存在但无效」token 的被拒认证。
 走 ``interactions.ledger`` 同步入口写一条 DENIED ``InteractionRun`` + 一条
 ``error`` 事件；``token_fingerprint`` 永远是 hash（绝不含明文，），
 ``raw_request`` 由 ledger 内部统一脱敏。整体包 try/except 降级 warning、
 绝不抛出，不阻塞 ``AuthenticationFailed``（denial 写入 best-effort，
 威胁 T-）。
 """
 logger.warning("access_token_denied", reason=reason, fingerprint=fingerprint)
 try:
 run = create_interaction_run(
 token_fingerprint=fingerprint,
 source="access_token_auth",
 request_id=request.META.get("HTTP_X_REQUEST_ID", ""),
 status=InteractionRun.Status.DENIED,
 # raw_request 只含非敏感请求元数据（ledger 写库前再统一脱敏兜底）。
 raw_request={"reason": reason, "path": request.path},
 )
 record_event(
 run, InteractionEvent.EventType.ERROR, {"reason": reason}
 )
 except Exception:
 logger.warning("access_token_denial_record_failed", reason=reason)
