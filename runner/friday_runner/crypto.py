from pathlib import Path
from cryptography.fernet import Fernet
KEY_FILE = Path.home / ".friday-runner" / "key"
def get_or_create_key -> bytes:
 if KEY_FILE.exists:
 return KEY_FILE.read_bytes
 KEY_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
 key = Fernet.generate_key
 KEY_FILE.write_bytes(key)
 KEY_FILE.chmod(0o600)
 return key
def encrypt_token(token: str) -> str:
 return Fernet(get_or_create_key).encrypt(token.encode).decode
def decrypt_token(encrypted: str) -> str:
 return Fernet(get_or_create_key).decrypt(encrypted.encode).decode
