"""凭证/数据治理类读路径无审计噪音测试（AUDITCOV-02，SC-4）。

校验凭证 / PAT / 排除规则的 **读** 操作（list / detail）绝不产生 AuditEvent——审计只记
真正的敏感写操作，读路径零噪音（SC-4）。
"""

from __future__ import annotations

import pytest

from audit.models import AuditEvent
from common.encryption import encrypt_value
from repositories.models import GitInstanceCredential, RepoExclusionRule

pytestmark = pytest.mark.django_db(transaction=True)

GIC_LIST = "/api/repositories/git-instance-credentials/"
EXCL_URL = "/api/repositories/{repo_id}/exclusions/"
PAT_LIST = "/api/access-tokens/"


def test_git_instance_credential_list_no_emit(authenticated_admin_client) -> None:
    GitInstanceCredential.objects.create(host="gitlab.read.com", encrypted_token=encrypt_value("x"))
    resp = authenticated_admin_client.get(GIC_LIST)
    assert resp.status_code == 200
    assert not AuditEvent.objects.exists()


def test_exclusion_rules_list_no_emit(authenticated_client, repository) -> None:
    RepoExclusionRule.objects.create(
        repository=repository, pattern="build/", rule_type="dir", source="user"
    )
    resp = authenticated_client.get(EXCL_URL.format(repo_id=repository.id))
    assert resp.status_code == 200
    assert not AuditEvent.objects.exists()


def test_pat_list_no_emit(authenticated_client, user) -> None:
    resp = authenticated_client.get(PAT_LIST)
    assert resp.status_code == 200
    assert not AuditEvent.objects.exists()
