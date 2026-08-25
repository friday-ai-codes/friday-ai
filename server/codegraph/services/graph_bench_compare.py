"""Threshold policy 与严格 paired benchmark comparator（纯函数、零 I/O）。

policy 由调用方以原始 bytes 注入，内容 hash 也基于这些 bytes。比较器只消费
``graph_bench_eval`` 的报告，不重跑 scorer，不接触 ORM、网络或文件系统。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from dataclasses import dataclass, field
from typing import Any

POLICY_SCHEMA_VERSION = "graph-bench-threshold-policy/v1"
VERDICTS = ("INVALID", "FAIL", "INSUFFICIENT_DATA", "PASS")
DIRECTIONS = ("higher_is_better", "lower_is_better")
MARKERS = frozenset({"NO_GOLD", "N/A", "SEED_MISSING", "INSUFFICIENT_DATA"})
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SCOPE_KINDS = ("overall", "bucket", "resolver", "case_aggregate")
_POLICY_KEYS = frozenset(
    {
        "schema_version",
        "policy_version",
        "status",
        "baseline",
        "candidate_expectation",
        "insufficient_data",
        "primary_quality_metrics",
        "gates",
    }
)
_BASELINE_KEYS = frozenset(
    {"report_sha256", "manifest_sha256", "comparison_identity", "system_identity"}
)
_INSUFFICIENT_DATA_KEYS = frozenset(
    {"min_samples", "required_bucket_missing", "optional_bucket_sparse"}
)
_GATE_KEYS = frozenset(
    {
        "scope",
        "metric",
        "direction",
        "baseline_value",
        "allowed_abs_regression",
        "required",
        "protected",
    }
)
_PRIMARY_METRIC_KEYS = frozenset({"scope", "metric"})
_COMPARISON_IDENTITY_KEYS = frozenset(
    {
        "repository",
        "branch",
        "commit_sha",
        "index_key_source",
        "gold_version",
        "split",
        "case_set_sha256",
        "evaluator_version",
        "evaluator_sha256",
        "min_bucket_samples",
    }
)
_SYSTEM_IDENTITY_KEYS = frozenset(
    {
        "release_label",
        "friday_revision",
        "ranking_version",
        "response_version",
        "manifest_hash",
        "index_generation",
        "index_signature",
    }
)

__all__ = [
    "DIRECTIONS",
    "MARKERS",
    "POLICY_SCHEMA_VERSION",
    "VERDICTS",
    "ComparisonResult",
    "Gate",
    "GateDetail",
    "ThresholdPolicy",
    "compare_graph_bench",
    "load_threshold_policy",
    "sha256_bytes",
]


def sha256_bytes(raw: bytes) -> str:
    """返回原始 bytes 的 SHA-256。"""

    return hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _require_mapping(payload: dict[str, Any], key: str, *, where: str) -> dict[str, Any]:
    if key not in payload:
        raise ValueError(f"{where} 缺少必填字段 {key}")
    value = payload[key]
    if not isinstance(value, dict):
        raise ValueError(f"{where}.{key} 必须是 object")
    return value


def _require_list(payload: dict[str, Any], key: str, *, where: str) -> list[Any]:
    if key not in payload:
        raise ValueError(f"{where} 缺少必填字段 {key}")
    value = payload[key]
    if not isinstance(value, list):
        raise ValueError(f"{where}.{key} 必须是 array")
    return value


def _require_text(payload: dict[str, Any], key: str, *, where: str) -> str:
    if key not in payload:
        raise ValueError(f"{where} 缺少必填字段 {key}")
    value = payload[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{where}.{key} 必须是非空字符串")
    return value


def _require_bool(payload: dict[str, Any], key: str, *, where: str) -> bool:
    if key not in payload:
        raise ValueError(f"{where} 缺少必填字段 {key}")
    value = payload[key]
    if not isinstance(value, bool):
        raise ValueError(f"{where}.{key} 必须是 boolean")
    return value


def _require_number(payload: dict[str, Any], key: str, *, where: str) -> float:
    if key not in payload:
        raise ValueError(f"{where} 缺少必填字段 {key}")
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where}.{key} 必须是有限数值，marker 不得参与算术")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{where}.{key} 必须是有限数值")
    return number


def _validate_sha256(value: Any, *, where: str) -> str:
    if isinstance(value, str) and "REPLACE_WITH_" in value:
        raise ValueError(f"{where} 不得使用占位 hash")
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise ValueError(f"{where} 必须是 64 位小写十六进制 SHA-256")
    return value


def _validate_exact_keys(
    payload: dict[str, Any],
    expected: frozenset[str],
    *,
    where: str,
) -> None:
    missing = sorted(expected - payload.keys())
    if missing:
        raise ValueError(f"{where} 缺少必填字段：{', '.join(missing)}")
    extra = sorted(payload.keys() - expected)
    if extra:
        raise ValueError(f"{where} 包含未知字段：{', '.join(extra)}")


def _validate_comparison_identity(identity: dict[str, Any]) -> dict[str, Any]:
    _validate_exact_keys(identity, _COMPARISON_IDENTITY_KEYS, where="comparison_identity")
    for key in _COMPARISON_IDENTITY_KEYS - {"min_bucket_samples"}:
        _require_text(identity, key, where="comparison_identity")
    _validate_sha256(identity["case_set_sha256"], where="comparison_identity.case_set_sha256")
    _validate_sha256(identity["evaluator_sha256"], where="comparison_identity.evaluator_sha256")
    minimum = identity["min_bucket_samples"]
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        raise ValueError("comparison_identity.min_bucket_samples 必须是正整数")
    return json.loads(_canonical(identity))


def _validate_system_identity(identity: dict[str, Any], *, where: str) -> dict[str, Any]:
    _validate_exact_keys(identity, _SYSTEM_IDENTITY_KEYS, where=where)
    for key in _SYSTEM_IDENTITY_KEYS:
        _require_text(identity, key, where=where)
    _validate_sha256(identity["manifest_hash"], where=f"{where}.manifest_hash")
    return json.loads(_canonical(identity))


def _validate_scope(scope: dict[str, Any], *, where: str) -> dict[str, Any]:
    kind = _require_text(scope, "kind", where=where)
    if kind not in _SCOPE_KINDS:
        raise ValueError(f"{where}.kind 越出闭集 {_SCOPE_KINDS}")
    if set(scope) == {"kind"} and kind in {"bucket", "resolver"}:
        raise ValueError(f"{where} 的 {kind} scope 必须显式声明维度")
    for key, value in scope.items():
        if not isinstance(key, str) or not isinstance(value, str) or not value:
            raise ValueError(f"{where} 的 scope 键值必须是非空字符串")
    return json.loads(_canonical(scope))


@dataclass(frozen=True)
class Gate:
    scope: dict[str, str]
    metric: str
    direction: str
    baseline_value: float
    allowed_abs_regression: float
    required: bool
    protected: bool

    @property
    def key(self) -> tuple[str, str]:
        return (_canonical(self.scope), self.metric)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": dict(self.scope),
            "metric": self.metric,
            "direction": self.direction,
            "baseline_value": self.baseline_value,
            "allowed_abs_regression": self.allowed_abs_regression,
            "required": self.required,
            "protected": self.protected,
        }


@dataclass(frozen=True)
class ThresholdPolicy:
    schema_version: str
    policy_version: str
    status: str
    policy_sha256: str
    baseline_report_sha256: str
    baseline_manifest_sha256: str
    comparison_identity: dict[str, Any]
    baseline_system_identity: dict[str, Any]
    candidate_expectation: dict[str, Any]
    min_samples: int
    required_bucket_missing: str
    optional_bucket_sparse: str
    primary_quality_metrics: tuple[tuple[str, str], ...]
    gates: tuple[Gate, ...]


@dataclass(frozen=True)
class GateDetail:
    scope: dict[str, str]
    metric: str
    direction: str
    baseline_value: float
    candidate_value: Any
    allowed_abs_regression: float
    required: bool
    protected: bool
    samples: int | None
    status: str
    reason: str
    delta: float | None
    strictly_improved: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": dict(self.scope),
            "metric": self.metric,
            "direction": self.direction,
            "baseline_value": self.baseline_value,
            "candidate_value": self.candidate_value,
            "allowed_abs_regression": self.allowed_abs_regression,
            "required": self.required,
            "protected": self.protected,
            "samples": self.samples,
            "status": self.status,
            "reason": self.reason,
            "delta": self.delta,
            "strictly_improved": self.strictly_improved,
        }


@dataclass
class ComparisonResult:
    verdict: str
    policy_sha256: str
    baseline_sha256: str
    candidate_sha256: str
    baseline_manifest_sha256: str
    comparison_identity: dict[str, Any] = field(default_factory=dict)
    baseline_system_identity: dict[str, Any] = field(default_factory=dict)
    candidate_system_identity: dict[str, Any] = field(default_factory=dict)
    reproducible_commands: dict[str, str] = field(default_factory=dict)
    invalid_reasons: list[str] = field(default_factory=list)
    gates: list[GateDetail] = field(default_factory=list)
    improvement_evidence: list[dict[str, Any]] = field(default_factory=list)
    per_case: list[dict[str, Any]] = field(default_factory=list)
    per_bucket: list[dict[str, Any]] = field(default_factory=list)
    resolver_cells: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "hashes": {
                "policy_sha256": self.policy_sha256,
                "baseline_sha256": self.baseline_sha256,
                "candidate_sha256": self.candidate_sha256,
                "baseline_manifest_sha256": self.baseline_manifest_sha256,
            },
            "comparison_identity": dict(self.comparison_identity),
            "baseline_system_identity": dict(self.baseline_system_identity),
            "candidate_system_identity": dict(self.candidate_system_identity),
            "reproducible_commands": dict(self.reproducible_commands),
            "invalid_reasons": list(self.invalid_reasons),
            "gates": [gate.to_dict() for gate in self.gates],
            "improvement_evidence": list(self.improvement_evidence),
            "per_case": list(self.per_case),
            "per_bucket": list(self.per_bucket),
            "resolver_cells": list(self.resolver_cells),
        }


def load_threshold_policy(raw: bytes) -> ThresholdPolicy:
    """解析并完整校验 policy 原始 bytes；任何隐式默认或占位都 fail-closed。"""

    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("threshold policy 不是合法 UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("threshold policy 顶层必须是 object")
    _validate_exact_keys(payload, _POLICY_KEYS, where="policy")

    schema_version = _require_text(payload, "schema_version", where="policy")
    if schema_version != POLICY_SCHEMA_VERSION:
        raise ValueError(f"policy.schema_version 越出闭集：{schema_version!r}")
    policy_version = _require_text(payload, "policy_version", where="policy")
    status = _require_text(payload, "status", where="policy")
    if status != "locked":
        raise ValueError("policy.status 必须为 locked")

    baseline = _require_mapping(payload, "baseline", where="policy")
    _validate_exact_keys(baseline, _BASELINE_KEYS, where="policy.baseline")
    if "report_sha256" not in baseline:
        raise ValueError("policy.baseline 缺少必填字段 report_sha256")
    if "manifest_sha256" not in baseline:
        raise ValueError("policy.baseline 缺少必填字段 manifest_sha256")
    report_sha256 = _validate_sha256(
        baseline["report_sha256"],
        where="policy.baseline.report_sha256",
    )
    manifest_sha256 = _validate_sha256(
        baseline["manifest_sha256"],
        where="policy.baseline.manifest_sha256",
    )
    comparison_identity = _validate_comparison_identity(
        _require_mapping(baseline, "comparison_identity", where="policy.baseline")
    )
    baseline_system = _validate_system_identity(
        _require_mapping(baseline, "system_identity", where="policy.baseline"),
        where="policy.baseline.system_identity",
    )
    candidate = _validate_system_identity(
        _require_mapping(payload, "candidate_expectation", where="policy"),
        where="policy.candidate_expectation",
    )

    insufficient = _require_mapping(payload, "insufficient_data", where="policy")
    _validate_exact_keys(
        insufficient,
        _INSUFFICIENT_DATA_KEYS,
        where="policy.insufficient_data",
    )
    if "min_samples" not in insufficient:
        raise ValueError("policy.insufficient_data 缺少必填字段 min_samples")
    min_samples = insufficient["min_samples"]
    if isinstance(min_samples, bool) or not isinstance(min_samples, int) or min_samples < 1:
        raise ValueError("policy.insufficient_data.min_samples 必须是正整数")
    required_missing = _require_text(
        insufficient,
        "required_bucket_missing",
        where="policy.insufficient_data",
    )
    optional_sparse = _require_text(
        insufficient,
        "optional_bucket_sparse",
        where="policy.insufficient_data",
    )
    if required_missing != "FAIL":
        raise ValueError("required_bucket_missing 必须为 FAIL")
    if optional_sparse != "INSUFFICIENT_DATA":
        raise ValueError("optional_bucket_sparse 必须为 INSUFFICIENT_DATA")

    gates: list[Gate] = []
    seen: set[tuple[str, str]] = set()
    for index, raw_gate in enumerate(_require_list(payload, "gates", where="policy")):
        where = f"policy.gates[{index}]"
        if not isinstance(raw_gate, dict):
            raise ValueError(f"{where} 必须是 object")
        _validate_exact_keys(raw_gate, _GATE_KEYS, where=where)
        scope = _validate_scope(
            _require_mapping(raw_gate, "scope", where=where), where=f"{where}.scope"
        )
        metric = _require_text(raw_gate, "metric", where=where)
        direction = _require_text(raw_gate, "direction", where=where)
        if direction not in DIRECTIONS:
            raise ValueError(f"{where}.direction 越出闭集 {DIRECTIONS}")
        baseline_value = _require_number(raw_gate, "baseline_value", where=where)
        tolerance = _require_number(raw_gate, "allowed_abs_regression", where=where)
        if tolerance < 0:
            raise ValueError(f"{where}.allowed_abs_regression 不得为负数")
        gate = Gate(
            scope=scope,
            metric=metric,
            direction=direction,
            baseline_value=baseline_value,
            allowed_abs_regression=tolerance,
            required=_require_bool(raw_gate, "required", where=where),
            protected=_require_bool(raw_gate, "protected", where=where),
        )
        if gate.key in seen:
            raise ValueError(f"{where} 与已有 scope+metric 重复")
        seen.add(gate.key)
        gates.append(gate)
    if not gates:
        raise ValueError("policy.gates 必须至少声明一个 gate")

    primary: list[tuple[str, str]] = []
    for index, item in enumerate(_require_list(payload, "primary_quality_metrics", where="policy")):
        where = f"policy.primary_quality_metrics[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{where} 必须是 object")
        _validate_exact_keys(item, _PRIMARY_METRIC_KEYS, where=where)
        scope = _validate_scope(
            _require_mapping(item, "scope", where=where), where=f"{where}.scope"
        )
        metric = _require_text(item, "metric", where=where)
        key = (_canonical(scope), metric)
        matching = next((gate for gate in gates if gate.key == key), None)
        if matching is None or not matching.required:
            raise ValueError(f"{where} primary 必须引用已声明的 required gate")
        primary.append(key)
    if not primary:
        raise ValueError("policy.primary_quality_metrics 必须至少声明一项")

    return ThresholdPolicy(
        schema_version=schema_version,
        policy_version=policy_version,
        status=status,
        policy_sha256=sha256_bytes(raw),
        baseline_report_sha256=report_sha256,
        baseline_manifest_sha256=manifest_sha256,
        comparison_identity=comparison_identity,
        baseline_system_identity=baseline_system,
        candidate_expectation=candidate,
        min_samples=min_samples,
        required_bucket_missing=required_missing,
        optional_bucket_sparse=optional_sparse,
        primary_quality_metrics=tuple(primary),
        gates=tuple(gates),
    )


def _index_unique(
    rows: Any,
    *,
    key_fn,
    label: str,
    reasons: list[str],
) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        reasons.append(f"{label} 必须是 array")
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            reasons.append(f"{label} 含非 object 项")
            continue
        key = key_fn(row)
        if not key:
            reasons.append(f"{label} 含空 key")
        elif key in indexed:
            reasons.append(f"{label} 含重复 key {key}")
        else:
            indexed[key] = row
    return indexed


def _pair_rows(
    baseline_rows: Any,
    candidate_rows: Any,
    *,
    key_fn,
    label: str,
    reasons: list[str],
) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    baseline = _index_unique(
        baseline_rows, key_fn=key_fn, label=f"baseline {label}", reasons=reasons
    )
    candidate = _index_unique(
        candidate_rows, key_fn=key_fn, label=f"candidate {label}", reasons=reasons
    )
    missing = sorted(baseline.keys() - candidate.keys())
    extra = sorted(candidate.keys() - baseline.keys())
    if missing:
        reasons.append(f"{label} candidate 缺失：{', '.join(missing)}")
    if extra:
        reasons.append(f"{label} candidate 多出：{', '.join(extra)}")
    return [
        (key, baseline[key], candidate[key]) for key in sorted(baseline.keys() & candidate.keys())
    ]


def _row_key(row: dict[str, Any]) -> str:
    key = row.get("key")
    return _canonical(key) if isinstance(key, dict) else ""


def _diff_values(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    ignored = {
        "case_id",
        "key",
        "language",
        "framework",
        "entry_type",
        "call_shape",
        "protected",
        "has_protected",
        "status",
        "n",
        "gold_count",
    }
    names = sorted((baseline.keys() & candidate.keys()) - ignored)
    values: dict[str, Any] = {}
    for name in names:
        before = baseline[name]
        after = candidate[name]
        delta = float(after) - float(before) if _is_number(before) and _is_number(after) else None
        values[name] = {"baseline": before, "candidate": after, "delta": delta}
    return values


def _is_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _case_aggregate(report: dict[str, Any], metric: str) -> tuple[Any, int]:
    cases = report.get("per_case")
    if not isinstance(cases, list):
        return None, 0
    if metric.endswith("_median"):
        source = metric.removesuffix("_median")
        values = [row.get(source) for row in cases if isinstance(row, dict)]
        numeric = [float(value) for value in values if _is_number(value)]
        return (statistics.median(numeric), len(numeric)) if numeric else ("INSUFFICIENT_DATA", 0)
    if metric.endswith("_p95"):
        source = metric.removesuffix("_p95")
        trials: list[float] = []
        for row in cases:
            value = row.get(source) if isinstance(row, dict) else None
            if isinstance(value, list):
                trials.extend(float(item) for item in value if _is_number(item))
            elif _is_number(value):
                trials.append(float(value))
        if not trials:
            return "INSUFFICIENT_DATA", 0
        ordered = sorted(trials)
        index = max(0, math.ceil(len(ordered) * 0.95) - 1)
        return ordered[index], len(ordered)
    values = [row.get(metric) for row in cases if isinstance(row, dict)]
    numeric = [float(value) for value in values if _is_number(value)]
    return (statistics.mean(numeric), len(numeric)) if numeric else ("INSUFFICIENT_DATA", 0)


def _locate_gate_value(
    report: dict[str, Any],
    gate: Gate,
) -> tuple[Any, int | None, str, bool]:
    kind = gate.scope["kind"]
    if kind == "overall":
        overall = report.get("overall")
        value = overall.get(gate.metric) if isinstance(overall, dict) else None
        samples = report.get("total_cases")
        return value, samples if isinstance(samples, int) else None, "OK", False
    if kind == "case_aggregate":
        value, samples = _case_aggregate(report, gate.metric)
        status = "OK" if samples >= 1 else "INSUFFICIENT_DATA"
        return value, samples, status, False

    rows = (
        report.get("per_bucket")
        if kind == "bucket"
        else (report.get("resolver") or {}).get("cells")
    )
    dimensions = {key: value for key, value in gate.scope.items() if key != "kind"}
    matches = [
        row
        for row in rows or []
        if isinstance(row, dict)
        and isinstance(row.get("key"), dict)
        and all(row["key"].get(key) == value for key, value in dimensions.items())
    ]
    if len(matches) != 1:
        return None, None, "MISSING", False
    row = matches[0]
    metrics = row.get("metrics") if kind == "bucket" else row
    value = metrics.get(gate.metric) if isinstance(metrics, dict) else None
    samples = row.get("n") if kind == "bucket" else row.get("gold_count")
    protected = bool(row.get("has_protected")) if kind == "bucket" else bool(gate.protected)
    return (
        value,
        samples if isinstance(samples, int) else None,
        str(row.get("status") or ""),
        protected,
    )


def _gate_detail(
    gate: Gate,
    *,
    candidate_value: Any,
    samples: int | None,
    source_status: str,
    source_protected: bool,
    minimum: int,
) -> GateDetail:
    missing = source_status == "MISSING" or candidate_value is None
    sparse = source_status == "INSUFFICIENT_DATA" or (samples is not None and samples < minimum)
    if gate.protected and gate.scope["kind"] == "bucket" and not source_protected:
        missing = True

    if missing or sparse or not _is_number(candidate_value):
        status = "FAIL" if gate.required or gate.protected else "INSUFFICIENT_DATA"
        reason = (
            "required/protected gate 缺失或样本不足"
            if status == "FAIL"
            else "optional gate 样本不足"
        )
        if candidate_value in MARKERS:
            reason = f"marker {candidate_value} 不参与算术；{reason}"
        return GateDetail(
            **gate.to_dict(),
            candidate_value=candidate_value,
            samples=samples,
            status=status,
            reason=reason,
            delta=None,
            strictly_improved=False,
        )

    candidate_number = float(candidate_value)
    if gate.direction == "higher_is_better":
        passed = candidate_number >= gate.baseline_value - gate.allowed_abs_regression
        delta = candidate_number - gate.baseline_value
        improved = candidate_number > gate.baseline_value
    else:
        passed = candidate_number <= gate.baseline_value + gate.allowed_abs_regression
        delta = gate.baseline_value - candidate_number
        improved = candidate_number < gate.baseline_value
    return GateDetail(
        **gate.to_dict(),
        candidate_value=candidate_value,
        samples=samples,
        status="PASS" if passed else "FAIL",
        reason="候选值在显式容差内" if passed else "候选值越过显式容差",
        delta=delta,
        strictly_improved=improved,
    )


def compare_graph_bench(
    *,
    baseline_report: dict[str, Any],
    candidate_report: dict[str, Any],
    policy: ThresholdPolicy,
    baseline_sha256: str,
    candidate_sha256: str,
    baseline_manifest_sha256: str,
) -> ComparisonResult:
    """先验证三份 artifact 与严格配对，再执行 direction-aware 四态 gate。"""

    result = ComparisonResult(
        verdict="INVALID",
        policy_sha256=policy.policy_sha256,
        baseline_sha256=baseline_sha256,
        candidate_sha256=candidate_sha256,
        baseline_manifest_sha256=baseline_manifest_sha256,
        comparison_identity=dict(policy.comparison_identity),
        baseline_system_identity=dict(baseline_report.get("system_identity") or {}),
        candidate_system_identity=dict(candidate_report.get("system_identity") or {}),
        reproducible_commands={
            "baseline": str(baseline_report.get("reproducible_command") or ""),
            "candidate": str(candidate_report.get("reproducible_command") or ""),
        },
    )
    reasons = result.invalid_reasons
    for label, value in (
        ("baseline_sha256", baseline_sha256),
        ("candidate_sha256", candidate_sha256),
        ("baseline_manifest_sha256", baseline_manifest_sha256),
    ):
        try:
            _validate_sha256(value, where=label)
        except ValueError as exc:
            reasons.append(str(exc))
    if baseline_sha256 != policy.baseline_report_sha256:
        reasons.append("baseline report raw-byte hash 与 policy pin 不一致")
    if baseline_manifest_sha256 != policy.baseline_manifest_sha256:
        reasons.append("baseline manifest hash 与 policy pin 不一致")

    for label, report in (("baseline", baseline_report), ("candidate", candidate_report)):
        if not isinstance(report, dict):
            reasons.append(f"{label} report 顶层必须是 object")
            continue
        if report.get("watermark") != "OK":
            reasons.append(f"{label} watermark 不是 OK")
        if report.get("comparison_identity") != policy.comparison_identity:
            reasons.append(f"{label} comparison identity 与 policy 不一致")
        if not report.get("reproducible_command"):
            reasons.append(f"{label} 缺少 reproducible_command")
    if baseline_report.get("comparison_identity") != candidate_report.get("comparison_identity"):
        reasons.append("baseline/candidate comparison identity 不一致")
    if baseline_report.get("system_identity") != policy.baseline_system_identity:
        reasons.append("baseline system identity 与 policy pin 不一致")
    if candidate_report.get("system_identity") != policy.candidate_expectation:
        reasons.append("candidate system identity/ranking/response/manifest 与 policy 不一致")

    case_pairs = _pair_rows(
        baseline_report.get("per_case"),
        candidate_report.get("per_case"),
        key_fn=lambda row: str(row.get("case_id") or ""),
        label="case",
        reasons=reasons,
    )
    bucket_pairs = _pair_rows(
        baseline_report.get("per_bucket"),
        candidate_report.get("per_bucket"),
        key_fn=_row_key,
        label="bucket",
        reasons=reasons,
    )
    baseline_resolver = baseline_report.get("resolver") or {}
    candidate_resolver = candidate_report.get("resolver") or {}
    resolver_pairs = _pair_rows(
        baseline_resolver.get("cells") if isinstance(baseline_resolver, dict) else None,
        candidate_resolver.get("cells") if isinstance(candidate_resolver, dict) else None,
        key_fn=_row_key,
        label="resolver cell",
        reasons=reasons,
    )

    # policy baseline_value 必须精确来自冻结 baseline；不允许在 compare 时漂移。
    for gate in policy.gates:
        baseline_value, _samples, _status, _protected = _locate_gate_value(
            baseline_report,
            gate,
        )
        if not _is_number(baseline_value) or float(baseline_value) != gate.baseline_value:
            reasons.append(
                f"gate {_canonical(gate.scope)}::{gate.metric} 的 baseline_value "
                "未精确复制冻结 baseline"
            )
    if reasons:
        return result

    result.per_case = [
        {"case_id": key, "metrics": _diff_values(before, after)}
        for key, before, after in case_pairs
    ]
    result.per_bucket = [
        {
            "key": before["key"],
            "baseline_status": before.get("status"),
            "candidate_status": after.get("status"),
            "metrics": _diff_values(
                before.get("metrics") or {},
                after.get("metrics") or {},
            ),
        }
        for _key, before, after in bucket_pairs
    ]
    result.resolver_cells = [
        {
            "key": before["key"],
            "baseline_status": before.get("status"),
            "candidate_status": after.get("status"),
            "metrics": _diff_values(before, after),
        }
        for _key, before, after in resolver_pairs
    ]

    for gate in policy.gates:
        value, samples, source_status, protected = _locate_gate_value(candidate_report, gate)
        result.gates.append(
            _gate_detail(
                gate,
                candidate_value=value,
                samples=samples,
                source_status=source_status,
                source_protected=protected,
                minimum=policy.min_samples,
            )
        )
    for detail in result.gates:
        key = (_canonical(detail.scope), detail.metric)
        if key in policy.primary_quality_metrics and detail.strictly_improved:
            result.improvement_evidence.append(
                {
                    "scope": detail.scope,
                    "metric": detail.metric,
                    "delta": detail.delta,
                }
            )

    if any(detail.status == "FAIL" for detail in result.gates):
        result.verdict = "FAIL"
    elif any(detail.status == "INSUFFICIENT_DATA" for detail in result.gates):
        result.verdict = "INSUFFICIENT_DATA"
    elif not result.improvement_evidence:
        result.verdict = "FAIL"
    else:
        result.verdict = "PASS"
    return result
