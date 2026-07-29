---
phase: 105
slug: golden-set
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-29
---

# Phase 105 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x（server/，uv 管理）+ vitest 4（web/） |
| **Config file** | server/pyproject.toml（[tool.pytest.ini_options]）；web/vitest 由 vite 配置 |
| **Quick run command** | `cd server && uv run pytest tests/codegraph tests/services -x -q -k router` |
| **Full suite command** | `cd server && uv run pytest -q`（前端改动另跑 `cd web && pnpm vitest run <spec>`） |
| **Estimated runtime** | 快跑 ~30s；全量分钟级 |

---

## Sampling Rate

- **After every task commit:** Run quick run command（受改测试目录定向跑）
- **After every plan wave:** Run 受影响模块全量（router/delivery/process_runtime 相关测试）
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| （由 planner 填充） | — | — | RELY-04/ROUTE-07/08/09 | — | 快照脱敏经 redact_for_ledger | unit/integration | `uv run pytest ...` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] golden set fixture 与离线 harness 测试文件 stub（REQ ROUTE-08）
- [ ] 现有 `server/tests/services/test_repo_router_adapter.py` 等 router 触点测试保持绿（回归基线）

*Existing infrastructure (pytest + pytest-socket + respx + factory-boy) covers all phase requirements; new test files are additive.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 前端展开分数分解的视觉观感 | ROUTE-07 | 视觉判断 | 打开对话路由结果面板，展开候选查看分解列表与合计行 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
