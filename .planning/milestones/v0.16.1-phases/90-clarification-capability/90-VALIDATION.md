---
phase: 90
slug: clarification-capability
status: planned
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-27
---

# Phase 90 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (pytest-django + pytest-asyncio) |
| **Config file** | `server/pyproject.toml` |
| **Quick run command** | `cd server && uv run pytest tests/delivery/test_clarification_service.py -q` |
| **Full suite command** | `cd server && uv run pytest tests/delivery tests/services/plan_orchestration -q` |
| **Estimated runtime** | ~60–120 seconds |

---

## Sampling Rate

- **After every task commit:** Run quick run command（相关 service/adapter 测试）
- **After every plan wave:** Run full suite command
- **Before verify:** Full suite green
- **Max feedback latency:** ~120 seconds

---

## Per-Task Verification Map

> Planner 已回填具体 task 行（90-01..04）。executor 执行时把 Status 翻转为 ✅/❌。

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | Status |
|---------|------|------|-------------|-----------|-------------------|--------|
| 90-01-T1 | 90-01 | 1 | CLARIFY-01 | unit (import) | `cd server && uv run python -c "from delivery.models import Clarification, ClarificationQuestion; assert hasattr(Clarification,'round_no'); print('ok')"` | ⬜ pending |
| 90-01-T2 | 90-01 | 1 | CLARIFY-01 | migration check | `cd server && uv run python manage.py makemigrations delivery --check --dry-run && uv run python manage.py migrate delivery 0026` | ⬜ pending |
| 90-02-T1 | 90-02 | 2 | CLARIFY-01 | unit | `cd server && uv run pytest tests/delivery/test_clarification_service.py -x -q` | ⬜ pending |
| 90-02-T2 | 90-02 | 2 | CLARIFY-01 | unit | `cd server && uv run pytest tests/delivery/test_clarification_service.py -k "adopted or adoption_rate or legacy or inv6" -q` | ⬜ pending |
| 90-03-T1 | 90-03 | 3 | CLARIFY-02 | unit | `cd server && uv run pytest tests/services/test_engine_clarify.py -x -q` | ⬜ pending |
| 90-03-T2 | 90-03 | 3 | CLARIFY-02 | integration | `cd server && uv run pytest tests/services/test_plan_research_e2e.py -k clarif -q` | ⬜ pending |
| 90-03-T3 | 90-03 | 3 | CLARIFY-02 | unit | `cd server && uv run pytest tests/services/test_engine_clarify.py -k "fail_soft or llm or pending" -q` | ⬜ pending |
| 90-04-T1 | 90-04 | 3 | CLARIFY-03 | unit (import) | `cd server && uv run python -c "from services.plan_orchestration import ask_clarification; import inspect; assert inspect.iscoroutinefunction(ask_clarification); print('ok')"` | ⬜ pending |
| 90-04-T2 | 90-04 | 3 | CLARIFY-03 | unit | `cd server && uv run pytest tests/services/test_ask_clarification_helper.py -q` | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

> **Nyquist Dimension 8**：每 task 均有 `<automated>` verify；新增测试文件/用例（90-02/03/04）由对应 plan 内的 test task 在同 wave 创建（无 Wave 0 跨 wave 缺口——既有 `tests/delivery/` 与 `tests/services/` 基建已就绪，新用例就地扩充）。无连续 3 个 task 缺 automated verify。

---

## Wave 0 Requirements

- 既有 `server/tests/delivery/` 与 `server/tests/services/plan_orchestration/` 基建覆盖；
  新增澄清模型/采纳率/接线测试就地扩充，无需新框架。

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 真实 LLM 多问题生成质量 | CLARIFY-02 | 需真实 provider | 配置 default_model 后触发编排澄清，人工核对问题/选项/推荐合理性 |

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] `nyquist_compliant: true` set after planner fills map

**Approval:** pending
