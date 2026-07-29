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

双版本快照契约（Phase 106，ROUTE-06 × research §6.2-9「版本不同即不可比」）：
新格式快照（106-06 起）携带 ``weight_config``（生效权重/常数全值，含 n_bar）+
``repo_meta``（**全部分桶仓**的元数据——dense 余弦/DB 聚合/T2 匹配分等外部
I/O 产物记录为数据，回放消费数据，与 Stage 1 排列记录同一模式；只存候选仓会
让非候选仓在回放时拿到缺失红利并污染比对，见 BL-02）+ ``stage0.scored_at``
（活跃度衰减时间锚点）——回放全部从快照读取，不依赖回放时的 SystemSetting /
默认常量 / 系统时钟（快照自包含）。105 旧快照（缺 weight_config 节，
``versions.weight_set_version == "phase105-v1"``）回退 legacy 三信号路径
（``aggregate_and_score(hits)`` 默认 PHASE105_WEIGHTS）按当时版本重算，
diff 输出标注 ``LEGACY_SNAPSHOT_NOTE``——不做跨版本换算或比较；
weight_config 节残缺/类型错误一律按 legacy 容错，不抛（T-106-18）。
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

__all__ = [
    "LEGACY_SNAPSHOT_NOTE",
    "ReplayResult",
    "replay_route_from_snapshot",
    "verify_snapshot_replay",
]

# score 比对容差：记录值与重算值经过同一 round（score 4 位 / breakdown 6 位，
# 与 RepoRouteCandidateV2.to_dict 一致），理论差为 0，容差仅防序列化噪声。
_SCORE_TOLERANCE = 1e-9

_COMPARE_KEYS = ("repo_id", "score", "breakdown", "confidence")

# 旧快照回放标注（research §6.2-9）：版本不同即不可比——legacy 快照按当时
# 版本（phase105-v1 三信号权重）重算比对，diff 头部加本行澄清比对口径。
LEGACY_SNAPSHOT_NOTE = "旧版本快照（phase105-v1），按当时版本比对"

# legacy 快照回放采用的版本标注值（105 快照 versions 位记录的即该字符串）。
_LEGACY_WEIGHT_SET_VERSION = "phase105-v1"


class ReplayResult(list):
    """回放候选列表 + 本次回放的版本元信息。

    向后兼容契约：仍是 ``list[dict]``（迭代/索引/len/== 语义不变，比对键
    repo_id/score/breakdown/confidence 不受影响），额外携带：

    - ``weight_set_version``：本次回放采用的权重版本——新格式取快照
      ``weight_config.weight_set_version``；旧格式恒为 ``"phase105-v1"``。
    - ``legacy_snapshot``：True 表示 105 旧快照回退路径（按当时版本比对）。
    - ``self_contained``：新格式快照的 ``repo_meta`` 是否覆盖全部分桶仓
      （BL-02）。False 表示快照不自包含（BL-02 修复前录制的快照）：回放已
      裁剪掉缺 meta 的仓以保持标尺对称，但结果不可用于「同结果」判定。
    - ``missing_meta_repo_ids``：被裁剪掉的分桶仓 id（自包含时为空列表）。
    """

    def __init__(
        self,
        candidates: list[dict[str, Any]] | None = None,
        *,
        weight_set_version: str = "",
        legacy_snapshot: bool = False,
        self_contained: bool = True,
        missing_meta_repo_ids: list[str] | None = None,
    ) -> None:
        super().__init__(candidates or [])
        self.weight_set_version = weight_set_version
        self.legacy_snapshot = legacy_snapshot
        self.self_contained = self_contained
        self.missing_meta_repo_ids = list(missing_meta_repo_ids or [])


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
) -> ReplayResult:
    """从快照 payload 重建输入并纯函数重算候选（零网络）。

    版本分流（双版本契约见模块 docstring）：

    - **新格式**（``payload["weight_config"]`` 存在且 weights 为非空 dict）：
      权重/常数（含快照当时生效的 n_bar）/repo_meta/scored_at 全部从快照读取
      注入 ``aggregate_and_score`` 六信号新路径——回放不依赖当时的 SystemSetting。
    - **legacy**（缺 weight_config 节的 105 快照，或节残缺/类型错误，T-106-18）：
      ``aggregate_and_score(hits)`` 默认三信号路径（PHASE105_WEIGHTS）重算，
      不抛异常；结果标注 ``legacy_snapshot=True``。

    流程：``payload["stage0"]["node_hits"]`` 还原 hit 形状 → 按版本重算分数/排序
    → Stage 1 参与（``stage1`` 无 skipped_reason）时按 payload 排列记录重排 +
    逐候选 ``apply_llm_adjustment``（confidence hint）；未参与时按重算排序取
    记录条数 → 输出 ``ReplayResult``（元素 ``{repo_id, score, breakdown,
    confidence}`` + ``weight_set_version``/``legacy_snapshot`` 元信息）。

    自包含性（BL-02）：新格式快照必须为**全部分桶仓**存 ``repo_meta``——106-06
    起录制端如此。对 BL-02 修复前录制的旧快照（只存候选仓），回放会把缺 meta
    的仓从 hits 中裁掉以保持标尺对称（否则这些仓同时拿到 S_top 口径漂移 +
    breadth denom=1.0 + facet 全缺三重缺失红利，分数虚高挤进比对窗口），并置
    ``self_contained=False`` + ``missing_meta_repo_ids``——该情形下
    :func:`verify_snapshot_replay` 直接判「快照不自包含」，不再输出误导性的
    字段差异。注意裁剪不能完全还原录制口径（query-local ``rrf_max`` 可能由
    被裁掉的仓贡献），所以是诊断降级而非等价回放。
    """
    stage0 = payload.get("stage0") or {}
    hits = _rebuild_hits(stage0.get("node_hits") or [])

    weight_config = payload.get("weight_config")
    wc = weight_config if isinstance(weight_config, dict) else {}
    wc_weights = wc.get("weights")
    legacy = not (isinstance(wc_weights, dict) and wc_weights)
    self_contained = True
    missing_meta: list[str] = []
    if legacy:
        # 105 旧快照 / weight_config 残缺：legacy 三信号路径按当时版本重算（不抛）。
        scored = aggregate_and_score(hits)
        weight_set_version = _LEGACY_WEIGHT_SET_VERSION
    else:
        repo_meta_raw = payload.get("repo_meta")
        repo_meta = repo_meta_raw if isinstance(repo_meta_raw, dict) else {}
        bucket_rids = {str((h.get("payload") or {}).get("repository_id", "")) for h in hits} - {""}
        missing_meta = sorted(bucket_rids - set(repo_meta))
        if missing_meta:
            self_contained = False
            hits = [
                h
                for h in hits
                if str((h.get("payload") or {}).get("repository_id", "")) in repo_meta
            ]
        scored = aggregate_and_score(
            hits,
            weights=wc_weights,
            repo_meta=repo_meta,
            constants=wc.get("constants"),
            now=stage0.get("scored_at"),
        )
        weight_set_version = str(wc.get("weight_set_version") or "")

    def _wrap(items: list[dict[str, Any]]) -> ReplayResult:
        return ReplayResult(
            items,
            weight_set_version=weight_set_version,
            legacy_snapshot=legacy,
            self_contained=self_contained,
            missing_meta_repo_ids=missing_meta,
        )

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
        return _wrap(out)

    # 降级/跳过路径：排列纯由重算分数导出，截取到记录条数（route() 的 top_k 截断）。
    top_n = len(recorded) if recorded else len(scored)
    return _wrap([_as_output(cand, _conf(rank)) for rank, cand in enumerate(scored[:top_n])])


def verify_snapshot_replay(
    payload: dict[str, Any],
    *,
    theta_abs: float,
    theta_margin: float,
    theta_med: float,
) -> tuple[bool, str]:
    """重算结果与 ``payload["candidates"]`` 记录逐字段比对（score 容差 1e-9）。

    比对键与容差对新旧快照一致（breakdown 键集合比对天然覆盖新信号键）；
    legacy 快照（105 旧格式回退路径）存在差异时，diff 文本头部加
    ``LEGACY_SNAPSHOT_NOTE`` 行澄清比对口径——版本不同即不可比（research §6.2-9）。

    前置断言（BL-02）：新格式快照的 ``repo_meta`` 必须覆盖全部分桶仓，否则
    直接判「快照不自包含」并列出缺 meta 的仓——而不是把裁剪/漂移后的分数当成
    字段差异报出来（后者会让 replay 这个审计工具稳定误报，信任度归零）。

    Returns:
        ``(True, "")`` 一致；``(False, diff 文本)`` 不一致（逐候选逐字段列差异）。
        比对键固定为 ``repo_id/score/breakdown/confidence``（不含 repo_name）。
    """
    recomputed = replay_route_from_snapshot(
        payload, theta_abs=theta_abs, theta_margin=theta_margin, theta_med=theta_med
    )
    if not recomputed.self_contained:
        return (
            False,
            "快照不自包含：分桶仓缺 repo_meta "
            f"{recomputed.missing_meta_repo_ids}——该快照录制于 BL-02 修复前"
            "（只存候选仓 meta），无法据此判定「回放同结果」；请用修复后录制的快照比对",
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
            # 位次不一致时补全「重算后的完整名次」——只报位置差异无法判断是
            # 单仓漂移还是整体重排（按位置盲比的诊断盲区）。
            diffs.append(
                f"[{i}] repo_id: recorded={rec_id!r} recomputed={rep['repo_id']!r}"
                f"；重算名次={[c['repo_id'] for c in recomputed]}"
            )
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
    if diffs and recomputed.legacy_snapshot:
        diffs.insert(0, LEGACY_SNAPSHOT_NOTE)
    return (not diffs, "\n".join(diffs))
