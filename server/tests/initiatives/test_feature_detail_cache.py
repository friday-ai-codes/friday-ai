"""功能点详情结构化缓存守护测试。

覆盖「解析时生成一次并存起来、点开不再重算」：
- ``aget_or_generate``：首次未命中调 LLM 生成并写缓存；再次命中缓存**不再调 LLM**。
- ``awarm`` + ``aget_cached_map``：预热后可批量按原文取回已缓存 sections。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from initiatives.models import FeatureDetailCache
from initiatives.services import ProjectDocService
from initiatives.services.feature_detail_service import feature_detail_service
from permissions.models import SpaceMembership, SpaceRole
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()

_GEN = "initiatives.services.feature_list_import.agenerate_feature_detail_sections"


@pytest.fixture(autouse=True)
def _silence_provision():
    with patch.object(ProjectDocService, "provision_dispatch", return_value=None):
        yield


@pytest.fixture
def space(db) -> Space:
    return Space.objects.create(name="FDC Space", feishu_project_key="fdc-space-key")


@pytest.fixture
def admin(db, space) -> object:
    u = User.objects.create_user(username="fdc_admin", password="x")
    SpaceMembership.objects.create(user=u, space=space, role=SpaceRole.ADMIN)
    return u


def _create_project(client, space, key="fdc-1") -> str:
    resp = client.post(
        "/api/projects/",
        {"space_id": str(space.id), "name": "P", "feishu_project_key": key},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    return resp.json()["id"]


def test_generate_once_then_cache_hit(space, admin):
    client = APIClient()
    client.force_authenticate(user=admin)
    project_id = _create_project(client, space)

    sections = [{"title": "功能描述", "type": "text", "content": "x"}]
    gen = AsyncMock(return_value=sections)
    with patch(_GEN, new=gen):
        out1 = async_to_sync(feature_detail_service.aget_or_generate)(project_id, "原文A")
        out2 = async_to_sync(feature_detail_service.aget_or_generate)(project_id, "原文A")

    assert out1 == sections
    assert out2 == sections
    # 第二次命中缓存，绝不再调 LLM。
    assert gen.await_count == 1
    assert FeatureDetailCache.objects.filter(project_id=project_id).count() == 1


def test_warm_then_cached_map(space, admin):
    client = APIClient()
    client.force_authenticate(user=admin)
    project_id = _create_project(client, space, key="fdc-2")

    gen = AsyncMock(return_value=[{"title": "T", "type": "text", "content": "c"}])
    with patch(_GEN, new=gen):
        warmed = async_to_sync(feature_detail_service.awarm)(
            project_id, ["s1", "s2", "s2", ""]
        )
    assert warmed == 2  # 去重 + 去空
    cached = async_to_sync(feature_detail_service.aget_cached_map)(
        project_id, ["s1", "s2", "unknown"]
    )
    assert set(cached.keys()) == {"s1", "s2"}
