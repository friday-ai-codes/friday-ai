"""离线回放守护测试（ROUTE-09，105-07）：回放同结果 + 零网络 + 脱敏 + payload 上限。

快照构造走真实 ``_h_route`` 组装代码路径（mock engine/session/emit 捕获 payload），
保证测试锁的是生产 payload 形状而非手写形状。全文件不做任何 socket allow——
pytest 默认 ``--disable-socket`` 下全绿即「回放全程零网络」的证明。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import codegraph.services.repo_router_scoring as repo_router_scoring
from codegraph.services.repo_router_replay import (
    replay_route_from_snapshot,
    verify_snapshot_replay,
)
from codegraph.services.repo_router_scoring import apply_llm_adjustment
from codegraph.services.repo_router_v2 import (
    RepoRouteCandidateV2,
    RepoRouteResultV2,
    RepoRouterV2,
)
from services.process_runtime.builtin_processes import _h_route

# θ 阈值与 settings 默认一致（ROUTING-RANKING §1.3a 初值）——replay 以参数注入。
THETA = {"theta_abs": 0.55, "theta_margin": 0.08, "theta_med": 0.35}

QUERY = "高三提分专项"


def _qdrant_hit(
    node_id: str,
    rid: str,
    score: float,
    *,
    repo_name: str = "",
    activity: str | None = "活跃开发",
    node_path: str = "",
    built_at: str = "2026-07-01T00:00:00Z",
) -> dict:
    """构造 Qdrant hybrid 检索返回的 hit 形状（route() 的 Stage 0 原始输入）。"""
    payload: dict = {
        "node_id": node_id,
        "repository_id": rid,
        "node_path": node_path or f"{rid}/能力/{node_id}",
        "sub_project": "",
        "summary": f"{node_id} 的能力摘要",
        "facets": {"活跃度": activity} if activity else {},
        "built_at": built_at,
    }
    if repo_name:
        payload["repo_name"] = repo_name
    return {"id": node_id, "score": score, "payload": payload}


def _default_hits(*, with_repo_name: bool = True) -> list[dict]:
    """三仓样本：r1 双命中高分（high）、r2 单命中中分（medium）、r3 低分（low）。"""
    name = {"r1": "repo-one", "r2": "repo-two", "r3": "repo-three"} if with_repo_name else {}
    return [
        _qdrant_hit("n1", "r1", 1.0, repo_name=name.get("r1", "")),
        _qdrant_hit("n2", "r1", 0.8, repo_name=name.get("r1", "")),
        _qdrant_hit("n3", "r2", 0.5, repo_name=name.get("r2", "")),
        _qdrant_hit("n4", "r3", 0.2, repo_name=name.get("r3", "")),
    ]


def _degraded_result(node_hits: list[dict], *, top_k: int = 3) -> RepoRouteResultV2:
    """走 route() 降级统一出口 ``_stage0_only_result``（Stage 1 未参与路径）产出结果。"""
    stage0_candidates = RepoRouterV2._stage0_candidates(node_hits, top_k=12)
    return RepoRouterV2._stage0_only_result(
        QUERY,
        node_hits,
        stage0_candidates,
        top_k,
        time.monotonic(),
        stage1_meta={"skipped_reason": "stage1_failed:TimeoutError"},
    )


def _v2_result_with_stage1(
    node_hits: list[dict],
    permutation: list[str],
    llm_conf_by_id: dict[str, str],
    stage1_meta: dict,
    *,
    top_k: int = 3,
) -> RepoRouteResultV2:
    """复刻 route() v2 路径的 Stage 1 排列处理（排列重排 + 只降不升）产出结果。"""
    stage0_candidates = RepoRouterV2._stage0_candidates(node_hits, top_k=12)
    sorted_scores = [float(c["score"]) for c in stage0_candidates]
    rank_by_id = {c["repo_id"]: i for i, c in enumerate(stage0_candidates)}
    by_id = {c["repo_id"]: c for c in stage0_candidates}
    final: list[RepoRouteCandidateV2] = []
    for rid in permutation:
        base = by_id[rid]
        deterministic = RepoRouterV2._deterministic_confidence(sorted_scores, rank_by_id[rid])
        confidence = apply_llm_adjustment(deterministic, llm_conf_by_id.get(rid))  # type: ignore[arg-type]
        final.append(
            RepoRouteCandidateV2(
                repo_id=rid,
                repo_name=base["repo_name"],
                score=float(base["score"]),
                confidence=confidence,
                reasoning="按能力节点命中推理",
                breakdown=dict(base["breakdown"]),
            )
        )
    final = final[:top_k]
    return RepoRouteResultV2(
        candidates=final,
        router_version="v2",
        auto_selected=bool(final) and final[0].confidence == "high",
        degraded=False,
        snapshot=RepoRouterV2._build_snapshot(QUERY, node_hits, final, stage1_meta=stage1_meta),
    )


async def _emit_payload(result: RepoRouteResultV2) -> dict:
    """走真实 ``_h_route`` 组装路径（adapter dict → _h_route → _emit_event）捕获 payload。"""
    routing = {
        "candidates": [
            {"repo_id": c.repo_id, "confidence": c.confidence, "repository_name": c.repo_name}
            for c in result.candidates
        ],
        "router_version": result.router_version,
        "auto_selected": result.auto_selected,
        "degraded": result.degraded,
        "snapshot": result.snapshot,
    }
    engine = SimpleNamespace(
        deps=SimpleNamespace(router=SimpleNamespace(route=AsyncMock(return_value=routing))),
        session_service=SimpleNamespace(_emit_event=AsyncMock()),
    )
    await _h_route(SimpleNamespace(id="s1"), engine)
    return engine.session_service._emit_event.call_args.args[2]


# ---------------------------------------------------------------------------
# 回放同结果
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_matches_recorded_without_stage1() -> None:
    """无 Stage 1（降级路径）：重算候选与记录逐字段相等（repo_id/score/breakdown/confidence）。"""
    payload = await _emit_payload(_degraded_result(_default_hits()))

    replayed = replay_route_from_snapshot(payload, **THETA)

    recorded = payload["candidates"]
    assert [c["repo_id"] for c in replayed] == [c["repo_id"] for c in recorded] == ["r1", "r2", "r3"]
    for rec, rep in zip(recorded, replayed):
        assert rep["repo_id"] == rec["repo_id"]
        assert rep["confidence"] == rec["confidence"]
        assert abs(rep["score"] - rec["score"]) <= 1e-9
        assert rep["breakdown"] == rec["breakdown"]
    # 语义抽查：margin 达标首位 high、次位 medium、尾位 low
    assert [c["confidence"] for c in replayed] == ["high", "medium", "low"]

    ok, diff = verify_snapshot_replay(payload, **THETA)
    assert ok, diff
    assert diff == ""


@pytest.mark.asyncio
async def test_replay_matches_recorded_with_stage1_permutation() -> None:
    """有 Stage 1：payload 排列记录（candidates 顺序 + confidence hint）重放后与记录相等。"""
    stage1_meta = {
        "prompt": "system+human 拼接 prompt",
        "response": '[{"repo_id": "r2"}, {"repo_id": "r1"}]',
        "model_id": "fast-model-v1",
        "prompt_hash": "a" * 64,
        "cache_hit": False,
    }
    # LLM 排列把 r2 提到首位，并把 r1 的确定性 high 降级为 medium（只降不升）
    result = _v2_result_with_stage1(
        _default_hits(), ["r2", "r1"], {"r1": "medium"}, stage1_meta
    )
    payload = await _emit_payload(result)
    assert payload["stage1"]["model_id"] == "fast-model-v1"

    replayed = replay_route_from_snapshot(payload, **THETA)

    recorded = payload["candidates"]
    assert [c["repo_id"] for c in replayed] == ["r2", "r1"]
    for rec, rep in zip(recorded, replayed):
        assert rep["repo_id"] == rec["repo_id"]
        assert rep["confidence"] == rec["confidence"]
        assert abs(rep["score"] - rec["score"]) <= 1e-9
        assert rep["breakdown"] == rec["breakdown"]
    # r1 被 LLM 降级为 medium 的记录被回放复现（apply_llm_adjustment 只降不升）
    assert replayed[1]["confidence"] == "medium"

    ok, diff = verify_snapshot_replay(payload, **THETA)
    assert ok, diff


@pytest.mark.asyncio
async def test_verify_detects_tampered_confidence() -> None:
    """记录被篡改（low 候选伪造成 high，违反只降不升）→ verify 返回 False + diff 文本。"""
    payload = await _emit_payload(_degraded_result(_default_hits()))
    payload["candidates"][2]["confidence"] = "high"

    ok, diff = verify_snapshot_replay(payload, **THETA)
    assert not ok
    assert "confidence" in diff


# ---------------------------------------------------------------------------
# repo_name 缺失容错（历史快照）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_tolerates_missing_repo_name() -> None:
    """node_hits 全部无 repo_name 的历史快照：回放不抛异常且比对通过（比对键不含 repo_name）。"""
    payload = await _emit_payload(_degraded_result(_default_hits(with_repo_name=False)))
    assert all("repo_name" not in h for h in payload["stage0"]["node_hits"])

    replayed = replay_route_from_snapshot(payload, **THETA)
    assert {"repo_id", "score", "breakdown", "confidence"} == set(replayed[0].keys())

    ok, diff = verify_snapshot_replay(payload, **THETA)
    assert ok, diff


@pytest.mark.asyncio
async def test_replay_result_invariant_to_repo_name_presence() -> None:
    """含名与缺名快照等值输入 → 回放输出逐字段一致（repo_name 不影响分数/排序/分级）。"""
    with_name = await _emit_payload(_degraded_result(_default_hits(with_repo_name=True)))
    without_name = await _emit_payload(_degraded_result(_default_hits(with_repo_name=False)))

    assert replay_route_from_snapshot(with_name, **THETA) == replay_route_from_snapshot(
        without_name, **THETA
    )


# ---------------------------------------------------------------------------
# 脱敏 + payload 上限 + 模块纯度
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_payload_redacts_injected_secret() -> None:
    """stage1 prompt 注入假密钥走 _h_route 组装路径 → 序列化 payload 无明文（T-105-15）。"""
    fake_key = "sk-abc123def456ghi789jkl012mno345"
    stage1_meta = {
        "prompt": f"上游返回的仓库摘要里混入了 {fake_key} 这样的敏感串",
        "response": "[]",
        "model_id": "fast-model-v1",
        "prompt_hash": "b" * 64,
        "cache_hit": False,
    }
    result = _v2_result_with_stage1(_default_hits(), ["r1"], {}, stage1_meta)
    payload = await _emit_payload(result)

    serialized = json.dumps(payload, ensure_ascii=False)
    assert "sk-abc123" not in serialized
    assert "REDACTED" in serialized


@pytest.mark.asyncio
async def test_snapshot_payload_under_64kb_with_50_hits() -> None:
    """50 个 node_hits 的满配快照序列化后 < 64KB（T-105-16 防 payload 无界膨胀）。"""
    hits = [
        _qdrant_hit(
            f"node-{i:03d}",
            f"repo-{i % 10}",
            1.0 - i * 0.01,
            repo_name=f"repository-name-{i % 10}",
            node_path=f"repo-{i % 10}/领域能力/模块-{i:03d}/子能力点-{i:03d}",
        )
        for i in range(50)
    ]
    stage1_meta = {
        "prompt": "候选仓库及命中节点：\n" + "\n".join(f"- 节点 {i} 的能力描述与推理材料" for i in range(50)),
        "response": json.dumps(
            [{"repo_id": f"repo-{i}", "reasoning": "一句中文推理理由" * 3} for i in range(3)],
            ensure_ascii=False,
        ),
        "model_id": "fast-model-v1",
        "prompt_hash": "c" * 64,
        "cache_hit": False,
    }
    result = _v2_result_with_stage1(hits, ["repo-0", "repo-1", "repo-2"], {}, stage1_meta)
    payload = await _emit_payload(result)

    assert len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) < 64 * 1024


def test_replay_module_import_purity() -> None:
    """replay 模块零 I/O：不 import Django/Qdrant/LLM/ORM（零网络回放的结构保证）。"""
    import codegraph.services.repo_router_replay as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in ("django", "qdrant", "langchain", "asgiref", "httpx", "openai"):
        assert not re.search(
            rf"^\s*(?:from|import)\s+{forbidden}", source, re.MULTILINE
        ), f"replay 模块不得 import {forbidden}"
    # 复用纯函数而非内联第二份实现
    assert "aggregate_and_score" in source
    assert "derive_confidence" in source
    assert "apply_llm_adjustment" in source


# ===========================================================================
# Phase 106（106-07）：新格式快照自包含回放 + 105 旧快照回退
#
# 新格式快照构造沿用「真实组装路径」纪律：Stage 0 打分走
# ``RepoRouterV2._stage0_candidates``（新路径参数注入），快照材料走
# ``_stage0_only_result`` / ``_build_snapshot``（与 route() 同一组装口径，
# 106-06），payload 走真实 ``_h_route`` 落盘路径——不手写 payload 字面量。
# ===========================================================================

# 固定时间锚点（远离真实运行时间 2026-07+）：活跃度衰减若误用系统时钟必现偏差。
SCORED_AT = "2026-01-15T00:00:00+00:00"

# 非默认权重（DEFAULT domain=0.15 → 0.20）：快照自包含检验的辨识度来源。
WEIGHTS_ALT: dict[str, float] = {
    "text": 0.40,
    "domain": 0.20,
    "activity": 0.12,
    "stack": 0.08,
    "team": 0.05,
}


def _full_constants() -> dict:
    """快照携带的生效常数全值（含 n_bar）——与 route() 组装口径一致（106-06）。"""
    consts = dict(repo_router_scoring.DEFAULT_WEIGHT_CONFIG["constants"])
    consts["n_bar"] = 60.0
    return consts


def _full_repo_meta() -> dict[str, dict]:
    """per-候选 repo_meta：r1/r2 满配（n_r/last_commit_at/dense_cos_max/facet_scores
    全有），r3 逐字段缺失（信号不可用走重归一化 + 活跃度枚举回退）。

    last_commit_at 与 SCORED_AT 的间隔刻意设计：r1 仅隔 5 天（≤ offset_days=14
    → 衰减系数恒 1.0），锚点若误用真实 now（2026-07+）该系数必 < 1。
    """
    return {
        "r1": {
            "n_r": 620,
            "last_commit_at": "2026-01-10T00:00:00+00:00",
            "dense_cos_max": 0.62,
            "facet_scores": {
                "domain": {"score": 1.0, "layer": "t1"},
                "stack": {"score": 0.8, "layer": "t2"},
                "team": {"score": None, "layer": None},
            },
            "criticality_value": "核心",
        },
        "r2": {
            "n_r": 30,
            "last_commit_at": "2025-12-01T00:00:00+00:00",
            "dense_cos_max": 0.5,
            "facet_scores": {
                "domain": {"score": 0.6, "layer": "t1"},
                "stack": {"score": 1.0, "layer": "t1"},
                "team": {"score": None, "layer": None},
            },
            "criticality_value": "重要",
        },
        "r3": {
            "n_r": 40,
            "last_commit_at": None,
            "dense_cos_max": None,
            "facet_scores": {
                "domain": {"score": None, "layer": None},
                "stack": {"score": None, "layer": None},
                "team": {"score": None, "layer": None},
            },
            "criticality_value": None,
        },
    }


def _snapshot_weight_config(
    weights: dict[str, float], constants: dict, *, version: str = "replay-test-v1"
) -> dict:
    """快照 weight_config 节（与 route() 的组装形状一致，106-06）。"""
    return {
        "weights": dict(weights),
        "constants": dict(constants),
        "weight_set_version": version,
        "alias_dict_hash": "d" * 64,
        "embedding_model_id": "test-embed-model",
    }


def _meta_stage0(
    node_hits: list[dict],
    *,
    weights: dict[str, float] | None = None,
    repo_meta: dict[str, dict] | None = None,
    constants: dict | None = None,
    scored_at: str = SCORED_AT,
) -> tuple[list[dict], dict, dict]:
    """新路径 Stage 0 打分 + 快照材料组装（复刻 route() 的六信号注入口径）。"""
    weights = weights if weights is not None else WEIGHTS_ALT
    repo_meta = repo_meta if repo_meta is not None else _full_repo_meta()
    constants = constants if constants is not None else _full_constants()
    stage0_candidates = RepoRouterV2._stage0_candidates(
        node_hits,
        top_k=12,
        weights=weights,
        repo_meta=repo_meta,
        constants=constants,
        now=scored_at,
    )
    snapshot_repo_meta = {
        c["repo_id"]: repo_meta[c["repo_id"]]
        for c in stage0_candidates
        if c["repo_id"] in repo_meta
    }
    return stage0_candidates, _snapshot_weight_config(weights, constants), snapshot_repo_meta


def _meta_degraded_result(
    node_hits: list[dict] | None = None, *, top_k: int = 3, scored_at: str = SCORED_AT
) -> RepoRouteResultV2:
    """新格式快照（Stage 1 未参与出口）：走真实 ``_stage0_only_result`` 组装路径。"""
    hits = node_hits if node_hits is not None else _default_hits()
    stage0_candidates, weight_config, snapshot_repo_meta = _meta_stage0(hits, scored_at=scored_at)
    return RepoRouterV2._stage0_only_result(
        QUERY,
        hits,
        stage0_candidates,
        top_k,
        time.monotonic(),
        stage1_meta={"skipped_reason": "use_llm_false"},
        weight_config=weight_config,
        repo_meta=snapshot_repo_meta,
        scored_at=scored_at,
    )


def _meta_result_with_stage1(
    node_hits: list[dict],
    permutation: list[str],
    llm_conf_by_id: dict[str, str],
    stage1_meta: dict,
    *,
    top_k: int = 3,
    repo_meta: dict[str, dict] | None = None,
) -> RepoRouteResultV2:
    """新格式快照（Stage 1 参与）：排列重排 + 只降不升，快照带 weight_config 三件套。"""
    stage0_candidates, weight_config, snapshot_repo_meta = _meta_stage0(
        node_hits, repo_meta=repo_meta
    )
    sorted_scores = [float(c["score"]) for c in stage0_candidates]
    rank_by_id = {c["repo_id"]: i for i, c in enumerate(stage0_candidates)}
    by_id = {c["repo_id"]: c for c in stage0_candidates}
    final: list[RepoRouteCandidateV2] = []
    for rid in permutation:
        base = by_id[rid]
        deterministic = RepoRouterV2._deterministic_confidence(sorted_scores, rank_by_id[rid])
        confidence = apply_llm_adjustment(deterministic, llm_conf_by_id.get(rid))  # type: ignore[arg-type]
        final.append(
            RepoRouteCandidateV2(
                repo_id=rid,
                repo_name=base["repo_name"],
                score=float(base["score"]),
                confidence=confidence,
                reasoning="按能力节点命中推理",
                breakdown=dict(base["breakdown"]),
                criticality=base.get("criticality"),
            )
        )
    final = final[:top_k]
    return RepoRouteResultV2(
        candidates=final,
        router_version="v2",
        auto_selected=bool(final) and final[0].confidence == "high",
        degraded=False,
        snapshot=RepoRouterV2._build_snapshot(
            QUERY,
            node_hits,
            final,
            stage1_meta=stage1_meta,
            weight_config=weight_config,
            repo_meta=snapshot_repo_meta,
            scored_at=SCORED_AT,
        ),
    )


class TestMultiSignalReplay:
    """新格式快照（weight_config + repo_meta + scored_at）自包含回放守护。"""

    @pytest.mark.asyncio
    async def test_new_snapshot_replay_matches_recorded(self) -> None:
        """新格式回放等值：候选顺序/score/breakdown（含 domain 键）/confidence
        与记录逐字段相等（score 容差 1e-9，round 口径对齐 to_dict）。"""
        payload = await _emit_payload(_meta_degraded_result())
        assert payload["weight_config"]["weights"]["domain"] == 0.20  # 非默认权重进快照
        assert payload["stage0"]["scored_at"] == SCORED_AT

        replayed = replay_route_from_snapshot(payload, **THETA)

        recorded = payload["candidates"]
        assert (
            [c["repo_id"] for c in replayed]
            == [c["repo_id"] for c in recorded]
            == ["r1", "r2", "r3"]
        )
        for rec, rep in zip(recorded, replayed):
            assert rep["repo_id"] == rec["repo_id"]
            assert rep["confidence"] == rec["confidence"]
            assert abs(rep["score"] - rec["score"]) <= 1e-9
            assert rep["breakdown"] == rec["breakdown"]
        # 新信号键随记录回放（breakdown 键集合比对天然覆盖新信号）
        assert "domain" in replayed[0]["breakdown"]
        assert "stack" in replayed[0]["breakdown"]

        ok, diff = verify_snapshot_replay(payload, **THETA)
        assert ok, diff
        assert diff == ""

    @pytest.mark.asyncio
    async def test_new_snapshot_with_stage1_permutation_matches(self) -> None:
        """新格式 + Stage 1 排列记录：重放按 payload 排列 + confidence hint 复现记录。"""
        stage1_meta = {
            "prompt": "system+human 拼接 prompt",
            "response": '[{"repo_id": "r2"}, {"repo_id": "r1"}]',
            "model_id": "fast-model-v1",
            "prompt_hash": "e" * 64,
            "cache_hit": False,
        }
        result = _meta_result_with_stage1(
            _default_hits(), ["r2", "r1"], {"r1": "medium"}, stage1_meta
        )
        payload = await _emit_payload(result)

        replayed = replay_route_from_snapshot(payload, **THETA)

        recorded = payload["candidates"]
        assert [c["repo_id"] for c in replayed] == ["r2", "r1"]
        for rec, rep in zip(recorded, replayed):
            assert rep["repo_id"] == rec["repo_id"]
            assert rep["confidence"] == rec["confidence"]
            assert abs(rep["score"] - rec["score"]) <= 1e-9
            assert rep["breakdown"] == rec["breakdown"]
        # r1 被 LLM 降级为 medium 的记录被复现（只降不升在新路径分数上成立）
        assert replayed[1]["confidence"] == "medium"

        ok, diff = verify_snapshot_replay(payload, **THETA)
        assert ok, diff

    @pytest.mark.asyncio
    async def test_replay_weights_come_from_snapshot_not_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """权重/常数来自快照而非环境：改掉 DEFAULT_WEIGHT_CONFIG 后同一快照回放结果不变。"""
        payload = await _emit_payload(_meta_degraded_result())
        baseline = replay_route_from_snapshot(payload, **THETA)

        monkeypatch.setitem(
            repo_router_scoring.DEFAULT_WEIGHT_CONFIG,
            "weights",
            {"text": 0.10, "domain": 0.55, "activity": 0.20, "stack": 0.30, "team": 0.40},
        )
        monkeypatch.setitem(
            repo_router_scoring.DEFAULT_WEIGHT_CONFIG,
            "constants",
            {**repo_router_scoring.DEFAULT_WEIGHT_CONFIG["constants"], "lam": 0.9},
        )

        again = replay_route_from_snapshot(payload, **THETA)

        assert list(again) == list(baseline)  # 快照自包含：环境默认值不参与
        recorded = payload["candidates"]
        for rec, rep in zip(recorded, again):
            assert abs(rep["score"] - rec["score"]) <= 1e-9
            assert rep["breakdown"] == rec["breakdown"]

    @pytest.mark.asyncio
    async def test_replay_activity_anchor_is_snapshot_scored_at(self) -> None:
        """衰减锚点取快照 scored_at 而非 now：同一快照相隔两次调用活跃度贡献相同，
        且 r1（last_commit 距锚点 5 天 ≤ offset）衰减系数恒 1.0——若实现误用真实
        当前时间（2026-07+，距 last_commit 半年）该系数必 < 1、逐字段等值即失败。"""
        payload = await _emit_payload(_meta_degraded_result())

        first = replay_route_from_snapshot(payload, **THETA)
        second = replay_route_from_snapshot(payload, **THETA)

        assert list(first) == list(second)  # 回放不读时钟
        rec_activity = payload["candidates"][0]["breakdown"]["activity"]
        assert abs(first[0]["breakdown"]["activity"] - rec_activity) <= 1e-9
        # 锚点语义直算：r1 available = text+domain+stack+activity，D=0.80，
        # 衰减系数 1.0 → activity 贡献 = 0.12 * 1.0 / 0.80（round 6 口径）
        assert abs(rec_activity - round(0.12 * 1.0 / 0.80, 6)) <= 1e-9

    @pytest.mark.asyncio
    async def test_replay_reports_weight_set_version_and_legacy_flag(self) -> None:
        """返回值契约新字段：weight_set_version（本次回放采用版本）+ legacy_snapshot。"""
        payload = await _emit_payload(_meta_degraded_result())

        replayed = replay_route_from_snapshot(payload, **THETA)

        assert replayed.weight_set_version == "replay-test-v1"
        assert replayed.legacy_snapshot is False

    @pytest.mark.asyncio
    async def test_verify_detects_tampered_domain_breakdown(self) -> None:
        """新格式快照篡改候选 breakdown["domain"] → verify 逐信号 diff 拦截（T-106-17）。"""
        payload = await _emit_payload(_meta_degraded_result())
        payload["candidates"][0]["breakdown"]["domain"] += 0.01

        ok, diff = verify_snapshot_replay(payload, **THETA)

        assert not ok
        assert "breakdown[domain]" in diff

    @pytest.mark.asyncio
    async def test_new_snapshot_payload_under_64kb_with_full_meta(self) -> None:
        """50 node_hits + 12 候选满配 repo_meta + weight_config 全值 < 64KB（Pitfall 5 复核）。"""
        hits = [
            _qdrant_hit(
                f"node-{i:03d}",
                f"repo-{i % 12}",
                1.0 - i * 0.01,
                repo_name=f"repository-name-{i % 12}",
                node_path=f"repo-{i % 12}/领域能力/模块-{i:03d}/子能力点-{i:03d}",
            )
            for i in range(50)
        ]
        full_meta = {
            f"repo-{r}": {
                "n_r": 100 + r,
                "last_commit_at": "2026-01-10T00:00:00+00:00",
                "dense_cos_max": 0.40 + r * 0.01,
                "facet_scores": {
                    "domain": {"score": 1.0, "layer": "t1"},
                    "stack": {"score": 0.8, "layer": "t2"},
                    "team": {"score": 0.6, "layer": "t1"},
                },
                "criticality_value": "核心",
            }
            for r in range(12)
        }
        stage1_meta = {
            "prompt": "候选仓库及命中节点：\n"
            + "\n".join(f"- 节点 {i} 的能力描述与推理材料" for i in range(50)),
            "response": json.dumps(
                [{"repo_id": f"repo-{i}", "reasoning": "一句中文推理理由" * 3} for i in range(3)],
                ensure_ascii=False,
            ),
            "model_id": "fast-model-v1",
            "prompt_hash": "f" * 64,
            "cache_hit": False,
        }
        result = _meta_result_with_stage1(
            hits, ["repo-0", "repo-1", "repo-2"], {}, stage1_meta, repo_meta=full_meta
        )
        payload = await _emit_payload(result)

        assert len(payload["repo_meta"]) == 12  # 12 候选 repo_meta 全部随快照
        assert payload["weight_config"]["constants"]["n_bar"] == 60.0
        assert len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) < 64 * 1024


class TestLegacySnapshotFallback:
    """105 旧快照（phase105-v1 / 缺 weight_config 节）回退守护——按当时版本比对。"""

    @pytest.mark.asyncio
    async def test_legacy_snapshot_replays_without_error_and_flags(self) -> None:
        """旧快照回放不抛：legacy 三信号路径重算与记录等值，返回值标注
        legacy_snapshot=True + weight_set_version="phase105-v1"。"""
        payload = await _emit_payload(_degraded_result(_default_hits()))
        assert "weight_config" not in payload  # legacy 快照以缺节识别（106-06 决策）

        replayed = replay_route_from_snapshot(payload, **THETA)

        recorded = payload["candidates"]
        for rec, rep in zip(recorded, replayed):
            assert rep["repo_id"] == rec["repo_id"]
            assert rep["confidence"] == rec["confidence"]
            assert abs(rep["score"] - rec["score"]) <= 1e-9
            assert rep["breakdown"] == rec["breakdown"]
        assert set(replayed[0]["breakdown"]) <= {"text", "breadth", "activity"}  # legacy 三信号
        assert replayed.legacy_snapshot is True
        assert replayed.weight_set_version == "phase105-v1"

        ok, diff = verify_snapshot_replay(payload, **THETA)
        assert ok, diff

    @pytest.mark.asyncio
    async def test_legacy_verify_diff_carries_version_note(self) -> None:
        """旧快照构造不等值场景 → diff 文本头部标注「旧版本快照（phase105-v1），
        按当时版本比对」；新格式快照的 diff 不带该标注（版本不同即不可比，§6.2-9）。"""
        from codegraph.services.repo_router_replay import LEGACY_SNAPSHOT_NOTE

        payload = await _emit_payload(_degraded_result(_default_hits()))
        payload["candidates"][2]["confidence"] = "high"  # 构造不等值

        ok, diff = verify_snapshot_replay(payload, **THETA)

        assert not ok
        assert diff.splitlines()[0] == LEGACY_SNAPSHOT_NOTE
        assert "phase105-v1" in diff

        new_payload = await _emit_payload(_meta_degraded_result())
        new_payload["candidates"][0]["breakdown"]["domain"] += 0.01
        ok2, diff2 = verify_snapshot_replay(new_payload, **THETA)
        assert not ok2
        assert LEGACY_SNAPSHOT_NOTE not in diff2

    @pytest.mark.asyncio
    async def test_malformed_weight_config_falls_back_legacy(self) -> None:
        """weight_config 节残缺/类型错误 → 视为 legacy 回退路径不抛（T-106-18）。"""
        payload = await _emit_payload(_degraded_result(_default_hits()))
        payload["weight_config"] = {"weights": "not-a-dict"}  # 类型错误节

        replayed = replay_route_from_snapshot(payload, **THETA)

        assert replayed.legacy_snapshot is True
        assert replayed.weight_set_version == "phase105-v1"
        ok, diff = verify_snapshot_replay(payload, **THETA)
        assert ok, diff
