"""截图识别需求 REST 端点测试（Phase 35-01 Task 3，VIS-01）。

覆盖（IsAuthenticated 守卫 + 35-UI-SPEC API 契约 + 后端权威双校验）：

- 未认证 → 401/403。
- 认证 + 合法 PNG（multipart 字段 ``screenshot``）→ 200 + 透传服务 result（含 results）。
- 上传非图片（text/plain）→ 400，code 来自 validate_image_bytes（unsupported_mime_type）。
- 上传 >10MB → 400 image_too_large。
- 服务返回 degraded=true → 端点 200 透传（不当作错误）。

被 mock 的 ``recall_from_screenshot`` 不会真正调 LLM；校验分支测真实
``validate_image_bytes``（不 mock），故合法用例用真实 PNG 头字节通过 sniff。
"""

from __future__ import annotations

import base64

import pytest
from asgiref.sync import sync_to_async
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import AsyncClient
from rest_framework_simplejwt.tokens import RefreshToken

from chat.multimodal import MAX_IMAGE_BYTES

pytestmark = pytest.mark.django_db(transaction=True)

URL = "/api/delivery/screenshot-recall/"

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


async def _make_user_headers() -> dict[str, str]:
    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    user = await user_model.objects.acreate_user(
        username="shot_api_user",
        password="shot-pass-123",
    )
    token = await sync_to_async(RefreshToken.for_user)(user)
    return {"authorization": f"Bearer {token.access_token}"}


@pytest.fixture
def patch_recall(monkeypatch: pytest.MonkeyPatch) -> dict:
    """monkeypatch services.screenshot_recall.recall_from_screenshot 为 async 返回固定 dict。"""
    from services import screenshot_recall

    state: dict = {"return_value": None, "calls": []}

    async def _fake(image_bytes, mime_type, *, user, **kw):
        state["calls"].append({"mime_type": mime_type, "size": len(image_bytes)})
        return state["return_value"]

    monkeypatch.setattr(screenshot_recall, "recall_from_screenshot", _fake, raising=True)
    return state


async def test_unauthenticated_rejected() -> None:
    """未认证 → 401/403（IsAuthenticated 守卫，T-35-03）。"""
    client = AsyncClient()
    png = SimpleUploadedFile("shot.png", PNG_1X1, content_type="image/png")
    resp = await client.post(URL, data={"screenshot": png})
    assert resp.status_code in (401, 403)


async def test_valid_png_returns_200_passthrough(patch_recall) -> None:
    """合法 PNG → 200 + 透传服务 result（含 results）。"""
    patch_recall["return_value"] = {
        "degraded": False,
        "semantics": {"text": "标题", "ui_elements": "", "business_intent": "下单"},
        "query": "标题\n下单",
        "results": [
            {
                "work_item_id": "WI-1",
                "title": "下单需求",
                "relevance": 0.9,
                "source": "delivery_knowledge",
            }
        ],
    }
    headers = await _make_user_headers()
    client = AsyncClient()
    png = SimpleUploadedFile("shot.png", PNG_1X1, content_type="image/png")
    resp = await client.post(URL, data={"screenshot": png}, headers=headers)

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["degraded"] is False
    assert body["results"][0]["work_item_id"] == "WI-1"
    # 服务被调用且收到 sniff 后的 mime_type。
    assert patch_recall["calls"][0]["mime_type"] == "image/png"


async def test_non_image_rejected_400(patch_recall) -> None:
    """非图片（text/plain）→ 400 unsupported_mime_type，不调服务。"""
    headers = await _make_user_headers()
    client = AsyncClient()
    txt = SimpleUploadedFile("a.txt", b"not an image at all", content_type="text/plain")
    resp = await client.post(URL, data={"screenshot": txt}, headers=headers)

    assert resp.status_code == 400, resp.content
    assert resp.json()["code"] == "unsupported_mime_type"
    assert patch_recall["calls"] == []


async def test_oversize_rejected_400(patch_recall) -> None:
    """>10MB → 400 image_too_large，不调服务。"""
    headers = await _make_user_headers()
    client = AsyncClient()
    big = SimpleUploadedFile(
        "big.png", b"x" * (MAX_IMAGE_BYTES + 1), content_type="image/png"
    )
    resp = await client.post(URL, data={"screenshot": big}, headers=headers)

    assert resp.status_code == 400, resp.content
    assert resp.json()["code"] == "image_too_large"
    assert patch_recall["calls"] == []


async def test_missing_file_rejected_400(patch_recall) -> None:
    """缺文件 → 400 missing_image。"""
    headers = await _make_user_headers()
    client = AsyncClient()
    resp = await client.post(URL, data={}, headers=headers)

    assert resp.status_code == 400, resp.content
    assert resp.json()["code"] == "missing_image"
    assert patch_recall["calls"] == []


async def test_degraded_passthrough_200(patch_recall) -> None:
    """服务返回 degraded=true → 端点 200 透传（不当作错误）。"""
    patch_recall["return_value"] = {
        "degraded": True,
        "degraded_reason": "未配置 vision 模型",
        "semantics": None,
        "query": None,
        "results": [],
    }
    headers = await _make_user_headers()
    client = AsyncClient()
    png = SimpleUploadedFile("shot.png", PNG_1X1, content_type="image/png")
    resp = await client.post(URL, data={"screenshot": png}, headers=headers)

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["degraded"] is True
    assert body["results"] == []
