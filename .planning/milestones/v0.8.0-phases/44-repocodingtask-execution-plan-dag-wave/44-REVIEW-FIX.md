---
phase: 44-repocodingtask-execution-plan-dag-wave
fixed_at: 2026-06-16T21:30:00Z
review_path: .planning/phases/44-repocodingtask-execution-plan-dag-wave/44-REVIEW.md
iteration: 1
findings_in_scope: 2
fixed: 2
skipped: 0
status: all_fixed
---

# Phase 44: Code Review Fix Report

**Fixed at:** 2026-06-16T21:30:00Z
**Source review:** .planning/phases/44-repocodingtask-execution-plan-dag-wave/44-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 2 (Critical + Warning)
- Fixed: 2
- Skipped: 0

验证：`uv run pytest tests/test_coding_wave.py tests/services/plan_orchestration/ tests/delivery/test_repo_coding_task_service.py` → 21 passed；`uv run ruff check`（改动文件）→ All checks passed。

## Fixed Issues

### WR-01: `build_repo_dep_edges` 不按 `id` 过滤任务，可生成「同 wave 跨仓依赖边」绕过首发派发的 wave 保证

**Files modified:** `server/services/plan_orchestration/wave_layering.py`
**Commit:** 6b82c7f7
**Applied fix:** 在 `build_repo_dep_edges` 的成边循环开头加 `if not t.get("id"): continue`，使其与 `build_repo_waves` 采用同一过滤口径——无 `id` 任务不再贡献仓级 `depends_on` 边。消除「无 id 但有 repository_id+dependencies 的任务抬高边集却不抬高 wave」的不一致，杜绝 wave0 首发段把含依赖仓与其上游仓同批并行 dispatch 的违序窗口。现有 `test_wave_layering.py` 5 例全绿。

### WR-02: 回调并发重入下，wave 派发副作用非幂等（可能重复建容器 / 重复 MR）

**Files modified:** `server/delivery/services/repo_coding_task_service.py`
**Commit:** 55655572
**Applied fix:** 采纳 REVIEW Fix 选项 1——把 `_mark_running_sync` 从无条件 `task.save()` 改为条件更新 `RepoCodingTask.objects.filter(id=..., status=PENDING).update(status=RUNNING, subagent_session=..., updated_at=...)`，并使 `mark_running` 返回影响行数（与 `mark_done` / `mark_blocked` 同范式）。并发 / 重复 dispatch 下仅首个 claim 影响 1 行、其余天然 no-op，状态回填获得幂等保护；返回值供调用方据此判定是否真正建容器。现有 `test_repo_coding_task_service.py` / `test_wave_progression.py` 全绿（用例均从 DB re-read 校验，不依赖内存态突变）。

**requires human verification:** 本项为并发/时序语义修复。已落地的条件守门使「状态回填」幂等，但 REVIEW 同时建议的 Fix 选项 2（dispatch 前以原子 `pending→running` claim 占位后再建容器，或显式验证 Phase 43 续驱对同一 node 的串行性）属架构性改动，未在本次自动修复范围内实施——它需要确认并在注释中记录 Phase 43 回调续驱的节点级串行保证，超出 atomic 单点修复的安全边界。建议开发者据 INV / Phase 43 闭环显式核验：当前实现已依赖回调串行性（`waiting` 判定 keys off RUNNING），条件守门为该前提提供了纵深防御，但若未来出现真正并发重入，仍需 claim-before-dispatch 才能根除重复建容器副作用。

---

_Fixed: 2026-06-16T21:30:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
