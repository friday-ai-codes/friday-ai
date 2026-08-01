"""蓝图 golden set 离线评估 command（Phase 111-04，GATE-02）。

对 ``server/tests/fixtures/blueprint_golden/*.json`` 逐 case 评估（对齐 v0.19.0
Phase 105 golden set 方法论；镜像 ``measure_extractor_precision`` 的
参数 / report / 非零退出分层）：

1. ``validate_blueprint`` 必须通过（schema 拒绝退化可检出）；
2. ``derive_technical_plan_document`` 必须通过，且**确定性双跑**逐字节一致
   （ROADMAP SC5「同输入重复运行结果一致」内建为门槛，派生漂移可检出）；
3. ``citation_coverage`` ≥ ``expected.min_citation_coverage``（覆盖率跌破可检出）；
4. ``target_repo_hit_rate`` ≥ ``expected.min_repo_hit_rate``（命中率跌破可检出）；
5. ``expected.required_feature_point_ids`` ⊆ 实际 feature_points id 集合。

任一 case 未过门槛 → ``CommandError`` 非零退出（golden 基线不许静默放水，
T-111-11）。指标算法零内联——全部调 ``services.process_runtime`` 纯函数，
本 command 只做 IO 与编排。全程无 LLM / 无网络 / 无 DB 写，天然过
``--disable-socket``。

CLI 用例::

    python manage.py evaluate_blueprint_golden
    python manage.py evaluate_blueprint_golden --fixtures-dir=/path/to/cases \\
        --output-json=/tmp/blueprint_golden_report.json
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import structlog
from django.core.management.base import BaseCommand, CommandError

from services.process_runtime.blueprint_execution import derive_technical_plan_document
from services.process_runtime.blueprint_quality import citation_coverage, target_repo_hit_rate
from services.process_runtime.blueprint_schema import validate_blueprint

logger = structlog.get_logger(__name__)

# server/delivery/management/commands/ → parents[3] = server/
_DEFAULT_FIXTURES_DIR = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "blueprint_golden"
)


def _load_case(path: Path) -> tuple[dict | None, str | None]:
    """读单条 golden case；坏 JSON / 坏形状记为该 case 失败，不 crash 全局（T-111-10）。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"fixture 加载失败：{exc}"
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("blueprint"), dict)
        or not isinstance(data.get("expected"), dict)
    ):
        return None, "fixture 顶层必须含 blueprint 与 expected 两个对象"
    return data, None


def _evaluate_case(name: str, blueprint: dict, expected: dict) -> dict[str, Any]:
    """逐门槛评估单条 case，返回确定性 report 条目（指标算法零内联）。"""
    failures: list[str] = []
    metrics: dict[str, Any] = {}

    ok, err = validate_blueprint(blueprint)
    if not ok:
        failures.append(f"validate_blueprint 未通过：{err}")

    doc, derive_err = derive_technical_plan_document(blueprint)
    if doc is None:
        failures.append(f"derive_technical_plan_document 未通过：{derive_err}")
    else:
        # 确定性双跑（ROADMAP SC5）：同输入重复派生必须逐字节一致。
        doc_again, _ = derive_technical_plan_document(blueprint)
        first = json.dumps(doc, sort_keys=True, ensure_ascii=False)
        second = json.dumps(doc_again, sort_keys=True, ensure_ascii=False)
        if first != second:
            failures.append("确定性双跑失败：同输入两次派生输出不一致")

    coverage = citation_coverage(blueprint)
    metrics["citation_coverage"] = round(coverage, 4)
    min_coverage = expected.get("min_citation_coverage")
    if isinstance(min_coverage, (int, float)) and coverage < float(min_coverage):
        failures.append(f"引用覆盖率 {coverage:.4f} < 门槛 {float(min_coverage):.4f}")

    raw_expected_repos = expected.get("direct_repos")
    expected_repos = [
        r for r in (raw_expected_repos if isinstance(raw_expected_repos, list) else []) if r
    ]
    hit_rate = target_repo_hit_rate(blueprint, expected_repos)
    metrics["target_repo_hit_rate"] = round(hit_rate, 4)
    min_hit = expected.get("min_repo_hit_rate")
    if isinstance(min_hit, (int, float)) and hit_rate < float(min_hit):
        failures.append(f"目标仓命中率 {hit_rate:.4f} < 门槛 {float(min_hit):.4f}")

    raw_required_fp = expected.get("required_feature_point_ids")
    required_fp = {
        fp
        for fp in (raw_required_fp if isinstance(raw_required_fp, list) else [])
        if isinstance(fp, str) and fp
    }
    spec = blueprint.get("requirement_spec")
    feature_points = spec.get("feature_points") if isinstance(spec, dict) else None
    actual_fp = {
        fp.get("id") for fp in (feature_points or []) if isinstance(fp, dict) and fp.get("id")
    }
    missing_fp = sorted(required_fp - actual_fp)
    if missing_fp:
        failures.append(f"必备功能点缺失：{missing_fp}")

    return {"name": name, "passed": not failures, "metrics": metrics, "failures": failures}


class Command(BaseCommand):
    help = (
        "蓝图 golden set 离线评估（GATE-02）：逐 case 输出引用覆盖率/目标仓命中率并按 "
        "expected 门槛判定，任一未过门槛非零退出；无 LLM/无网络/无 DB 写。"
    )

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--fixtures-dir",
            type=str,
            default=str(_DEFAULT_FIXTURES_DIR),
            help="golden case 目录（默认 server/tests/fixtures/blueprint_golden）",
        )
        parser.add_argument(
            "--output-json",
            type=str,
            default=None,
            help="可选：汇总 report 另写一份 JSON 文件",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        started = time.monotonic()
        fixtures_dir = Path(options["fixtures_dir"])
        # golden 基线缺失是硬错误，不做 advisory 跳过（T-111-11 防静默放水）。
        if not fixtures_dir.is_dir():
            self.stderr.write(f"golden fixtures 目录不存在: {fixtures_dir}")
            raise CommandError("golden 基线缺失（目录不存在），拒绝评估")
        case_paths = sorted(fixtures_dir.glob("*.json"))
        if not case_paths:
            self.stderr.write(f"golden fixtures 目录为空: {fixtures_dir}")
            raise CommandError("golden 基线缺失（目录为空），拒绝评估")

        cases: list[dict[str, Any]] = []
        for path in case_paths:
            data, load_err = _load_case(path)
            if data is None:
                cases.append(
                    {"name": path.stem, "passed": False, "metrics": {}, "failures": [load_err]}
                )
                continue
            name = data.get("name") if isinstance(data.get("name"), str) else path.stem
            cases.append(_evaluate_case(name, data["blueprint"], data["expected"]))

        failed_count = sum(1 for case in cases if not case["passed"])
        report = {
            "total": len(cases),
            "passed": len(cases) - failed_count,
            "failed": failed_count,
            "cases": cases,
        }

        for case in cases:
            metric_text = " ".join(
                f"{key}={value}" for key, value in sorted(case["metrics"].items())
            )
            verdict = "PASS" if case["passed"] else "FAIL"
            # 先判空再拼（MN-13）：对成品字符串做 replace 会误伤 case 名里的 ":  →"，
            # 而确定性双跑门槛正是逐字节比对本行输出。
            head = f"{case['name']}: {metric_text}" if metric_text else f"{case['name']}:"
            self.stdout.write(f"{head} → {verdict}")
            for failure in case["failures"]:
                self.stdout.write(f"  - {failure}")

        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))

        if options.get("output_json"):
            output_path = Path(options["output_json"])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        logger.info(
            "blueprint_golden_evaluated",
            category="caller",
            component="process_runtime",
            initiated_by_user_id="system",
            fixtures_dir=str(fixtures_dir),
            total=len(cases),
            failed=failed_count,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )

        if failed_count:
            raise CommandError(f"{failed_count} 个 golden case 未过门槛")
