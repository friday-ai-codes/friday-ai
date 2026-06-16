---
phase: 39-parallel-research
plan: 03
subsystem: plan_orchestration
tags: [adapter, fan-out, dispatch, filter_then_container]
requires: [delivery.ResearchService, runners.dispatcher, subagent.SubAgentSession, PlanSession.routing]
provides: [services.plan_orchestration.ResearchDispatchAdapter]
affects: [39-04]
key-files:
  created:
    - server/services/plan_orchestration/research_adapter.py
    - server/tests/services/test_research_adapter.py
  modified:
    - server/services/plan_orchestration/__init__.py
decisions:
  - "deep_confidence={high,medium} 起容器，low/降级走轻量 server 端合成 PartialPlan（省资源）"
  - "复用 DispatchTask(task_type=plan)+get_dispatcher+SubAgentSession(PLAN)，env explore 只读"
  - "runner 离线不重试循环，deep 仓降级轻量，编排不挂死（runner_offline=True）"
  - "_count_online_runners 提为方法便于测试注入（patch.object）"
metrics:
  duration: ~7m
  completed: 2026-06-16
---

# Phase 39 Plan 03: ResearchDispatchAdapter Summary

立 `ResearchDispatchAdapter(ResearchProtocol)`：filter_then_container 核心调度器——server
端快筛 routing 候选，high/medium 仓 fan-out 独立 claude code 容器（上下文隔离）+ 经
ResearchService 建 task/回填 running，low 仓走轻量 server 端 PartialPlan 省资源；复用既有
容器底座（DispatchTask/get_dispatcher/SubAgentSession），emit repo.research.started。

## Tasks
1. ResearchDispatchAdapter（filter + fan-out + 轻量合成 + prompt 注入 + 凭证）+ re-export — commit (adapter)
2. 全 mock dispatch 单测（7）— commit d941ad2

## Tests
- `tests/services/test_research_adapter.py`：7 passed（全 mock dispatcher/runner，真实容器 E2E DEFERRED）
- 覆盖：filter 分流 / 容器回填 running / prompt 注入 §7 / no-candidates no-op / runner offline 降级 / started 事件 / service 写入
- ruff line 100：通过

## Deviations from Plan
- None — 按 plan 调度契约实现；凭证/runtime 解析包 try/except best-effort（缺凭证不阻断调度，容器内自报错）。

## Self-Check: PASSED
- FOUND: server/services/plan_orchestration/research_adapter.py
- FOUND commit d941ad2 + adapter commit
