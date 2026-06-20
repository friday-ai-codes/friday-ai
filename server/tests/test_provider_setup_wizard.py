"""Phase 3: 首启向导供应商一键配置编排端点测试。

覆盖 Requirement: PROV-01（密文落库系统级凭证）、PROV-04（健康校验 + 可操作提示）、
PROV-05（设系统默认 + 绑定 Claude Code）、SEC-02（Fernet 密文存储）。

权限：IsSuperUser。httpx 上游用 respx mock；端点为 adrf async，但用 DRF APIClient 同步驱动。
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from common.encryption import decrypt_value

WIZARD_URL = "/api/providers/setup-wizard/"
MESSAGES = "https://api.anthropic.com/v1/messages"
_OK_MESSAGE = {"type": "message", "content": []}

User = get_user_model()


def _superuser():
    return User.objects.create_superuser(username="wiz-admin", password="x")


def _payload(**overrides):
    data = {
        "api_key": "sk-ant-wizardtest-1234567890",
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-4-5",
        "context_length": 200000,
        "supports_vision": True,
    }
    data.update(overrides)
    return data


@pytest.mark.django_db(transaction=True)
class TestProviderSetupWizard:
    @respx.mock
    def test_creates_encrypted_default_and_binds_claude_code(self) -> None:
        """PROV-01/05 + SEC-02：成功路径密文落库 + 设默认 + 绑 Claude Code。"""
        from system.models import ProviderCredential, SettingKeys, SystemSetting

        respx.post(MESSAGES).mock(return_value=httpx.Response(200, json=_OK_MESSAGE))

        client = APIClient()
        client.force_authenticate(user=_superuser())
        resp = client.post(WIZARD_URL, _payload(), format="json")
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["provider_type"] == "anthropic"
        assert body["is_default"] is True
        assert body["claude_code_bound"] is True
        assert body["default_model"] == "claude-sonnet-4-5"

        cred = ProviderCredential.objects.get(
            scope="system", provider_type="anthropic", name="default"
        )
        assert cred.is_default is True
        assert cred.is_active is True
        assert cred.default_model == "claude-sonnet-4-5"
        # SEC-02：encrypted_config 为密文（不含明文 api_key），可被 Fernet 解回
        assert "sk-ant-wizardtest-1234567890" not in cred.encrypted_config
        decrypted = json.loads(decrypt_value(cred.encrypted_config))
        assert decrypted["api_key"] == "sk-ant-wizardtest-1234567890"
        assert decrypted["base_url"] == "https://api.anthropic.com"

        # PROV-05：Claude Code 配置写入指向该凭证 + 三档映射
        cc = SystemSetting.objects.get(key=SettingKeys.CLAUDE_CODE_CONFIG)
        cc_value = json.loads(cc.value)
        assert cc_value["credential_id"] == str(cred.id)
        assert cc_value["model_mapping"]["opus"] == "claude-sonnet-4-5"
        assert cc_value["model_mapping"]["sonnet"] == "claude-sonnet-4-5"
        assert cc_value["model_mapping"]["haiku"] == "claude-sonnet-4-5"

    @respx.mock
    def test_health_fail_no_persist_actionable(self) -> None:
        """PROV-04：健康校验失败返回 400 + 可操作提示，且不落任何凭证。"""
        from system.models import ProviderCredential

        respx.post(MESSAGES).mock(
            return_value=httpx.Response(401, json={"error": "invalid api key"})
        )

        client = APIClient()
        client.force_authenticate(user=_superuser())
        resp = client.post(WIZARD_URL, _payload(), format="json")
        assert resp.status_code == 400, resp.content
        body = resp.json()
        assert body["code"] == "provider_health_failed"
        assert "请检查" in body["detail"]
        assert not ProviderCredential.objects.filter(provider_type="anthropic").exists()

    @respx.mock
    def test_error_redacted(self) -> None:
        """安全：上游 body 含 sk-ant-* 明文时，响应错误须脱敏。"""
        respx.post(MESSAGES).mock(
            return_value=httpx.Response(422, text='{"error":"bad key sk-ant-leak0987654321abcdef"}')
        )
        client = APIClient()
        client.force_authenticate(user=_superuser())
        resp = client.post(WIZARD_URL, _payload(), format="json")
        assert resp.status_code == 400
        assert "sk-ant-leak0987654321abcdef" not in json.dumps(resp.json())

    @respx.mock
    def test_idempotent_retry(self) -> None:
        """幂等：同 name 重复提交仅一行（update_or_create），不撞唯一约束。"""
        from system.models import ProviderCredential

        respx.post(MESSAGES).mock(return_value=httpx.Response(200, json=_OK_MESSAGE))
        client = APIClient()
        client.force_authenticate(user=_superuser())

        first = client.post(WIZARD_URL, _payload(), format="json")
        assert first.status_code == 200
        second = client.post(
            WIZARD_URL,
            _payload(api_key="sk-ant-wizardtest-newkey-0001", model="claude-sonnet-4-5"),
            format="json",
        )
        assert second.status_code == 200

        creds = ProviderCredential.objects.filter(
            scope="system", provider_type="anthropic", name="default"
        )
        assert creds.count() == 1
        decrypted = json.loads(decrypt_value(creds.first().encrypted_config))
        assert decrypted["api_key"] == "sk-ant-wizardtest-newkey-0001"

    def test_requires_superuser(self) -> None:
        """普通用户 403。"""
        user = User.objects.create_user(username="plain", password="x")
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(WIZARD_URL, _payload(), format="json")
        assert resp.status_code == 403

    def test_anonymous_rejected(self) -> None:
        """匿名 401/403。"""
        client = APIClient()
        resp = client.post(WIZARD_URL, _payload(), format="json")
        assert resp.status_code in (401, 403)

    def test_missing_fields_400(self) -> None:
        """缺 api_key / base_url / model 返回 400。"""
        client = APIClient()
        client.force_authenticate(user=_superuser())
        resp = client.post(WIZARD_URL, {"model": "x"}, format="json")
        assert resp.status_code == 400
