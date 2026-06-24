"""contract 凭证泄漏防护契约测试。

覆盖 Requirement: contract
威胁参考: security mitigation (structlog 凭证泄漏), security mitigation (上游 error body 泄漏)

锁名契约（credential leak protection contract）：
- 本文件必含**顶层函数** `def test_no_credential_leak_in_logs(...)` —— 命名不可改
"""

from __future__ import annotations

from typing import Any

import pytest

from common.logging import (
    REDACTED,
    configure_structlog,
    redact_credentials,
    redact_secrets_in_text,
    sentry_before_send,
)


# === 顶层函数：命名锁死契约（不可改名）===


def test_no_credential_leak_in_logs(capfd: Any) -> None:
    """contract Success Criteria #5 锁死命名契约。

    故意 logger.info 含 api_key='sk-ant-leaktest12345' → 断言 stdout 含 ***REDACTED*** 不含明文。
    """
    import structlog

    configure_structlog()
    logger = structlog.get_logger("test_credential_leak_top_level")
    logger.info(
        "provider_error",
        api_key="sk-ant-leaktest12345",
        credential={"api_key": "sk-leaktest-nested"},
    )

    captured = capfd.readouterr()
    output = captured.out + captured.err
    assert REDACTED in output, f"REDACTED missing from output: {output[:300]}"
    assert "sk-ant-leaktest12345" not in output, f"raw key leaked: {output[:300]}"
    assert "sk-leaktest-nested" not in output, f"nested key leaked: {output[:300]}"


# === Class-based 测试套件 ===


class TestRedactCredentialsProcessor:
    """structlog redact_credentials processor 单元测试。"""

    def test_redact_flat_api_key_field(self) -> None:
        event: dict[str, Any] = {"event": "provider_error", "api_key": "sk-ant-leaktest12345"}
        result = redact_credentials(None, "info", event)
        assert result["api_key"] == REDACTED
        assert "sk-ant-leaktest" not in str(result)

    def test_redact_nested_credential_dict_key_match(self) -> None:
        # "credential" 顶层 key 命中 KEY_PATTERN -> 整个值替换
        event: dict[str, Any] = {
            "event": "err",
            "credential": {"api_key": "sk-leak-nested-xx", "base_url": "https://x"},
        }
        result = redact_credentials(None, "info", event)
        assert result["credential"] == REDACTED

    def test_redact_value_pattern_when_key_innocent(self) -> None:
        # 字段名不命中但值含 sk-ant- 前缀 -> SENSITIVE_VALUE_PATTERN 兜底
        event: dict[str, Any] = {
            "event": "raw",
            "log_line": "Authorization: Bearer sk-ant-leaktest1234567890",
        }
        result = redact_credentials(None, "info", event)
        assert "sk-ant-leaktest" not in result["log_line"]
        assert REDACTED in result["log_line"]

    def test_redact_recursive_list_of_dicts(self) -> None:
        event: dict[str, Any] = {
            "items": [
                {"api_key": "fixture-api-key-value"},
                {"name": "alice"},
            ]
        }
        result = redact_credentials(None, "info", event)
        assert result["items"][0]["api_key"] == REDACTED
        assert result["items"][1]["name"] == "alice"

    def test_redact_does_not_touch_non_sensitive_fields(self) -> None:
        event: dict[str, Any] = {
            "event": "ok",
            "user_id": 42,
            "duration_ms": 123,
            "ok": True,
        }
        result = redact_credentials(None, "info", event)
        assert result["user_id"] == 42
        assert result["duration_ms"] == 123
        assert result["ok"] is True


class TestRedactSecretsInText:
    """业务字符串脱敏 helper（security mitigation 直接消费）。"""

    @pytest.mark.parametrize(
        "input_text,must_not_contain",
        [
            ("got sk-ant-leaktest1234567890 from upstream", "sk-ant-leaktest"),
            ("error: invalid sk-12345678901234567890abcdef", "sk-12345678901234567890"),
            ("Authorization: AIzaSyD123456789012345678901234567", "AIzaSyD"),
            ("Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", "eyJhbGciOiJIUzI1NiI"),
            # Friday Access Token 明文前缀也必须脱敏（与 sk-ant 并列）
            ("leaked friday_pat_ABCDEFGHIJKLMNOPQRSTUVWX token", "friday_pat_ABCD"),
        ],
    )
    def test_redact_common_provider_keys(self, input_text: str, must_not_contain: str) -> None:
        result = redact_secrets_in_text(input_text)
        assert must_not_contain not in result
        assert REDACTED in result

    def test_redact_pem_private_key(self) -> None:
        pem = (
            "-----BEGIN " "PRIVATE KEY-----\n"
            "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcw\n"
            "-----END " "PRIVATE KEY-----"
        )
        result = redact_secrets_in_text(pem)
        assert "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcw" not in result
        assert REDACTED in result

    def test_redact_empty_or_none_safe(self) -> None:
        assert redact_secrets_in_text("") == ""

    def test_redact_does_not_touch_short_strings(self) -> None:
        # short "sk-x" < 20 字符 -> 不替换（避免误伤）
        result = redact_secrets_in_text("sk-x is a short literal")
        assert result == "sk-x is a short literal"


class TestSentryBeforeSend:
    """Sentry before_send 纯函数（本 phase 不接 sentry-sdk，仅契约保护）。"""

    def test_filters_frame_vars(self) -> None:
        fake_event: dict[str, Any] = {
            "exception": {
                "values": [
                    {
                        "stacktrace": {
                            "frames": [
                                {
                                    "function": "connect",
                                    "vars": {
                                        "api_key": "sk-leak",
                                        "host": "api.anthropic.com",
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        }
        cleaned = sentry_before_send(fake_event, {})
        assert cleaned is not None
        frame = cleaned["exception"]["values"][0]["stacktrace"]["frames"][0]
        assert frame["vars"]["api_key"] == REDACTED
        assert frame["vars"]["host"] == "api.anthropic.com"

    def test_filters_extra_section(self) -> None:
        fake_event: dict[str, Any] = {
            "extra": {"credential_config": {"api_key": "sk-leak-extra-xxxxxxxxxxxxx"}}
        }
        cleaned = sentry_before_send(fake_event, {})
        assert cleaned is not None
        # extra.credential_config 顶层 key "credential_config" 命中（含 "credential" 子串）
        assert (
            cleaned["extra"]["credential_config"] == REDACTED
            or "sk-leak-extra" not in str(cleaned)
        )

    def test_filters_breadcrumbs_data(self) -> None:
        fake_event: dict[str, Any] = {
            "breadcrumbs": {
                "values": [
                    {
                        "category": "auth",
                        "data": {"api_key": "sk-leak-bc-xxxxxxxxxxxxxxxxx"},
                    }
                ]
            }
        }
        cleaned = sentry_before_send(fake_event, {})
        assert cleaned is not None
        bc_data = cleaned["breadcrumbs"]["values"][0]["data"]
        assert bc_data["api_key"] == REDACTED

    def test_handles_empty_event_gracefully(self) -> None:
        cleaned = sentry_before_send({}, {})
        assert cleaned == {}


class TestConfigureStructlogIntegration:
    """configure_structlog 集成测试（capfd 验证实际 stdout 不含明文）。"""

    def test_configure_idempotent(self) -> None:
        configure_structlog()
        configure_structlog()  # 调两次不抛
        import structlog

        logger = structlog.get_logger("test_idempotent")
        logger.info("test_event", normal_field="ok")  # 不抛即可

    def test_default_filter_drops_debug_keeps_warning(
        self, capfd: Any, monkeypatch: Any,
    ) -> None:
        """默认过滤级别 = INFO：debug 不应进入 stdout（避免 graph 阶段 debug 刷屏），
        warning 必须正常输出。
        """
        import structlog

        monkeypatch.delenv("FRIDAY_STRUCTLOG_LEVEL", raising=False)
        monkeypatch.delenv("DJANGO_LOG_LEVEL", raising=False)

        configure_structlog()
        logger = structlog.get_logger("test_default_filter")
        logger.debug("noisy_debug_event", normal_field="ok")
        logger.warning("loud_warning_event", normal_field="ok")

        captured = capfd.readouterr()
        output = captured.out + captured.err
        assert "noisy_debug_event" not in output
        assert "loud_warning_event" in output

    def test_env_override_enables_debug(
        self, capfd: Any, monkeypatch: Any,
    ) -> None:
        """FRIDAY_STRUCTLOG_LEVEL=DEBUG 时放开 debug 输出。"""
        import structlog

        monkeypatch.setenv("FRIDAY_STRUCTLOG_LEVEL", "DEBUG")
        configure_structlog()
        logger = structlog.get_logger("test_env_override")
        logger.debug("opt_in_debug_event", normal_field="ok")

        captured = capfd.readouterr()
        output = captured.out + captured.err
        assert "opt_in_debug_event" in output

    def test_pydantic_validation_error_post_redact(self, capfd: Any) -> None:
        """模拟 plan aresolve_or_error 中 ValidationError 场景的脱敏链路。"""
        import structlog

        configure_structlog()
        logger = structlog.get_logger("test_validation_redact")
        # 即使 raw_input 字典内含明文 sk-leak，processor 必须脱敏
        logger.error(
            "provider_credential_schema_invalid",
            provider="anthropic",
            credential_id="00000000-0000-0000-0000-000000000001",
            raw_input={"api_key": "sk-leak-validation-xxxxxxxxxxxxxx"},
        )
        captured = capfd.readouterr()
        output = captured.out + captured.err
        assert "sk-leak-validation" not in output


@pytest.mark.django_db
class TestSystemLogSinkRedaction:
    """落库链路对称守护（LOG-02）：SystemLogEntry 落库行绝不含明文凭证。

    对称于上面的 stdout 守护——验证 ``enqueue_system_log`` 严格挂在
    ``redact_credentials`` 之后，落库内容已脱敏（脱敏契约命门）。
    """

    def test_structlog_event_persisted_redacted(self) -> None:
        """structlog 业务事件经处理链 fan-out 落库后无明文凭证。"""
        import json

        import structlog

        from system import log_sink
        from system.models import SystemLogEntry

        log_sink._reset_for_tests()
        configure_structlog()
        logger = structlog.get_logger("test_sink_redact")
        logger.info(
            "provider_error",
            api_key="sk-ant-leaktest12345",
            credential={"api_key": "sk-leaktest-nested"},
        )
        log_sink.flush_now()

        latest = SystemLogEntry.objects.order_by("-id").first()
        assert latest is not None
        serialized = json.dumps(
            {
                "message": latest.message,
                "payload": latest.payload,
                "correlation": latest.correlation,
                "event": latest.event,
            }
        )
        assert "sk-ant-leaktest12345" not in serialized
        assert "sk-leaktest-nested" not in serialized
        assert REDACTED in serialized

    def test_stdlib_record_persisted_redacted(self) -> None:
        """stdlib 日志经 RingBufferHandler fan-out 落库后无明文凭证。"""
        import json
        import logging

        from common.logging import RingBufferHandler
        from system import log_sink
        from system.models import SystemLogEntry

        log_sink._reset_for_tests()
        handler = RingBufferHandler()
        record = logging.LogRecord(
            name="django.request",
            level=logging.WARNING,
            pathname=__file__,
            lineno=1,
            msg="upstream said Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
            args=(),
            exc_info=None,
        )
        handler.emit(record)
        log_sink.flush_now()

        latest = SystemLogEntry.objects.order_by("-id").first()
        assert latest is not None
        serialized = json.dumps({"message": latest.message, "payload": latest.payload})
        assert "eyJhbGciOiJIUzI1NiI" not in serialized
        assert REDACTED in serialized
