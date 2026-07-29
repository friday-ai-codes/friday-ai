"""blueprint/v1 content 经 ArtifactService 落库接线测试（PLAN 111-01 Task 3）。

覆盖：合法蓝图落 Artifact + v1（SCHEMA-01）/ 缺段被 ArtifactContentInvalid 拒 /
v0 content 走原 validate_technical_plan 路径零回归 / add_version 版本链 +
diff_blueprint_blocks 端到端（SCHEMA-07）。
"""

from __future__ import annotations

import copy

import pytest

from delivery.models import ArtifactVersion
from delivery.services import ArtifactContentInvalid, ArtifactService
from services.process_runtime.blueprint_schema import diff_blueprint_blocks
from tests.helpers.blueprint_samples import make_blueprint

pytestmark = pytest.mark.django_db(transaction=True)


async def test_blueprint_content_creates_artifact_v1():
    svc = ArtifactService()
    artifact = await svc.create(
        artifact_type="technical_plan",
        content=make_blueprint(),
        created_by_user_id="tester",
    )
    assert artifact.artifact_type == "technical_plan"
    v1 = await ArtifactVersion.objects.aget(id=artifact.current_version_id)
    assert v1.version_no == 1
    assert v1.content["schema_version"] == "blueprint/v1"


async def test_blueprint_missing_section_rejected():
    content = make_blueprint()
    content.pop("interaction_flows")
    svc = ArtifactService()
    with pytest.raises(ArtifactContentInvalid):
        await svc.create(artifact_type="technical_plan", content=content)


async def test_v0_content_still_passes_original_validation():
    # v0 最小样例（无 schema_version）走原 validate_technical_plan 路径。
    # 已实测该样例判定为合法（title/summary 非空 + execution_plan 数组无 minItems），
    # 固化断言：创建成功（v0 行为零变化）。
    svc = ArtifactService()
    artifact = await svc.create(
        artifact_type="technical_plan",
        content={"title": "t", "summary": "s", "execution_plan": []},
    )
    assert artifact.current_version_id is not None


def test_discriminator_follows_schema_module_constant(monkeypatch):
    """MN-10：判别分支跟随 blueprint_schema 的唯一常量，不复制字面量。

    把常量改成 ``blueprint/v2`` 后，带该 schema_version 的 content 必须仍走
    ``validate_blueprint``——否则新版蓝图会静默落到 v0 校验路径上。
    """
    import services.process_runtime.blueprint_schema as schema_module
    from delivery.artifacts.builtin_types import _validate_technical_plan

    hits: list[dict] = []

    def _fake_validate(content):
        hits.append(content)
        return True, None

    monkeypatch.setattr(schema_module, "BLUEPRINT_SCHEMA_VERSION", "blueprint/v2")
    monkeypatch.setattr(schema_module, "validate_blueprint", _fake_validate)

    ok, err = _validate_technical_plan({"schema_version": "blueprint/v2"})
    assert (ok, err) == (True, None)
    assert len(hits) == 1


async def test_v0_invalid_content_still_rejected():
    # v0 缺 execution_plan 仍被原 schema 拒（回归面双向验证）。
    svc = ArtifactService()
    with pytest.raises(ArtifactContentInvalid):
        await svc.create(artifact_type="technical_plan", content={"title": "只有标题"})


async def test_add_version_supersedes_and_block_diff_end_to_end():
    svc = ArtifactService()
    v1_content = make_blueprint()
    artifact = await svc.create(
        artifact_type="technical_plan",
        content=v1_content,
        created_by_user_id="tester",
    )
    v1 = await ArtifactVersion.objects.aget(id=artifact.current_version_id)

    v2_content = copy.deepcopy(v1_content)
    changed_block = v2_content["meta"]["summary"][0]
    changed_block["text"] = "修改后的执行摘要（触发新版本）。"
    v2 = await svc.add_version(artifact, v2_content)

    assert v2.version_no == 2
    assert v2.supersedes_id == v1.id
    await artifact.arefresh_from_db()
    assert artifact.current_version_id == v2.id

    diff = diff_blueprint_blocks(v1.content, v2.content)
    assert diff["modified"] == [changed_block["block_id"]]
    assert diff["added"] == []
    assert diff["removed"] == []
