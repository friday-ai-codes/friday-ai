"""入站 git webhook 端点守护测试（Phase 80，MR-02）：

- 未配置密钥 → fail-closed 403
- 无效签名 → 403
- 有效 GitHub HMAC → 200 + MR 同步
- 有效 GitLab token → 200
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from rest_framework.test import APIClient

from initiatives.models import MergeRequest
from system.models import SettingKeys, SystemSetting

pytestmark = pytest.mark.django_db(transaction=True)

_SECRET = "whsecret123"


def _github_body():
    return {
        "action": "opened",
        "pull_request": {
            "number": 99,
            "html_url": "https://github.com/o/r/pull/99",
            "title": "feat: z",
            "state": "open",
            "merged": False,
            "head": {"ref": "feat/z"},
            "base": {"ref": "main"},
        },
        "repository": {"html_url": "https://github.com/o/r"},
    }


def test_no_secret_configured_fail_closed():
    client = APIClient()
    resp = client.post(
        "/api/git-webhooks/github/", _github_body(), format="json"
    )
    assert resp.status_code == 403


def test_invalid_signature_rejected():
    SystemSetting.objects.create(key=SettingKeys.GIT_WEBHOOK_SECRET, value=_SECRET)
    client = APIClient()
    resp = client.post(
        "/api/git-webhooks/github/",
        _github_body(),
        format="json",
        HTTP_X_HUB_SIGNATURE_256="sha256=deadbeef",
    )
    assert resp.status_code == 403


def test_valid_github_hmac_syncs_mr():
    SystemSetting.objects.create(key=SettingKeys.GIT_WEBHOOK_SECRET, value=_SECRET)
    body = _github_body()
    raw = json.dumps(body).encode("utf-8")
    sig = hmac.new(_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    client = APIClient()
    resp = client.post(
        "/api/git-webhooks/github/",
        data=raw,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=f"sha256={sig}",
        HTTP_X_GITHUB_DELIVERY="delivery-1",
    )
    assert resp.status_code == 200, resp.content
    assert MergeRequest.objects.filter(platform="github", external_id="99").exists()


def test_valid_gitlab_token_syncs_mr():
    SystemSetting.objects.create(key=SettingKeys.GIT_WEBHOOK_SECRET, value=_SECRET)
    body = {
        "object_kind": "merge_request",
        "object_attributes": {
            "iid": 8,
            "url": "https://gitlab.com/o/r/-/merge_requests/8",
            "title": "feat: g",
            "source_branch": "feat/g",
            "target_branch": "main",
            "state": "opened",
            "action": "open",
        },
        "project": {"web_url": "https://gitlab.com/o/r"},
    }
    raw = json.dumps(body).encode("utf-8")
    client = APIClient()
    resp = client.post(
        "/api/git-webhooks/gitlab/",
        data=raw,
        content_type="application/json",
        HTTP_X_GITLAB_TOKEN=_SECRET,
        HTTP_X_GITLAB_EVENT_UUID="evt-1",
    )
    assert resp.status_code == 200, resp.content
    assert MergeRequest.objects.filter(platform="gitlab", external_id="8").exists()
