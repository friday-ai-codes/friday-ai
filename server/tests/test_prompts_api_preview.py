"""Prompt Preview API 集成测试（Plan-02 Task 3 填实）。"""

from __future__ import annotations

import asyncio
import json

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from prompts.models import Prompt, PromptCategory, PromptScope
from prompts.services import append_version


def _make_prompt_with_body(
    admin_user,
    slug: str,
    body: str,
    *,
    scope: str = PromptScope.SYSTEM,
    space=None,
) -> Prompt:
    p = Prompt.objects.create(
        slug=slug,
        category=PromptCategory.AUX_MODEL,
        scope=scope,
        space=space,
        title="t",
        created_by=admin_user,
    )
    asyncio.run(append_version(p, body, admin_user))
    p.refresh_from_db()
    return p


@pytest.mark.django_db(transaction=True)
class TestPromptPreviewAPI:
    """Preview 端点 5 个集成用例。"""

    def test_preview_happy_path(
        self,
        authenticated_admin_client,
        admin_user,
    ) -> None:
        p = _make_prompt_with_body(
            admin_user, "preview.ok", "Hello {{name}}"
        )
        url = reverse("prompt-preview", kwargs={"prompt_id": p.id})
        resp = authenticated_admin_client.post(
            url,
            data=json.dumps({"variables": {"name": "Alice"}}),
            content_type="application/json",
        )
        assert resp.status_code == 200, resp.content
        # contract: 变量值被 XML tag 包裹
        assert "<name>Alice</name>" in resp.json()["rendered"]

    def test_preview_missing_variables_returns_422(
        self,
        authenticated_admin_client,
        admin_user,
    ) -> None:
        p = _make_prompt_with_body(
            admin_user, "preview.miss", "Hi {{name}} {{age}}"
        )
        url = reverse("prompt-preview", kwargs={"prompt_id": p.id})
        resp = authenticated_admin_client.post(
            url,
            data=json.dumps({"variables": {"name": "X"}}),
            content_type="application/json",
        )
        assert resp.status_code == 422, resp.content
        body = resp.json()
        assert body["error"] == "prompt_variable_missing"
        assert body["slug"] == "preview.miss"
        assert "age" in body["missing"]

    def test_preview_extra_variables_ok(
        self,
        authenticated_admin_client,
        admin_user,
    ) -> None:
        p = _make_prompt_with_body(
            admin_user, "preview.extra", "Hi {{name}}"
        )
        url = reverse("prompt-preview", kwargs={"prompt_id": p.id})
        resp = authenticated_admin_client.post(
            url,
            data=json.dumps(
                {"variables": {"name": "X", "extra": "Y"}}
            ),
            content_type="application/json",
        )
        assert resp.status_code == 200, resp.content

    def test_preview_unauthenticated_401(
        self,
        api_client,
        admin_user,
    ) -> None:
        p = _make_prompt_with_body(
            admin_user, "preview.auth", "Hi {{name}}"
        )
        url = reverse("prompt-preview", kwargs={"prompt_id": p.id})
        resp = api_client.post(
            url,
            data=json.dumps({"variables": {"name": "X"}}),
            content_type="application/json",
        )
        # 401 或 403 — DRF 默认未认证对非 GET 返回 401 或 403 视 auth class 而定
        assert resp.status_code in (401, 403), resp.content

    def test_preview_project_scope_requires_member_role(
        self,
        admin_user,
        project,
        other_user,
    ) -> None:
        """项目级 prompt preview 需要 VIEWER+ 项目角色。"""
        p = _make_prompt_with_body(
            admin_user,
            "preview.proj.auth",
            "Hi",
            scope=PromptScope.PROJECT,
            space=project,
        )
        # other_user 不是 project 任何角色
        client = APIClient()
        client.force_authenticate(user=other_user)
        url = reverse("prompt-preview", kwargs={"prompt_id": p.id})
        resp = client.post(
            url,
            data=json.dumps({"variables": {}}),
            content_type="application/json",
        )
        assert resp.status_code == 403, resp.content
