"""FeishuDocClient.create_folder 单元测试（82-02 Task 1）。

覆盖四种响应形状：
- code==0 → 返回 data.token
- code==99991400（限流）→ 重试后成功 / 持续限流抛 RateLimitError
- code!=0 其它 → FeishuDocAPIError
- 返回体缺 token → FeishuDocAPIError

镜像既有 ``test_feishu_doc_errors.py`` 的 mock 范式（patch httpx.AsyncClient + 预置
``get_tenant_access_token`` 跳过真实鉴权）；并 patch ``asyncio.sleep`` 让 @retry 退避瞬时，
避免单测因 wait_exponential 阻塞。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.feishu_doc import (
    FeishuDocAPIError,
    FeishuDocClient,
    RateLimitError,
)


@pytest.fixture
def client() -> FeishuDocClient:
    return FeishuDocClient(app_id="test-id", app_secret="test-secret")


def _resp(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    return resp


def _patch_httpx(post_mock: AsyncMock):
    """构造 httpx.AsyncClient 上下文管理器 mock，post 走传入的 AsyncMock。"""
    mock_client = AsyncMock()
    mock_client.post = post_mock
    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_cls


@pytest.mark.asyncio
async def test_create_folder_success_returns_token(client: FeishuDocClient) -> None:
    post = AsyncMock(return_value=_resp({"code": 0, "data": {"token": "fldcnNEW"}}))
    with patch.object(client, "get_tenant_access_token", return_value="fake-token"):
        with patch("httpx.AsyncClient", _patch_httpx(post)):
            token = await client.create_folder(name="P 工作区", folder_token="fldcnPARENT")
    assert token == "fldcnNEW"
    # 校验端点 + body 形状
    _, kwargs = post.call_args
    assert kwargs["json"] == {"name": "P 工作区", "folder_token": "fldcnPARENT"}


@pytest.mark.asyncio
async def test_create_folder_rate_limit_then_success(client: FeishuDocClient) -> None:
    """99991400 限流一次后成功（@retry 退避，asyncio.sleep 被 patch 为瞬时）。"""
    post = AsyncMock(
        side_effect=[
            _resp({"code": 99991400, "msg": "rate limit exceeded"}),
            _resp({"code": 0, "data": {"token": "fldcnOK"}}),
        ]
    )
    with patch.object(client, "get_tenant_access_token", return_value="fake-token"):
        with patch("asyncio.sleep", new=AsyncMock()):
            with patch("httpx.AsyncClient", _patch_httpx(post)):
                token = await client.create_folder(name="X", folder_token="fldcnP")
    assert token == "fldcnOK"
    assert post.call_count == 2


@pytest.mark.asyncio
async def test_create_folder_rate_limit_exhausts_raises(client: FeishuDocClient) -> None:
    """持续限流 → 重试耗尽后抛 RateLimitError。"""
    post = AsyncMock(return_value=_resp({"code": 99991400, "msg": "rate limit"}))
    with patch.object(client, "get_tenant_access_token", return_value="fake-token"):
        with patch("asyncio.sleep", new=AsyncMock()):
            with patch("httpx.AsyncClient", _patch_httpx(post)):
                with pytest.raises(RateLimitError):
                    await client.create_folder(name="X", folder_token="fldcnP")


@pytest.mark.asyncio
async def test_create_folder_other_error_raises_api_error(client: FeishuDocClient) -> None:
    post = AsyncMock(return_value=_resp({"code": 1254000, "msg": "permission denied"}))
    with patch.object(client, "get_tenant_access_token", return_value="fake-token"):
        with patch("httpx.AsyncClient", _patch_httpx(post)):
            with pytest.raises(FeishuDocAPIError):
                await client.create_folder(name="X", folder_token="fldcnP")


@pytest.mark.asyncio
async def test_create_folder_missing_token_raises_api_error(client: FeishuDocClient) -> None:
    post = AsyncMock(return_value=_resp({"code": 0, "data": {}}))
    with patch.object(client, "get_tenant_access_token", return_value="fake-token"):
        with patch("httpx.AsyncClient", _patch_httpx(post)):
            with pytest.raises(FeishuDocAPIError):
                await client.create_folder(name="X", folder_token="fldcnP")
