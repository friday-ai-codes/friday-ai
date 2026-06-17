"""审计载荷脱敏入口（AUDIT-02）。

``_redact_audit_payload`` 在 ``AuditService.emit`` 入口内对 ``before`` / ``after`` /
``metadata`` 强制递归脱敏：key-name 命中 + 值级密钥/高熵模式兜底，绝不回填明文。
这是**纵深防御兜底**——即便调用方传明文也绝不落明文。

INV-3：本模块**不 import** ``services.sensitive_detect`` / ``delivery.services.work_item_service``
（那在更高耦合层，audit app 不应硬依赖跨层）；语义对齐既有范式，正则常量**复刻**到本模块。
脱敏策略来源对照（复刻，非 import）：
- key-name 命中集 ← ``work_item_service._SECRET_KV_RE`` 的键名集。
- 值级密钥正则 + 高熵 Shannon 判定 ← ``sensitive_detect._SECRET_PATTERNS`` /
  ``_HIGH_ENTROPY_TOKEN_RE`` / ``_shannon_entropy``。
- 递归只抹命中叶子、保留同载荷其余字段 ← ``sensitive_purge._redact_value``。
"""

from __future__ import annotations

import math
import re
from typing import Any, Final

__all__ = ["REDACTION_PLACEHOLDER", "_redact_audit_payload"]

# 脱敏占位符（替换命中的敏感键值 / 值级密钥叶子）。
REDACTION_PLACEHOLDER: Final[str] = "[已脱敏]"

# ---- 敏感键名集（小写归一化后子串命中）----
# 复刻 work_item_service._SECRET_KV_RE 键名集语义；归一化去分隔符后比较，命中
# api_key / apikey / access_token / access-token 等书写变体。
_SENSITIVE_KEY_TOKENS: Final[tuple[str, ...]] = (
    "token",
    "secret",
    "password",
    "passwd",
    "apikey",  # api_key / api-key 归一化后形态
    "accesstoken",
    "refreshtoken",
    "accesskey",
    "secretkey",
    "privatekey",
    "credential",
    "authorization",
    "encryptedconfig",
    "tokenhash",
    "appsecret",
)


def _normalize_key(key: str) -> str:
    """键名归一化：转小写 + 去除 ``_`` / ``-`` / 空格分隔符，便于变体子串匹配。"""
    return re.sub(r"[\s_\-]", "", key.lower())


def _is_sensitive_key(key: str) -> bool:
    """键名（归一化后）命中任一敏感 token 子串 → True。"""
    normalized = _normalize_key(key)
    return any(token in normalized for token in _SENSITIVE_KEY_TOKENS)


# ---- 值级密钥/高熵兜底（复刻 sensitive_detect._SECRET_PATTERNS，不 import）----
_SECRET_VALUE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"(?i)\b(api[_-]?key|secret|password|token)\b\s*[:=]\s*\S{8,}"),
)

# 高熵候选 token：长度 ≥ 40 的 base64/hex/url-safe 串（复刻 sensitive_detect）。
_HIGH_ENTROPY_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9+/=_\-]{40,}")
_HIGH_ENTROPY_THRESHOLD: Final[float] = 4.0  # Shannon 熵（bits/char）阈值，保守避免误报普通长串


def _shannon_entropy(s: str) -> float:
    """计算字符串的 Shannon 熵（bits/char），用于高熵密钥串判定（复刻 sensitive_detect）。"""
    if not s:
        return 0.0
    counts: dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _redact_str(value: str) -> tuple[str, bool]:
    """str 叶子值级脱敏：命中密钥正则 或（高熵 token 且 Shannon ≥ 阈值）→ 整串替换。

    返回 ``(新值, 是否命中)``。未命中原样返回 ``(value, False)``。
    """
    for pattern in _SECRET_VALUE_PATTERNS:
        if pattern.search(value):
            return REDACTION_PLACEHOLDER, True
    for token in _HIGH_ENTROPY_TOKEN_RE.findall(value):
        if _shannon_entropy(token) >= _HIGH_ENTROPY_THRESHOLD:
            return REDACTION_PLACEHOLDER, True
    return value, False


def _redact_audit_payload(payload: Any) -> Any:
    """递归脱敏审计载荷：key-name 命中整体抹值，值级密钥/高熵只抹命中叶子。

    - dict：``_is_sensitive_key(k)`` → 值整体替换占位符（无论类型）；否则对 v 递归。
    - list：逐元素递归。
    - str 叶子：走 ``_redact_str`` 值级判定。
    - 其余标量（int/bool/None/float）：原样返回。
    - 入参非 dict/list 时也安全（兜底按标量/str 处理）。

    保留结构与非敏感字段（参考 ``sensitive_purge._redact_value`` 只抹命中叶子）。
    """
    if isinstance(payload, dict):
        out: dict[Any, Any] = {}
        for k, v in payload.items():
            if isinstance(k, str) and _is_sensitive_key(k):
                out[k] = REDACTION_PLACEHOLDER
            else:
                out[k] = _redact_audit_payload(v)
        return out
    if isinstance(payload, list):
        return [_redact_audit_payload(item) for item in payload]
    if isinstance(payload, str):
        return _redact_str(payload)[0]
    return payload
