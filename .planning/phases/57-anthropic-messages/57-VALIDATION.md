---
phase: 57
slug: anthropic-messages
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-17
---

# Phase 57 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. 源自 57-RESEARCH.md §6 四层 Validation Architecture + Nyquist 覆盖矩阵。纯增量 phase——除新增测试外，**既有 `tests/compat/` 必须逐字保持全绿**（零回归底线）。

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x (pytest-asyncio + pytest-django) |
| **Config file** | `server/pyproject.toml` ([tool.pytest]) |
| **Quick run command** | `cd server && uv run pytest tests/compat/test_anthropic_adapter.py tests/compat/test_anthropic_schemas.py tests/compat/test_messages.py -q` |
| **Full suite command** | `cd server && uv run pytest tests/compat/ -q` |
| **Estimated runtime** | ~20 秒 |

---

## Sampling Rate

- **After every task commit:** Run `cd server && uv run pytest tests/compat/test_anthropic_adapter.py tests/compat/test_anthropic_schemas.py tests/compat/test_messages.py -q`
- **After every plan wave:** Run `cd server && uv run pytest tests/compat/ -q`（含既有 OpenAI adapter/view/progress/auth 全套——零回归门禁）
- **Before `$gsd-verify-work`:** Full compat suite must be green
- **Max feedback latency:** 25 秒

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 57-01-1 serializer+规整 | 01 | 1 | ANTHROPIC-01 | INV-5 | max_tokens 必填、system 提顶、content 仅取 text part | unit | `uv run pytest tests/compat/test_anthropic_schemas.py -q` | ❌ W0 | ⬜ pending |
| 57-01-2 adapter 骨架（SSE 编码+事件骨架+text 路径） | 01 | 1 | ANTHROPIC-01 | P-1 / P-5 | 双行帧 `event:`+`data:`、绝不发 tool_use block、不复用 sse_encode | unit/integration | `uv run pytest tests/compat/test_anthropic_adapter.py -q` | ❌ W0 | ⬜ pending |
| 57-01-3 MessagesView 非流式+urls | 01 | 1 | ANTHROPIC-01 | P-2 / P-8 | 响应 usage=input_tokens/output_tokens、content 仅 text 正文 | integration | `uv run pytest tests/compat/test_messages.py -q` | ❌ W0 | ⬜ pending |
| 57-02-1 translate_stream prelude thinking+TOOL_USE 预埋 | 02 | 2 | ANTHROPIC-02 | INV-5 / P-3 / P-5 / P-6 | thinking 先于 text、index 配对、绝不 tool_use、THINKING 不外透 | integration | `uv run pytest tests/compat/test_anthropic_adapter.py -q` | ✅(W1) | ⬜ pending |
| 57-02-2 MessagesView 流式接线 | 02 | 2 | ANTHROPIC-02 | INV-5 / P-8 | view 级命中 RAG→thinking progress 先于正文、非流式 content 零污染、sentinel 不泄漏 | integration | `uv run pytest tests/compat/test_messages.py -q` | ✅(W1) | ⬜ pending |
| 57-零回归 | 01/02 | 1+2 | ANTHROPIC-01/02 | — | OpenAI 端点逐字不变、progress.py 不改 | integration | `uv run pytest tests/compat/ -q` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `server/tests/compat/test_anthropic_schemas.py` — serializer 校验（max_tokens 必填/`<1`、system 可选、content string/parts、role∈{user,assistant}）+ `anthropic_to_openai_messages` 规整纯函数（system 提顶、block→text part、text 拼接）
- [ ] `server/tests/compat/test_anthropic_adapter.py` — `anthropic_sse_encode` 双行帧 + 8 个事件骨架纯函数形状 + adapter 流式集成（注入 AgentEvent 序列）
- [ ] `server/tests/compat/test_messages.py` — `MessagesView` 流式/非流式 view 级集成 + 安全 sentinel + 零回归断言

*既有 `test_adapter.py` 已提供 `_make_runner` / `_collect` / `_collect_raw` 范式可直接复用（注入 AgentEvent 序列、收集 SSE 字节）；既有 `test_chat_completions.py` 提供 `AsyncClient` + `patch _build_runner` / `patch prepare_messages_with_meta` view 级范式。*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 真实 Anthropic 客户端（anthropic-python / curl）`POST /v1/messages` 流式可见 thinking block trace | ANTHROPIC-02 | 需真实 Provider 凭证 + 真实查询命中 RAG | 配置 Provider，`curl -N /v1/messages -d '{"model":"x","max_tokens":1024,"stream":true,"messages":[...]}'` 命中 RAG，观察 `event: content_block_delta`+`thinking_delta` 在正文前出现 |

*其余 phase 行为均有自动化验证。*

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 25s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
