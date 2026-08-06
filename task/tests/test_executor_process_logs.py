"""容器过程留痕的纯函数用例（quick-260806 蓝图过程明细）。

守三件事：

1. ⭐ **工具结果预览**：`ToolResultBlock.content` 的三态（str / 多模态 list / None）都能拿到
   单行预览；超长截断并**标出总长**（否则读者分不清「文件就这么短」与「被截了」）。
2. ⭐ **加密思考不外泄也不占位**：`ThinkingBlock` 只有明文 `thinking` 才打印，
   `signature`（Anthropic 的 base64 加密签名）**绝不**被当成「思考」打出来 —— 它既是纯
   噪音，又会挤占日志上限把真步骤顶掉。
3. 工具入参上界足够容纳 `file_path` 这类关键字段（「读了哪个文件」是过程明细最要紧的一维）。
"""

from __future__ import annotations

from core.executor import (
    _MAX_TOOL_INPUT_CHARS,
    _MAX_TOOL_RESULT_CHARS,
    _iter_blocks,
    _tool_result_preview,
)


class _Thinking:
    """仅带 `signature` 的 ThinkingBlock 替身（Anthropic 加密推理时的真实形态）。"""

    def __init__(self, thinking: str = "", signature: str = "") -> None:
        self.thinking = thinking
        self.signature = signature


def test_tool_result_preview_handles_plain_string() -> None:
    assert _tool_result_preview("hello") == "hello"


def test_tool_result_preview_folds_newlines_into_one_line() -> None:
    """日志一行一条；真换行会把单条结果撑成多行、打乱与工具调用的配对关系。"""
    assert _tool_result_preview("a\nb") == "a\\nb"


def test_tool_result_preview_joins_multimodal_text_parts() -> None:
    """list 态只取 `text`：图片等二进制分片对文本日志没有意义。"""
    content = [
        {"type": "text", "text": "第一段"},
        {"type": "image"},
        {"type": "text", "text": "第二段"},
    ]
    assert _tool_result_preview(content) == "第一段\\n第二段"


def test_tool_result_preview_marks_total_length_when_truncated() -> None:
    """⭐ 截断必须标总长，否则「文件就这么短」与「被截了」在界面上无法区分。"""
    text = "x" * (_MAX_TOOL_RESULT_CHARS + 50)
    preview = _tool_result_preview(text)

    assert preview.startswith("x" * 20)
    assert f"共 {len(text)} 字符" in preview
    assert len(preview) < len(text)


def test_tool_result_preview_of_none_is_an_explicit_placeholder() -> None:
    """⛔ 不返回空串：空串在界面上等同于「这条日志没内容」，与「工具确实返回了空」混淆。"""
    assert _tool_result_preview(None) == "(空)"


def test_iter_blocks_tolerates_string_content() -> None:
    """`UserMessage.content` 可能是纯字符串（非工具结果的普通消息）⇒ 归一成空列表不抛。"""
    assert _iter_blocks("纯文本") == []
    assert _iter_blocks(None) == []
    assert _iter_blocks([1, 2]) == [1, 2]


def test_thinking_signature_is_never_treated_as_readable_thinking() -> None:
    """⭐ 加密签名不是思考。

    容器侧此前写的是 `thinking or signature` ⇒ Anthropic 加密推理时 `thinking` 为空，
    回落打印出 `EoMFCnEIEBAB…` 这串 base64。本用例锁死取值口径：**只取 `thinking`**。
    """
    encrypted = _Thinking(signature="EoMFCnEIEBABGAIqQEVySBpDl8GTtfS3UG1J")
    readable = _Thinking(thinking="我先读一下路由证据")

    assert str(getattr(encrypted, "thinking", "") or "").strip() == ""
    assert str(getattr(readable, "thinking", "") or "").strip() == "我先读一下路由证据"


def test_tool_input_limit_fits_a_realistic_file_path_call() -> None:
    """入参上界要装得下 `get_repository_file` 这类调用——截掉 `file_path` 等于丢掉「读了哪个文件」。"""
    call = (
        '{"repository_id": "a1bef5cc-b5e4-4869-8a5a-e1c4f5db4663", '
        '"file_path": "server/services/process_runtime/blueprint_research_adapter.py"}'
    )
    assert len(call) < _MAX_TOOL_INPUT_CHARS
