---
phase: 46
slug: pr-pr
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-16
---

# Phase 46 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x (pytest-asyncio + pytest-django) |
| **Config file** | `server/pyproject.toml` ([tool.pytest.ini_options]) |
| **Quick run command** | `cd server && uv run pytest tests/workflows/ -k "pr or cross_ref or target_branch" -q` |
| **Full suite command** | `cd server && uv run pytest tests/ -q` |
| **Estimated runtime** | ~60–120 seconds (targeted ~10s) |

---

## Sampling Rate

- **After every task commit:** Run quick run command (targeted PR/cross-ref tests)
- **After every plan wave:** Run full suite command
- **Before `$gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 46-01-01 | 01 | 1 | PR-01 | — | 各仓 MR target_branch = 各仓 default_branch（非 first-repo / 非 "main"）；缺凭证 fail-soft 不回退 | unit | `cd server && uv run pytest tests/workflows/ -k target_branch -q` | ❌ W0 | ⬜ pending |
| 46-02-01 | 02 | 2 | PR-02 | — | 成功仓 ≥2 时 cross-ref 回写各兄弟仓链接 + 追溯段（TechnicalPlan/WorkItem）；回写失败仅 warning，PR 仍 completed | unit | `cd server && uv run pytest tests/workflows/ -k "cross_ref or pr_cross" -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `server/tests/workflows/test_coding_pr_target_branch.py` — PR-01 各仓 target_branch 解析 + 零回归 + fail-soft stubs
- [ ] `server/tests/workflows/test_pr_cross_reference.py` — PR-02 cross-ref section 纯函数 + 回写 + 追溯段 + fail-soft stubs

*If none: "Existing infrastructure covers all phase requirements."*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 真实 GitLab/GitHub 多仓 PR 创建 + cross-ref 回写端到端 | PR-01/PR-02 | 需真实 git 平台凭证 + runner+Docker 容器，本地无法闭环（既有 deferred） | 配置多仓真实凭证，跑一次多仓 wave 编码，核对各 PR target_branch 正确 + 描述含兄弟 PR 链接 + 方案/工作项追溯 |

*If none: "All phase behaviors have automated verification."*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
