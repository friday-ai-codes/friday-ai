"""Fernet 加密激活回归保护（contract）。覆盖 roundtrip / 空值 / Unicode / 长 JSON / plaintext legacy fallback。"""

import pytest


class TestEncryptionRoundtrip:
    """Fernet 对称加密激活后的 round-trip 与兼容契约测试。"""

    def test_roundtrip_basic(self) -> None:
        """基础 round-trip：encrypt 后 cipher != plain，decrypt(cipher) == plain。"""
        from common.encryption import decrypt_value, encrypt_value

        plain = "sk-ant-test-secret-value"
        cipher = encrypt_value(plain)

        assert cipher != plain, "激活后 encrypt_value 必须返回真密文，不再 pass-through"
        assert decrypt_value(cipher) == plain, "round-trip 必须还原原值"

    def test_empty_value_passthrough(self) -> None:
        """空值透传：encrypt_value('') == '' 且 decrypt_value('') == ''。"""
        from common.encryption import decrypt_value, encrypt_value

        assert encrypt_value("") == ""
        assert decrypt_value("") == ""

    def test_none_value_passthrough(self) -> None:
        """None 值兼容路径：保留 type:ignore 容忍度（历史签名是 str）。"""
        from common.encryption import decrypt_value, encrypt_value

        assert encrypt_value(None) is None  # type: ignore[arg-type]
        assert decrypt_value(None) is None  # type: ignore[arg-type]

    def test_unicode(self) -> None:
        """中文 + emoji + 转义字符 round-trip 正确。"""
        from common.encryption import decrypt_value, encrypt_value

        plain = "中文密钥 🔐 with emoji\n换行\t制表\"quote'"
        cipher = encrypt_value(plain)

        assert cipher != plain
        assert decrypt_value(cipher) == plain

    def test_long_json_payload(self) -> None:
        """200+ 字符 JSON 序列化字符串 round-trip 正确。"""
        import json

        from common.encryption import decrypt_value, encrypt_value

        payload = json.dumps(
            {
                "api_key": "sk-ant-" + "x" * 64,
                "base_url": "https://api.anthropic.com/v1",
                "model": "claude-sonnet-4-5",
                "metadata": {"nested": {"keys": list(range(20))}},
                "notes": "长 JSON payload 覆盖 ProviderCredential.encrypted_config 的典型大小",
            }
        )
        assert len(payload) > 200

        cipher = encrypt_value(payload)
        assert cipher != payload
        assert decrypt_value(cipher) == payload

    def test_plaintext_legacy_fallback(self) -> None:
        """**关键回归** —— 任意未加密字符串经 decrypt_value 后原样返回。

        保护 26+ 历史 decrypt_value 调用方契约（Space.claude_api_key_encrypted /
        SystemSetting.is_encrypted=True 等存量数据路径）。
        """
        from common.encryption import decrypt_value

        legacy_values = [
            "legacy-plain-value",
            "not-encrypted",
            "sk-ant-legacy-plain-key-stored-before-v21",
            "简体中文明文",
            "value with spaces and symbols !@#$%",
        ]
        for legacy in legacy_values:
            assert decrypt_value(legacy) == legacy, (
                f"plaintext fallback 契约破裂：decrypt_value({legacy!r}) 应原样返回"
            )

    @pytest.mark.parametrize(
        "plain",
        [
            "",
            "a",
            "x" * 10000,
            "包含 \n 换行 \t 与 'quote'",
            "sk-ant-" + "0" * 100,
            "🔐🚀✨",
        ],
    )
    def test_roundtrip_parametrized(self, plain: str) -> None:
        """参数化 round-trip：覆盖空 / 单字符 / 超长 / 特殊转义 / 前缀密钥 / 纯 emoji。"""
        from common.encryption import decrypt_value, encrypt_value

        cipher = encrypt_value(plain)
        if plain == "":
            assert cipher == ""
        else:
            assert cipher != plain, f"激活后 encrypt_value({plain!r}) 必须返回真密文"

        assert decrypt_value(cipher) == plain

    def test_encrypt_then_decrypt_across_calls(self) -> None:
        """多次 encrypt 同一明文 → 每次密文可能不同（Fernet 含时间戳/IV），但都能 decrypt 回原值。"""
        from common.encryption import decrypt_value, encrypt_value

        plain = "same-input-different-ciphers"
        cipher1 = encrypt_value(plain)
        cipher2 = encrypt_value(plain)

        # Fernet 密文包含 IV + 时间戳，两次加密结果应不同（概率上几乎必然）
        # 但即便相同也不算 bug——核心不变量是都能 decrypt 回原值
        assert decrypt_value(cipher1) == plain
        assert decrypt_value(cipher2) == plain
