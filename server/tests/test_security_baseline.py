"""Security baseline tests for production-safe settings and webhook signature policy."""
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path
import pytest
from django.test import override_settings
from rest_framework import status
SERVER_DIR = Path(__file__).resolve.parents[1]
def _boot_django_with_env(extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
 env = os.environ.copy
 env.update(extra_env)
 env.setdefault("PYTHONPATH", str(SERVER_DIR))
 env.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
 return subprocess.run(
 [
 sys.executable,
 "-c",
 "import django; django.setup; print('settings-ok')",
 ],
 cwd=SERVER_DIR,
 env=env,
 capture_output=True,
 text=True,
 check=False,
 )
@pytest.mark.parametrize(
 ("env_overrides", "expected_error"),
 [
 (
 {
 "FRIDAY_PRODUCTION": "true",
 "DEBUG": "true",
 "SECRET_KEY": "prod-secret-key",
 "ALLOWED_HOSTS": "example.com",
 },
 "Production mode requires DEBUG=False",
 ),
 (
 {
 "FRIDAY_PRODUCTION": "true",
 "DEBUG": "false",
 "SECRET_KEY": "django-insecure-change-me-in-production",
 "ALLOWED_HOSTS": "example.com",
 },
 "Production mode requires a non-default SECRET_KEY",
 ),
 (
 {
 "FRIDAY_PRODUCTION": "true",
 "DEBUG": "false",
 "SECRET_KEY": "prod-secret-key",
 "ALLOWED_HOSTS": "*",
 },
 "Production mode requires explicit ALLOWED_HOSTS",
 ),
 ],
)
def test_production_security_guardrails_fail_fast(env_overrides: dict[str, str], expected_error: str) -> None:
 result = _boot_django_with_env(env_overrides)
 assert result.returncode != 0
 assert expected_error in (result.stdout + result.stderr)
def test_development_defaults_allow_bootstrap -> None:
 result = _boot_django_with_env(
 {
 "FRIDAY_PRODUCTION": "false",
 "DEBUG": "false",
 "SECRET_KEY": "dev-local-secret",
 "ALLOWED_HOSTS": "localhost,127.0.0.1",
 }
 )
 assert result.returncode == 0
 assert "settings-ok" in result.stdout
@pytest.mark.django_db
@override_settings(FEISHU_SIGNATURE_REQUIRED=True, FEISHU_ENCRYPT_KEY="")
def test_feishu_signature_required_rejects_missing_encrypt_key(api_client) -> None:
 response = api_client.post(
 "/api/feishu/card/callback/",
 {
 "action": {"value": {"action": "unknown_action"}},
 "open_message_id": "msg_1",
 },
 format="json",
 )
 assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
 assert "FEISHU_ENCRYPT_KEY" in response.data["detail"]
@pytest.mark.django_db
@override_settings(FEISHU_SIGNATURE_REQUIRED=True, FEISHU_ENCRYPT_KEY="test-encrypt-key")
def test_feishu_signature_missing_headers_returns_401(api_client) -> None:
 response = api_client.post(
 "/api/feishu/im/message/",
 {
 "header": {"event_type": "im.message.receive_v1", "event_id": "evt-1"},
 "event": {},
 },
 format="json",
 )
 assert response.status_code == status.HTTP_401_UNAUTHORIZED
 assert "签名头" in response.data["detail"]
@pytest.mark.django_db
@override_settings(FEISHU_SIGNATURE_REQUIRED=False, FEISHU_ENCRYPT_KEY="")
def test_feishu_signature_dev_bypass_allows_request(api_client) -> None:
 response = api_client.post(
 "/api/feishu/im/message/",
 {
 "header": {"event_type": "im.message.receive_v1", "event_id": "evt-2"},
 "event": {
 "message": {
 "chat_id": "chat_1",
 "message_id": "msg_1",
 "message_type": "text",
 "content": '{\"text\":\"hello\"}',
 },
 "sender": {"sender_id": {"open_id": "ou_test"}},
 },
 },
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["status"] == "ok"
