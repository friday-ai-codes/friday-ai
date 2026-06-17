---
phase: 58-feishu-cardkit-streaming
plan: 01
subsystem: api
tags: [feishu, cardkit, streaming, httpx, im]

# Dependency graph
requires:
  - phase: 27-feishu-interface-fixes
    provides: FeishuIMClient/FeishuIMService（get_tenant_access_token + send_message/send_card/update_card 手写 httpx 基建）
provides:
  - FeishuIMClient.create_card_entity / send_card_entity / stream_card_content / settle_card_stream（CardKit v1 4 端点封装）
  - FeishuIMService 4 个 CardKit 委托方法
  - build_streaming_card_v2（schema 2.0 流式卡构造器）
  - build_answer_markdown（终态 answer+引用+usage 单 markdown 串）
affects: [58-02, feishu-bot-streaming, cardkit]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CardKit 手写 httpx 封装：复用 get_tenant_access_token + httpx.AsyncClient + data.get('code')==0 判定 + structlog（与 send_card/update_card 同构，不引 lark-oapi cardkit SDK）"
    - "content 全量文本（非 delta）+ sequence 由调用方严格递增透传（方法层不内置计数器）+ uuid 幂等"
    - "respx 形状单测：token 缓存预置避免真实鉴权请求，捕获 request body 断言端点/payload"

key-files:
  created:
    - server/tests/test_feishu_cardkit.py
  modified:
    - server/services/feishu_im.py
    - server/feishu/cards/bot_cards.py
    - server/tests/test_feishu_bot_cards.py

key-decisions:
  - "CardKit 4 方法直接进 feishu_im.py（不新建 feishu_cardkit.py），与 send_card/update_card 同类，复用同一 token/httpx 基建（D-1）"
  - "sequence 由调用方传入并严格递增，方法层只透传 + 形状断言，不内置计数器（P-2，留 Wave 2）"
  - "content 为全量文本，方法不做累积（P-4，累积是 bot 职责）"
  - "终态用 build_answer_markdown 单 markdown 串（复用 _reference_lines + usage 行，与 build_answer_card 降级路径表达一致）供 Wave 2 content PUT（D-3）"
  - "settle_card_stream 与 stream_card_content 共享同一单调 sequence；code!=0 统一抛 FeishuIMError（F-5 降级判定基础）"

patterns-established:
  - "CardKit 封装：create_card_entity（POST /cardkit/v1/cards）→ send_card_entity（复用 send_message interactive）→ stream_card_content（PUT elements/{id}/content 全量+sequence）→ settle_card_stream（PATCH settings streaming_mode=false）"
  - "uuid 关键字参数默认空串，非空才写入 body（D-6 幂等）"

requirements-completed: [CARD-01]

# Metrics
duration: 14 min
completed: 2026-06-17
---

# Phase 58 Plan 01: CardKit 封装层 Summary

**FeishuIMClient/Service 手写 httpx 新增 CardKit v1 4 端点流式封装（create/send/stream/settle，全量 content + 严格递增 sequence + uuid 幂等 + code!=0→FeishuIMError），并新增 schema 2.0 流式卡构造器 build_streaming_card_v2 与终态单串 helper build_answer_markdown**

## Performance

- **Duration:** 14 min
- **Started:** 2026-06-17T12:36Z
- **Completed:** 2026-06-17T12:50Z
- **Tasks:** 2
- **Files modified:** 4（3 改 + 1 新建）

## Accomplishments
- `FeishuIMClient` 新增 4 个 CardKit 原生流式方法（手写 httpx，复用 `get_tenant_access_token`）：`create_card_entity`（POST `/cardkit/v1/cards`，type=card_json + 转义 2.0 JSON → card_id）、`send_card_entity`（复用 `send_message` interactive 引用 card_id）、`stream_card_content`（PUT `.../elements/{id}/content`，全量文本 + sequence）、`settle_card_stream`（PATCH `.../settings`，streaming_mode=false）；`code!=0` 统一抛 `FeishuIMError`。
- `FeishuIMService` 新增 4 个同构委托方法。
- `bot_cards.py` 新增 `build_streaming_card_v2`（schema 2.0 流式卡，单 markdown 元素带 element_id）与 `build_answer_markdown`（终态 answer+引用+usage 单 markdown 串，复用 `_reference_lines` + usage 行格式）。
- 新建 `test_feishu_cardkit.py`（respx 形状单测 10 例）：端点/payload/sequence 严格递增/content 全量/uuid 幂等/code!=0 抛错全覆盖；扩展 `test_feishu_bot_cards.py`（4 新例）。
- 零回归：`send_card`/`update_card`/`send_message`/`get_tenant_access_token` 与既有所有卡片 builder 符号逐字不变。

## Task Commits

Each task was committed atomically:

1. **Task 1: FeishuIMClient 4 CardKit httpx 方法 + Service 4 委托 + httpx 形状单测** - `468ea4891` (feat)
2. **Task 2: bot_cards build_streaming_card_v2 + build_answer_markdown + 单测** - `6613b67a4` (feat)

**Plan metadata:** (this commit) (docs: complete plan)

## Files Created/Modified
- `server/services/feishu_im.py` - `FeishuIMClient` 4 CardKit 方法（create/send/stream/settle）+ `FeishuIMService` 4 委托
- `server/feishu/cards/bot_cards.py` - `build_streaming_card_v2`（schema 2.0 流式卡）+ `build_answer_markdown`（终态单串）
- `server/tests/test_feishu_cardkit.py` - CardKit httpx 形状单测（新建，10 例）
- `server/tests/test_feishu_bot_cards.py` - 扩展 build_streaming_card_v2 / build_answer_markdown 单测（4 新例）

## Decisions Made
None - followed plan as specified（关键决策 D-1/P-2/P-4/D-3/D-6 均在 plan 内已拍板，逐条落实）。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None。Task 1 测试文件首次 ruff `I001`（import 块未排序，`unittest.mock` 与第三方库顺序）即时修正后全绿。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Wave 2（58-02）可消费：`im_service.create_card_entity/send_card_entity/stream_card_content/settle_card_stream` 4 委托 + `build_streaming_card_v2`/`build_answer_markdown` 2 helper 齐备，仅需在 `bot/service.py` 流式段接线 `TEXT_DELTA`（sequence 计数器、节流、fail-soft 降级）。
- 验证：`cd server && uv run pytest tests/ -q -k "feishu_cardkit or feishu_bot_cards or feishu_card_retry"` → 31 passed（10 cardkit + 8 bot_cards + 13 card_retry），零回归。

---
*Phase: 58-feishu-cardkit-streaming*
*Completed: 2026-06-17*
