---
phase: 47
slug: question-hitl-replan
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-17
---

# Phase 47 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework (server)** | pytest 9.x (pytest-asyncio + pytest-django) |
| **Framework (task)** | pytest (task/ 独立套件) |
| **Config file** | `server/pyproject.toml` / `task/pyproject.toml` |
| **Quick run (server)** | `cd server && uv run pytest tests/test_coding_question_hitl.py -q` |
| **Quick run (task)** | `cd task && uv run pytest tests/test_question_loop.py -q` |
| **Full suite (server)** | `cd server && uv run pytest tests/ -q` |
| **Estimated runtime** | targeted ~10s, full ~60–120s |

---

## Sampling Rate

- **After every task commit:** Run quick run command (targeted HITL tests)
- **After every plan wave:** Run full targeted suite (task + server HITL)
- **Before verify:** Server full suite must be green (excluding pre-existing deferred `test_batch_pr.py`)
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 47-01-01 | 01 | 1 | HITL-01 | T-47-02 | `report_question` payload 对齐 serializer；问题正文不入日志 | unit | `cd task && uv run pytest tests/test_question_loop.py -q` | ❌ W0 | ⬜ pending |
| 47-01-02 | 01 | 1 | HITL-01 | T-47-03 | `ask_user_and_wait` 取回答/超时→default/超时→fail，永不挂起、永不 raise | unit | `cd task && uv run pytest tests/test_question_loop.py -q` | ❌ W0 | ⬜ pending |
| 47-02-01 | 02 | 1 | HITL-01 | T-47-01 | wave(node_execution) question 回调路由 + 缺 chat_id fail-soft | unit | `cd server && uv run pytest tests/test_coding_question_hitl.py -k routing -q` | ❌ W0 | ⬜ pending |
| 47-02-02 | 02 | 1 | HITL-01 | — | 遇阻→RUNNING→aadvance waiting→回答→completed→resume；no-replan 守护 | integration | `cd server && uv run pytest tests/test_coding_question_hitl.py -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `task/tests/test_question_loop.py` — report_question payload + ask_user_and_wait（答/超时default/超时fail）+ 轮询幂等 stubs
- [ ] `server/tests/test_coding_question_hitl.py` — wave question 路由 + e2e（waiting→answer→resume）+ no-replan guard stubs

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 真实 runner + Docker 容器编码遇阻 → 飞书提问卡片 → 用户回答 → 容器续跑 → wave 推进端到端 | HITL-01 | 需真实 runner + Docker + 飞书配置，本地无法闭环（既有 deferred） | 配置真实凭证跑一次多仓 wave 编码，制造遇阻，核对飞书提问卡片送达、回答后容器续跑并完成 wave |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
