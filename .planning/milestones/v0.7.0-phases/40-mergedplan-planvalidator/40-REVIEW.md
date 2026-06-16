---
phase: 40-mergedplan-planvalidator
reviewed: 2026-06-16T11:40:00Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - server/delivery/models/architect_merge.py
  - server/delivery/migrations/0014_architectmerge.py
  - server/delivery/models/__init__.py
  - server/services/plan_orchestration/merged_plan.py
  - server/services/plan_orchestration/plan_validator.py
  - server/services/plan_orchestration/architect_merge_adapter.py
  - server/services/plan_orchestration/engine.py
  - server/services/plan_orchestration/__init__.py
  - server/delivery/services/plan_session_service.py
findings:
  critical: 1
  warning: 2
  info: 4
  total: 7
status: fixed
fixed_at: 2026-06-16T11:50:00Z
fix_report: 40-REVIEW-FIX.md
resolved:
  - CR-01  # 融合 adapter 接入 §7 schema 闸口 + _handle_pass 防御兜底
  - WR-01  # PlanValidator 拦空 execution_plan
  - WR-02  # PlanValidator 跨仓字段形状非法记 error（防 false-pass）
  - IN-02  # _handle_pass 先记 ArchitectMerge 再置指针（防孤儿 canonical）
deferred:
  - IN-01  # 随 CR-01 自然消解（schema 闸口已接线）
  - IN-03  # str(exc) 入库脱敏（可选，风险低，未处理）
  - IN-04  # acount() 并发非原子（更严格非风险，按 review 跳过）
---

# Phase 40: Code Review Report

**Reviewed:** 2026-06-16T11:40:00Z
**Depth:** standard
**Files Reviewed:** 9
**Status:** findings_found

## Summary

审查 Phase 40 reduce 段实现（ArchitectMerge 模型 + migration 0014、MergedPlan §7 schema、PlanValidator 5 项跨仓校验、ArchitectMergeAdapter 融合接线、engine._merge 限次回退、set_current_plan_version）。

整体质量高：DOMAIN §6/§7/§14/§15 落得扎实，async ORM 全程 `*_id`/`.values()`/`afirst`/`acount`/`aexists`（成功规避 Phase 38 CR-01 lazy-FK bug 类），INV-6 落库唯一入口、engine 纯度（仅 transition）、§15 事件不含 CoT/密钥（INV-5）均到位。环检测（DFS 三色 + 自环）正确——**循环 dependency_dag 确实被拒，不存在该项 false-pass**；限次回退 **attempt 计数持久化 + 超限前置检查正确，无 off-by-one、无无限循环**；validate_plan 失败分支**不调 create_from、不落 partial canonical**（特别关注项 (b)(c) 通过）。

但发现 **1 个 BLOCKER**：融合 adapter **跳过了 MergedPlan schema 闸口**（`validate_merged_plan` 在运行路径从未被调用），导致一类「schema 非法但跨仓校验通过」的 LLM 产物会在 `create_from` 内抛 `PlanContentInvalid` 未被捕获，冲到 engine 通用 except 落 **terminal failed**，而非按设计走 `ArchitectMerge(failed)` + §14 限次回退——这恰是特别关注项「malformed MergedPlan from LLM → validation errors not crash」与「LLM 降级不崩」契约的破口。另有 2 个 false-pass 风险的 WARNING。

## Critical Issues

### CR-01: 融合 adapter 缺失 MergedPlan schema 闸口 —— schema 非法产物绕过优雅降级，崩成 terminal failed

**File:** `server/services/plan_orchestration/architect_merge_adapter.py:160-175`
**Issue:**
`merge()` 在合成后仅调用 `validate_plan(merged)`（PlanValidator，**跨仓语义**校验），**从未调用 `validate_merged_plan`（§7 schema 校验）**——经 grep 确认 `validate_merged_plan` 仅存在于 `__init__.py` re-export、`merged_plan.py` 定义与测试，**运行路径零调用**。

`validate_plan`（`plan_validator.py`）对 execution_plan **项级 schema 不做任何强校验**：`_check_contract_consistency` / `_check_rollback_completeness` 用 `task.get("repository_id")`，缺失即静默跳过，不报 error。因此一份「某 execution_plan 项缺 `repository_id`/`name`/`branch_strategy`，但跨仓 dag 无环、契约一致、回滚覆盖其余仓」的 MergedPlan 会得到 `valid=True` →进入 `_handle_pass`：

```python
report = validate_plan(merged)          # 跨仓语义 OK → valid=True
if report.get("valid"):
    return await self._handle_pass(...)  # 直接落 canonical
```

`_handle_pass` 调 `create_from(...)`（line 173，**无 try/except**）。`TechnicalPlanService.create_from` 内 `validate_technical_plan` 此时才发现 schema 非法 → `raise PlanContentInvalid`。该异常**未在 adapter 捕获**，逐层冒泡到 `engine.advance` 的通用 `except Exception` → `transition("fail")` 落 **failed 终态**。

后果（违反 MERGE-02 / §14 设计）：
- 一个**可恢复**的验证失败被错误地变成**不可恢复**的 terminal failed（应走 §14 回退 clarifying/researching + 限次重试）。
- **不写 ArchitectMerge 行**（attempt 计数缺失）、**不发 `plan.validation.failed` 事件**——融合记账与可观测性丢失。
- `merged_plan.py` 的设计承诺「过 `validate_merged_plan` 的 content 必能过 create_from 内的 `validate_technical_plan`」是对的，但 adapter 调的是 `validate_plan`（另一个函数），承诺链断裂。

该类输入未被任何测试覆盖（现有 fail 测试用「成环 dag」——schema 合法但跨仓非法，走的是 `_handle_fail` 正确路径）。

**Fix:** 在合成后、`validate_plan` 之前补 schema 闸口，使 schema 非法走与 PlanValidator 失败相同的优雅降级分支：

```python
# 5. schema 闸口（§7）—— 保证后续 create_from 不二次失败
from services.plan_orchestration.merged_plan import validate_merged_plan
schema_ok, schema_err = validate_merged_plan(merged)
if not schema_ok:
    report = {"valid": False, "errors": [{"check": "schema", "message": schema_err}]}
    return await self._handle_fail(session, report, attempt, has_stale)

# 6. PlanValidator（跨仓语义）
report = validate_plan(merged)
if report.get("valid"):
    return await self._handle_pass(session, merged, report, attempt)
return await self._handle_fail(session, report, attempt, has_stale)
```

（防御性补强：可同时在 `_handle_pass` 内 `try/except PlanContentInvalid` 兜底，避免任何未来 create_from 校验漂移再次崩到 terminal。）

## Warnings

### WR-01: 空 `execution_plan` 通过全部校验 —— 零任务「主方案」被当 canonical 落库并 done

**File:** `server/services/plan_orchestration/plan_validator.py:79-81`, `server/services/plan_orchestration/merged_plan.py:54-59`
**Issue:**
`validate_technical_plan` 的 JSON Schema 对 `execution_plan` 只要求 `type: array`，**无 `minItems`**（见 `workflows/schemas/technical_plan.py:96-99`），故 `{"title","summary","execution_plan": []}` schema **通过**。`validate_plan` 对空 execution_plan 也不报错：`_check_rollback_completeness` 的 `required` 集为空 → 直接 `return [], []`；其余检查均空集跳过。

结果：架构师产出**零可执行任务**的 MergedPlan（只要 `rollback_plan` 非空）会同时过 `validate_merged_plan` 与 `validate_plan` → 落 canonical、置 `current_plan_version`、`ArchitectMerge(passed)`、session→done。这正是 PlanValidator 要防的「架构师只是更贵的总结器」场景的反例（40-01 Task 2 behavior 亦声明「execution_plan 为空 → (False, ...)」，但实现未兑现）。

**Fix:** 在 `validate_plan` 增一项非空校验（或在 `validate_merged_plan` 显式拦空），例如：

```python
def _check_non_empty_plan(merged: dict) -> tuple[list[dict], list[dict]]:
    if not _execution_plan(merged):
        return [{"check": "rollback_completeness",
                 "message": "execution_plan 为空（无可执行任务）"}], []
    return [], []
```

并把它纳入 `validate_plan` 的 checks 元组（或给 `MERGED_PLAN_JSON` 加 `minItems: 1`）。

### WR-02: 形状非法的跨仓字段被静默降级为空 —— 校验整项跳过，false-pass

**File:** `server/services/plan_orchestration/plan_validator.py:84-96, 221-224, 249-252`
**Issue:**
半可信防御把**类型不符**的字段一律当空处理：`_dependency_dag` 对非 dict 的 `dependency_dag` 返回 `{}`；`_check_migration_order` 对非 list 的 `data_migrations` 直接 `return [], []`；`_check_release_order` 对非 list 的 `release_order` 当空。若 LLM 把 `dependency_dag` 产成**边列表**（`[["a","b"],...]`）或其他非约定 dict 形状，`_check_acyclic`/`_check_migration_order`/`_check_release_order` 会**全部静默跳过**——一份真实成环/顺序倒置的方案因「形状不对」反而过验。defensive-by-coercion 把「结构非法」误判为「无违例」。

**Fix:** 区分「字段缺省（跳过）」与「字段存在但形状非法（应记 warning/error）」。例如 `dependency_dag` 存在但非 dict 时追加一条 `{"check": "dependency_cycle", "message": "dependency_dag 形状非法（非邻接表 dict），跨仓校验已跳过"}` warning（或 error），让坏形状不再无声通过。

## Info

### IN-01: `validate_merged_plan` 运行路径零调用（仅 re-export + 测试）

**File:** `server/services/plan_orchestration/merged_plan.py:44`, `server/services/plan_orchestration/__init__.py`
**Issue:** 见 CR-01——schema 闸口在融合流水线中实际未接线，运行时 schema 覆盖仅靠 `create_from` 内的 `validate_technical_plan`（且时机在 PlanValidator 之后、降级保护之外）。修了 CR-01 后此项自然消解。
**Fix:** 随 CR-01 在 adapter 接入 `validate_merged_plan` 即可。

### IN-02: `_handle_pass` 三步非原子，失败可留孤儿 canonical

**File:** `server/services/plan_orchestration/architect_merge_adapter.py:170-183`
**Issue:** `create_from`（自身 atomic 并已 commit）→ `set_current_plan_version` → `_record_merge` 为三个独立 await，彼此非原子。若 `set_current_plan_version` 或 `_record_merge` 抛错，已提交的 canonical `PlanVersion` 成孤儿（session 指针未置、无 ArchitectMerge 记账），且异常冒泡到 engine 落 failed。概率低（均为简单 update/insert），但属一致性边角。
**Fix:** 可接受现状（记录于此）；若需强一致，将 set_current_plan_version + _record_merge 收进一个 `sync_to_async` + `transaction.atomic` 块。

### IN-03: 降级 report 落 `str(exc)` 入库（ArchitectMerge.validation_report）

**File:** `server/services/plan_orchestration/architect_merge_adapter.py:147`
**Issue:** synthesis 失败时 `report = {"reason": "synthesis_failed", "error": str(exc)}` 写入 DB。事件仅发 `{"reasons": ["synthesis_failed"]}`（INV-5 OK，不外泄），但 provider/LLM 客户端异常串可能含 endpoint/诊断细节。非外暴露面，风险低。
**Fix:** 可选——入库前对 error 串做长度截断/脱敏（与 §9 敏感清理精神一致）。

### IN-04: `attempt` 经 `acount()` 计算，与并发融合非原子

**File:** `server/services/plan_orchestration/architect_merge_adapter.py:132`
**Issue:** `attempt = ArchitectMerge.objects.filter(session_id=).acount()` 与并发 merge() 非原子；两个并发 merge 可读到同一 count。但 merging 段无 fan-out 并发，且 `transition` 的 `ConcurrentTransitionError` 守护使只有一个 advance 能推进——净效果是「更严格」而非绕过限次，不构成无限循环风险。仅记录。
**Fix:** 无需处理；若未来 merging 引入并发，可改用 DB 侧原子序号或行锁。

---

_Reviewed: 2026-06-16T11:40:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
