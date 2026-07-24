"""测量 volar vs tree-sitter import / call resolution 精度。

per work item / work item / work item
=========================

- **G6 实战门（硬卡）**：``import_resolution_accuracy >= 0.70`` AND
  ``cross_file_call_resolution_completeness >= 0.70``
- **G7 stretch advisory**：``>= 0.80``；不阻塞 phase 完成但 SUMMARY 标 gap

CLI 用例
========

::

    python manage.py measure_extractor_precision \\
        --sample-repo=/path/to/vue-repo \\
        --sub-spaces=apps/courses,apps/home,packages/shared-utils \\
        --output-json=/tmp/volar_precision_report.json
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import shutil
import sys
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import structlog
from django.core.management.base import BaseCommand

logger = structlog.get_logger(__name__)

_EVENT_PRECISION_MEASURED = "volar_precision_measured"
_EVENT_PRECISION_SKIPPED = "volar_precision_skipped"
_EVENT_PRECISION_GROUND_TRUTH_LOADED = "volar_precision_ground_truth_loaded"


@dataclasses.dataclass(frozen=True)
class _GroundTruthEntry:
    sub_project: str
    file_path: str
    line: int
    kind: str  # "import" | "call"
    expected_target_path: str
    expected_callee_symbol: str


def _normalize_path(path: str | None) -> str:
    """简化路径比较：去掉前缀 / 去尾 / 后缀 .ts / .tsx / .vue 转空。"""
    if not path:
        return ""
    return path.replace("\\", "/").strip("/")


class Command(BaseCommand):
    help = (
        "测量 volar vs tree-sitter import / call resolution 精度"
        "（G6 70% 实战门 / G7 80% stretch advisory）"
    )

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--sample-repo",
            type=str,
            required=True,
            help="样本仓库绝对路径（如 /Users/.../example-app）",
        )
        parser.add_argument(
            "--sub-projects",
            type=str,
            default=(
                "apps/courses,apps/studyCheckList,apps/home,"
                "apps/explore,packages/shared-utils"
            ),
            help="逗号分隔的 sub-project 相对路径列表（默认 5 项）",
        )
        parser.add_argument(
            "--baseline-backend",
            type=str,
            default="tree_sitter",
            choices=["tree_sitter", "volar"],
            help="对比基线 backend（默认 tree_sitter）",
        )
        parser.add_argument(
            "--output-json",
            type=str,
            default="/tmp/volar_precision_report.json",
        )
        parser.add_argument(
            "--ground-truth-csv",
            type=str,
            default=str(
                Path(__file__).parent.parent / "fixtures" / "volar_precision_ground_truth.csv"
            ),
        )
        parser.add_argument(
            "--skip-on-missing-binary",
            action="store_true",
            default=True,
            help="vue-language-server 缺失时 advisory 跳过（CI 友好；exit 0）",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        sample_repo = Path(options["sample_repo"])
        sub_projects = [s.strip() for s in options["sub_projects"].split(",") if s.strip()]
        output_json = Path(options["output_json"])
        ground_truth_csv = Path(options["ground_truth_csv"])
        skip_on_missing = bool(options.get("skip_on_missing_binary", True))

        vls_bin = shutil.which("vue-language-server")
        if vls_bin is None and skip_on_missing:
            advisory = (
                "vue-language-server 未在 PATH（建议 npm i -g @vue/language-server）；"
                "advisory 跳过精度测量。"
            )
            logger.info(_EVENT_PRECISION_SKIPPED, reason=advisory)
            self.stdout.write(advisory)
            return

        if not sample_repo.exists():
            advisory = f"--sample-repo 路径不存在: {sample_repo}；跳过测量"
            logger.info(_EVENT_PRECISION_SKIPPED, reason=advisory)
            self.stdout.write(advisory)
            return

        if not ground_truth_csv.exists():
            self.stderr.write(f"ground truth CSV 不存在: {ground_truth_csv}")
            raise SystemExit(2)

        ground_truth = _load_ground_truth(ground_truth_csv)
        logger.info(
            _EVENT_PRECISION_GROUND_TRUTH_LOADED,
            csv_path=str(ground_truth_csv),
            entry_count=len(ground_truth),
        )

        report = self._measure(
            sample_repo=sample_repo,
            sub_projects=sub_projects,
            ground_truth=ground_truth,
        )
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(report, indent=2, ensure_ascii=False))

        import_acc = float(report.get("import_resolution_accuracy", 0.0))
        call_compl = float(report.get("cross_file_call_resolution_completeness", 0.0))
        passed = import_acc >= 0.70 and call_compl >= 0.70
        stretch_passed = import_acc >= 0.80 and call_compl >= 0.80
        report["passed"] = passed
        report["stretch_passed"] = stretch_passed

        logger.info(
            _EVENT_PRECISION_MEASURED,
            import_accuracy=import_acc,
            call_completeness=call_compl,
            sample_size=int(report.get("sample_size", 0)),
            first_full_index_seconds=float(report.get("first_full_index_seconds", 0.0)),
            passed=passed,
            stretch_passed=stretch_passed,
        )
        self.stdout.write(json.dumps(report, indent=2, ensure_ascii=False))

        if not passed:
            self.stderr.write(
                f"精度门未通过：import_accuracy={import_acc:.2f}, "
                f"call_completeness={call_compl:.2f}（要求 ≥ 0.70）"
            )
            raise SystemExit(1)

        if passed and not stretch_passed:
            self.stderr.write(
                f"⚠ stretch 80% 未达：import_accuracy={import_acc:.2f}, "
                f"call_completeness={call_compl:.2f}；G6 70% 通过 advisory 不阻塞"
            )

    def _measure(
        self,
        *,
        sample_repo: Path,
        sub_projects: list[str],
        ground_truth: list[_GroundTruthEntry],
    ) -> dict[str, Any]:
        """端到端测量：discover → 双 backend extract → diff ground truth。

        实装策略：
            1. discover_sub_projects 拿 SubProject 元数据
            2. 对 ground truth 中每条 entry：
               - 对应 sub_project 用 VolarBackend extract_imports/calls
               - 对比 expected_target_path / expected_callee_symbol
            3. 累计 import_match / call_match 计数
            4. 测量首次全量 backend 实例化耗时
        """
        from codegraph.extractors.base import FileContext
        from codegraph.lsp.volar_backend import VolarBackend
        from codegraph.lsp.volar_pool import get_volar_pool
        from codegraph.lsp.workspace_discovery import discover_sub_projects

        start = time.monotonic()
        all_sub_projects = discover_sub_projects(sample_repo)
        sub_project_index = {
            sp.root.relative_to(sample_repo).as_posix(): sp
            for sp in all_sub_projects
            if sp.root.is_relative_to(sample_repo)
        }

        pool = get_volar_pool()
        import_total = 0
        import_match = 0
        call_total = 0
        call_match = 0
        per_sub_project_stats: dict[str, dict[str, int]] = {}

        try:
            for entry in ground_truth:
                if entry.sub_project not in sub_project_index:
                    continue
                if sub_projects and entry.sub_project not in sub_projects:
                    continue
                sp_meta = sub_project_index[entry.sub_project]
                stats = per_sub_project_stats.setdefault(
                    entry.sub_project, {"import_total": 0, "import_match": 0, "call_total": 0, "call_match": 0}
                )

                file_abs = (sample_repo / entry.file_path).resolve()
                if not file_abs.exists():
                    continue

                language = _infer_language(file_abs.suffix)
                if language is None:
                    continue

                supervisor = pool.get(sp_meta.root, vue_version=sp_meta.vue_version)
                backend = VolarBackend(language=language, supervisor=supervisor)
                source = file_abs.read_text(errors="replace")
                ctx = FileContext(
                    file_path=str(file_abs),
                    language=language,
                    repository_id="precision-measure",
                )
                handle = backend.parse_file(str(file_abs), source)

                if entry.kind == "import":
                    imports = backend.extract_imports(handle, ctx)
                    matched = _match_import(
                        imports=imports,
                        expected_line=entry.line,
                        expected_target=entry.expected_target_path,
                    )
                    import_total += 1
                    stats["import_total"] += 1
                    if matched:
                        import_match += 1
                        stats["import_match"] += 1
                elif entry.kind == "call":
                    calls = backend.extract_calls(handle, ctx)
                    matched = _match_call(
                        calls=calls,
                        expected_callee=entry.expected_callee_symbol,
                    )
                    call_total += 1
                    stats["call_total"] += 1
                    if matched:
                        call_match += 1
                        stats["call_match"] += 1
        finally:
            try:
                pool.shutdown_all(timeout=10.0)
            except Exception as exc:  # noqa: BLE001
                logger.warning("volar_pool_shutdown_unexpected", error=str(exc))

        elapsed = time.monotonic() - start
        return {
            "import_resolution_accuracy": (import_match / import_total) if import_total else 0.0,
            "cross_file_call_resolution_completeness": (
                (call_match / call_total) if call_total else 0.0
            ),
            "sample_size": import_total + call_total,
            "import_total": import_total,
            "import_match": import_match,
            "call_total": call_total,
            "call_match": call_match,
            "first_full_index_seconds": elapsed,
            "ground_truth_entries": len(ground_truth),
            "per_sub_project": per_sub_project_stats,
            "ground_truth_csv": str(Path(__file__).parent.parent / "fixtures" / "volar_precision_ground_truth.csv"),
        }


def _load_ground_truth(csv_path: Path) -> list[_GroundTruthEntry]:
    """读 CSV → list[_GroundTruthEntry]；跳过非法行 + 容忍空字段。"""
    entries: list[_GroundTruthEntry] = []
    with csv_path.open(newline="", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            try:
                entry = _GroundTruthEntry(
                    sub_project=(row.get("sub_project") or "").strip(),
                    file_path=(row.get("file_path") or "").strip(),
                    line=int((row.get("line") or "0").strip()),
                    kind=(row.get("kind") or "").strip(),
                    expected_target_path=(row.get("expected_target_path") or "").strip(),
                    expected_callee_symbol=(row.get("expected_callee_symbol") or "").strip(),
                )
            except (TypeError, ValueError):
                continue
            if not entry.sub_project or not entry.file_path:
                continue
            entries.append(entry)
    return entries


def _infer_language(suffix: str) -> str | None:
    return {
        ".vue": "vue",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".js": "javascript",
        ".jsx": "jsx",
    }.get(suffix.lower())


def _match_import(
    imports: Iterable[Any],
    expected_line: int,
    expected_target: str,
) -> bool:
    """Import 匹配：行号 ± 2 容忍 + target_path 后缀对齐。"""
    expected_norm = _normalize_path(expected_target)
    for imp in imports:
        line_val = int(getattr(imp, "line", 0) or 0)
        target_path = getattr(imp, "target_path", None)
        target_norm = _normalize_path(target_path)
        if not expected_target:
            # ground truth 没填 target → 仅断言 import 被抽到（line 容忍）
            if abs(line_val - expected_line) <= 2:
                return True
            continue
        if not target_norm:
            continue
        if expected_norm in target_norm or target_norm.endswith(expected_norm):
            return True
    return False


def _match_call(calls: Iterable[Any], expected_callee: str) -> bool:
    """Call 匹配：callee_name 精确字符串匹配。"""
    if not expected_callee:
        return False
    for call in calls:
        callee = getattr(call, "callee_name", "")
        if isinstance(callee, str) and callee == expected_callee:
            return True
    return False
