---
phase: 107
slug: layered-presentation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-29
---

# Phase 107 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x（server/，uv 管理）+ vitest 4（web/） |
| **Config file** | server/pyproject.toml |
| **Quick run command** | `cd server && uv run pytest tests/codegraph tests/delivery -q` |
| **Full suite command** | `cd server && uv run pytest -q`；前端 `cd web && pnpm vitest run` |
| **Estimated runtime** | 快跑 ~40s；全量 ~11min |

---

## Sampling Rate

- **After every task commit:** 受改模块定向跑（codegraph / delivery / services / workflows）
- **After every plan wave:** 受影响模块全量 + golden 门禁（分数口径不得漂移）
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| （由 planner 填充） | — | — | ROUTE-01/02, RELY-02/03/05 | — | 降级原因经 redact；澄清出口任务带 initiated_by_user_id | unit/integration | `uv run pytest ...` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] 分组/迟滞置顶的离线 golden 验证（复用 106 fixture 的 2 条 cross_group 样本，零网络）
- [ ] 澄清超时出口的并发幂等守护（CAS no-op 语义）

*Existing infrastructure (pytest + pytest-socket + respx + vitest) covers all phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 分组/跨组/降级三块 UI 观感 | ROUTE-01/02, RELY-03 | 视觉判断 | 对话路由面板：确认两组分区、跨组 badge、降级横幅与徽标灰化，与 107-UI-SPEC 一致 |
| 澄清必达真机链路（IM/飞书送达） | RELY-02 | 需真实 IM 环境 | 真实会话触发澄清，确认送达 + 可作答 + 送达失败留痕 |
| O-6 生产延迟分位实测 | RELY-05 | 需生产数据 | 生产查 SystemLogEntry 的 stage1 duration_ms 分位，回填 107-MEASUREMENTS.md |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
