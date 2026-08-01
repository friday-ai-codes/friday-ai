"""charter REST 三端点 API 测试（CHARTER-01，111-03 Task 3）。

覆盖（对齐 111-03-PLAN acceptance_criteria + 威胁缓解 T-111-06/T-111-07）：
- 未认证请求 → 401/403（三端点全部拒绝，IsAuthenticated 守门）。
- GET 无章程 → 404 中性消息；POST draft（mock LLM）→ 200 且 source=="ai_draft"、
  positioning 来自 mock；GET → 200。
- POST confirm 带 edits → 200 且 source=="human_confirmed"、version==2、edits 生效
  （evolution 非法值被 normalize 回退）。
- POST draft 当 provider 缺失（patch aresolve）→ 503。
- 不存在的 repository_id → 404（GET 无章程 / draft 仓库不存在 / confirm 章程不存在）。

LLM mock 手法同 ``test_charter_service.py``：charter_service 函数内懒 import，
patch 点在源模块 ``agents.llm_factory.build_chat_model`` /
``services.provider_config.ProviderConfigService.aresolve``。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from django.db import OperationalError

from repositories.models import RepoCharter, Repository
from tests.helpers.fake_chat_model import FakeChatModel

pytestmark = pytest.mark.django_db(transaction=True)

_ARESOLVE = "services.provider_config.ProviderConfigService.aresolve"
_BUILD = "agents.llm_factory.build_chat_model"

CHARTER_URL = "/api/repositories/{repo_id}/charter/"
DRAFT_URL = "/api/repositories/{repo_id}/charter/draft/"
CONFIRM_URL = "/api/repositories/{repo_id}/charter/confirm/"

MISSING_REPO_ID = "00000000-0000-0000-0000-000000000001"


def _resolved(default_model: str = "test-model") -> SimpleNamespace:
    return SimpleNamespace(extra={"default_model": default_model})


def _charter_json(positioning: str = "C 端学生移动 H5 学习应用集") -> str:
    return json.dumps(
        {
            "positioning": positioning,
            "owned_domains": [
                {
                    "domain": "学习功能页 / 培优课",
                    "status": "planned",
                    "note": "净新增落点",
                    "citations": ["cit_1"],
                }
            ],
            "boundaries": [
                {"rule": "不承接课程权益鉴权", "decided_by": "human:zane", "citations": []}
            ],
            "placement_preferences": [{"kind": "学生端练习页", "target": "apps/*", "note": ""}],
            "audience": "C端学生",
            "form": "移动端H5",
            "evolution": "active",
        },
        ensure_ascii=False,
    )


def _mock_llm(positioning: str = "C 端学生移动 H5 学习应用集"):
    """patch aresolve + build_chat_model 双点，返回可组合的 patcher 元组。"""
    return (
        patch(_ARESOLVE, new=AsyncMock(return_value=_resolved())),
        patch(_BUILD, return_value=FakeChatModel(responses=[_charter_json(positioning)])),
    )


def _post_draft(client, repo_id, positioning: str = "C 端学生移动 H5 学习应用集"):
    p1, p2 = _mock_llm(positioning)
    with p1, p2:
        return client.post(DRAFT_URL.format(repo_id=repo_id))


# ── 鉴权守门（T-111-06）──────────────────────────────────────────────────


class TestCharterAuth:
    def test_get_unauthenticated_blocked(self, api_client, repository: Repository) -> None:
        resp = api_client.get(CHARTER_URL.format(repo_id=repository.id))
        assert resp.status_code in (401, 403)

    def test_draft_unauthenticated_blocked(self, api_client, repository: Repository) -> None:
        resp = api_client.post(DRAFT_URL.format(repo_id=repository.id))
        assert resp.status_code in (401, 403)
        assert not RepoCharter.objects.filter(repository=repository).exists()

    def test_confirm_unauthenticated_blocked(self, api_client, repository: Repository) -> None:
        resp = api_client.post(CONFIRM_URL.format(repo_id=repository.id), {}, format="json")
        assert resp.status_code in (401, 403)


# ── GET 章程读取 ──────────────────────────────────────────────────────────


class TestCharterDetail:
    def test_get_no_charter_404(self, authenticated_client, repository: Repository) -> None:
        resp = authenticated_client.get(CHARTER_URL.format(repo_id=repository.id))
        assert resp.status_code == 404

    def test_get_missing_repo_404(self, authenticated_client) -> None:
        resp = authenticated_client.get(CHARTER_URL.format(repo_id=MISSING_REPO_ID))
        assert resp.status_code == 404

    def test_get_after_draft_returns_charter(
        self, authenticated_client, repository: Repository
    ) -> None:
        assert _post_draft(authenticated_client, repository.id).status_code == 200

        resp = authenticated_client.get(CHARTER_URL.format(repo_id=repository.id))
        assert resp.status_code == 200
        body = resp.json()
        assert body["repository"] == str(repository.id)
        assert body["source"] == "ai_draft"
        assert body["version"] == 1
        assert body["positioning"] == "C 端学生移动 H5 学习应用集"
        assert body["draft_content"] == {}


# ── POST draft：AI 起草 ───────────────────────────────────────────────────


class TestCharterDraft:
    def test_draft_creates_ai_draft(self, authenticated_client, repository: Repository) -> None:
        resp = _post_draft(authenticated_client, repository.id, positioning="起草定位")
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "ai_draft"
        assert body["positioning"] == "起草定位"
        assert body["owned_domains"][0]["domain"] == "学习功能页 / 培优课"
        # DB 真落行
        charter = RepoCharter.objects.get(repository=repository)
        assert charter.source == RepoCharter.Source.AI_DRAFT

    def test_draft_provider_missing_503(self, authenticated_client, repository: Repository) -> None:
        with patch(_ARESOLVE, new=AsyncMock(return_value=None)):
            resp = authenticated_client.post(DRAFT_URL.format(repo_id=repository.id))
        assert resp.status_code == 503
        assert not RepoCharter.objects.filter(repository=repository).exists()

    def test_draft_persist_error_500_not_503(
        self, authenticated_client, repository: Repository
    ) -> None:
        """MJ-02：草案落库失败回 500，且文案不指向「供应商配置」。"""
        p1, p2 = _mock_llm()
        with (
            p1,
            p2,
            patch.object(
                RepoCharter.objects, "create", side_effect=OperationalError("database is locked")
            ),
        ):
            resp = authenticated_client.post(DRAFT_URL.format(repo_id=repository.id))
        assert resp.status_code == 500
        assert "供应商" not in resp.json()["detail"]
        assert not RepoCharter.objects.filter(repository=repository).exists()

    def test_draft_missing_repo_404(self, authenticated_client) -> None:
        resp = authenticated_client.post(DRAFT_URL.format(repo_id=MISSING_REPO_ID))
        assert resp.status_code == 404

    def test_draft_after_confirm_only_writes_draft_content(
        self, authenticated_client, repository: Repository
    ) -> None:
        """human_confirmed 后再起草：响应正式字段不变，新草案进 draft_content（P11 API 面）。"""
        assert _post_draft(authenticated_client, repository.id, "人工确认前定位").status_code == 200
        confirm = authenticated_client.post(
            CONFIRM_URL.format(repo_id=repository.id), {}, format="json"
        )
        assert confirm.status_code == 200

        resp = _post_draft(authenticated_client, repository.id, "AI 想覆盖的新定位")
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "human_confirmed"
        assert body["positioning"] == "人工确认前定位"
        assert body["draft_content"]["positioning"] == "AI 想覆盖的新定位"


# ── POST confirm：人工确认 ────────────────────────────────────────────────


class TestCharterConfirm:
    def test_confirm_with_edits(self, authenticated_client, repository: Repository, user) -> None:
        assert _post_draft(authenticated_client, repository.id).status_code == 200

        resp = authenticated_client.post(
            CONFIRM_URL.format(repo_id=repository.id),
            {"edits": {"positioning": "人工改写", "evolution": "bogus-value"}},
            format="json",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "human_confirmed"
        assert body["version"] == 2
        assert body["positioning"] == "人工改写"
        assert body["evolution"] == "active"  # 非法值被 normalize 回退
        assert body["confirmed_by"] == str(user.id)
        assert body["draft_content"] == {}

    def test_confirm_without_body(self, authenticated_client, repository: Repository) -> None:
        assert _post_draft(authenticated_client, repository.id).status_code == 200
        resp = authenticated_client.post(CONFIRM_URL.format(repo_id=repository.id))
        assert resp.status_code == 200
        assert resp.json()["source"] == "human_confirmed"

    def test_confirm_no_charter_404(self, authenticated_client, repository: Repository) -> None:
        resp = authenticated_client.post(
            CONFIRM_URL.format(repo_id=repository.id), {}, format="json"
        )
        assert resp.status_code == 404
        assert not RepoCharter.objects.filter(repository=repository).exists()

    def test_confirm_missing_repo_404(self, authenticated_client) -> None:
        resp = authenticated_client.post(
            CONFIRM_URL.format(repo_id=MISSING_REPO_ID), {}, format="json"
        )
        assert resp.status_code == 404
