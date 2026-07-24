"""PRD 正文快照只读 REST 端点守护测试（Phase 30-04）。

端到端兑现 DOC-02 成功标准 3——"给定带 prd_url 的 WorkItem（三元组），可经
``Document`` 实体检索到其 PRD 正文快照"：

- 命中：force_authenticate → GET prd-document 三元组 → 200 + content==PRD 正文快照
  （经 Document.current_version.content 检索）+ document_type=="prd" + content_storage=="both"。
- 未认证：匿名 GET → 401（IsAuthenticated 守卫，T-30-09）。
- 参数：缺三元组 / work_item_id 非整数 → 400。
- 未命中：WorkItem 不存在 → 404；WorkItem 存在但无 PRD Document → 404（明确语义）。
- 只读不写（T-30-10）：请求前后 Document/DocumentVersion 行数不变（端点纯读）。

Document 夹具经 ``DocumentService.upsert_from_feishu`` 建（守 INV-6，不旁路 ORM 写
Document）；端点不回源，pytest-socket 隔离零真实网络（无需 respx）。异步 +
sync_to_async 跨线程写库 → transaction=True。
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async
from django.test import AsyncClient
from rest_framework_simplejwt.tokens import RefreshToken

from delivery.models import Document, DocumentVersion, WorkItem, WorkItemOrigin
from delivery.services import DocumentService

pytestmark = pytest.mark.django_db(transaction=True)

# DOMAIN §16 实测自然键 + 多租户深链
PROJECT_KEY = "000000000000000000000001"
STORY_ID = 1000000002
DOC_TOKEN = "Abcd1234efGhIjKl"
PRD_URL = f"https://acme.feishu.cn/docx/{DOC_TOKEN}"
PRD_BODY = "PRD 正文快照"

ENDPOINT = "/api/delivery/work-items/prd-document/"


async def _make_user_headers() -> dict[str, str]:
    """创建测试用户 + JWT Bearer 头（async）。"""
    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    user = await user_model.objects.acreate_user(
        username="prd_doc_api_user",
        password="prd-doc-pass-123",
    )
    token = await sync_to_async(RefreshToken.for_user)(user)
    return {"authorization": f"Bearer {token.access_token}"}


async def _make_work_item(work_item_id: int = STORY_ID) -> WorkItem:
    """建一个 story WorkItem（origin=manual）。"""
    return await WorkItem.objects.acreate(
        feishu_project_key=PROJECT_KEY,
        work_item_type="story",
        work_item_id=work_item_id,
        origin=WorkItemOrigin.MANUAL,
        title="测试需求",
    )


async def _make_prd_document(work_item: WorkItem, content: str = PRD_BODY) -> Document:
    """经 DocumentService 建 PRD Document 夹具（守 INV-6，不旁路 ORM 写）。"""
    return await DocumentService().upsert_from_feishu(
        work_item=work_item,
        document_type="prd",
        doc_token=DOC_TOKEN,
        content=content,
        canonical_url=PRD_URL,
        source=WorkItemOrigin.MANUAL,
    )


# ============================================================================
# 命中：经 Document 实体检索到 PRD 正文快照（DOC-02 成功标准 3）
# ============================================================================


async def test_returns_prd_snapshot_via_document_entity() -> None:
    """命中已落库 WorkItem 的 PRD Document → 200 + content 为 current_version 正文。"""
    headers = await _make_user_headers()
    work_item = await _make_work_item()
    await _make_prd_document(work_item)

    client = AsyncClient()
    resp = await client.get(
        ENDPOINT,
        {
            "feishu_project_key": PROJECT_KEY,
            "work_item_type": "story",
            "work_item_id": STORY_ID,
        },
        headers=headers,
    )

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["content"] == PRD_BODY
    assert body["document_type"] == "prd"
    assert body["content_storage"] == "both"
    assert body["external_ref"] == DOC_TOKEN
    assert body["feishu_tenant"] == "acme"
    assert body["version"] == 1


# ============================================================================
# 认证（T-30-09）
# ============================================================================


async def test_unauthenticated_rejected() -> None:
    """匿名 GET → 401（IsAuthenticated 守卫，T-30-09）。"""
    work_item = await _make_work_item()
    await _make_prd_document(work_item)

    client = AsyncClient()
    resp = await client.get(
        ENDPOINT,
        {
            "feishu_project_key": PROJECT_KEY,
            "work_item_type": "story",
            "work_item_id": STORY_ID,
        },
    )
    assert resp.status_code in (401, 403)


# ============================================================================
# 参数校验
# ============================================================================


async def test_missing_triple_params_400() -> None:
    """缺三元组参数 → 400。"""
    headers = await _make_user_headers()

    client = AsyncClient()
    resp = await client.get(
        ENDPOINT,
        {"feishu_project_key": PROJECT_KEY},
        headers=headers,
    )
    assert resp.status_code == 400


async def test_invalid_work_item_id_400() -> None:
    """work_item_id 非整数 → 400。"""
    headers = await _make_user_headers()

    client = AsyncClient()
    resp = await client.get(
        ENDPOINT,
        {
            "feishu_project_key": PROJECT_KEY,
            "work_item_type": "story",
            "work_item_id": "abc",
        },
        headers=headers,
    )
    assert resp.status_code == 400


# ============================================================================
# 未命中：明确 404（不臆造空文档）
# ============================================================================


async def test_missing_work_item_404() -> None:
    """WorkItem 不存在 → 404。"""
    headers = await _make_user_headers()

    client = AsyncClient()
    resp = await client.get(
        ENDPOINT,
        {
            "feishu_project_key": PROJECT_KEY,
            "work_item_type": "story",
            "work_item_id": 999999,
        },
        headers=headers,
    )
    assert resp.status_code == 404


async def test_work_item_without_prd_document_404() -> None:
    """WorkItem 存在但未建 PRD Document → 404（明确语义，不返回空文档）。"""
    headers = await _make_user_headers()
    await _make_work_item()

    client = AsyncClient()
    resp = await client.get(
        ENDPOINT,
        {
            "feishu_project_key": PROJECT_KEY,
            "work_item_type": "story",
            "work_item_id": STORY_ID,
        },
        headers=headers,
    )
    assert resp.status_code == 404


# ============================================================================
# 只读不写（T-30-10）
# ============================================================================


async def test_endpoint_is_read_only_no_row_change() -> None:
    """端点纯读：请求前后 Document/DocumentVersion 行数不变。"""
    headers = await _make_user_headers()
    work_item = await _make_work_item()
    await _make_prd_document(work_item)

    docs_before = await Document.objects.acount()
    versions_before = await DocumentVersion.objects.acount()

    client = AsyncClient()
    resp = await client.get(
        ENDPOINT,
        {
            "feishu_project_key": PROJECT_KEY,
            "work_item_type": "story",
            "work_item_id": STORY_ID,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.content

    assert await Document.objects.acount() == docs_before
    assert await DocumentVersion.objects.acount() == versions_before
