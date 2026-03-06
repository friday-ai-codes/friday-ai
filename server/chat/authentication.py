"""Chat API 自定义鉴权：X-Chat-Key header 密钥认证。
支持通过 X-Chat-Key header 提供密钥进行认证，
与 JWT Bearer token 并行使用，任一通过即可。
密钥值存储在 SystemSetting 中，支持加密存储。
"""
import hmac
from django.contrib.auth.models import AnonymousUser
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from common.encryption import decrypt_value
from system.models import SettingKeys, SystemSetting
class ChatKeyAuthentication(BaseAuthentication):
 """通过 X-Chat-Key header 认证。
 认证逻辑：
 - header 不存在 → 返回 None（交给下一个 authenticator）
 - 配置密钥不存在 → 返回 None
 - header 值匹配 → 返回 (AnonymousUser, "chat-key")
 - header 值不匹配 → raise AuthenticationFailed
 注意：authenticate 是同步方法（DRF BaseAuthentication 要求），
 在 async view 中 DRF/adrf 会自动用 sync_to_async 包装。
 """
 def authenticate(self, request) -> tuple | None:
 """验证 X-Chat-Key header。"""
 chat_key = request.META.get("HTTP_X_CHAT_KEY")
 if not chat_key:
 return None
 # 从 SystemSetting 获取配置密钥
 try:
 setting = SystemSetting.objects.get(key=SettingKeys.CHAT_KEY)
 except SystemSetting.DoesNotExist:
 return None
 if not setting.value:
 return None
 # 解密（如果加密存储）
 expected_key = (
 decrypt_value(setting.value)
 if setting.is_encrypted
 else setting.value
 )
 # 常量时间比较，防止 timing attack
 if hmac.compare_digest(chat_key, expected_key):
 return (AnonymousUser, "chat-key")
 raise AuthenticationFailed("无效的 Chat Key")
 def authenticate_header(self, request) -> str:
 """返回 WWW-Authenticate header 值。"""
 return "X-Chat-Key"
