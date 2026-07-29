"""离线回放：从 repo.routing 快照 payload 重建输入 → 纯函数重算 → 与记录比对（ROUTE-09）。

零 I/O 纯函数模块：仅依赖 stdlib 与 ``repo_router_scoring``（同样零 I/O）——
禁止 import Django / Qdrant / LLM / ORM；pytest 默认 ``--disable-socket`` 下
测试全绿即「回放全程零网络」的结构证明。

回放与 ``route()`` / golden harness 共用同一份纯函数
（``aggregate_and_score`` / ``derive_confidence`` / ``apply_llm_adjustment``）——
本模块只做「payload 形状 ↔ 纯函数输入输出」的适配，禁止内联第二份打分 /
confidence 实现（推导只在 scoring 模块一处）。

Stage 1 排列记录契约：LLM 是回放中唯一不可重算的环节，其决策以数据形式记录
在 payload 里——``payload["candidates"]`` 的顺序即 Stage 1 排列，每候选的
``confidence`` 即只降不升调节后的最终值。回放时该值作为 hint 重新过
``apply_llm_adjustment``：合法记录满足 ``min(det, min(det, hint)) == min(det, hint)``
恒等，重算必得同值；若记录违反只降不升（如 low 被伪造成 high），重算值将与
记录不一致，``verify_snapshot_replay`` 即拦截。``payload["stage1"]`` 无
``skipped_reason`` 标记 Stage 1 参与；含 ``skipped_reason``（降级/跳过路径）
则排列纯由重算分数导出。

repo_name 容错契约：快照 node_hits 本就不存 repo_name（105-03 最小字段集），
重建 payload 不含 repo_name——由打分核心的回退规则（缺失 → repo_name=repo_id）
保证确定性，replay 不自行补名；比对键固定为 repo_id/score/breakdown/confidence
（不含 repo_name），缺名历史快照回放不抛异常且与含名快照等值输入结果一致。
"""

from __future__ import annotations

from typing import Any

from codegraph.services.repo_router_scoring import (
    Confidence,
    ScoredCandidate,
    aggregate_and_score,
    apply_llm_adjustment,
    derive_confidence,
)

__all__ = ["replay_route_from_snapshot", "verify_snapshot_replay"]

# score 比对容差：记录值与重算值经过同一 round（score 4 位 / breakdown 6 位，
# 与 RepoRouteCandidateV2.to_dict 一致），理论差为 0，容差仅防序列化噪声。
_SCORE_TOLERANCE = 1e-9

_COMPARE_KEYS = ("repo_id", "score", "breakdown", "confidence")


def _rebuild_hits(node_hits: list[Any]) -> list[dict[str, Any]]:
    """把快照最小字段集 node_hits 还原为 ``aggregate_and_score`` 的 hit 形状。

    ``node_id`` 必须回填进 payload：打分核心桶内 tie-break 第二键读
    ``payload.node_id``，缺失会让等分 hits 顺序不定 → facets 取样漂移。
    repo_name 不还原（快照本就不存）——打分核心回退 ``repo_name = repo_id``。
    """
    hits: list[dict[str, Any]] = []
    for h in node_hits:
        if not isinstance(h, dict):
            continue
        activity = h.get("activity_facet")
        node_id = str(h.get("node_id", ""))
        hits.append(
            {
                "id": node_id,
                "score": float(h.get("score", 0.0)),
                "payload": {
                    "node_id": node_id,
                    "repository_id": str(h.get("repository_id", "")),
                    "node_path": str(h.get("node_path", "")),
                    "facets": {"活跃度": activity} if activity is not None else {},
                },
            }
        )
    return hits


def _deterministic_confidence(
    sorted_scores: list[float],
    rank: int,
    *,
    theta_abs: float,
    theta_margin: float,
    theta_med: float,
) -> Confidence:
    """复刻 route() 的 rank-1 / rank>1 confidence 推导顺序（阈值全参数注入）。

    rank-1 走 ``derive_confidence``（margin 规则——high 仅 rank-1 可得）；
    rank>1 走 ``score >= θ_med → medium else low``（与
    ``RepoRouterV2._deterministic_confidence`` 语义逐字一致）。
    """
    if rank <= 0:
        return derive_confidence(
            sorted_scores,
            theta_abs=theta_abs,
            theta_margin=theta_margin,
            theta_med=theta_med,
        )
    score = sorted_scores[rank] if rank < len(sorted_scores) else 0.0
    return "medium" if score >= theta_med else "low"


def _as_output(cand: ScoredCandidate, confidence: Confidence) -> dict[str, Any]:
    """重算候选 → 比对输出形状（round 口径与 ``RepoRouteCandidateV2.to_dict`` 一致）。"""
    return {
        "repo_id": cand.repo_id,
        "score": round(cand.score, 4),
        "breakdown": {k: round(v, 6) for k, v in cand.breakdown.items()},
        "confidence": confidence,
    }


def replay_route_from_snapshot(
    payload: dict[str, Any],
    *,
    theta_abs: float,
    theta_margin: float,
    theta_med: float,
) -> list[dict[str, Any]]:
    """从快照 payload 重建输入并纯函数重算候选（零网络）。

    流程：``payload["stage0"]["node_hits"]`` 还原 hit 形状 → ``aggregate_and_score``
    重算分数/排序 → Stage 1 参与（``stage1`` 无 skipped_reason）时按 payload 排列
    记录重排 + 逐候选 ``apply_llm_adjustment``（confidence hint）；未参与时按重算
    排序取记录条数 → 输出 ``[{repo_id, score, breakdown, confidence}]``。
    """
    stage0 = payload.get("stage0") or {}
    scored = aggregate_and_score(_rebuild_hits(stage0.get("node_hits") or []))
    sorted_scores = [c.score for c in scored]
    recorded = payload.get("candidates") or []
    stage1 = payload.get("stage1") or {}
    llm_participated = isinstance(stage1, dict) and not stage1.get("skipped_reason")

    def _conf(rank: int) -> Confidence:
        return _deterministic_confidence(
            sorted_scores,
            rank,
            theta_abs=theta_abs,
            theta_margin=theta_margin,
            theta_med=theta_med,
        )

    if llm_participated:
        by_id = {c.repo_id: c for c in scored}
        rank_by_id = {c.repo_id: i for i, c in enumerate(scored)}
        out: list[dict[str, Any]] = []
        for item in recorded:
            if not isinstance(item, dict):
                continue
            rid = str(item.get("repo_id", ""))
            cand = by_id.get(rid)
            if cand is None:
                continue  # 记录里出现重算不出的 repo_id：跳过，verify 侧以条数不齐拦截
            hint_raw = str(item.get("confidence", "")).lower()
            hint: Confidence | None = (
                hint_raw if hint_raw in ("high", "medium", "low") else None  # type: ignore[assignment]
            )
            out.append(_as_output(cand, apply_llm_adjustment(_conf(rank_by_id[rid]), hint)))
        return out

    # 降级/跳过路径：排列纯由重算分数导出，截取到记录条数（route() 的 top_k 截断）。
    top_n = len(recorded) if recorded else len(scored)
    return [_as_output(cand, _conf(rank)) for rank, cand in enumerate(scored[:top_n])]


def verify_snapshot_replay(
    payload: dict[str, Any],
    *,
    theta_abs: float,
    theta_margin: float,
    theta_med: float,
) -> tuple[bool, str]:
    """重算结果与 ``payload["candidates"]`` 记录逐字段比对（score 容差 1e-9）。

    Returns:
        ``(True, "")`` 一致；``(False, diff 文本)`` 不一致（逐候选逐字段列差异）。
        比对键固定为 ``repo_id/score/breakdown/confidence``（不含 repo_name）。
    """
    recomputed = replay_route_from_snapshot(
        payload, theta_abs=theta_abs, theta_margin=theta_margin, theta_med=theta_med
    )
    recorded = payload.get("candidates") or []
    diffs: list[str] = []
    if len(recomputed) != len(recorded):
        diffs.append(
            f"candidate count mismatch: recorded={len(recorded)} recomputed={len(recomputed)}"
        )
    for i, (rec, rep) in enumerate(zip(recorded, recomputed)):
        rec_id = str(rec.get("repo_id", "")) if isinstance(rec, dict) else ""
        if rec_id != rep["repo_id"]:
            diffs.append(f"[{i}] repo_id: recorded={rec_id!r} recomputed={rep['repo_id']!r}")
            continue
        rec_conf = str(rec.get("confidence", ""))
        if rec_conf != rep["confidence"]:
            diffs.append(
                f"[{i}] {rec_id} confidence: recorded={rec_conf!r} recomputed={rep['confidence']!r}"
            )
        rec_score = float(rec.get("score", 0.0) or 0.0)
        if abs(rec_score - rep["score"]) > _SCORE_TOLERANCE:
            diffs.append(
                f"[{i}] {rec_id} score: recorded={rec_score} recomputed={rep['score']}"
            )
        rec_bd = rec.get("breakdown") or {}
        rep_bd = rep["breakdown"]
        if set(rec_bd) != set(rep_bd):
            diffs.append(
                f"[{i}] {rec_id} breakdown keys: recorded={sorted(rec_bd)} recomputed={sorted(rep_bd)}"
            )
        else:
            for sig in sorted(rec_bd):
                if abs(float(rec_bd[sig]) - rep_bd[sig]) > _SCORE_TOLERANCE:
                    diffs.append(
                        f"[{i}] {rec_id} breakdown[{sig}]: "
                        f"recorded={rec_bd[sig]} recomputed={rep_bd[sig]}"
                    )
    return (not diffs, "\n".join(diffs))
