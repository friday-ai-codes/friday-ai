"""``delivery.services.crawl_service`` 单元测试。

覆盖：
- URL 识别 ``_classify``（飞书 docx/base/wiki、通用、未知）
- 模型输出稳健解析 ``_parse_items_json``（代码围栏 / 杂质 / 过滤非法 id）
- ``crawl_url`` 分支：未配置飞书 / ok / empty / 未识别（均打桩抓取与 AI，免 DB/网络）
"""
from __future__ import annotations

import pytest

from delivery.services import crawl_service as cs


class TestClassify:
    def test_docx(self) -> None:
        kind, ids = cs._classify("https://acme.feishu.cn/docx/Abc123Token")
        assert kind == cs._KIND_DOC
        assert ids["doc_id"] == "Abc123Token"

    def test_bitable_with_table(self) -> None:
        kind, ids = cs._classify(
            "https://acme.feishu.cn/base/AppTok?table=tblXYZ&view=vewABC"
        )
        assert kind == cs._KIND_BITABLE
        assert ids["app_token"] == "AppTok"
        assert ids["table_id"] == "tblXYZ"

    def test_bitable_without_table(self) -> None:
        kind, ids = cs._classify("https://acme.feishu.cn/base/AppTok")
        assert kind == cs._KIND_BITABLE
        assert ids["app_token"] == "AppTok"
        assert ids["table_id"] == ""

    def test_wiki(self) -> None:
        kind, ids = cs._classify("https://acme.feishu.cn/wiki/WikiTok")
        assert kind == cs._KIND_WIKI
        assert ids["token"] == "WikiTok"

    def test_generic(self) -> None:
        kind, _ = cs._classify("https://example.com/notes.txt")
        assert kind == cs._KIND_GENERIC

    def test_unknown_scheme(self) -> None:
        kind, _ = cs._classify("ftp://example.com/x")
        assert kind == cs._KIND_UNKNOWN

    def test_feishu_unknown_shape(self) -> None:
        kind, _ = cs._classify("https://acme.feishu.cn/some/other/path")
        assert kind == cs._KIND_UNKNOWN


class TestParseItemsJson:
    def test_plain_array(self) -> None:
        out = cs._parse_items_json(
            '[{"space":"示例","work_item_id":123,"work_item_type":"story","mr_url":"u"}]'
        )
        assert out == [
            {
                "space": "示例",
                "work_item_id": 123,
                "work_item_type": "story",
                "mr_url": "u",
            }
        ]

    def test_code_fence(self) -> None:
        out = cs._parse_items_json('```json\n[{"work_item_id": "456"}]\n```')
        assert len(out) == 1
        assert out[0]["work_item_id"] == 456
        assert out[0]["space"] == ""

    def test_prose_wrapping(self) -> None:
        out = cs._parse_items_json(
            '好的，结果如下：[{"work_item_id": 7}] 以上。'
        )
        assert out == [
            {"space": "", "work_item_id": 7, "work_item_type": "", "mr_url": ""}
        ]

    def test_drops_invalid_ids(self) -> None:
        out = cs._parse_items_json(
            '[{"work_item_id": "abc"}, {"work_item_id": 0}, {"work_item_id": 9}]'
        )
        assert [i["work_item_id"] for i in out] == [9]

    def test_garbage(self) -> None:
        assert cs._parse_items_json("not json at all") == []
        assert cs._parse_items_json("") == []
        assert cs._parse_items_json('{"not": "a list"}') == []


@pytest.mark.asyncio
class TestCrawlUrl:
    async def test_empty_url(self) -> None:
        res = await cs.crawl_url("")
        assert res.status == cs.CrawlStatus.ERROR

    async def test_unknown_url(self) -> None:
        res = await cs.crawl_url("ftp://x/y")
        assert res.status == cs.CrawlStatus.ERROR

    async def test_feishu_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _no_creds() -> None:
            return None

        monkeypatch.setattr(cs, "_aget_system_feishu_credentials", _no_creds)
        res = await cs.crawl_url("https://acme.feishu.cn/base/AppTok?table=tbl1")
        assert res.status == cs.CrawlStatus.FEISHU_NOT_CONFIGURED
        assert res.settings_deeplink == cs.FEISHU_SETTINGS_DEEPLINK
        assert res.source_kind == cs._KIND_BITABLE

    async def test_ok_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _creds() -> tuple[str, str]:
            return "app", "secret"

        async def _fetch(kind, ids, app_id, app_secret) -> tuple[str, str]:
            return cs._KIND_BITABLE, "row1\nrow2"

        async def _spaces() -> list:
            return []

        async def _extract(content, spaces) -> list:
            return [
                {"space": "s", "work_item_id": 1, "work_item_type": "", "mr_url": ""}
            ]

        monkeypatch.setattr(cs, "_aget_system_feishu_credentials", _creds)
        monkeypatch.setattr(cs, "_acrawl_feishu", _fetch)
        monkeypatch.setattr(cs, "_aget_spaces", _spaces)
        monkeypatch.setattr(cs, "_aextract_items", _extract)

        res = await cs.crawl_url("https://acme.feishu.cn/base/AppTok?table=tbl1")
        assert res.status == cs.CrawlStatus.OK
        assert len(res.items) == 1

    async def test_empty_when_no_items(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _creds() -> tuple[str, str]:
            return "app", "secret"

        async def _fetch(kind, ids, app_id, app_secret) -> tuple[str, str]:
            return cs._KIND_DOC, "some content"

        async def _spaces() -> list:
            return []

        async def _extract(content, spaces) -> list:
            return []

        monkeypatch.setattr(cs, "_aget_system_feishu_credentials", _creds)
        monkeypatch.setattr(cs, "_acrawl_feishu", _fetch)
        monkeypatch.setattr(cs, "_aget_spaces", _spaces)
        monkeypatch.setattr(cs, "_aextract_items", _extract)

        res = await cs.crawl_url("https://acme.feishu.cn/docx/Doc1")
        assert res.status == cs.CrawlStatus.EMPTY

    async def test_generic_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fetch_generic(url) -> str:
            return "plain text content"

        async def _spaces() -> list:
            return []

        async def _extract(content, spaces) -> list:
            return [
                {"space": "", "work_item_id": 42, "work_item_type": "", "mr_url": ""}
            ]

        monkeypatch.setattr(cs, "_acrawl_generic", _fetch_generic)
        monkeypatch.setattr(cs, "_aget_spaces", _spaces)
        monkeypatch.setattr(cs, "_aextract_items", _extract)

        res = await cs.crawl_url("https://example.com/notes.txt")
        assert res.status == cs.CrawlStatus.OK
        assert res.items[0]["work_item_id"] == 42
