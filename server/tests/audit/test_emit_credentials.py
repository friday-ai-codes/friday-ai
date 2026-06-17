"""凭证/数据治理类敏感操作 emit 行落库测试（AUDITCOV-02，SC-2 / SC-3 排除规则）。

覆盖 Git 实例凭证 CRUD + per-repo 排除规则增删 + PAT 增吊（幂等）的审计 emit 接线，
断言 AuditEvent 行落库正确（action / actor / target / 前后值），并校验凭证型字段
绝不落明文（SC-2 脱敏核心：DB 审计载荷无 token 明文 / token_hash）。

驱动方式：DRF APIClient。git-instance-credentials 需 superuser（IsAdminUser），排除规则
与 PAT 沿用普通认证用户。django_db(transaction=True) 以触发 transaction.on_commit。
"""

from __future__ import annotations

import json

import pytest

from audit.models import AuditEvent
from common.encryption import encrypt_value
from repositories.models import GitInstanceCredential, RepoExclusionRule

pytestmark = pytest.mark.django_db(transaction=True)

PROVIDER_CRED_URL = "/api/providers/credentials/"
PROVIDER_CRED_DETAIL = "/api/providers/credentials/{cred_id}/"
PROVIDER_API_KEY = "sk-ant-validkey1234567890abcdef"


def _provider_payload(name: str) -> dict:
    return {
        "provider_type": "anthropic",
        "name": name,
        "scope": "system",
        "default_model": "claude-3-5-sonnet-20241022",
        "available_models": [
            {"id": "claude-3-5-sonnet-20241022", "display_name": "Claude 3.5 Sonnet"}
        ],
        "config": {"api_key": PROVIDER_API_KEY, "base_url": "https://api.anthropic.com"},
    }


GIC_LIST = "/api/repositories/git-instance-credentials/"
GIC_DETAIL = "/api/repositories/git-instance-credentials/{cred_id}/"
EXCL_URL = "/api/repositories/{repo_id}/exclusions/"
EXCL_DETAIL = "/api/repositories/{repo_id}/exclusions/{rule_id}/"
PAT_LIST = "/api/access-tokens/"
PAT_REVOKE = "/api/access-tokens/{pk}/revoke/"

PLAINTEXT_TOKEN = "glpat-SECRET-PLAINTEXT-abc123XYZ"


def _payload_blob(event: AuditEvent) -> str:
    return json.dumps(event.before) + json.dumps(event.after) + json.dumps(event.metadata)


# ---------------------------------------------------------------------------
# Git 实例凭证 CRUD（superuser）—— 创建/更新/删除 emit + 脱敏（核心）
# ---------------------------------------------------------------------------


class TestGitInstanceCredentialEmit:
    def test_create_emits_redacted(self, authenticated_admin_client, admin_user) -> None:
        resp = authenticated_admin_client.post(
            GIC_LIST,
            {"host": "gitlab.audit.com", "access_token": PLAINTEXT_TOKEN, "label": "L"},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        event = AuditEvent.objects.get(
            action="credential.created", target_type="git_instance_credential"
        )
        assert event.actor_id == admin_user.id
        assert event.after["host"] == "gitlab.audit.com"
        assert event.after["provided"] is True
        # SC-2 核心：审计载荷绝不含 token 明文
        assert PLAINTEXT_TOKEN not in _payload_blob(event)

    def test_update_token_emits_token_changed(self, authenticated_admin_client, admin_user) -> None:
        cred = GitInstanceCredential.objects.create(
            host="gitlab.rotate.com", encrypted_token=encrypt_value("old-token")
        )
        new_token = "glpat-NEW-ROTATED-token-999"
        resp = authenticated_admin_client.patch(
            GIC_DETAIL.format(cred_id=cred.id),
            {"access_token": new_token},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        event = AuditEvent.objects.get(
            action="credential.updated", target_type="git_instance_credential"
        )
        assert event.after["rotated"] is True
        assert new_token not in _payload_blob(event)

    def test_delete_emits_with_before_snapshot(
        self, authenticated_admin_client, admin_user
    ) -> None:
        cred = GitInstanceCredential.objects.create(
            host="gitlab.del.com", provider="gitlab", encrypted_token=encrypt_value("x")
        )
        resp = authenticated_admin_client.delete(GIC_DETAIL.format(cred_id=cred.id))
        assert resp.status_code == 204
        event = AuditEvent.objects.get(
            action="credential.deleted", target_type="git_instance_credential"
        )
        assert event.before["host"] == "gitlab.del.com"
        assert event.before["provider"] == "gitlab"


# ---------------------------------------------------------------------------
# Provider 凭证 CRUD（system app）—— 创建/更新/删除 emit + 脱敏（核心）
# ---------------------------------------------------------------------------


class TestProviderCredentialEmit:
    def test_create_emits_redacted(self, system_admin_user) -> None:
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(user=system_admin_user)
        resp = client.post(PROVIDER_CRED_URL, _provider_payload("aud-anth"), format="json")
        assert resp.status_code == 201, resp.content
        event = AuditEvent.objects.get(
            action="credential.created", target_type="provider_credential"
        )
        assert event.actor_id == system_admin_user.id
        assert event.after["provider_type"] == "anthropic"
        assert event.after["name"] == "aud-anth"
        # SC-2 核心：api_key 明文绝不入审计载荷
        assert PROVIDER_API_KEY not in _payload_blob(event)

    def test_delete_emits_with_snapshot(self, system_admin_user) -> None:
        from rest_framework.test import APIClient

        from system.models import ProviderCredential

        client = APIClient()
        client.force_authenticate(user=system_admin_user)
        client.post(PROVIDER_CRED_URL, _provider_payload("aud-del"), format="json")
        cred_id = ProviderCredential.objects.get(name="aud-del").id
        resp = client.delete(PROVIDER_CRED_DETAIL.format(cred_id=cred_id))
        assert resp.status_code in (200, 204)
        event = AuditEvent.objects.get(
            action="credential.deleted", target_type="provider_credential"
        )
        assert event.before["name"] == "aud-del"
        assert PROVIDER_API_KEY not in _payload_blob(event)


# ---------------------------------------------------------------------------
# per-repo 排除规则增删 emit（SC-3）
# ---------------------------------------------------------------------------


class TestExclusionRuleEmit:
    def test_create_emits(self, authenticated_client, user, repository) -> None:
        resp = authenticated_client.post(
            EXCL_URL.format(repo_id=repository.id),
            {"pattern": "*.secret", "rule_type": "glob"},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        event = AuditEvent.objects.get(
            action="exclusion_rule.changed", target_type="repo_exclusion_rule"
        )
        assert event.actor_id == user.id
        assert event.after["pattern"] == "*.secret"
        assert event.metadata["op"] == "created"

    def test_delete_emits_with_snapshot(self, authenticated_client, repository) -> None:
        rule = RepoExclusionRule.objects.create(
            repository=repository, pattern="tmp/", rule_type="dir", source="user"
        )
        resp = authenticated_client.delete(
            EXCL_DETAIL.format(repo_id=repository.id, rule_id=rule.id)
        )
        assert resp.status_code == 204
        event = AuditEvent.objects.get(
            action="exclusion_rule.changed",
            target_type="repo_exclusion_rule",
            metadata__op="deleted",
        )
        assert event.before["pattern"] == "tmp/"


# ---------------------------------------------------------------------------
# PAT 增 / 吊（幂等）emit + 明文不落审计（SC-2）
# ---------------------------------------------------------------------------


class TestPatEmit:
    def test_create_emits_redacted(self, authenticated_client, user) -> None:
        resp = authenticated_client.post(PAT_LIST, {"name": "ci-token"}, format="json")
        assert resp.status_code == 201, resp.content
        plaintext = resp.json()["token"]
        event = AuditEvent.objects.get(action="pat.created", target_type="pat")
        assert event.actor_id == user.id
        assert event.after["name"] == "ci-token"
        # 明文 / token_hash 绝不入审计载荷
        assert plaintext not in _payload_blob(event)

    def test_revoke_emits(self, authenticated_client, user) -> None:
        create = authenticated_client.post(PAT_LIST, {"name": "rev"}, format="json")
        pk = create.json()["id"]
        resp = authenticated_client.post(PAT_REVOKE.format(pk=pk), format="json")
        assert resp.status_code == 200
        assert AuditEvent.objects.filter(action="pat.revoked", target_id=str(pk)).count() == 1

    def test_revoke_idempotent_single_event(self, authenticated_client, user) -> None:
        """重复 revoke 同一 token 仅产 1 条 pat.revoked（幂等，首吊才 emit）。"""
        create = authenticated_client.post(PAT_LIST, {"name": "idem"}, format="json")
        pk = create.json()["id"]
        authenticated_client.post(PAT_REVOKE.format(pk=pk), format="json")
        authenticated_client.post(PAT_REVOKE.format(pk=pk), format="json")
        assert AuditEvent.objects.filter(action="pat.revoked", target_id=str(pk)).count() == 1
