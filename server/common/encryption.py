"""Encryption utilities — disabled for internal network deployment.
All values are stored and returned as plain text.
The encrypt_value / decrypt_value functions are kept as pass-throughs
so that existing call sites continue to work without modification.
"""
def encrypt_value(value: str) -> str:
 """Return *value* unchanged (encryption disabled)."""
 return value
def decrypt_value(encrypted_value: str) -> str:
 """Return *encrypted_value* unchanged (encryption disabled).
 For backward compatibility with data that was previously encrypted
 via Fernet, we attempt to decrypt it first. If the decryption fails
 (key mismatch, or the value was never encrypted), we simply return
 the raw value.
 """
 if not encrypted_value:
 return encrypted_value
 try:
 import base64
 import hashlib
 from cryptography.fernet import Fernet
 from django.conf import settings
 secret = getattr(settings, "FRIDAY_ENCRYPTION_KEY", "") or settings.SECRET_KEY
 try:
 if len(base64.urlsafe_b64decode(secret)) == 32:
 key = secret.encode if isinstance(secret, str) else secret
 else:
 raise ValueError
 except Exception:
 key_bytes = hashlib.sha256(secret.encode).digest
 key = base64.urlsafe_b64encode(key_bytes)
 decrypted = Fernet(key).decrypt(encrypted_value.encode)
 return decrypted.decode
 except Exception:
 return encrypted_value
