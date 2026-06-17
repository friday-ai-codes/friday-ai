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

# ---- 敏感键名集 ----
# 复刻 work_item_service._SECRET_KV_RE 键名集语义。匹配采用「分段边界」而非裸子串，
# 避免 token 误伤 LLM 域常见用量字段（prompt_tokens / tokens_used / max_tokens）。

# 单词级敏感段：要求与 key 的某个**整段**（按 _ / - / 空格 / camelCase 切分）相等才命中。
# 因此 access_token / token 命中，而 prompt_tokens（段为 "tokens"）/ max_tokens 不命中。
_SENSITIVE_WORD_SEGMENTS: Final[frozenset[str]] = frozenset(
    {
        "token",
        "secret",
        "password",
        "passwd",
        "credential",
        "authorization",
    }
)

# 复合敏感词：本身已足够特异，按归一化（去分隔符）后子串命中，覆盖 api_key / apikey /
# access_token / access-token 等书写变体；不会误伤计数类字段（prompttokens 不含这些复合词）。
_SENSITIVE_COMPOUND_TOKENS: Final[tuple[str, ...]] = (
    "apikey",  # api_key / api-key 归一化后形态
    "accesstoken",
    "refreshtoken",
    "accesskey",
    "secretkey",
    "privatekey",
    "encryptedconfig",
    "tokenhash",
    "appsecret",
)


def _key_segments(key: str) -> list[str]:
    """把键名切分为小写分段：先在 camelCase 边界插入分隔符，再按 ``_`` / ``-`` / 空格切分。

    例：``accessToken`` → ``["access", "token"]``；``prompt_tokens`` → ``["prompt", "tokens"]``。
    """
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", s)
    return [seg for seg in re.split(r"[\s_\-]+", s.lower()) if seg]


def _is_sensitive_key(key: str) -> bool:
    """敏感键判定：任一整段命中单词级敏感段，或归一化后含任一复合敏感词 → True。

    分段整词匹配避免 ``token`` 误伤 ``prompt_tokens`` / ``tokens_used`` / ``max_tokens``，
    同时 ``access_token`` / ``api_key`` / ``secret`` / ``password`` 仍命中。
    """
    segments = _key_segments(key)
    if any(seg in _SENSITIVE_WORD_SEGMENTS for seg in segments):
        return True
    normalized = "".join(segments)
    return any(token in normalized for token in _SENSITIVE_COMPOUND_TOKENS)


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
    - list / tuple / set / frozenset：逐元素递归并**归一化为 list**。
      Django ``JSONField`` 默认 ``json.dumps`` 会把 tuple 序列化为 JSON 数组而成功落库，
      若不递归则 tuple 内明文密钥会绕过脱敏落明文（违背 SC-4「绝不落明文」/ PAT-02）；
      set/frozenset 同样归一化递归后再交给 JSON 序列化，避免「可落库 + 未脱敏」泄漏路径。
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
    if isinstance(payload, str):
        return _redact_str(payload)[0]
    # str/bytes 已在上面单独处理；其余可迭代（list/tuple/set/frozenset）统一归一化为 list 后递归
    if isinstance(payload, (list, tuple, set, frozenset)):
        return [_redact_audit_payload(item) for item in payload]
    return payload
