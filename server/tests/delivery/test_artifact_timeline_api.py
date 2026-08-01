"""Artifact 版本轨 / 时间线只读 REST API 守护测试（Chassis v2 · P7）。

覆盖：

- list：GET /api/delivery/artifacts/ 返回 + ?artifact_type= / ?work_item_id= / ?space_id=
  过滤 + 非法 UUID 400；含当前版本摘要。
- timeline：GET /api/delivery/artifacts/<id>/ 返回全版本时间线（倒序 + supersedes 链 +
  is_current + produced_by_ref + 当前版本 render_markdown 摘要）；不存在 404。
- downstream：GET /api/delivery/artifact-versions/<id>/downstream/ 聚合
  RepoCodingTask / SddSpec（真实 FK）+ ArchitectMerge（软 UUID）；版本不存在 404。

async + sync_to_async 跨线程写库 → transaction=True。
"""

from __future__ import annotations

import uuid

import pytest

from delivery.models import (
    ArchitectMerge,
    Artifact,
    ArtifactVersion,
    ConvergenceSession,
    RepoCodingTask,
    SddSpec,
    WorkItem,
    WorkItemOrigin,
)
from projects.models import Space
from repositories.models import Repository

pytestmark = pytest.mark.django_db(transaction=True)


def _valid_plan_content(title: str = "标题") -> dict:
    return {
        "title": title,
        "summary": "摘要",
        "execution_plan": [
            {
                "id": "t1",
                "name": "任务一",
                "repository_id": "repo-1",
                "repository_name": "repo",
                "branch_strategy": "feature",
            }
        ],
    }


def _make_repo() -> Repository:
    return Repository.objects.create(
        name=f"repo-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )


def _make_work_item(space: Space | None = None) -> WorkItem:
    return WorkItem.objects.create(
        feishu_project_key=f"pk-{uuid.uuid4().hex[:6]}",
        work_item_type="story",
        work_item_id=int(uuid.uuid4().int % 1_000_000_000),
        origin=WorkItemOrigin.MANUAL,
        space=space,
    )


def _make_artifact_with_versions(
    *,
    artifact_type: str = "technical_plan",
    work_item: WorkItem | None = None,
    version_count: int = 1,
) -> Artifact:
    """直接建 Artifact + 链式 ArtifactVersion（v1<-v2<-...），并置 current_version。"""
    artifact = Artifact.objects.create(
        artifact_type=artifact_type,
        title="时间线测试",
        work_item=work_item,
    )
    previous: ArtifactVersion | None = None
    for n in range(1, version_count + 1):
        version = ArtifactVersion.objects.create(
            artifact=artifact,
            version_no=n,
            supersedes=previous,
            content=_valid_plan_content(f"v{n}"),
            content_hash=f"hash-{n}",
            produced_by_ref=f"signal:{n}",
            produced_by_session_id=f"sess-{n}",
        )
        previous = version
    artifact.current_version = previous
    artifact.save(update_fields=["current_version"])
    return artifact


# ---- list ----


def test_list_requires_auth(api_client) -> None:
    resp = api_client.get("/api/delivery/artifacts/")
    assert resp.status_code in (401, 403)


def test_list_returns_artifacts_with_current_version(authenticated_client) -> None:
    artifact = _make_artifact_with_versions(version_count=2)
    resp = authenticated_client.get("/api/delivery/artifacts/")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    row = body[0]
    assert row["id"] == str(artifact.id)
    assert row["artifact_type"] == "technical_plan"
    assert row["current_version"]["version_no"] == 2
    assert row["current_version"]["is_current"] is True


def test_list_filter_by_artifact_type(authenticated_client) -> None:
    _make_artifact_with_versions(artifact_type="technical_plan")
    other = Artifact.objects.create(artifact_type="review_report", title="x")
    resp = authenticated_client.get("/api/delivery/artifacts/?artifact_type=review_report")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == str(other.id)


def test_list_filter_by_work_item(authenticated_client) -> None:
    wi = _make_work_item()
    target = _make_artifact_with_versions(work_item=wi)
    _make_artifact_with_versions()  # 无 work_item，不应出现
    resp = authenticated_client.get(f"/api/delivery/artifacts/?work_item_id={wi.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == str(target.id)


def test_list_filter_by_space(authenticated_client) -> None:
    space = Space.objects.create(name="s", feishu_project_key=f"sp-{uuid.uuid4().hex[:6]}")
    wi = _make_work_item(space=space)
    target = _make_artifact_with_versions(work_item=wi)
    _make_artifact_with_versions(work_item=_make_work_item())  # 别的空间
    resp = authenticated_client.get(f"/api/delivery/artifacts/?space_id={space.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == str(target.id)


def test_list_invalid_work_item_id_400(authenticated_client) -> None:
    resp = authenticated_client.get("/api/delivery/artifacts/?work_item_id=not-a-uuid")
    assert resp.status_code == 400


def test_list_invalid_space_id_400(authenticated_client) -> None:
    resp = authenticated_client.get("/api/delivery/artifacts/?space_id=not-a-uuid")
    assert resp.status_code == 400


# ---- timeline ----


def test_timeline_returns_versions_desc_with_chain(authenticated_client) -> None:
    artifact = _make_artifact_with_versions(version_count=3)
    versions = list(artifact.versions.order_by("version_no"))

    resp = authenticated_client.get(f"/api/delivery/artifacts/{artifact.id}/")
    assert resp.status_code == 200
    body = resp.json()

    # 倒序：最新在前
    assert [v["version_no"] for v in body["versions"]] == [3, 2, 1]
    latest, mid, first = body["versions"]
    # supersedes 链：v3<-v2<-v1
    assert latest["supersedes_id"] == str(versions[1].id)
    assert mid["supersedes_id"] == str(versions[0].id)
    assert first["supersedes_id"] is None
    # is_current 仅当前版本为真
    assert latest["is_current"] is True
    assert mid["is_current"] is False
    # produced_by_ref 回答"为何变成它"
    assert latest["produced_by_ref"] == "signal:3"
    # 当前版本 render_markdown 摘要（technical_plan 已注册渲染器）
    assert body["current_version_markdown"]
    assert "v3" in body["current_version_markdown"]


def test_timeline_not_found_404(authenticated_client) -> None:
    resp = authenticated_client.get(f"/api/delivery/artifacts/{uuid.uuid4()}/")
    assert resp.status_code == 404


# ---- downstream ----


def test_downstream_aggregates_references(authenticated_client) -> None:
    artifact = _make_artifact_with_versions(version_count=1)
    version = artifact.current_version
    repo = _make_repo()

    coding = RepoCodingTask.objects.create(artifact_version=version, repository=repo, wave=0)
    spec = SddSpec.objects.create(artifact_version=version, repository=repo)
    session = ConvergenceSession.objects.create(
        process_type="technical_plan", entrypoint="workflow"
    )
    merge = ArchitectMerge.objects.create(session=session, merged_artifact_version=version.id)

    resp = authenticated_client.get(f"/api/delivery/artifact-versions/{version.id}/downstream/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["artifact_version_id"] == str(version.id)
    assert [t["id"] for t in body["coding_tasks"]] == [str(coding.id)]
    assert [s["id"] for s in body["sdd_specs"]] == [str(spec.id)]
    assert [m["id"] for m in body["architect_merges"]] == [str(merge.id)]
    assert body["architect_merges"][0]["session_id"] == str(session.id)
    assert body["total"] == 3


def test_downstream_empty_when_no_references(authenticated_client) -> None:
    artifact = _make_artifact_with_versions(version_count=1)
    version = artifact.current_version
    resp = authenticated_client.get(f"/api/delivery/artifact-versions/{version.id}/downstream/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["coding_tasks"] == []


def test_downstream_version_not_found_404(authenticated_client) -> None:
    resp = authenticated_client.get(f"/api/delivery/artifact-versions/{uuid.uuid4()}/downstream/")
    assert resp.status_code == 404


# ---- blueprint/v1 判别两键（同步点 2 收尾） ----
#
# ⭐ 蓝图与 v0 旧方案**共用 artifact_type="technical_plan"**（DESIGN §3.1：按
# content.schema_version 判别，不新增 artifact_type）⇒ 在这个只读面上两者此前长得一模
# 一样，前端 `ArtifactTimeline.vue` 分不出哪条是带批注与人审的结构化蓝图。两键**纯追加**，
# 既有八键一字未动。


def test_list_marks_a_v0_artifact_with_empty_discriminators(authenticated_client) -> None:
    """⭐ v0 旧方案：两键**恒空串**（合法取值，⛔ 不是 null / 不是缺键）。

    与下一条**正反并列**：只断言蓝图那一档会漏掉「两档都被标成蓝图」的假通过。
    """
    _make_artifact_with_versions()
    row = authenticated_client.get("/api/delivery/artifacts/").json()[0]
    assert row["schema_version"] == ""
    assert row["current_status"] == ""


def test_list_marks_a_blueprint_artifact(authenticated_client) -> None:
    """⭐ blueprint/v1：`schema_version` 与 11 态 `current_status` 如实回。

    ⚠️ 状态键名刻意**不是模型字段名**（INV-6 字段级守卫扫全 server/），全仓蓝图
    响应体统一用 `current_status`。
    """
    artifact = _make_artifact_with_versions()
    ArtifactVersion.objects.filter(id=artifact.current_version_id).update(
        content={"schema_version": "blueprint/v1", "meta": {"title": "蓝图"}}
    )
    Artifact.objects.filter(id=artifact.id).update(blueprint_status="pending_review")

    row = authenticated_client.get("/api/delivery/artifacts/").json()[0]
    assert row["schema_version"] == "blueprint/v1"
    assert row["current_status"] == "pending_review"
    # 既有八键一个不少（纯追加）。
    assert {"id", "artifact_type", "title", "status", "work_item_id"} <= set(row)


def test_timeline_detail_carries_the_same_two_discriminators(authenticated_client) -> None:
    """时间线详情继承同两键（详情序列化器派生自列表序列化器，⛔ 不各写一份）。"""
    artifact = _make_artifact_with_versions()
    ArtifactVersion.objects.filter(id=artifact.current_version_id).update(
        content={"schema_version": "blueprint/v1", "meta": {"title": "蓝图"}}
    )
    Artifact.objects.filter(id=artifact.id).update(blueprint_status="confirmed")

    body = authenticated_client.get(f"/api/delivery/artifacts/{artifact.id}/").json()
    assert body["schema_version"] == "blueprint/v1"
    assert body["current_status"] == "confirmed"


def test_discriminator_is_not_derived_from_artifact_type(authenticated_client) -> None:
    """⛔ 判别只看 content.schema_version：同 artifact_type 的两条必须分得开。"""
    v0 = _make_artifact_with_versions()
    bp = _make_artifact_with_versions()
    ArtifactVersion.objects.filter(id=bp.current_version_id).update(
        content={"schema_version": "blueprint/v1", "meta": {"title": "蓝图"}}
    )

    rows = {r["id"]: r for r in authenticated_client.get("/api/delivery/artifacts/").json()}
    assert rows[str(v0.id)]["artifact_type"] == rows[str(bp.id)]["artifact_type"]
    assert rows[str(v0.id)]["schema_version"] == ""
    assert rows[str(bp.id)]["schema_version"] == "blueprint/v1"
