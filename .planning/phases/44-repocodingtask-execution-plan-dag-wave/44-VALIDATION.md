---
phase: 44
slug: repocodingtask-execution-plan-dag-wave
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-16
---

# Phase 44 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 + pytest-asyncio + pytest-django 4.8（+ factory-boy / respx / pytest-socket） |
| **Config file** | `server/pyproject.toml`（`[tool.pytest.ini_options]` / coverage / ruff） |
| **Quick run command** | `cd server && uv run pytest tests/delivery/test_repo_coding_task_*.py tests/services/plan_orchestration/test_wave_*.py -x` |
| **Full suite command** | `cd server && uv run pytest tests/delivery tests/services/plan_orchestration -x` |
| **Estimated runtime** | ~60 seconds (scoped); full server suite longer |

---

## Sampling Rate

- **After every task commit:** Run `cd server && uv run pytest tests/delivery/test_repo_coding_task_*.py tests/services/plan_orchestration/test_wave_*.py -x`
- **After every plan wave:** Run `cd server && uv run pytest tests/delivery tests/services/plan_orchestration -x`
- **Before `$gsd-verify-work`:** Full server suite must be green (含 INV-6 守护 + event_taxonomy 守护若动)
- **Max feedback latency:** ~60 seconds (scoped)

---

## Per-Task Verification Map

| Req ID | Behavior | Test Type | Automated Command | File Exists | Status |
|--------|----------|-----------|-------------------|-------------|--------|
| WAVE-01 | 模型字段/Meta/索引/状态枚举正确 | unit | `pytest tests/delivery/test_repo_coding_task_models.py -x` | ❌ W0 | ⬜ pending |
| WAVE-01 | 拓扑分层：空依赖→单 wave0 全并行（零回归） | unit | `pytest tests/services/plan_orchestration/test_wave_layering.py::test_empty_deps_single_wave -x` | ❌ W0 | ⬜ pending |
| WAVE-01 | 拓扑分层：线性链多 wave / 菱形依赖 / 环 fail-fast | unit | `pytest tests/services/plan_orchestration/test_wave_layering.py -x` | ❌ W0 | ⬜ pending |
| WAVE-01 | 同仓多 task 取 wave max | unit | `pytest tests/services/plan_orchestration/test_wave_layering.py::test_same_repo_max_wave -x` | ❌ W0 | ⬜ pending |
| WAVE-01 | INV-6 grep 守护（无旁路写 RepoCodingTask） | unit | `pytest tests/delivery/test_repo_coding_task_inv6_guard.py -x` | ❌ W0 | ⬜ pending |
| WAVE-02 | wave gate：wave N 全终态才 dispatch N+1；在途不提前 dispatch | unit/integration | `pytest tests/services/plan_orchestration/test_wave_progression.py::test_wave_gate -x` | ❌ W0 | ⬜ pending |
| WAVE-02 | 失败隔离：单 wave 单仓 failed 不影响兄弟 | unit | `pytest tests/services/plan_orchestration/test_wave_progression.py::test_failure_isolation -x` | ❌ W0 | ⬜ pending |
| WAVE-02 | 下游阻断：上游 failed → depends_on 链标 blocked 不 dispatch | unit | `pytest tests/services/plan_orchestration/test_wave_progression.py::test_downstream_blocked -x` | ❌ W0 | ⬜ pending |
| WAVE-02 | 幂等：重复 callback / 并发 resume → no-op 不重复 dispatch | unit | `pytest tests/services/plan_orchestration/test_wave_progression.py::test_idempotent -x` | ❌ W0 | ⬜ pending |
| WAVE-02 | 部分成功收尾：done 仓出 MR，failed/blocked 仓如实标注 | integration | `pytest tests/workflows/ -k coding_wave -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/delivery/test_repo_coding_task_models.py` — WAVE-01 模型字段/Meta/索引/状态枚举
- [ ] `tests/delivery/test_repo_coding_task_service.py` — WAVE-01/02 service 状态推进/幂等
- [ ] `tests/delivery/test_repo_coding_task_inv6_guard.py` — INV-6 守护（镜像 `test_research_inv6_guard.py`）
- [ ] `tests/services/plan_orchestration/test_wave_layering.py` — 拓扑分层（空/线性/菱形/环/同仓 max）
- [ ] `tests/services/plan_orchestration/test_wave_progression.py` — wave gate / 失败隔离 / 下游阻断 / 幂等
- [ ] AICodingNode wave 集成测试（mock dispatcher + SubAgentSession 状态）— 复用现有 coding node 测试 fixture（planner 须 grep `tests/` 现有 AICodingNode 测试以复用 mock 边界）
- Framework install: 无需（pytest 已配）

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 真实 runner + Docker 容器端到端 wave resume | WAVE-02 | 本地无法闭环（需真实 runner + Docker daemon），沿用既有 deferred | 部署 runner + Docker，触发多 wave 编码 workflow，观察 wave N done → wave N+1 dispatch |

*自动化测试以 mock IO 边界（dispatcher / SubAgentSession 状态）覆盖拓扑分层、wave gating、失败隔离、幂等。*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
