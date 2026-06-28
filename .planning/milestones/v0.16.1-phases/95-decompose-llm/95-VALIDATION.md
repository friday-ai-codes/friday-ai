---
phase: 95
slug: decompose-llm
status: planned
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-28
---

# Phase 95 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (pytest-django + pytest-asyncio, `asyncio_mode=auto`) |
| **Config file** | `server/pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `cd server && uv run pytest tests/services/test_plan_orchestration_engine.py -x` |
| **Full suite command** | `cd server && uv run pytest tests/services/ -x` |
| **Estimated runtime** | ~30–90 seconds |

---

## Sampling Rate

- **After every task commit:** `cd server && uv run pytest tests/services/test_plan_orchestration_engine.py -x`（含 helper 时加 `test_decompose_segments.py`）
- **After every plan wave:** `cd server && uv run pytest tests/services/ -x`
- **Before verify:** `cd server && uv run pytest` 全绿
- **Max feedback latency:** ~90 seconds

---

## Per-Task Verification Map

> Planner 已回填具体 task 行（95-01..03）。executor 执行时把 Status 翻转为 ✅/❌。

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | Status |
|---------|------|------|-------------|-----------|-------------------|--------|
| 95-01-T1 | 95-01 | 1 | DECOMP-01 | unit (enum) | `cd server && uv run python -c "from agents.call_source import CallSource; assert CallSource.PLAN_DECOMPOSE.value=='plan_decompose'; assert len(list(CallSource))==32; print('ok')"` | ⬜ pending |
| 95-01-T2 | 95-01 | 1 | DECOMP-01 | doc check | `cd /Users/zaneliu/Projects/open-source/friday-ai && grep -F '\| \`plan_decompose\` \|' .planning/observability/LOGGING-SPEC.md && grep -F '\| \`plan_clarification\` \|' .planning/observability/LOGGING-SPEC.md` | ⬜ pending |
| 95-02-T1 | 95-02 | 2 | DECOMP-01 | unit (pure fns) | `cd server && uv run pytest tests/services/test_decompose_segments.py -x` | ⬜ pending |
| 95-02-T2 | 95-02 | 2 | DECOMP-01 | unit (async/fail-soft) | `cd server && uv run pytest tests/services/test_decompose_segments.py -x` | ⬜ pending |
| 95-03-T1 | 95-03 | 3 | DECOMP-01 | unit (engine wiring) | `cd server && uv run pytest tests/services/test_plan_orchestration_engine.py -x` | ⬜ pending |
| 95-03-T2 | 95-03 | 3 | DECOMP-01 | unit (LLM/fail-soft/event) | `cd server && uv run pytest tests/services/test_plan_orchestration_engine.py -k decompose -x` | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

> **Nyquist Dimension 8**：每 task 均有 `<automated>` verify。新增测试文件 `test_decompose_segments.py` 与 engine 用例由对应 plan 内 test task 在**同 wave 同 plan** 创建（无 Wave 0 跨 wave 缺口——`tests/services/` 基建已就绪，新用例就地扩充）。无连续 3 个 task 缺 automated verify。

---

## Wave 0 Requirements

- 既有 `server/tests/services/` 基建（pytest-django + pytest-asyncio）已覆盖；
  helper 单测（`test_decompose_segments.py`）与 engine decompose 用例就地新建，无需新框架。

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 真实 LLM 跨仓拆分质量 | DECOMP-01 | 需真实 provider 凭证（测试态走 fail-soft 回退） | 部署态配置 default_model 后触发编排 decompose，人工核对 segments 的 module/layer/repo_hint 合理性 |
| call_source 维度指标上报 | DECOMP-01 | 需真实 LLM 调用经 chokepoint 落 ModelUsageRecord | 真实调用后查询 `ModelUsageRecord` 含 `call_source='plan_decompose'` 行 + ttft/token |

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] `nyquist_compliant: true` set after planner fills map

**Approval:** pending
