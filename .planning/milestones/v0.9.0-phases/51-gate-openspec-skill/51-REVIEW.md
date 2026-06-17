---
phase: 51-gate-openspec-skill
reviewed: 2026-06-17T04:16:58Z
depth: deep
files_reviewed: 4
files_reviewed_list:
  - server/delivery/services/repo_coding_task_service.py
  - server/workflows/nodes/ai/coding.py
  - task/core/config.py
  - task/core/executor.py
findings:
  critical: 0
  warning: 1
  info: 2
  total: 3
status: issues_found
---

# Phase 51: Code Review Report

**Reviewed:** 2026-06-17T04:16:58Z
**Depth:** deep（跨文件追踪 gate → service → wave_progression → task executor 调用链）
**Files Reviewed:** 4（源码）+ 6（对应测试，作为佐证阅读，未计入计分）
**Status:** issues_found（无 BLOCKER；1 WARNING + 2 INFO 均为健壮性/防御性，不阻断发布）

## Summary

审查 Phase 51「编码前置 gate + openspec skill 编码策略」的 4 个源码改动，沿
`_dispatch_wave → _apply_openspec_gate → service.mark_gate_blocked → aadvance_coding_waves`
（传递闭包阻断）与 `_run_repo_coding → DispatchTask.metadata → TaskConfig.follow_openspec
→ _get_system_prompt` 两条链做了跨文件追踪，并实跑全部相关测试（server 34 passed / task 28 passed）。

核心安全/正确性属性全部成立，**未发现 BLOCKER**：

- **gate fail-closed 正确**：`follow_openspec=True` 仓在「无 spec / draft / in_review /
  implemented / 查询异常」全路径均不放行（拦截 `spec_not_approved` / `gate_error`），仅
  `APPROVED` 放行；`follow_openspec=False` 仓直接放行且**完全不触发 SddSpec 查询**（非 SDD 零回归）。
- **单仓 gate 校验隔离不崩 wave**：SddSpec 读取异常被 per-repo `try/except` 捕获（`gate_error`
  fail-closed），不波及其余仓 dispatch（测试 `test_gate_error_fail_closed_isolated` 佐证）。
- **liveness 无死锁**：拦截仓经 `mark_gate_blocked` 标 `failed` → 下一轮 `aadvance_coding_waves`
  Step 2 传递闭包将其全部 pending 下游标 `upstream_failed`（测试 `test_gate_blocked_blocks_downstream`
  得 `all_terminal`）；首发全拦截走 `waiting_sessions=[] + failed` → NodeResult failed；wave 推进
  全拦截走 `_advance` 有界 `for` 循环 `continue` 收敛（max_passes 上界）。
- **`mark_gate_blocked` 幂等收口**：条件更新仅 `pending→failed`（影响 0 行即 no-op），不翻在途/终态；
  唯一写入经 service，INV-6 grep 守护通过（`test_inv6_no_bypass_repo_coding_task_write` 通过）。
- **`follow_openspec` 置位大小写一致**：service `== "SDD"` 与 Phase 48 `sdd_detect._SDD_VALUE="SDD"`
  / `spec_generation` 过滤值逐字一致。
- **async ORM 无裸 lazy-FK**：gate 用 `task.plan_version_id` / `task.repository_id` 标量 + `afirst`；
  service facets 查询在 `@sync_to_async` 同步块内用 `*_id` 标量 `values_list`。
- **env 注入仅 approved SDD 仓不泄漏**：`openspec_env` 仅 `follow_openspec=True` 时含
  `env_FRIDAY_TASK_FOLLOW_OPENSPEC=true`，否则键缺省（`test_env_no_injection_non_sdd` 佐证）。
- **task system_prompt 零回归**：`_get_system_prompt` 的 `base` 与改动前 return 文本逐字相等，
  `follow_openspec=False` 直接返回 `base`；env 默认 False；MagicMock 断言用例已显式置 False。

下列为非阻断的健壮性/防御性观察。

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: gate 的 DB 写入（`mark_gate_blocked`）落在 per-repo `try/except` 隔离边界之外

**File:** `server/workflows/nodes/ai/coding.py:683-711`
**Issue:**
`_apply_openspec_gate` 的 docstring 与块注释声称「单仓 gate 校验抛异常 → ... 异常绝不向外冒泡、
不波及其余仓 dispatch（绝不崩整 wave）」，但 `try/except` 仅包裹了 **SddSpec 读取**
（行 683-701）。拦截写入 `await service.mark_gate_blocked(...)` 与随后的
`repositories.get(...)` / `gate_blocked_failed.append(...)`（行 703-711）落在 `except` 之外。

若 `mark_gate_blocked` 因瞬时 DB 故障抛异常，异常会冒出 `_apply_openspec_gate` →
`_dispatch_wave`，导致**本 wave 中排在该仓之后的其余仓既不被 gate 评估也不被 dispatch**——
与「单仓隔离、绝不崩整 wave」的自述契约不符。在 wave 推进路径上更明显：`_resume_wave` 仅把
`aadvance_coding_waves` 包在 `try` 内，`_dispatch_next_wave`（→ `_dispatch_wave`）未被包裹
（行 928-929），异常会一路冒到节点重入，违反「绝不让节点重入异常回灌使容器回调 5xx」的设计目标。

注意：异常方向是 **fail-closed**（未校验仓不会被放行/dispatch），故**非安全漏洞**，属健壮性/
liveness 退化（一仓的 DB 写抖动会牵连同 wave 其余仓）。现有测试 `test_gate_error_fail_closed_isolated`
只注入了**读取**异常，未覆盖**写入**异常路径，故该缺口未被测试捕获。

**Fix:** 把写入与登记并入隔离边界（与读取同 `try`，或整体包裹 per-repo 循环体）：

```python
for repo_id in repo_ids:
    task = tasks_by_repo.get(repo_id)
    if task is None or not getattr(task, "follow_openspec", False):
        passed_repo_ids.append(repo_id)
        continue
    try:
        blocked_reason = "spec_not_approved"
        spec_status = "missing"
        spec = (
            await SddSpec.objects.filter(
                plan_version_id=task.plan_version_id,
                repository_id=task.repository_id,
            )
            .order_by("-updated_at")
            .afirst()
        )
        if spec is not None and spec.status == SddSpecStatus.APPROVED:
            passed_repo_ids.append(repo_id)
            continue
        spec_status = str(spec.status) if spec is not None else "missing"
        await service.mark_gate_blocked(task, blocked_reason, spec_status)
    except Exception as exc:  # noqa: BLE001 — gate fail-closed 隔离，绝不崩整 wave
        log.warning("coding_openspec_gate_error", repo_id=repo_id, error=str(exc))
        blocked_reason = "gate_error"
        # 写入失败时尽力补标终态（再失败则 swallow，靠 aadvance 兜底回填/收尾）
        try:
            await service.mark_gate_blocked(task, blocked_reason, "unknown")
        except Exception:  # noqa: BLE001
            pass
    repo = repositories.get(repo_id)
    gate_blocked_failed.append({...})
```

（关键改动：`mark_gate_blocked` 的首次写入移入 `try`，写入异常也走 fail-closed 隔离，
保证「同 wave 其余仓不受单仓写抖动牵连」。）

## Info

### IN-01: `task is None` 分支为 fail-open 放行（与 fail-closed 主旨方向相反）

**File:** `server/workflows/nodes/ai/coding.py:676-679`
**Issue:**
gate 对 `task is None` 的仓直接 `passed_repo_ids.append(repo_id)` 放行（注释「无 task 理论不应
发生 → 放行」）。这是**唯一一处 fail-open**：若某 SDD 仓因时序/数据异常缺失 task 对象，会被当作
非 SDD 放行（且因 dispatch 侧 `follow_openspec` 同样取自 task → 不注入 env，至少不会误注入）。
实际不可达——wave 模式下 `tasks_by_repo` 恒覆盖 dispatch 批次的全部仓（首发来自
`create_tasks_for_plan`，推进来自 `_dispatch_next_wave` 的 `dispatch` 批），故为纯防御性观察。

**Fix（可选，加固而非必须）:** 鉴于本 phase 的 fail-closed 强约束，可将 `task is None` 视为异常态
拦截（`mark_*`/记一条 warning）而非放行；或保留现状但在注释中明确「该分支放行仅因 None 不可达，
非 SDD 判定依据是 `follow_openspec` 而非 None」。

### IN-02: `mark_gate_blocked` 返回的影响行数被调用方丢弃

**File:** `server/workflows/nodes/ai/coding.py:703` ／ `server/delivery/services/repo_coding_task_service.py:161-180`
**Issue:**
`mark_gate_blocked` 文档化「返回影响行数」（条件更新 `pending→failed`，0 即 no-op），但
`_apply_openspec_gate` 丢弃返回值，无条件把该仓登记进 `gate_blocked_failed`。在 dispatch 路径上
进入 gate 的 task 恒为 pending（首发全新 pending；推进批来自 `_collect_dispatchable_pending`
的 pending），故返回值恒为 1，当前无实际错配。仅作为「返回值语义未被消费」的一致性提示——
若未来 gate 被复用于可能非 pending 的 task 场景，无条件登记会与「实际是否被本次拦截」脱节。

**Fix（可选）:** 若需严谨，可据返回行数决定是否登记（`if await service.mark_gate_blocked(...)`），
或在 docstring 标注「调用方依赖 dispatch 前置 pending 不变量，故忽略返回值」。

---

_Reviewed: 2026-06-17T04:16:58Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
