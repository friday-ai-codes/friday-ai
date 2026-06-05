"""飞书文档内容截断逻辑测试。

验证 truncate_doc_content 在不同长度输入下的行为。
"""

from services.feishu_doc import MAX_DOC_CHARS, truncate_doc_content


class TestTruncateDocContent:
    """截断辅助函数测试。"""

    def test_short_content_not_truncated(self) -> None:
        text = "a" * 100
        result, truncated = truncate_doc_content(text)
        assert result == text
        assert truncated is False

    def test_exact_limit_not_truncated(self) -> None:
        text = "b" * MAX_DOC_CHARS
        result, truncated = truncate_doc_content(text)
        assert result == text
        assert truncated is False
        assert len(result) == 30_000

    def test_long_content_truncated(self) -> None:
        text = "c" * 50_000
        result, truncated = truncate_doc_content(text)
        assert len(result) == MAX_DOC_CHARS
        assert result == "c" * 30_000
        assert truncated is True

    def test_empty_content(self) -> None:
        result, truncated = truncate_doc_content("")
        assert result == ""
        assert truncated is False
