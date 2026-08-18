"""Phase 130 placement units 聚合单测（UNIT-01；D-04~D-06）。"""

from __future__ import annotations

import pytest

from services.process_runtime.placement_units import (
    PlacementUnit,
    PlacementUnitsResult,
    build_placement_units,
)


def _features_two_modules() -> tuple[list[dict], list[dict]]:
    """2 模块各 3 个 feature。"""
    modules = [
        {
            "name": "模块A",
            "summary": "看板与任务",
            "depends_on": ["模块B"],
        },
        {
            "name": "模块B",
            "summary": "做题与练习",
        },
    ]
    features = [
        {
            "id": "f-a1",
            "module": "模块A",
            "name": "任务列表",
            "description": "展示高三任务",
            "acceptance": "验收：任务必须出现在列表 SECRET_ACCEPT_A1",
        },
        {
            "id": "f-a2",
            "module": "模块A",
            "name": "任务详情",
            "description": "查看任务进度",
            "acceptance_criteria": "验收正文 SECRET_ACCEPT_A2",
        },
        {
            "id": "f-a3",
            "module": "模块A",
            "name": "任务筛选",
            "description": "按学科筛选",
        },
        {
            "id": "f-b1",
            "module": "模块B",
            "name": "练习入口",
            "description": "复用端内做题组件打开练习",
        },
        {
            "id": "f-b2",
            "module": "模块B",
            "name": "错题本",
            "description": "收集错题",
        },
        {
            "id": "f-b3",
            "module": "模块B",
            "name": "练习报告",
            "description": "生成练习报告",
        },
    ]
    return modules, features


def test_same_module_aggregation_reduces_unit_count():
    """同模块合并：unit 数 ≤ 模块数，且远小于 6 个独立 feature。"""
    modules, features = _features_two_modules()
    # 去掉 depends_on，仅测同模块合并
    modules = [
        {"name": "模块A", "summary": "看板与任务"},
        {"name": "模块B", "summary": "做题与练习"},
    ]
    result = build_placement_units(features_flat=features, modules=modules)
    assert isinstance(result, PlacementUnitsResult) or isinstance(result, dict)
    units = result.units if hasattr(result, "units") else result["units"]
    unit_count = (
        result.unit_count if hasattr(result, "unit_count") else result.get("unit_count")
    )
    assert unit_count == len(units)
    assert len(units) <= 2
    assert len(units) < 6
    for u in units:
        assert isinstance(u, PlacementUnit) or isinstance(u, dict)
        payload = u if isinstance(u, dict) else u.__dict__
        assert payload.get("unit_id")
        assert payload.get("feature_ids") or payload.get("feature_keys")
        assert payload.get("module_names")
        assert "query_text" in payload


def test_module_depends_on_merges_or_links_units():
    """模块 A depends_on B 时合并或建立可测关系，总 unit 数 < 独立 feature 数。"""
    modules, features = _features_two_modules()
    result = build_placement_units(features_flat=features, modules=modules)
    units = result.units if hasattr(result, "units") else result["units"]
    assert len(units) < 6
    # 默认同依赖链合并 → 期望 1 个合并单元（或 ≤ 模块数）
    assert len(units) <= 2
    # 若未完全合并，至少应有 unit 间边可测
    if len(units) > 1:
        linked = False
        for u in units:
            payload = u if isinstance(u, dict) else u.__dict__
            edges = payload.get("depends_on_units") or payload.get("unit_edges") or []
            if edges:
                linked = True
                break
        # 合并优先；若未合并则必须有边
        assert linked or len(units) == 1
    else:
        merged = units[0] if isinstance(units[0], dict) else units[0].__dict__
        mods = set(merged.get("module_names") or [])
        assert "模块A" in mods and "模块B" in mods


def test_reuse_phrase_populates_reuse_edges_and_host_hints():
    """「复用端内做题组件」→ reuse_edges 非空，reuse_host_hints 含 practice 相关 hint。"""
    modules, features = _features_two_modules()
    result = build_placement_units(features_flat=features, modules=modules)
    units = result.units if hasattr(result, "units") else result["units"]
    found = False
    for u in units:
        payload = u if isinstance(u, dict) else u.__dict__
        edges = payload.get("reuse_edges") or []
        hints = payload.get("reuse_host_hints") or []
        if edges:
            found = True
            hint_blob = " ".join(str(h).lower() for h in hints)
            assert any(
                tok in hint_blob
                for tok in ("practice", "做题", "练习", "practice_reuse_host")
            ), hints
            # 不硬编码仓 UUID
            for edge in edges:
                blob = str(edge)
                assert "uuid" not in blob.lower()
                assert len(blob) < 500
    assert found


def test_query_text_excludes_acceptance_body():
    """query_text 不含 acceptance / acceptance_criteria 正文。"""
    modules, features = _features_two_modules()
    result = build_placement_units(features_flat=features, modules=modules)
    units = result.units if hasattr(result, "units") else result["units"]
    for u in units:
        payload = u if isinstance(u, dict) else u.__dict__
        qt = str(payload.get("query_text") or "")
        assert "SECRET_ACCEPT_A1" not in qt
        assert "SECRET_ACCEPT_A2" not in qt
        assert "验收：" not in qt or "SECRET_ACCEPT" not in qt


def test_placement_units_observability_no_requirement_body(monkeypatch):
    """观测 placement_units_started/completed；kwargs 无超长需求全文。"""
    events: list[tuple[str, dict]] = []

    class _FakeLogger:
        def info(self, event, **kwargs):
            events.append((event, kwargs))

        def warning(self, event, **kwargs):
            events.append((event, kwargs))

        def error(self, event, **kwargs):
            events.append((event, kwargs))

    monkeypatch.setattr(
        "services.process_runtime.placement_units.logger",
        _FakeLogger(),
    )

    long_req = "这是一段很长很长很长很长很长很长很长很长很长很长很长很长的需求原文" * 5
    modules = [{"name": "M1", "summary": "s"}]
    features = [
        {
            "id": "f1",
            "module": "M1",
            "name": "功能",
            "description": long_req,
        }
    ]
    result = build_placement_units(features_flat=features, modules=modules)
    names = [e[0] for e in events]
    assert any("placement_units_started" in n for n in names)
    assert any("placement_units_completed" in n for n in names)
    for _name, kwargs in events:
        blob = " ".join(str(v) for v in kwargs.values())
        assert "很长很长很长很长很长很长很长很长很长很长很长很长的需求原文" not in blob
        assert kwargs.get("category") == "sampling"
        assert kwargs.get("component") == "process_runtime"
    unit_count = (
        result.unit_count if hasattr(result, "unit_count") else result.get("unit_count")
    )
    assert unit_count == 1
    completed = next(kw for n, kw in events if "placement_units_completed" in n)
    assert "unit_count" in completed
    assert "duration_ms" in completed


def test_merge_depends_on_false_links_units_without_collapsing_them():
    """⭐ Fix A：``merge_depends_on=False`` 时 depends_on 只写 **unit 边**，⛔ 不并查合并。

    蓝图 funnel 走的就是这条路径：默认 True 会把「A depends_on B」的两个模块塌回同一个
    unit，于是多模块需求又变成一次 RepoRouterV2 查询、primary/supporting 全靠一份查询
    定——正是 Fix A 要消灭的 mega-unit。
    """
    modules, features = _features_two_modules()

    result = build_placement_units(features_flat=features, modules=modules, merge_depends_on=False)

    units = result.units
    assert result.unit_count == 2, "depends_on 不得让两个模块塌成一个 unit"
    by_module = {}
    for unit in units:
        for name in unit.module_names:
            by_module[name] = unit
    assert set(by_module) == {"模块A", "模块B"}
    # 依赖关系仍可测：A → B 的 unit 边存在
    assert by_module["模块B"].unit_id in by_module["模块A"].depends_on_units
    assert by_module["模块A"].unit_id not in by_module["模块B"].depends_on_units


def test_build_from_feature_list_dict():
    """可用 feature_list 字典入口。"""
    modules, features = _features_two_modules()
    result = build_placement_units(
        feature_list={"modules": modules, "features_flat": features}
    )
    units = result.units if hasattr(result, "units") else result["units"]
    assert len(units) >= 1
    assert len(units) < 6
