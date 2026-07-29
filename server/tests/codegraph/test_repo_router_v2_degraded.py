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


def _install_stage1_model(monkeypatch: pytest.MonkeyPatch, model: Any) -> None:
    """让 Stage 1 走到 model.ainvoke：patch lazy import 的 build_chat_model seam
    与 aget_claude_code_runtime_config（模型名解析不触 DB）。"""

    async def _fake_cc_rt() -> dict[str, str]:
        return {"haiku_model": "fake-haiku"}

    monkeypatch.setattr(
        "services.provider_config.aget_claude_code_runtime_config", _fake_cc_rt
    )
    monkeypatch.setattr("agents.llm_factory.build_chat_model", lambda *a, **kw: model)


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
