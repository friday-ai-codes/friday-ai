# Phase 58: 飞书原生流式卡片（CardKit） - Context

**Gathered:** 2026-06-17
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — 推荐答案自动采纳)

<domain>
## Phase Boundary

本 phase 把飞书机器人对话回复从"PATCH 全量替换卡片"改为飞书**原生 CardKit 流式增量更新**——正文随 AI 生成逐步增量推送到同一张卡片，体验顺滑无全量重绘；流式失败/不支持时优雅降级回既有 PATCH 路径，回复绝不丢失。

**现状坐标（实证）：**
- `server/feishu/bot/service.py` `FeishuBotService.process_message`：先发"思考中"卡（`send_card`），消费 `ConversationService.send_message_stream` 事件流，仅在 `TOOL_USE_START` 时 `update_card`（PATCH 全量替换为 `build_streaming_card`），最终 `MESSAGE_COMPLETE` 后一次性 `_replace_card` 成 `build_answer_card`。**正文无增量**——TEXT_DELTA 事件当前完全未消费，用户只见"思考中→工具列表→最终整段答案"的跳变。
- `server/services/feishu_im.py` `FeishuIMClient.update_card`：`PATCH /im/v1/messages/{id}`（msg_type=interactive，全量 card content）——即现状全量替换实现。
- `server/feishu/cards/bot_cards.py`：卡片构造（thinking/streaming/answer/error/clarification/welcome），markdown block 为主。
- `agents/core/events.py`：`TEXT_DELTA="text_delta"` 已存在且为标准事件；bot 路径未消费。

**交付物边界：**
- 在 `FeishuIMClient` / `FeishuIMService` 新增 CardKit 原生流式 API 封装（创建流式卡片实体 + 增量推送文本 + 收尾定版），独立于既有 `send_card` / `update_card`（PATCH）方法。
- `FeishuBotService.process_message` 流式段改为：优先用 CardKit 流式卡片承载正文增量（消费 `TEXT_DELTA` 逐步 append），工具调用进度沿用既有语义（可并入流式卡片的状态区或保留 PATCH 提示）。
- 优雅降级：CardKit 创建/推送失败或环境不支持时，自动回退既有"思考卡→PATCH 更新→answer 卡"路径，最终答案与引用/usage 不丢失。
- 守护测试覆盖：CardKit 流式 happy path（增量推送顺序）、降级路径（CardKit 失败回退 PATCH 仍出答案）、零回归（既有 PATCH 卡片测试不破）。

**不在本 phase（Out of Scope）：**
- 飞书卡片交互组件（按钮/表单回调）与多卡片会话编排（v2 OPENX-03）。
- 工作流自动建群节点（Phase 59）。
- chat Web 前端流式（已有，非本 phase）。
</domain>

<decisions>
## Implementation Decisions

### CardKit 流式机制
- 新增飞书 CardKit 原生流式 API 封装（plan-phase research 须确认精确端点与协议，预期为：`POST /open-apis/cardkit/v1/cards` 创建卡片实体（`config.streaming_mode=true` + 含 element_id 的文本元素）→ `interactive` 消息引用 card_id 下发 → `PUT /open-apis/cardkit/v1/cards/{card_id}/elements/{element_id}/content`（带 sequence 单调递增）增量推送文本 → 收尾停止流式）。
- CardKit 方法独立新增，**绝不改** 既有 `send_card` / `update_card`（PATCH）签名与行为——PATCH 路径保留作为降级通道。
- 正文增量数据源：消费 `send_message_stream` 的 `TEXT_DELTA` 事件（`event.data["text"]`）累积推送；当前 bot 未消费 TEXT_DELTA，本 phase 新接入。
- sequence 管理：流式推送须带单调递增 sequence（飞书要求），用本地计数器；推送节流可选（合并短 delta 减少 API QPS，由实现按节流阈值定夺）。

### 工具进度与流式正文共存
- 工具调用进度（`TOOL_USE_START`）语义保留：优先并入 CardKit 流式卡片的"状态/工具区"（若 CardKit 支持多元素增量），否则在流式正文前以一段轻量前言呈现；不因切流式而丢失"正在调用 X 工具"的可见性。
- 最终定版：流式结束后用既有 `build_answer_card`（含引用/usage/matched_space_label）作为终态——CardKit 卡片收尾替换/定版为完整答案卡（保证引用与 token 统计齐全），或在 CardKit 卡内补齐这些区块（由 research 判断 CardKit 表达力）。

### 优雅降级（CARD-01 硬要求）
- CardKit 创建失败 / 推送失败 / 环境不支持（如租户未开通 cardkit）→ 自动回退既有路径：继续用"思考卡 + PATCH update_card + answer 卡"，最终答案、引用、usage 完整不丢。
- 降级判定要点（fail-soft）：任何 CardKit API 异常都 try/except 捕获 + 结构化 warning，切回 PATCH 分支；绝不让流式失败冒泡成"无回复/报错卡"（除非本就是真实处理错误）。
- waiting / 空答案 / 图片错误 / 澄清等既有分支逻辑完全保留（这些不是流式正文场景）。

### 测试边界
- CardKit 流式封装单测：创建卡片实体 / 增量推送（sequence 递增、content append）/ 收尾 API 的请求形状（mock httpx，断言端点/payload/sequence）。
- 服务层集成测：mock `send_message_stream` 产 TEXT_DELTA 序列 + mock CardKit client → 断言增量按序推送、终态定版为 answer 卡。
- 降级测：CardKit create/push 抛错 → 断言回退 PATCH 路径、最终仍 `_replace_card` 成 answer 卡（答案不丢）。
- 零回归测：既有 `test_feishu_bot_*` / `test_feishu_bot_cards` 全绿（PATCH 路径与卡片构造不破）。
- 真实飞书租户端到端观感（顺滑/无闪烁）属人工验收（需真实飞书应用），记 deferred（对齐既有飞书 E2E deferred 惯例）。

### the agent's Discretion
- CardKit 流式封装的方法命名/放置（`FeishuIMClient` 内新增 or 独立 `feishu_cardkit.py`）、节流策略、sequence 计数器实现，由 plan/execute 阶段按代码现状定夺。
- 工具进度并入流式卡片 vs 保留前言，依 research 对 CardKit 多元素增量能力的结论决定。
- 是否加 SystemSetting 开关启停原生流式（默认开，失败自动降级）——若实现简单可加，否则纯靠 fail-soft 降级。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/services/feishu_im.py` `FeishuIMClient`（`get_tenant_access_token` 缓存、`send_message` / `send_card` / `update_card` / httpx + tenacity rate-limit 重试范式）——CardKit 新方法复用 token/httpx/重试基建。
- `server/services/feishu_im.py` `FeishuIMService`（bot 用的便捷封装，`send_card` / `update_card` 委托）——新增 CardKit 流式委托方法。
- `server/feishu/bot/service.py` `FeishuBotService.process_message`：流式事件消费主循环（line 270-300）+ `_replace_card`（fail-soft update→send 兜底，line 583-604）——本 phase 主改点；`_replace_card` 的 fail-soft 范式可借鉴降级。
- `server/feishu/cards/bot_cards.py` `build_streaming_card` / `build_answer_card` / `build_thinking_card`：卡片构造，终态定版复用 answer 卡。
- `agents/core/events.py` `TEXT_DELTA` / `TOOL_USE_START` / `MESSAGE_COMPLETE` / `PHASE_TRANSITION`：事件常量，新接入 TEXT_DELTA。

### Established Patterns
- httpx.AsyncClient + tenant_access_token Bearer + `data.get("code")==0` 判定 + 结构化 structlog 日志；RateLimitError + tenacity 指数退避重试（`send_card`）。
- fail-soft 卡片更新：`_replace_card` 先 `update_card` 失败再 `send_card` 兜底——降级通道现成范式。
- 测试在 `server/tests/test_feishu_bot_*.py`（pipeline/integration/cards/...）；mock IM client/service。
- 测试命令：`cd server && uv run pytest tests/ -q -k feishu`（plan-phase 核对实际选择器）。

### Integration Points
- `ConversationService.send_message_stream`（`chat/conversation_service.py`）：bot 正文事件来源——research 须确认该流是否对 bot（role=developer）路径稳定发射 `TEXT_DELTA`（chat Web 已消费 TEXT_DELTA，预期发射，但须实证 bot 路径不被某些模式吞掉）。
- 飞书 CardKit API（`open.feishu.cn/open-apis/cardkit/v1/*`）：外部协议——research 须用 WebSearch 查飞书官方 CardKit 流式文档（2026）确认创建/推送/收尾端点、streaming_mode 配置、sequence 规则、element_id 约束、租户开通前提（降级判定依据）。
- `lark-oapi>=1.5.2`（已在依赖）：可能已内置 CardKit SDK 方法——research 须确认是否复用 SDK 而非手写 httpx（优先复用 SDK，与既有手写 httpx 二选一由 research 定）。

</code_context>

<specifics>
## Specific Ideas

- CardKit 原生流式承载正文 TEXT_DELTA 增量，是飞书侧与 Web 端 SSE 流式对称的"逐字增量"体验，替代当前"整段跳变"。
- 降级复用既有 `_replace_card` fail-soft 范式 + PATCH 通道，CARD-01 的"流式失败优雅降级、回复不丢"零额外成本兜底。
- token/httpx/tenacity 基建复用既有 `FeishuIMClient`，CardKit 仅加端点方法，最小新增面。
</specifics>

<deferred>
## Deferred Ideas

- 飞书卡片交互组件（按钮/表单回调）与多卡片会话编排——v2 OPENX-03。
- 真实飞书租户端到端顺滑观感人工验收——deferred（需真实飞书应用，对齐既有飞书 E2E deferred）。
- 流式正文的富 markdown/代码块分块渲染优化——若 CardKit 支持可后续打磨，非本 phase 必需。
</deferred>
