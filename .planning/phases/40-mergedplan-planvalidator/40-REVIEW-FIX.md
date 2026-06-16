---
phase: 40-mergedplan-planvalidator
fixed_at: 2026-06-16T11:50:00Z
review_path: .planning/phases/40-mergedplan-planvalidator/40-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 4
skipped: 3
status: all_fixed
---

# Phase 40: Code Review Fix Report

**Fixed at:** 2026-06-16T11:50:00Z
**Source review:** 40-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 4（CR-01 + WR-01 + WR-02 + IN-02）
- Fixed: 4
- Skipped (out of scope / deferred per review): 3（IN-01 自然消解、IN-03、IN-04）

## Fixed Issues

### CR-01: 融合 adapter 缺失 MergedPlan schema 闸口（BLOCKER）

**Files modified:** `server/services/plan_orchestration/architect_merge_adapter.py`, `server/tests/services/test_architect_merge_adapter.py`
**Commit:** 53ff67a62
**Applied fix:**
- `merge()` 在 `validate_plan`（跨仓语义）之前补 `validate_merged_plan`（§7 schema）闸口；schema
  非法（如 execution_plan 项缺 `repository_id`）走 `_handle_fail` 优雅降级（`ArchitectMerge(failed)`
  + `plan.validation.failed` 事件 + §14 限次回退），不再冲到 `create_from` 抛 `PlanContentInvalid`
  冒泡到 engine 崩成 terminal failed。
- 防御补强：`_handle_pass` 内 `create_from` 包 `try/except PlanContentInvalid`，schema 漂移再失败
  亦转验证失败回退，绝不 terminal。
- 新增测试：schema 非法 MergedPlan → 直接 merge 与端到端 engine.advance 均按验证失败回退
  （clarifying，非 failed）；create_from 漂移亦优雅降级。

**Verification:** logic + schema-gate 行为，已被新增单测覆盖（含 e2e 回退断言）。

### WR-01: 空 execution_plan 通过全部校验

**Files modified:** `server/services/plan_orchestration/plan_validator.py`, `server/tests/services/test_plan_validator.py`
**Commit:** 3fba2d194
**Applied fix:** 新增 `_check_non_empty_plan`：空/缺 `execution_plan` → `non_empty_plan` 校验 error，
走融合失败优雅降级路径（「架构师不只是更贵的总结器」）。新增测试：空 + 缺 execution_plan → error。

### WR-02: 形状非法的跨仓字段被静默降级为空（false-pass）

**Files modified:** `server/services/plan_orchestration/plan_validator.py`, `server/tests/services/test_plan_validator.py`
**Commit:** 9cd1919a1
**Applied fix:** 新增 `_check_field_shapes`：`dependency_dag`/`data_migrations`/`release_order`
「存在但类型不符」时记 error（区分「缺省跳过」vs「形状非法」），坏形状不再无声降级为空跳过环/迁移/
发布校验。新增测试：malformed dependency_dag / data_migrations / release_order → 校验 error。

### IN-02: `_handle_pass` 三步非原子，失败可留孤儿 canonical

**Files modified:** `server/services/plan_orchestration/architect_merge_adapter.py`（随 CR-01 提交）
**Commit:** 53ff67a62
**Applied fix:** 调整 `_handle_pass` 顺序——`create_from` 后先落 `ArchitectMerge(passed)`（引用
version_id）再置 `session.current_plan_version`，使后续步骤失败也不致留「canonical 孤儿 + 无
ArchitectMerge 记录」。与 CR-01 同属 `_handle_pass` 通过路径加固，物理耦合（共享 `has_stale`
签名），故合并一次提交。

## Skipped Issues

### IN-01: `validate_merged_plan` 运行路径零调用
**Reason:** 随 CR-01 自然消解——schema 闸口已在 adapter 接线，无需独立改动。

### IN-03: 降级 report 落 `str(exc)` 入库
**Reason:** review 评级风险低（非外暴露面，事件层 INV-5 已不外泄）；按 instructions 仅作可选项，未处理。

### IN-04: `attempt` 经 `acount()` 与并发融合非原子
**Reason:** review 明确「更严格非风险、不构成无限循环」；instructions 显式要求跳过。

---

_Fixed: 2026-06-16T11:50:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_

> 注：本次在主工作树（`main`）上直接做了每个 finding 的原子提交（而非临时 worktree）——
> 因临时 worktree 缺少 `server/.venv`（项目为可编辑安装，worktree 内跑测会指向 main 而非 worktree
> 代码），无法正确执行「针对修复跑测」的强制步骤；且工作树仅有一个未跟踪的 planning 文档、无并发写入者。
> 最终结果（main 上的原子提交）与 worktree cleanup tail fast-forward 等价。
