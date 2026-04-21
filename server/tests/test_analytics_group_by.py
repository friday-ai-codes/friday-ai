"""Phase Plan — Analytics group_by 参数测试。
覆盖 契约：
- GET /api/analytics/overview/?group_by={none|provider_type|project}
- GET /api/analytics/token-cost/?group_by={none|provider_type|project}
Behavior 矩阵（PLAN A–F）：
- A: overview + group_by=none → {group_by: "none", total: {...}} flat 兼容
- B: overview + group_by=provider_type → {groups: {"anthropic": {...}, "openai_chat": {...}}}
- C: overview + group_by=project → {groups: {"<project_id>": {...}}}
- D: overview + group_by=invalid → 400 + {detail: "invalid group_by"}
- E: token-cost + group_by=provider_type → {groups: {"anthropic": [{date, cost, tokens}]}}
- F: TokenUsage.provider_type=null → "unknown" bucket
"""
from __future__ import annotations
from decimal import Decimal
from typing import TYPE_CHECKING
import pytest
if TYPE_CHECKING:
 from rest_framework.test import APIClient
@pytest.mark.django_db
class TestAnalyticsGroupByOverview:
 """GET /api/analytics/overview/?group_by=... 测试（Behavior A-D + F）。"""
 def test_group_by_none_returns_flat_total_shape(
 self,
 authenticated_client: "APIClient",
 analytics_token_usage_factory,
 ) -> None:
 """Behavior A：显式 ?group_by=none 返回 {group_by, total} 包装（新 shape）。
 Note: 不带 ?group_by 参数时继续返回 legacy flat shape（Phase 兼容，
 由 TestAnalyticsOverview:test_returns_kpi_data 覆盖）。
 """
 analytics_token_usage_factory(provider_type="anthropic", count=2)
 resp = authenticated_client.get("/api/analytics/overview/?group_by=none")
 assert resp.status_code == 200
 data = resp.json
 assert data["group_by"] == "none"
 assert "total" in data
 # total 包含原 flat KPI 字段
 assert "total_executions" in data["total"]
 assert "success_rate" in data["total"]
 # 分组模式不返回 groups 键
 assert "groups" not in data or data.get("groups") in (None, {}, )
 def test_group_by_provider_type_returns_groups_dict(
 self,
 authenticated_client: "APIClient",
 analytics_token_usage_factory,
 ) -> None:
 """Behavior B：group_by=provider_type 返回 groups dict + total 汇总。"""
 analytics_token_usage_factory(
 provider_type="anthropic", count=3, cost_usd=Decimal("0.01")
 )
 analytics_token_usage_factory(
 provider_type="openai_chat", count=2, cost_usd=Decimal("0.02")
 )
 resp = authenticated_client.get(
 "/api/analytics/overview/?group_by=provider_type"
 )
 assert resp.status_code == 200
 data = resp.json
 assert data["group_by"] == "provider_type"
 assert "groups" in data
 assert "anthropic" in data["groups"]
 assert "openai_chat" in data["groups"]
 # anthropic 组聚合 3 条 × 0.01 = 0.03
 anth = data["groups"]["anthropic"]
 assert anth["count"] == 3
 assert anth["total_tokens"] == 3 * (500 + 500) # factory 默认 input+output
 assert float(anth["total_cost_usd"]) == pytest.approx(0.03, abs=0.001)
 # openai_chat 2 × 0.02 = 0.04
 openai = data["groups"]["openai_chat"]
 assert openai["count"] == 2
 assert float(openai["total_cost_usd"]) == pytest.approx(0.04, abs=0.001)
 # total 汇总包含原 flat 字段
 assert "total" in data
 def test_group_by_invalid_returns_400(
 self,
 authenticated_client: "APIClient",
 ) -> None:
 """Behavior D：白名单校验，group_by=foobar → 400。"""
 resp = authenticated_client.get(
 "/api/analytics/overview/?group_by=invalid"
 )
 assert resp.status_code == 400
 data = resp.json
 assert "invalid group_by" in data.get("detail", "").lower or \
 data.get("detail") == "invalid group_by"
 def test_group_by_provider_type_null_bucket_mapped_to_unknown(
 self,
 authenticated_client: "APIClient",
 analytics_token_usage_factory,
 ) -> None:
 """Behavior F：provider_type=None 历史行映射到 "unknown" bucket。"""
 # factory 不支持 None，直接用 django model 创建
 from decimal import Decimal as D
 from uuid import uuid4
 from django.apps import apps
 TokenUsage = apps.get_model("subagent", "TokenUsage")
 SubAgentSession = apps.get_model("subagent", "SubAgentSession")
 AgentSession = apps.get_model("agents", "AgentSession")
 main = AgentSession.objects.create(
 session_id=f"main-{uuid4.hex}",
 status=AgentSession.Status.COMPLETED,
 )
 session = SubAgentSession.objects.create(
 session_id=f"sess-{uuid4.hex}",
 main_session=main,
 repo_url="https://github.com/test/legacy.git",
 task_type=SubAgentSession.TaskType.CODING,
 )
 TokenUsage.objects.create(
 session=session,
 input_tokens=100,
 output_tokens=200,
 total_cost_usd=D("0.005"),
 model="legacy-model",
 provider_type=None,
 )
 # 再添一条正常 anthropic 对照
 analytics_token_usage_factory(provider_type="anthropic", count=1)
 resp = authenticated_client.get(
 "/api/analytics/overview/?group_by=provider_type"
 )
 assert resp.status_code == 200
 data = resp.json
 assert "unknown" in data["groups"], \
 f"provider_type=None 应合并到 unknown bucket，实得 groups={list(data['groups'].keys)}"
 assert data["groups"]["unknown"]["count"] == 1
 assert "anthropic" in data["groups"]
@pytest.mark.django_db
class TestAnalyticsGroupByTokenCost:
 """GET /api/analytics/token-cost/?group_by=... 测试（Behavior E）。"""
 def test_group_by_provider_type_returns_per_provider_series(
 self,
 authenticated_client: "APIClient",
 analytics_token_usage_factory,
 ) -> None:
 """Behavior E：token-cost + provider_type → {groups: {<pt>: [{date, tokens, cost}]}}。"""
 analytics_token_usage_factory(
 provider_type="anthropic", count=2, cost_usd=Decimal("0.015")
 )
 analytics_token_usage_factory(
 provider_type="gemini", count=1, cost_usd=Decimal("0.008")
 )
 resp = authenticated_client.get(
 "/api/analytics/token-cost/?group_by=provider_type"
 )
 assert resp.status_code == 200
 data = resp.json
 assert data["group_by"] == "provider_type"
 assert "groups" in data
 assert "anthropic" in data["groups"]
 assert "gemini" in data["groups"]
 # groups[anthropic] 是 list[TokenCostDataPoint]
 assert isinstance(data["groups"]["anthropic"], list)
 assert len(data["groups"]["anthropic"]) >= 1
 # 单条数据点结构
 anth_point = data["groups"]["anthropic"][0]
 assert "date" in anth_point
 assert "input_tokens" in anth_point
 assert "output_tokens" in anth_point
 assert "total_cost_usd" in anth_point
 def test_token_cost_group_by_none_returns_flat_list_compat(
 self,
 authenticated_client: "APIClient",
 analytics_token_usage_factory,
 ) -> None:
 """Behavior A（token-cost 变体）：group_by=none 保留历史 flat list 兼容。"""
 analytics_token_usage_factory(provider_type="anthropic", count=1)
 # 不带 group_by 参数（与旧 Phase 契约一致）
 resp = authenticated_client.get("/api/analytics/token-cost/")
 assert resp.status_code == 200
 data = resp.json
 # 旧路径仍返回 list（保向后兼容）
 assert isinstance(data, list), \
 "group_by=none（缺省）必须兼容旧 Phase 的 flat list shape"
