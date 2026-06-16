---
phase: 40-mergedplan-planvalidator
status: passed
verified: 2026-06-16
verifier: gsd-executor (goal-backward)
real_llm_e2e: deferred
---

# Phase 40 Verification — 架构师融合 + MergedPlan + PlanValidator + 跨仓依赖

> 方法：goal-backward——从 phase 目标（编排 reduce 段：架构师融合产结构化 MergedPlan +
> PlanValidator 拦截低质量方案 + 跨仓依赖显式建模 + §15 事件，落 canonical 经 INV-6）反推
> 每条成功标准是否由实现 + 测试坐实。
> **真实 LLM E2E 沿用既有里程碑惯例 DEFERRED**：融合逻辑（pass/fail/降级/限次回退/事件/
> canonical 落库）以 mock synthesizer 全路径覆盖（对齐 39-04 真实容器 E2E deferred）。

## Success Criteria

### SC-1 — 架构师融合 → 结构化 MergedPlan 经 TechnicalPlanService 落 canonical（MERGE-01）✅
- `ArchitectMergeAdapter.merge` 收齐 session 的 valid `PartialPlan`（`.filter(research_task__session_id=, valid=True).values("content")`，async 防裸 lazy-FK）→ 注入 `MergedPlanSynthesizer.synthesize` 产 §7 MergedPlan → `validate_plan` 通过 → `TechnicalPlanService.create_from(origin="orchestration", {"content": merged}, work_item=<by id>)` 落 canonical `PlanVersion` + `set_current_plan_version` 置 `PlanSession.current_plan_version` + `ArchitectMerge(passed, merged_plan_version=...)`。
- INV-6：canonical 仅经 `TechnicalPlanService`（既有 `test_technical_plan_inv6_guard` 绿）；`ArchitectMerge` 仅经本 adapter（新 `test_architect_merge_inv6_guard` 绿）。INV-2：`work_item_id` None（chat）时 `create_from(work_item=None)` 合法。
- **证据**：`test_architect_merge_adapter.py::test_merge_pass_path`（canonical origin=orchestration + current_plan_version 置 + ArchitectMerge passed + merged_plan_version 非空 + plan.merge.started/completed 事件）、`test_merge_inv2_work_item_none`（work_item None pass）、`test_e2e_engine_merge_pass`（engine.advance → done + canonical 闭环）。
- **结论**：PASSED（mock synthesizer；真实 LLM 合成 deferred）。

### SC-2 — PlanValidator 拦截 5 类违例 + failed report + §14 回退（MERGE-02）✅
- `validate_plan`（40-01，纯函数）5 项校验各自命中违例：契约一致性 / 依赖成环（DFS 三色 + 自环）/ 迁移顺序倒置 / 发布顺序违反依赖 / 缺回滚 → `valid=False` + 定位 error；合法 MergedPlan → `valid=True`。半可信输入恒不抛异常（fail-safe）。
- 校验失败 → adapter 不落 canonical + `ArchitectMerge(failed, validation_report=report)` + 返回 `back_target`（partial stale/缺 → researching；否则默认 clarifying）；LLM 合成异常 → graceful 降级（report `synthesis_failed`，back_target=researching，不上抛）。
- engine `_merge` 据 report §14 回退：fail 首次 → `validation_failed_reclarify`(merging→clarifying) / `validation_failed_reresearch`(merging→researching)；`attempt >= MAX_MERGE_RETRIES(1)` → `fail` 终态（`merge_validation_exhausted`，防无限循环）。engine 纯度保持（仅 transition，`test_engine_does_not_write_status_directly` + 本 phase 守护绿）。
- **证据**：`test_plan_validator.py`（5 项违例各 1 例 + 合法全过 + 半可信不崩，9 passed）；`test_architect_merge_adapter.py::test_merge_fail_path`（无 canonical + ArchitectMerge failed + report + plan.validation.failed）、`test_merge_synthesis_failure_degraded`（降级 reason=synthesis_failed 不崩）；`test_plan_orchestration_engine_merge.py`（pass→done / fail→clarifying / fail→researching / 超限→failed reason=merge_validation_exhausted，5 passed）；`test_e2e_engine_merge_fail_reclarify`（端到端回退 clarifying + 无 canonical）。
- **结论**：PASSED。

### SC-3 — 跨仓依赖显式建模（dependency_dag + execution_plan deps）（MERGE-03）✅
- §7 MergedPlan content 含 `dependency_dag`（邻接表 `{repo_id: [dep_repo_id]}`）+ `execution_plan[].dependencies`（task id 列表）；`validate_merged_plan` 经 `validate_technical_plan` 校验 execution_plan 子结构（含 repository_id/coding_instruction/dependencies），保证「过本校验者必过 create_from 内校验」。
- `validate_plan` 的 `_check_acyclic` 合并 dependency_dag + execution_plan deps 统一成有向图检测环（去重边 + 自环显式判环）；`_check_migration_order`/`_check_release_order` 据 dependency_dag 边校验顺序——跨仓拓扑显式落入 canonical content（为 v0.8 wave 编码铺底）。
- **证据**：`test_merged_plan_schema.py`（execution_plan 子结构复用 technical_plan，5 passed）；`test_plan_validator.py::test_dependency_cycle_violation`/`test_migration_order_violation`/`test_release_order_violation`（跨仓拓扑校验命中）；pass 路径 e2e 落 canonical content 含 dependency_dag。
- **结论**：PASSED。

### SC-4 — plan.merge.* / plan.validation.failed §15 事件 ✅
- `plan.merge.started`（payload `{partials:[repo_id...]}`）、`plan.merge.completed`（`{plan_version_id}`）、`plan.validation.failed`（`{reasons:[check...]}`）——均经 `PlanSessionService._emit_event` 钩子，best-effort try/except 不阻断融合。
- **证据**：`test_architect_merge_adapter.py::test_merge_pass_path`（started+completed）、`test_merge_fail_path`（started+validation.failed）、`test_merge_synthesis_failure_degraded`（降级亦发 validation.failed）。
- **结论**：PASSED（事件经 _emit_event 钩子产出；真实 sink 收口 Phase 41）。

## Locked Decisions Honored
- ✅ 架构师 = server 端**可注入 LLM 合成器**（非容器；`MergedPlanSynthesizer` Protocol + `LLMMergedPlanSynthesizer` 默认，单测 mock 可替换；LLM 失败 graceful 降级）。
- ✅ canonical 仅经 `TechnicalPlanService.create_from(origin="orchestration")`（INV-6）；`ArchitectMerge` 仅经融合 adapter（INV-6 grep 守护 `test_architect_merge_inv6_guard` 通过）。
- ✅ INV-2：merged plan → `session.work_item_id` 经 by-id 查（None 合法）。
- ✅ engine 不 mutate status（transition only，纯度守护绿）。
- ✅ 复用 `validate_technical_plan` 作 execution_plan 子校验（PF-02）。
- ✅ PlanValidator 5 项校验（契约一致 / DAG 无环 / 迁移顺序 / 发布顺序 / 回滚完整）。
- ✅ 限次回退（`MAX_MERGE_RETRIES=1`，超限 failed 终态）。
- ✅ §14 验证失败回退（默认 clarifying，partial stale/缺 → researching）。
- ✅ §15 事件 plan.merge.started/completed/plan.validation.failed。
- ✅ **规避 Phase 38 CR-01 async lazy-FK bug 类**：async 全程 `*_id`/`.values()`/`afirst`/`acount`/`aexists`（adapter 不裸访问 lazy-FK）。

## Migration
- delivery `0014_architectmerge`（依赖 0013）已生成并应用；`makemigrations --check --dry-run`（全仓）→ **No changes detected**（零漂移）。`TechnicalPlanOrigin.orchestration` 已存在（Phase 37），无新增迁移。

## Test Summary
- 新增测试：models(4) + merged_plan_schema(5) + plan_validator(9) + adapter incl e2e(6) + engine_merge(5) + inv6_guard(2) = **31 passed**。
- 回归套件（`tests/delivery` + plan_orchestration engine/engine_merge/adapter/merged_plan/plan_validator/research_adapter/research_aggregation）：**346 passed**，无回退（含既有 INV-6 / engine 纯度守护）。
- ruff line 100 全通过。

## Deferred / Notes
- **真实 LLM 合成 E2E DEFERRED**（本地无真实模型凭证；融合 pass/fail/降级/限次回退/事件/canonical 落库逻辑以 mock synthesizer 全覆盖）—— 逻辑已验证，按惯例以 deferred note 通过。Phase 41 工作流入口端到端跑通时收口真实 sink + clarification 回路。

## Verdict: PASSED (real-LLM E2E deferred)
