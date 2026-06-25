"""Prompt CRUD API 集成测试（Plan-02 Task 3 填实）。

TestPromptSerializers 是 Task 1 的真实单元测试（Serializer 层契约）。
TestPromptCRUDAPI 是 Task 3 的真实集成测试（走 views.py + urls.py + 完整 DRF）。
"""

from __future__ import annotations

import asyncio
import json

import pytest
from django.urls import reverse

from prompts.models import Prompt, PromptCategory, PromptScope
from prompts.services import append_version

# ============================================================================
# Task 1: Serializer 层单元测试
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestPromptSerializers:
    """Serializer 层单元测试（Task 1 真实运行，不依赖 views）。"""

    def test_list_serializer_has_no_body_field(self, admin_user) -> None:
        from prompts.serializers import PromptListSerializer

        p = Prompt.objects.create(
            slug="test.serial.list",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.SYSTEM,
            title="t",
            created_by=admin_user,
        )
        data = PromptListSerializer(p).data
        assert "body" not in data
        assert data["slug"] == "test.serial.list"
        assert data["active_version_number"] is None

    def test_create_serializer_rejects_system_with_project(
        self,
        admin_user,
        project,
    ) -> None:
        from prompts.serializers import PromptCreateSerializer

        serializer = PromptCreateSerializer(
            data={
                "slug": "x.sys.with.space",
                "category": "aux_model",
                "scope": "system",
                "space": str(project.id),
                "title": "t",
                "body": "hi",
            }
        )
        assert not serializer.is_valid()
        assert "space" in serializer.errors

    def test_create_serializer_rejects_project_without_project(
        self,
        admin_user,
    ) -> None:
        from prompts.serializers import PromptCreateSerializer

        serializer = PromptCreateSerializer(
            data={
                "slug": "x.proj.no.space",
                "category": "aux_model",
                "scope": "project",
                "space": None,
                "title": "t",
                "body": "hi",
            }
        )
        assert not serializer.is_valid()
        assert "space" in serializer.errors

    def test_detail_serializer_exposes_declared_variables(
        self,
        admin_user,
    ) -> None:
        from prompts.serializers import PromptDetailSerializer

        p = Prompt.objects.create(
            slug="test.serial.declared",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.SYSTEM,
            title="t",
            created_by=admin_user,
        )
        asyncio.run(append_version(p, "Hello {{name}} {{age}}", admin_user))
        p.refresh_from_db()
        data = PromptDetailSerializer(p).data
        assert data["declared_variables"] == ["name", "age"]
        assert data["active_version"]["body"] == "Hello {{name}} {{age}}"
        assert data["active_version"]["version"] == 1


# ============================================================================
# Task 3: CRUD 11 用例集成测试
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestPromptCRUDAPI:
    """CRUD 5 端点集成测试（走真实 views + urls + DRF 路由）。"""

    def test_list_system_scope_returns_only_system_prompts(
        self,
        authenticated_admin_client,
        admin_user,
        project,
    ) -> None:
        Prompt.objects.create(
            slug="list.s1",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.SYSTEM,
            title="sys1",
            created_by=admin_user,
        )
        Prompt.objects.create(
            slug="list.s2",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.SYSTEM,
            title="sys2",
            created_by=admin_user,
        )
        Prompt.objects.create(
            slug="list.p1",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.PROJECT,
            space=project,
            title="proj1",
            created_by=admin_user,
        )
        url = reverse("prompt-list") + "?scope=system"
        resp = authenticated_admin_client.get(url)
        assert resp.status_code == 200, resp.content
        data = resp.json()
        slugs = {item["slug"] for item in data}
        # 只看本测试种的 slug（系统中可能有其他 system prompt）
        assert "list.s1" in slugs
        assert "list.s2" in slugs
        assert "list.p1" not in slugs

    def test_list_project_scope_filters_by_project_id(
        self,
        authenticated_admin_client,
        admin_user,
        project,
        second_project,
    ) -> None:
        Prompt.objects.create(
            slug="listproj.a",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.PROJECT,
            space=project,
            title="t1",
            created_by=admin_user,
        )
        Prompt.objects.create(
            slug="listproj.b",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.PROJECT,
            space=second_project,
            title="t2",
            created_by=admin_user,
        )
        url = reverse("prompt-list") + f"?scope=project&space_id={project.id}"
        resp = authenticated_admin_client.get(url)
        assert resp.status_code == 200, resp.content
        slugs = {item["slug"] for item in resp.json()}
        assert "listproj.a" in slugs
        assert "listproj.b" not in slugs

    def test_list_category_filter(
        self,
        authenticated_admin_client,
        admin_user,
    ) -> None:
        Prompt.objects.create(
            slug="cat.chat1",
            category=PromptCategory.CHAT_AGENT,
            scope=PromptScope.SYSTEM,
            title="c1",
            created_by=admin_user,
        )
        Prompt.objects.create(
            slug="cat.aux1",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.SYSTEM,
            title="c2",
            created_by=admin_user,
        )
        url = reverse("prompt-list") + "?scope=system&category=chat_agent"
        resp = authenticated_admin_client.get(url)
        assert resp.status_code == 200, resp.content
        slugs = {item["slug"] for item in resp.json()}
        assert "cat.chat1" in slugs
        assert "cat.aux1" not in slugs

    def test_retrieve_returns_active_version_body(
        self,
        authenticated_admin_client,
        admin_user,
    ) -> None:
        p = Prompt.objects.create(
            slug="retrieve.test",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.SYSTEM,
            title="t",
            created_by=admin_user,
        )
        asyncio.run(append_version(p, "Hello {{name}}", admin_user))
        url = reverse("prompt-detail", kwargs={"prompt_id": p.id})
        resp = authenticated_admin_client.get(url)
        assert resp.status_code == 200, resp.content
        data = resp.json()
        assert data["active_version"]["body"] == "Hello {{name}}"
        assert data["declared_variables"] == ["name"]

    def test_create_system_prompt_as_superuser_succeeds(
        self,
        authenticated_admin_client,
    ) -> None:
        url = reverse("prompt-list")
        payload = {
            "slug": "create.new.sys",
            "category": "aux_model",
            "scope": "system",
            "title": "新系统级",
            "description": "",
            "body": "Hi {{who}}",
            "change_note": "initial",
            "space": None,
        }
        resp = authenticated_admin_client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 201, resp.content
        data = resp.json()
        assert data["slug"] == "create.new.sys"
        assert data["active_version"]["version"] == 1
        assert data["active_version"]["body"] == "Hi {{who}}"
        assert data["declared_variables"] == ["who"]

    def test_create_prompt_appends_first_version(
        self,
        authenticated_admin_client,
    ) -> None:
        url = reverse("prompt-list")
        payload = {
            "slug": "create.v.first",
            "category": "aux_model",
            "scope": "system",
            "title": "t",
            "body": "body1",
            "space": None,
        }
        resp = authenticated_admin_client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 201, resp.content
        prompt_id = resp.json()["id"]
        versions_url = reverse("prompt-versions", kwargs={"prompt_id": prompt_id})
        versions_resp = authenticated_admin_client.get(versions_url)
        assert versions_resp.status_code == 200, versions_resp.content
        assert len(versions_resp.json()) == 1

    def test_patch_body_appends_new_version(
        self,
        authenticated_admin_client,
        admin_user,
    ) -> None:
        p = Prompt.objects.create(
            slug="patch.body.append",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.SYSTEM,
            title="t",
            created_by=admin_user,
        )
        asyncio.run(append_version(p, "v1 body", admin_user))
        url = reverse("prompt-detail", kwargs={"prompt_id": p.id})
        resp = authenticated_admin_client.patch(
            url,
            data=json.dumps({"body": "v2 body"}),
            content_type="application/json",
        )
        assert resp.status_code == 200, resp.content
        data = resp.json()
        assert data["active_version"]["version"] == 2
        assert data["active_version"]["body"] == "v2 body"

    def test_patch_body_idempotent_returns_same_version(
        self,
        authenticated_admin_client,
        admin_user,
    ) -> None:
        p = Prompt.objects.create(
            slug="patch.idem",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.SYSTEM,
            title="t",
            created_by=admin_user,
        )
        asyncio.run(append_version(p, "same body", admin_user))
        url = reverse("prompt-detail", kwargs={"prompt_id": p.id})
        resp = authenticated_admin_client.patch(
            url,
            data=json.dumps({"body": "same body"}),
            content_type="application/json",
        )
        assert resp.status_code == 200, resp.content
        # 幂等：字节级相等跳过创建，version 仍为 1
        assert resp.json()["active_version"]["version"] == 1

    def test_patch_title_only_does_not_append_version(
        self,
        authenticated_admin_client,
        admin_user,
    ) -> None:
        p = Prompt.objects.create(
            slug="patch.title.only",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.SYSTEM,
            title="old",
            created_by=admin_user,
        )
        asyncio.run(append_version(p, "body", admin_user))
        url = reverse("prompt-detail", kwargs={"prompt_id": p.id})
        resp = authenticated_admin_client.patch(
            url,
            data=json.dumps({"title": "new"}),
            content_type="application/json",
        )
        assert resp.status_code == 200, resp.content
        data = resp.json()
        assert data["title"] == "new"
        assert data["active_version"]["version"] == 1

    def test_delete_non_builtin_prompt(
        self,
        authenticated_admin_client,
        admin_user,
    ) -> None:
        p = Prompt.objects.create(
            slug="delete.ok",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.SYSTEM,
            title="t",
            created_by=admin_user,
            is_builtin=False,
        )
        url = reverse("prompt-detail", kwargs={"prompt_id": p.id})
        resp = authenticated_admin_client.delete(url)
        assert resp.status_code == 204, resp.content
        assert not Prompt.objects.filter(id=p.id).exists()

    def test_delete_builtin_system_prompt_forbidden(
        self,
        authenticated_admin_client,
        admin_user,
    ) -> None:
        p = Prompt.objects.create(
            slug="delete.builtin",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.SYSTEM,
            title="t",
            created_by=admin_user,
            is_builtin=True,
        )
        url = reverse("prompt-detail", kwargs={"prompt_id": p.id})
        resp = authenticated_admin_client.delete(url)
        assert resp.status_code == 403, resp.content
        assert resp.json()["error"] == "builtin_not_deletable"
        assert Prompt.objects.filter(id=p.id).exists()
