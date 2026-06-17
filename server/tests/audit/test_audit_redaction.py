"""审计脱敏入口测试（AUDIT-02，SC-4）。

覆盖 key-name 命中 / 值级密钥 / 高熵 / 嵌套只抹叶子 / 非 str 标量保留，
证明 ``_redact_audit_payload`` 绝不回填明文。
"""

from audit.services.redaction import REDACTION_PLACEHOLDER, _redact_audit_payload

# 长度 ≥ 40 的高熵 base64 串（字符分布多样，Shannon 远超 4.0），不含 key=value 赋值形。
_HIGH_ENTROPY_VALUE = "aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY2zA4bC6dE8fG0"


def test_placeholder_value():
    """占位符为约定的 [已脱敏]。"""
    assert REDACTION_PLACEHOLDER == "[已脱敏]"


def test_key_name_hit():
    """敏感键名命中 → 值整体替换占位符；非敏感键保留。"""
    payload = {
        "token": "abc",
        "secret": "abc",
        "password": "abc",
        "api_key": "abc",
        "access_token": "abc",
        "private_key": "abc",
        "credential": "abc",
        "encrypted_config": "abc",
        "token_hash": "abc",
        "name": "alice",
    }
    out = _redact_audit_payload(payload)
    for key in (
        "token",
        "secret",
        "password",
        "api_key",
        "access_token",
        "private_key",
        "credential",
        "encrypted_config",
        "token_hash",
    ):
        assert out[key] == REDACTION_PLACEHOLDER, f"敏感键 {key} 未脱敏"
    assert out["name"] == "alice"


def test_sensitive_keys_still_redacted():
    """MEDIUM-2：真正的敏感键名仍命中脱敏（分段/复合匹配不放过）。"""
    payload = {
        "token": "x",
        "access_token": "x",
        "refresh_token": "x",
        "api_key": "x",
        "apiKey": "x",
        "secret": "x",
        "password": "x",
        "app_secret": "x",
        "private_key": "x",
        "encrypted_config": "x",
    }
    out = _redact_audit_payload(payload)
    for key in payload:
        assert out[key] == REDACTION_PLACEHOLDER, f"敏感键 {key} 未脱敏"


def test_benign_count_keys_not_redacted():
    """MEDIUM-2：LLM 用量/计数类字段（含 token 子串）不应被过度脱敏。"""
    payload = {
        "prompt_tokens": 1500,
        "tokens_used": 42,
        "max_tokens": 4096,
        "completion_tokens": 300,
        "promptTokens": 1500,
    }
    out = _redact_audit_payload(payload)
    assert out == payload


def test_value_level_secret():
    """键名未命中但值命中密钥模式（GitHub token / 私钥块）→ 值被替换。"""
    gh = _redact_audit_payload({"note": "ghp_AAAABBBBCCCCDDDDEEEE1234"})
    assert gh["note"] == REDACTION_PLACEHOLDER

    pem = _redact_audit_payload(
        {"blob": "-----BEGIN RSA PRIVATE KEY-----\nMIIBderp\n-----END RSA PRIVATE KEY-----"}
    )
    assert pem["blob"] == REDACTION_PLACEHOLDER


def test_high_entropy_value():
    """含 ≥40 字符高熵 base64 串的值被替换。"""
    out = _redact_audit_payload({"blob": _HIGH_ENTROPY_VALUE})
    assert out["blob"] == REDACTION_PLACEHOLDER


def test_nested_structure():
    """dict/list 嵌套含敏感叶子 → 只命中叶子被抹，同载荷非敏感字段保留。"""
    payload = {
        "user": "alice",
        "creds": {"password": "p", "kept": "ok"},
        "items": [{"api_key": "x"}, {"label": "safe"}],
    }
    out = _redact_audit_payload(payload)
    assert out["user"] == "alice"
    assert out["creds"]["password"] == REDACTION_PLACEHOLDER
    assert out["creds"]["kept"] == "ok"
    assert out["items"][0]["api_key"] == REDACTION_PLACEHOLDER
    assert out["items"][1]["label"] == "safe"


def test_non_string_scalars_preserved():
    """非敏感键的 int/bool/None/float 标量原样保留。"""
    payload = {"count": 3, "enabled": True, "missing": None, "ratio": 1.5}
    out = _redact_audit_payload(payload)
    assert out == {"count": 3, "enabled": True, "missing": None, "ratio": 1.5}


def test_tuple_value_recursed_and_normalized():
    """MEDIUM-1：tuple 值递归脱敏并归一化为 list，明文密钥不绕过（PAT-02 / SC-4）。"""
    out = _redact_audit_payload({"data": ("ghp_AAAABBBBCCCCDDDDEEEE1234",)})
    assert out["data"] == [REDACTION_PLACEHOLDER]
    assert isinstance(out["data"], list)


def test_set_value_recursed_and_normalized():
    """MEDIUM-1：set/frozenset 值递归脱敏并归一化为 list（避免「可落库+未脱敏」泄漏）。"""
    out = _redact_audit_payload({"data": {"ghp_AAAABBBBCCCCDDDDEEEE1234"}})
    assert out["data"] == [REDACTION_PLACEHOLDER]
    assert isinstance(out["data"], list)

    fout = _redact_audit_payload({"data": frozenset({"ghp_AAAABBBBCCCCDDDDEEEE1234"})})
    assert fout["data"] == [REDACTION_PLACEHOLDER]
