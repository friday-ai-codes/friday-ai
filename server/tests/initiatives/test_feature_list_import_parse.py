"""feature_list_import 解析健壮性测试：截断 JSON 抢救 + 正常解析。"""

from __future__ import annotations

from initiatives.services.feature_list_import import (
    _extract_complete_objects,
    _parse_modules_json,
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
