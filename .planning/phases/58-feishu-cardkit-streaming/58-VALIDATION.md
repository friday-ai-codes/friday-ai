---
phase: 58
slug: feishu-cardkit-streaming
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-17
---

# Phase 58 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. 源自 58-RESEARCH.md §6 四层 Validation Architecture + Nyquist 覆盖矩阵。**纯增量 phase**——CardKit 流式仅作 happy 正文流增强，既有 thinking 卡 + PATCH `update_card` + `build_answer_card`/`build_streaming_card`/`build_thinking_card` 与所有非流式分支（澄清/图片错误/waiting/空答案/异常）**必须逐字保持全绿**（零回归底线）。CardKit 任一步失败 → fail-soft 切回既有路径，答案/引用/usage 不丢（CARD-01 硬要求）。

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x (pytest-asyncio + pytest-django + respx) |
| **Config file** | `server/pyproject.toml` ([tool.pytest]) |
| **Quick run command** | `cd server && uv run pytest tests/test_feishu_cardkit.py tests/test_feishu_bot_cards.py -q` |
| **Full suite command** | `cd server && uv run pytest tests/test_feishu_cardkit.py tests/test_feishu_bot_pipeline.py tests/test_feishu_bot_integration.py tests/test_feishu_bot_cards.py -q` |
| **Estimated runtime** | ~25 秒 |

---

## Sampling Rate

- **After every task commit:** Run `cd server && uv run pytest tests/test_feishu_cardkit.py tests/test_feishu_bot_cards.py -q`
- **After every plan wave:** Run `cd server && uv run pytest tests/test_feishu_cardkit.py tests/test_feishu_bot_pipeline.py tests/test_feishu_bot_integration.py tests/test_feishu_bot_cards.py -q`（含既有 PATCH 卡片路径 / 工具进度 / p2p / 群聊 / welcome 全套——零回归门禁）
- **Before `$gsd-verify-work`:** 上述 full suite 全绿
- **Max feedback latency:** 30 秒

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 58-01-1 CardKit 4 httpx 方法 + service 委托 | 01 | 1 | CARD-01 | T-58-01 | 端点/payload 形状正确；`code!=0` → `FeishuIMError`（降级判定基础）；token 复用 `get_tenant_access_token` | unit | `uv run pytest tests/test_feishu_cardkit.py -q` | ❌ W0 | ⬜ pending |
| 58-01-2 bot_cards 2.0 流式卡构造器 + 终态 markdown | 01 | 1 | CARD-01 | — | schema 2.0 + streaming_mode/element_id；终态串含 answer+引用+usage、中文；既有 builder 逐字不变 | unit | `uv run pytest tests/test_feishu_bot_cards.py -q` | ✅(W0部分) | ⬜ pending |
| 58-02-1 流式段接 TEXT_DELTA + 惰性创建/推送/settle | 02 | 2 | CARD-01 | T-58-02 / T-58-03 | 只消费 TEXT_DELTA（P-1 不翻倍）；content 累积全量（P-4）；sequence 严格递增（P-2）；工具进度仍走 thinking 卡（D-4） | integration | `uv run pytest tests/test_feishu_bot_pipeline.py -q` | ✅(W1) | ⬜ pending |
| 58-02-2 fail-soft 降级 + 终态 + 零回归 | 02 | 2 | CARD-01 | T-58-04 / T-58-05 | create/push/settle 抛错 → 切既有 PATCH + answer 卡（答案不丢）；异常不冒泡成 status=error（P-9）；非流式分支零新 CardKit 调用 | integration | `uv run pytest tests/test_feishu_bot_pipeline.py tests/test_feishu_bot_integration.py -q` | ✅(W1) | ⬜ pending |
| 58-零回归 | 01/02 | 1+2 | CARD-01 | T-58-06 | 既有 PATCH 卡片路径 / 工具进度 / p2p / 群聊 / welcome 逐字不变；`send_card`/`update_card`/`build_answer_card`/`build_streaming_card`/`build_thinking_card` 符号不动 | integration | `uv run pytest tests/test_feishu_bot_pipeline.py tests/test_feishu_bot_integration.py tests/test_feishu_bot_cards.py -q` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `server/tests/test_feishu_cardkit.py` — **新文件**：`create_card_entity` / `send_card_entity` / `stream_card_content` / `settle_card_stream` 的 httpx 形状单测（端点 / payload / sequence 严格递增 / uuid 幂等 / `code!=0` → `FeishuIMError`），mock 点 `respx`（或 `patch httpx.AsyncClient`），无 DB / 无 `send_message_stream`。
- [ ] `server/tests/test_feishu_bot_cards.py` — **扩展既有文件**：新增 `build_streaming_card_v2`（schema 2.0 + streaming_mode/element_id）与 `build_answer_markdown`（终态单串 answer+引用+usage）单测；既有卡片测试逐字保留。
- [ ] `server/tests/test_feishu_bot_pipeline.py` — **扩展既有文件**：新增 `_text_delta_stream` 等 fake stream helper（产 `TOOL_USE_START` + 多个 `TEXT_DELTA` + 可选 `PART_DELTA` + `MESSAGE_COMPLETE`）；im_service `SimpleNamespace` 增 `create_card_entity`/`send_card_entity`/`stream_card_content`/`settle_card_stream`=`AsyncMock`。既有 11 个 pipeline 测试逐字保留。

*既有 `test_feishu_bot_pipeline.py` 已提供 `SimpleNamespace` im_service + `patch ConversationService.send_message_stream`（async gen 产 `AgentEvent`）+ `AsyncMock` 范式可直接复用；新增流式/降级测试沿用同范式。框架（pytest/respx）已在 `server/pyproject.toml` 依赖，无需安装。*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 真实飞书租户端到端流式卡片顺滑观感（无明显闪烁 / 全量重绘，逐字打字机增量） | CARD-01 / Success #2 | 需真实飞书应用（已开通 `cardkit:card:write` scope + 租户开通 CardKit）+ 真实 LLM Provider 凭证 + 飞书客户端 ≥7.20 肉眼观感 | 配置飞书 App + Provider，在群聊 @Friday 或私聊提问，肉眼确认正文逐字增量推进同一张卡片、无整段跳变；在未开通 CardKit 的租户重复 → 确认自动降级为既有 thinking→answer 卡且答案完整 |

*其余 phase 行为（端点/payload/sequence 形状、流式按序推送、parts 双轨防翻倍、fail-soft 降级、零回归）均有自动化验证。*

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
