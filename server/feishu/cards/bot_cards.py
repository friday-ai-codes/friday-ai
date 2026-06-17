"""Card builders for Feishu bot lifecycle messages."""

from __future__ import annotations

from typing import Any

TOOL_NAME_DISPLAY: dict[str, str] = {
    "search_repository_code": "🔍 搜索代码",
    "browse_file_content": "📄 浏览文件",
    "list_project_structure": "📂 查看目录结构",
    "list_project_repositories": "📦 列出仓库",
    "get_repository_info": "ℹ️ 获取仓库信息",
    "get_project_overview": "📋 获取项目概览",
    "deep_analysis": "🧠 深度分析",
    "create_coding_plan": "📝 生成编码方案",
    "update_coding_plan": "✏️ 更新编码方案",
    "fetch_feishu_document": "📑 读取飞书文档",
}


def _display_tool_name(name: str) -> str:
    if name.startswith("mcp__"):
        parts = name.split("__", 2)
        if len(parts) == 3:
            name = parts[2]
    return TOOL_NAME_DISPLAY.get(name, f"🔧 {name}")


def _markdown_block(content: str) -> dict[str, Any]:
    return {"tag": "markdown", "content": content}


def _reference_lines(references: list[dict[str, Any]]) -> str:
    if not references:
        return "- 未引用具体代码上下文，仅基于项目概览回答"

    lines: list[str] = []
    for ref in references[:5]:
        repo = ref.get("repository") or ref.get("repo") or "未知仓库"
        path = ref.get("path") or ref.get("file") or ""
        line = ref.get("line") or ref.get("lines") or ""
        summary = ref.get("summary") or ref.get("text") or ""
        suffix = f" ({line})" if line else ""
        location = f"`{repo}:{path}`{suffix}" if path else f"`{repo}`"
        lines.append(f"- {location} {summary}".strip())
    return "\n".join(lines)


def build_welcome_card() -> dict[str, Any]:
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "Friday Bot 已加入群聊"},
            "template": "blue",
        },
        "elements": [
            _markdown_block(
                "直接在群里 **@Friday** 提问即可。\n\n"
                "我会先识别项目/仓库，再检索上下文并给出回答；"
                "如果信息不够明确，我会先发澄清卡。"
            ),
        ],
    }


def build_thinking_card() -> dict[str, Any]:
    """初始「思考中...」卡片，收到消息后立即发送。"""
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "Friday"},
            "template": "blue",
            "ud_icon": {"tag": "standard_icon", "token": "ai-sparkle_outlined"},
        },
        "elements": [
            _markdown_block("思考中..."),
        ],
    }


def build_streaming_card(tool_names: list[str]) -> dict[str, Any]:
    """流式更新卡片，逐行展示正在调用的工具。"""
    lines = "\n".join(_display_tool_name(name) for name in tool_names)
    content = f"思考中...\n\n{lines}" if lines else "思考中..."
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "Friday"},
            "template": "blue",
            "ud_icon": {"tag": "standard_icon", "token": "ai-sparkle_outlined"},
        },
        "elements": [
            _markdown_block(content),
        ],
    }


def build_background_analysis_card(
    question: str,
    *,
    task_count: int = 0,
    phase: str = "waiting",
) -> dict[str, Any]:
    """构建后台分析等待卡，避免 waiting/barrier 场景显示空答案。"""
    task_line = f"- 后台任务数：{task_count}" if task_count > 0 else "- 后台任务仍在运行"
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "Friday 后台分析中"},
            "template": "blue",
            "ud_icon": {"tag": "standard_icon", "token": "ai-sparkle_outlined"},
        },
        "elements": [
            _markdown_block(f"**原问题**\n{question}"),
            {"tag": "hr"},
            _markdown_block(
                "后台分析中：我已经把任务交给后台继续分析，完成后会更新这张卡。\n\n"
                "**当前状态**\n"
                f"- 阶段：{phase}\n"
                f"{task_line}\n"
                "- 暂未生成最终回复，请稍后查看"
            ),
        ],
    }


def build_processing_card(question: str, progress_state: str = "项目识别中", thread_hint: str = "") -> dict[str, Any]:
    hint = f"\n\n话题线索：{thread_hint}" if thread_hint else ""
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "Friday 正在处理中"},
            "template": "blue",
        },
        "elements": [
            _markdown_block(f"**原问题**\n{question}{hint}"),
            {"tag": "hr"},
            _markdown_block(
                "**处理进度**\n"
                f"- 当前阶段：{progress_state}\n"
                "- 项目识别中\n"
                "- 上下文检索中\n"
                "- 回答生成中"
            ),
        ],
    }


def build_clarification_card(question: str, candidates: list[str]) -> dict[str, Any]:
    candidate_lines = "\n".join(f"- {candidate}" for candidate in candidates) or "- 请补充项目、仓库或引用上下文"
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "需要更多上下文"},
            "template": "orange",
        },
        "elements": [
            _markdown_block(f"**原问题**\n{question}"),
            {"tag": "hr"},
            _markdown_block(
                "我还不能稳定判断项目归属或上下文范围。\n\n"
                f"**可选线索**\n{candidate_lines}"
            ),
        ],
    }


def build_answer_card(
    question: str,
    answer: str,
    references: list[dict[str, Any]],
    usage: dict[str, Any] | None = None,
    *,
    compact: bool = False,
    matched_space_label: str = "",
) -> dict[str, Any]:
    """构建最终回答卡片。

    compact=True 用于私聊场景，只显示回答正文。
    """
    elements: list[dict[str, Any]] = []
    if matched_space_label:
        elements.append(_markdown_block(f"已自动匹配「{matched_space_label}」空间"))
        if not compact:
            elements.append({"tag": "hr"})

    if compact:
        elements.append(_markdown_block(answer or "（无回复内容）"))
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "Friday"},
                "template": "blue",
                "ud_icon": {"tag": "standard_icon", "token": "ai-sparkle_outlined"},
            },
            "elements": elements,
        }

    elements.extend([
        _markdown_block(f"**原问题**\n{question}"),
        {"tag": "hr"},
        _markdown_block(f"**回答**\n{answer}"),
        {"tag": "hr"},
        _markdown_block(f"**已参考上下文**\n{_reference_lines(references)}"),
    ])
    if usage:
        input_t = usage.get("input_tokens", 0)
        output_t = usage.get("output_tokens", 0)
        cost = usage.get("cost_usd", 0)
        elements.append({"tag": "hr"})
        elements.append(
            _markdown_block(f"💰 输入 {input_t} / 输出 {output_t} tokens · ${cost:.4f}")
        )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "Friday"},
            "template": "blue",
            "ud_icon": {"tag": "standard_icon", "token": "ai-sparkle_outlined"},
        },
        "elements": elements,
    }


def build_streaming_card_v2(
    initial_text: str = "思考中...",
    element_id: str = "md_body",
) -> dict[str, Any]:
    """构建 schema 2.0 流式卡片实体（供 CardKit create_card_entity 使用）。

    含单个可流式 markdown 元素（带开发者自定义 element_id），CardKit 增量推送
    经 stream_card_content 更新该 element 的全量文本。

    Args:
        initial_text: 初始文本（创建时占位，后续被流式 content 覆盖）
        element_id: 可流式文本元素的 element_id（1~20 字符）

    Returns:
        schema 2.0 卡片 dict（schema=="2.0" + config.streaming_mode=true）
    """
    return {
        "schema": "2.0",
        "config": {
            "streaming_mode": True,
            "update_multi": True,
            "streaming_config": {
                "print_frequency_ms": {"default": 70, "android": 70, "ios": 70, "pc": 70},
                "print_step": {"default": 1, "android": 1, "ios": 1, "pc": 1},
                "print_strategy": "fast",
            },
        },
        "header": {
            "title": {"tag": "plain_text", "content": "Friday"},
            "template": "blue",
            "ud_icon": {"tag": "standard_icon", "token": "ai-sparkle_outlined"},
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": initial_text, "element_id": element_id},
            ],
        },
    }


def build_answer_markdown(
    answer: str,
    references: list[dict[str, Any]],
    usage: dict[str, Any] | None = None,
    matched_space_label: str = "",
) -> str:
    """构建终态单 markdown 字符串（供 CardKit content PUT 收尾）。

    复用 `_reference_lines` 与 build_answer_card 的 usage 行格式，拼成 answer +
    引用 + usage 的单串，`---` 作区块分隔。与 build_answer_card 降级路径表达一致。

    Args:
        answer: 回答正文
        references: 引用上下文列表（内部截断 references[:5]）
        usage: token / 成本统计（可选）
        matched_space_label: 自动匹配的空间名（非空时作首行）

    Returns:
        终态 markdown 字符串
    """
    blocks: list[str] = []
    if matched_space_label:
        blocks.append(f"已自动匹配「{matched_space_label}」空间")
    blocks.append(f"**回答**\n{answer}")
    blocks.append(f"---\n**已参考上下文**\n{_reference_lines(references)}")
    if usage:
        input_t = usage.get("input_tokens", 0)
        output_t = usage.get("output_tokens", 0)
        cost = usage.get("cost_usd", 0)
        blocks.append(f"---\n💰 输入 {input_t} / 输出 {output_t} tokens · ${cost:.4f}")
    return "\n\n".join(blocks)


def build_error_card(question: str, hint_text: str) -> dict[str, Any]:
    hint = hint_text or "请稍后重试，并尽量补充项目/仓库信息。"
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "Friday 处理失败"},
            "template": "red",
        },
        "elements": [
            _markdown_block(f"**原问题**\n{question}"),
            {"tag": "hr"},
            _markdown_block(
                "处理过程中出现异常。\n\n"
                f"{hint}\n"
                "- 可补充项目/仓库名称后重试\n"
                "- 若持续失败，请联系管理员排查"
            ),
        ],
    }
