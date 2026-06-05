"""initial implementation plan Task 01 — contract 对话 Provider pin 语义（后端校验）。

覆盖 contract 三态判定真源：
- active/draft → PATCH provider_credential_id / model / title 允许
- frozen (status ∈ {completed, stopped, error}) → PATCH provider/model 拒绝（400 + code=conversation_frozen）
- frozen → PATCH title 允许
- 404 对话不存在
- validation：指向已禁用 / 不存在的 ProviderCredential → 400

Fixture 依赖（conftest.py）：
    - frozen_conversation_factory
    - project_a_anthropic_credential
    - project
"""

from __future__ import annotations

import json

import pytest
from rest_framework.test import APIClient

from chat.models import Conversation


def _client() -> APIClient:
    """创建未认证 APIClient；Chat API 默认鉴权关闭（CHAT_AUTH_ENABLED 不开启）。"""
    return APIClient()


def _url(conv_id: str) -> str:
    return f"/api/chat/conversations/{conv_id}/"


# ============================================================================
# Test A — frozen(completed) PATCH provider_credential_id → 400 conversation_frozen
# ============================================================================


@pytest.mark.django_db
def test_frozen_completed_rejects_provider_repin_with_400(
    frozen_conversation_factory,
    project_a_anthropic_credential,
) -> None:
    """Behavior A：已完成对话 PATCH provider_credential_id 返回 400 + code=conversation_frozen。"""
    conv = frozen_conversation_factory(status="completed")

    resp = _client().patch(
        _url(str(conv.id)),
        data={"provider_credential_id": str(project_a_anthropic_credential.id)},
        format="json",
    )

    assert resp.status_code == 400, resp.content
    body = resp.json()
    assert body["code"] == "conversation_frozen"
    assert "completed" in body["detail"]


# ============================================================================
# Test B — frozen(completed) PATCH title → 200
# ============================================================================


@pytest.mark.django_db
def test_frozen_completed_allows_title_update(
    frozen_conversation_factory,
) -> None:
    """Behavior B：已完成对话 PATCH title（不含 provider/model）允许。"""
    conv = frozen_conversation_factory(status="completed", title="原标题")

    resp = _client().patch(
        _url(str(conv.id)),
        data={"title": "新标题"},
        format="json",
    )

    assert resp.status_code == 200, resp.content
    conv.refresh_from_db()
    assert conv.title == "新标题"


# ============================================================================
# Test C — active(running) PATCH provider_credential_id → 200 持久化
# ============================================================================


@pytest.mark.django_db
def test_active_running_can_repin_provider(
    frozen_conversation_factory,
    project_a_anthropic_credential,
) -> None:
    """Behavior C：活跃对话（status=running）PATCH provider_credential_id 成功持久化。"""
    conv = frozen_conversation_factory(status="running")

    resp = _client().patch(
        _url(str(conv.id)),
        data={"provider_credential_id": str(project_a_anthropic_credential.id)},
        format="json",
    )

    assert resp.status_code == 200, resp.content
    conv.refresh_from_db()
    assert str(conv.provider_credential_id_id) == str(project_a_anthropic_credential.id)


# ============================================================================
# Test D — draft PATCH provider_credential_id → 200
# ============================================================================


@pytest.mark.django_db
def test_draft_can_repin_provider(
    frozen_conversation_factory,
    project_a_anthropic_credential,
) -> None:
    """Behavior D：draft 态对话 PATCH provider_credential_id 允许（无 user message）。"""
    conv = frozen_conversation_factory(status="draft")

    resp = _client().patch(
        _url(str(conv.id)),
        data={"provider_credential_id": str(project_a_anthropic_credential.id)},
        format="json",
    )

    assert resp.status_code == 200, resp.content
    conv.refresh_from_db()
    assert str(conv.provider_credential_id_id) == str(project_a_anthropic_credential.id)


# ============================================================================
# Test E — PATCH 不存在的 conversation_id → 404
# ============================================================================


@pytest.mark.django_db
def test_patch_nonexistent_conversation_returns_404() -> None:
    """Behavior E：PATCH 不存在的对话 ID 返回 404。"""
    resp = _client().patch(
        _url("00000000-0000-0000-0000-000000000000"),
        data={"title": "x"},
        format="json",
    )
    assert resp.status_code == 404, resp.content


# ============================================================================
# Test F — PATCH 指向 inactive ProviderCredential → 400 validation
# ============================================================================


@pytest.mark.django_db
def test_patch_inactive_provider_credential_rejected(
    frozen_conversation_factory,
    project_a_anthropic_credential,
) -> None:
    """Behavior F：指向已禁用的 ProviderCredential → 400 validation error。"""
    project_a_anthropic_credential.is_active = False
    project_a_anthropic_credential.save(update_fields=["is_active"])

    conv = frozen_conversation_factory(status="draft")
    resp = _client().patch(
        _url(str(conv.id)),
        data={"provider_credential_id": str(project_a_anthropic_credential.id)},
        format="json",
    )

    assert resp.status_code == 400, resp.content


# ============================================================================
# 辅助断言：frozen 态对 stopped / error 同样拒绝（contract 完整覆盖）
# ============================================================================


@pytest.mark.django_db
@pytest.mark.parametrize("frozen_status", ["stopped", "error"])
def test_frozen_variants_also_reject(
    frozen_conversation_factory,
    project_a_anthropic_credential,
    frozen_status: str,
) -> None:
    """Behavior A 扩展：stopped / error 同样拒绝 provider 修改。"""
    conv = frozen_conversation_factory(status=frozen_status)

    resp = _client().patch(
        _url(str(conv.id)),
        data={"provider_credential_id": str(project_a_anthropic_credential.id)},
        format="json",
    )

    assert resp.status_code == 400, resp.content
    body = resp.json()
    assert body["code"] == "conversation_frozen"
    assert frozen_status in body["detail"]
