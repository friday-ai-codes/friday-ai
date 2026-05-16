"""`HybridBudget` 行为测试（per Phase + ）。
覆盖 8 条 assertion：
1. 默认 ratio 0.6/0.4 + max_tokens=8000 → {rag:4320, graph:2880}
2. max_tokens=0 → {rag:0, graph:0}
3. HybridBudget 是 frozen dataclass（dataclasses.is_dataclass + frozen=True）
4. settings.GRAPHRAG_BUDGET_RATIO=0.7 覆盖 → rag 比例 0.7（allocate(8000)["rag"] == 5040）
5. settings 0.05 → clamp 到 0.1 + structlog warning hybrid_budget_ratio_clamped
6. settings 0.95 → clamp 到 0.9 + structlog warning
7. from_settings 不读 settings.ENABLE_CODEGRAPH（grep gate）
8. allocate buffer ratio 复用 TOKEN_BUFFER_RATIO=0.9
"""
from __future__ import annotations
import dataclasses
from pathlib import Path
import pytest
import structlog
from services.retrieval import budget as budget_module
from services.retrieval.budget import (
 GRAPHRAG_BUDGET_RATIO_DEFAULT,
 HybridBudget,
)
from services.retrieval.token_budget import TOKEN_BUFFER_RATIO
def test_default_ratio_allocates_60_40 -> None:
 result = HybridBudget.allocate(8000)
 # Phase: cross_repo=0.0 默认 → cross_repo key 存在但值为 0
 assert result == {"rag": 4320, "graph": 2880, "cross_repo": 0}
def test_zero_max_tokens_allocates_zero -> None:
 result = HybridBudget.allocate(0)
 assert result == {"rag": 0, "graph": 0, "cross_repo": 0}
def test_hybrid_budget_is_frozen_dataclass -> None:
 assert dataclasses.is_dataclass(HybridBudget)
 assert HybridBudget.__dataclass_params__.frozen is True
 with pytest.raises(dataclasses.FrozenInstanceError):
 HybridBudget.rag = 0.5 # type: ignore[misc]
def test_buffer_ratio_matches_token_buffer -> None:
 """allocate 必须复用 token_budget.TOKEN_BUFFER_RATIO=0.9 buffer 折算。"""
 assert TOKEN_BUFFER_RATIO == 0.9
 expected_effective = int(10_000 * TOKEN_BUFFER_RATIO)
 out = HybridBudget(rag=0.5, graph=0.5).allocate(10_000)
 assert out["rag"] == int(expected_effective * 0.5)
 assert out["graph"] == int(expected_effective * 0.5)
def test_from_settings_default(settings) -> None:
 """settings 未显式设置时，from_settings 使用 GRAPHRAG_BUDGET_RATIO_DEFAULT=0.6。"""
 settings.GRAPHRAG_BUDGET_RATIO = GRAPHRAG_BUDGET_RATIO_DEFAULT
 bud = HybridBudget.from_settings
 assert bud.rag == pytest.approx(0.6)
 assert bud.graph == pytest.approx(0.4)
def test_from_settings_override_70_30(settings) -> None:
 settings.GRAPHRAG_BUDGET_RATIO = 0.7
 bud = HybridBudget.from_settings
 assert bud.rag == pytest.approx(0.7)
 assert bud.graph == pytest.approx(0.3)
 assert bud.allocate(8000)["rag"] == int(8000 * 0.9 * 0.7)
def _capture_structlog_events -> tuple[list[dict], object]:
 """安装 structlog 捕获 processor，返回 (events_list, restore_callable)。
 用 ``structlog.DropEvent`` 兜底，避免事件穿透到 PrintLogger / JSONRenderer 引发
 `unexpected keyword argument` TypeError。
 """
 events: list[dict] =
 def _capture(logger, method_name, event_dict): # type: ignore[no-untyped-def]
 events.append(dict(event_dict))
 raise structlog.DropEvent
 old = structlog.get_config
 structlog.configure(
 processors=[_capture],
 wrapper_class=old["wrapper_class"],
 logger_factory=old["logger_factory"],
 cache_logger_on_first_use=False,
 )
 def _restore -> None:
 structlog.configure(**old)
 return events, _restore
def test_from_settings_clamp_lower_bound_and_warns(settings) -> None:
 """ratio < 0.1 → clamp 到 0.1 + structlog warning hybrid_budget_ratio_clamped。"""
 settings.GRAPHRAG_BUDGET_RATIO = 0.05
 events, restore = _capture_structlog_events
 try:
 bud = HybridBudget.from_settings
 finally:
 restore # type: ignore[operator]
 assert bud.rag == pytest.approx(0.1)
 assert bud.graph == pytest.approx(0.9)
 clamp_events = [e for e in events if e.get("event") == "hybrid_budget_ratio_clamped"]
 assert clamp_events, f"expected hybrid_budget_ratio_clamped event, got {events}"
 evt = clamp_events[-1]
 assert evt["requested"] == pytest.approx(0.05)
 assert evt["clamped"] == pytest.approx(0.1)
def test_from_settings_clamp_upper_bound_and_warns(settings) -> None:
 settings.GRAPHRAG_BUDGET_RATIO = 0.95
 events, restore = _capture_structlog_events
 try:
 bud = HybridBudget.from_settings
 finally:
 restore # type: ignore[operator]
 assert bud.rag == pytest.approx(0.9)
 assert bud.graph == pytest.approx(0.1)
 clamp_events = [e for e in events if e.get("event") == "hybrid_budget_ratio_clamped"]
 assert clamp_events
 assert clamp_events[-1]["clamped"] == pytest.approx(0.9)
def test_budget_module_does_not_read_enable_codegraph -> None:
 """grep gate：services/retrieval/budget.py 不允许执行
 ``settings.ENABLE_CODEGRAPH`` 表达式（per Pitfall 5——图谱开关只走
 isinstance(provider, GraphCapableProvider) 守卫）。
 检查 `settings.ENABLE_CODEGRAPH` 完整 token；docstring / 注释里可以出现该
 词，但不允许写成 attribute 访问的实际代码表达式。等价于 CI 的
 `rg "settings\\.ENABLE_CODEGRAP[H]" server/services/retrieval/` 必须 0 命中。
 """
 source = Path(budget_module.__file__).read_text(encoding="utf-8")
 assert "settings.ENABLE_CODEGRAPH" not in source, (
 "budget.py 源代码出现 settings.ENABLE_CODEGRAPH 表达式（grep gate 失败）"
 )
