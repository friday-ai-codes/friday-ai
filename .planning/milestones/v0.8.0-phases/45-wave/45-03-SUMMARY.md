---
phase: 45-wave
plan: 03
subsystem: workflows / plan_orchestration (integration tests)
tags: [artifact-passthrough, wave, integration-test, idempotency, fail-soft, e2e]
requires:
  - "Plan 45-01 提取落库（build_produced_artifacts + record_produced_artifacts + _backfill_running_terminal 提取钩子，已 ship）"
  - "Plan 45-02 注入下游（acollect_upstream_artifacts + render_upstream_artifacts_section + coding.py dispatch 链透传，已 ship）"
  - "Phase 44 wave 集成测试 harness（test_coding_wave.py：_dispatched / _stub_provider_resolution / _settle_session / _resume / _make_plan_version / _make_repo）"
provides:
  - "tests/test_coding_wave.py::test_artifact_passthrough — 端到端产物传递集成验收（SC-3）"
  - "tests/test_coding_wave.py::test_artifact_passthrough_idempotent — 幂等 no-op（D-15）"
  - "tests/test_coding_wave.py::test_artifact_extract_fail_soft — 提取异常 fail-soft（D-15 / T-45-09）"
affects:
  - "ARTIFACT-01 + ARTIFACT-02 端到端链路验收闭环（提取→注入全链路 mock IO 边界）"
tech-stack:
  added: []
  patterns:
    - "蓝本 test_multi_wave_progression：首发 dispatch wave0 → _settle_session → _resume → aadvance 推进 dispatch wave1"
    - "断言面 = 捕获的 wave2 DispatchTask.prompt / metadata（既有 _dispatched mock）"
    - "fail-soft：monkeypatch 源模块 build_produced_artifacts 抛错验证 swallow（局部 import 故 patch 源属性生效）"
    - "幂等：直接复调 aadvance_coding_waves → done 仓不再进提取段 → produced_artifacts 逐字不漂移"
key-files:
  created:
    - ".planning/phases/45-wave/45-03-SUMMARY.md"
  modified:
    - "server/tests/test_coding_wave.py"
decisions:
  - "本 plan 测试-only，无新增生产符号——复用 Plan 01/02 已 ship 的提取/注入链；仅扩充 test_coding_wave.py"
  - "_settle_session 增 defaulted modified_files 参数（默认 [\"f.py\"]）保既有 4 wave 测试零回归，happy-path 传 openapi 契约文件名"
  - "幂等用直接复调 aadvance_coding_waves 验证 no-op（done 仓非 RUNNING → 不再提取 → 含 extracted_at 逐字不变），强于经节点重入"
  - "fail-soft patch build_produced_artifacts（提取链一环）抛错 → 验证 wave1 仍 done、wave2 仍 dispatch 且注入段空、advance 不冒泡"
metrics:
  duration: "~12min"
  completed: "2026-06-16"
  tasks: 2
  files: 1
---

# Phase 45 Plan 03: ARTIFACT-01 + ARTIFACT-02 端到端集成验收（SC-3）Summary

以 mock IO 边界（dispatcher / SubAgentSession / TaskResult）端到端验证「提取→注入」全链路：在既有 `tests/test_coding_wave.py` 扩充三测——构造 wave1 后端仓 + wave2 前端仓（跨仓 `depends_on` 边），wave1 容器完成（`TaskResult` 含 openapi 契约文件）→ `aadvance_coding_waves` 回填 done 触发 Plan 01 提取落 `produced_artifacts` → 推进 wave2 dispatch → 断言捕获的 wave2 `DispatchTask.prompt` 含 wave1 产出的契约文件名 + 「上游产物」段。真实 runner+Docker E2E 沿用既有 deferred。

## What Shipped

### Task 1 — D-13 端到端 happy-path 产物传递集成测试（commit `82f7df9b`）
- 新增 `test_artifact_passthrough`，蓝本 `test_multi_wave_progression`：wave1 后端仓（wave0）+ wave2 前端仓（wave1，`dependencies:["t1"]` 跨仓边）。
- 扩展 `_settle_session` 增 `modified_files: list[str] | None = None`（默认 `["f.py"]` 保既有 4 wave 测试零回归），happy-path 传 `["api/openapi.yaml", "src/app.py"]`。
- 流程：首发 dispatch wave0(后端) → `_settle_session(ok=True, modified_files=[openapi])` → `_resume` → `node.execute` 触发 `aadvance_coding_waves`（回填后端 done → 提取落 `produced_artifacts` → 推进 dispatch wave1 前端）。
- 断言：① 后端 `task.produced_artifacts["available"] is True` 且 `openapi` 桶含 `api/openapi.yaml`（提取落库正确）；② 前端 `DispatchTask.prompt` 含「上游产物」段标题 + `api/openapi.yaml` 契约文件名（产物传递正确，SC-3）；③ `"raw_output" not in prompt`（仅传白名单路径，T-45-10）。

### Task 2 — 幂等 + fail-soft 集成验收（D-15）+ phase gate 全量回归（commit `8d470e42`）
- `test_artifact_passthrough_idempotent`（幂等）：happy-path 跑到后端 done + 产物落库后，捕获 `produced_artifacts`，直接复调 `aadvance_coding_waves(pv.id)` → 返回 `{"waiting": True}`（前端仍 RUNNING）；后端已 done（非 RUNNING）不再进提取段 → 重读 `produced_artifacts` 逐字不漂移（含 `extracted_at`，覆盖写 no-op 语义）；无重复异常派发（`_dispatched` 空）。
- `test_artifact_extract_fail_soft`（fail-soft）：`monkeypatch.setattr("services.plan_orchestration.artifact_extraction.build_produced_artifacts", _boom)`（局部 import 故 patch 源属性即生效），驱动后端 done → 提取抛错被 swallow → 断言 wave1 仍 `DONE`、`r2.status == "waiting_event"`、wave2 前端仍 dispatch、其 prompt 不含「上游产物」段（注入段空零回归降级）、`produced_artifacts == {}`、advance 不冒泡（容器回调不 5xx，T-45-09）。
- phase gate：`pytest tests/services/plan_orchestration tests/delivery tests/test_coding_wave.py tests/test_coding_node.py` → **360 passed, 1 xfailed**（既有 xfail，非本 plan 引入），Phase 44 既有 4 wave 集成测试 + test_coding_node 12 用例 + INV-6 字段级守护零回归。

## Deviations from Plan

None — plan executed exactly as written（测试-only，未触任何生产代码）。

## Verification Results

| Gate | Result |
|------|--------|
| `pytest tests/test_coding_wave.py::test_artifact_passthrough -x` | 1 passed（happy path） |
| `pytest tests/test_coding_wave.py::test_artifact_passthrough_idempotent ::test_artifact_extract_fail_soft -x` | 2 passed（幂等 + fail-soft） |
| `pytest tests/services/plan_orchestration tests/delivery tests/test_coding_wave.py tests/test_coding_node.py` | 360 passed, 1 xfailed（phase gate 零回归 + INV-6 守护 + Phase 44 wave/coding 测试） |
| `ruff check tests/test_coding_wave.py` | All checks passed |

## Security Notes

- T-45-09（DoS / 提取异常 → 回调 5xx 重试风暴）：fail-soft 集成断言提取异常被 swallow、wave 推进不失败、advance 不冒泡（覆盖 Pitfall 3 验收）。
- T-45-10（Info Disclosure / 端到端产物经下游 prompt 泄漏）：happy-path 断言 wave2 prompt 仅含契约文件路径，且 `"raw_output" not in prompt`（白名单字段，不含 token/raw_output 正文）。
- T-45-SC（supply-chain）：本 plan 仅新增测试代码，不安装任何外部包，无供应链面。

## Known Stubs

None — 三测均经真实 mock IO 边界端到端驱动（dispatcher / SubAgentSession / TaskResult mock，ORM 走真实 DB transaction）；fail-soft 空注入段为设计降级路径，非 stub。

## Self-Check: PASSED

- FOUND: server/tests/test_coding_wave.py（含 test_artifact_passthrough / test_artifact_passthrough_idempotent / test_artifact_extract_fail_soft）
- FOUND commit 82f7df9b（Task 1）/ 8d470e42（Task 2）
