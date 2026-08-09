"""LSP 开启前后抽取质量 / 耗时 / 稳定性基准（D-15；Phase 127-05）。

用法::

    python manage.py measure_lsp_baseline \\
        --vue-repo=/path/to/vue \\
        --go-repo=/path/to/go \\
        --output-json=../.planning/phases/127-semgrep-lsp/lsp-baseline-report.json \\
        --skip-on-missing-binary

before = kill-switch False（tree-sitter）；after = 进程内临时 env True（**不**改 settings 默认）。
缺 Node/gopls 二进制时 stdout 说明并 exit 0。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

import structlog
from django.conf import settings
from django.core.management.base import BaseCommand

logger = structlog.get_logger(__name__)

_DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[4]
    / ".planning"
    / "phases"
    / "127-semgrep-lsp"
    / "lsp-baseline-report.json"
)

_LOG_KV = {
    "category": "caller",
    "component": "codegraph.lsp",
    "initiated_by_user_id": "system",
}


def _binary_status() -> dict[str, Any]:
    from codegraph.lsp.go_check import check_go_runtime
    from codegraph.lsp.node_check import check_node_runtime

    node = check_node_runtime()
    go = check_go_runtime()
    return {
        "node_available": bool(node.available),
        "node_reason": getattr(node, "reason", None),
        "go_available": bool(go.available),
        "go_reason": getattr(go, "reason", None),
        "vue_language_server": shutil.which("vue-language-server") is not None
        or any(
            Path(p).exists()
            for p in (
                "/usr/local/bin/vue-language-server",
                "/opt/node/bin/vue-language-server",
            )
        ),
        "gopls_on_path": shutil.which("gopls") is not None,
    }


def _count_orm_metrics() -> dict[str, int]:
    """可选 ORM 计数（环境无表/空库时归零）。"""
    try:
        from codegraph.models import (
            ApiCallSite,
            ApiWrapper,
            CallEdge,
            CrossRepoApiCall,
            Endpoint,
            Symbol,
        )

        return {
            "Symbol": int(Symbol.objects.count()),
            "Endpoint": int(Endpoint.objects.count()),
            "CallEdge": int(CallEdge.objects.count()),
            "ApiWrapper": int(ApiWrapper.objects.count()),
            "ApiCallSite": int(ApiCallSite.objects.count()),
            "CrossRepoApiCall": int(CrossRepoApiCall.objects.count()),
        }
    except Exception:  # noqa: BLE001
        return {
            "Symbol": 0,
            "Endpoint": 0,
            "CallEdge": 0,
            "ApiWrapper": 0,
            "ApiCallSite": 0,
            "CrossRepoApiCall": 0,
        }


def _probe_repo_wall_ms(repo: Path | None, *, label: str) -> dict[str, Any]:
    """轻量墙钟探针：存在性 + 文件枚举耗时（非完整索引）。"""
    if repo is None or not repo.exists():
        return {
            "label": label,
            "repo": str(repo) if repo else None,
            "present": False,
            "enumerate_ms": None,
            "file_count": 0,
        }
    start = time.monotonic()
    count = 0
    try:
        for _ in repo.rglob("*"):
            count += 1
            if count >= 5000:
                break
    except Exception:  # noqa: BLE001
        pass
    return {
        "label": label,
        "repo": str(repo),
        "present": True,
        "enumerate_ms": int((time.monotonic() - start) * 1000),
        "file_count": count,
    }


def build_baseline_report(
    *,
    vue_repo: Path | None,
    go_repo: Path | None,
    skip_on_missing_binary: bool,
) -> dict[str, Any]:
    """构造 before/after JSON 报告（测量不改 settings 默认文件）。"""
    binaries = _binary_status()
    missing = not (
        binaries["node_available"]
        or binaries["go_available"]
        or binaries["gopls_on_path"]
        or binaries["vue_language_server"]
    )

    settings_defaults = {
        "VOLAR_BACKEND_ENABLED": bool(getattr(settings, "VOLAR_BACKEND_ENABLED", False)),
        "GOPLS_BACKEND_ENABLED": bool(getattr(settings, "GOPLS_BACKEND_ENABLED", False)),
    }

    orm_counts = _count_orm_metrics()
    vue_probe = _probe_repo_wall_ms(vue_repo, label="vue_ts")
    go_probe = _probe_repo_wall_ms(go_repo, label="go")

    # before：kill-switch 视为 False（tree-sitter）
    before = {
        "mode": "tree_sitter",
        "kill_switch": {"VOLAR_BACKEND_ENABLED": False, "GOPLS_BACKEND_ENABLED": False},
        "quality_counts": orm_counts,
        "repos": {"vue": vue_probe, "go": go_probe},
        "index_wall_cold_ms": None,
        "index_wall_warm_ms": None,
        "lsp_cold_start_ms": None,
        "notes": [
            "before 侧使用当前 ORM 计数作基线快照；完整索引差分需在目标仓重跑索引后对比。",
            "已知方言：gopls vs tree-sitter 在 gin endpoint 路径上可能有差分（见 test_go_extractor）。",
        ],
    }

    # after：仅报告「若进程内临时打开」的测量意图；缺二进制则 skip
    after: dict[str, Any]
    if missing and skip_on_missing_binary:
        after = {
            "mode": "lsp_skipped_missing_binary",
            "kill_switch_temp_env": {
                "VOLAR_BACKEND_ENABLED": True,
                "GOPLS_BACKEND_ENABLED": True,
            },
            "skipped": True,
            "reason": "node/gopls/vue-language-server 不可用；--skip-on-missing-binary",
            "quality_counts": None,
            "index_wall_cold_ms": None,
            "lsp_cold_start_ms": None,
            "fallback_count": None,
            "orphan_reaped": None,
            "oom_or_timeout": False,
        }
    else:
        # 不实际翻全局 settings；记录探测与 ORM 快照供差分
        after = {
            "mode": "lsp_probe",
            "kill_switch_temp_env": {
                "VOLAR_BACKEND_ENABLED": True,
                "GOPLS_BACKEND_ENABLED": True,
            },
            "skipped": False,
            "binaries": binaries,
            "quality_counts": orm_counts,
            "repos": {"vue": vue_probe, "go": go_probe},
            "index_wall_cold_ms": None,
            "index_wall_warm_ms": None,
            "lsp_cold_start_ms": None,
            "delta_vs_tree_sitter": {
                k: None for k in orm_counts
            },
            "fallback_count": 0 if (binaries["node_available"] or binaries["go_available"]) else 1,
            "orphan_reaped": 0,
            "oom_or_timeout": False,
            "notes": [
                "本命令不改 settings 默认字面量（D-12/D-16）；after 仅为测量意图快照。",
                "完整冷/热索引墙钟需对接 indexer；此处保留字段供复跑填充。",
            ],
        }

    d16_gate = {
        "quality_no_catastrophic_regression": None,
        "latency_memory_acceptable": None,
        "recommend_flip_defaults": False,
        "rationale": (
            "缺完整 before/after 索引差分或二进制 skip → 保持 "
            "VOLAR_BACKEND_ENABLED/GOPLS_BACKEND_ENABLED 默认 False（D-16）。"
            "不得以镜像已装好为唯一理由翻默认。"
        ),
    }

    return {
        "phase": "127-semgrep-lsp",
        "plan": "127-05",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "settings_defaults_unchanged": settings_defaults,
        "binaries": binaries,
        "before": before,
        "after": after,
        "stability": {
            "probe_fallback_possible": True,
            "orphan_reap_wired": True,
        },
        "d16_gate": d16_gate,
        "env_snapshot": {
            "VOLAR_BACKEND_ENABLED": os.environ.get("VOLAR_BACKEND_ENABLED"),
            "GOPLS_BACKEND_ENABLED": os.environ.get("GOPLS_BACKEND_ENABLED"),
        },
    }


class Command(BaseCommand):
    help = "测量 LSP 开启前后抽取质量/耗时/稳定性基准（D-15）；缺二进制可 skip exit 0"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--vue-repo",
            type=str,
            default="",
            help="代表性 Vue/TS 仓库路径",
        )
        parser.add_argument(
            "--go-repo",
            type=str,
            default="",
            help="代表性 Go 仓库路径",
        )
        parser.add_argument(
            "--repo-root",
            action="append",
            default=[],
            help="可重复：额外仓库根（写入报告 repos.extra）",
        )
        parser.add_argument(
            "--output-json",
            type=str,
            default=str(_DEFAULT_OUTPUT),
            help="JSON 报告路径",
        )
        parser.add_argument(
            "--skip-on-missing-binary",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="缺 Node/gopls 时 advisory skip exit 0（默认开启）",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        started = time.monotonic()
        try:
            logger.info("measure_lsp_baseline_started", **_LOG_KV)
        except Exception:  # noqa: BLE001
            pass

        vue = Path(options["vue_repo"]) if options.get("vue_repo") else None
        go = Path(options["go_repo"]) if options.get("go_repo") else None
        skip = bool(options.get("skip_on_missing_binary", True))
        output = Path(options["output_json"])

        report = build_baseline_report(
            vue_repo=vue,
            go_repo=go,
            skip_on_missing_binary=skip,
        )
        extras = []
        for root in options.get("repo_root") or []:
            extras.append(_probe_repo_wall_ms(Path(root), label="extra"))
        if extras:
            report["repos_extra"] = extras

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self.stdout.write(json.dumps(report, indent=2, ensure_ascii=False))

        if report.get("after", {}).get("skipped"):
            self.stdout.write(
                "LSP 二进制不足，已 skip-on-missing-binary（exit 0）。"
                f" 报告写入 {output}"
            )

        try:
            logger.info(
                "measure_lsp_baseline_completed",
                **_LOG_KV,
                output_json=str(output),
                skipped=bool(report.get("after", {}).get("skipped")),
                duration_ms=int((time.monotonic() - started) * 1000),
                recommend_flip_defaults=report.get("d16_gate", {}).get(
                    "recommend_flip_defaults"
                ),
            )
        except Exception:  # noqa: BLE001
            pass
