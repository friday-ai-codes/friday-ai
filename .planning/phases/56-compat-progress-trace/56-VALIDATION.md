---
phase: 56
slug: compat-progress-trace
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-17
---

# Phase 56 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. 源自 56-RESEARCH.md §6 四层 Validation Architecture + Nyquist 覆盖矩阵。

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x (pytest-asyncio + pytest-django) |
| **Config file** | `server/pyproject.toml` ([tool.pytest]) |
| **Quick run command** | `cd server && uv run pytest tests/compat/ -q` |
| **Full suite command** | `cd server && uv run pytest tests/compat/ -q` |
| **Estimated runtime** | ~15 秒 |

---

## Sampling Rate

- **After every task commit:** Run `cd server && uv run pytest tests/compat/test_adapter.py tests/compat/test_progress.py -q`
- **After every plan wave:** Run `cd server && uv run pytest tests/compat/ -q`
- **Before `$gsd-verify-work`:** Full compat suite must be green
- **Max feedback latency:** 20 秒

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 56-纯函数映射 | 01 | 1 | TRACE-01 | INV-5 / P-2 | progress 文本仅含工具名高层语义，不含 tool_input/result/CoT | unit | `uv run pytest tests/compat/test_progress.py -q` | ❌ W0 | ⬜ pending |
| 56-adapter 集成 | 01 | 1 | TRACE-01, TRACE-02 | P-3 | 无 tool_calls 字段 / finish_reason≠tool_calls | integration | `uv run pytest tests/compat/test_adapter.py -q` | ✅ | ⬜ pending |
| 56-RAG progress | 02 | 2 | TRACE-01 | INV-5 | 检索 progress 只透出命中数等非敏感计数 | integration | `uv run pytest tests/compat/ -k progress -q` | ❌ W0 | ⬜ pending |
| 56-零回归 | 01/02 | 2 | TRACE-02 | — | 无事件序列 SSE 逐字等价，非流式 content 不变 | integration | `uv run pytest tests/compat/test_adapter.py -q` | ✅ | ⬜ pending |
| 56-安全不泄漏 | 01 | 1 | INV-5 | P-2 | sentinel 全不出现于 SSE 字节流 | unit/integration | `uv run pytest tests/compat/ -k sentinel -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `server/tests/compat/test_progress.py` — 纯函数映射单测（各工具名→预期文本 / 未知→None / sentinel 不泄漏）
- [ ] 扩充 `server/tests/compat/test_adapter.py` — 注入 TOOL_USE_START 序列 + RAG progress 集成 + 零回归 byte-eq

*既有 `test_adapter.py` 已提供 `_make_runner` / `_collect` 范式可复用。*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 真实外部 OpenAI 客户端（如 openai-python / curl）流式可见"正在检索 RAG" | TRACE-01 | 需真实 Provider 凭证 + 真实查询命中 RAG | 配置 Provider，`curl -N /v1/chat/completions stream:true` 含命中 RAG 的 query，观察 reasoning_content progress |

*其余 phase 行为均有自动化验证。*

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 20s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
