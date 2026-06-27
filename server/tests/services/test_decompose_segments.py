"""decompose_segments helper 单测（DECOMP-01，95-02）。

镜像 clarification_questions 测试范式：纯函数（解析/normalize）不触网；异步接线用
patch 模块级符号 + AsyncMock 注入，覆盖 happy / JSON 健壮 / fail-soft / 缺 model /
call_source 标注。
"""

from __future__ import annotations

from services.plan_orchestration.decompose_segments import (
    _build_prompt,
    _content_to_text,
    _parse_segments_json,
    _system_prompt,
    normalize_decomposition_segments,
)

# ── 纯函数：_parse_segments_json ──────────────────────────────────────────


def test_parse_segments_json_from_code_block() -> None:
    """```json 代码块内的 {"segments": [...]} 被正确提取。"""
    text = '前缀说明\n```json\n{"segments": [{"title": "登录页改造"}]}\n```\n后缀'
    parsed = _parse_segments_json(text)
    assert parsed == [{"title": "登录页改造"}]


def test_parse_segments_json_bare_json_object() -> None:
    """裸 JSON（无代码块围栏）的 segments 对象兜底解析。"""
    parsed = _parse_segments_json('{"segments": [{"title": "A"}, {"title": "B"}]}')
    assert parsed == [{"title": "A"}, {"title": "B"}]


def test_parse_segments_json_top_level_list() -> None:
    """顶层 list 也接受（容错 LLM 直接给数组）。"""
    parsed = _parse_segments_json('[{"title": "A"}]')
    assert parsed == [{"title": "A"}]


def test_parse_segments_json_filters_non_dict_items() -> None:
    """list 中非 dict 项被剔除。"""
    parsed = _parse_segments_json('{"segments": [{"title": "A"}, "noise", 123]}')
    assert parsed == [{"title": "A"}]


def test_parse_segments_json_invalid_returns_empty() -> None:
    """非 JSON / 畸形文本 → 返回 []（不抛）。"""
    assert _parse_segments_json("这不是 JSON，只是一段普通解释。") == []
    assert _parse_segments_json("") == []
    assert _parse_segments_json("```\nnot json at all\n```") == []


# ── 纯函数：normalize_decomposition_segments ──────────────────────────────


def test_normalize_skips_missing_title() -> None:
    """缺/空 title 的项被跳过。"""
    raw = [{"title": "有标题"}, {"title": ""}, {"module": "无标题项"}]
    result = normalize_decomposition_segments(raw)
    assert len(result) == 1
    assert result[0]["title"] == "有标题"


def test_normalize_invalid_layer_falls_back_to_empty() -> None:
    """非法 layer 回退空字符串；合法 layer 保留（大小写不敏感）。"""
    raw = [
        {"title": "A", "layer": "weird"},
        {"title": "B", "layer": "FRONTEND"},
        {"title": "C", "layer": "backend"},
    ]
    result = normalize_decomposition_segments(raw)
    assert result[0]["layer"] == ""
    assert result[1]["layer"] == "frontend"
    assert result[2]["layer"] == "backend"


def test_normalize_coerces_and_strips_fields() -> None:
    """module / repo_hint 强转 str/strip；缺失为空字符串；title 也 strip。"""
    raw = [{"title": "  标题  ", "module": 123, "repo_hint": "  web  "}]
    result = normalize_decomposition_segments(raw)
    assert result[0] == {
        "title": "标题",
        "module": "123",
        "layer": "",
        "repo_hint": "web",
    }


def test_normalize_truncates_to_max_segments() -> None:
    """超 max_segments 截断防 LLM 失控。"""
    raw = [{"title": f"seg-{i}"} for i in range(50)]
    result = normalize_decomposition_segments(raw, max_segments=5)
    assert len(result) == 5
    assert result[-1]["title"] == "seg-4"


def test_normalize_empty_input_returns_empty() -> None:
    assert normalize_decomposition_segments([]) == []


# ── 纯函数：_content_to_text ──────────────────────────────────────────────


def test_content_to_text_handles_str_and_blocks() -> None:
    """兼容 str 与 reasoning content_blocks（只拼 text block）。"""
    assert _content_to_text("plain") == "plain"
    blocks = [
        {"type": "reasoning", "text": "思考中"},
        {"type": "text", "text": "答案A"},
        {"text": "答案B"},
        "裸字符串块",
    ]
    # 镜像 clarification：拼接顺序为迭代序，含任意带 text 的 dict + 裸 str。
    assert _content_to_text(blocks) == "思考中答案A答案B裸字符串块"
    assert _content_to_text(None) == ""


# ── 纯函数：prompt 构造 ───────────────────────────────────────────────────


def test_system_prompt_mentions_segments_json() -> None:
    sp = _system_prompt()
    assert "segments" in sp
    assert "frontend" in sp


def test_build_prompt_includes_requirement_and_repos() -> None:
    prompt = _build_prompt("把登录页改造", include_repos=["web-portal", "api-gateway"])
    assert "把登录页改造" in prompt
    assert "web-portal" in prompt
    assert "api-gateway" in prompt


def test_build_prompt_without_repos() -> None:
    prompt = _build_prompt("需求", include_repos=None)
    assert "需求" in prompt
    assert "候选仓库" not in prompt
