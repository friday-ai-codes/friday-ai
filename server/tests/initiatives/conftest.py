"""tests/initiatives 共享 fixtures（Phase 83 Wave 0 脚手架）。

提供同步引擎测试复用的异步工厂与飞书 httpx mock：
- ``project_doc_factory``：建 (space, project, ProjectDoc)，经 ``ProjectDocService`` 落库（INV-6）。
- ``block_map_factory``：经 ``ProjectDocService.upsert_block_map`` 落 ``ProjectDocBlockMap``。
- ``project_memory_factory``：经 ``MemoryService.append`` 落 ``ProjectMemory``（受限入口跳过成员校验）。
- ``respx_feishu``：飞书 OpenAPI httpx mock（默认放过 tenant_access_token 取号）。

工厂均为异步可调用，使用方测试须标 ``pytest.mark.django_db(transaction=True)``
（async + ``sync_to_async`` 写库需 transaction）。纯函数算法测试（``test_doc_sync_diff.py``）
不依赖这些 fixtures。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from initiatives.models import DocSection, DocSyncStatus, DocType

User = get_user_model()


@sync_to_async
def _create_space(**kw: Any) -> Any:
    from projects.models import Space

    return Space.objects.create(**kw)


@sync_to_async
def _create_user(username: str) -> Any:
    return User.objects.create_user(username=username, password="x")


@pytest.fixture
def project_doc_factory():
    """异步工厂：建 space + project + ProjectDoc 并返回该 doc（写入经 ProjectDocService）。"""
    from initiatives.services import ProjectDocService, ProjectService

    counter = {"n": 0}

    async def _make(
        *,
        doc_type: str = DocType.STATE,
        sync_status: str = DocSyncStatus.READY,
        **fields: Any,
    ) -> Any:
        counter["n"] += 1
        n = counter["n"]
        space = await _create_space(name=f"S{n}", feishu_project_key=f"k{n}")
        user = await _create_user(username=f"docu{n}")
        # 抑制真实后台 provision 派发（单测不触飞书外呼）。
        with patch.object(ProjectDocService, "provision_dispatch", return_value=None):
            project, _ = await ProjectService().create(
                space=space, name=f"P{n}", created_by=user, feishu_project_key=f"k{n}"
            )
        return await ProjectDocService().upsert_doc(
            project_id=project.id,
            doc_type=doc_type,
            sync_status=sync_status,
            **fields,
        )

    return _make


@pytest.fixture
def block_map_factory():
    """异步工厂：经 ProjectDocService 落一条 ProjectDocBlockMap。"""
    from initiatives.services import ProjectDocService

    async def _make(
        *,
        doc_id: Any,
        feishu_block_id: str,
        db_ref: str = "",
        section: str = DocSection.SYSTEM,
        content_hash: str = "",
    ) -> Any:
        return await ProjectDocService().upsert_block_map(
            doc_id=doc_id,
            feishu_block_id=feishu_block_id,
            db_ref=db_ref,
            section=section,
            content_hash=content_hash,
        )

    return _make


@pytest.fixture
def project_memory_factory():
    """异步工厂：经 MemoryService 落一条 ProjectMemory（受限入口，跳过成员校验）。"""
    from initiatives.services import MemoryService

    async def _make(
        *,
        project_id: Any,
        content: str = "记忆条目",
        contributor: Any = None,
    ) -> Any:
        return await MemoryService().append(
            project_id=project_id,
            content=content,
            contributor=contributor,
            _skip_member_check=True,
        )

    return _make


@pytest.fixture
def respx_feishu():
    """飞书 OpenAPI httpx mock（供 Wave 2+ pull/push 测试复用）。"""
    import respx

    with respx.mock(
        base_url="https://open.feishu.cn/open-apis", assert_all_called=False
    ) as router:
        router.post("/auth/v3/tenant_access_token/internal").respond(
            json={"code": 0, "tenant_access_token": "t-test", "expire": 7200}
        )
        yield router
