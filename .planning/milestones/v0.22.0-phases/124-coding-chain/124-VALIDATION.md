---
phase: 124
slug: coding-chain
status: complete
nyquist_compliant: true
wave_0_complete: true
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
| **Full suite command** | Quick run + `cd task && uv run pytest tests/test_knowledge_tools.py tests/test_openspec_prompt.py tests/test_detect_changes_prompt.py tests/test_claude_sdk_integration.py tests/test_blueprint_context_tools_schema.py tests/test_blueprint_context_wait.py -q` |
| **Estimated runtime** | Task verify 目标 &lt;30s（单文件）；Quick run / wave gate ~30–90s（三文件 mock） |

---

## Sampling Rate

- **After every task commit:** Run **该 task 的** `<automated>`（单文件/小子集；目标 &lt;30s）— 勿把 Quick run 三文件塞进每个 task verify
- **After every plan wave / phase gate:** Run Quick run command（server 三文件）+ Full suite 中 task 侧相关套件
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** task verify &lt;30s；wave/phase gate ≤90s

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 124-00-01 | 00 | 0 | DIFF-03/04 | — | N/A | scaffold collect | `pytest … --collect-only -q` (3 server files) | ✅ | ✅ green |
| 124-00-02 | 00 | 0 | DIFF-03 | T-124-01 | N/A | scaffold collect | `pytest tests/test_detect_changes_prompt.py --collect-only -q` | ✅ | ✅ green |
| 124-01-01 | 01 | 1 | DIFF-03 | — | schema/whitelist；无 mcp submodule 改动 | unit | `cd task && uv run pytest tests/test_knowledge_tools.py -k detect_changes -q` | ✅ | ✅ green |
| 124-01-02 | 01 | 1 | DIFF-03 | T-124-01 | prompt 静态字面量；不改 runner | unit | `cd task && uv run pytest tests/test_detect_changes_prompt.py tests/test_openspec_prompt.py -q` | ✅ | ✅ green |
| 124-02-01 | 02 | 1 | DIFF-04 | D-13 | settings 无 kill-switch | config grep | `rg CODE_GRAPH_IMPACT_REPORT_ TIMEOUT|MAX_CHARS settings.py` | ✅ | ✅ green |
| 124-02-02 | 02 | 1 | DIFF-04 | T-124-02/03/04/05 | stub 仅稳定 error_code；无堆栈/源码 | unit | `cd server && uv run pytest tests/services/code_graph/test_impact_report.py -q --reuse-db` | ✅ | ✅ green |
| 124-03-01 | 03 | 2 | DIFF-04 | T-124-04 | fail-soft：异常不阻断 create_merge_request；含 create_mr_for_task | unit | `cd server && uv run pytest tests/workflows/test_coding_impact_report.py -q --reuse-db` | ✅ | ✅ green |
| 124-03-02 | 03 | 2 | DIFF-04 / D-14 | T-124-05 | workflow↔MCP 段规范化一致；view+work_item 传 user | unit sentinel | `cd server && uv run pytest tests/mcp_tools/test_mr_impact_report.py -q --reuse-db` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `server/tests/services/code_graph/test_impact_report.py` — formatter / stub / timeout / 体积 / 观测（124-00 已建 skip 桩；124-02 转绿）
- [x] `server/tests/workflows/test_coding_impact_report.py` — `_create_mr_for_repo` fail-soft + 段附加 + `test_create_mr_for_task_failsoft_appends_impact`（124-03 转绿）
- [x] `server/tests/mcp_tools/test_mr_impact_report.py` — MCP 路径 + D-14 对等哨兵（含 `test_workflow_mcp_impact_section_parity`；124-03 转绿）
- [x] `task/tests/test_detect_changes_prompt.py` — prompt 条件追加（可扩 `test_openspec_prompt.py`；124-01 转绿）
- [x] 更新既有 task 计数断言 10→11（`test_knowledge_tools.py`、`test_blueprint_context_*`、`test_claude_sdk_integration.py`）— **由 124-01 落地**

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

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Task verify feedback latency &lt; 30s；wave/phase gate ≤90s
- [x] `nyquist_compliant: true` set in frontmatter（after 124-03）

**Approval:** approved (124-03 Quick run 18 passed；D-14 sentinel green)
