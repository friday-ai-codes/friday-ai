---
phase: 91
slug: clarification-outlets-resume
nyquist_compliant: true
test_stack:
  backend: "pytest>=9.0.2 + pytest-django + pytest-asyncio + respx (httpx mock) + pytest-socket"
  frontend: "vitest@^4 + @vue/test-utils + happy-dom"
backend_quick: "cd server && uv run pytest <file> -x -q"
frontend_quick: "cd web && pnpm vitest run <spec>"
---

# Phase 91 — Nyquist Validation Map

每个 task 的行为均有 `<automated>` 验证命令；新建测试文件在所属 plan 内先建（RED）后实现（GREEN），无独立 Wave 0 plan。

## Per-Task Validation Map

| Plan-Task | Requirement | Behavior | Automated Command | Test File | Status |
|-----------|-------------|----------|-------------------|-----------|--------|
| 91-01-T1 | CLARIFY-06 | 共享 helper answer_round + adrive 续推（同源、engine 缺省=chat、注入复用、幂等） | `cd server && uv run pytest tests/services/test_answer_resume.py -x -q` | server/tests/services/test_answer_resume.py | NEW (Wave 0 gap) |
| 91-01-T2 | CLARIFY-07 | 多轮：答后信息不足再发一轮 / 上界触顶带现有信息继续 / 重判吃答案防同题死循环 | `cd server && uv run pytest tests/services/test_engine_clarify.py -k "multi_round or round_cap" -x -q` | server/tests/services/test_engine_clarify.py | EXTEND |
| 91-02-T1 | WR-03 | 三处 pending 经 ahas_pending（结构化子题轮不误判） | `cd server && uv run pytest tests/workflows/test_plan_research_node.py tests/services -k pending -x -q` | server/tests/workflows/test_plan_research_node.py | EXTEND |
| 91-02-T2 | CLARIFY-05 | 卡片携 clarification_id + action=plan_clarify_answer | `cd server && uv run pytest tests/workflows/test_plan_research_node.py -k clarif -x -q` | server/tests/workflows/test_plan_research_node.py | EXTEND |
| 91-02-T3 | CLARIFY-05 | 工作流节点 CLARIFYING 发卡 + 建 WorkflowEventSubscription | `cd server && uv run pytest tests/workflows/test_plan_research_node.py -k "clarif or subscription" -x -q` | server/tests/workflows/test_plan_research_node.py | EXTEND |
| 91-03-T1 | CLARIFY-05, CLARIFY-06 | 飞书回调 form_value→answers[]→answer_round→续推→approve_node（防伪造/幂等/fail-soft） | `cd server && uv run pytest tests/feishu/test_plan_clarify_callback.py -x -q` | server/tests/feishu/test_plan_clarify_callback.py | NEW (Wave 0 gap) |
| 91-04-T1 | CLARIFY-04 | runtime 暴露 plan 结构化轮 pending_plan_clarification | `cd server && uv run pytest tests/test_plan_clarification_answer_endpoint.py -k runtime -x -q` | server/tests/test_plan_clarification_answer_endpoint.py | NEW (Wave 0 gap) |
| 91-04-T2 | CLARIFY-04, CLARIFY-06 | 专路由收 answers[] + owner gate + answer_round 写 delivery + 续推 + 干净 contextvars | `cd server && uv run pytest tests/test_plan_clarification_answer_endpoint.py -x -q` | server/tests/test_plan_clarification_answer_endpoint.py | NEW (Wave 0 gap) |
| 91-05-T1 | CLARIFY-04 | 前端类型/api/store 接线（专路由 + runtime 键） | `cd web && pnpm vue-tsc --noEmit` | web/src/types/clarification.ts | EXTEND |
| 91-05-T2 | CLARIFY-04 | 多题多选卡渲染 + ⭐推荐默认选中 + answers[] 聚合提交 + 单题零回归 | `cd web && pnpm vitest run src/components/chat/__tests__/ClarificationCard.spec.ts` | web/src/components/chat/__tests__/ClarificationCard.spec.ts | NEW (Wave 0 gap) |

## INV-6 / 安全守护
| Guard | Command |
|-------|---------|
| INV-6 无旁路写 Clarification/ClarificationQuestion（回调/endpoint/helper 不触红） | `cd server && uv run pytest tests/delivery/test_clarification_service.py -k inv6 -x` |
| 无新 migration（Phase 90 字段已够） | `cd server && uv run python manage.py makemigrations --check` |

## Wave 0 Gaps（在所属 plan 内 RED-first 创建）
- [ ] `server/tests/services/test_answer_resume.py`（91-01）
- [ ] `server/tests/feishu/test_plan_clarify_callback.py`（91-03）
- [ ] `server/tests/test_plan_clarification_answer_endpoint.py`（91-04）
- [ ] `web/src/components/chat/__tests__/ClarificationCard.spec.ts`（91-05）

## Phase Gate
后端相关全绿 + `cd web && pnpm vue-tsc --noEmit` + `ruff`/`mypy` 干净 + INV-6 守护无回归 + `pnpm vitest run` → `/gsd-verify-work`。
