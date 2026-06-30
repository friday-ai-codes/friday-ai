"""feature_list_import 解析健壮性测试：截断 JSON 抢救 + 正常解析。"""

from __future__ import annotations

from initiatives.services.feature_list_import import (
    _extract_complete_objects,
    _materialize_modules,
    _number_lines,
    _parse_modules_json,
    _slice_lines,
)


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
                    "acceptance": ["验收项一：当持有权限时展示入口", "验收项二：样式与其他入口一致"],
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
