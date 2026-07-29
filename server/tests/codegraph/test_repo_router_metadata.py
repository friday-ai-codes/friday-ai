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

import hashlib
import math
from unittest.mock import AsyncMock

import pytest
from django.core.cache import cache
from structlog.testing import capture_logs

import codegraph.services.repo_router_metadata as metadata_mod
from codegraph.services.repo_router_metadata import (
    DEFAULT_ALIAS_DICT,
    FACET_ACTIVITY,
    FACET_CRITICALITY,
    FACET_DOMAIN,
    FACET_STACK,
    FACET_TEAM,
    LAYER_T1,
    LAYER_T2,
    UNCLASSIFIED_VALUE,
    FacetT2Matcher,
    alias_dict_hash,
    match_t1,
    merge_alias_dict,
    resolve_facet_scores,
    warm_facet_vectors,
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

    def test_short_ascii_canonical_needs_context(self):
        """MN-08：单/双字符 ASCII canonical 不允许裸值命中，只能经别名。

        词边界挡不住「c 端」「C 轮」这类误报（技术栈=C 的仓会拿满分），
        英文动词 "go" 同理——T1 是确定性层，误报比漏报代价高。
        """
        for query in ("c 端用户增长实验", "C 轮融资数据看板", "先 go 一步做灰度"):
            assert match_t1(query, FACET_STACK, "C", DEFAULT_ALIAS_DICT) is None, query
            assert match_t1(query, FACET_STACK, "Go", DEFAULT_ALIAS_DICT) is None, query
        # 带上下文的别名仍然命中（漏报面由别名词典兜住，运维可扩充）
        assert match_t1("重写 c语言 扩展模块", FACET_STACK, "C", DEFAULT_ALIAS_DICT) == 1.0
        assert match_t1("golang 服务迁移", FACET_STACK, "Go", DEFAULT_ALIAS_DICT) == 1.0
        # 三字符及以上的 ASCII canonical 不受影响
        assert match_t1("升级 rust 版本", FACET_STACK, "Rust", DEFAULT_ALIAS_DICT) == 1.0

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


# ============================================================================
# FacetT2Matcher：校准余弦 + facet 值向量缓存 + 静默降级（Task 2）
# ============================================================================

_QUERY_VEC = [1.0, 0.0]


def _vec_with_cos(c: float) -> list[float]:
    """构造与 _QUERY_VEC 余弦恰为 c 的单位向量。"""
    return [c, math.sqrt(max(0.0, 1.0 - c * c))]


def _facet_vec_key(model_id: str, value: str) -> str:
    """锁定 plan 指定的缓存 key 格式：repo_router:facet_vec:{model_id}:{sha256(value)}。"""
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"repo_router:facet_vec:{model_id}:{digest}"


@pytest.fixture()
def _clear_local_vec_cache():
    """进程内二级缓存跨用例共享——用例前后各清一次（模块级 dict 不随事务回滚）。"""
    metadata_mod._facet_vec_local_cache.clear()
    yield
    metadata_mod._facet_vec_local_cache.clear()


@pytest.mark.usefixtures("_clear_local_vec_cache")
class TestFacetT2Matcher:
    async def test_calibration_clip_three_points(self, monkeypatch):
        """校准 clip 三点：cos=0.55→1.0、0.25→0.0、0.40→0.5（lo=0.25/hi=0.55）。"""
        for cos, expected in ((0.55, 1.0), (0.25, 0.0), (0.40, 0.5)):
            mock = AsyncMock(return_value=_vec_with_cos(cos))
            monkeypatch.setattr("services.embedding.EmbeddingService.generate_embedding", mock)
            matcher = FacetT2Matcher(model_id=f"calib-{cos}", t2_c_lo=0.25, t2_c_hi=0.55)
            score = await matcher.match(_QUERY_VEC, f"校准点-{cos}")
            assert score == pytest.approx(expected)

    async def test_cache_hit_zero_embedding_calls(self, monkeypatch):
        """facet 值向量缓存命中 → 零 embedding 调用（用缓存向量算余弦）。"""
        mock = AsyncMock(return_value=_vec_with_cos(0.55))
        monkeypatch.setattr("services.embedding.EmbeddingService.generate_embedding", mock)
        model_id = "cache-hit-model"
        value = "在线教育"
        cache.set(_facet_vec_key(model_id, value), _vec_with_cos(0.40), timeout=60)
        matcher = FacetT2Matcher(model_id=model_id, t2_c_lo=0.25, t2_c_hi=0.55)
        score = await matcher.match(_QUERY_VEC, value)
        # 命中缓存向量（cos 0.40 → 0.5），而非 mock 的 0.55
        assert score == pytest.approx(0.5)
        assert mock.await_count == 0

    async def test_cache_miss_embeds_once_and_writes_back(self, monkeypatch):
        """miss → 调用一次 embedding 并回写 cache；第二次同值调用次数不增。"""
        mock = AsyncMock(return_value=_vec_with_cos(0.55))
        monkeypatch.setattr("services.embedding.EmbeddingService.generate_embedding", mock)
        model_id = "cache-miss-model"
        value = "唯一值A"
        matcher = FacetT2Matcher(model_id=model_id, t2_c_lo=0.25, t2_c_hi=0.55)
        assert await matcher.match(_QUERY_VEC, value) == pytest.approx(1.0)
        assert mock.await_count == 1
        # Django cache 已回写
        assert cache.get(_facet_vec_key(model_id, value)) is not None
        assert await matcher.match(_QUERY_VEC, value) == pytest.approx(1.0)
        assert mock.await_count == 1

    async def test_embedding_failure_returns_none_and_warns(self, monkeypatch):
        """EmbeddingService 返回 None → match 返回 None + repo_router_t2_degraded 采样 warning。"""
        mock = AsyncMock(return_value=None)
        monkeypatch.setattr("services.embedding.EmbeddingService.generate_embedding", mock)
        matcher = FacetT2Matcher(model_id="fail-model", t2_c_lo=0.25, t2_c_hi=0.55)
        long_value = "长值" * 20  # 40 字符：断言日志截断 32
        with capture_logs() as logs:
            score = await matcher.match(_QUERY_VEC, long_value)
        assert score is None
        degraded = [e for e in logs if e["event"] == "repo_router_t2_degraded"]
        assert degraded, "必须记录 repo_router_t2_degraded warning"
        assert degraded[0]["category"] == "sampling"
        assert len(degraded[0]["facet_value"]) <= 32  # T-106-07 截断

    async def test_resolver_query_embedding_none_all_t1(self, monkeypatch):
        """query_embedding=None → T2 整体不可用（零 embedding 调用），resolver 全走 T1。"""
        mock = AsyncMock(return_value=_vec_with_cos(0.55))
        monkeypatch.setattr("services.embedding.EmbeddingService.generate_embedding", mock)
        matcher = FacetT2Matcher(model_id="no-query-vec", t2_c_lo=0.25, t2_c_hi=0.55)
        result = await resolve_facet_scores(
            "完全无关的需求",
            {FACET_DOMAIN: "高三提分"},
            alias_dict=_TEST_ALIAS_DICT,
            constants={},
            query_embedding=None,
            t2_matcher=matcher,
        )
        assert result["domain"] == {"score": None, "layer": None}
        assert mock.await_count == 0

    async def test_resolver_t2_wiring_layer_t2(self, monkeypatch):
        """T1 未命中且 T2 可用 → 走 T2 校准余弦，layer 标注 t2。"""
        mock = AsyncMock(return_value=_vec_with_cos(0.40))
        monkeypatch.setattr("services.embedding.EmbeddingService.generate_embedding", mock)
        matcher = FacetT2Matcher(model_id="wiring-model", t2_c_lo=0.25, t2_c_hi=0.55)
        result = await resolve_facet_scores(
            "完全无关的需求",
            {FACET_DOMAIN: "高三提分"},
            alias_dict=_TEST_ALIAS_DICT,
            constants={},
            query_embedding=_QUERY_VEC,
            t2_matcher=matcher,
        )
        assert result["domain"]["score"] == pytest.approx(0.5)
        assert result["domain"]["layer"] == LAYER_T2

    async def test_resolver_t2_disabled_facet_stays_t1_only(self, monkeypatch):
        """facet 在 t2_disabled_facets（O-2 放弃条款）→ 不走 T2，零 embedding 调用。"""
        mock = AsyncMock(return_value=_vec_with_cos(0.55))
        monkeypatch.setattr("services.embedding.EmbeddingService.generate_embedding", mock)
        matcher = FacetT2Matcher(model_id="disabled-model", t2_c_lo=0.25, t2_c_hi=0.55)
        result = await resolve_facet_scores(
            "完全无关的需求",
            {FACET_DOMAIN: "高三提分"},
            alias_dict=_TEST_ALIAS_DICT,
            constants={"t2_disabled_facets": ["domain"]},
            query_embedding=_QUERY_VEC,
            t2_matcher=matcher,
        )
        assert result["domain"] == {"score": None, "layer": None}
        assert mock.await_count == 0

    async def test_resolver_accepts_chinese_facet_dim_name_for_disable(self, monkeypatch):
        """MJ-02：填中文维度名（校准报告行键 / 运维习惯）同样停用 T2。

        修复前 resolver 比的是英文 signal 名，运维照命令输出与 UI 提示填
        「业务线/产品线」时 ``signal in disabled`` 恒假——O-2「放弃该 facet 的
        T2 通道」这条硬约束在生产里静默失效。
        """
        mock = AsyncMock(return_value=_vec_with_cos(0.55))
        monkeypatch.setattr("services.embedding.EmbeddingService.generate_embedding", mock)
        matcher = FacetT2Matcher(model_id="cn-disabled-model", t2_c_lo=0.25, t2_c_hi=0.55)
        for disabled_value in ("业务线/产品线", "业务域", "DOMAIN"):
            mock.reset_mock()
            result = await resolve_facet_scores(
                "完全无关的需求",
                {FACET_DOMAIN: "高三提分"},
                alias_dict=_TEST_ALIAS_DICT,
                constants={"t2_disabled_facets": [disabled_value]},
                query_embedding=_QUERY_VEC,
                t2_matcher=matcher,
            )
            assert result["domain"] == {"score": None, "layer": None}, disabled_value
            assert mock.await_count == 0, disabled_value

    async def test_resolver_ignores_unknown_disable_values(self, monkeypatch):
        """无法识别的停用值不误伤其他 facet（校验层已在写入时拒绝，此处不反噬）。"""
        mock = AsyncMock(return_value=_vec_with_cos(0.40))
        monkeypatch.setattr("services.embedding.EmbeddingService.generate_embedding", mock)
        matcher = FacetT2Matcher(model_id="unknown-disable", t2_c_lo=0.25, t2_c_hi=0.55)
        result = await resolve_facet_scores(
            "完全无关的需求",
            {FACET_DOMAIN: "高三提分"},
            alias_dict=_TEST_ALIAS_DICT,
            constants={"t2_disabled_facets": ["不存在的维度", 42]},
            query_embedding=_QUERY_VEC,
            t2_matcher=matcher,
        )
        assert result["domain"]["layer"] == LAYER_T2

    async def test_team_never_uses_t2(self, monkeypatch):
        """团队归属开放集只走 T1——即便 T2 可用也不调 embedding（RESEARCH A3）。"""
        mock = AsyncMock(return_value=_vec_with_cos(0.55))
        monkeypatch.setattr("services.embedding.EmbeddingService.generate_embedding", mock)
        matcher = FacetT2Matcher(model_id="team-model", t2_c_lo=0.25, t2_c_hi=0.55)
        result = await resolve_facet_scores(
            "需求未提任何团队",
            {FACET_TEAM: "group/sub"},
            alias_dict=_TEST_ALIAS_DICT,
            constants={},
            query_embedding=_QUERY_VEC,
            t2_matcher=matcher,
        )
        assert result["team"] == {"score": None, "layer": None}
        assert mock.await_count == 0


@pytest.mark.usefixtures("_clear_local_vec_cache")
class TestT2EmbedBudget:
    """MJ-06：单实例（== 单次路由）embedding 次数硬上限，超限静默降级 T1-only。"""

    async def test_budget_caps_embedding_calls_and_degrades_silently(self, monkeypatch):
        mock = AsyncMock(return_value=_vec_with_cos(0.40))
        monkeypatch.setattr("services.embedding.EmbeddingService.generate_embedding", mock)
        matcher = FacetT2Matcher(
            model_id="budget-model", t2_c_lo=0.25, t2_c_hi=0.55, embed_budget=2
        )

        scores = [await matcher.match(_QUERY_VEC, f"未缓存值-{i}") for i in range(5)]

        assert mock.await_count == 2  # 预算 2 次用尽后不再发请求
        assert scores[0] is not None and scores[1] is not None
        assert scores[2:] == [None, None, None]  # 降级 T1-only，不抛异常

    async def test_no_budget_means_unlimited(self, monkeypatch):
        """离线场景（校准 command）不传预算 → 不限次数。"""
        mock = AsyncMock(return_value=_vec_with_cos(0.40))
        monkeypatch.setattr("services.embedding.EmbeddingService.generate_embedding", mock)
        matcher = FacetT2Matcher(model_id="unlimited-model", t2_c_lo=0.25, t2_c_hi=0.55)

        for i in range(4):
            assert await matcher.match(_QUERY_VEC, f"另一批未缓存值-{i}") is not None

        assert mock.await_count == 4


@pytest.mark.usefixtures("_clear_local_vec_cache")
class TestWarmFacetVectors:
    async def test_warm_batch_success_count(self, monkeypatch):
        """批量预热：成功条数按可用向量计；预热后 match 零单条 embedding 调用。"""
        batch_mock = AsyncMock(return_value=[_vec_with_cos(0.5), None, _vec_with_cos(0.3)])
        monkeypatch.setattr(
            "services.embedding.EmbeddingService.generate_embeddings_batch", batch_mock
        )
        matcher = FacetT2Matcher(model_id="warm-model", t2_c_lo=0.25, t2_c_hi=0.55)
        count = await warm_facet_vectors(["值一", "值二", "值三"], matcher)
        assert count == 2
        assert batch_mock.await_count == 1
        single_mock = AsyncMock(return_value=_vec_with_cos(0.9))
        monkeypatch.setattr("services.embedding.EmbeddingService.generate_embedding", single_mock)
        assert await matcher.match(_QUERY_VEC, "值一") is not None
        assert single_mock.await_count == 0

    async def test_warm_skips_invalid_and_dedupes(self, monkeypatch):
        """无效值（空/未分类/非 str/超长）跳过，重复值去重后只 embed 一次。"""
        batch_mock = AsyncMock(return_value=[_vec_with_cos(0.5)])
        monkeypatch.setattr(
            "services.embedding.EmbeddingService.generate_embeddings_batch", batch_mock
        )
        matcher = FacetT2Matcher(model_id="warm-skip-model", t2_c_lo=0.25, t2_c_hi=0.55)
        values = ["同值", "同值", "", UNCLASSIFIED_VALUE, None, "长" * 201]
        count = await warm_facet_vectors(values, matcher)
        assert count == 1
        batch_mock.assert_awaited_once_with(["同值"])

    async def test_warm_counts_already_cached(self, monkeypatch):
        """已在缓存的值计入成功条数且不重复 embed。"""
        model_id = "warm-cached-model"
        cache.set(_facet_vec_key(model_id, "已缓存值"), _vec_with_cos(0.4), timeout=60)
        batch_mock = AsyncMock(return_value=[_vec_with_cos(0.5)])
        monkeypatch.setattr(
            "services.embedding.EmbeddingService.generate_embeddings_batch", batch_mock
        )
        matcher = FacetT2Matcher(model_id=model_id, t2_c_lo=0.25, t2_c_hi=0.55)
        count = await warm_facet_vectors(["已缓存值", "新值"], matcher)
        assert count == 2
        batch_mock.assert_awaited_once_with(["新值"])
