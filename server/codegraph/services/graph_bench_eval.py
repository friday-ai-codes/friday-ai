"""图查询基准评测地基：run identity、三方水位校验与 gold schema（纯函数，零 I/O）。

**为什么需要它。** Phase 133 要建立可复现、无阈值污染的 v0.22 原始基线：评测者
用固定 repository/branch/commit SHA 运行 benchmark，三方水位（索引 built_at、
gold 标注 sha、源码 checkout sha）不一致即把 run 标为 ``INVALID``，绝不产出部分
结论（BENCH-01）；gold 冻结数据集必须有可校验的分桶维度与版本化身份（BENCH-02）。
这些口径必须能脱离真实 Qdrant/embedding 在默认 ``--disable-socket`` 套件单测，
且与生产实现零漂移，故全部收敛为纯函数。

本模块**只做算术、零 I/O**：不触碰 ORM / 向量库 / 网络，不读文件。
三方水位 sha 由调用方（Plan 04 的 management command）按 ``(repository_id, branch)``
解析后注入；gold 输入为已 ``json.load`` 的 dict。

**指标口径（BENCH-04/05，Plan 03 追加）。** 每个质量指标锁定固定分母与空结果规则：
空 gold 记 ``NO_GOLD``（不计入平均，**非满分**）、无预测记 ``N/A``、impact
``seed_in_graph=False`` 记 ``SEED_MISSING``、trace ``node_not_in_graph`` 单列不进
成功率分母。分桶按 ``language × framework × entry_type``，样本不足标
``INSUFFICIENT_DATA`` 且不进 overall；聚合用 macro（按 case 平均），受保护桶单列
不被 overall 抵消。本模块只产原始分布，**不含任何回归门/目标值/容差/比对逻辑**
（阈值决策权属 Phase 140，BENCH-03）。

**防循环论证（BENCH-02 硬约束）。** resolved edge gold 来自独立 callsite 标注而
非被测 codegraph 反向导出；因此 ``edge_golds`` 的 ``callee_uid`` 非空时必须附
``evidence_file_line``（人工核验锚点），缺即拒绝。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "BUCKET_OK",
    "CALL_SHAPES",
    "ENTRY_TYPES",
    "FRAMEWORKS",
    "INSUFFICIENT_DATA",
    "LANGUAGES",
    "MIN_BUCKET_SAMPLES",
    "NODE_NOT_IN_GRAPH",
    "NO_GOLD",
    "NOT_APPLICABLE",
    "SEED_MISSING",
    "CaseOutcome",
    "GoldCase",
    "GoldDataset",
    "RunIdentity",
    "aggregate_report",
    "bucket_metrics",
    "bucket_status",
    "build_report",
    "build_run_identity",
    "evaluate_case",
    "rank_process_candidates",
    "score_edge_pr",
    "score_impact_precision",
    "score_process_recall",
    "score_symbol_recall",
    "score_trace",
    "validate_gold_case",
    "validate_gold_dataset",
    "validate_watermark",
]

# ---------------------------------------------------------------------------
# BENCH-01：run identity 五元组 + 三方水位校验
# ---------------------------------------------------------------------------

# gold 分桶维度闭集（BENCH-02/BENCH-05）：越界值一律被 schema 校验拒绝。
# framework 无显式模型字段，由标注者显式填写（无显式 framework 时填 "none"）。
LANGUAGES = ("python", "typescript", "javascript", "go")
FRAMEWORKS = ("django", "vue", "gin", "none")
ENTRY_TYPES = ("http_endpoint", "process_entry", "plain_symbol")
# call_shape 仅 resolved edge gold 需要，记录独立 callsite 标注的调用形态。
CALL_SHAPES = ("direct", "member", "import_alias", "receiver", "from_import")


@dataclass
class RunIdentity:
    """一次 benchmark run 的唯一评测身份（BENCH-01）。

    五元组 ``(repository, branch, commit_sha, index_key, gold_version)`` 保证全部
    证据（Symbol/Process/调用边/``file:line``/impact）强制来自同一 commit SHA。
    ``index_key_source`` 记录 index_key 的取值来源（当前恒为
    ``last_indexed_commit_sha``），供 Phase 140 演进为复合键时平滑升级。
    """

    repository: str
    branch: str
    commit_sha: str
    index_key: str
    gold_version: str
    index_key_source: str = "last_indexed_commit_sha"

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "branch": self.branch,
            "commit_sha": self.commit_sha,
            "index_key": self.index_key,
            "gold_version": self.gold_version,
            "index_key_source": self.index_key_source,
        }


def build_run_identity(
    *,
    repository: str,
    branch: str,
    commit_sha: str,
    index_key: str,
    gold_version: str,
    index_key_source: str = "last_indexed_commit_sha",
) -> RunIdentity:
    """装配 run identity。

    ``branch`` 允许为空串（"" = base 分支，与 ``Symbol.branch_name`` 同口径）。
    ``repository`` / ``gold_version`` 为空串则身份不完整，raise ``ValueError``。
    """
    if not repository:
        raise ValueError("repository 为必填，run identity 不能为空")
    if not gold_version:
        raise ValueError("gold_version 为必填，run identity 不能为空")
    return RunIdentity(
        repository=repository,
        branch=branch,
        commit_sha=commit_sha,
        index_key=index_key,
        gold_version=gold_version,
        index_key_source=index_key_source,
    )


def validate_watermark(
    *,
    index_built_at_sha: str | None,
    gold_annotated_at_sha: str | None,
    source_checkout_sha: str | None,
    process_built_at_sha: str | None = None,
) -> str:
    """三方水位一致性校验（fail-closed → "OK" 或 "INVALID"）。

    规则：三个必填 sha 任一为空/None → ``INVALID``；三者集合大小 != 1 → ``INVALID``；
    可选第四参 ``process_built_at_sha`` 传入（非 None）且与公共 sha 不等 → ``INVALID``
    （防 ProcessTrace/SymbolCommunity 投影漂移），不传则不参与判定。仅当三者非空且
    全相等才返回 ``OK``——水位不一致绝不产出部分结论（BENCH-01）。
    """
    if not (index_built_at_sha and gold_annotated_at_sha and source_checkout_sha):
        return "INVALID"
    if len({index_built_at_sha, gold_annotated_at_sha, source_checkout_sha}) != 1:
        return "INVALID"
    if process_built_at_sha is not None and process_built_at_sha != index_built_at_sha:
        return "INVALID"
    return "OK"


# ---------------------------------------------------------------------------
# BENCH-02：gold 冻结数据集 schema 与校验
# ---------------------------------------------------------------------------

# 三切分（baseline 只用 dev + locked_test，holdout 留最终验收）。
_REQUIRED_SPLITS = ("dev", "locked_test", "holdout")
# manifest 顶层必填键。
_REQUIRED_MANIFEST_KEYS = ("gold_version", "annotated_at_sha", "splits")


@dataclass
class GoldCase:
    """一条 gold 标注 case（分桶维度必填，独立于被测图）。"""

    case_id: str
    split: str
    query: str
    language: str
    framework: str
    entry_type: str
    expected_symbols: list[dict[str, Any]] = field(default_factory=list)
    expected_processes: list[dict[str, Any]] = field(default_factory=list)
    edge_golds: list[dict[str, Any]] = field(default_factory=list)
    trace_golds: list[dict[str, Any]] = field(default_factory=list)
    impact_golds: list[dict[str, Any]] = field(default_factory=list)
    protected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "split": self.split,
            "query": self.query,
            "language": self.language,
            "framework": self.framework,
            "entry_type": self.entry_type,
            "expected_symbols": list(self.expected_symbols),
            "expected_processes": list(self.expected_processes),
            "edge_golds": list(self.edge_golds),
            "trace_golds": list(self.trace_golds),
            "impact_golds": list(self.impact_golds),
            "protected": self.protected,
        }


@dataclass
class GoldDataset:
    """一个版本化的冻结 gold 数据集。"""

    gold_version: str
    annotated_at_sha: str
    repository: str
    branch: str
    splits: dict[str, Any] = field(default_factory=dict)
    cases: list[GoldCase] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "gold_version": self.gold_version,
            "annotated_at_sha": self.annotated_at_sha,
            "repository": self.repository,
            "branch": self.branch,
            "splits": dict(self.splits),
            "cases": [c.to_dict() for c in self.cases],
        }


def _require_enum(case_id: str, field_name: str, value: Any, closed_set: tuple[str, ...]) -> str:
    """校验某字段存在且 ∈ 闭集，返回其值；缺失或越界 raise ``ValueError``。"""
    if value is None:
        raise ValueError(f"gold case {case_id} 缺少必填分桶维度 {field_name}")
    if value not in closed_set:
        raise ValueError(
            f"gold case {case_id} 的 {field_name}={value!r} 越出闭集 {closed_set}"
        )
    return value


def validate_gold_case(case: dict[str, Any]) -> GoldCase:
    """校验单条 gold case，返回 :class:`GoldCase`；不合法 raise ``ValueError``。

    必填：``query``（非空白）、``language``/``framework``/``entry_type``（存在且 ∈
    闭集）。``edge_golds`` 每条 ``call_shape`` ∈ 闭集，且 ``callee_uid`` 非空时
    ``evidence_file_line`` 必填（独立 callsite 标注锚点，防反导）。``expected_*``
    缺省给空列表；``protected`` 缺省 False。错误消息含 ``case_id`` 与字段名。
    """
    case_id = str(case.get("case_id") or "<unknown>")

    query = case.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError(f"gold case {case_id} 缺少必填 query（或 query 为空白）")

    language = _require_enum(case_id, "language", case.get("language"), LANGUAGES)
    framework = _require_enum(case_id, "framework", case.get("framework"), FRAMEWORKS)
    entry_type = _require_enum(case_id, "entry_type", case.get("entry_type"), ENTRY_TYPES)

    edge_golds = case.get("edge_golds") or []
    for i, edge in enumerate(edge_golds):
        call_shape = edge.get("call_shape")
        if call_shape is not None and call_shape not in CALL_SHAPES:
            raise ValueError(
                f"gold case {case_id} 的 edge_golds[{i}].call_shape={call_shape!r} "
                f"越出闭集 {CALL_SHAPES}"
            )
        if edge.get("callee_uid") and not edge.get("evidence_file_line"):
            raise ValueError(
                f"gold case {case_id} 的 edge_golds[{i}] 有 callee_uid 但缺 "
                "evidence_file_line（独立 callsite 标注锚点，防反导）"
            )

    return GoldCase(
        case_id=str(case.get("case_id") or ""),
        split=str(case.get("split") or ""),
        query=query,
        language=language,
        framework=framework,
        entry_type=entry_type,
        expected_symbols=list(case.get("expected_symbols") or []),
        expected_processes=list(case.get("expected_processes") or []),
        edge_golds=list(edge_golds),
        trace_golds=list(case.get("trace_golds") or []),
        impact_golds=list(case.get("impact_golds") or []),
        protected=bool(case.get("protected", False)),
    )


def validate_gold_dataset(manifest: dict[str, Any], cases: list[dict[str, Any]]) -> GoldDataset:
    """校验 gold 数据集 manifest 与全部 case，返回 :class:`GoldDataset`。

    manifest 必填 ``gold_version``/``annotated_at_sha``/``splits``，且 ``splits`` 须
    含 ``dev``/``locked_test``/``holdout`` 三键；逐条 ``validate_gold_case``。缺失
    raise ``ValueError`` 并指明缺失键。
    """
    for key in _REQUIRED_MANIFEST_KEYS:
        if not manifest.get(key):
            raise ValueError(f"gold manifest 缺少必填键 {key}")

    splits = manifest.get("splits") or {}
    for split in _REQUIRED_SPLITS:
        if split not in splits:
            raise ValueError(f"gold manifest 的 splits 缺少必填切分 {split}")

    validated = [validate_gold_case(c) for c in cases]
    return GoldDataset(
        gold_version=str(manifest["gold_version"]),
        annotated_at_sha=str(manifest["annotated_at_sha"]),
        repository=str(manifest.get("repository") or ""),
        branch=str(manifest.get("branch") or ""),
        splits=dict(splits),
        cases=validated,
    )


# ---------------------------------------------------------------------------
# BENCH-04：逐 case 指标 scorer 与空结果规则
# ---------------------------------------------------------------------------

# 空结果标记（报告中显式单列，绝不静默并入分母或记满分）。
# 统一原则（沿袭 PITFALLS B0）：空 gold ≠ 满分；无预测 ≠ 满分；``found=False`` ≠ 空
# 数组；``seed_in_graph=False`` 与「无影响」必须分开。
NO_GOLD = "NO_GOLD"  # gold 为空 → 该 case 此指标不计入平均（非满分）
NOT_APPLICABLE = "N/A"  # 无预测 → 不计入平均（非满分）
SEED_MISSING = "SEED_MISSING"  # impact seed_in_graph=False → 单列，不计 precision
NODE_NOT_IN_GRAPH = "node_not_in_graph"  # trace 端点不在图 → 单列，不计成功率分母
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"  # 分桶样本不足 → 不进 overall
BUCKET_OK = "OK"  # 分桶样本充足

# 稀疏桶样本下限（研究中 Assumption A2，可配置）：n 小于此值的桶标
# ``INSUFFICIENT_DATA``，单列展示且不进 overall（防大桶主导掩盖小桶退化）。
MIN_BUCKET_SAMPLES = 3

# 报告与聚合保留的小数位。逐 case / 逐桶 / overall 统一按同精度取整，避免不同层
# 的舍入口径不一致（本阶段无回归门，仅为展示一致性）。
_BASELINE_PRECISION = 4


def score_symbol_recall(
    expected_uids: list[str], predicted_top_k_uids: list[str]
) -> float | str:
    """NL→Symbol Recall@k：``|expected ∩ predicted| / len(expected)``。

    空结果规则：``expected`` 为空 → ``NO_GOLD``（分母 0，不计入平均，**不记满分**）；
    ``predicted`` 空且 gold 非空 → ``0.0``。命中按 uid 集合精确匹配。
    """
    if not expected_uids:
        return NO_GOLD
    got = set(predicted_top_k_uids)
    return sum(1 for e in expected_uids if e in got) / len(expected_uids)


def rank_process_candidates(
    retrieved_uids: list[str], candidate_processes: list[dict[str, Any]]
) -> list[str]:
    """把检索结果映射到 Process 候选并按确定性规则排序，返回 ``process_key`` 列表。

    排序键：``(与 retrieved 交集数降序, process_key 升序决胜)``——交集数相同按
    ``process_key`` 字典序保证跨 run 可复现。每个 candidate 含 ``process_key`` 与
    ``step_symbol_uids``。这是 baseline 的**测量映射**（把检索结果映射到 Process
    候选以记分），不是生产 Process 检索器（属 Phase 136）。
    """
    retrieved = set(retrieved_uids)

    def _overlap(candidate: dict[str, Any]) -> int:
        steps = candidate.get("step_symbol_uids") or []
        return len(retrieved & set(steps))

    ordered = sorted(
        candidate_processes,
        key=lambda c: (-_overlap(c), str(c.get("process_key") or "")),
    )
    return [str(c.get("process_key") or "") for c in ordered]


def score_process_recall(
    expected_keys: list[str], predicted_top3_keys: list[str]
) -> float | str:
    """NL→Process Recall@3：``|expected ∩ predicted| / len(expected)``。

    命中**仅以 ``process_key`` 精确匹配**计（禁名称模糊命中——名称相近但 key 不同
    不算命中）。空结果规则同 symbol recall：gold 空 → ``NO_GOLD``。
    """
    if not expected_keys:
        return NO_GOLD
    got = set(predicted_top3_keys)
    return sum(1 for e in expected_keys if e in got) / len(expected_keys)


def score_edge_pr(
    edge_golds: list[dict[str, Any]], predicted_edges: list[dict[str, Any]]
) -> dict[str, float | str]:
    """resolved edge precision/recall，以 ``(caller_uid, callee_uid)`` 二元组判命中。

    分母锁定：precision 分母 = 预测边数；recall 分母 = gold 边数。
    空结果规则：无预测边 → ``precision=NOT_APPLICABLE``（非满分）；gold 空 →
    ``recall=NO_GOLD``。返回 ``{"precision": ..., "recall": ...}``。
    """
    gold_pairs = {(g.get("caller_uid"), g.get("callee_uid")) for g in edge_golds}
    pred_pairs = {(p.get("caller_uid"), p.get("callee_uid")) for p in predicted_edges}
    hits = len(pred_pairs & gold_pairs)
    precision: float | str = NOT_APPLICABLE if not pred_pairs else hits / len(pred_pairs)
    recall: float | str = NO_GOLD if not gold_pairs else hits / len(gold_pairs)
    return {"precision": precision, "recall": recall}


def score_impact_precision(
    expected_affected: list[str],
    predicted_affected: list[str],
    *,
    seed_in_graph: bool,
) -> float | str:
    """impact precision：``|expected ∩ predicted| / len(predicted)``（分母 = 预测受影响数）。

    空结果规则（顺序敏感）：``seed_in_graph=False`` → ``SEED_MISSING``（单列，不计
    precision）；``predicted`` 空 → ``NOT_APPLICABLE``；``expected`` 空 → ``NO_GOLD``。
    """
    if not seed_in_graph:
        return SEED_MISSING
    if not predicted_affected:
        return NOT_APPLICABLE
    if not expected_affected:
        return NO_GOLD
    got = set(predicted_affected)
    return sum(1 for e in expected_affected if e in got) / len(predicted_affected)


def _trace_path_matches(gold: dict[str, Any], result: dict[str, Any]) -> bool:
    """判定 trace 命中的路径是否与 gold 一致（供区分「成功」与「错误路径」）。

    gold 可附 ``expected_path``（uid 列表）做精确比对；缺省则退化为端点比对——
    若 result 提供 ``path``，须以 gold 的 ``source_uid``/``target_uid`` 为首尾；
    两者皆无路径细节可比时，``found`` 即视为一致（无从判错）。
    """
    expected_path = gold.get("expected_path")
    path = result.get("path")
    if expected_path is not None:
        return list(path or []) == list(expected_path)
    if path:
        return path[0] == gold.get("source_uid") and path[-1] == gold.get("target_uid")
    return True


def score_trace(
    trace_golds: list[dict[str, Any]], trace_results: list[dict[str, Any]]
) -> dict[str, Any]:
    """trace 三态折算：``found`` / ``no_path`` / ``node_not_in_graph``。

    遍历每条 gold 查询对应的结果（按下标配对）：

    - ``found=True`` 且路径与 gold 一致 → 成功；
    - ``found=True`` 但路径不一致 → 错误路径（计入 ``error_path_rate``）；
    - ``reason=="no_path"`` → 失败路径（计入分母，既非成功也非错误路径）；
    - ``reason=="node_not_in_graph"`` → 计入 ``node_not_in_graph_count``，**不进分母**。

    分母 = 在图查询数（排除 ``node_not_in_graph``）。无可量测查询（分母 0）时
    ``success_rate``/``error_path_rate`` 记 ``NO_GOLD``。
    """
    success = 0
    error_path = 0
    node_not_in_graph = 0
    denominator = 0
    for gold, result in zip(trace_golds, trace_results, strict=False):
        if result.get("reason") == NODE_NOT_IN_GRAPH:
            node_not_in_graph += 1
            continue
        denominator += 1
        if result.get("found"):
            if _trace_path_matches(gold, result):
                success += 1
            else:
                error_path += 1
        # found=False 且 reason=no_path → 失败路径：仅进分母，不计成功/错误。

    if denominator == 0:
        success_rate: float | str = NO_GOLD
        error_path_rate: float | str = NO_GOLD
    else:
        success_rate = success / denominator
        error_path_rate = error_path / denominator
    return {
        "success_rate": success_rate,
        "error_path_rate": error_path_rate,
        "node_not_in_graph_count": node_not_in_graph,
        "denominator": denominator,
    }


# ---------------------------------------------------------------------------
# BENCH-04：arrival set → CaseOutcome 折算
# ---------------------------------------------------------------------------


def _round_metric(value: float | str) -> float | str:
    """float 按 ``_BASELINE_PRECISION`` 取整；str 空结果标记原样返回。"""
    return round(value, _BASELINE_PRECISION) if isinstance(value, float) else value


@dataclass
class CaseOutcome:
    """单条 case 的折算结果（进报告 JSON）。

    质量指标字段（``symbol_recall`` … ``trace_error_path_rate``）允许为 float 或
    str 空结果标记（``NO_GOLD``/``N/A``/``SEED_MISSING``）；``error`` 非空时这些
    字段置空字符串（单 case 容错，不中断其它 case 折算）。``cold_ms``/``warm_ms``/
    ``tokens`` 仅记录，不参与质量聚合。
    """

    case_id: str
    split: str
    language: str
    framework: str
    entry_type: str
    protected: bool = False
    symbol_recall: float | str = ""
    process_recall: float | str = ""
    edge_precision: float | str = ""
    edge_recall: float | str = ""
    impact_precision: float | str = ""
    trace_success_rate: float | str = ""
    trace_error_path_rate: float | str = ""
    trace_node_not_in_graph_count: int = 0
    cold_ms: int = 0
    warm_ms: int = 0
    tokens: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "split": self.split,
            "language": self.language,
            "framework": self.framework,
            "entry_type": self.entry_type,
            "protected": self.protected,
            "symbol_recall": _round_metric(self.symbol_recall),
            "process_recall": _round_metric(self.process_recall),
            "edge_precision": _round_metric(self.edge_precision),
            "edge_recall": _round_metric(self.edge_recall),
            "impact_precision": _round_metric(self.impact_precision),
            "trace_success_rate": _round_metric(self.trace_success_rate),
            "trace_error_path_rate": _round_metric(self.trace_error_path_rate),
            "trace_node_not_in_graph_count": self.trace_node_not_in_graph_count,
            "cold_ms": self.cold_ms,
            "warm_ms": self.warm_ms,
            "tokens": self.tokens,
            "error": self.error,
        }


def evaluate_case(
    *,
    gold: GoldCase,
    predicted_symbol_uids: list[str],
    candidate_processes: list[dict[str, Any]],
    predicted_edges: list[dict[str, Any]],
    impact_result: dict[str, Any],
    trace_results: list[dict[str, Any]],
    cold_ms: int = 0,
    warm_ms: int = 0,
    tokens: int = 0,
    error: str = "",
) -> CaseOutcome:
    """把某 case 的 arrival set（被测能力输出）折算成 :class:`CaseOutcome`。

    各指标调用上文 scorer：symbol 用 ``predicted_symbol_uids[:5]``；process 用
    ``rank_process_candidates(...)[:3]``；edge 用 ``score_edge_pr``；impact 用
    ``gold.impact_golds`` 首个的 ``expected_affected_uids`` 与 ``impact_result`` 的
    受影响 uid 列表（``seed_in_graph`` 缺省 True）；trace 用 ``score_trace``。

    ``error`` 非空时各质量指标置空字符串但仍返回正常 :class:`CaseOutcome`（沿袭
    recall eval 的单 case 容错：一条 case 出错不中断其它 case 折算）。
    """
    dims = {
        "case_id": gold.case_id,
        "split": gold.split,
        "language": gold.language,
        "framework": gold.framework,
        "entry_type": gold.entry_type,
        "protected": gold.protected,
        "cold_ms": cold_ms,
        "warm_ms": warm_ms,
        "tokens": tokens,
        "error": error,
    }
    if error:
        return CaseOutcome(**dims)  # type: ignore[arg-type]

    symbol_recall = score_symbol_recall(
        [str(s.get("uid") or "") for s in gold.expected_symbols],
        list(predicted_symbol_uids)[:5],
    )
    process_recall = score_process_recall(
        [str(p.get("process_key") or "") for p in gold.expected_processes],
        rank_process_candidates(list(predicted_symbol_uids), candidate_processes)[:3],
    )
    edge = score_edge_pr(gold.edge_golds, predicted_edges)

    impact_expected: list[str] = []
    if gold.impact_golds:
        impact_expected = list(gold.impact_golds[0].get("expected_affected_uids") or [])
    impact_precision = score_impact_precision(
        impact_expected,
        list(impact_result.get("affected_uids") or []),
        seed_in_graph=bool(impact_result.get("seed_in_graph", True)),
    )

    trace = score_trace(gold.trace_golds, trace_results)
    return CaseOutcome(
        **dims,  # type: ignore[arg-type]
        symbol_recall=symbol_recall,
        process_recall=process_recall,
        edge_precision=edge["precision"],
        edge_recall=edge["recall"],
        impact_precision=impact_precision,
        trace_success_rate=trace["success_rate"],
        trace_error_path_rate=trace["error_path_rate"],
        trace_node_not_in_graph_count=trace["node_not_in_graph_count"],
    )


# ---------------------------------------------------------------------------
# BENCH-05：分桶 + INSUFFICIENT_DATA + macro 聚合；BENCH-03：无阈值报告
# ---------------------------------------------------------------------------

# 参与逐桶 / overall macro 平均的质量指标（trace_node_not_in_graph_count 为计数、
# cold/warm/tokens 仅记录，均不参与平均）。
_QUALITY_METRICS = (
    "symbol_recall",
    "process_recall",
    "edge_precision",
    "edge_recall",
    "impact_precision",
    "trace_success_rate",
    "trace_error_path_rate",
)


def _macro(values: list[float | str]) -> float | str:
    """按 case 取平均（macro）：只对数值型 case 求平均，跳过空结果标记。

    分母 = 该指标数值 case 数。无可平均数值时记 ``NO_GOLD``（该桶此指标无可量测
    数据，不记满分）。用 macro 而非 micro（按样本合并）：case 之间 gold 数量差异
    大，micro 会让大桶主导、掩盖小桶整体退化（PITFALLS Pitfall 3）。
    """
    nums = [v for v in values if isinstance(v, float)]
    if not nums:
        return NO_GOLD
    return round(sum(nums) / len(nums), _BASELINE_PRECISION)


def bucket_status(n: int, min_samples: int = MIN_BUCKET_SAMPLES) -> str:
    """分桶状态：``n >= MIN_BUCKET_SAMPLES`` → ``OK``，否则 ``INSUFFICIENT_DATA``。"""
    return BUCKET_OK if n >= max(min_samples, 1) else INSUFFICIENT_DATA


def bucket_metrics(
    cases: list[CaseOutcome], min_samples: int = MIN_BUCKET_SAMPLES
) -> list[dict[str, Any]]:
    """按 ``(language, framework, entry_type)`` 分桶并算各质量指标的 macro 平均。

    每桶记录 ``key``/``n``/``status``/``has_protected``/``metrics``。``status`` 由
    :func:`bucket_status` 判定；``metrics`` 仅对数值型 case 求平均（跳过
    ``NO_GOLD``/``N/A``/``SEED_MISSING`` 标记）。
    """
    groups: dict[tuple[str, str, str], list[CaseOutcome]] = {}
    for case in cases:
        key = (case.language, case.framework, case.entry_type)
        groups.setdefault(key, []).append(case)

    buckets: list[dict[str, Any]] = []
    for (language, framework, entry_type), members in sorted(groups.items()):
        buckets.append(
            {
                "key": {
                    "language": language,
                    "framework": framework,
                    "entry_type": entry_type,
                },
                "n": len(members),
                "status": bucket_status(len(members), min_samples),
                "has_protected": any(m.protected for m in members),
                "metrics": {
                    metric: _macro([getattr(m, metric) for m in members])
                    for metric in _QUALITY_METRICS
                },
            }
        )
    return buckets


def aggregate_report(
    cases: list[CaseOutcome], min_samples: int = MIN_BUCKET_SAMPLES
) -> dict[str, Any]:
    """聚合逐桶结果为 overall + 稀疏桶 / 受保护桶单列。

    ``overall`` 只聚合 ``status==OK`` 且**非受保护**的桶（macro：按 case 平均，非
    按样本合并 micro）。``INSUFFICIENT_DATA`` 稀疏桶与受保护桶分别单列——稀疏桶
    数据不足不参与结论；受保护桶的退化不得被 overall 的提升抵消（PITFALLS
    Pitfall 3）。
    """
    buckets = bucket_metrics(cases, min_samples)
    ok_keys = {
        (b["key"]["language"], b["key"]["framework"], b["key"]["entry_type"])
        for b in buckets
        if b["status"] == BUCKET_OK and not b["has_protected"]
    }
    overall_cases = [
        c for c in cases if (c.language, c.framework, c.entry_type) in ok_keys
    ]
    return {
        "overall": {
            metric: _macro([getattr(c, metric) for c in overall_cases])
            for metric in _QUALITY_METRICS
        },
        "per_bucket": buckets,
        "insufficient_buckets": [b for b in buckets if b["status"] == INSUFFICIENT_DATA],
        "protected_buckets": [b for b in buckets if b["has_protected"]],
        "total_cases": len(cases),
    }


def build_report(
    *,
    identity: RunIdentity,
    watermark: str,
    split: str,
    cases: list[CaseOutcome],
    min_samples: int = MIN_BUCKET_SAMPLES,
) -> dict[str, Any]:
    """装配最终**无阈值**原始报告（BENCH-03）。

    只含原始值与空结果标记：echo 评测身份五元组与水位状态、逐 case、逐桶、
    overall、受保护桶 / 稀疏桶单列，并附空结果规则图例。本报告**不引入任何回归
    门/目标值/容差/比对字段**——阈值决策权属 Phase 140 独立评审。
    """
    aggregated = aggregate_report(cases, min_samples)
    return {
        "identity": identity.to_dict(),
        "watermark": watermark,
        "split": split,
        "per_case": [c.to_dict() for c in cases],
        "per_bucket": aggregated["per_bucket"],
        "overall": aggregated["overall"],
        "protected_buckets": aggregated["protected_buckets"],
        "insufficient_buckets": aggregated["insufficient_buckets"],
        "total_cases": aggregated["total_cases"],
        "legend": {
            NO_GOLD: "gold 为空：该 case 此指标不计入平均（非满分）",
            NOT_APPLICABLE: "无预测：不计入平均（非满分）",
            SEED_MISSING: "impact seed_in_graph=False：单列，不计 precision",
            NODE_NOT_IN_GRAPH: "trace 端点不在图：单列，不计成功率分母",
            INSUFFICIENT_DATA: "分桶样本不足 MIN_BUCKET_SAMPLES：单列，不进 overall",
        },
    }
