---
phase: 106
slug: multi-signal-scoring
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-29
---

# Phase 106 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x（server/，uv 管理）+ vitest 4（web/，若触前端标签映射） |
| **Config file** | server/pyproject.toml |
| **Quick run command** | `cd server && uv run pytest tests/codegraph -q` |
| **Full suite command** | `cd server && uv run pytest -q` |
| **Estimated runtime** | 快跑 ~30s；全量 ~10min |

---

## Sampling Rate

- **After every task commit:** 受改模块定向跑（codegraph / settings / repositories）
- **After every plan wave:** `tests/codegraph + golden 门禁 + 受影响 services`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| （由 planner 填充） | — | — | ROUTE-03/04/05/06 | — | 权重写入走既有权限面；无凭证入日志 | unit/integration | `uv run pytest ...` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] golden fixture 结构扩展（facets/repo_meta/scored_at）+ 重建路径守护
- [ ] 打分核心新签名的不变量测试扩展（INV-R1~R4 覆盖新信号）

*Existing infrastructure covers all phase requirements; new test files are additive.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| O-2 生产余弦校准 / O-5 生产覆盖率 | ROUTE-04/05 | 需生产数据 | 生产实例跑扩展后的 measure command，回填 106-MEASUREMENTS.md |
| 系统设置权重编辑面观感 | ROUTE-06 | 视觉判断 | 管理页调整权重并保存，复跑路由观察 breakdown 变化 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
