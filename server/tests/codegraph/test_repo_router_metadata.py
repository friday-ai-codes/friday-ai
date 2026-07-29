"""元数据 resolver 测试（Phase 106-03，ROUTE-04 三层匹配 T1/T2）。

锁定语义（106-CONTEXT / 106-RESEARCH §2，全部写成测试）：
- T1 确定性别名词典：canonical/alias 命中 1.0、仅 parent（上位类目）命中 0.6、
  未命中 None——纯函数、零网络零 DB，golden harness（106-08）可离线 import。
- `技术栈` 单字符串多值（"Python/Vue/Go"）split("/") 后按
  ``0.8·max + 0.2·second_max`` 聚合——绝不 sum/mean（尺寸偏置同构重演）。
- "未分类"/空串/缺失/超长（>200 字符，DoS 护栏）→ 信号不可用
  （{score: None, layer: None}，进重归一化），不补 0。
- `团队归属` 条件信号：需求文本未提团队 → None（不给 0.5）；只走 T1。
- 输出契约与 repo_router_scoring 的 repo_meta.facet_scores 键契约严格一致
  （{"domain"|"stack"|"team": {"score", "layer"}}）。
"""

from __future__ import annotations

import pytest

from codegraph.services.repo_router_metadata import (
    DEFAULT_ALIAS_DICT,
    FACET_ACTIVITY,
    FACET_CRITICALITY,
    FACET_DOMAIN,
    FACET_STACK,
    FACET_TEAM,
    LAYER_T1,
    UNCLASSIFIED_VALUE,
    alias_dict_hash,
    match_t1,
    merge_alias_dict,
    resolve_facet_scores,
)

# 测试用别名词典（domain/team 维度 DEFAULT 为空骨架，测试自带条目）
_TEST_ALIAS_DICT = {
    FACET_DOMAIN: {
        "高三提分": {"aliases": ["提分专项"], "parent": "K12教育"},
    },
    FACET_TEAM: {
        "group/sub": {"aliases": ["基础平台组"], "parent": None},
    },
}


# ============================================================================
# match_t1：T1 确定性匹配纯函数（1.0 / 0.6 / None）
# ============================================================================


class TestMatchT1:
    def test_canonical_substring_hit(self):
        """canonical 值本身子串命中 → 1.0（无需词典条目）。"""
        assert match_t1("给高三提分专项加功能", FACET_DOMAIN, "高三提分", {}) == 1.0

    def test_alias_hit(self):
        """query 仅含别名（不含 canonical）→ 1.0。"""
        assert match_t1("提分专项要加导出功能", FACET_DOMAIN, "高三提分", _TEST_ALIAS_DICT) == 1.0

    def test_parent_only_hit(self):
        """canonical 与别名均未命中、仅上位类目命中 → 0.6。"""
        assert match_t1("K12教育行业的通用改造", FACET_DOMAIN, "高三提分", _TEST_ALIAS_DICT) == 0.6

    def test_no_hit_returns_none(self):
        """均未命中 → None（不可用，非 0）。"""
        assert match_t1("完全无关的一条需求", FACET_DOMAIN, "高三提分", _TEST_ALIAS_DICT) is None

    def test_case_insensitive_match(self):
        """大小写不敏感（casefold）：query 小写命中 canonical "Python"。"""
        assert match_t1("优化 python 后端接口", FACET_STACK, "Python", DEFAULT_ALIAS_DICT) == 1.0

    def test_default_dict_language_alias(self):
        """DEFAULT_ALIAS_DICT 内置语言别名：golang → Go。"""
        assert match_t1("golang 服务迁移到新集群", FACET_STACK, "Go", DEFAULT_ALIAS_DICT) == 1.0

    def test_short_ascii_alias_no_false_positive(self):
        """ASCII 短 token 词边界防误报：django 不得命中 Go、tests 不得命中 ts。"""
        assert match_t1("升级 django 配置", FACET_STACK, "Go", DEFAULT_ALIAS_DICT) is None
        assert match_t1("补充 tests 覆盖", FACET_STACK, "TypeScript", DEFAULT_ALIAS_DICT) is None

    def test_overlong_value_returns_none(self):
        """超长 facet 值（>200 字符）→ 直接不可匹配（DoS 护栏）。"""
        long_value = "长" * 201
        # query 即值本身——若无长度护栏会误判 1.0
        assert match_t1(long_value, FACET_DOMAIN, long_value, {}) is None

    def test_empty_or_non_str_value_returns_none(self):
        assert match_t1("任意需求", FACET_DOMAIN, "", {}) is None
        assert match_t1("任意需求", FACET_DOMAIN, None, {}) is None

    def test_default_dict_covers_ext_language_map(self):
        """技术栈维度骨架照抄 facet_service._EXT_LANGUAGE_MAP 全部语言名。"""
        from repositories.facet_service import _EXT_LANGUAGE_MAP

        stack_entries = DEFAULT_ALIAS_DICT[FACET_STACK]
        assert set(_EXT_LANGUAGE_MAP.values()) <= set(stack_entries)

    def test_default_dict_has_all_seven_dimensions(self):
        """五个 facet 维度 + 服务对象/技术形态 全部有骨架键（空骨架亦可）。"""
        for dim in (
            FACET_DOMAIN,
            FACET_STACK,
            FACET_TEAM,
            FACET_CRITICALITY,
            FACET_ACTIVITY,
            "服务对象",
            "技术形态",
        ):
            assert dim in DEFAULT_ALIAS_DICT


# ============================================================================
# resolve_facet_scores：facet_scores 组装（T1-only 路径；T2 见 Task 2）
# ============================================================================


class TestResolveFacetScores:
    async def test_output_contract_three_signals(self):
        """输出键恰为 domain/stack/team，形状 {score, layer}（scorer 契约）。"""
        result = await resolve_facet_scores("任意需求", {}, alias_dict={}, constants={})
        assert set(result) == {"domain", "stack", "team"}
        for entry in result.values():
            assert entry == {"score": None, "layer": None}

    async def test_domain_t1_hit(self):
        result = await resolve_facet_scores(
            "给高三提分专项加功能",
            {FACET_DOMAIN: "高三提分"},
            alias_dict=_TEST_ALIAS_DICT,
            constants={},
        )
        assert result["domain"] == {"score": 1.0, "layer": LAYER_T1}

    async def test_domain_parent_hit_scores_point_six(self):
        result = await resolve_facet_scores(
            "K12教育行业的通用改造",
            {FACET_DOMAIN: "高三提分"},
            alias_dict=_TEST_ALIAS_DICT,
            constants={},
        )
        assert result["domain"] == {"score": 0.6, "layer": LAYER_T1}

    async def test_domain_t1_miss_without_t2_returns_none(self):
        """T1 未命中且 t2_matcher 不可用 → 不可用（None），不给兜底分。"""
        result = await resolve_facet_scores(
            "完全无关的需求",
            {FACET_DOMAIN: "高三提分"},
            alias_dict=_TEST_ALIAS_DICT,
            constants={},
        )
        assert result["domain"] == {"score": None, "layer": None}

    async def test_stack_multivalue_max_aggregation(self):
        """ "Python/Vue/Go" 仅命中 Python → 0.8·1.0 + 0.2·0 = 0.8（绝不 sum/mean）。"""
        result = await resolve_facet_scores(
            "python 后端接口优化",
            {FACET_STACK: "Python/Vue/Go"},
            alias_dict=DEFAULT_ALIAS_DICT,
            constants={},
        )
        assert result["stack"]["score"] == pytest.approx(0.8)
        assert result["stack"]["layer"] == LAYER_T1

    async def test_stack_two_hits_uses_second_max(self):
        """Python 与 Vue 双命中 → 0.8·1.0 + 0.2·1.0 = 1.0。"""
        result = await resolve_facet_scores(
            "python 后端加 vue 前端联调",
            {FACET_STACK: "Python/Vue/Go"},
            alias_dict=DEFAULT_ALIAS_DICT,
            constants={},
        )
        assert result["stack"]["score"] == pytest.approx(1.0)
        assert result["stack"]["layer"] == LAYER_T1

    async def test_stack_no_hit_unavailable(self):
        """全部值未命中 → 信号不可用（None），标签多的仓不因此得分更高。"""
        result = await resolve_facet_scores(
            "rust 重写存储层",
            {FACET_STACK: "Python/Vue"},
            alias_dict=DEFAULT_ALIAS_DICT,
            constants={},
        )
        assert result["stack"] == {"score": None, "layer": None}

    async def test_unclassified_domain_unavailable(self):
        """facet 值 "未分类" 视为缺失（Pitfall 2）。"""
        result = await resolve_facet_scores(
            "任意需求",
            {FACET_DOMAIN: UNCLASSIFIED_VALUE},
            alias_dict=_TEST_ALIAS_DICT,
            constants={},
        )
        assert result["domain"] == {"score": None, "layer": None}

    async def test_missing_key_and_empty_value_unavailable(self):
        """facets 缺键 / 值为空串 → 同样不可用。"""
        for facets in ({}, {FACET_DOMAIN: ""}, {FACET_DOMAIN: None}):
            result = await resolve_facet_scores(
                "给高三提分专项加功能",
                facets,
                alias_dict=_TEST_ALIAS_DICT,
                constants={},
            )
            assert result["domain"] == {"score": None, "layer": None}

    async def test_overlong_value_unavailable_no_raise(self):
        """超长值（>200 字符）→ 不可用且不抛异常（T-106-06）。"""
        long_value = "域" * 201
        result = await resolve_facet_scores(
            long_value,
            {FACET_DOMAIN: long_value, FACET_STACK: long_value, FACET_TEAM: long_value},
            alias_dict=_TEST_ALIAS_DICT,
            constants={},
        )
        for entry in result.values():
            assert entry == {"score": None, "layer": None}

    async def test_facets_not_dict_tolerated(self):
        """facets 非 dict（trust boundary 容错）→ 全部不可用，不抛。"""
        result = await resolve_facet_scores(
            "任意需求", None, alias_dict=_TEST_ALIAS_DICT, constants={}
        )
        for entry in result.values():
            assert entry == {"score": None, "layer": None}

    async def test_team_not_mentioned_returns_none(self):
        """条件信号：需求未提任何团队 token → None（不给 0.5）。"""
        result = await resolve_facet_scores(
            "加一个导出功能",
            {FACET_TEAM: "group/sub"},
            alias_dict=_TEST_ALIAS_DICT,
            constants={},
        )
        assert result["team"] == {"score": None, "layer": None}

    async def test_team_namespace_chain_hit(self):
        """query 含 "group/sub" 命名空间链 → 按 T1 打分。"""
        result = await resolve_facet_scores(
            "group/sub 组的仓库加功能",
            {FACET_TEAM: "group/sub"},
            alias_dict=_TEST_ALIAS_DICT,
            constants={},
        )
        assert result["team"] == {"score": 1.0, "layer": LAYER_T1}

    async def test_team_alias_hit(self):
        """query 含团队别名 → 按 T1 打分。"""
        result = await resolve_facet_scores(
            "基础平台组的服务要加监控",
            {FACET_TEAM: "group/sub"},
            alias_dict=_TEST_ALIAS_DICT,
            constants={},
        )
        assert result["team"] == {"score": 1.0, "layer": LAYER_T1}


# ============================================================================
# merge_alias_dict / alias_dict_hash：覆盖合并与快照 hash 纯函数
# ============================================================================


class TestMergeAliasDict:
    def test_override_adds_new_canonical(self):
        merged = merge_alias_dict(
            DEFAULT_ALIAS_DICT,
            {FACET_DOMAIN: {"高三提分": {"aliases": ["提分专项"], "parent": "K12教育"}}},
        )
        assert "高三提分" in merged[FACET_DOMAIN]
        assert merged[FACET_DOMAIN]["高三提分"]["aliases"] == ["提分专项"]

    def test_override_appends_aliases_without_mutating_default(self):
        default = {FACET_STACK: {"Python": {"aliases": ["py"], "parent": None}}}
        merged = merge_alias_dict(default, {FACET_STACK: {"Python": {"aliases": ["蟒蛇"]}}})
        assert merged[FACET_STACK]["Python"]["aliases"] == ["py", "蟒蛇"]
        # default 不被原地修改
        assert default[FACET_STACK]["Python"]["aliases"] == ["py"]

    def test_override_appends_deduped(self):
        default = {FACET_STACK: {"Python": {"aliases": ["py"], "parent": None}}}
        merged = merge_alias_dict(default, {FACET_STACK: {"Python": {"aliases": ["py", "py3"]}}})
        assert merged[FACET_STACK]["Python"]["aliases"] == ["py", "py3"]

    def test_malformed_override_entries_skipped(self):
        """非 dict 结构条目跳过（T-106-08 容错），不抛异常。"""
        merged = merge_alias_dict(
            DEFAULT_ALIAS_DICT,
            {
                FACET_DOMAIN: {"合法条目": {"aliases": ["ok"]}, "坏条目": "not-a-dict"},
                FACET_STACK: "整个维度都不是 dict",
                123: {"数字维度": {}},
            },
        )
        assert "合法条目" in merged[FACET_DOMAIN]
        assert "坏条目" not in merged[FACET_DOMAIN]
        # DEFAULT 的技术栈维度不受坏 override 影响
        assert "Python" in merged[FACET_STACK]

    def test_merge_tolerates_non_dict_override(self):
        merged = merge_alias_dict(DEFAULT_ALIAS_DICT, None)
        assert "Python" in merged[FACET_STACK]

    def test_hash_key_order_invariant(self):
        """键序不同但内容相同 → 相同 sha256（canonical JSON）。"""
        dict_a = {
            FACET_DOMAIN: {"a": {"aliases": ["x"], "parent": None}},
            FACET_STACK: {"Python": {"aliases": ["py"], "parent": None}},
        }
        dict_b = {
            FACET_STACK: {"Python": {"parent": None, "aliases": ["py"]}},
            FACET_DOMAIN: {"a": {"parent": None, "aliases": ["x"]}},
        }
        assert alias_dict_hash(dict_a) == alias_dict_hash(dict_b)
        assert len(alias_dict_hash(dict_a)) == 64  # sha256 hexdigest

    def test_hash_differs_on_content_change(self):
        dict_a = {FACET_DOMAIN: {"a": {"aliases": ["x"], "parent": None}}}
        dict_b = {FACET_DOMAIN: {"a": {"aliases": ["y"], "parent": None}}}
        assert alias_dict_hash(dict_a) != alias_dict_hash(dict_b)
