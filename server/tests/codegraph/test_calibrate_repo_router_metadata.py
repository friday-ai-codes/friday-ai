"""calibrate_repo_router_metadata management command 测试（106-04 Task 2）。

O-2 校准管线的结构性验证（开发库只定管线，生产分布 deferred）：

- ``--structural`` 端到端零网络（pytest --disable-socket 全局强制）：
  合成 query/值对 + seed 确定性伪向量 → 负样本分布 → c_lo 建议 → 判定表。
- 无 ``--positives-file`` 时 c_hi 列为「需人工正样本，deferred」。
- ``--positives-file`` 结构校验（外部文件不可信，威胁边界）与 c_hi/判定计算。
- EmbeddingService 未配置/失败（mock 返回 None）→ 报错退出并提示 ``--structural``。
- 分位数与 ``repo_router_eval._quantile`` 同口径（线性插值，固定输入 → 已知 p95）。
"""

from __future__ import annotations

import io
import json
import math

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from codegraph.management.commands.calibrate_repo_router_metadata import (
    DISCRIMINATION_THRESHOLD,
    _quantile,
    _structural_vector,
)
from delivery.models import WorkItem
from services.embedding import EmbeddingService


def _run_command(*args: str) -> str:
    out = io.StringIO()
    call_command("calibrate_repo_router_metadata", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_structural_json_end_to_end() -> None:
    """--structural 端到端：默认 facet 集 = 3 语义分面 + 技术栈；c_lo 建议齐备。"""
    report = json.loads(_run_command("--structural", "--format", "json", "--negatives", "40"))

    assert report["mode"] == "structural"
    assert report["negatives_per_facet"] == 40
    assert [row["facet"] for row in report["facets"]] == [
        "业务线/产品线",
        "服务对象",
        "技术形态",
        "技术栈",
    ]
    for row in report["facets"]:
        assert row["skipped_reason"] is None
        assert row["value_count"] > 0
        negatives = row["negatives"]
        assert set(negatives) == {"count", "min", "p50", "p95", "max"}
        assert negatives["count"] == 40
        assert (
            -1.0
            <= negatives["min"]
            <= negatives["p50"]
            <= negatives["p95"]
            <= negatives["max"]
            <= 1.0
        )
        assert row["c_lo_suggested"] == negatives["p95"]
        # 无 --positives-file：c_hi 缺席，判定为 deferred（不猜正样本分布）
        assert row["c_hi_suggested"] is None
        assert row["verdict"] == "需人工正样本，deferred"
    stack_row = report["facets"][3]
    assert stack_row["facet"] == "技术栈"
    assert stack_row["value_count"] == 18  # _EXT_LANGUAGE_MAP 全语言枚举


@pytest.mark.django_db
def test_structural_markdown_contains_verdict_table_and_backfill_hint() -> None:
    """markdown 输出含判定表结构与回填指引（PUT 端点 + weight_set_version 提示）。"""
    output = _run_command("--structural", "--negatives", "20")

    assert "| facet | 闭集值数 |" in output
    assert "c_lo 建议（负 p95）" in output
    assert "需人工正样本，deferred" in output
    assert "PUT /api/settings/repo-router/weight-config/" in output
    assert "weight_set_version" in output
    assert "embedding_model_id" in output


@pytest.mark.django_db
def test_structural_with_positives_file_computes_c_hi_and_verdict(tmp_path) -> None:
    """--positives-file：按闭集值反查归属 facet，正样本 p50 → c_hi，判定口径锁定。"""
    positives = [
        {"query": "Python 服务定时任务不触发", "facet_value": "Python"},
        {"query": "Go 网关限流规则配置", "facet_value": "Go"},
        {"query": "无法归属的条目", "facet_value": "不存在的闭集值"},
    ]
    path = tmp_path / "positives.json"
    path.write_text(json.dumps(positives, ensure_ascii=False), encoding="utf-8")

    report = json.loads(
        _run_command(
            "--structural",
            "--format",
            "json",
            "--negatives",
            "20",
            "--positives-file",
            str(path),
        )
    )

    assert report["skipped_positives"] == 1  # 无法归属的条目跳过不猜
    stack_row = next(row for row in report["facets"] if row["facet"] == "技术栈")
    assert stack_row["positives"]["count"] == 2
    assert isinstance(stack_row["c_hi_suggested"], float)
    # 判定口径：c_hi - c_lo < 0.10 → 弃用 T2，否则保留（ROUTING-RANKING §3.2 步骤 3）
    gap = stack_row["c_hi_suggested"] - stack_row["c_lo_suggested"]
    expected = (
        "建议加入 t2_disabled_facets（区分度不足）" if gap < DISCRIMINATION_THRESHOLD else "保留 T2"
    )
    assert stack_row["verdict"] == expected
    # 未带正样本的语义分面仍为 deferred
    domain_row = next(row for row in report["facets"] if row["facet"] == "业务线/产品线")
    assert domain_row["verdict"] == "需人工正样本，deferred"


@pytest.mark.django_db
def test_positives_file_invalid_structure_rejected(tmp_path) -> None:
    """外部正样本文件不可信：非数组 / 缺键条目直接报错退出（威胁边界校验）。"""
    not_a_list = tmp_path / "bad.json"
    not_a_list.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    with pytest.raises(CommandError, match="JSON 数组"):
        _run_command("--structural", "--positives-file", str(not_a_list))

    missing_key = tmp_path / "missing.json"
    missing_key.write_text(json.dumps([{"query": "只有 query"}]), encoding="utf-8")
    with pytest.raises(CommandError, match="结构非法"):
        _run_command("--structural", "--positives-file", str(missing_key))


@pytest.mark.django_db
def test_embedding_unavailable_errors_with_structural_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EmbeddingService 全部返回 None（未配置/失败）→ 报错退出并提示 --structural。"""

    async def _none_batch(texts, batch_size=32, on_progress=None):
        return [None] * len(texts)

    monkeypatch.setattr(
        EmbeddingService,
        "generate_embeddings_batch",
        classmethod(lambda cls, texts, batch_size=32, on_progress=None: _none_batch(texts)),
    )
    for index in range(5):
        WorkItem.objects.create(
            feishu_project_key="proj",
            work_item_type="story",
            work_item_id=index,
            origin="manual",
            title=f"真实需求标题样本 {index}",
        )

    with pytest.raises(CommandError, match="--structural"):
        _run_command("--format", "json")


def test_quantile_linear_interpolation_matches_eval() -> None:
    """分位数与 repo_router_eval._quantile 同口径：固定输入 → 已知 p95。"""
    from codegraph.services.repo_router_eval import _quantile as eval_quantile

    vals = [round(0.1 * i, 4) for i in range(1, 11)]  # 0.1 .. 1.0（已升序）
    # pos = 0.95 * 9 = 8.55 → 0.9*0.45 + 1.0*0.55 = 0.955
    assert _quantile(vals, 0.95) == pytest.approx(0.955)
    assert _quantile(vals, 0.95) == pytest.approx(eval_quantile(vals, 0.95))
    assert _quantile(vals, 0.50) == pytest.approx(eval_quantile(vals, 0.50))
    assert _quantile([0.42], 0.95) == 0.42


def test_structural_vector_deterministic_unit_norm() -> None:
    """伪向量 seed 确定性（同文本同向量）且单位范数（余弦落 [-1,1]）。"""
    assert _structural_vector("同一文本") == _structural_vector("同一文本")
    assert _structural_vector("文本甲") != _structural_vector("文本乙")
    norm = math.sqrt(sum(v * v for v in _structural_vector("任意文本")))
    assert norm == pytest.approx(1.0, abs=1e-9)
