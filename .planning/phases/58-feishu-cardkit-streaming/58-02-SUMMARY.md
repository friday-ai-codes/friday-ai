---
phase: 58-feishu-cardkit-streaming
plan: 02
subsystem: api
tags: [feishu, cardkit, streaming, bot, fail-soft]

# Dependency graph
requires:
  - phase: 58-feishu-cardkit-streaming (Plan 01)
    provides: FeishuIMService.create_card_entity/send_card_entity/stream_card_content/settle_card_stream + build_streaming_card_v2/build_answer_markdown
provides:
  - FeishuBotService 流式段接入原生 CardKit（TEXT_DELTA → 惰性创建 + 节流增量推送 + 终态 settle）
  - _CardKitStream 本轮会话态 dataclass（单调 sequence，content PUT 与 settle 共享）
  - CardKit fail-soft 降级（create/stream/settle 任一失败 → 切回 build_answer_card，答案/引用/usage 不丢）
  - W-2 settle-only 失败语义（内容已送达视为 answered，不重复发卡）
  - W-1 thinking 卡终态收口（绝不留「思考中」悬挂）
affects: [feishu-bot-streaming, cardkit]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "流式正文只消费 TEXT_DELTA（绝不消费 parts 双轨增量事件），全量 content 累积 + 单调 sequence 透传（P-1/P-2/P-4）"
    - "CardKit 全程 try/except fail-soft + cardkit_disabled/cardkit_done 守卫：失败仅结构化 warning、绝不冒泡成 status=error，切回既有 PATCH 路径"
    - "区分『内容已送达 + 仅 settle 失败』(answered，不补卡) 与『内容未送达』(完全降级出 answer 卡)（W-2）"

key-files:
  created:
    - .planning/phases/58-feishu-cardkit-streaming/58-02-SUMMARY.md
  modified:
    - server/feishu/bot/service.py
    - server/tests/test_feishu_bot_pipeline.py

key-decisions:
  - "节流阈值抽为模块常量 _CARDKIT_STREAM_THROTTLE_S=0.3（可被测试 patch 为 0 关闭节流），content PUT 直接引用模块全局以保证 patch 生效（P-3）"
  - "W-1 thinking 卡收口用独立 _build_cardkit_closeout_card（『已回复，请见下方卡片 👇』），绝不复用 build_streaming_card([]) 那渲染『思考中...』会留永久悬挂旧卡"
  - "W-2：终态先推全量 content（content_delivered=True）→ 再收口 thinking 卡 → 最后 settle；settle 失败时内容已渲染故视为 answered（last_bot_message_id=CardKit message_id），绝不补发 build_answer_card 避免答案重复两次"
  - "TOOL_USE_START 工具进度保持既有 update_card(thinking_card_id, build_streaming_card(tool_names))（D-4，留 thinking 卡不并入 CardKit）"

patterns-established:
  - "惰性创建：首个有效 TEXT_DELTA 才 create_card_entity(build_streaming_card_v2)+send_card_entity；纯工具/waiting/空答案轮次无 TEXT_DELTA 故不产 CardKit 实体（F-1）"
  - "CardKit 失败 ≠ 处理失败：真实错误（image/empty/waiting/澄清/异常）仍走既有 error/waiting/clarification 卡，不被降级逻辑吞掉（P-9 边界）"

requirements-completed: [CARD-01]

# Metrics
duration: 8 min
completed: 2026-06-17
---

# Phase 58 Plan 02: bot 接线 + fail-soft 降级 Summary

**FeishuBotService.process_message 流式段接入原生 CardKit（TEXT_DELTA 惰性创建 + ~300ms 节流全量增量推送 + sequence 单调 + 终态 build_answer_markdown/settle 收尾 + thinking 卡收口），CardKit 任一步失败全程 try/except fail-soft 切回 build_answer_card，答案/引用/usage 不丢且绝不冒泡成 status=error**

## Performance

- **Duration:** 8 min
- **Started:** 2026-06-17T12:44Z
- **Completed:** 2026-06-17T12:52Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `bot/service.py` 流式段新增 `elif event.type == TEXT_DELTA:` 分支：累积全量 `body`（P-4）、首个有效 delta 惰性 `create_card_entity(build_streaming_card_v2)` + `send_card_entity`、按 `_CARDKIT_STREAM_THROTTLE_S` 节流推 `stream_card_content`（sequence 经 `_CardKitStream.next_sequence` 单调递增，P-2/P-3）。
- 模块级新增 `@dataclass(slots=True) _CardKitStream`（card_id/element_id/message_id/sequence + next_sequence）与 `_build_cardkit_closeout_card`（W-1 收口卡）。
- `MESSAGE_COMPLETE` 终态：CardKit 可用且有正文 → 推 `build_answer_markdown` 全量终态 + 收口 thinking 卡 + `settle_card_stream`；`if not cardkit_done` 守卫包住既有 `build_answer_card` + `_replace_card` 兜底。
- **P-1**：只消费 TEXT_DELTA，绝不消费 parts 双轨增量事件（service.py grep 零 `PART_DELTA`）；混入 PART_DELTA 正文不翻倍。
- **D-2/P-9 fail-soft**：create/send/stream/settle 四类调用全程 try/except + 结构化 warning（`feishu_cardkit_create_failed`/`_stream_failed`/`_settle_failed`，4 处），失败置 `cardkit_disabled`/不改 result，降级回 build_answer_card。
- **W-2**：内容已送达仅 settle 失败 → 视为 answered（last_bot_message_id=CardKit message_id），不重复发卡；内容推送阶段失败才完全降级。
- 既有非流式分支（澄清/图片错误/waiting/空答案/异常）逐字保留（git diff 限流式段 + import + dataclass）。

## Task Commits

Each task was committed atomically:

1. **Task 1: _CardKitStream + 流式段 TEXT_DELTA 接线（惰性创建 + 节流增量 + 终态 stream+settle + W-1 收口）+ 流式集成测** - `045fe332b` (feat)
2. **Task 2: fail-soft 降级 + W-2 settle-only + 零回归测试** - `fbc96b8f7` (test)

**Plan metadata:** (this commit) (docs: complete plan)

## Files Created/Modified
- `server/feishu/bot/service.py` - `_CardKitStream` dataclass + `_build_cardkit_closeout_card` + `_CARDKIT_STREAM_THROTTLE_S` 常量 + 流式段 TEXT_DELTA 接线 + 终态 CardKit stream/settle + `if not cardkit_done` 降级守卫 + import（time/TEXT_DELTA/build_streaming_card_v2/build_answer_markdown）
- `server/tests/test_feishu_bot_pipeline.py` - `_text_delta_stream`/`_cardkit_im_service` helper + 流式集成测（递增 sequence/全量 content/PART_DELTA 防翻倍/D-4/W-1）+ 4 降级/边界测（create 失败 / stream 中途失败 / settle-only W-2 / waiting 零 CardKit 调用）

## Decisions Made
- 见 frontmatter `key-decisions`（节流模块常量可 patch、W-1 独立收口卡、W-2 终态顺序 content→收口→settle、D-4 工具进度留 thinking 卡）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - 正确性] W-2 终态顺序与语义按 checker 修正实现（优先于 plan Task 2 原测描述）**
- **Found during:** Task 2（settle-only 失败测）
- **Issue:** plan Task 2 原文 `test_cardkit_settle_failure_still_answers` 描述「终态以 build_answer_card 兜底」，但 user critical constraint W-2 明确要求 settle-only 失败时内容已渲染、视为 answered 且**不再**补发 build_answer_card（避免答案重复两次）。两者冲突。
- **Fix:** 以 W-2 为准——终态顺序 stream content（content_delivered=True）→ 收口 thinking 卡 → settle；settle 失败走 `content_delivered` 分支视为 answered（last_bot_message_id=CardKit message_id），断言无第二张 answer 卡（无「已参考上下文」）。
- **Files modified:** server/feishu/bot/service.py, server/tests/test_feishu_bot_pipeline.py
- **Verification:** `test_cardkit_settle_failure_still_answers` 断言 status=answered + last_bot_message_id=="om_1" + update_card 仅 2 次且无「已参考上下文」。
- **Committed in:** `fbc96b8f7`（Task 2 commit）

**2. [Rule 1 - 一致性] P-1 注释去除字面 `PART_DELTA` token**
- **Found during:** Task 2（verification grep「service.py 不含 PART_DELTA」）
- **Issue:** P-1 注释含字面 `PART_DELTA`，触发 verification grep 误报。
- **Fix:** 改写为「绝不读 parts 双轨增量事件」，保持语义且 grep 干净（service.py 零 `PART_DELTA`）。
- **Files modified:** server/feishu/bot/service.py
- **Verification:** `rg PART_DELTA feishu/bot/service.py` 零命中。
- **Committed in:** `fbc96b8f7`（Task 2 commit）

---

**Total deviations:** 2 auto-fixed（1 正确性按 checker W-2 修正、1 一致性注释）。
**Impact on plan:** W-2 修正使语义更正确（避免答案重复），与 user critical constraint 一致；无 scope creep。

## Issues Encountered
None。`uv run` 须在 `server/` 目录执行（仓库内另有同名 `server/server/` 子目录，注意不要重复 `cd server`）。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 58 完成（2/2 plans，CARD-01 落地）：CardKit 封装层（58-01）+ bot 接线/fail-soft 降级（58-02）齐备。
- 验证：`cd server && uv run pytest tests/test_feishu_bot_pipeline.py tests/test_feishu_bot_integration.py tests/test_feishu_bot_cards.py -q` → 30 passed，零回归。
- 真实「顺滑观感」（Success #2）为人工验收 deferred（需真飞书租户开通 CardKit）。
- Ready for Phase 59（工作流自动建群节点，GROUP-01）。

---
*Phase: 58-feishu-cardkit-streaming*
*Completed: 2026-06-17*
