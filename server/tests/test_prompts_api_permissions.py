"""Prompt API RBAC 权限矩阵测试（Plan-02 Task 5 填实）。

矩阵：
- 系统级：IsSuperUser 可写 / IsAuthenticated 可读
- 项目级：IsProjectAdmin 可写 / VIEWER+ 可读
- work item 双分支拆分：非 superuser ADMIN 正面 + 非 superuser MEMBER 负面
- superuser bypass 路径专用测试

12 条测试，覆盖系统级/项目级读写/删除/跨项目防护。
"""

from __future__ import annotations

import asyncio
import json

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from permissions.models import SpaceMembership, SpaceRole
from prompts.models import Prompt, PromptCategory, PromptScope
from prompts.services import append_version


@pytest.mark.django_db(transaction=True)
class TestPromptAPIPermissions:
    """12 条 RBAC 测试。"""

    # ---- 系统级读/写 ----

    def test_viewer_can_read_system_prompts(
        self,
        authenticated_viewer_client,
        admin_user,
    ) -> None:
        Prompt.objects.create(
            slug="rbac.read.sys",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.SYSTEM,
            title="t",
            created_by=admin_user,
        )
        url = reverse("prompt-list") + "?scope=system"
        resp = authenticated_viewer_client.get(url)
        assert resp.status_code == 200, resp.content

    def test_regular_user_cannot_create_system_prompt_403(
        self,
        authenticated_client,
    ) -> None:
        url = reverse("prompt-list")
        payload = {
            "slug": "rbac.hack.sys",
            "category": "aux_model",
            "scope": "system",
            "title": "坏人",
            "body": "恶意",
            "space": None,
        }
        resp = authenticated_client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 403, resp.content
        assert resp.json()["error"] == "permission_denied"

    def test_superuser_can_create_system_prompt(
        self,
        authenticated_admin_client,
    ) -> None:
        url = reverse("prompt-list")
        payload = {
            "slug": "rbac.legit.sys",
            "category": "aux_model",
            "scope": "system",
            "title": "合法",
            "body": "正常",
            "space": None,
        }
        resp = authenticated_admin_client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 201, resp.content

    # ---- 项目级 双分支拆分（work item 核心）----

    def test_non_superuser_project_admin_can_edit_project_prompt(
        self,
        user,
        admin_user,
        project,
        project_memberships,
    ) -> None:
        """work item 正面：非 superuser project ADMIN 可编辑项目级 prompt → 200。

        关键：使用 `user` fixture（非 superuser）+ `project_memberships`
        将 `user` 设为 project 的 SpaceRole.ADMIN。这样 PATCH 请求实际走的是
        `PermissionService.has_project_access(user, project, SpaceRole.ADMIN)` 分支，
        而不是 superuser bypass。
        """
        # 防 fixture 漂移
        assert not user.is_superuser, (
            "fixture 漂移：user 必须是非 superuser，否则本测试退化为 superuser bypass"
        )
        assert project_memberships["admin"].user_id == user.id
        assert project_memberships["admin"].role == SpaceRole.ADMIN

        p = Prompt.objects.create(
            slug="rbac.proj.admin.edit",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.PROJECT,
            space=project,
            title="t",
            created_by=admin_user,
        )
        asyncio.run(append_version(p, "v1", admin_user))

        client = APIClient()
        client.force_authenticate(user=user)  # 非 superuser project ADMIN
        url = reverse("prompt-detail", kwargs={"prompt_id": p.id})
        resp = client.patch(
            url,
            data=json.dumps({"body": "v2"}),
            content_type="application/json",
        )
        # work item 走 PermissionService.has_project_access(..., ADMIN) 分支放行
        assert resp.status_code == 200, resp.content
        p.refresh_from_db()
        assert p.active_version is not None
        assert p.active_version.body == "v2"

    def test_non_superuser_project_member_cannot_edit_project_prompt(
        self,
        admin_user,
        project,
        member_user,
        project_memberships,
    ) -> None:
        """work item 负面：非 superuser project MEMBER 不能编辑项目级 prompt → 403。

        与正面配对：MEMBER 角色不满足 has_project_access(..., ADMIN)，必须 403。
        证明 ADMIN 分支判断的精确性 —— ADMIN 放行、MEMBER 拒绝。
        """
        assert not member_user.is_superuser
        assert project_memberships["member"].user_id == member_user.id
        assert project_memberships["member"].role == SpaceRole.MEMBER

        p = Prompt.objects.create(
            slug="rbac.proj.member",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.PROJECT,
            space=project,
            title="t",
            created_by=admin_user,
        )
        asyncio.run(append_version(p, "v1", admin_user))

        client = APIClient()
        client.force_authenticate(user=member_user)
        url = reverse("prompt-detail", kwargs={"prompt_id": p.id})
        resp = client.patch(
            url,
            data=json.dumps({"body": "v2_attempt"}),
            content_type="application/json",
        )
        assert resp.status_code == 403, resp.content
        assert resp.json()["error"] == "permission_denied"
        # body 未被修改
        p.refresh_from_db()
        if p.active_version is not None:
            assert p.active_version.body == "v1"

    def test_project_viewer_cannot_edit_project_prompt_403(
        self,
        admin_user,
        project,
        viewer_user,
        project_memberships,
    ) -> None:
        assert project_memberships["viewer"].role == SpaceRole.VIEWER
        p = Prompt.objects.create(
            slug="rbac.proj.viewer",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.PROJECT,
            space=project,
            title="t",
            created_by=admin_user,
        )
        asyncio.run(append_version(p, "v1", admin_user))
        client = APIClient()
        client.force_authenticate(user=viewer_user)
        url = reverse("prompt-detail", kwargs={"prompt_id": p.id})
        resp = client.patch(
            url,
            data=json.dumps({"body": "v2"}),
            content_type="application/json",
        )
        assert resp.status_code == 403, resp.content

    def test_non_member_cannot_read_project_prompt_403(
        self,
        admin_user,
        project,
        other_user,
    ) -> None:
        p = Prompt.objects.create(
            slug="rbac.proj.read",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.PROJECT,
            space=project,
            title="t",
            created_by=admin_user,
        )
        asyncio.run(append_version(p, "v1", admin_user))
        client = APIClient()
        client.force_authenticate(user=other_user)
        url = reverse("prompt-detail", kwargs={"prompt_id": p.id})
        resp = client.get(url)
        assert resp.status_code == 403, resp.content

    def test_superuser_bypasses_project_admin_check(
        self,
        authenticated_admin_client,
        admin_user,
        second_project,
    ) -> None:
        """work item superuser bypass 路径专用测试。

        本测试只验证 superuser 全量放行规则，不验证 IsProjectAdmin 分支
        （IsProjectAdmin 分支由 test_non_superuser_project_admin_can_edit_project_prompt
        正面 + test_non_superuser_project_member_cannot_edit_project_prompt 负面覆盖）。

        场景：admin_user（superuser）对 second_project（其不是 ADMIN）的 prompt
        发 PATCH，应返回 200，因为 is_superuser 在权限判断的最前端短路放行。
        """
        assert admin_user.is_superuser
        assert not SpaceMembership.objects.filter(
            user=admin_user,
            space=second_project,
        ).exists(), "admin_user 不应在 second_project 有任何成员关系"

        p = Prompt.objects.create(
            slug="rbac.proj.su",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.PROJECT,
            space=second_project,
            title="t",
            created_by=admin_user,
        )
        asyncio.run(append_version(p, "v1", admin_user))
        url = reverse("prompt-detail", kwargs={"prompt_id": p.id})
        resp = authenticated_admin_client.patch(
            url,
            data=json.dumps({"body": "v2"}),
            content_type="application/json",
        )
        # 仅靠 superuser bypass 通过；走的是 IsSuperUser 短路而非 has_project_access
        assert resp.status_code == 200, resp.content

    def test_cross_project_leak_prevention(
        self,
        admin_user,
        project,
        second_project,
        user,
        project_memberships,
    ) -> None:
        """Space A ADMIN 尝试编辑 Space B 的 prompt → 403。

        user 是 project 的 ADMIN（来自 project_memberships fixture），
        但对 second_project 没有任何角色，因此必须被 403 拦截。
        """
        assert not user.is_superuser
        assert project_memberships["admin"].user_id == user.id
        assert not SpaceMembership.objects.filter(
            user=user,
            space=second_project,
        ).exists()

        p = Prompt.objects.create(
            slug="rbac.proj.leak",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.PROJECT,
            space=second_project,
            title="t",
            created_by=admin_user,
        )
        asyncio.run(append_version(p, "v1", admin_user))
        client = APIClient()
        client.force_authenticate(user=user)
        url = reverse("prompt-detail", kwargs={"prompt_id": p.id})
        resp = client.patch(
            url,
            data=json.dumps({"body": "v2_hacked"}),
            content_type="application/json",
        )
        assert resp.status_code == 403, resp.content

    def test_delete_project_prompt_requires_admin_role(
        self,
        admin_user,
        project,
        member_user,
        project_memberships,
    ) -> None:
        """DELETE 对项目级 prompt 需 ADMIN，MEMBER 拒绝。"""
        p = Prompt.objects.create(
            slug="rbac.proj.delete",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.PROJECT,
            space=project,
            title="t",
            created_by=admin_user,
            is_builtin=False,
        )
        client = APIClient()
        client.force_authenticate(user=member_user)
        url = reverse("prompt-detail", kwargs={"prompt_id": p.id})
        resp = client.delete(url)
        assert resp.status_code == 403, resp.content
        assert Prompt.objects.filter(id=p.id).exists()

    def test_regular_user_cannot_delete_system_prompt(
        self,
        authenticated_client,
        admin_user,
    ) -> None:
        """普通登录用户（非 superuser）不能删除系统级 prompt。"""
        p = Prompt.objects.create(
            slug="rbac.sys.delete",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.SYSTEM,
            title="t",
            created_by=admin_user,
            is_builtin=False,
        )
        url = reverse("prompt-detail", kwargs={"prompt_id": p.id})
        resp = authenticated_client.delete(url)
        assert resp.status_code == 403, resp.content
        assert Prompt.objects.filter(id=p.id).exists()

    def test_project_member_cannot_delete_project_prompt(
        self,
        admin_user,
        project,
        member_user,
        project_memberships,
    ) -> None:
        """项目 MEMBER 角色不能删除项目级 prompt（只有 ADMIN 可以）。"""
        p = Prompt.objects.create(
            slug="rbac.proj.member.delete",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.PROJECT,
            space=project,
            title="t",
            created_by=admin_user,
            is_builtin=False,
        )
        client = APIClient()
        client.force_authenticate(user=member_user)
        url = reverse("prompt-detail", kwargs={"prompt_id": p.id})
        resp = client.delete(url)
        assert resp.status_code == 403, resp.content
        assert Prompt.objects.filter(id=p.id).exists()
