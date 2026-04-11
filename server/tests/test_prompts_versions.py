"""PromptVersion append-only + 幂等 + activate pointer flip 测试。"""
from __future__ import annotations
import pytest
from prompts.models import Prompt, PromptCategory, PromptScope, PromptVersion
from prompts.services import (
 activate_version,
 append_version,
 compute_version_diff,
)
@pytest.mark.django_db(transaction=True)
class TestPromptVersioning:
 async def test_append_version_increments_version_number(
 self, admin_user
 ) -> None:
 prompt = await Prompt.objects.acreate(
 slug="versioning.inc",
 category=PromptCategory.AUX_MODEL,
 scope=PromptScope.SYSTEM,
 title="t",
 created_by=admin_user,
 )
 v1 = await append_version(prompt, "body v1", admin_user)
 v2 = await append_version(prompt, "body v2", admin_user)
 v3 = await append_version(prompt, "body v3", admin_user)
 assert v1.version == 1
 assert v2.version == 2
 assert v3.version == 3
 # active_version 指针应指向最新版本
 await prompt.arefresh_from_db(fields=["active_version"])
 active_id = prompt.active_version_id
 assert active_id == v3.id
 async def test_append_version_idempotent_on_byte_equal_body(
 self, admin_user
 ) -> None:
 prompt = await Prompt.objects.acreate(
 slug="versioning.idempotent",
 category=PromptCategory.AUX_MODEL,
 scope=PromptScope.SYSTEM,
 title="t",
 created_by=admin_user,
 )
 v1 = await append_version(prompt, "same body", admin_user)
 v2 = await append_version(prompt, "same body", admin_user)
 # 幂等:第二次返回同一实例,版本号不递增
 assert v1.id == v2.id
 assert v1.version == v2.version == 1
 # DB 中仍只有 1 条版本记录
 count = await PromptVersion.objects.filter(prompt=prompt).acount
 assert count == 1
 async def test_append_version_non_idempotent_on_different_body(
 self, admin_user
 ) -> None:
 """字节差异即生成新版本(防退化)。"""
 prompt = await Prompt.objects.acreate(
 slug="versioning.diff",
 category=PromptCategory.AUX_MODEL,
 scope=PromptScope.SYSTEM,
 title="t",
 created_by=admin_user,
 )
 v1 = await append_version(prompt, "body", admin_user)
 v2 = await append_version(prompt, "body ", admin_user) # 尾随空格
 assert v1.id != v2.id
 assert v2.version == 2
 async def test_activate_version_switches_pointer_only(
 self, admin_user
 ) -> None:
 prompt = await Prompt.objects.acreate(
 slug="versioning.activate",
 category=PromptCategory.AUX_MODEL,
 scope=PromptScope.SYSTEM,
 title="t",
 created_by=admin_user,
 )
 v1 = await append_version(prompt, "v1", admin_user)
 await append_version(prompt, "v2", admin_user)
 # 当前 active=v2;切回 v1
 await activate_version(prompt, v1)
 await prompt.arefresh_from_db(fields=["active_version"])
 assert prompt.active_version_id == v1.id
 # 确认没有创建新版本(仍然 2 条)
 count = await PromptVersion.objects.filter(prompt=prompt).acount
 assert count == 2
 async def test_activate_to_earlier_version_rollback(
 self, admin_user
 ) -> None:
 """回滚到早期版本后 body 不被修改。"""
 prompt = await Prompt.objects.acreate(
 slug="versioning.rollback",
 category=PromptCategory.AUX_MODEL,
 scope=PromptScope.SYSTEM,
 title="t",
 created_by=admin_user,
 )
 v1 = await append_version(prompt, "original", admin_user)
 await append_version(prompt, "modified", admin_user)
 await activate_version(prompt, v1)
 await prompt.arefresh_from_db(fields=["active_version"])
 fresh_v1 = await PromptVersion.objects.aget(pk=v1.id)
 assert fresh_v1.body == "original"
 async def test_compute_version_diff_unified_format(
 self, admin_user
 ) -> None:
 prompt = await Prompt.objects.acreate(
 slug="versioning.diff_fmt",
 category=PromptCategory.AUX_MODEL,
 scope=PromptScope.SYSTEM,
 title="t",
 created_by=admin_user,
 )
 v1 = await append_version(prompt, "line1\nline2\nline3\n", admin_user)
 v2 = await append_version(
 prompt, "line1\nline2 changed\nline3\n", admin_user
 )
 diff = compute_version_diff(v1, v2)
 assert "---" in diff
 assert "+++" in diff
 assert "@@" in diff
 assert "line2 changed" in diff
