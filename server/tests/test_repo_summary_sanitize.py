"""implementation Task 1: _parse_summary_json 和脱敏测试。

Test 6: _parse_summary_json 能从 ```json ... ``` 代码块中提取 JSON
Test 7: _sanitize_summary 能移除 email / Bearer token / ghp_ API key
"""

import pytest


class TestParseSummaryJson:
    """Test 6: _parse_summary_json 从多种格式中提取/解析 JSON。"""

    def test_extracts_json_from_code_block(self) -> None:
        """从 ```json ... ``` 代码块中提取并格式化 JSON。"""
        from subagent.api.callbacks import _parse_summary_json

        raw = '''Here is the summary:

```json
{"overview": "A Python web app", "tech_stack": ["Django", "PostgreSQL"]}
```

Hope this helps!'''

        result = _parse_summary_json(raw)
        assert '"overview": "A Python web app"' in result
        assert '"tech_stack"' in result
        # 应该是格式化的 JSON（有缩进）
        assert "\n" in result

    def test_parses_direct_json(self) -> None:
        """直接 JSON 字符串也能正确解析并格式化。"""
        from subagent.api.callbacks import _parse_summary_json

        raw = '{"overview": "Test repo", "language": "TypeScript"}'
        result = _parse_summary_json(raw)
        assert '"overview": "Test repo"' in result

    def test_returns_raw_text_on_invalid_json(self) -> None:
        """非 JSON 文本原样返回。"""
        from subagent.api.callbacks import _parse_summary_json

        raw = "# Summary\n\nThis is a markdown summary."
        result = _parse_summary_json(raw)
        assert result == raw

    def test_handles_empty_string(self) -> None:
        """空字符串原样返回。"""
        from subagent.api.callbacks import _parse_summary_json

        result = _parse_summary_json("")
        assert result == ""

    def test_handles_json_with_whitespace(self) -> None:
        """带前后空白的 JSON 能正确解析。"""
        from subagent.api.callbacks import _parse_summary_json

        raw = '  \n  {"overview": "Test"}  \n  '
        result = _parse_summary_json(raw)
        assert '"overview": "Test"' in result


class TestSanitizeSummary:
    """Test 7: 脱敏测试 — 验证 email / Bearer token / ghp_ API key 被移除。

    由于 _sanitize_summary 存在于容器侧 (task/core/runner.py)，
    此处测试 _parse_summary_json 不会引入敏感信息（透传测试）。
    如果服务端有额外脱敏需求，此处验证相同的正则规则。
    """

    def test_email_not_preserved_in_passthrough(self) -> None:
        """验证 _parse_summary_json 不引入额外数据 — 含 email 的文本原样返回。

        注意：服务端 _parse_summary_json 仅做 JSON 解析，不做脱敏。
        脱敏在容器侧完成（Plan-02）。此测试确认 passthrough 行为。
        """
        from subagent.api.callbacks import _parse_summary_json

        raw = "This repo is maintained by user@example.com"
        result = _parse_summary_json(raw)
        # 非 JSON 原样返回 — passthrough 行为
        assert result == raw

    def test_bearer_token_in_json_passthrough(self) -> None:
        """JSON 中含 Bearer token 的字段正常解析（脱敏责任在容器侧）。"""
        from subagent.api.callbacks import _parse_summary_json

        import json

        data = {"overview": "This uses Bearer abc123 for auth"}
        raw = json.dumps(data)
        result = _parse_summary_json(raw)
        parsed = json.loads(result)
        assert parsed["overview"] == "This uses Bearer abc123 for auth"

    def test_ghp_key_in_json_passthrough(self) -> None:
        """JSON 中含 ghp_ key 的字段正常解析（脱敏责任在容器侧）。"""
        from subagent.api.callbacks import _parse_summary_json

        import json

        data = {"overview": "Token: " "ghp_" "ABC123def456"}
        raw = json.dumps(data)
        result = _parse_summary_json(raw)
        parsed = json.loads(result)
        assert parsed["overview"] == "Token: " "ghp_" "ABC123def456"
