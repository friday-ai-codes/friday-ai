"""feature_list_import 解析健壮性测试：截断 JSON 抢救 + 正常解析。"""

from __future__ import annotations

import pytest

from initiatives.services.feature_list_import import (
    _MAX_DOC_CHARS,
    _clean_node_name,
    _extract_complete_objects,
    _materialize_modules,
    _normalize_sections,
    _number_lines,
    _parse_modules_json,
    _slice_lines,
    compute_parse_budget,
)


def test_materialize_slices_source_and_summary() -> None:
    # feature_lines → 功能点整段 source；summary_lines → 模块概述 summary。
    doc = "模块A概述行1\n概述行2\n功能点X标题\n功能描述正文\n验收：a"
    lines = doc.split("\n")
    raw = [
        {
            "module": "模块A",
            "summary_lines": [1, 2],
            "features": [
                {"name": "功能点X", "feature_lines": [3, 5], "acceptance_lines": [[5, 5]]}
            ],
        }
    ]
    out = _materialize_modules(raw, lines)
    assert out and out[0]["summary"] == "模块A概述行1\n概述行2"
    feat = out[0]["features"][0]
    assert feat["name"] == "功能点X"
    assert feat["source"] == "功能点X标题\n功能描述正文\n验收：a"
    assert feat["acceptance"] == ["验收：a"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("#### 功能点 A：页面结构与 4 节点", "功能点 A：页面结构与 4 节点"),
        ("## 模块 3: 单题型学习页", "模块 3: 单题型学习页"),
        ("- [ ] **功能点 B**：4 节点解锁", "功能点 B：4 节点解锁"),
        ("> - 引用里的列表项", "引用里的列表项"),
        ("1. `代码名` 与 [链接](https://x.dev)", "代码名 与 链接"),
        ("纯文字标题", "纯文字标题"),
        ("", ""),
        (None, ""),
    ],
)
def test_clean_node_name_strips_markdown_marks(raw: object, expected: str) -> None:
    # 节点名来自逐行裁剪，块级前缀（标题/列表/引用）与行内标记都不该进树。
    assert _clean_node_name(raw) == expected


def test_materialize_features_cleans_name_sliced_from_line() -> None:
    # name_line 路径按行裁原文，整行连着 `#### ` 一起进来——名字要剥、原文要留。
    doc = "#### 功能点 A：页面结构\n正文一行\n- [ ] 当进入页面时展示 4 节点"
    lines = doc.split("\n")
    raw = [
        {
            "module": "### 模块 3: 单题型学习页",
            "features": [{"name_line": 1, "feature_lines": [1, 3], "acceptance_lines": [[3, 3]]}],
        }
    ]
    out = _materialize_modules(raw, lines)
    assert out and out[0]["module"] == "模块 3: 单题型学习页"
    feat = out[0]["features"][0]
    assert feat["name"] == "功能点 A：页面结构"
    # 验收项与 source 仍逐字保留（解析契约：内容可回溯原文）。
    assert feat["acceptance"] == ["- [ ] 当进入页面时展示 4 节点"]
    assert feat["source"].startswith("#### 功能点 A：页面结构")


def test_normalize_sections_types_and_dropping() -> None:
    raw = {
        "sections": [
            {"title": "功能描述", "type": "text", "content": "一段描述"},
            {"title": "业务规则", "type": "list", "content": ["规则1", " ", "规则2"]},
            {"title": "流程图", "type": "mermaid", "content": "flowchart TD\n A-->B"},
            {"title": "空段", "type": "text", "content": "  "},
            {"title": "脏类型", "type": "weird", "content": "兜底为 text"},
        ]
    }
    out = _normalize_sections(raw)
    assert [s["type"] for s in out] == ["text", "list", "mermaid", "text"]
    assert out[1]["content"] == ["规则1", "规则2"]
    assert out[3]["type"] == "text"


def test_compute_parse_budget_reserves_headroom() -> None:
    # 输出取 min(期望8000, 模型上限)；输入字数 < 模型输入 token（已扣输出/prompt/安全余量）。
    budget = compute_parse_budget("anthropic", "claude-sonnet-4-20250514")
    assert budget["max_output_tokens"] <= 8000
    assert 0 < budget["max_input_chars"] <= _MAX_DOC_CHARS
    # 字数预算应小于「输入token×换算」上界，确保扣过余量。
    assert budget["max_input_chars"] < budget["max_input_tokens"] * 1.4


def test_compute_parse_budget_unknown_model_falls_back() -> None:
    # 未知模型走 DEFAULT_CAPABILITIES（128k 输入 / 4096 输出），仍给出正字数。
    budget = compute_parse_budget("unknown", "totally-made-up-model")
    assert budget["max_input_chars"] > 0
    assert budget["max_output_tokens"] > 0


def test_parse_clean_json() -> None:
    raw = '{"modules":[{"module":"M1","features":[{"name":"F1","acceptance":["a1"]}]}]}'
    out = _parse_modules_json(raw)
    assert out == [{"module": "M1", "features": [{"name": "F1", "acceptance": ["a1"]}]}]


def test_parse_with_code_fence() -> None:
    raw = '```json\n{"modules":[{"module":"M","features":[{"name":"F"}]}]}\n```'
    out = _parse_modules_json(raw)
    assert out and out[0]["module"] == "M"


def test_extract_complete_objects_ignores_truncated_tail() -> None:
    body = '{"module":"A","features":[]},{"module":"B","features":[]},{"module":"C","fea'
    objs = _extract_complete_objects(body)
    assert len(objs) == 2  # A、B 完整，C 截断丢弃


def test_extract_handles_braces_in_strings() -> None:
    body = '{"module":"含{花}括号","features":[]},{"module":"B"}'
    objs = _extract_complete_objects(body)
    assert len(objs) == 2


def test_parse_salvages_truncated_output() -> None:
    # 模拟 max_tokens 截断：modules 数组中最后一个对象不完整。
    raw = (
        '{"modules":[{"module":"M1","features":[{"name":"F1","acceptance":["a"]}]},'
        '{"module":"M2","features":[{"name":"F2"}]},'
        '{"module":"M3","features":[{"name":"F3'
    )
    out = _parse_modules_json(raw)
    assert out is not None
    names = [m["module"] for m in out]
    assert "M1" in names and "M2" in names  # 截断的 M3 被丢弃，前两个抢救成功
    assert "M3" not in names


# ── 行号裁剪方案 ──────────────────────────────────────────────


def test_number_lines() -> None:
    lines, numbered = _number_lines("a\nb\nc")
    assert lines == ["a", "b", "c"]
    assert numbered == "1|a\n2|b\n3|c"


def test_slice_lines_inclusive_and_clamp() -> None:
    lines = ["L1", "L2", "L3", "L4"]
    assert _slice_lines(lines, 2, 3) == "L2\nL3"  # 闭区间
    assert _slice_lines(lines, 1, 1) == "L1"
    assert _slice_lines(lines, 3, 999) == "L3\nL4"  # 越界 clamp
    assert _slice_lines(lines, 5, 6) == ""  # 全越界
    assert _slice_lines(lines, "x", 2) == ""  # 非法


def test_materialize_modules_slices_acceptance_by_lines() -> None:
    lines = [
        "功能点 A：入口位置",  # 1
        "验收项一：当持有权限时展示入口",  # 2
        "验收项二：样式与其他入口一致",  # 3
    ]
    raw = [
        {
            "module": "入口模块",
            "features": [
                {"name": "入口位置", "acceptance_lines": [[2, 2], [3, 3]]},
            ],
        }
    ]
    out = _materialize_modules(raw, lines)
    assert out == [
        {
            "module": "入口模块",
            "features": [
                {
                    "name": "入口位置",
                    "acceptance": [
                        "验收项一：当持有权限时展示入口",
                        "验收项二：样式与其他入口一致",
                    ],
                }
            ],
        }
    ]


def test_materialize_modules_fallback_text_acceptance() -> None:
    out = _materialize_modules(
        [{"module": "M", "features": [{"name": "F", "acceptance": ["原文验收项"]}]}],
        ["irrelevant"],
    )
    assert out == [{"module": "M", "features": [{"name": "F", "acceptance": ["原文验收项"]}]}]


def test_materialize_modules_name_line() -> None:
    lines = ["功能点标题原文", "其他"]
    out = _materialize_modules(
        [{"module": "M", "features": [{"name_line": 1, "acceptance_lines": []}]}],
        lines,
    )
    assert out and out[0]["features"][0]["name"] == "功能点标题原文"
