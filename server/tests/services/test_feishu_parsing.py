"""`services.feishu_parsing` 共享 helper 单测（纯函数 + 本地构造 Response）。

覆盖 Phase 27 CONTEXT 测试策略 ②③④⑤ 的 helper 层部分：
- 防御式 JSON 解析（safe/strict）对非 JSON 响应 fail-soft / fail-loud。
- `build_feishu_fields` 完整保留 5 键元数据（FIX-04）。
- `extract_prd_url` / `extract_select_label` 按 alias/key 提取。
- `rich_text_to_markdown` 行为等价。
- `derive_relations_from_fields` 从实测字段派生关系（FIX-02）。
- `parse_comments` 对齐 comment/list 形状并容错（FIX-03）。

fixture 取自 DOMAIN-MODEL.md §16 实测值（story 1000000002 / issue 1000000006）。
纯函数测试不发真实网络（pytest-socket 隔离）；需要 Response 时用 `httpx.Response`
本地构造，绝不发请求。
"""

from __future__ import annotations

import httpx

from services.feishu_parsing import (
    PRD_URL_ALIAS,
    PRD_URL_FIELD_KEY,
    FeishuResponseError,
    RelationSpec,
    build_feishu_fields,
    derive_relations_from_fields,
    extract_prd_url,
    extract_related_ids,
    extract_select_label,
    extract_tech_doc_url,
    find_field,
    flatten_fields,
    parse_comments,
    rich_text_to_markdown,
    safe_response_json,
    strict_response_json,
)

# === DOMAIN §16 实测字段 fixture ===

# story 1000000002 的代表性字段（含 prd_url link / select / 三个关联字段）
STORY_RAW_FIELDS = [
    {
        "field_key": PRD_URL_FIELD_KEY,
        "field_name": "需求文档",
        "field_value": "https://tenant.feishu.cn/docx/doc_token_abc",
        "field_type_key": "link",
        "field_alias": PRD_URL_ALIAS,
    },
    {
        "field_key": "field_000002",
        "field_name": "小组",
        "field_value": {"label": "示例组A", "value": "opt_1"},
        "field_type_key": "select",
        "field_alias": "example_platform_group",
    },
    {
        "field_key": "field_000008",
        "field_name": "所属项目",
        "field_value": [1000000004],
        "field_type_key": "work_item_related_multi_select",
        "field_alias": None,
    },
    {
        "field_key": "planning_sprint",
        "field_name": "所属迭代",
        "field_value": [6290075691],
        "field_type_key": "work_item_related_multi_select",
        "field_alias": "planning_sprint",
    },
    {
        "field_key": "planning_version",
        "field_name": "规划版本",
        "field_value": [],
        "field_type_key": "work_item_related_multi_select",
        "field_alias": "planning_version",
    },
]


def _json_response(payload: dict) -> httpx.Response:
    """本地构造一个 content-type=json 的 httpx.Response（不发请求）。"""
    return httpx.Response(200, json=payload)


def _text_response(text: str, content_type: str = "text/html") -> httpx.Response:
    """本地构造一个非 JSON 的 httpx.Response（不发请求）。"""
    return httpx.Response(200, text=text, headers={"content-type": content_type})


# === 防御式 JSON 解析 ===


def test_safe_response_json_valid() -> None:
    """合法 JSON 响应返回解析后的 dict。"""
    resp = _json_response({"err_code": 0, "data": []})
    assert safe_response_json(resp, log_event="feishu.test") == {
        "err_code": 0,
        "data": [],
    }


def test_safe_response_json_html_returns_none() -> None:
    """content-type=text/html 的响应 fail-soft 返回 None，不抛异常。"""
    resp = _text_response("<html><body>error</body></html>")
    assert safe_response_json(resp, log_event="feishu.test") is None


def test_safe_response_json_extra_data_returns_none() -> None:
    """body 为非 JSON（即便声明 json）→ fail-soft 返回 None。"""
    resp = httpx.Response(
        200,
        text="Extra data: line 1 column 5",
        headers={"content-type": "application/json"},
    )
    assert safe_response_json(resp, log_event="feishu.test") is None


def test_safe_response_json_expect_dict_list_returns_none() -> None:
    """合法 JSON 但为 list（expect=dict）→ fail-soft 返回 None（WR-01）。"""
    resp = _json_response([])  # 合法 JSON list
    assert safe_response_json(resp, log_event="feishu.test", expect=dict) is None


def test_safe_response_json_expect_dict_scalar_returns_none() -> None:
    """合法 JSON 但为标量/字符串（expect=dict）→ fail-soft 返回 None（WR-01）。"""
    resp_str = httpx.Response(200, json="err")  # 合法 JSON 字符串
    resp_int = httpx.Response(200, json=123)  # 合法 JSON 数字
    assert safe_response_json(resp_str, log_event="feishu.test", expect=dict) is None
    assert safe_response_json(resp_int, log_event="feishu.test", expect=dict) is None


def test_safe_response_json_expect_dict_passthrough() -> None:
    """合法 JSON dict（expect=dict）→ 原样返回（类型匹配）。"""
    resp = _json_response({"err_code": 0})
    assert safe_response_json(resp, log_event="feishu.test", expect=dict) == {"err_code": 0}


def test_strict_response_json_valid() -> None:
    """合法 JSON 响应返回 dict。"""
    resp = _json_response({"err_code": 0})
    assert strict_response_json(resp, log_event="feishu.test") == {"err_code": 0}


def test_strict_response_json_non_json_raises() -> None:
    """非 JSON 响应抛 FeishuResponseError（带截断 body 片段）。"""
    resp = _text_response("Extra data: line 1 column 5", content_type="text/plain")
    raised = False
    try:
        strict_response_json(resp, log_event="feishu.test")
    except FeishuResponseError as exc:
        raised = True
        # 异常消息只含 body 截断片段，不含凭证
        assert "Extra data" in str(exc)
    assert raised


# === 字段保留 / 拍平 / 提取 ===


def test_build_feishu_fields_preserves_all_keys() -> None:
    """build_feishu_fields 完整保留 5 个键（FIX-04 元数据不丢）。"""
    fields = build_feishu_fields(STORY_RAW_FIELDS)
    assert len(fields) == 5
    prd = fields[0]
    assert set(prd.keys()) == {
        "field_key",
        "field_name",
        "field_value",
        "field_type_key",
        "field_alias",
    }
    assert prd["field_name"] == "需求文档"
    assert prd["field_type_key"] == "link"
    assert prd["field_alias"] == PRD_URL_ALIAS


def test_build_feishu_fields_skips_non_dict() -> None:
    """畸形（非 dict）项被跳过，不抛异常。"""
    fields = build_feishu_fields([{"field_key": "a"}, "garbage", None])
    assert len(fields) == 1


def test_flatten_fields_backward_compatible() -> None:
    """flatten_fields 仍产出 {field_key: field_value}（向后兼容）。"""
    flat = flatten_fields(STORY_RAW_FIELDS)
    assert flat[PRD_URL_FIELD_KEY] == "https://tenant.feishu.cn/docx/doc_token_abc"
    assert flat["field_000008"] == [1000000004]


def test_find_field_by_key_and_alias() -> None:
    """find_field 支持按 key 与 alias 查找。"""
    fields = build_feishu_fields(STORY_RAW_FIELDS)
    by_key = find_field(fields, key="field_000002")
    by_alias = find_field(fields, alias="example_platform_group")
    assert by_key is not None and by_key is by_alias
    assert find_field(fields, key="missing") is None


def test_extract_prd_url_by_alias() -> None:
    """extract_prd_url 从含 alias prd_url 的字段取出 docx 链接。"""
    fields = build_feishu_fields(STORY_RAW_FIELDS)
    assert extract_prd_url(fields) == "https://tenant.feishu.cn/docx/doc_token_abc"


def test_extract_prd_url_by_key_fallback() -> None:
    """alias 缺失时回退按 key field_000001 提取。"""
    fields = build_feishu_fields(
        [
            {
                "field_key": PRD_URL_FIELD_KEY,
                "field_name": "需求文档",
                "field_value": "https://x.feishu.cn/docx/tok",
                "field_type_key": "link",
                "field_alias": None,
            }
        ]
    )
    assert extract_prd_url(fields) == "https://x.feishu.cn/docx/tok"


def test_extract_prd_url_missing_returns_empty() -> None:
    """无 prd 字段返回空串。"""
    assert extract_prd_url([]) == ""


def test_extract_tech_doc_url_by_key() -> None:
    """extract_tech_doc_url 按 key field_000009 提取。"""
    fields = build_feishu_fields(
        [
            {
                "field_key": "field_000009",
                "field_name": "技术方案",
                "field_value": "https://x.feishu.cn/docx/tech",
                "field_type_key": "link",
                "field_alias": None,
            }
        ]
    )
    assert extract_tech_doc_url(fields) == "https://x.feishu.cn/docx/tech"


def test_extract_select_label() -> None:
    """extract_select_label 从 {label, value} 取 label。"""
    assert extract_select_label({"label": "示例组A", "value": "opt_1"}) == "示例组A"
    assert extract_select_label("not a dict") is None
    assert extract_select_label({"value": "no_label"}) is None


def test_extract_related_ids_variants() -> None:
    """extract_related_ids 归一 int / 数字字符串 / dict，跳过非 list。"""
    assert extract_related_ids([1000000004]) == [1000000004]
    assert extract_related_ids(["123", 456]) == [123, 456]
    assert extract_related_ids([{"id": 789}]) == [789]
    assert extract_related_ids([]) == []
    assert extract_related_ids("not a list") == []


# === 富文本 → Markdown ===


def test_rich_text_to_markdown_paragraph_with_bold() -> None:
    """paragraph + bold mark 转 Markdown（与原 _parse_rich_text 等价）。"""
    rich = {
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "前缀"},
                    {"type": "text", "text": "加粗", "marks": [{"type": "bold"}]},
                ],
            }
        ]
    }
    assert rich_text_to_markdown(rich) == "前缀**加粗**"


def test_rich_text_to_markdown_str_passthrough() -> None:
    """str 输入原样返回；非 dict/str 输入转字符串。"""
    assert rich_text_to_markdown("plain") == "plain"
    assert rich_text_to_markdown(None) == ""


def test_rich_text_to_markdown_heading_and_link() -> None:
    """heading 级别 + link mark 行为等价。"""
    rich = {
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": "标题"}],
            },
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "链接",
                        "marks": [{"type": "link", "attrs": {"href": "https://x.com"}}],
                    }
                ],
            },
        ]
    }
    assert rich_text_to_markdown(rich) == "## 标题\n[链接](https://x.com)"


# === 关系派生（FIX-02）===


def test_derive_relations_belongs_to_project() -> None:
    """field_000008=[1000000004] → belongs_to_project（DOMAIN §16 实测）。"""
    fields = build_feishu_fields(STORY_RAW_FIELDS)
    specs = derive_relations_from_fields(fields)
    project_specs = [s for s in specs if s.source_field_key == "field_000008"]
    assert len(project_specs) == 1
    spec = project_specs[0]
    assert spec == RelationSpec(
        relation_type="belongs_to_project",
        source_field_key="field_000008",
        target_external_id=1000000004,
        origin="feishu_field",
    )


def test_derive_relations_sprint() -> None:
    """planning_sprint=[6290075691] → sprint。"""
    fields = build_feishu_fields(STORY_RAW_FIELDS)
    specs = derive_relations_from_fields(fields)
    sprint_specs = [s for s in specs if s.source_field_key == "planning_sprint"]
    assert len(sprint_specs) == 1
    assert sprint_specs[0].relation_type == "sprint"
    assert sprint_specs[0].target_external_id == 6290075691


def test_derive_relations_empty_value_skipped() -> None:
    """空 [] 关联值（planning_version）不产出关系。"""
    fields = build_feishu_fields(STORY_RAW_FIELDS)
    specs = derive_relations_from_fields(fields)
    assert not [s for s in specs if s.source_field_key == "planning_version"]


def test_derive_relations_unknown_field_is_related() -> None:
    """未知关联字段归 related。"""
    fields = build_feishu_fields(
        [
            {
                "field_key": "field_unknown",
                "field_name": "未知关联",
                "field_value": [111],
                "field_type_key": "work_item_related_multi_select",
                "field_alias": None,
            }
        ]
    )
    specs = derive_relations_from_fields(fields)
    assert len(specs) == 1
    assert specs[0].relation_type == "related"
    assert specs[0].target_external_id == 111


def test_derive_relations_ignores_non_relation_fields() -> None:
    """非关联类型字段（select / multi_text）被忽略，不产出关系。"""
    fields = build_feishu_fields(
        [
            {
                "field_key": "field_000002",
                "field_name": "小组",
                "field_value": {"label": "示例组A", "value": "opt_1"},
                "field_type_key": "select",
                "field_alias": "example_platform_group",
            },
            {
                "field_key": "description",
                "field_name": "描述",
                "field_value": "text",
                "field_type_key": "multi_text",
                "field_alias": None,
            },
        ]
    )
    assert derive_relations_from_fields(fields) == []


# === 评论解析（FIX-03）===


def test_parse_comments_shape() -> None:
    """对齐 comment/list 形状逐条取 id/content/created_at/author/thread_parent_id。"""
    data = {
        "err_code": 0,
        "data": {
            "comments": [
                {
                    "id": "c1",
                    "content": {
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "评论正文"}],
                            }
                        ]
                    },
                    "created_at": 1700000000,
                    "author": {"name": "张三"},
                    "parent_id": "c0",
                }
            ]
        },
    }
    comments = parse_comments(data)
    assert len(comments) == 1
    c = comments[0]
    assert c["id"] == "c1"
    assert c["content"] == "评论正文"
    assert c["created_at"] == 1700000000
    assert c["author"] == "张三"
    assert c["thread_parent_id"] == "c0"


def test_parse_comments_author_fallback() -> None:
    """缺 author.name → Unknown；无 parent → thread_parent_id 空串。"""
    data = {"data": {"comments": [{"id": "c2", "content": "纯文本"}]}}
    comments = parse_comments(data)
    assert comments[0]["author"] == "Unknown"
    assert comments[0]["thread_parent_id"] == ""
    assert comments[0]["content"] == "纯文本"


def test_parse_comments_none_returns_empty() -> None:
    """data=None / 缺 comments 键 / 形状不符 → []，不抛异常。"""
    assert parse_comments(None) == []
    assert parse_comments({}) == []
    assert parse_comments({"data": {}}) == []
    assert parse_comments({"data": {"comments": "not a list"}}) == []
    assert parse_comments("garbage") == []
