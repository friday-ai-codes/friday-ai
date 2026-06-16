---
phase: 36-plansession
plan: 03
subsystem: services
tags: [ORCH-01, plan-orchestration, engine, injectable-protocols, entry-agnostic]
requires: [36-02]
provides:
  - "PlanOrchestrationEngine.advance 状态驱动推进器（入口无关）"
  - "可注入 stage 协议 + 骨架默认实现"
affects: []
tech-stack:
  added: []
  patterns: ["state-driven step advancer", "typing.Protocol injectable deps + skeleton defaults", "transition-driven (no direct status write)"]
key-files:
  created:
    - server/services/plan_orchestration/__init__.py
    - server/services/plan_orchestration/protocols.py
    - server/services/plan_orchestration/engine.py
    - server/tests/services/test_plan_orchestration_engine.py
  modified: []
decisions:
  - "依赖注入用 typing.Protocol + Skeleton* 骨架默认实现（38-41 逐步替换且单测可 mock）"
  - "engine 经 PlanSessionService.transition 驱动转移，绝不直接写 status"
  - "骨架 NotImplementedError 上抛（不吞 failed）；普通异常落 failed"
metrics:
  duration: "~20m"
  completed: 2026-06-16
---

# Phase 36 Plan 03: 编排 engine 骨架 Summary

立可复用的 `ai_plan_research` 编排 engine 抽象（ORCH-01）：状态驱动 step 推进器 `PlanOrchestrationEngine.advance(session)`，工作流与 Chat 共用同一底层（入口无关 + 可注入依赖），按 `session.status` 分派 stage handler，经 `PlanSessionService.transition` 驱动转移，从任意持久化 status resume。

## What Was Built

- **package** `server/services/plan_orchestration/`（service 层）。
- **protocols.py**：`RouterProtocol/RecallProtocol/ResearchProtocol/MergeProtocol`（`typing.Protocol`，方法均 async，窄接口以 `session` 为主入参）+ 骨架默认实现 `SkeletonRouter/SkeletonRecall/SkeletonResearch/SkeletonMerge`（对应方法 `raise NotImplementedError` 带接入 phase TODO）。
- **engine.py** `PlanOrchestrationEngine`：
  - `__init__(*, session_service, router, recall, research, merge)` 依赖注入；缺省骨架；不接收任何 workflow/chat IO（入口无关）。
  - `advance(session)`：按 status 分派 `_decompose/_route/_recall/_clarify/_research/_merge`；done/failed 终态 no-op；try/except —— NotImplementedError 原样上抛、普通异常经 `transition(session,"fail",error={stage,exception,message})` 落 failed。
  - `_decompose` 最小真实实现（requirement_text/include_repos → segments 按非空行切分），经 transition `decomposed`→routing；其余 stage 调注入依赖后经 transition 推进对应 event；`_clarify` 最小 pass-through。
  - 全 async，ORM 经 async ORM（`afirst`）；**engine.py 无 `.status=` 直接赋值**（守 36-02 INV-6）。
- **测试**：advance(decomposing→routing 真实拆分) / 任意 status resume / 注入 mock 被调（recall/research/merge）/ clarify pass-through / 源码守护 engine 无直接 status 写 / 骨架 NotImplementedError 上抛 / 普通异常落 failed。

## Deviations from Plan

None - plan executed exactly as written.

## Verification Evidence

- `pytest tests/services/test_plan_orchestration_engine.py` → **7 passed**；与 INV-6 守护合跑 → **9 passed**（engine 未触发 36-02 PlanSession 旁路写守护）。
- `python -c "from services.plan_orchestration import PlanOrchestrationEngine; from services.plan_orchestration.protocols import SkeletonRouter"` → **IMPORT OK**。
- `rg -n "\.status\s*=" services/plan_orchestration/engine.py` → **NO DIRECT STATUS WRITE**。
- `ruff format --check services/plan_orchestration/` → 通过。

## Success Criteria

- ✅ 成功标准 4（ORCH-01）：可复用编排 engine 抽象就位，驱动流水线推进，工作流与 Chat 可共用同一底层（入口无关 + 可注入依赖）。

## Self-Check: PASSED
- FOUND: server/services/plan_orchestration/{__init__,protocols,engine}.py
- FOUND commits f0e8bfeba, c54e0af9f
