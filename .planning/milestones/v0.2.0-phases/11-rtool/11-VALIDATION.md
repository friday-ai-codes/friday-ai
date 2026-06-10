---
phase: 11
slug: rtool
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-09
---

# Phase 11 — Validation Strategy

> Cross-component (server / runner-Go / task-Python) validation for the RemoteTool loop.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (server + task), go test (runner) |
| **Config file** | `server/pyproject.toml`, `task/pyproject.toml`, `runner/Makefile` |
| **Quick run command** | `cd task && uv run pytest tests/test_remote_tools.py -q` |
| **Full suite command** | `cd server && uv run pytest tests/test_remote_tool_execute.py tests/test_remote_tool_dispatch.py -q && cd ../task && uv run pytest tests/test_remote_tools.py tests/test_callback.py -q && cd ../runner && go test ./internal/docker/...` |
| **Estimated runtime** | ~90–150 seconds |

---

## Sampling Rate

- **After every task commit:** quick run command for the touched component
- **After every plan wave:** full suite (the component(s) touched + cross-component contract tests)
- **Before verification:** all three components green
- **Max feedback latency:** 150 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------------|-----------|-------------------|-------------|--------|
| 11-xx | — | 1 | RTOOL-02 | task 用 remote_tools 构建 SDK MCP server，每工具回调 /api/tools/execute/ | unit | `cd task && uv run pytest tests/test_remote_tools.py -q` | ❌ W0 | ⬜ pending |
| 11-xx | — | 1 | RTOOL-03 | PAT 经 server→runner→task 注入；日志/审计脱敏，绝不出现明文 | unit/integration | `cd task && uv run pytest tests/test_remote_tools.py -q` | ❌ W0 | ⬜ pending |
| 11-xx | — | 1 | RTOOL-04 | 回调遇 401(吊销) → 结构化工具错误，不崩容器，任务续跑 | unit | `cd task && uv run pytest tests/test_remote_tools.py -q` | ❌ W0 | ⬜ pending |
| 11-xx | — | 1 | RTOOL-02/03 | server dispatch payload + runner env 含 remote_tools + token + tools endpoint | unit | `cd runner && go test ./internal/docker/...` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `task/tests/test_remote_tools.py`（新）— SDK MCP server 构建、工具 handler 回调（mock httpx）、401 graceful、无明文泄漏、无 remote_tools 时不挂 server
- [ ] `server/tests/test_remote_tool_dispatch.py`（新）— dispatch payload 含 remote_tools + tools endpoint（+ 实时请求线程下传 PAT 的机会性路径）
- [ ] `runner/internal/docker/executor_test.go` — 新 env（FRIDAY_TASK_USER_TOKEN / REMOTE_TOOLS / TOOLS_ENDPOINT）正确装配且不打印明文
- [ ] task/server 既有套件回归（test_claude_sdk_integration / test_remote_tool_execute）保持绿

*Existing pytest/go-test infra covers the rest.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 真实 task 容器内 agent 调用 remote tool 闭环 | RTOOL-02/03 | 需 Docker 容器 + 真实 Claude SDK + 运行中 server | 跑一次带 remote_tools 的任务，确认 agent 调用工具并经 /api/tools/execute/ 返回 |
| docker logs / runner 日志无 PAT 明文 | RTOOL-03 | 容器日志目检 | 检查 docker logs 与 runner StreamLogs 无 friday_pat_ 明文 |
| 任务运行中吊销令牌，在途跑完仅阻断新调用 | RTOOL-04 | 时序相关人工触发 | 任务执行中吊销其令牌，确认在途任务跑完、后续工具调用被拒 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] PAT plaintext never in logs (task/runner/server) — assert in tests
- [ ] Wave 0 covers all MISSING references across 3 components
- [ ] No watch-mode flags
- [ ] Feedback latency < 150s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
