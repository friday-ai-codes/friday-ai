---
phase: 38-routing-recall
status: passed
verified: 2026-06-16
mode: goal-backward
requirements: [ROUTE-01, RECALL-01]
plans_executed: [38-01, 38-02, 38-03]
---

# Phase 38: 路由 + 召回接入 — Verification

**Goal:** 把 Phase 36 引擎里 `routing` / `recalling` 两段的骨架（`SkeletonRouter`/`SkeletonRecall`）替换为真实实现，复用既有 `RepoRouterV2` + `DeliveryKnowledgeSearchService`，结果落 `PlanSession`，按 DOMAIN §14 转移，并产出 §15 `repo.routing` / `knowledge.recalling` trace 事件。

## Goal-Backward Success Criteria

### SC-1 — routing 候选仓 + confidence 持久化 + routing → recalling ✅ PASS

**要求**：routing 阶段经 `RepoRouterV2Adapter` 路由出候选仓 + confidence 写入 `PlanSession.routing`，按 §14 `routed` 转移 routing → recalling。

**证据：**
- `RepoRouterV2Adapter.route` 复用 `RepoRouterV2.route(query, top_k, repository_ids, use_llm=True)`，映射精简候选 `{repo_id, confidence, repository_name}` + `router_version` + `auto_selected`（`server/services/plan_orchestration/repo_router_adapter.py`）。
- `engine._route` 捕获返回 → `transition(session, "routed", routing=result)`（`server/services/plan_orchestration/engine.py`）；`_PERSISTABLE_FIELDS` 含 `routing`（`plan_session_service.py`），落 `PlanSession.routing` 字段（migration 0011）。
- §14 `routed`：`_ALLOWED[ROUTING]["routed"] == RECALLING`，转移 routing → recalling。
- 候选范围按 include_repos → work_item.project 仓库 → 全库 优先级解析。
- **测试**：`test_route_persists_routing_and_emits_event`（DB 重取 status=recalling 且 routing==注入 dict）；`test_repo_router_adapter.py` 5 例（映射/空 query 跳过/三档范围）。

### SC-2 — recall context 注入 + recalling → clarifying ✅ PASS

**要求**：recalling 阶段经 `DeliveryKnowledgeRecallAdapter` 召回相似需求/缺陷/复盘/技术方案写入 `PlanSession.recall_context`，按 §14 `recalled` 转移 recalling → clarifying。

**证据：**
- `DeliveryKnowledgeRecallAdapter.recall` 复用 `DeliveryKnowledgeSearchService.search_similar`，`entity_kinds = [work_item, tech_plan, code_change]`，routing 候选仓收窄 `repository_ids`，映射精简命中 `{entity_id, kind, title, score}`（`server/services/plan_orchestration/recall_adapter.py`）。
- 权限 fail-closed：`user = session.created_by`，None 时透传（不伪造 actor）→ `search_similar` 经 `resolve_allowed_project_ids(None)` 返回 [] → 空召回，不泄漏越权数据。检索异常 try/except → best-effort 空召回。
- `engine._recall` 捕获 → `transition(session, "recalled", recall_context=hits)`；`_PERSISTABLE_FIELDS` 含 `recall_context`。
- §14 `recalled`：`_ALLOWED[RECALLING]["recalled"] == CLARIFYING`，转移 recalling → clarifying。
- **测试**：`test_recall_persists_context_and_emits_event`（DB 重取 status=clarifying 且 recall_context==注入 hits）；`test_recall_adapter.py` 5 例（映射/created_by None fail-closed 断言 user 透传 None/异常空召回/routing 收窄/kinds 常量）。

### SC-3 — repo.routing + knowledge.recalling §15 trace 事件 ✅ PASS

**要求**：两段产出 §15 信封 trace 事件 `repo.routing` / `knowledge.recalling`，经 Phase 36 `_emit_event` 钩子产出。

**证据：**
- `engine._route` 在转移后调 `_emit_event("repo.routing", session, {"candidates": [{repo_id, confidence}]})`（仅 repo_id/confidence，不含 reasoning，INV-5 trace 非 CoT）。
- `engine._recall` 在转移后调 `_emit_event("knowledge.recalling", session, {"query", "kinds", "hits": len})`（hits 仅计数，不外泄命中明细）。
- **测试**：engine 两测试以 AsyncMock spy `_emit_event`，断言 `call_args_list` 含一次正确 event 名 + §15 payload（用 any 匹配，避开 transition 内部以 §14 event 名调用的 `_emit_event`）。

## Locked Decisions Honored

- ✅ 复用 `RepoRouterV2.route` + `DeliveryKnowledgeSearchService.search_similar`，未重写路由/检索逻辑。
- ✅ `created_by=None` → fail-closed 空召回（透传 user=None，无伪造 actor，测试断言）。
- ✅ routing/recall_context 仅经 `PlanSessionService` 单一写入入口持久化（INV-6）；engine 不直接 mutate status。
- ✅ `entity_kinds` 映射 knowledge `EntityKind` 实际值（work_item/tech_plan/code_change）。
- ✅ §15 信封事件经 `_emit_event` 钩子产出（真实 sink Phase 41 收口）。

## Guard / Regression

- ✅ `test_engine_does_not_write_status_directly`（源码守护：engine.py 无 `.status=` 直写）持续绿。
- ✅ `makemigrations --check`（全局）退出码 0，无模型/迁移漂移。
- ✅ 全量回归：`tests/delivery/` + plan_orchestration engine + 两 adapter = **286 passed, 0 failed**。

## Migration Status

- `server/delivery/migrations/0011_plansession_routing_recall_created_by.py` — 三 AddField（routing/recall_context/created_by）；`makemigrations --check` 干净。

## Verdict

**PHASE 38 PASSED** — ROUTE-01 + RECALL-01 全部成功标准达成，locked decisions 全部遵守，无回归，迁移干净。
