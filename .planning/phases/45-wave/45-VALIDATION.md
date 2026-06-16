---
phase: 45
slug: wave
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-16
---

# Phase 45 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 + pytest-asyncio + pytest-django 4.8（+ factory-boy / respx / pytest-socket） |
| **Config file** | `server/pyproject.toml`（`[tool.pytest.ini_options]` / coverage / ruff） |
| **Quick run command** | `cd server && uv run pytest tests/services/plan_orchestration/test_artifact_*.py tests/delivery/test_repo_coding_task_service.py -x` |
| **Full suite command** | `cd server && uv run pytest tests/services/plan_orchestration tests/delivery tests/test_coding_wave.py -x` |
| **Estimated runtime** | ~60 seconds (scoped); full server suite longer |

---

## Sampling Rate

- **After every task commit:** Run `cd server && uv run pytest tests/services/plan_orchestration/test_artifact_*.py tests/delivery/test_repo_coding_task_service.py -x`
- **After every plan wave:** Run `cd server && uv run pytest tests/services/plan_orchestration tests/delivery -x`
- **Before `$gsd-verify-work`:** Full server suite must be green (含 INV-6 守护 + 端到端产物传递集成)
- **Max feedback latency:** ~60 seconds (scoped)

---

## Per-Task Verification Map

| Req ID | Behavior | Test Type | Automated Command | File Exists | Status |
|--------|----------|-----------|-------------------|-------------|--------|
| ARTIFACT-01 | `build_produced_artifacts`：git TaskResult（openapi/proto/schema 路径）→ 正确归类 api_contracts/openapi（D-11） | unit | `pytest tests/services/plan_orchestration/test_artifact_extraction.py::test_classify_contracts -x` | ❌ W0 | ⬜ pending |
| ARTIFACT-01 | `build_produced_artifacts`：无 TaskResult → `{"available": false}` 占位（fail-soft）（D-11） | unit | `pytest tests/services/plan_orchestration/test_artifact_extraction.py::test_no_task_result -x` | ❌ W0 | ⬜ pending |
| ARTIFACT-01 | `build_produced_artifacts`：空 modified_files → 结构合法、各桶空（D-11） | unit | `pytest tests/services/plan_orchestration/test_artifact_extraction.py::test_empty_files -x` | ❌ W0 | ⬜ pending |
| ARTIFACT-01 | `RepoCodingTaskService.record_produced_artifacts`：写 produced_artifacts（覆盖式幂等）（D-05/D-15） | unit | `pytest tests/delivery/test_repo_coding_task_service.py::test_record_produced_artifacts -x` | ❌ W0 | ⬜ pending |
| ARTIFACT-01 | INV-6 守护：旁路写 `produced_artifacts` 被断言拦截（D-14） | unit | `pytest tests/delivery/test_repo_coding_task_inv6_guard.py -x` | ⚠️ extend | ⬜ pending |
| ARTIFACT-02 | `render_upstream_artifacts_section`：多上游→段含各仓契约；空→空串（D-12） | unit | `pytest tests/services/plan_orchestration/test_artifact_injection.py::test_render_section -x` | ❌ W0 | ⬜ pending |
| ARTIFACT-02 | `_build_coding_prompt`：带 upstream_artifacts→prompt 含「上游产物」段+契约文件名（D-12） | unit | `pytest tests/test_coding_node.py::test_prompt_injection -x` | ⚠️ extend | ⬜ pending |
| ARTIFACT-02 | `_build_coding_prompt`：不带 upstream_artifacts→prompt 与 Phase 44 现行为逐字一致（零回归）（D-12） | unit | `pytest tests/test_coding_node.py::test_no_regression -x` | ⚠️ extend | ⬜ pending |
| ARTIFACT-01+02 | 端到端：wave1 done→提取落 produced_artifacts→wave2 dispatch prompt/metadata 含 wave1 契约（D-13, SC-3） | integration | `pytest tests/test_coding_wave.py::test_artifact_passthrough -x` | ⚠️ extend | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/services/plan_orchestration/test_artifact_extraction.py` — `build_produced_artifacts` 纯函数（归类/无 TaskResult/空文件）
- [ ] `tests/services/plan_orchestration/test_artifact_injection.py` — `render_upstream_artifacts_section` 纯函数注入段渲染
- [ ] `tests/test_coding_node.py` — `_build_coding_prompt` 上游产物注入 + 零回归逐字断言（扩充既有 prompt 基线）
- [ ] `tests/delivery/test_repo_coding_task_service.py` — `record_produced_artifacts`（扩充既有 service 测试）
- [ ] `tests/delivery/test_repo_coding_task_inv6_guard.py` — INV-6 守护扩充 `produced_artifacts` 字段赋值拦截（镜像既有 guard）
- [ ] `tests/test_coding_wave.py` — 端到端产物传递集成（扩充既有 wave 集成测试，复用 mock dispatcher + SubAgentSession + TaskResult fixture）
- Framework install: 无需（pytest 已配）

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 真实 runner + Docker 容器端到端产物传递 | ARTIFACT-01/02 | 本地无法闭环（需真实 runner + Docker daemon），沿用既有 deferred | 部署 runner + Docker，触发跨仓依赖编码 workflow，观察 wave1 done 后 wave2 容器 prompt 含上游契约 |

*自动化测试以 mock IO 边界（dispatcher / SubAgentSession / TaskResult）覆盖提取归类、写库幂等、prompt 注入、零回归、端到端产物传递。*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
