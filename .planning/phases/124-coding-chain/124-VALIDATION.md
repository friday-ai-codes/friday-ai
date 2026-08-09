---
phase: 124
slug: coding-chain
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-10
---

# Phase 124 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio + pytest-django（server）；pytest（task） |
| **Config file** | `server/pyproject.toml`；`task/pyproject.toml` |
| **Quick run command** | `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest tests/services/code_graph/test_impact_report.py tests/workflows/test_coding_impact_report.py tests/mcp_tools/test_mr_impact_report.py -q --reuse-db` |
| **Full suite command** | Quick run + `cd task && uv run pytest tests/test_knowledge_tools.py tests/test_openspec_prompt.py tests/test_detect_changes_prompt.py tests/test_claude_sdk_integration.py tests/test_blueprint_context_tools_schema.py -q` |
| **Estimated runtime** | ~30–90 seconds（mock `run_detect_changes`） |

---

## Sampling Rate

- **After every task commit:** Run Quick run command（server impact_report 相关）或 task 对应子集
- **After every plan wave:** Run Full suite command（本相位相关）
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 124-W0-* | 00 | 0 | DIFF-03/04 | — | N/A | scaffold | create missing test stubs | ❌ W0 | ⬜ pending |
| 124-*-* | 01+ | 1+ | DIFF-03 | T-124-01 | prompt 静态字面量；无 token 入日志 | unit | `cd task && uv run pytest tests/test_knowledge_tools.py -k detect_changes -q` | ❌ W0 | ⬜ pending |
| 124-*-* | 01+ | 1+ | DIFF-03 | T-124-01 | plan/execute 才挂指引；不改 runner | unit | `cd task && uv run pytest tests/test_detect_changes_prompt.py -q` | ❌ W0 | ⬜ pending |
| 124-*-* | 01+ | 1+ | DIFF-04 | T-124-02/03 | stub 仅稳定 error_code；无堆栈/凭证 | unit | `cd server && uv run pytest tests/services/code_graph/test_impact_report.py -q --reuse-db` | ❌ W0 | ⬜ pending |
| 124-*-* | 01+ | 1+ | DIFF-04 | T-124-04 | fail-soft：异常不阻断 create_merge_request | unit | `cd server && uv run pytest tests/workflows/test_coding_impact_report.py tests/mcp_tools/test_mr_impact_report.py -q --reuse-db` | ❌ W0 | ⬜ pending |
| 124-*-* | 01+ | 1+ | DIFF-04 / D-14 | — | workflow↔MCP 段规范化一致 | unit sentinel | `test_mr_impact_report.py::test_workflow_mcp_impact_section_parity` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Planner must refine Task IDs to match final PLAN task numbers.*

---

## Wave 0 Requirements

- [ ] `server/tests/services/code_graph/test_impact_report.py` — formatter / stub / timeout / 体积 / 观测
- [ ] `server/tests/workflows/test_coding_impact_report.py` — `_create_mr_for_repo` fail-soft + 段附加
- [ ] `server/tests/mcp_tools/test_mr_impact_report.py` — MCP 路径 + D-14 对等哨兵
- [ ] `task/tests/test_detect_changes_prompt.py` — prompt 条件追加（可扩 `test_openspec_prompt.py`）
- [ ] 更新既有 task 计数断言 10→11（`test_knowledge_tools.py`、`test_blueprint_context_*`、`test_claude_sdk_integration.py`）

*Existing pytest infrastructure covers frameworks; Wave 0 adds missing phase-specific test files/stubs.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| — | — | — | All phase behaviors have automated verification（CONTEXT：不要求生产仓人工点 MR） |

---

## Threat → Test Mapping (ASVS L1)

| Threat ID | STRIDE | Secure Behavior | Automated Test |
|-----------|--------|-----------------|----------------|
| T-124-01 | Tampering | `_detect_changes_guidance` 静态字面量，无外部输入拼接 | `test_detect_changes_prompt.py` |
| T-124-02 | Information Disclosure | stub/日志无 token/堆栈/绝对路径 | `test_impact_report.py` stub/redact 断言 |
| T-124-03 | Information Disclosure | 不渲染源码正文；`include_content` 默认关 | formatter 快照无源码块 |
| T-124-04 | Denial of Service | 30s timeout；超时→stub；MR 仍创建 | timeout + fail-soft 双链路测 |
| T-124-05 | Elevation / Spoofing | ACL 失败→stub，禁止空成功四段 | ACL mock → stub `unavailable` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
