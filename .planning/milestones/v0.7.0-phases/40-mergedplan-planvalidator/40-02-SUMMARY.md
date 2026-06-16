---
phase: 40-mergedplan-planvalidator
plan: 02
subsystem: plan_orchestration / delivery
tags: [adapter, llm-synthesizer, engine-wiring, inv6-guard, events]
requires:
  - 40-01 ArchitectMerge model + validate_plan + validate_merged_plan
  - delivery.TechnicalPlanService.create_from (Phase 37, INV-6)
  - delivery.PlanSessionService.transition (Phase 36)
  - services.plan_orchestration.engine (Phase 36)
provides:
  - services.plan_orchestration.ArchitectMergeAdapter (MergeProtocol)
  - services.plan_orchestration.MergedPlanSynthesizer / LLMMergedPlanSynthesizer
  - PlanSessionService.set_current_plan_version
  - engine._merge §14 三分支接线
affects:
  - Phase 41 (clarification 回路 / 事件 sink / 工作流入口)
tech-stack:
  added: []
  patterns:
    - 可注入 Protocol synthesizer + 默认 LLM 实现 (38/39 范式)
    - LLM 合成异常 graceful 降级 (落 failed report, 不上抛)
    - async 防裸 lazy-FK (.values/afirst/acount/aexists + *_id 标量)
    - 限次回退防无限循环 (MAX_MERGE_RETRIES=1)
    - INV-6 grep 守护 (ArchitectMerge 唯一 writer)
    - engine 纯度 (仅 transition, 不写 status)
key-files:
  created:
    - server/services/plan_orchestration/architect_merge_adapter.py
    - server/tests/services/test_architect_merge_adapter.py
    - server/tests/services/test_plan_orchestration_engine_merge.py
    - server/tests/delivery/test_architect_merge_inv6_guard.py
  modified:
    - server/services/plan_orchestration/engine.py
    - server/services/plan_orchestration/__init__.py
    - server/delivery/services/plan_session_service.py
    - server/tests/services/test_plan_orchestration_engine.py
decisions:
  - 架构师 = server 端可注入 LLM 合成 (非容器); 真实 LLM E2E deferred (mock 覆盖)
  - back_target 判定: partial stale/缺 → researching; 否则默认 clarifying
  - MAX_MERGE_RETRIES=1 落 engine + adapter 双常量 (engine 据 adapter attempt 判限次)
  - set_current_plan_version 窄方法落 PlanSessionService (不旁路模型写)
metrics:
  duration: ~18min
  completed: 2026-06-16
---

# Phase 40 Plan 02: ArchitectMergeAdapter + engine 接线 Summary

实现 reduce 段真实融合接线（MERGE-01/02/03）：`ArchitectMergeAdapter` 收齐 valid `PartialPlan` → 注入 LLM 合成器产 §7 MergedPlan → `PlanValidator`；通过经 `TechnicalPlanService.create_from(origin="orchestration")` 落 canonical + 置 `current_plan_version` + `ArchitectMerge(passed)`，失败落 `ArchitectMerge(failed)` 不落 canonical。`engine._merge` 据结果 §14 转移：pass→done、fail→限次回退 clarifying/researching、超限→failed 终态。

## What Was Built

- **ArchitectMergeAdapter（MergeProtocol）**：pass/fail/降级三路径，async 全程 `*_id`/`.values()`/`afirst`/`acount`/`aexists` 防裸 lazy-FK（规避 Phase 38 CR-01）。canonical 仅经 `TechnicalPlanService`（INV-6），`ArchitectMerge` 仅经本 adapter 写入（INV-6 grep 守护）。INV-2：`work_item_id` None 时 `create_from(work_item=None)` 合法。§15 事件 `plan.merge.started`/`plan.merge.completed`/`plan.validation.failed`。
- **MergedPlanSynthesizer 协议 + LLMMergedPlanSynthesizer**：可注入；默认实现经 `ProviderConfigService.aresolve` + `build_chat_model` + `ainvoke` + 健壮 JSON 解析（取首{末}、不 eval）。真实 LLM E2E deferred，单测全用 mock。合成失败抛异常 → adapter 捕获降级。
- **PlanSessionService.set_current_plan_version**：窄方法，条件 `update()` + 同步内存态（不旁路模型写）。
- **engine._merge 接线**：§14 三分支，纯 transition（engine 纯度守护绿）；`MAX_MERGE_RETRIES=1`；`ConcurrentTransitionError` 良性 no-op。

## Tasks Completed

| Task | Name | Commit |
|------|------|--------|
| 1 | ArchitectMergeAdapter + 可注入 MergedPlanSynthesizer（TDD） | feat(40-02) ArchitectMergeAdapter |
| 2 | engine._merge 接线（pass/fail/限次回退）（含既有测试契约更新） | feat(40-02) wire engine._merge |
| 3 | ArchitectMerge INV-6 grep 守护 + 融合段端到端集成 | test(40-02) INV-6 guard + e2e |

## Verification

- `makemigrations --check --dry-run`（全仓）：No changes detected ✓
- `pytest tests/services/test_architect_merge_adapter.py`：6 passed（pass/fail/降级/INV-2 + e2e pass/fail-reclarify）
- `pytest tests/services/test_plan_orchestration_engine_merge.py`：5 passed
- `pytest tests/delivery/test_architect_merge_inv6_guard.py`：2 passed
- `ruff check`（adapter + engine + service + 测试）：All checks passed
- 全回归：`tests/delivery` + plan_orchestration 套件 **346 passed**，无回退（含既有 INV-6/纯度守护）

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - 契约变更] 更新既有 engine 测试 merge mock**
- **Found during:** Task 2（engine._merge 接线后）
- **Issue:** `test_plan_orchestration_engine.py::test_injected_protocol_mocks_called` 的 `merge.merge` 返回 `{}`（旧占位契约 → 直接 done）；新 `_merge` 按 `validation_status` 分派，`{}` → 视为非 passed → 回退 clarifying，断言失败。
- **Fix:** 把该 mock 返回值改为 `{"validation_status": "passed", "attempt": 0}`（对齐 Phase 40 merge adapter 返回契约），merging→done 断言恢复有效。
- **Files modified:** server/tests/services/test_plan_orchestration_engine.py
- **Commit:** feat(40-02) wire engine._merge

**2. [无需处理] TechnicalPlanOrigin.ORCHESTRATION 已存在**
- 40-02 action 提到「若 TechnicalPlanOrigin 无 orchestration 则补 + makemigrations」——实测已存在（Phase 37 已含），无需改动 / 无新增迁移。

## Known Stubs

- **真实 LLM 合成 E2E**：`LLMMergedPlanSynthesizer.synthesize` 真实容器/真实模型路径 deferred（对齐 39-04），本 phase 仅构造 + mock 单测覆盖。逻辑（pass/fail/降级/限次回退/事件）已由 mock synthesizer 全路径验证。Phase 41 工作流入口端到端跑通时收口真实 sink。

## Self-Check: PASSED

- 文件均存在（architect_merge_adapter.py + 3 测试 + engine/service/__init__ 改动）
- 5 个 plan commit 均落库
- `from services.plan_orchestration import ArchitectMergeAdapter` 可导入（测试已验证）
