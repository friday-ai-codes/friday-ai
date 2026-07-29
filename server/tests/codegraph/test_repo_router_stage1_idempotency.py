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
