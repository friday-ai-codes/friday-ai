"""蓝图 confirmed 后 provided HTTP 契约回流项目 API 清单（quick 260806-sif）。

守四件事（正反并列，断言一律 DB 重读）：

1. **回流成立**：pending_review → confirmed 后，content.api_contracts 里 provided+http
   且 method/path 非空的契约在 ``ProjectStateApi`` 生成 ``status=planned``、
   ``source=agent``、``description=契约 name`` 的行。
2. **筛选口径**：consumed / kind != http / method 为空 的契约一律不落行。
3. **现状优先（幂等）**：已存在同 (method, path) 条目（如 implemented/manual）在 confirm
   后逐字原样——``upsert_state_api`` 是 get_or_create 语义，⛔ 不覆盖。
4. **best-effort**：回流抛异常不阻断 confirmed 转移本身（状态已 CAS 落库）。

构造范式照 ``test_blueprint_review_threads._make_artifact``（confirm 守卫要求
pending_review 且无阻塞线程——不开任何线程即可）与
``test_blueprint_intake._make_project``（ProjectStateApi 有 Project FK，项目须真实存在）。
content 手拼 dict 直接 ORM 建版本（不过 schema 校验），tests 豁免 INV-6。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest
from asgiref.sync import sync_to_async

from delivery.models import Artifact, ArtifactVersion, BlueprintStatus
from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService

pytestmark = pytest.mark.django_db(transaction=True)

_PROJECT_ID = "44444444-4444-4444-4444-444444444444"


# ══════════════════════════════════════════════════════════════════════════
# 数据工厂
# ══════════════════════════════════════════════════════════════════════════


@sync_to_async
def _make_project(project_id: str = _PROJECT_ID) -> Any:
    """建一个 ``initiatives.Project``（工厂形状照 ``test_blueprint_intake._make_project``）。"""
    from initiatives.models import Project
    from projects.models import Space

    project = Project.objects.filter(id=project_id).first()
    if project is None:
        space, _ = Space.objects.get_or_create(
            name=f"space-{project_id[:8]}",
            defaults={"feishu_project_key": f"k-{project_id[:8]}"},
        )
        project = Project.objects.create(id=project_id, space=space, name=f"proj-{project_id[:8]}")
    return project


@sync_to_async
def _make_pending_review_artifact(contracts: list[dict], *, project_id: str = _PROJECT_ID) -> Any:
    """pending_review 蓝图 + 手拼 content 的 v1 版本（直接 ORM，tests 豁免 INV-6）。"""
    artifact = Artifact.objects.create(
        artifact_type="technical_plan", blueprint_status=BlueprintStatus.PENDING_REVIEW
    )
    version = ArtifactVersion.objects.create(
        artifact=artifact,
        version_no=1,
        content={"meta": {"project_id": project_id}, "api_contracts": contracts},
    )
    artifact.current_version = version
    artifact.save(update_fields=["current_version"])
    return artifact


def _contract(
    contract_id: str,
    *,
    direction: str = "provided",
    kind: str = "http",
    method: str = "POST",
    path: str = "",
    name: str = "",
) -> dict:
    return {
        "id": contract_id,
        "name": name or f"契约 {contract_id}",
        "kind": kind,
        "direction": direction,
        "method": method,
        "path": path or f"/api/{contract_id}/",
    }


async def _api_rows(project_id: str = _PROJECT_ID) -> list[Any]:
    from initiatives.models import ProjectStateApi

    return [
        row async for row in ProjectStateApi.objects.filter(project_id=project_id).order_by("path")
    ]


async def _db_status(artifact: Any) -> str:
    fresh = await Artifact.objects.aget(id=artifact.id)
    return fresh.blueprint_status


# ══════════════════════════════════════════════════════════════════════════
# 用例
# ══════════════════════════════════════════════════════════════════════════


async def test_confirm_syncs_provided_http_contracts_to_state_apis() -> None:
    """① provided+http 契约在 confirmed 后落 ProjectStateApi（planned/agent/name）。"""
    await _make_project()
    artifact = await _make_pending_review_artifact(
        [
            _contract("api_a", method="POST", path="/api/orders/", name="下单接口"),
            _contract("api_b", method="GET", path="/api/orders/{id}/", name="订单详情"),
        ]
    )

    await BlueprintLifecycleService().transition(
        artifact, BlueprintStatus.CONFIRMED, initiated_by_user_id="u1"
    )

    assert await _db_status(artifact) == BlueprintStatus.CONFIRMED
    rows = await _api_rows()
    assert [(r.method, r.path) for r in rows] == [
        ("POST", "/api/orders/"),
        ("GET", "/api/orders/{id}/"),
    ]
    for row in rows:
        assert row.status == "planned"
        assert row.source == "agent"
    assert rows[0].description == "下单接口"
    assert rows[1].description == "订单详情"


async def test_confirm_skips_consumed_non_http_and_incomplete_contracts() -> None:
    """② consumed / kind=event / method 为空 三类契约均不落行。"""
    await _make_project()
    artifact = await _make_pending_review_artifact(
        [
            _contract("api_c", direction="consumed", path="/api/upstream/"),
            _contract("api_d", kind="event", path="/topic/order-created"),
            _contract("api_e", method="", path="/api/no-method/"),
        ]
    )

    await BlueprintLifecycleService().transition(
        artifact, BlueprintStatus.CONFIRMED, initiated_by_user_id="u1"
    )

    assert await _db_status(artifact) == BlueprintStatus.CONFIRMED
    assert await _api_rows() == []


async def test_confirm_does_not_overwrite_existing_state_api_row() -> None:
    """③ 已存在同 (method, path) 条目原样保留（get_or_create 不覆盖，现状优先）。"""
    from initiatives.models.project_state_api import ApiSource, ApiStatus
    from initiatives.services.project_doc_service import ProjectDocService

    await _make_project()
    existing, created = await ProjectDocService().upsert_state_api(
        project_id=_PROJECT_ID,
        method="POST",
        path="/api/orders/",
        description="人工录入的现状条目",
        status=ApiStatus.IMPLEMENTED,
        source=ApiSource.MANUAL,
        initiated_by_user_id="human",
    )
    assert created

    artifact = await _make_pending_review_artifact(
        [_contract("api_a", method="POST", path="/api/orders/", name="下单接口")]
    )
    await BlueprintLifecycleService().transition(
        artifact, BlueprintStatus.CONFIRMED, initiated_by_user_id="u1"
    )

    rows = await _api_rows()
    assert len(rows) == 1
    fresh = rows[0]
    assert fresh.id == existing.id
    assert fresh.status == ApiStatus.IMPLEMENTED
    assert fresh.source == ApiSource.MANUAL
    assert fresh.description == "人工录入的现状条目"


async def test_confirm_survives_state_api_sync_failure() -> None:
    """④ 回流抛异常（best-effort 吞掉）⇒ transition 正常返回且 DB 已 confirmed。"""
    from initiatives.services.project_doc_service import ProjectDocService

    await _make_project()
    artifact = await _make_pending_review_artifact(
        [_contract(f"api_{uuid.uuid4().hex[:6]}", path="/api/boom/")]
    )

    with patch.object(ProjectDocService, "upsert_state_api", side_effect=RuntimeError("sync boom")):
        result = await BlueprintLifecycleService().transition(
            artifact, BlueprintStatus.CONFIRMED, initiated_by_user_id="u1"
        )

    assert result.blueprint_status == BlueprintStatus.CONFIRMED
    assert await _db_status(artifact) == BlueprintStatus.CONFIRMED
    assert await _api_rows() == []
