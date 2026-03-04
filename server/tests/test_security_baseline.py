"""Security baseline tests for production-safe settings and webhook signature policy."""
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path
import pytest
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
