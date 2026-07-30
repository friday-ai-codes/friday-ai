"""RepoRouterV2 Stage 1 失联降级行为测试（RELY-04，Phase 105-03）。

生产事故链（会话 ccd817d9）：Stage 1 失联 → confidence 恒 low → auto_selected
恒 false → 编排卡死。本文件锁定修复后的行为契约：

- 三种失联情形（网关 400 / 连接错误 / 超时）+ 两条静默 None 路径
  （provider_missing / unparsable_llm_output）下 route() 仍产出按分数 margin
  确定性推导的 high/medium/low 分级，且 degraded=True；
- margin 达标（首位确定性 high）→ auto_selected=True（降级路径也能自动推进）；
- 低分/小 margin 输入 → medium/low、auto_selected=False（不误推进）；
- LLM confidence 只降不升：high→medium 降级生效，low→high 升级被拒；
- degraded=False 仅在 v2（Stage 1 成功）路径。

每条用例断言四元组：router_version / degraded / 首位 confidence / auto_selected。

Stage 0 不打真 Qdrant：monkeypatch ``RepoRouterV2._stage0_node_search`` 返回
构造 node_hits。Stage 1 失败注入走 conftest 同款 seam——patch 目标为
``agents.llm_factory.build_chat_model``（函数内 lazy import，RESEARCH Pattern 2）。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from codegraph.services.repo_router_v2 import RepoRouterV2

# ---------------------------------------------------------------------------
# 构造输入：node_hits fixture（高 margin / 低 margin 两组）
# ---------------------------------------------------------------------------


def _hit(
    node_id: str,
    rid: str,
    score: float,
    *,
    facets: dict[str, str] | None = None,
    node_path: str = "root/能力",
    built_at: str = "2026-07-29T00:00:00Z",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "node_id": node_id,
        "repository_id": rid,
        "repo_name": rid,
        "node_path": node_path,
        "built_at": built_at,
    }
    if facets is not None:
        payload["facets"] = json.dumps(facets, ensure_ascii=False)
    return {"id": node_id, "score": score, "payload": payload}


def _high_margin_hits() -> list[dict[str, Any]]:
    """repo-a 碾压 repo-b：text=1.0 + breadth=1.0 + 活跃开发 → score≈0.99；
    repo-b 单命中低分 → score≈0.24（<θ_med）。margin 远超 θ_margin → 首位 high。"""
    hits = [
        _hit(f"a{i}", "repo-a", 0.032 - i * 0.002, facets={"活跃度": "活跃开发"})
        for i in range(6)
    ]
    hits.append(_hit("b0", "repo-b", 0.010))
    return hits


def _low_margin_hits() -> list[dict[str, Any]]:
    """两仓分数接近（margin < θ_margin=0.08）→ 首位只能 medium，不误推进。"""
    return [_hit("a0", "repo-a", 0.020), _hit("b0", "repo-b", 0.019)]


# ---------------------------------------------------------------------------
# Stage 0 / Stage 1 注入 seam
# ---------------------------------------------------------------------------


def _install_stage0(monkeypatch: pytest.MonkeyPatch, hits: list[dict[str, Any]]) -> None:
    async def _fake_search(query: str, repository_ids: list[str] | None) -> list[dict[str, Any]]:
        return hits

    monkeypatch.setattr(RepoRouterV2, "_stage0_node_search", _fake_search)


@pytest.fixture(autouse=True)
def _fast_stage1_backoff(settings) -> None:
    """把 Stage 1 重试退避基数压到毫秒级（107-05 Task 1 引入重试后的测试提速）。

    本文件多数用例注入的是可重试类异常（超时 / 连接错误），按默认 2.0s 退避真睡
    会给整个文件平白加十几秒。退避时长本身只在专门的上界用例里断言，那条用例在
    本 fixture 之后自行覆盖该值（fixture 先于用例体执行）。
    """
    settings.REPO_ROUTER_STAGE1_RETRY_BACKOFF_SECONDS = 0.001


def _cand(rid: str, score: float) -> dict[str, Any]:
    """构造一个 Stage 0 候选（分数钉死）——凸组合与最终顺序断言需要精确分差。"""
    return {
        "repo_id": rid,
        "repo_name": rid,
        "score": score,
        "breakdown": {"text_relevance": score},
        "facets": {},
        "hits": [_hit(f"{rid}-n0", rid, score)],
        "criticality": None,
    }


def _window(n: int) -> list[dict[str, Any]]:
    """Stage 0 窗口：``r1..rn`` 按分数降序（LLM 收到的候选顺序即此顺序）。"""
    return [_cand(f"r{i}", 0.90 - (i - 1) * 0.05) for i in range(1, n + 1)]


def _install_stage0_candidates(
    monkeypatch: pytest.MonkeyPatch, candidates: list[dict[str, Any]]
) -> None:
    """把 Stage 0 打分产物钉死为给定候选（绕开六信号打分，分数精确可控）。"""
    monkeypatch.setattr(
        RepoRouterV2,
        "_stage0_candidates",
        classmethod(lambda cls, node_hits, **kwargs: [dict(c) for c in candidates]),
    )


def _install_stage1_model(monkeypatch: pytest.MonkeyPatch, model: Any) -> None:
    """让 Stage 1 走到 model.ainvoke：patch lazy import 的 build_chat_model seam
    与 aget_claude_code_runtime_config（模型名解析不触 DB）。"""

    async def _fake_cc_rt() -> dict[str, str]:
        return {"haiku_model": "fake-haiku"}

    monkeypatch.setattr(
        "services.provider_config.aget_claude_code_runtime_config", _fake_cc_rt
    )
    monkeypatch.setattr("agents.llm_factory.build_chat_model", lambda *a, **kw: model)


def _install_stage1_model_capturing(monkeypatch: pytest.MonkeyPatch, model: Any) -> dict[str, Any]:
    """同 ``_install_stage1_model``，另把 build_chat_model 的构造 kwargs 记下来。"""
    captured: dict[str, Any] = {}

    async def _fake_cc_rt() -> dict[str, str]:
        return {"haiku_model": "fake-haiku"}

    def _build(*_args: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return model

    monkeypatch.setattr("services.provider_config.aget_claude_code_runtime_config", _fake_cc_rt)
    monkeypatch.setattr("agents.llm_factory.build_chat_model", _build)
    return captured


def _spy_wait_for(monkeypatch: pytest.MonkeyPatch) -> list[float | None]:
    """记录传给 ``asyncio.wait_for`` 的 timeout 实参（per-attempt 超时上界断言）。"""
    recorded: list[float | None] = []
    real_wait_for = asyncio.wait_for

    async def _spy(awaitable: Any, timeout: float | None = None) -> Any:
        recorded.append(timeout)
        return await real_wait_for(awaitable, timeout=timeout)

    monkeypatch.setattr(asyncio, "wait_for", _spy)
    return recorded


def _spy_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """记录退避睡眠实参并把真实睡眠压成 0（退避上界断言，用例本身秒回）。"""
    recorded: list[float] = []
    real_sleep = asyncio.sleep

    async def _spy(delay: float, *_args: Any, **_kwargs: Any) -> Any:
        recorded.append(delay)
        return await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _spy)
    return recorded


def _llm_order_json(*repo_ids: str, confidence: str = "medium") -> str:
    """构造 Stage 1 排列输出（数组顺序即 LLM 的排序结论）。"""
    return json.dumps(
        [
            {
                "repo_id": rid,
                "sub_project": "",
                "confidence": confidence,
                "reasoning": "",
                "matched_node_paths": [],
            }
            for rid in repo_ids
        ],
        ensure_ascii=False,
    )


class _RaisingModel:
    """ainvoke 抛指定异常（网关 400 / 连接错误 / TimeoutError 注入）。"""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def ainvoke(self, messages: Any) -> Any:
        raise self._exc


class _SlowModel:
    """ainvoke 睡过 monkeypatch 后的小超时值 → 真走 asyncio.wait_for 超时路径。"""

    async def ainvoke(self, messages: Any) -> Any:
        await asyncio.sleep(5.0)


class _TextModel:
    """ainvoke 返回固定文本（成功路径 / 不可解析输出注入）。"""

    def __init__(self, text: str) -> None:
        self._text = text

    async def ainvoke(self, messages: Any) -> Any:
        return SimpleNamespace(content=self._text)


class _FlakyModel:
    """前 ``fail_times`` 次 ainvoke 抛异常、其后返回固定文本；记录调用次数。"""

    def __init__(self, exc: Exception, text: str = "", *, fail_times: int = 1) -> None:
        self._exc = exc
        self._text = text
        self._fail_times = fail_times
        self.calls = 0

    async def ainvoke(self, messages: Any) -> Any:
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._exc
        return SimpleNamespace(content=self._text)


class _CountingSlowModel:
    """ainvoke 睡过 per-attempt 超时值并记录调用次数（预算耗尽断言用）。"""

    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, messages: Any) -> Any:
        self.calls += 1
        await asyncio.sleep(5.0)


def _assert_degraded_high(result: Any) -> None:
    """高 margin 输入 + Stage 1 失联的期望四元组。"""
    assert result.router_version == "v2_stage0_only"
    assert result.degraded is True
    assert result.candidates[0].confidence == "high"
    assert result.auto_selected is True


# ---------------------------------------------------------------------------
# 三种失联情形（CONTEXT：网关 400 / 连接错误 / 超时）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gateway_400_degrades_to_deterministic_high(
    monkeypatch, mock_aresolve_ok
) -> None:
    """网关 400（provider SDK 风格异常）→ 降级仍按 margin 出 high + 自动推进。"""
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _high_margin_hits())
    _install_stage1_model(
        monkeypatch,
        _RaisingModel(RuntimeError("Error code: 400 - {'error': {'message': 'bad request'}}")),
    )

    result = await RepoRouterV2.route("高三提分专项需求")

    _assert_degraded_high(result)


@pytest.mark.asyncio
async def test_connection_error_degrades_to_deterministic_high(
    monkeypatch, mock_aresolve_ok
) -> None:
    """连接错误（ConnectionError）→ 同样确定性分级 + degraded + 自动推进。"""
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _high_margin_hits())
    _install_stage1_model(monkeypatch, _RaisingModel(ConnectionError("connect failed")))

    result = await RepoRouterV2.route("高三提分专项需求")

    _assert_degraded_high(result)


@pytest.mark.asyncio
async def test_timeout_degrades_to_deterministic_high(
    monkeypatch, mock_aresolve_ok, settings
) -> None:
    """超时（真走 asyncio.wait_for，ainvoke 睡过小超时值）→ 降级 + 自动推进。"""
    mock_aresolve_ok()
    settings.REPO_ROUTER_STAGE1_TIMEOUT_SECONDS = 0.05
    _install_stage0(monkeypatch, _high_margin_hits())
    _install_stage1_model(monkeypatch, _SlowModel())

    result = await RepoRouterV2.route("高三提分专项需求")

    _assert_degraded_high(result)


# ---------------------------------------------------------------------------
# 静默 None 路径（provider_missing / unparsable_llm_output）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_missing_degrades_to_deterministic_high(
    monkeypatch, mock_aresolve_missing
) -> None:
    """凭证缺失（aresolve 返回 ProviderMissingError）→ 静默 None 路径同样分级。"""
    mock_aresolve_missing()
    _install_stage0(monkeypatch, _high_margin_hits())

    result = await RepoRouterV2.route("高三提分专项需求")

    _assert_degraded_high(result)
    # 快照材料随结果携带（ROUTE-09 数据底座）
    assert result.snapshot["stage0"]["query"] == "高三提分专项需求"
    assert result.snapshot["versions"]["weight_set_version"]


@pytest.mark.asyncio
async def test_unparsable_llm_output_degrades_to_deterministic_high(
    monkeypatch, mock_aresolve_ok
) -> None:
    """LLM 输出非 JSON → 静默 None 路径同样产出确定性分级 + degraded=True。"""
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _high_margin_hits())
    _install_stage1_model(monkeypatch, _TextModel("抱歉，我无法输出 JSON。"))

    result = await RepoRouterV2.route("高三提分专项需求")

    _assert_degraded_high(result)


# ---------------------------------------------------------------------------
# 低分 / 小 margin：不误推进
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_low_margin_degrades_to_medium_no_auto_select(
    monkeypatch, mock_aresolve_ok
) -> None:
    """小 margin 输入 + 失联 → 首位 medium（margin 不达标）、auto_selected=False。"""
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _low_margin_hits())
    _install_stage1_model(monkeypatch, _RaisingModel(ConnectionError("connect failed")))

    result = await RepoRouterV2.route("模糊需求")

    assert result.router_version == "v2_stage0_only"
    assert result.degraded is True
    assert result.candidates[0].confidence == "medium"
    assert result.auto_selected is False


@pytest.mark.asyncio
async def test_rank2_below_theta_med_graded_low(monkeypatch, mock_aresolve_ok) -> None:
    """rank>1 且 score < θ_med → low（high 仅 rank-1 可得的分级规则）。"""
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _high_margin_hits())
    _install_stage1_model(monkeypatch, _RaisingModel(ConnectionError("connect failed")))

    result = await RepoRouterV2.route("高三提分专项需求")

    assert result.degraded is True
    assert [c.repo_id for c in result.candidates[:2]] == ["repo-a", "repo-b"]
    assert result.candidates[1].confidence == "low"


# ---------------------------------------------------------------------------
# use_llm=False：与失联路径语义一致（auto_selected 由确定性 confidence 驱动）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_use_llm_false_semantics_match_degraded_path(monkeypatch) -> None:
    """use_llm=False 也产出确定性分级并可 auto_selected（两条路径语义一致）。"""
    _install_stage0(monkeypatch, _high_margin_hits())

    result = await RepoRouterV2.route("高三提分专项需求", use_llm=False)

    _assert_degraded_high(result)
    # 候选携带 breakdown 且 Σ贡献 == score（ROUTE-07）
    top = result.candidates[0]
    assert top.breakdown
    assert abs(sum(top.breakdown.values()) - top.score) < 1e-9


# ---------------------------------------------------------------------------
# 只降不升（Stage 1 成功路径）+ degraded=False 仅在 v2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_downgrade_high_to_medium_applies(monkeypatch, mock_aresolve_ok) -> None:
    """LLM 对首位输出 medium（确定性为 high）→ 最终 medium、auto_selected=False、
    degraded=False（v2 路径是 degraded=False 的唯一来源）。"""
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _high_margin_hits())
    llm_output = json.dumps(
        [
            {
                "repo_id": "repo-a",
                "sub_project": "",
                "confidence": "medium",
                "reasoning": "边界情形建议人工确认",
                "matched_node_paths": [],
            }
        ],
        ensure_ascii=False,
    )
    _install_stage1_model(monkeypatch, _TextModel(llm_output))

    result = await RepoRouterV2.route("高三提分专项需求")

    assert result.router_version == "v2"
    assert result.degraded is False
    assert result.candidates[0].confidence == "medium"
    assert result.auto_selected is False


@pytest.mark.asyncio
async def test_llm_upgrade_low_to_high_rejected(monkeypatch, mock_aresolve_ok) -> None:
    """LLM 对确定性 low 的候选输出 high → 升级被拒（最终 low，不触发 auto_selected）——
    LLM 无法把任何候选推成 auto_selected（threat T-105-07）。"""
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _high_margin_hits())
    # repo-b 在 stage0 中 rank=2 且 score < θ_med → 确定性 low；LLM 却把它排首位给 high
    llm_output = json.dumps(
        [
            {
                "repo_id": "repo-b",
                "sub_project": "",
                "confidence": "high",
                "reasoning": "（LLM 幻觉式断言）",
                "matched_node_paths": [],
            }
        ],
        ensure_ascii=False,
    )
    _install_stage1_model(monkeypatch, _TextModel(llm_output))

    result = await RepoRouterV2.route("高三提分专项需求")

    assert result.router_version == "v2"
    assert result.degraded is False
    assert result.candidates[0].repo_id == "repo-b"
    assert result.candidates[0].confidence == "low"
    assert result.auto_selected is False


# ---------------------------------------------------------------------------
# 零候选短路：node_hits 非空但全部缺 repository_id → 不进 Stage 1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zero_candidates_short_circuits_before_stage1(
    monkeypatch, mock_aresolve_ok
) -> None:
    """node_hits 非空但打分核心过滤后零候选 → 提前短路，不发空 prompt 的
    LLM 调用（IN-04a）。"""
    mock_aresolve_ok()
    bad_hits = [
        {
            "id": "x0",
            "score": 0.02,
            # payload 缺 repository_id → 打分核心过滤 → stage0_candidates 为空
            "payload": {"node_id": "x0", "repo_name": "ghost", "node_path": "root/能力"},
        }
    ]
    _install_stage0(monkeypatch, bad_hits)
    build_calls: list[int] = []
    monkeypatch.setattr(
        "agents.llm_factory.build_chat_model",
        lambda *a, **kw: build_calls.append(1),
    )

    result = await RepoRouterV2.route("需求")

    assert result.router_version == "v2_stage0_only"
    assert result.degraded is True
    assert result.candidates == []
    assert result.auto_selected is False
    assert result.snapshot["stage1"]["skipped_reason"] == "no_stage0_candidates"
    # Stage 1 从未构造模型——零 LLM 调用
    assert build_calls == []


# ---------------------------------------------------------------------------
# 降级原因闭集 + 上游异常文本脱敏（107-03 Task 3，RELY-03 / T-107-02）
# ---------------------------------------------------------------------------


class _APIConnectionError(Exception):
    """类型名含 ``Connect`` 的上游异常替身（分类只吃类型名，不吃消息）。"""


def _install_no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """凭证可解析但拿不到任何模型名 → Stage 1 走 no_model_configured 分支。"""

    async def _fake_cc_rt() -> dict[str, str]:
        return {}

    monkeypatch.setattr("services.provider_config.aget_claude_code_runtime_config", _fake_cc_rt)


@pytest.mark.asyncio
async def test_degrade_reason_timeout(monkeypatch, mock_aresolve_ok, settings) -> None:
    """超时（真走 asyncio.wait_for）→ degrade_reason == "timeout"。"""
    mock_aresolve_ok()
    settings.REPO_ROUTER_STAGE1_TIMEOUT_SECONDS = 0.05
    _install_stage0(monkeypatch, _high_margin_hits())
    _install_stage1_model(monkeypatch, _SlowModel())

    result = await RepoRouterV2.route("高三提分专项需求")

    assert result.router_version == "v2_stage0_only"
    assert result.degraded is True
    assert result.degrade_reason == "timeout"


@pytest.mark.asyncio
async def test_degrade_reason_upstream_error(monkeypatch, mock_aresolve_ok) -> None:
    """上游连接类异常（类型名含 Connect）→ degrade_reason == "upstream_error"。"""
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _high_margin_hits())
    _install_stage1_model(monkeypatch, _RaisingModel(_APIConnectionError("upstream down")))

    result = await RepoRouterV2.route("高三提分专项需求")

    assert result.degrade_reason == "upstream_error"


@pytest.mark.asyncio
async def test_degrade_reason_provider_missing(monkeypatch, mock_aresolve_missing) -> None:
    """凭证未解析 → degrade_reason == "provider_missing"。"""
    mock_aresolve_missing()
    _install_stage0(monkeypatch, _high_margin_hits())

    result = await RepoRouterV2.route("高三提分专项需求")

    assert result.degrade_reason == "provider_missing"


@pytest.mark.asyncio
async def test_degrade_reason_no_model_maps_to_provider_missing(
    monkeypatch, mock_aresolve_ok
) -> None:
    """凭证可解析但无 model 名 → 同样归 "provider_missing"（用户视角同一处置）。"""
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _high_margin_hits())
    _install_no_model(monkeypatch)

    result = await RepoRouterV2.route("高三提分专项需求")

    assert result.snapshot["stage1"]["skipped_reason"] == "no_model_configured"
    assert result.degrade_reason == "provider_missing"


@pytest.mark.asyncio
async def test_degrade_reason_unparsable(monkeypatch, mock_aresolve_ok) -> None:
    """LLM 输出不可解析 → degrade_reason == "unparsable"。"""
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _high_margin_hits())
    _install_stage1_model(monkeypatch, _TextModel("抱歉，我无法输出 JSON。"))

    result = await RepoRouterV2.route("高三提分专项需求")

    assert result.degrade_reason == "unparsable"


@pytest.mark.asyncio
async def test_degrade_reason_no_valid_candidates_maps_to_unparsable(
    monkeypatch, mock_aresolve_ok
) -> None:
    """LLM 输出合法 JSON 但全是编造 repo_id → 同样归 "unparsable"。"""
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _high_margin_hits())
    _install_stage1_model(
        monkeypatch,
        _TextModel(json.dumps([{"repo_id": "ghost-repo", "confidence": "high"}])),
    )

    result = await RepoRouterV2.route("高三提分专项需求")

    assert result.snapshot["stage1"]["skipped_reason"] == "no_valid_candidates_in_llm_output"
    assert result.degrade_reason == "unparsable"


@pytest.mark.asyncio
async def test_degrade_reason_v1_fallback_is_no_node_index(monkeypatch) -> None:
    """节点索引无命中 → 回落 v1 且 degrade_reason == "no_node_index"。"""
    _install_stage0(monkeypatch, [])

    async def _fake_v1_route(query: str, top_k: int = 3) -> list[Any]:
        return []

    monkeypatch.setattr("codegraph.services.repo_router.RepoRouter.route", _fake_v1_route)

    result = await RepoRouterV2.route("高三提分专项需求")

    assert result.router_version == "v1_fallback"
    assert result.degraded is True
    assert result.degrade_reason == "no_node_index"


@pytest.mark.asyncio
async def test_degrade_reason_empty_for_non_user_visible_paths(monkeypatch) -> None:
    """use_llm=False 与 Stage 0 零候选：degraded 仍 True，但无用户可见降级原因行。"""
    _install_stage0(monkeypatch, _high_margin_hits())

    result = await RepoRouterV2.route("高三提分专项需求", use_llm=False)

    assert result.degraded is True
    assert result.degrade_reason == ""

    _install_stage0(
        monkeypatch,
        [{"id": "x0", "score": 0.02, "payload": {"node_id": "x0", "repo_name": "ghost"}}],
    )

    zero = await RepoRouterV2.route("需求", use_llm=False)

    assert zero.candidates == []
    assert zero.degrade_reason == ""


@pytest.mark.asyncio
async def test_degrade_reason_is_always_in_closed_set(monkeypatch, mock_aresolve_ok) -> None:
    """任意异常类型下 degrade_reason 恒 ∈ DEGRADE_REASONS | {""}（基数受控）。"""
    from codegraph.services.repo_router_ranking import DEGRADE_REASONS

    for exc in (
        TimeoutError("timed out"),
        _APIConnectionError("connect refused"),
        ConnectionError("connect failed"),
        RuntimeError("Error code: 400 - {'error': {'message': 'bad request'}}"),
        ValueError("weird"),
    ):
        mock_aresolve_ok()
        _install_stage0(monkeypatch, _high_margin_hits())
        _install_stage1_model(monkeypatch, _RaisingModel(exc))

        result = await RepoRouterV2.route("高三提分专项需求")

        assert result.degrade_reason in DEGRADE_REASONS | {""}


@pytest.mark.asyncio
async def test_redact_upstream_secret_from_snapshot_and_meta(
    monkeypatch, mock_aresolve_ok
) -> None:
    """上游异常消息含密钥 → 快照与降级留痕均无明文（T-107-02；截断不是脱敏）。"""
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _high_margin_hits())
    _install_stage1_model(
        monkeypatch,
        _RaisingModel(RuntimeError("401 invalid api key sk-ant-abcdefgh12345678 rejected")),
    )

    result = await RepoRouterV2.route("高三提分专项需求")

    dumped = json.dumps(result.snapshot, ensure_ascii=False)
    assert "sk-ant-" not in dumped
    assert "abcdefgh12345678" not in dumped
    stage1 = result.snapshot["stage1"]
    # 脱敏后的排障文本仍在（有可下钻线索，只是无明文密钥）
    assert "REDACTED" in stage1["error_redacted"]
    assert stage1["degrade_reason"] == result.degrade_reason


@pytest.mark.asyncio
async def test_redact_meta_load_failure_log_event(monkeypatch) -> None:
    """repo_meta 组装失败分支的异常文本同样经脱敏（全文件归零，非只改 Stage 1）。

    用 ``capture_logs`` 断言**事件字段本身**已脱敏：它绕过全局
    ``redact_credentials`` processor，因此证明的是源头脱敏而非兜底脱敏。
    """
    from structlog.testing import capture_logs

    _install_stage0(monkeypatch, _high_margin_hits())

    async def _boom(node_hits, query, query_dense, config):
        raise RuntimeError("meta pipeline exploded with sk-ant-abcdefgh12345678")

    monkeypatch.setattr(RepoRouterV2, "_load_repo_meta", _boom)

    with capture_logs() as events:
        result = await RepoRouterV2.route("高三提分专项需求", use_llm=False)

    assert result.candidates  # 回退 legacy 三信号，路由仍可用
    failed = [e for e in events if e.get("event") == "repo_router_meta_load_failed"]
    assert failed, "meta 组装失败必须留证"
    assert "sk-ant-" not in json.dumps(failed, ensure_ascii=False, default=str)
    assert "REDACTED" in failed[0]["error"]


@pytest.mark.asyncio
async def test_redact_stage1_failure_log_event(monkeypatch, mock_aresolve_ok) -> None:
    """Stage 1 失败日志的 ``error`` 字段在源头脱敏（截断不是脱敏）。"""
    from structlog.testing import capture_logs

    mock_aresolve_ok()
    _install_stage0(monkeypatch, _high_margin_hits())
    _install_stage1_model(
        monkeypatch,
        _RaisingModel(RuntimeError("401 invalid api key sk-ant-abcdefgh12345678 rejected")),
    )

    with capture_logs() as events:
        await RepoRouterV2.route("高三提分专项需求")

    failed = [e for e in events if e.get("event") == "repo_router_v2_stage1_failed"]
    assert failed
    assert "sk-ant-" not in json.dumps(failed, ensure_ascii=False, default=str)
    assert "REDACTED" in failed[0]["error"]


# ---------------------------------------------------------------------------
# Stage 1 有界调用：1 次重试 + 首调与重试共享总预算（107-05 Task 1，RELY-05）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stage1_retry_recovers_on_second_attempt(monkeypatch, mock_aresolve_ok) -> None:
    """首调超时、重试成功 → 正常 v2 结果，替身被调用 2 次，attempts == 2。"""
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _high_margin_hits())
    model = _FlakyModel(
        TimeoutError("first attempt timed out"), _llm_order_json("repo-a"), fail_times=1
    )
    _install_stage1_model(monkeypatch, model)

    result = await RepoRouterV2.route("高三提分专项需求")

    assert result.router_version == "v2"
    assert result.degraded is False
    assert model.calls == 2
    assert result.snapshot["stage1"]["attempts"] == 2


@pytest.mark.asyncio
async def test_stage1_retry_exhausted_degrades_after_two_attempts(
    monkeypatch, mock_aresolve_ok
) -> None:
    """两次都超时 → 降级继续（timeout），且重试次数硬上界为 1（共 2 次调用）。"""
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _high_margin_hits())
    model = _FlakyModel(TimeoutError("still timing out"), fail_times=2)
    _install_stage1_model(monkeypatch, model)

    result = await RepoRouterV2.route("高三提分专项需求")

    assert result.router_version == "v2_stage0_only"
    assert result.degraded is True
    assert result.degrade_reason == "timeout"
    assert model.calls == 2


# ---------------------------------------------------------------------------
# MJ-02：α 对 auto_selected 的影响必须**方向单调**且可观测
#
# `auto_selected` 读的是按 score_ranked 排序后的扁平列表首位，所以 α 确实会参与
# 「是否自动推进」的判定（凸组合的设计后果）。可接受的前提是方向单调安全：
# confidence == high 只可能出现在 Stage 0 位次 0 上，故 α 只能把 True 变 False
# （更多人工确认），绝不可能 False→True 让本不该自动推进的场景自动推进。
# 该单调性此前**无任何断言锁定**，被 α 抑制的场景也无从与「本来就不该自动推进」区分。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("alpha", [0.0, 0.35, 0.9, 1.0])
async def test_alpha_never_turns_auto_selected_on(
    monkeypatch, mock_aresolve_ok, settings, alpha: float
) -> None:
    """单调性护栏：任何 α 下 auto_selected 为 True ⟹ α=0 时也为 True（只抑制不误开）。

    输入固定为「LLM 把 Stage 0 第二名排到首位」这一最能翻转顺序的排列；LLM 一律给
    high（只降不升 → 确定性分级不被 LLM 改动，把变量隔离成只有 α）。α=0 时
    auto_selected 为 True（Stage 0 首位 high），α 增大只可能把它压成 False。
    """
    mock_aresolve_ok()
    settings.REPO_ROUTER_STAGE1_ALPHA = alpha
    _install_stage0(monkeypatch, _high_margin_hits())
    _install_stage1_model(
        monkeypatch, _TextModel(_llm_order_json("repo-b", "repo-a", confidence="high"))
    )

    result = await RepoRouterV2.route("高三提分专项需求")

    assert result.router_version == "v2"
    # 存在 high 候选是 α=0 基线为 True 的充要条件（high 只可能落在 Stage 0 首位）
    baseline_auto_selected = any(c.confidence == "high" for c in result.candidates)
    assert baseline_auto_selected is True
    if result.auto_selected:
        assert baseline_auto_selected, "α 把 auto_selected 由 False 翻成了 True（方向不单调）"


@pytest.mark.asyncio
async def test_alpha_suppression_is_observable(monkeypatch, mock_aresolve_ok, settings) -> None:
    """α 把 high 候选挤下首位 → auto_selected=False 且抑制标记为 True（代价可观测）。"""
    mock_aresolve_ok()
    settings.REPO_ROUTER_STAGE1_ALPHA = 0.9
    _install_stage0(monkeypatch, _high_margin_hits())
    _install_stage1_model(
        monkeypatch, _TextModel(_llm_order_json("repo-b", "repo-a", confidence="high"))
    )

    result = await RepoRouterV2.route("高三提分专项需求")

    assert result.candidates[0].repo_id == "repo-b"
    assert result.candidates[0].confidence != "high"
    assert result.auto_selected is False
    assert result.auto_selected_suppressed_by_alpha is True


@pytest.mark.asyncio
async def test_no_suppression_flag_when_alpha_keeps_high_on_top(
    monkeypatch, mock_aresolve_ok, settings
) -> None:
    """α 未改变首位 → 正常自动推进且抑制标记为 False（不误报抑制）。"""
    mock_aresolve_ok()
    settings.REPO_ROUTER_STAGE1_ALPHA = 0.35
    _install_stage0(monkeypatch, _high_margin_hits())
    _install_stage1_model(
        monkeypatch, _TextModel(_llm_order_json("repo-a", "repo-b", confidence="high"))
    )

    result = await RepoRouterV2.route("高三提分专项需求")

    assert result.candidates[0].repo_id == "repo-a"
    assert result.auto_selected is True
    assert result.auto_selected_suppressed_by_alpha is False


@pytest.mark.asyncio
async def test_suppression_flag_false_when_nothing_to_suppress(
    monkeypatch, mock_aresolve_ok, settings
) -> None:
    """无 high 候选（本来就不该自动推进）→ 抑制标记必须为 False，二者可区分。"""
    mock_aresolve_ok()
    settings.REPO_ROUTER_STAGE1_ALPHA = 0.9
    _install_stage0(monkeypatch, _low_margin_hits())
    _install_stage1_model(monkeypatch, _TextModel(_llm_order_json("repo-b", "repo-a")))

    result = await RepoRouterV2.route("模糊需求")

    assert all(c.confidence != "high" for c in result.candidates)
    assert result.auto_selected is False
    assert result.auto_selected_suppressed_by_alpha is False


# ---------------------------------------------------------------------------
# MJ-01：**真实 SDK 异常类**下的重试与降级原因
#
# 修复前分类只看 `type(exc).__name__` 的子串，而 `APIStatusError` 是 SDK 基类——
# 生产抛的 `RateLimitError` / `InternalServerError` 名字里都不含 "APIStatus"，于是
# 429/5xx 全落 `unknown`（既不重试、用户还只看到「未知原因」），`BadRequestError`
# 反因名字命中上游表而被重试一次（白烧一次上游调用，与 docstring 直接矛盾）。
# 用真实异常类（带真实 status_code）钉住修复后的行为。
# ---------------------------------------------------------------------------


def _openai_status_error(kind: str, status: int) -> Exception:
    """构造带真实 ``status_code`` 的 openai SDK 异常实例。"""
    import httpx
    import openai

    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    response = httpx.Response(status, request=request)
    return getattr(openai, kind)(f"upstream {status}", response=response, body=None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "status"),
    [
        ("RateLimitError", 429),
        ("InternalServerError", 500),
        ("InternalServerError", 503),
        # Anthropic 的 529 Overloaded 同样经 APIStatusError 子类抛出
        ("InternalServerError", 529),
    ],
)
async def test_stage1_retries_real_429_and_5xx(
    monkeypatch, mock_aresolve_ok, kind: str, status: int
) -> None:
    """429/5xx 真实 SDK 异常 → 重试一次并恢复（修复前这些一次都不重试）。"""
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _high_margin_hits())
    model = _FlakyModel(
        _openai_status_error(kind, status), _llm_order_json("repo-a"), fail_times=1
    )
    _install_stage1_model(monkeypatch, model)

    result = await RepoRouterV2.route("高三提分专项需求")

    assert model.calls == 2, f"{kind}({status}) 未被重试"
    assert result.router_version == "v2"
    assert result.degraded is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "status"),
    [
        ("RateLimitError", 429),
        ("InternalServerError", 500),
        ("InternalServerError", 529),
    ],
)
async def test_stage1_429_and_5xx_report_upstream_error_not_unknown(
    monkeypatch, mock_aresolve_ok, kind: str, status: int
) -> None:
    """两次都失败时降级原因是「网关错误」而非「未知原因」（用户看到的就是这行）。"""
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _high_margin_hits())
    model = _FlakyModel(_openai_status_error(kind, status), fail_times=2)
    _install_stage1_model(monkeypatch, model)

    result = await RepoRouterV2.route("高三提分专项需求")

    assert result.degraded is True
    assert result.degrade_reason == "upstream_error"
    assert result.degrade_reason != "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "status"),
    [
        ("BadRequestError", 400),
        ("AuthenticationError", 401),
        ("PermissionDeniedError", 403),
        ("NotFoundError", 404),
        ("UnprocessableEntityError", 422),
    ],
)
async def test_stage1_does_not_retry_deterministic_4xx(
    monkeypatch, mock_aresolve_ok, kind: str, status: int
) -> None:
    """4xx 确定性失败只调一次上游：重试一次结果一样，只会白烧预算与一行用量记录。"""
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _high_margin_hits())
    model = _FlakyModel(_openai_status_error(kind, status), fail_times=2)
    _install_stage1_model(monkeypatch, model)

    result = await RepoRouterV2.route("高三提分专项需求")

    assert model.calls == 1, f"{kind}({status}) 被重试了 —— 与不可重试判据矛盾"
    assert result.degraded is True
    assert result.degrade_reason == "upstream_error"


@pytest.mark.asyncio
async def test_stage1_timeout_status_codes_report_timeout(
    monkeypatch, mock_aresolve_ok
) -> None:
    """504 网关超时的降级原因是「上游超时」而非泛化的「网关错误」。"""
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _high_margin_hits())
    model = _FlakyModel(_openai_status_error("InternalServerError", 504), fail_times=2)
    _install_stage1_model(monkeypatch, model)

    result = await RepoRouterV2.route("高三提分专项需求")

    assert result.degrade_reason == "timeout"
    assert model.calls == 2


@pytest.mark.asyncio
async def test_stage1_budget_exhausted_skips_second_call(
    monkeypatch, mock_aresolve_ok, settings
) -> None:
    """总预算耗尽 → 不发第二次调用（1 次），并留下预算耗尽事件。"""
    from structlog.testing import capture_logs

    mock_aresolve_ok()
    settings.REPO_ROUTER_STAGE1_TOTAL_BUDGET_SECONDS = 0.01
    _install_stage0(monkeypatch, _high_margin_hits())
    model = _CountingSlowModel()
    _install_stage1_model(monkeypatch, model)

    with capture_logs() as events:
        result = await RepoRouterV2.route("高三提分专项需求")

    assert result.degraded is True
    assert model.calls == 1
    assert [e for e in events if e.get("event") == "repo_router_v2_stage1_budget_exhausted"]


@pytest.mark.asyncio
async def test_stage1_per_attempt_timeout_is_capped_by_remaining_budget(
    monkeypatch, mock_aresolve_ok, settings
) -> None:
    """per-attempt 超时取 min(per_call, 剩余预算)：per_call 远大于总预算时以后者为准。"""
    mock_aresolve_ok()
    settings.REPO_ROUTER_STAGE1_TIMEOUT_SECONDS = 1000.0
    settings.REPO_ROUTER_STAGE1_TOTAL_BUDGET_SECONDS = 2.0
    _install_stage0(monkeypatch, _high_margin_hits())
    _install_stage1_model(monkeypatch, _FlakyModel(ConnectionError("connect failed"), fail_times=2))
    timeouts = _spy_wait_for(monkeypatch)

    result = await RepoRouterV2.route("高三提分专项需求")

    assert result.degraded is True
    assert timeouts, "Stage 1 必须经 asyncio.wait_for 发起调用"
    assert all(t is not None and t <= 2.0 for t in timeouts)


@pytest.mark.asyncio
async def test_stage1_retry_backoff_never_exceeds_remaining_budget(
    monkeypatch, mock_aresolve_ok, settings
) -> None:
    """退避睡眠不超过剩余预算：退避基数远大于总预算时以剩余预算为准。"""
    mock_aresolve_ok()
    settings.REPO_ROUTER_STAGE1_RETRY_BACKOFF_SECONDS = 1000.0
    settings.REPO_ROUTER_STAGE1_TOTAL_BUDGET_SECONDS = 1.0
    _install_stage0(monkeypatch, _high_margin_hits())
    _install_stage1_model(monkeypatch, _FlakyModel(ConnectionError("connect failed"), fail_times=2))
    sleeps = _spy_sleep(monkeypatch)

    result = await RepoRouterV2.route("高三提分专项需求")

    assert result.degraded is True
    assert sleeps, "可重试失败后必须有一次退避睡眠"
    assert max(sleeps) <= 1.0


@pytest.mark.asyncio
async def test_stage1_cache_hit_skips_call_and_retry(monkeypatch, mock_aresolve_ok) -> None:
    """缓存命中路径零调用、零重试，attempts 记 0（口径与 stage1_completed 一致）。"""
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _high_margin_hits())
    model = _FlakyModel(TimeoutError("unused"), _llm_order_json("repo-a"), fail_times=0)
    _install_stage1_model(monkeypatch, model)

    first = await RepoRouterV2.route("高三提分专项需求")
    second = await RepoRouterV2.route("高三提分专项需求")

    assert first.snapshot["stage1"]["cache_hit"] is False
    assert model.calls == 1
    assert second.snapshot["stage1"]["cache_hit"] is True
    assert model.calls == 1
    assert second.snapshot["stage1"]["attempts"] == 0


@pytest.mark.asyncio
async def test_stage1_retry_is_not_delegated_to_langchain(monkeypatch, mock_aresolve_ok) -> None:
    """langchain 内部重试保持关闭：重试写在我们自己的循环里才受总预算约束。"""
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _high_margin_hits())
    captured = _install_stage1_model_capturing(monkeypatch, _TextModel(_llm_order_json("repo-a")))

    await RepoRouterV2.route("高三提分专项需求")

    assert captured["max_retries"] == 0


# ---------------------------------------------------------------------------
# 有界重排：K=3 rank-swap 裁剪 + 凸组合写 score_ranked（107-05 Task 2，RELY-05）
# ---------------------------------------------------------------------------


async def _route_with_llm_order(
    monkeypatch: pytest.MonkeyPatch,
    candidates: list[dict[str, Any]],
    llm_order: tuple[str, ...],
    **route_kwargs: Any,
) -> Any:
    """钉死 Stage 0 候选 + 钉死 LLM 排列，跑一次 route。"""
    _install_stage0(monkeypatch, _high_margin_hits())
    _install_stage0_candidates(monkeypatch, candidates)
    _install_stage1_model(monkeypatch, _TextModel(_llm_order_json(*llm_order)))
    return await RepoRouterV2.route("需求文本", **route_kwargs)


@pytest.mark.asyncio
async def test_rank_budget_clamps_tail_promotion(monkeypatch, mock_aresolve_ok) -> None:
    """LLM 把 Stage 0 第 8 位提到首位 → 裁剪产物里它不早于第 4 位，违规数留痕。

    断言落在 ``clamped_order`` 上而**不是**最终扁平列表：最终列表按凸组合后的
    ``score_ranked`` 排序，相对 Stage 0 的位移上界是 2K 而非 K。
    """
    mock_aresolve_ok()
    result = await _route_with_llm_order(
        monkeypatch, _window(8), ("r8", "r1", "r2", "r3", "r4", "r5", "r6", "r7")
    )

    stage1 = result.snapshot["stage1"]
    assert stage1["clamped_order"].index("r8") >= 7 - 3
    assert stage1["rank_budget_violations"] >= 1
    assert stage1["rank_budget_k"] == 3
    assert stage1["alpha"] == pytest.approx(0.35)


@pytest.mark.asyncio
async def test_rank_budget_identity_permutation_has_no_violation(
    monkeypatch, mock_aresolve_ok
) -> None:
    """LLM 排列 == Stage 0 排列 → 违规数 0 且裁剪产物逐字等于 Stage 0 顺序。"""
    mock_aresolve_ok()
    order = tuple(f"r{i}" for i in range(1, 9))
    result = await _route_with_llm_order(monkeypatch, _window(8), order)

    stage1 = result.snapshot["stage1"]
    assert stage1["rank_budget_violations"] == 0
    assert stage1["clamped_order"] == list(order)


@pytest.mark.asyncio
async def test_rank_budget_subset_is_not_inflated(monkeypatch, mock_aresolve_ok) -> None:
    """子集常态：LLM 只返回窗口末三位 → 裁剪产物长度恰 3、不膨胀回全量、违规数不虚高。"""
    mock_aresolve_ok()
    result = await _route_with_llm_order(monkeypatch, _window(8), ("r6", "r7", "r8"))

    stage1 = result.snapshot["stage1"]
    assert stage1["clamped_order"] == ["r6", "r7", "r8"]
    assert stage1["rank_budget_violations"] == 0
    assert stage1["llm_returned_count"] == 3
    assert stage1["stage0_window_count"] == 8
    # 最终扁平列表只断言**元素集合**恒等（顺序由凸组合决定）。
    assert {c.repo_id for c in result.candidates} == {"r6", "r7", "r8"}


@pytest.mark.asyncio
async def test_rank_budget_dropped_candidates_promotion_is_observable(
    monkeypatch, mock_aresolve_ok
) -> None:
    """「丢弃式提升」：只返回窗口末位一个仓即可绕过 K 的字面损害上界。

    ``rank_budget_violations`` 结构上看不到这条路径（子集内位次天然为 0），
    靠 ``llm_returned_count`` / ``stage0_window_count`` 两个计数事后可识别。
    """
    mock_aresolve_ok()
    result = await _route_with_llm_order(monkeypatch, _window(8), ("r8",))

    stage1 = result.snapshot["stage1"]
    assert stage1["llm_returned_count"] == 1
    assert stage1["stage0_window_count"] == 8
    assert stage1["rank_budget_violations"] == 0
    assert [c.repo_id for c in result.candidates] == ["r8"]


@pytest.mark.asyncio
async def test_score_ranked_final_order_with_pinned_stage0_margins(
    monkeypatch, mock_aresolve_ok
) -> None:
    """钉死 Stage 0 分差后断言**算出来的**最终顺序（而非「最终顺序 == LLM 顺序」）。

    r1=0.90 / r2=0.50 / r3=0.40，LLM 排列 [r3,r2,r1]，α=0.35 →
    score_ranked 为 r3 0.610 / r1 0.585 / r2 0.500 → 最终 [r3, r1, r2]。
    """
    mock_aresolve_ok()
    result = await _route_with_llm_order(
        monkeypatch,
        [_cand("r1", 0.90), _cand("r2", 0.50), _cand("r3", 0.40)],
        ("r3", "r2", "r1"),
        grouping_repository_ids=[],
    )

    ranked = {c.repo_id: c.score_ranked for c in result.candidates}
    assert ranked["r3"] == pytest.approx(0.610, abs=1e-9)
    assert ranked["r1"] == pytest.approx(0.585, abs=1e-9)
    assert ranked["r2"] == pytest.approx(0.500, abs=1e-9)
    assert [c.repo_id for c in result.candidates] == ["r3", "r1", "r2"]


@pytest.mark.asyncio
async def test_llm_fabricated_repo_id_is_dropped(monkeypatch, mock_aresolve_ok) -> None:
    """LLM 编造窗口外 repo_id → 既不进裁剪产物也不进结果候选。"""
    mock_aresolve_ok()
    result = await _route_with_llm_order(
        monkeypatch, _window(3), ("ghost-repo", "r1", "r2"), grouping_repository_ids=[]
    )

    stage1 = result.snapshot["stage1"]
    assert "ghost-repo" not in stage1["clamped_order"]
    assert stage1["clamped_order"] == ["r1", "r2"]
    assert "ghost-repo" not in {c.repo_id for c in result.candidates}


@pytest.mark.asyncio
async def test_score_ranked_is_convex_combination(monkeypatch, mock_aresolve_ok) -> None:
    """凸组合生效：score_ranked == 0.65*score + 0.35*(1 - idx/(n-1))。"""
    mock_aresolve_ok()
    result = await _route_with_llm_order(
        monkeypatch,
        [_cand("r1", 0.90), _cand("r2", 0.50), _cand("r3", 0.40)],
        ("r3", "r2", "r1"),
        grouping_repository_ids=[],
    )

    clamped = result.snapshot["stage1"]["clamped_order"]
    n = len(clamped)
    by_id = {c.repo_id: c for c in result.candidates}
    for idx, rid in enumerate(clamped):
        expected = 0.65 * by_id[rid].score + 0.35 * (1.0 - idx / (n - 1))
        assert by_id[rid].score_ranked == pytest.approx(expected, abs=1e-9)


@pytest.mark.asyncio
async def test_score_and_breakdown_unchanged_by_convex_combination(
    monkeypatch, mock_aresolve_ok
) -> None:
    """D-3 硬约束：凸组合只写旁路字段，score 与 breakdown 逐键不变、Σ 恒等仍成立。"""
    import math as _math

    mock_aresolve_ok()
    window = [_cand("r1", 0.90), _cand("r2", 0.50), _cand("r3", 0.40)]

    with_llm = await _route_with_llm_order(
        monkeypatch, window, ("r3", "r2", "r1"), grouping_repository_ids=[]
    )
    _install_stage0(monkeypatch, _high_margin_hits())
    _install_stage0_candidates(monkeypatch, window)
    without_llm = await RepoRouterV2.route("需求文本", grouping_repository_ids=[], use_llm=False)

    baseline = {c.repo_id: c for c in without_llm.candidates}
    for cand in with_llm.candidates:
        assert cand.score == baseline[cand.repo_id].score
        assert cand.breakdown == baseline[cand.repo_id].breakdown
        assert abs(_math.fsum(cand.breakdown.values()) - cand.score) < 1e-9
        assert "alpha" not in cand.breakdown


@pytest.mark.asyncio
async def test_single_candidate_does_not_divide_by_zero(monkeypatch, mock_aresolve_ok) -> None:
    """N==1 无重排空间 → 不抛 ZeroDivisionError，旁路分为 None 或等于 score。"""
    mock_aresolve_ok()
    result = await _route_with_llm_order(
        monkeypatch, [_cand("r1", 0.90)], ("r1",), grouping_repository_ids=[]
    )

    top = result.candidates[0]
    assert top.score_ranked is None or top.score_ranked == pytest.approx(top.score)


@pytest.mark.asyncio
async def test_degraded_path_leaves_score_ranked_none(monkeypatch, mock_aresolve_ok) -> None:
    """Stage 1 降级 → α 按 0 处理：全部候选 score_ranked 保持 None（消费方回退 score）。"""
    mock_aresolve_ok()
    _install_stage0(monkeypatch, _high_margin_hits())
    _install_stage0_candidates(monkeypatch, _window(3))
    _install_stage1_model(monkeypatch, _RaisingModel(RuntimeError("Error code: 400 - bad")))

    result = await RepoRouterV2.route("需求文本", grouping_repository_ids=[])

    assert result.degraded is True
    assert result.candidates
    assert all(c.score_ranked is None for c in result.candidates)


@pytest.mark.asyncio
async def test_confidence_is_unaffected_by_convex_combination(
    monkeypatch, mock_aresolve_ok, settings
) -> None:
    """confidence 仍吃 Stage 0 分数列表：α 开关不改变任何候选的分级（RELY-04 不回退）。"""
    mock_aresolve_ok()
    window = [_cand("r1", 0.90), _cand("r2", 0.50), _cand("r3", 0.40)]

    settings.REPO_ROUTER_STAGE1_ALPHA = 0.35
    blended = await _route_with_llm_order(
        monkeypatch, window, ("r3", "r2", "r1"), grouping_repository_ids=[]
    )
    settings.REPO_ROUTER_STAGE1_ALPHA = 0.0
    plain = await _route_with_llm_order(
        monkeypatch, window, ("r3", "r2", "r1"), grouping_repository_ids=[]
    )

    assert {c.repo_id: c.confidence for c in blended.candidates} == {
        c.repo_id: c.confidence for c in plain.candidates
    }


@pytest.mark.asyncio
async def test_presentation_tie_break_is_repo_id_ascending(
    monkeypatch, mock_aresolve_ok, settings
) -> None:
    """比较值相等时按 repo_id 升序——排序由 107-03 的 _apply_presentation 唯一承载。"""
    mock_aresolve_ok()
    settings.REPO_ROUTER_STAGE1_ALPHA = 0.0
    result = await _route_with_llm_order(
        monkeypatch,
        [_cand("r-z", 0.50), _cand("r-a", 0.50)],
        ("r-z", "r-a"),
        grouping_repository_ids=[],
    )

    assert [c.repo_id for c in result.candidates] == ["r-a", "r-z"]


# ---------------------------------------------------------------------------
# Stage 1 ModelUsageRecord 埋点（107-05 Task 3，LOGGING-SPEC §9 检查项）
# ---------------------------------------------------------------------------


async def _usage_rows() -> list[Any]:
    from interactions.models import ModelUsageRecord

    return [row async for row in ModelUsageRecord.objects.all()]


@pytest.mark.django_db(transaction=True)
class TestStage1ModelUsageRecording:
    """口径：**每次上游调用一行**（重试算两次请求），缓存命中零行。"""

    async def test_stage1_usage_row_on_success(self, monkeypatch, mock_aresolve_ok) -> None:
        mock_aresolve_ok()
        _install_stage0(monkeypatch, _high_margin_hits())
        _install_stage1_model(monkeypatch, _TextModel(_llm_order_json("repo-a")))

        result = await RepoRouterV2.route("高三提分专项需求")

        assert result.router_version == "v2"
        rows = await _usage_rows()
        assert len(rows) == 1
        assert rows[0].call_source == "aux_repo_router"
        assert rows[0].failure_type == ""
        assert rows[0].model
        assert rows[0].duration_ms is not None and rows[0].duration_ms >= 0

    async def test_stage1_usage_row_on_timeout_failure(
        self, monkeypatch, mock_aresolve_ok, settings
    ) -> None:
        mock_aresolve_ok()
        # 总预算极小 → 首调超时后即刻耗尽，只发一次上游调用（恰一行）。
        settings.REPO_ROUTER_STAGE1_TOTAL_BUDGET_SECONDS = 0.01
        _install_stage0(monkeypatch, _high_margin_hits())
        _install_stage1_model(monkeypatch, _CountingSlowModel())

        result = await RepoRouterV2.route("高三提分专项需求")

        assert result.degraded is True
        rows = await _usage_rows()
        assert len(rows) == 1
        assert rows[0].failure_type == "timeout"
        assert rows[0].duration_ms is not None and rows[0].duration_ms >= 0

    async def test_stage1_usage_one_row_per_upstream_attempt(
        self, monkeypatch, mock_aresolve_ok
    ) -> None:
        mock_aresolve_ok()
        _install_stage0(monkeypatch, _high_margin_hits())
        _install_stage1_model(
            monkeypatch,
            _FlakyModel(TimeoutError("first"), _llm_order_json("repo-a"), fail_times=1),
        )

        result = await RepoRouterV2.route("高三提分专项需求")

        assert result.degraded is False
        rows = await _usage_rows()
        assert len(rows) == 2
        assert {r.failure_type for r in rows} == {"timeout", ""}

    async def test_stage1_usage_zero_rows_on_cache_hit(self, monkeypatch, mock_aresolve_ok) -> None:
        mock_aresolve_ok()
        _install_stage0(monkeypatch, _high_margin_hits())
        _install_stage1_model(monkeypatch, _TextModel(_llm_order_json("repo-a")))

        await RepoRouterV2.route("高三提分专项需求")
        assert len(await _usage_rows()) == 1

        second = await RepoRouterV2.route("高三提分专项需求")

        assert second.snapshot["stage1"]["cache_hit"] is True
        assert len(await _usage_rows()) == 1

    async def test_stage1_usage_binds_triggering_user(self, monkeypatch, mock_aresolve_ok) -> None:
        import structlog

        mock_aresolve_ok()
        _install_stage0(monkeypatch, _high_margin_hits())
        _install_stage1_model(monkeypatch, _TextModel(_llm_order_json("repo-a")))

        structlog.contextvars.bind_contextvars(user_id="42")
        try:
            await RepoRouterV2.route("高三提分专项需求")
        finally:
            structlog.contextvars.unbind_contextvars("user_id")

        rows = await _usage_rows()
        assert rows[0].user_id == "42"

    async def test_stage1_usage_defaults_user_to_system(
        self, monkeypatch, mock_aresolve_ok
    ) -> None:
        import structlog

        mock_aresolve_ok()
        structlog.contextvars.clear_contextvars()
        _install_stage0(monkeypatch, _high_margin_hits())
        _install_stage1_model(monkeypatch, _TextModel(_llm_order_json("repo-a")))

        await RepoRouterV2.route("高三提分专项需求")

        rows = await _usage_rows()
        assert rows[0].user_id == "system"

    async def test_stage1_usage_tokens_default_to_zero_when_unknown(
        self, monkeypatch, mock_aresolve_ok
    ) -> None:
        """上游未回 usage metadata → token 一律记 0（不猜）。"""
        mock_aresolve_ok()
        _install_stage0(monkeypatch, _high_margin_hits())
        _install_stage1_model(monkeypatch, _TextModel(_llm_order_json("repo-a")))

        await RepoRouterV2.route("高三提分专项需求")

        rows = await _usage_rows()
        assert rows[0].prompt_tokens == 0
        assert rows[0].completion_tokens == 0
        assert rows[0].total_tokens == 0
        assert rows[0].ttft_ms is None

    async def test_stage1_usage_write_failure_never_breaks_route(
        self, monkeypatch, mock_aresolve_ok
    ) -> None:
        """埋点写库抛异常 → 路由主流程不受影响（观测 best-effort）。"""
        mock_aresolve_ok()
        _install_stage0(monkeypatch, _high_margin_hits())
        _install_stage1_model(monkeypatch, _TextModel(_llm_order_json("repo-a")))

        async def _boom(**_kwargs: Any) -> None:
            raise RuntimeError("ledger down")

        monkeypatch.setattr("interactions.ledger.arecord_llm_usage", _boom)

        result = await RepoRouterV2.route("高三提分专项需求")

        assert result.router_version == "v2"
        assert result.degraded is False
        assert await _usage_rows() == []
