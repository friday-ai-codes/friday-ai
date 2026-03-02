"""Encryption utilities using Fernet symmetric encryption."""
import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
def _get_fernet_key -> bytes:
 """Get or derive a valid Fernet key from SECRET_KEY."""
 secret = settings.FRIDAY_ENCRYPTION_KEY or settings.SECRET_KEY
 # Check if it's already a valid Fernet key
 try:
 if len(base64.urlsafe_b64decode(secret)) == 32:
 return secret.encode if isinstance(secret, str) else secret
 except Exception:
 pass
 # Derive a key using SHA256
 key_bytes = hashlib.sha256(secret.encode).digest
 return base64.urlsafe_b64encode(key_bytes)
def get_fernet -> Fernet:
 """Get Fernet instance for encryption/decryption."""
 return Fernet(_get_fernet_key)
def encrypt_value(value: str) -> str:
 """Encrypt a string value.
 Args:
 value: Plain text value to encrypt
 Returns:
 Base64 encoded encrypted value
 """
 if not value:
 return value
 fernet = get_fernet
 encrypted = fernet.encrypt(value.encode)
 return encrypted.decode
def decrypt_value(encrypted_value: str) -> str:
 """Decrypt an encrypted value.
 Args:
 encrypted_value: Base64 encoded encrypted value
 Returns:
 Decrypted plain text value
 """
 if not encrypted_value:
 return encrypted_value
 fernet = get_fernet
 try:
 decrypted = fernet.decrypt(encrypted_value.encode)
 except InvalidToken:
 raise ValueError(
 "解密失败：密钥不匹配。可能是 FRIDAY_ENCRYPTION_KEY 或 SECRET_KEY 已变更，"
 "请重新配置加密字段的值"
 )
 return decrypted.decode
