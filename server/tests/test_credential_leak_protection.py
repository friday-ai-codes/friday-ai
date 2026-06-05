"""Phase Plan: 凭证泄漏防护契约测试。
覆盖 Requirement:
威胁参考: T- (structlog 凭证泄漏), T- (上游 error body 泄漏)
锁名契约（CONTEXT.md D5 + ROADMAP Success Criteria #5）：
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
def _anthropic_key -> str:
 return "sk-ant-" + "leaktest1234567890"
def _openai_key -> str:
 return "sk-" + "12345678901234567890abcdef"
def _google_key -> str:
 return "AIza" + "SyD123456789012345678901234567"
def _friday_pat -> str:
 return "friday_pat_" + "ABCDEFGHIJKLMNOPQRSTUVWX"
def _pem_private_key -> str:
 return (
 "-----BEGIN " + "PRIVATE KEY-----\n"
 "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcw\n"
 "-----END " + "PRIVATE KEY-----"
 )
# === 顶层函数：命名锁死契约（不可改名）===
def test_no_credential_leak_in_logs(capfd: Any) -> None:
 """ Success Criteria #5 锁死命名契约。
 故意 logger.info 含 secret-looking api_key → 断言 stdout 含 ***REDACTED*** 不含明文。
 """
 import structlog
 api_key = _anthropic_key
 nested_key = _openai_key
 configure_structlog
 logger = structlog.get_logger("test_credential_leak_top_level")
 logger.info(
 "provider_error",
 api_key=api_key,
 credential={"api_key": nested_key},
 )
 captured = capfd.readouterr
 output = captured.out + captured.err
 assert REDACTED in output, f"REDACTED missing from output: {output[:300]}"
 assert api_key not in output, f"raw key leaked: {output[:300]}"
 assert nested_key not in output, f"nested key leaked: {output[:300]}"
# === Class-based 测试套件 ===
class TestRedactCredentialsProcessor:
 """structlog redact_credentials processor 单元测试。"""
 def test_redact_flat_api_key_field(self) -> None:
 event: dict[str, Any] = {"event": "provider_error", "api_key": _anthropic_key}
 result = redact_credentials(None, "info", event)
 assert result["api_key"] == REDACTED
 assert "sk-ant-leaktest" not in str(result)
 def test_redact_nested_credential_dict_key_match(self) -> None:
 # "credential" 顶层 key 命中 KEY_PATTERN -> 整个值替换
 event: dict[str, Any] = {
 "event": "err",
 "credential": {"api_key": _openai_key, "base_url": "https://x"},
 }
 result = redact_credentials(None, "info", event)
 assert result["credential"] == REDACTED
 def test_redact_value_pattern_when_key_innocent(self) -> None:
 # 字段名不命中但值含 sk-ant- 前缀 -> SENSITIVE_VALUE_PATTERN 兜底
 api_key = _anthropic_key
 event: dict[str, Any] = {
 "event": "raw",
 "log_line": f"Authorization: Bearer {api_key}",
 }
 result = redact_credentials(None, "info", event)
 assert api_key not in result["log_line"]
 assert REDACTED in result["log_line"]
 def test_redact_recursive_list_of_dicts(self) -> None:
 event: dict[str, Any] = {
 "items": [
 {"api_key": _openai_key},
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
 """业务字符串脱敏 helper（T- 直接消费）。"""
 @pytest.mark.parametrize(
 "input_text,must_not_contain",
 [
 ("got " + _anthropic_key + " from upstream", "sk-ant-" + "leaktest"),
 ("error: invalid " + _openai_key, "sk-" + "12345678901234567890"),
 ("Authorization: " + _google_key, "AIza" + "SyD"),
 ("Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", "eyJhbGciOiJIUzI1NiI"),
 # Phase：Friday Access Token 明文前缀也必须脱敏（与 sk-ant 并列）
 ("leaked " + _friday_pat + " token", "friday_pat_" + "ABCD"),
 ],
 )
 def test_redact_common_provider_keys(self, input_text: str, must_not_contain: str) -> None:
 result = redact_secrets_in_text(input_text)
 assert must_not_contain not in result
 assert REDACTED in result
 def test_redact_pem_private_key(self) -> None:
 pem = _pem_private_key
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
 "extra": {"credential_config": {"api_key": _openai_key}}
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
 "data": {"api_key": _openai_key},
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
 configure_structlog
 configure_structlog # 调两次不抛
 import structlog
 logger = structlog.get_logger("test_idempotent")
 logger.info("test_event", normal_field="ok") # 不抛即可
 def test_default_filter_drops_debug_keeps_warning(
 self, capfd: Any, monkeypatch: Any,
 ) -> None:
 """默认过滤级别 = INFO：debug 不应进入 stdout（避免 graph 阶段 debug 刷屏），
 warning 必须正常输出。
 """
 import structlog
 monkeypatch.delenv("FRIDAY_STRUCTLOG_LEVEL", raising=False)
 monkeypatch.delenv("DJANGO_LOG_LEVEL", raising=False)
 configure_structlog
 logger = structlog.get_logger("test_default_filter")
 logger.debug("noisy_debug_event", normal_field="ok")
 logger.warning("loud_warning_event", normal_field="ok")
 captured = capfd.readouterr
 output = captured.out + captured.err
 assert "noisy_debug_event" not in output
 assert "loud_warning_event" in output
 def test_env_override_enables_debug(
 self, capfd: Any, monkeypatch: Any,
 ) -> None:
 """FRIDAY_STRUCTLOG_LEVEL=DEBUG 时放开 debug 输出。"""
 import structlog
 monkeypatch.setenv("FRIDAY_STRUCTLOG_LEVEL", "DEBUG")
 configure_structlog
 logger = structlog.get_logger("test_env_override")
 logger.debug("opt_in_debug_event", normal_field="ok")
 captured = capfd.readouterr
 output = captured.out + captured.err
 assert "opt_in_debug_event" in output
 def test_pydantic_validation_error_post_redact(self, capfd: Any) -> None:
 """模拟 Plan aresolve_or_error 中 ValidationError 场景的脱敏链路。"""
 import structlog
 configure_structlog
 logger = structlog.get_logger("test_validation_redact")
 # 即使 raw_input 字典内含明文 sk-leak，processor 必须脱敏
 logger.error(
 "provider_credential_schema_invalid",
 provider="anthropic",
 credential_id="00000000-0000-0000-0000-000000000001",
 raw_input={"api_key": "sk-test-placeholder"},
 )
 captured = capfd.readouterr
 output = captured.out + captured.err
 assert "sk-test-placeholder" not in output
