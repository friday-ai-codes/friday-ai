---
phase: 51-gate-openspec-skill
verified: 2026-06-17T04:14:00Z
status: human_needed
score: 8/8 must-haves verified
overrides_applied: 0
human_verification:

  - test: "真实 runner + Docker 容器 E2E：未批准 spec 的 SDD 仓真实编码派发被 gate 拦截（容器不起、task failed reason=spec_not_approved），已批准仓正常起容器编码"
    expected: "未批准仓无容器产出且操作者可见阻断原因；已批准仓正常产出 PR"
    why_human: "需真实 runner 调度 + Docker 守护进程起容器，自动化测试只覆盖 server 侧派发判定，不实际拉起容器"

  - test: "openspec skill 真实加载：approved SDD 仓容器内 setting_sources=[project] 原生加载仓库内 .claude/skills，且 system_prompt openspec 段被真模型遵循（按 openspec/ 已批准 spec 的 delta 编码）"
    expected: "容器内 claude code 加载到仓库 openspec skill，编码产出遵循已批准 spec delta，不自行扩张范围"
    why_human: "依赖真实容器运行时 + 真模型行为，无法以 grep / 单测验证模型是否真正遵循 openspec 流程"
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: human_needed
---

# Phase 51: 编码前置 gate + openspec skill 编码策略 Verification Report

**Phase Goal:** SDD 仓库编码前强制 spec 已批准，且编码容器遵循 openspec 流程
**Verified:** 2026-06-17T04:14:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

合并 ROADMAP 成功标准（4 条）+ PLAN frontmatter must_haves（去重后映射）。

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | SDD 仓 `create_tasks_for_plan` 置 `follow_openspec=True`，非 SDD=False，漂移幂等回填（GATE-01 来源） | ✓ VERIFIED | `repo_coding_task_service.py:60-90`：按 `Repository.facets.methodology=="SDD"` 标量查置位 + `not created` 漂移回填合并 save；`test_repo_coding_task_service.py` follow_openspec 三组断言通过 |
| 2 | `mark_gate_blocked` 仅 pending→failed + `error={reason, spec_status}`，非 pending no-op（INV-6 单一写入入口） | ✓ VERIFIED | `repo_coding_task_service.py:161-180` 条件 `.filter(status=PENDING).update(status=FAILED, error=...)`，镜像 `mark_blocked` 范式；`test_repo_coding_task_inv6_guard.py` 经 service 正向断言通过 |
| 3 | `follow_openspec=False`/legacy 仓不经 gate、不查 SddSpec 直接放行（成功标准 4 零回归） | ✓ VERIFIED | `coding.py:666-679` service/tasks_by_repo 为空短路 + per-repo False 直接 append 不查 spec；`test_gate_follow_openspec_false_passes_without_spec_query`、`test_gate_legacy_short_circuit`（SddSpec spy 未调用）通过 |
| 4 | `follow_openspec=True` 且关联 `SddSpec(plan_version_id, repository_id, status=APPROVED)` 存在 → 放行 dispatch（成功标准 2） | ✓ VERIFIED | `coding.py:683-694` `afirst` + `spec.status==SddSpecStatus.APPROVED` 放行；`test_gate_approved_passes` 通过；`SddSpecStatus.APPROVED` 存在（`sdd_spec.py:35`） |
| 5 | 未批准（无 spec / draft / in_review / 非 approved）→ `mark_gate_blocked` 拦截不 dispatch，reason=spec_not_approved，如实标注阻断原因（成功标准 1） | ✓ VERIFIED | `coding.py:695-711` 拦截 + spec_status 落库 + 并入 failed 返回；`test_gate_unapproved_blocked`（参数化多态）通过 |
| 6 | gate 拦截仓视同 failed → `aadvance_coding_waves` 传递闭包阻断下游（liveness 不死锁） | ✓ VERIFIED | `coding.py:635-638` gate_blocked_failed 并入 failed 返回；`test_gate_blocked_blocks_downstream` 验证下游 upstream_failed 通过 |
| 7 | gate 校验异常 → fail-closed（reason=gate_error + warning），单仓 try/except 隔离不崩整 wave（成功标准 1 安全边界） | ✓ VERIFIED | `coding.py:697-703` `except Exception` 转 gate_error + log.warning（仅 repo_id/error）；`test_gate_error_fail_closed_isolated` 验证其余仓正常 dispatch 通过 |
| 8 | GATE-02 注入链路：approved SDD 仓 dispatch 注入 `env_FRIDAY_TASK_FOLLOW_OPENSPEC=true`；task `TaskConfig.follow_openspec` 读 env；`_get_system_prompt` 追加 openspec 段；非 SDD/缺省零回归（成功标准 3） | ✓ VERIFIED | server `coding.py:1582-1608` 逐键 openspec_env 并入 metadata；task `config.py:111-114` env 映射字段；`executor.py:832-847` 条件追加 `_openspec_guidance`；`setting_sources=["project"]`（`executor.py:578`）原生加载 `.claude/skills`；`test_env_injection_sdd_repo`/`test_env_no_injection_non_sdd`/`test_openspec_prompt.py`/`test_config.py` 通过 |

**Score:** 8/8 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/delivery/services/repo_coding_task_service.py` | follow_openspec 置位 + `_mark_gate_blocked_sync` | ✓ VERIFIED | 含 `def _mark_gate_blocked_sync`（:173）+ follow_openspec defaults/漂移回填（:60-90） |
| `server/workflows/nodes/ai/coding.py` | `_apply_openspec_gate` + env 注入 | ✓ VERIFIED | helper（:640-713）+ `env_FRIDAY_TASK_FOLLOW_OPENSPEC`（:1584）；WIRED 经 `_dispatch_wave`（:553） |
| `server/tests/test_coding_openspec_gate.py` | gate 全态 + 下游阻断 + env 守护 | ✓ VERIFIED | 8 测试函数（含 spec_not_approved / gate_error / env 注入），全绿 |
| `task/core/config.py` | `TaskConfig.follow_openspec` 字段 | ✓ VERIFIED | `:111-114` Field(default=False) + env_prefix 映射 |
| `task/core/executor.py` | `_get_system_prompt` 条件追加 + `_openspec_guidance` | ✓ VERIFIED | `:832-847` 条件拼接独立 helper |
| `task/tests/test_openspec_prompt.py` | true 含段 / false 逐字等现状 | ✓ VERIFIED | 3 测试（含独立 helper 断言），全绿 |

### Key Link Verification

| From | To | Via | Status |
| ---- | -- | --- | ------ |
| `coding.py` | `delivery.SddSpec` 批准校验 | `afirst` + `status==SddSpecStatus.APPROVED`（:692） | ✓ WIRED |
| `coding.py` | `RepoCodingTaskService.mark_gate_blocked` | 未批准/异常仓经 service 标 failed（:703） | ✓ WIRED |
| `coding.py` | task 容器 env | follow_openspec=True 注入 `env_FRIDAY_TASK_FOLLOW_OPENSPEC`（:1584/1608） | ✓ WIRED |
| `repo_coding_task_service.py` | `Repository.facets` | `values_list("facets")` 推 methodology==SDD（:67-68） | ✓ WIRED |
| `executor.py` | `TaskConfig.follow_openspec` | `_get_system_prompt` 读 `self.config.follow_openspec`（:832） | ✓ WIRED |
| `executor.py setting_sources` | 仓库内 `.claude/skills` | `setting_sources=["project"]` 原生加载（:578，复用未改） | ✓ WIRED |

### Behavioral Spot-Checks / Probe Execution

| Suite | Command | Result | Status |
| ----- | ------- | ------ | ------ |
| server gate/service/wave | `cd server && uv run pytest tests/delivery/test_repo_coding_task_service.py tests/delivery/test_repo_coding_task_inv6_guard.py tests/test_coding_openspec_gate.py tests/test_coding_wave.py -q` | 34 passed | ✓ PASS |
| task config/prompt/callback | `cd task && uv run pytest tests/test_config.py tests/test_openspec_prompt.py tests/test_callback.py -q` | 28 passed | ✓ PASS |
| migrations | `cd server && uv run python manage.py makemigrations --check --dry-run` | No changes detected | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| GATE-01 | 51-01, 51-02 | 编码派发前校验 spec 已 approved，未批准拦截不静默放行 | ✓ SATISFIED | Truths 1/2/5/6/7（gate + mark_gate_blocked + 下游阻断 + fail-closed） |
| GATE-02 | 51-02, 51-03 | 容器注入 openspec 指引 + setting_sources 原生加载 skill | ⚠ SATISFIED（链路完备，真模型遵循需人工） | Truth 8（env→config→system_prompt→skill 加载链路全 WIRED） |

### Anti-Patterns Found

| File | Pattern | Severity |
| ---- | ------- | -------- |
| 改动文件 | TBD/FIXME/XXX/HACK/PLACEHOLDER | ℹ️ 无（grep 零命中） |

### Human Verification Required

1. **gate 拦截真实编码（runner + Docker E2E）** — 未批准 SDD 仓派发被 gate 拦截、容器不起、操作者可见阻断原因；已批准仓正常起容器产 PR。
   - Why human：需真实 runner 调度 + Docker 守护进程，自动化只覆盖 server 派发判定。
2. **openspec skill 真实加载 + 真模型遵循** — approved SDD 仓容器内 `setting_sources=[project]` 加载仓库 `.claude/skills`，system_prompt openspec 段被真模型遵循按 spec delta 编码。
   - Why human：依赖真实容器运行时与真模型行为，grep/单测无法验证模型是否真正遵循流程。

### Gaps Summary

无阻断性 gap。GATE-01 编码前置 gate（置位来源 → fail-closed 校验 → 单一写入入口 → 下游闭包阻断 → 单仓隔离）与 GATE-02 注入链路（dispatch env → task config → system_prompt → 原生 skill 加载）在代码层全部坐实，并有真跑的 server 34 + task 28 用例与干净 `makemigrations --check` 佐证；改动文件无 debt marker。非 SDD/legacy 零回归经 grep spy + 行为双证。唯一未自动化的是真实 runner+Docker 容器 E2E（gate 拦截真实编码 / openspec skill 真实加载 + 真模型遵循），按 CONTEXT/SUMMARY 既定边界标 human_needed，与既有容器 E2E deferred 一致。

---

_Verified: 2026-06-17T04:14:00Z_
_Verifier: Claude (gsd-verifier)_
