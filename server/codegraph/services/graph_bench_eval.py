"""图查询基准评测地基：run identity、三方水位校验与 gold schema（纯函数，零 I/O）。

**为什么需要它。** Phase 133 要建立可复现、无阈值污染的 v0.22 原始基线：评测者
用固定 repository/branch/commit SHA 运行 benchmark，三方水位（索引 built_at、
gold 标注 sha、源码 checkout sha）不一致即把 run 标为 ``INVALID``，绝不产出部分
结论（BENCH-01）；gold 冻结数据集必须有可校验的分桶维度与版本化身份（BENCH-02）。
这些口径必须能脱离真实 Qdrant/embedding 在默认 ``--disable-socket`` 套件单测，
且与生产实现零漂移，故全部收敛为纯函数。

本模块**只做算术、零 I/O**：不触碰 ORM / 向量库 / 网络，不读文件。
三方水位 sha 由调用方（Plan 04 的 management command）按 ``(repository_id, branch)``
解析后注入；gold 输入为已 ``json.load`` 的 dict。指标折算/分桶/聚合由 Plan 03
追加到同一文件。

**防循环论证（BENCH-02 硬约束）。** resolved edge gold 来自独立 callsite 标注而
非被测 codegraph 反向导出；因此 ``edge_golds`` 的 ``callee_uid`` 非空时必须附
``evidence_file_line``（人工核验锚点），缺即拒绝。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "CALL_SHAPES",
    "ENTRY_TYPES",
    "FRAMEWORKS",
    "LANGUAGES",
    "GoldCase",
    "GoldDataset",
    "RunIdentity",
    "build_run_identity",
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
