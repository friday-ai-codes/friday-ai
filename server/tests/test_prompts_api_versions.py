"""Prompt Versions API 集成测试（Plan Task 4 填实）。
覆盖：list / diff / activate pointer flip / 回滚场景 / RBAC。
"""
from __future__ import annotations
import asyncio
import pytest
from django.urls import reverse
from prompts.models import Prompt, PromptCategory, PromptScope, PromptVersion
from prompts.services import append_version
def _make_versioned_prompt(
 admin_user,
 slug: str,
 bodies: list[str],
) -> Prompt:
 p = Prompt.objects.create(
 slug=slug,
 category=PromptCategory.AUX_MODEL,
 scope=PromptScope.SYSTEM,
 title="t",
 created_by=admin_user,
 )
 for body in bodies:
 asyncio.run(append_version(p, body, admin_user))
 p.refresh_from_db
 return p
@pytest.mark.django_db(transaction=True)
class TestPromptVersionsAPI:
 """Versions list / diff / activate 集成测试。"""
 def test_versions_list_returns_desc_order(
 self,
 authenticated_admin_client,
 admin_user,
 ) -> None:
 p = _make_versioned_prompt(admin_user, "v.list", ["v1", "v2", "v3"])
 url = reverse("prompt-versions", kwargs={"prompt_id": p.id})
 resp = authenticated_admin_client.get(url)
 assert resp.status_code == 200, resp.content
 versions = resp.json
 assert len(versions) == 3
 assert [v["version"] for v in versions] == [3, 2, 1]
 assert [v["body"] for v in versions] == ["v3", "v2", "v1"]
 def test_version_diff_unified_format(
 self,
 authenticated_admin_client,
 admin_user,
 ) -> None:
 p = _make_versioned_prompt(
 admin_user,
 "v.diff",
 ["Line 1\nLine 2\nLine 3\n", "Line 1\nChanged\nLine 3\n"],
 )
 url = reverse(
 "prompt-version-diff",
 kwargs={"prompt_id": p.id, "v1_num": 1, "v2_num": 2},
 )
 resp = authenticated_admin_client.get(url)
 assert resp.status_code == 200, resp.content
 body = resp.json
 assert body["v1"] == 1
 assert body["v2"] == 2
 diff_text = body["diff"]
 assert "---" in diff_text
 assert "+++" in diff_text
 assert "@@" in diff_text
 assert "-Line 2" in diff_text
 assert "+Changed" in diff_text
 def test_version_diff_non_existent_version_404(
 self,
 authenticated_admin_client,
 admin_user,
 ) -> None:
 p = _make_versioned_prompt(admin_user, "v.404", ["only"])
 url = reverse(
 "prompt-version-diff",
 kwargs={"prompt_id": p.id, "v1_num": 1, "v2_num": 999},
 )
 resp = authenticated_admin_client.get(url)
 assert resp.status_code == 404, resp.content
 def test_activate_version_switches_pointer(
 self,
 authenticated_admin_client,
 admin_user,
 ) -> None:
 p = _make_versioned_prompt(
 admin_user, "act.pointer", ["v1", "v2", "v3"]
 )
 # current active = v3
 assert p.active_version is not None
 assert p.active_version.version == 3
 v1 = PromptVersion.objects.get(prompt=p, version=1)
 url = reverse(
 "prompt-activate",
 kwargs={"prompt_id": p.id, "version_id": v1.id},
 )
 resp = authenticated_admin_client.post(url)
 assert resp.status_code == 200, resp.content
 p.refresh_from_db
 assert p.active_version is not None
 assert p.active_version.version == 1
 def test_activate_does_not_create_new_version(
 self,
 authenticated_admin_client,
 admin_user,
 ) -> None:
 p = _make_versioned_prompt(admin_user, "act.no_new", ["v1", "v2"])
 before_count = p.versions.count
 v1 = PromptVersion.objects.get(prompt=p, version=1)
 url = reverse(
 "prompt-activate",
 kwargs={"prompt_id": p.id, "version_id": v1.id},
 )
 resp = authenticated_admin_client.post(url)
 assert resp.status_code == 200, resp.content
 p.refresh_from_db
 # 版本数不变，activate 只是 pointer flip
 assert p.versions.count == before_count
 def test_activate_to_earlier_version_rollback(
 self,
 authenticated_admin_client,
 admin_user,
 ) -> None:
 p = _make_versioned_prompt(
 admin_user, "act.rollback", ["initial", "broken", "fixed"]
 )
 v1 = PromptVersion.objects.get(prompt=p, version=1)
 url = reverse(
 "prompt-activate",
 kwargs={"prompt_id": p.id, "version_id": v1.id},
 )
 resp = authenticated_admin_client.post(url)
 assert resp.status_code == 200, resp.content
 detail = resp.json
 assert detail["active_version"]["body"] == "initial"
 assert detail["active_version"]["version"] == 1
 def test_activate_system_prompt_non_superuser_forbidden(
 self,
 authenticated_client, # 普通登录用户（非 superuser）
 admin_user,
 ) -> None:
 p = _make_versioned_prompt(admin_user, "act.403", ["v1", "v2"])
 v1 = PromptVersion.objects.get(prompt=p, version=1)
 url = reverse(
 "prompt-activate",
 kwargs={"prompt_id": p.id, "version_id": v1.id},
 )
 resp = authenticated_client.post(url)
 assert resp.status_code == 403, resp.content
 assert resp.json["error"] == "permission_denied"
