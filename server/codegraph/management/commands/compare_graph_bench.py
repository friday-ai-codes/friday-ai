"""只读比较 baseline、candidate 与 threshold policy，并写审计报告。"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import structlog
from django.core.management.base import BaseCommand, CommandError

from codegraph.services.graph_bench_compare import (
    ComparisonResult,
    compare_graph_bench,
    load_threshold_policy,
    sha256_bytes,
)
from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

_LOG_KV = {
    "category": "caller",
    "component": "codegraph",
    "initiated_by_user_id": "system",
}


def _read_bytes(path: Path, *, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ValueError(f"{label} 读取失败：{exc}") from exc


def _decode_report(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} 不是合法 UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} 顶层必须是 object")
    return payload


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        raise CommandError(f"compare report 写入失败：{exc}") from exc


def _reproducible_command(options: dict[str, Any]) -> str:
    return " ".join(
        [
            "python manage.py compare_graph_bench",
            f"--baseline {options['baseline']}",
            f"--candidate {options['candidate']}",
            f"--policy {options['policy']}",
            f"--output {options['output']}",
        ]
    )


def _log_started() -> None:
    try:
        logger.info("graph_bench_compare_started", **_LOG_KV)
    except Exception:  # noqa: BLE001 — 观测 best-effort
        pass


def _log_completed(*, verdict: str, duration_ms: int, gate_count: int) -> None:
    try:
        logger.info(
            "graph_bench_compare_completed",
            verdict=verdict,
            gate_count=gate_count,
            duration_ms=duration_ms,
            **_LOG_KV,
        )
    except Exception:  # noqa: BLE001 — 观测 best-effort
        pass


def _log_failed(*, verdict: str, duration_ms: int, error: str) -> None:
    try:
        logger.error(
            "graph_bench_compare_failed",
            verdict=verdict,
            duration_ms=duration_ms,
            error=redact_secrets_in_text(error)[:200],
            **_LOG_KV,
        )
    except Exception:  # noqa: BLE001 — 观测 best-effort
        pass


class Command(BaseCommand):
    help = "只读比较 graph benchmark baseline/candidate，并按锁定 policy 输出四态 verdict"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--baseline", required=True, help="冻结 baseline report JSON")
        parser.add_argument("--candidate", required=True, help="candidate report JSON")
        parser.add_argument("--policy", required=True, help="锁定 threshold policy JSON")
        parser.add_argument("--output", required=True, help="compare audit report 输出路径")

    def handle(self, *args: Any, **options: Any) -> None:
        started = time.monotonic()
        _log_started()
        output_path = Path(str(options["output"]))

        try:
            baseline_raw = _read_bytes(Path(str(options["baseline"])), label="baseline")
            candidate_raw = _read_bytes(Path(str(options["candidate"])), label="candidate")
            policy_raw = _read_bytes(Path(str(options["policy"])), label="policy")
            baseline = _decode_report(baseline_raw, label="baseline")
            candidate = _decode_report(candidate_raw, label="candidate")
            policy = load_threshold_policy(policy_raw)
            result = compare_graph_bench(
                baseline_report=baseline,
                candidate_report=candidate,
                policy=policy,
                baseline_sha256=sha256_bytes(baseline_raw),
                candidate_sha256=sha256_bytes(candidate_raw),
                # command 的公开契约仅有三份输入；manifest hash 是 policy 的冻结 pin。
                # 若调用方持有 manifest bytes，可直接调用纯 comparator 复核该参数。
                baseline_manifest_sha256=policy.baseline_manifest_sha256,
            )
        except (ValueError, TypeError) as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            safe_error = redact_secrets_in_text(str(exc))
            payload = {
                "verdict": "INVALID",
                "hashes": {
                    "policy_sha256": sha256_bytes(locals().get("policy_raw", b"")),
                    "baseline_sha256": sha256_bytes(locals().get("baseline_raw", b"")),
                    "candidate_sha256": sha256_bytes(locals().get("candidate_raw", b"")),
                    "baseline_manifest_sha256": None,
                },
                "invalid_reasons": [safe_error],
                "gates": [],
                "per_case": [],
                "per_bucket": [],
                "resolver_cells": [],
                "reproducible_command": _reproducible_command(options),
                "duration_ms": duration_ms,
            }
            _write_report(output_path, payload)
            _log_failed(verdict="INVALID", duration_ms=duration_ms, error=safe_error)
            raise CommandError(f"graph benchmark compare INVALID：{safe_error}") from exc

        duration_ms = int((time.monotonic() - started) * 1000)
        payload = result.to_dict()
        payload.update(
            {
                "reproducible_command": _reproducible_command(options),
                "duration_ms": duration_ms,
            }
        )
        _write_report(output_path, payload)
        self.stdout.write(f"compare report 已写入 {output_path}")
        self.stdout.write(f"graph benchmark compare verdict: {result.verdict}")

        if result.verdict == "PASS":
            _log_completed(
                verdict=result.verdict,
                duration_ms=duration_ms,
                gate_count=len(result.gates),
            )
            return

        reason = _failure_reason(result)
        _log_failed(
            verdict=result.verdict,
            duration_ms=duration_ms,
            error=reason,
        )
        raise CommandError(f"graph benchmark compare {result.verdict}：{reason}")


def _failure_reason(result: ComparisonResult) -> str:
    if result.invalid_reasons:
        return "；".join(result.invalid_reasons)
    failed = [gate.reason for gate in result.gates if gate.status != "PASS"]
    if failed:
        return "；".join(failed)
    return "缺少严格改善证据"
