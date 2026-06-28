"""飞书文档 API 错误码分类单元测试。

验证 get_document_content 根据不同的 API error_code 抛出正确的异常子类。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.feishu_doc import (
    DocumentNotFoundError,
    FeishuDocAPIError,
    FeishuDocClient,
    PermissionDeniedError,
    RateLimitError,
)


@pytest.fixture
def client() -> FeishuDocClient:
    return FeishuDocClient(app_id="test-id", app_secret="test-secret")


def _mock_response(code: int, msg: str = "test error") -> MagicMock:
    """构造模拟的 httpx 响应。"""
    resp = MagicMock()
    resp.json.return_value = {"code": code, "msg": msg}
    return resp


def _mock_success_response() -> MagicMock:
    """构造成功的 httpx 响应。"""
    resp = MagicMock()
    resp.json.return_value = {
        "code": 0,
        "msg": "success",
        "data": {"items": []},
    }
    return resp


class TestFeishuDocErrorClassification:
    """飞书 API 错误码 → 异常子类映射测试。"""

    @pytest.mark.asyncio
    async def test_permission_denied_91204(self, client: FeishuDocClient) -> None:
        with patch.object(client, "get_tenant_access_token", return_value="fake-token"):
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_response(91204)
            with patch("httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                with pytest.raises(PermissionDeniedError):
                    await client.get_document_content("test-doc")

    @pytest.mark.asyncio
    async def test_permission_denied_95008(self, client: FeishuDocClient) -> None:
        with patch.object(client, "get_tenant_access_token", return_value="fake-token"):
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_response(95008)
            with patch("httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                with pytest.raises(PermissionDeniedError):
                    await client.get_document_content("test-doc")

    @pytest.mark.asyncio
    async def test_permission_denied_95009(self, client: FeishuDocClient) -> None:
        with patch.object(client, "get_tenant_access_token", return_value="fake-token"):
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_response(95009)
            with patch("httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                with pytest.raises(PermissionDeniedError):
                    await client.get_document_content("test-doc")

    @pytest.mark.asyncio
    async def test_permission_denied_91003(self, client: FeishuDocClient) -> None:
        with patch.object(client, "get_tenant_access_token", return_value="fake-token"):
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_response(91003)
            with patch("httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                with pytest.raises(PermissionDeniedError):
                    await client.get_document_content("test-doc")

    @pytest.mark.asyncio
    async def test_permission_denied_99991672(self, client: FeishuDocClient) -> None:
        with patch.object(client, "get_tenant_access_token", return_value="fake-token"):
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_response(99991672)
            with patch("httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                with pytest.raises(PermissionDeniedError):
                    await client.get_document_content("test-doc")

    @pytest.mark.asyncio
    async def test_not_found_91402(self, client: FeishuDocClient) -> None:
        with patch.object(client, "get_tenant_access_token", return_value="fake-token"):
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_response(91402)
            with patch("httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                with pytest.raises(DocumentNotFoundError):
                    await client.get_document_content("test-doc")

    @pytest.mark.asyncio
    async def test_not_found_95006(self, client: FeishuDocClient) -> None:
        with patch.object(client, "get_tenant_access_token", return_value="fake-token"):
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_response(95006)
            with patch("httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                with pytest.raises(DocumentNotFoundError):
                    await client.get_document_content("test-doc")

    @pytest.mark.asyncio
    async def test_not_found_1002(self, client: FeishuDocClient) -> None:
        with patch.object(client, "get_tenant_access_token", return_value="fake-token"):
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_response(1002)
            with patch("httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                with pytest.raises(DocumentNotFoundError):
                    await client.get_document_content("test-doc")

    @pytest.mark.asyncio
    async def test_not_found_95007(self, client: FeishuDocClient) -> None:
        with patch.object(client, "get_tenant_access_token", return_value="fake-token"):
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_response(95007)
            with patch("httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                with pytest.raises(DocumentNotFoundError):
                    await client.get_document_content("test-doc")

    @pytest.mark.asyncio
    async def test_rate_limit_99991400(self, client: FeishuDocClient) -> None:
        """验证已有 RateLimitError 行为不退化。"""
        with patch.object(client, "get_tenant_access_token", return_value="fake-token"):
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_response(99991400)
            with patch("httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                with pytest.raises(RateLimitError):
                    await client.get_document_content("test-doc")

    @pytest.mark.asyncio
    async def test_unknown_error_code(self, client: FeishuDocClient) -> None:
        """未知错误码应抛出基类 FeishuDocAPIError。"""
        with patch.object(client, "get_tenant_access_token", return_value="fake-token"):
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_response(99999)
            with patch("httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                with pytest.raises(FeishuDocAPIError):
                    await client.get_document_content("test-doc")

    @pytest.mark.asyncio
    async def test_success_no_exception(self, client: FeishuDocClient) -> None:
        """成功响应（code=0）不应抛异常。"""
        with patch.object(client, "get_tenant_access_token", return_value="fake-token"):
            mock_client = AsyncMock()
            mock_client.get.return_value = _mock_success_response()
            with patch("httpx.AsyncClient") as mock_cls:
                mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                markdown, blocks = await client.get_document_content("test-doc")
                assert isinstance(markdown, str)
                assert isinstance(blocks, list)

    @pytest.mark.asyncio
    async def test_docs_url_routes_to_legacy_raw_content(
        self, client: FeishuDocClient
    ) -> None:
        with patch.object(
            client, "get_legacy_document_content", new=AsyncMock(return_value="旧版正文")
        ) as legacy:
            markdown, blocks = await client.get_document_content_by_url(
                "https://x.feishu.cn/docs/doccnLegacy123"
            )

        legacy.assert_awaited_once_with("doccnLegacy123")
        assert markdown == "旧版正文"
        assert blocks == []

    @pytest.mark.asyncio
    async def test_docs_url_falls_back_to_docx_for_upgraded_docs(
        self, client: FeishuDocClient
    ) -> None:
        legacy_error = FeishuDocAPIError(
            "读取旧版文档失败: this API is not supported docx (Upgraded Docs) type"
        )
        with patch.object(
            client, "get_legacy_document_content", new=AsyncMock(side_effect=legacy_error)
        ) as legacy, patch.object(
            client, "_get_docx_document_content", new=AsyncMock(return_value=("新版正文", []))
        ) as get_docx:
            markdown, blocks = await client.get_document_content_by_url(
                "https://x.feishu.cn/docs/upgradedToken123"
            )

        legacy.assert_awaited_once_with("upgradedToken123")
        get_docx.assert_awaited_once_with("upgradedToken123")
        assert markdown == "新版正文"
        assert blocks == []

    @pytest.mark.asyncio
    async def test_wiki_url_routes_docx_node_to_docx_blocks(
        self, client: FeishuDocClient
    ) -> None:
        with patch.object(
            client, "resolve_wiki_node", new=AsyncMock(return_value=("docx", "docxToken"))
        ) as resolve, patch.object(
            client, "get_document_content", new=AsyncMock(return_value=("新版正文", []))
        ) as get_docx:
            markdown, blocks = await client.get_document_content_by_url(
                "https://x.feishu.cn/wiki/wikiNode123"
            )

        resolve.assert_awaited_once_with("wikiNode123")
        get_docx.assert_awaited_once_with("docxToken")
        assert markdown == "新版正文"
        assert blocks == []

    @pytest.mark.asyncio
    async def test_wiki_url_routes_legacy_doc_node_to_raw_content(
        self, client: FeishuDocClient
    ) -> None:
        with patch.object(
            client, "resolve_wiki_node", new=AsyncMock(return_value=("doc", "doccnLegacy123"))
        ) as resolve, patch.object(
            client, "get_legacy_document_content", new=AsyncMock(return_value="旧版正文")
        ) as legacy:
            markdown, blocks = await client.get_document_content_by_url(
                "https://x.feishu.cn/wiki/wikiNode123"
            )

        resolve.assert_awaited_once_with("wikiNode123")
        legacy.assert_awaited_once_with("doccnLegacy123")
        assert markdown == "旧版正文"
        assert blocks == []
