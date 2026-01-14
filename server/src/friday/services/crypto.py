"""Cryptography service for credential encryption."""
from cryptography.fernet import Fernet
from ..config import get_settings
settings = get_settings
# Initialize Fernet cipher with SECRET_KEY
# If SECRET_KEY is not a valid Fernet key, generate one from it
_key = settings.SECRET_KEY
if len(_key) != 44 or not _key.endswith("="):
 # Derive a Fernet-compatible key from the secret
 import base64
 import hashlib
 hash_bytes = hashlib.sha256(_key.encode).digest
 _key = base64.urlsafe_b64encode(hash_bytes).decode
cipher = Fernet(_key.encode)
def encrypt_value(value: str) -> str:
 """Encrypt a sensitive string value.
 Args:
 value: Plain text value to encrypt
 Returns:
 Encrypted value as base64 string
 """
 return cipher.encrypt(value.encode).decode
def decrypt_value(encrypted: str) -> str:
 """Decrypt an encrypted string value.
 Args:
 encrypted: Encrypted value (base64 string)
 Returns:
 Decrypted plain text value
 """
 return cipher.decrypt(encrypted.encode).decode