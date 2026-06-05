"""加密统一入口 —— Fernet 对称加密（implementation 起激活）。

激活背景：v21.0 引入 ProviderCredential 凭证模型需要真加密；
保持兼容路径：decrypt_value 对 plaintext legacy 值返回原值，
避免破坏 SystemSetting 等存量数据（26+ 历史调用方契约不破）。

设计要点：
- 密钥派生 `_derive_fernet_key()` 从 `FRIDAY_ENCRYPTION_KEY` 或 `SECRET_KEY`
  派生 32-byte Fernet key，encrypt_value / decrypt_value 共享同一 helper；
- decrypt_value 吞掉 InvalidToken / ValueError，返回原值（plaintext fallback）；
- None 透传路径保留（历史签名 `str` 但部分 nullable 字段会传入 None）。
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _derive_fernet_key() -> bytes:
    """从 settings.FRIDAY_ENCRYPTION_KEY 或 SECRET_KEY 派生 32-byte Fernet key。

    派生规则：
    1. 若 secret 已是合法 base64 url-safe 32-byte（解出 32 字节）→ 直接返回 secret 字节
    2. 否则 sha256(secret) → urlsafe_b64encode → 32-byte base64 key

    返回：Fernet 接受的 urlsafe base64 32-byte key（bytes）
    """
    secret = getattr(settings, "FRIDAY_ENCRYPTION_KEY", "") or settings.SECRET_KEY

    try:
        if len(base64.urlsafe_b64decode(secret)) == 32:
            return secret.encode() if isinstance(secret, str) else secret
        raise ValueError
    except Exception:
        key_bytes = hashlib.sha256(secret.encode()).digest()
        return base64.urlsafe_b64encode(key_bytes)


def encrypt_value(value: str) -> str:
    """Fernet 加密：返回 urlsafe base64 密文字符串。

    空字符串 / None 透传（保持与历史调用方签名兼容）。
    """
    if not value:
        return value

    fernet = Fernet(_derive_fernet_key())
    token = fernet.encrypt(value.encode())
    return token.decode()


def decrypt_value(encrypted_value: str) -> str:
    """Fernet 解密 + plaintext fallback。

    空字符串 / None 透传；若 encrypted_value 不是合法 Fernet token
    （InvalidToken / ValueError / 其他异常），原样返回以兼容 v21.0
    之前存入的明文数据（保护 26+ 历史 decrypt_value 调用方契约）。
    """
    if not encrypted_value:
        return encrypted_value

    try:
        fernet = Fernet(_derive_fernet_key())
        decrypted = fernet.decrypt(encrypted_value.encode())
        return decrypted.decode()
    except (InvalidToken, ValueError, Exception):
        return encrypted_value
