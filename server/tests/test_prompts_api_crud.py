"""Prompt CRUD API 测试（Plan Task 3 填实）。
Wave stubs 在 Plan Task 1 落地（class TestPromptCRUDAPI），
真实断言由 Task 3 填充。本文件内的 TestPromptSerializers 是 Task 1 的
真实单元测试，验证 Serializer 层契约。
"""
from __future__ import annotations
import asyncio
import pytest
@pytest.mark.skip(reason="Wave Task 3 待实现（待 views.py 就位）")
@pytest.mark.django_db
class TestPromptCRUDAPI:
 """CRUD 5 端点集成测试（Task 3 填充）。"""
 def test_list_system_scope_returns_only_system_prompts(self) -> None: ...
 def test_list_project_scope_filters_by_project_id(self) -> None: ...
 def test_list_category_filter(self) -> None: ...
 def test_retrieve_returns_active_version_body(self) -> None: ...
 def test_create_system_prompt_as_superuser_succeeds(self) -> None: ...
 def test_create_prompt_appends_first_version(self) -> None: ...
 def test_patch_body_appends_new_version(self) -> None: ...
 def test_patch_body_idempotent_returns_same_version(self) -> None: ...
 def test_patch_title_only_does_not_append_version(self) -> None: ...
 def test_delete_non_builtin_prompt(self) -> None: ...
 def test_delete_builtin_system_prompt_forbidden(self) -> None: ...
@pytest.mark.django_db(transaction=True)
class TestPromptSerializers:
 """Serializer 层单元测试（Task 1 真实运行，不依赖 views）。"""
 def test_list_serializer_has_no_body_field(self, admin_user) -> None:
 from prompts.models import Prompt, PromptCategory, PromptScope
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
 "slug": "x.sys.with.project",
 "category": "aux_model",
 "scope": "system",
 "project": str(project.id),
 "title": "t",
 "body": "hi",
 }
 )
 assert not serializer.is_valid
 assert "project" in serializer.errors
 def test_create_serializer_rejects_project_without_project(
 self,
 admin_user,
 ) -> None:
 from prompts.serializers import PromptCreateSerializer
 serializer = PromptCreateSerializer(
 data={
 "slug": "x.proj.no.project",
 "category": "aux_model",
 "scope": "project",
 "title": "t",
 "body": "hi",
 }
 )
 assert not serializer.is_valid
 assert "project" in serializer.errors
 def test_detail_serializer_exposes_declared_variables(
 self,
 admin_user,
 ) -> None:
 from prompts.models import Prompt, PromptCategory, PromptScope
 from prompts.serializers import PromptDetailSerializer
 from prompts.services import append_version
 p = Prompt.objects.create(
 slug="test.serial.declared",
 category=PromptCategory.AUX_MODEL,
 scope=PromptScope.SYSTEM,
 title="t",
 created_by=admin_user,
 )
 asyncio.run(append_version(p, "Hello {{name}} {{age}}", admin_user))
 p.refresh_from_db
 data = PromptDetailSerializer(p).data
 assert data["declared_variables"] == ["name", "age"]
 assert data["active_version"]["body"] == "Hello {{name}} {{age}}"
 assert data["active_version"]["version"] == 1
