"""blueprint_schema 纯函数测试（PLAN 111-01 Task 1，SCHEMA-01 / SCHEMA-07）。

覆盖：合法样例通过 / 顶层缺段拒绝（参数化）/ 段内必填缺失拒绝 / v0 pass-through /
引用完整性 / feature_point_id 解析 / 枚举非法值 / iter_blocks 覆盖与路径形状 /
block 级 diff 三分类与确定性。纯函数，无 django_db。
"""

from __future__ import annotations

import copy

import pytest

from services.process_runtime.blueprint_schema import (
    BLUEPRINT_SCHEMA_VERSION,
    diff_blueprint_blocks,
    iter_blocks,
    validate_blueprint,
)
from tests.helpers.blueprint_samples import make_blueprint

_BLOCK_TYPES = {"paragraph", "pseudocode", "table", "list", "mermaid"}


def _count_blocks(node) -> int:
    """递归统计样例中的 Block 数（带 block_id 且 type 为块类型的 dict）。"""
    count = 0
    if isinstance(node, dict):
        if node.get("block_id") and node.get("type") in _BLOCK_TYPES:
            count += 1
        for value in node.values():
            count += _count_blocks(value)
    elif isinstance(node, list):
        for item in node:
            count += _count_blocks(item)
    return count


# ---- 合法样例 ----


def test_make_blueprint_passes_validation():
    ok, err = validate_blueprint(make_blueprint())
    assert (ok, err) == (True, None)


def test_non_dict_rejected():
    ok, err = validate_blueprint(["not", "a", "dict"])
    assert ok is False
    assert "JSON 对象" in (err or "")


# ---- 顶层缺段拒绝（六段 + meta + requirement_spec + must_haves + citations）----


@pytest.mark.parametrize(
    "missing_key",
    [
        "meta",
        "requirement_spec",
        "repo_associations",
        "current_state_analysis",
        "implementation_overview",
        "api_contracts",
        "impact_analysis",
        "interaction_flows",
        "must_haves",
        "citations",
    ],
)
def test_missing_required_top_level_key_rejected(missing_key):
    content = make_blueprint()
    content.pop(missing_key)
    ok, err = validate_blueprint(content)
    assert ok is False
    assert missing_key in (err or "")


# ---- 段内必填字段缺失拒绝 ----


def test_meta_missing_project_id_rejected():
    content = make_blueprint()
    content["meta"].pop("project_id")
    ok, err = validate_blueprint(content)
    assert ok is False
    assert "project_id" in (err or "")


def test_item_missing_title_rejected():
    content = make_blueprint()
    content["implementation_overview"]["items"][0].pop("title")
    ok, err = validate_blueprint(content)
    assert ok is False
    assert "title" in (err or "")


def test_feature_point_missing_intent_rejected():
    """FLOW-01：intent 是 feature_point 必填枚举——缺失即被 validate_blueprint 拒绝。"""
    content = make_blueprint()
    content["requirement_spec"]["feature_points"][0].pop("intent")
    ok, err = validate_blueprint(content)
    assert ok is False
    assert "intent" in (err or "")


def test_feature_point_invalid_intent_rejected():
    """枚举白名单在 schema 内——非法意图值（refactor）不得过门。"""
    content = make_blueprint()
    content["requirement_spec"]["feature_points"][0]["intent"] = "refactor"
    ok, err = validate_blueprint(content)
    assert ok is False
    assert err


@pytest.mark.parametrize("intent", ["greenfield", "brownfield", "fix"])
def test_feature_point_intent_enum_accepted(intent):
    """三个合法枚举值均通过（正向白名单覆盖，驱动 blueprint_route 加权）。"""
    content = make_blueprint()
    content["requirement_spec"]["feature_points"][0]["intent"] = intent
    ok, err = validate_blueprint(content)
    assert (ok, err) == (True, None)


def test_finding_missing_citations_rejected():
    content = make_blueprint()
    content["current_state_analysis"][0]["findings"][0].pop("citations")
    ok, err = validate_blueprint(content)
    assert ok is False
    assert "citations" in (err or "")


# ---- v0 pass-through ----


def test_v0_shape_without_schema_version_passes_through():
    ok, err = validate_blueprint({"title": "t", "summary": "s", "execution_plan": []})
    assert (ok, err) == (True, None)


def test_schema_version_constant():
    assert BLUEPRINT_SCHEMA_VERSION == "blueprint/v1"


# ---- 引用完整性 ----


def test_block_citation_not_in_pool_rejected():
    content = make_blueprint()
    content["current_state_analysis"][0]["findings"][0]["citations"] = ["cit_missing"]
    ok, err = validate_blueprint(content)
    assert ok is False
    assert "cit_missing" in (err or "")


def test_feature_point_id_unresolvable_rejected():
    content = make_blueprint()
    content["implementation_overview"]["items"][0]["feature_point_id"] = "fp_nope"
    ok, err = validate_blueprint(content)
    assert ok is False
    assert "fp_nope" in (err or "")


def test_item_repository_id_not_in_associations_rejected():
    """MJ-01：items[].repository_id 必须存在于 repo_associations（坏仓 id 不得过门）。"""
    content = make_blueprint()
    content["implementation_overview"]["items"][0]["repository_id"] = "repo-ghost"
    ok, err = validate_blueprint(content)
    assert ok is False
    assert "repo-ghost" in (err or "")
    assert "repo_associations" in (err or "")


def test_current_state_analysis_repository_id_not_in_associations_rejected():
    """MJ-01：current_state_analysis[].repository_id 同款引用完整性。"""
    content = make_blueprint()
    content["current_state_analysis"][0]["repository_id"] = "repo-ghost"
    ok, err = validate_blueprint(content)
    assert ok is False
    assert "repo-ghost" in (err or "")
    assert "repo_associations" in (err or "")


def test_citation_pool_key_mismatch_rejected():
    """MN-09：引用池 key 与条目 citation_id 不一致 → 拒绝（否则引用判定两头落空）。"""
    content = make_blueprint()
    content["citations"]["cit_repo_file"]["citation_id"] = "cite_1"
    ok, err = validate_blueprint(content)
    assert ok is False
    assert "cit_repo_file" in (err or "")


@pytest.mark.parametrize(
    ("section", "duplicate"),
    [
        ("implementation_overview.items", "impl_01"),
        ("requirement_spec.feature_points", "fp_01"),
        ("api_contracts", "api_01"),
    ],
)
def test_duplicate_ids_rejected(section, duplicate):
    """MN-08：id 重复 → 拒绝（按 id 建索引的下游会静默后者胜出）。"""
    content = make_blueprint()
    if section == "implementation_overview.items":
        records = content["implementation_overview"]["items"]
    elif section == "requirement_spec.feature_points":
        records = content["requirement_spec"]["feature_points"]
    else:
        records = content["api_contracts"]
    clone = copy.deepcopy(records[0])
    clone["id"] = duplicate
    records.append(clone)

    ok, err = validate_blueprint(content)
    assert ok is False
    assert duplicate in (err or "")
    assert "重复 id" in (err or "")


def test_indirect_repository_id_accepted_in_items():
    """indirect 仓也在 repo_associations 中——引用完整性只查在册与否，不查 role。"""
    content = make_blueprint()
    content["implementation_overview"]["items"][0]["repository_id"] = "repo-shared"
    ok, err = validate_blueprint(content)
    assert (ok, err) == (True, None)


# ---- 报错出口脱敏与截断（MJ-03）----


def test_validation_error_truncated():
    """jsonschema 把整段实例 repr 拼进 message；出口必须截断，不做无界正文回显。"""
    content = make_blueprint()
    content["requirement_spec"] = ["超长正文" * 500]
    ok, err = validate_blueprint(content)
    assert ok is False
    assert err is not None
    assert err.endswith("…（已截断）")
    assert len(err) < 600


def test_validation_error_redacts_secrets():
    """半可信正文里夹带的凭证样本不得原样进 API 响应与日志。"""
    content = make_blueprint()
    content["requirement_spec"] = "sk-ant-api03-SECRETVALUE1234567890"
    ok, err = validate_blueprint(content)
    assert ok is False
    assert "sk-ant-api03-SECRETVALUE1234567890" not in (err or "")
    assert "REDACTED" in (err or "")


def test_validation_exception_path_also_formatted(monkeypatch):
    """兜底 except 出口同样走脱敏 + 截断。"""
    from types import SimpleNamespace

    import services.process_runtime.blueprint_schema as schema_module

    def _boom(_content):
        raise RuntimeError("Bearer sk-ant-leaked-token-value")

    monkeypatch.setattr(schema_module, "_VALIDATOR", SimpleNamespace(iter_errors=_boom))
    ok, err = validate_blueprint(make_blueprint())
    assert ok is False
    assert err is not None
    assert err.startswith("blueprint 校验异常: ")
    assert "sk-ant-leaked-token-value" not in err


# ---- 枚举非法值拒绝 ----


def test_invalid_role_enum_rejected():
    content = make_blueprint()
    content["repo_associations"][0]["role"] = "both"
    ok, err = validate_blueprint(content)
    assert ok is False
    assert "both" in (err or "")


def test_invalid_change_type_enum_rejected():
    # 蓝图侧 change_type 只认 create/modify/remove/indirect_refine——delete 是
    # technical_plan 侧 files.action 的值，混用必须被拒。
    content = make_blueprint()
    content["implementation_overview"]["items"][0]["change_type"] = "delete"
    ok, err = validate_blueprint(content)
    assert ok is False


def test_invalid_finding_kind_enum_rejected():
    content = make_blueprint()
    content["current_state_analysis"][0]["findings"][0]["kind"] = "misc"
    ok, err = validate_blueprint(content)
    assert ok is False


# ---- iter_blocks ----


def test_iter_blocks_covers_all_sample_blocks():
    content = make_blueprint()
    blocks = iter_blocks(content)
    assert len(blocks) == _count_blocks(content)
    block_ids = [block["block_id"] for _path, block in blocks]
    assert len(block_ids) == len(set(block_ids)), "样例 block_id 必须唯一"


def test_iter_blocks_section_path_uses_id_index():
    paths = {path for path, _block in iter_blocks(make_blueprint())}
    assert "implementation_overview.items[impl_01].how" in paths
    assert "requirement_spec.feature_points[fp_01].description" in paths
    assert "repo_associations[repo-backend].rationale.text" in paths
    assert "current_state_analysis[repo-backend].findings[cs_01].text" in paths
    assert "interaction_flows[flow_01].steps[1].note" in paths


def test_iter_blocks_defensive_on_non_dict():
    assert iter_blocks(None) == []
    assert iter_blocks({"meta": "oops", "repo_associations": "oops"}) == []


# ---- block 级 diff（SCHEMA-07）----


def _make_v2(v1: dict) -> dict:
    v2 = copy.deepcopy(v1)
    # 修改一个块
    v2["meta"]["summary"][0]["text"] = "修改后的执行摘要。"
    # 删除一个块
    v2["impact_analysis"]["rollback_plan"] = []
    # 新增一个块
    v2["requirement_spec"]["background"].append(
        {"block_id": "blk_new_note", "type": "paragraph", "text": "新增的背景补充。"}
    )
    return v2


def test_diff_blueprint_blocks_three_way():
    v1 = make_blueprint()
    v2 = _make_v2(v1)
    diff = diff_blueprint_blocks(v1, v2)
    assert diff == {
        "added": ["blk_new_note"],
        "removed": ["blk_impact_rollback"],
        "modified": ["blk_meta_summary"],
    }


def test_diff_blueprint_blocks_deterministic():
    v1 = make_blueprint()
    v2 = _make_v2(v1)
    assert diff_blueprint_blocks(v1, v2) == diff_blueprint_blocks(v1, v2)


def test_diff_identical_versions_empty():
    v1 = make_blueprint()
    assert diff_blueprint_blocks(v1, copy.deepcopy(v1)) == {
        "added": [],
        "removed": [],
        "modified": [],
    }
