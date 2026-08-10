"""RepoRouterV2 Stage 1 幂等三件套行为测试（ROUTE-09，Phase 105-05）。

success criterion 3 的「Stage 1 可用情形下重复路由完全相同」由系统层保证，
不依赖模型层。本文件锁定：

- 双跑幂等（缓存路径）：同 query 连续两次 route() → 第二次 LLM 调用数为 0
  （输入哈希缓存命中），两次结果逐字段相等；
- 禁缓存纯函数同结果：cache 为 no-op 时 fake model 固定响应 → 两次结果仍
  逐字段相等（确定性不靠缓存——Pitfall 7 假绿防护，须两条路径分别断言）；
- 缓存 key 敏感性：stage0_input / index_version 任一变化 → key 不同
  （重索引后旧缓存自然失效）；
- LLM 输出含数值 score 字段 → 被过滤，候选分数仍为 Stage 0 归一化分；
- 缓存后端异常 → 路由正常完成（缓存 best-effort，绝不反噬路由）。

Stage 0 用 monkeypatch ``_stage0_node_search`` 固定输入；Stage 1 走 conftest
同款 seam（patch ``agents.llm_factory.build_chat_model``，函数内 lazy import）。
conftest ``_clear_throttle_cache`` autouse 每测试 cache.clear()——测试隔离免费。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from codegraph.services.repo_router_v2 import RepoRouterV2

# ---------------------------------------------------------------------------
# 构造输入与注入 seam（沿用 test_repo_router_v2_degraded 风格）
# ---------------------------------------------------------------------------


def _hit(
    node_id: str,
    rid: str,
    score: float,
    *,
    node_path: str = "root/能力",
    summary: str = "能力概述",
    built_at: str = "2026-07-29T00:00:00Z",
) -> dict[str, Any]:
    return {
        "id": node_id,
        "score": score,
        "payload": {
            "node_id": node_id,
            "repository_id": rid,
            "repo_name": rid,
            "node_path": node_path,
            "summary": summary,
            "built_at": built_at,
        },
    }


def _hits() -> list[dict[str, Any]]:
    """repo-a 高 margin 碾压 repo-b（首位确定性 high）。"""
    hits = [_hit(f"a{i}", "repo-a", 0.032 - i * 0.002) for i in range(6)]
    hits.append(_hit("b0", "repo-b", 0.010))
    return hits


def _install_stage0(monkeypatch: pytest.MonkeyPatch, hits: list[dict[str, Any]]) -> None:
    async def _fake_search(query: str, repository_ids: list[str] | None) -> list[dict[str, Any]]:
        return hits

    monkeypatch.setattr(RepoRouterV2, "_stage0_node_search", _fake_search)


def _install_stage1_model(monkeypatch: pytest.MonkeyPatch, model: Any) -> None:
    async def _fake_cc_rt() -> dict[str, str]:
        return {"haiku_model": "fake-haiku"}

    monkeypatch.setattr(
        "services.provider_config.aget_claude_code_runtime_config", _fake_cc_rt
    )
    monkeypatch.setattr("agents.llm_factory.build_chat_model", lambda *a, **kw: model)


class _CountingModel:
    """ainvoke 返回固定文本并计数——「第二次调用 LLM 次数 == 0」的显式证据。"""

    def __init__(self, text: str) -> None:
        self._text = text
        self.calls = 0

    async def ainvoke(self, messages: Any) -> Any:
        self.calls += 1
        return SimpleNamespace(content=self._text)


def _llm_output(*, extra_fields: dict[str, Any] | None = None) -> str:
    item: dict[str, Any] = {
        "repo_id": "repo-a",
        "sub_project": "",
        "confidence": "high",
        "reasoning": "命中能力节点 root/能力",
        "matched_node_paths": ["root/能力"],
    }
    if extra_fields:
        item.update(extra_fields)
    return json.dumps([item], ensure_ascii=False)


def _result_fields(result: Any) -> dict[str, Any]:
    """结果的可比字段集（逐字段相等断言用）。"""
    return {
        "candidates": [c.to_dict() for c in result.candidates],
        "auto_selected": result.auto_selected,
        "degraded": result.degraded,
        "router_version": result.router_version,
    }


class _NoopCache:
    """禁缓存：get 恒 None / set 吞掉——验证确定性不靠缓存（Pitfall 7）。"""

    def get(self, key: str, default: Any = None) -> Any:
        return None

    def set(self, key: str, value: Any, timeout: Any = None) -> None:
        return None


class _RaisingCache:
    """缓存后端异常注入：get/set 全抛——best-effort 防线验证。"""

    def get(self, key: str, default: Any = None) -> Any:
        raise RuntimeError("cache backend down")

    def set(self, key: str, value: Any, timeout: Any = None) -> None:
        raise RuntimeError("cache backend down")


# ---------------------------------------------------------------------------
# 双跑幂等（缓存路径）：第二次零 LLM 调用 + 结果逐字段相等
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_double_run_cache_hit_zero_llm_calls_identical_results(
    monkeypatch, mock_aresolve_ok
) -> None:
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _hits())
    model = _CountingModel(_llm_output())
    _install_stage1_model(monkeypatch, model)

    first = await RepoRouterV2.route("高三提分专项需求")
    assert model.calls == 1
    assert first.snapshot["stage1"]["cache_hit"] is False

    second = await RepoRouterV2.route("高三提分专项需求")
    # 第二次调用 LLM 次数 == 0（缓存命中，计数器不增长）
    assert model.calls == 1
    assert second.snapshot["stage1"]["cache_hit"] is True

    assert _result_fields(first) == _result_fields(second)
    assert first.router_version == "v2"
    # 版本绑定四元组齐备（weight_set/index/prompt_hash/model_id）
    versions = second.snapshot["versions"]
    assert versions["weight_set_version"]
    assert versions["index_version"]
    assert versions["prompt_hash"] == first.snapshot["versions"]["prompt_hash"]
    assert versions["model_id"] == "fake-haiku"


# ---------------------------------------------------------------------------
# 禁缓存纯函数同结果（确定性不靠缓存——假绿防护）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_cache_pure_function_identical_results(
    monkeypatch, mock_aresolve_ok
) -> None:
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _hits())
    model = _CountingModel(_llm_output())
    _install_stage1_model(monkeypatch, model)
    monkeypatch.setattr("codegraph.services.repo_router_v2.cache", _NoopCache())

    first = await RepoRouterV2.route("高三提分专项需求")
    second = await RepoRouterV2.route("高三提分专项需求")

    # 禁缓存：两次都真调 LLM（固定响应），结果仍逐字段相等
    assert model.calls == 2
    assert first.snapshot["stage1"]["cache_hit"] is False
    assert second.snapshot["stage1"]["cache_hit"] is False
    assert _result_fields(first) == _result_fields(second)


# ---------------------------------------------------------------------------
# 缓存 key 敏感性（直接断言 _stage1_cache_key 输出）
# ---------------------------------------------------------------------------


def test_cache_key_sensitive_to_stage0_input() -> None:
    decode = {"temperature": 0.0, "top_p": 1.0, "seed": 42}
    input_a = {"query": "需求 A", "candidates": [{"repo_id": "repo-a", "hits": []}]}
    input_b = {"query": "需求 B", "candidates": [{"repo_id": "repo-a", "hits": []}]}

    k_a = RepoRouterV2._stage1_cache_key("m1", input_a, decode, "iv-1")
    k_b = RepoRouterV2._stage1_cache_key("m1", input_b, decode, "iv-1")

    assert k_a.startswith("repo_router_v2:stage1:")
    assert k_a != k_b
    # 同输入 → 同 key（key 本身确定性）
    assert k_a == RepoRouterV2._stage1_cache_key("m1", input_a, decode, "iv-1")


def test_cache_key_sensitive_to_output_cap() -> None:
    """prompt 动态插值「最多输出 max(top_k,3) 项」并入 key 材料（MJ-02）。

    top_k=3 与 top_k=5 渲染出不同 prompt——是不同 LLM 输入，key 必须不同，
    否则先缓存的 ≤3 项排列会冒充 top_k=5 请求的结果（条数错误 + prompt_hash
    审计断链）。
    """
    decode = {"temperature": 0.0, "top_p": 1.0, "seed": 42}
    base = {"query": "需求", "candidates": [{"repo_id": "repo-a", "hits": []}]}
    input_cap3 = {**base, "output_cap": 3}
    input_cap5 = {**base, "output_cap": 5}

    k3 = RepoRouterV2._stage1_cache_key("m1", input_cap3, decode, "iv-1")
    k5 = RepoRouterV2._stage1_cache_key("m1", input_cap5, decode, "iv-1")
    assert k3 != k5


@pytest.mark.asyncio
async def test_cache_not_shared_across_top_k(monkeypatch, mock_aresolve_ok) -> None:
    """同 query 不同 top_k 不得命中同一缓存（端到端行为守护，MJ-02）。"""
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _hits())
    model = _CountingModel(_llm_output())
    _install_stage1_model(monkeypatch, model)

    first = await RepoRouterV2.route("高三提分专项需求", top_k=3)
    assert model.calls == 1
    assert first.snapshot["stage1"]["cache_hit"] is False

    second = await RepoRouterV2.route("高三提分专项需求", top_k=5)
    # output_cap 3 → 5：不同 prompt = 不同输入，必须真调 LLM 而非命中旧缓存
    assert model.calls == 2
    assert second.snapshot["stage1"]["cache_hit"] is False


def test_cache_key_sensitive_to_index_version() -> None:
    """重索引（built_at 变化 → index_version 变化）→ key 不同，旧缓存自然失效。"""
    decode = {"temperature": 0.0, "top_p": 1.0, "seed": 42}
    stage0_input = {"query": "需求", "candidates": [{"repo_id": "repo-a", "hits": []}]}
    iv_old = RepoRouterV2._index_version({"repo-a": "2026-07-29T00:00:00Z"})
    iv_new = RepoRouterV2._index_version({"repo-a": "2026-07-30T00:00:00Z"})

    assert iv_old != iv_new
    k_old = RepoRouterV2._stage1_cache_key("m1", stage0_input, decode, iv_old)
    k_new = RepoRouterV2._stage1_cache_key("m1", stage0_input, decode, iv_new)
    assert k_old != k_new


# ---------------------------------------------------------------------------
# index_version 单一口径：snapshot.versions 复用 Stage 1 缓存 key 的值
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_index_version_matches_stage1_cache_scope(
    monkeypatch, mock_aresolve_ok
) -> None:
    """snapshot.versions.index_version 与参与 Stage 1 缓存 key 的值恒等（MN-02）。

    fixture 里 Stage 1 喂入 repo-a + repo-b 两仓，但 LLM 只返回 repo-a——
    最终候选仓集合是 Stage 1 候选仓集合的真子集，两口径的哈希必然不同：
    versions 必须记录缓存 key 用的那个（Stage 1 口径），否则回放门禁/缓存
    审计交叉比对时对不上。
    """
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _hits())
    model = _CountingModel(_llm_output())
    _install_stage1_model(monkeypatch, model)

    result = await RepoRouterV2.route("高三提分专项需求")

    built_at = "2026-07-29T00:00:00Z"
    stage1_scope = RepoRouterV2._index_version(
        {"repo-a": built_at, "repo-b": built_at}
    )
    final_scope = RepoRouterV2._index_version({"repo-a": built_at})
    assert stage1_scope != final_scope  # 两口径确实可分（测试前提自证）
    assert result.snapshot["versions"]["index_version"] == stage1_scope
    assert result.snapshot["stage1"]["index_version"] == stage1_scope


# ---------------------------------------------------------------------------
# LLM 输出含数值 score → 过滤（候选分数仍为 Stage 0 归一化分）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_numeric_score_field_filtered(monkeypatch, mock_aresolve_ok) -> None:
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _hits())

    # 基线：Stage 0 归一化分（use_llm=False 路径）
    baseline = await RepoRouterV2.route("高三提分专项需求", use_llm=False)
    stage0_score = baseline.candidates[0].score

    model = _CountingModel(_llm_output(extra_fields={"score": 0.987654}))
    _install_stage1_model(monkeypatch, model)

    result = await RepoRouterV2.route("高三提分专项需求")

    assert result.router_version == "v2"
    top = result.candidates[0]
    assert top.repo_id == "repo-a"
    # LLM 的数值 score 不采信：候选分数仍为 Stage 0 归一化分
    assert top.score == pytest.approx(stage0_score)
    assert top.score != pytest.approx(0.987654)
    # 快照候选里也不带 LLM 分数（to_dict 的 score 即 Stage 0 分）
    assert result.snapshot["candidates"][0]["score"] == pytest.approx(
        round(stage0_score, 4)
    )


# ---------------------------------------------------------------------------
# LLM 输出重复 repo_id → 去重（首见保留；防缓存把重复固化 24h）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_duplicate_repo_id_deduplicated(monkeypatch, mock_aresolve_ok) -> None:
    """LLM 输出同仓两次 → 结果只保留首见项，重复项丢弃（MN-01）。"""
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _hits())
    dup_output = json.dumps(
        [
            {
                "repo_id": "repo-a",
                "sub_project": "",
                "confidence": "high",
                "reasoning": "首见",
                "matched_node_paths": ["root/能力"],
            },
            {
                "repo_id": "repo-a",
                "sub_project": "",
                "confidence": "low",
                "reasoning": "重复项",
                "matched_node_paths": [],
            },
            {
                "repo_id": "repo-b",
                "sub_project": "",
                "confidence": "medium",
                "reasoning": "另一仓",
                "matched_node_paths": [],
            },
        ],
        ensure_ascii=False,
    )
    model = _CountingModel(dup_output)
    _install_stage1_model(monkeypatch, model)

    result = await RepoRouterV2.route("高三提分专项需求")

    assert result.router_version == "v2"
    ids = [c.repo_id for c in result.candidates]
    assert ids == ["repo-a", "repo-b"]
    # 首见项字段保留（重复项不覆盖也不追加）
    assert result.candidates[0].reasoning == "首见"
    # 快照候选同样无重复（前端 v-for :key 依赖）
    snap_ids = [c["repo_id"] for c in result.snapshot["candidates"]]
    assert len(snap_ids) == len(set(snap_ids))


# ---------------------------------------------------------------------------
# 缓存后端异常 → best-effort 不反噬路由
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_backend_exception_does_not_break_route(
    monkeypatch, mock_aresolve_ok
) -> None:
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _hits())
    model = _CountingModel(_llm_output())
    _install_stage1_model(monkeypatch, model)
    monkeypatch.setattr("codegraph.services.repo_router_v2.cache", _RaisingCache())

    result = await RepoRouterV2.route("高三提分专项需求")

    # 缓存 get/set 全抛异常，路由仍正常完成（直调 LLM 一次）
    assert model.calls == 1
    assert result.router_version == "v2"
    assert result.candidates[0].repo_id == "repo-a"
    assert result.auto_selected is True


# ---------------------------------------------------------------------------
# 已知拒收 decode 参数的模型：Stage 1 首次构建即不带 temperature/top_p/seed
# （省掉「先 400 → 丢参重建 → 再调」的废调用），不在清单的模型仍走被动重试。
# ---------------------------------------------------------------------------


def test_model_rejects_decode_params_known_model() -> None:
    from django.test import override_settings

    from codegraph.services.repo_router_v2 import _model_rejects_decode_params

    with override_settings(
        REPO_ROUTER_STAGE1_DECODE_PARAM_REJECT_MODELS=["claude-opus", "claude-sonnet"]
    ):
        assert _model_rejects_decode_params("claude-opus-4-8") is True
        assert _model_rejects_decode_params("Claude-Sonnet-5") is True  # 大小写不敏感
        assert _model_rejects_decode_params("mimo-v2.5-pro") is False
        assert _model_rejects_decode_params("") is False


def test_model_rejects_decode_params_empty_or_missing_config() -> None:
    from django.test import override_settings

    from codegraph.services.repo_router_v2 import _model_rejects_decode_params

    with override_settings(REPO_ROUTER_STAGE1_DECODE_PARAM_REJECT_MODELS=[]):
        assert _model_rejects_decode_params("claude-opus-4-8") is False
    with override_settings(REPO_ROUTER_STAGE1_DECODE_PARAM_REJECT_MODELS=None):
        assert _model_rejects_decode_params("claude-opus-4-8") is False
