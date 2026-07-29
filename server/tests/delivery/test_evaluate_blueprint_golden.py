"""evaluate_blueprint_golden command 测试（Phase 111-04 Task 2，GATE-02）。

call_command + StringIO 范式（对齐 test_rebuild_repo_summaries）；command 纯文件读 +
纯函数计算，无需 django_db。覆盖：默认目录通过（含 gaokao_boost/PASS 输出）、离线
确定性（连续两次输出逐字节一致）、schema 退化非零退出、命中率门槛生效、空目录硬错误。
"""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from tests.helpers.blueprint_samples import make_blueprint

_PERMISSIVE_EXPECTED = {
    "direct_repos": [],
    "required_feature_point_ids": [],
    "min_citation_coverage": 0.0,
    "min_repo_hit_rate": 0.0,
}


def _write_case(directory: Path, name: str, blueprint: dict, expected: dict) -> None:
    payload = {
        "name": name,
        "description": "测试用 golden case",
        "blueprint": blueprint,
        "expected": expected,
    }
    (directory / f"{name}.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def test_default_fixtures_dir_passes_and_reports_gaokao_boost() -> None:
    buf = StringIO()
    call_command("evaluate_blueprint_golden", stdout=buf)
    output = buf.getvalue()
    assert "gaokao_boost" in output
    assert "PASS" in output
    assert "FAIL" not in output.replace('"failed": 0', "")


def test_repeat_runs_are_byte_identical() -> None:
    """离线确定性（ROADMAP SC5）：同输入连续两次运行输出逐字节一致。"""
    first, second = StringIO(), StringIO()
    call_command("evaluate_blueprint_golden", stdout=first)
    call_command("evaluate_blueprint_golden", stdout=second)
    assert first.getvalue() == second.getvalue()


def test_schema_invalid_case_exits_nonzero(tmp_path: Path) -> None:
    blueprint = make_blueprint()
    blueprint.pop("interaction_flows")  # 缺六段之一 → validate_blueprint 拒绝
    _write_case(tmp_path, "broken_schema", blueprint, dict(_PERMISSIVE_EXPECTED))
    with pytest.raises(CommandError, match="未过门槛"):
        call_command(
            "evaluate_blueprint_golden", "--fixtures-dir", str(tmp_path), stdout=StringIO()
        )


def test_repo_hit_rate_gate_enforced(tmp_path: Path) -> None:
    """blueprint 只留一个 direct 仓且不在期望集合 → 命中率 0 < 门槛 1.0 → 非零退出。"""
    blueprint = make_blueprint()
    for assoc in blueprint["repo_associations"][1:]:
        assoc["role"] = "indirect"
    expected = dict(_PERMISSIVE_EXPECTED)
    expected["direct_repos"] = ["study-course"]
    expected["min_repo_hit_rate"] = 1.0
    _write_case(tmp_path, "hit_rate_miss", blueprint, expected)
    with pytest.raises(CommandError, match="未过门槛"):
        call_command(
            "evaluate_blueprint_golden", "--fixtures-dir", str(tmp_path), stdout=StringIO()
        )


def test_bad_json_case_fails_without_crashing_run(tmp_path: Path) -> None:
    """坏 JSON 记为该 case 失败（非零退出），好 case 仍被评估输出。"""
    (tmp_path / "corrupt.json").write_text("{不是 JSON", encoding="utf-8")
    _write_case(tmp_path, "good_case", make_blueprint(), dict(_PERMISSIVE_EXPECTED))
    buf = StringIO()
    with pytest.raises(CommandError, match="1 个 golden case 未过门槛"):
        call_command("evaluate_blueprint_golden", "--fixtures-dir", str(tmp_path), stdout=buf)
    output = buf.getvalue()
    assert "corrupt" in output and "good_case" in output


def test_empty_fixtures_dir_is_hard_error(tmp_path: Path) -> None:
    with pytest.raises(CommandError, match="golden 基线缺失"):
        call_command(
            "evaluate_blueprint_golden", "--fixtures-dir", str(tmp_path), stdout=StringIO()
        )


def test_missing_fixtures_dir_is_hard_error(tmp_path: Path) -> None:
    with pytest.raises(CommandError, match="golden 基线缺失"):
        call_command(
            "evaluate_blueprint_golden",
            "--fixtures-dir",
            str(tmp_path / "not-there"),
            stdout=StringIO(),
        )


def test_output_json_writes_report_file(tmp_path: Path) -> None:
    report_path = tmp_path / "report" / "golden.json"
    call_command("evaluate_blueprint_golden", "--output-json", str(report_path), stdout=StringIO())
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["failed"] == 0
    assert any(case["name"] == "gaokao_boost" for case in report["cases"])
