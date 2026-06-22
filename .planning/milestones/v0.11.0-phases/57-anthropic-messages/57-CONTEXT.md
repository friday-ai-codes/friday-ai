# Phase 57: Anthropic 兼容端点 `/v1/messages` - Context

**Gathered:** 2026-06-17
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — 推荐答案自动采纳)

<domain>
## Phase Boundary

本 phase 新增 Anthropic Messages 兼容端点 `POST /v1/messages`，复用既有 chat/agent 内核（`_build_runner` + `prepare_messages_with_meta` + `LangChainAgentRunner`），提供 Anthropic Messages 形状的请求/响应映射，非流式 + 流式（SSE）均可用，trace/progress 经 Anthropic `thinking` content block 透出（复用 Phase 56 的同一 §15 事件 taxonomy 映射与 `retrieval_to_progress` 派生，INV-5 非原始 CoT）。

**交付物边界：**
- 新增 `POST /v1/messages`（含带/不带末尾斜杠双注册，对齐既有 compat 路由策略），落在既有 `server/compat/` app，新增 `MessagesView`（adrf `APIView`，复用 `OptionalBearerTokenAuth`）。
- 请求按 Anthropic Messages 形状映射：`model` / `messages`（role: user/assistant，content: string 或 content blocks）/ `system`（顶层 system prompt）/ `max_tokens`（必填）/ `stream` / `temperature`，并复用 compat 既有扩展字段 `repository_ids` / `project_id`（RAG 范围）。
- 新增 `AnthropicCompatAdapter`（与 `OpenAICompatAdapter` 平行），把 `AgentEvent` 流翻译为 Anthropic Messages SSE 事件序列：`message_start` → (`content_block_start` / `content_block_delta` / `content_block_stop`) → `message_delta` → `message_stop`，含 `ping` 可选。
- 非流式响应聚合为 Anthropic Messages 形状：`{id, type:"message", role:"assistant", content:[{type:"text",text:...}], model, stop_reason, stop_sequence, usage:{input_tokens, output_tokens}}`。
- trace/progress 经 `thinking` content block 透出（`content_block_start type=thinking` + `content_block_delta type=thinking_delta`），数据源复用 Phase 56 的 `tool_event_to_progress`（事件映射，前向兼容）+ `retrieval_to_progress`（真实 RAG 命中计数，兑现可见效果）。
- 既有 OpenAI compat 端点（`/v1/chat/completions`、`/v1/models`）零回归。

**不在本 phase（Out of Scope）：**
- Anthropic 端点的工具使用（`tool_use` / `tool_result` content block）与多模态 content block 全量对齐（v2 OPENX-02）。
- 标准双向 `tool_calls`（客户端自带工具回传，v2 OPENX-01）。
- 暴露模型私有原始 CoT / 原始 thinking 链（INV-5 永久 Out of Scope）。
- 动态 model 列表 / `count_tokens` 等 Anthropic 周边端点。
</domain>

<decisions>
## Implementation Decisions

### 端点与请求映射
- 端点 `POST /v1/messages`（+ `/v1/messages/`），新增独立 `MessagesView`，与 OpenAI 端点共用 `server/compat/` app、`OptionalBearerTokenAuth`、`_build_runner`、`prepare_messages_with_meta`。
- 新增 `AnthropicMessagesRequestSerializer`：`model`（CharField，固定忽略实际值复用 `friday-default`）、`max_tokens`（IntegerField，required，min 1，Anthropic 必填）、`messages`（user/assistant，content 支持 string 与 text/image_url content parts）、`system`（顶层 system，string 或 content blocks，可选）、`stream`（默认 False）、`temperature`（可选 0–1）、复用 `repository_ids` / `project_id` 扩展字段。
- 消息转换复用 `request_handler` 的转换语义：把 Anthropic `system` 顶层字段 + `messages` 一起规整为 OpenAI 风格 dict 后委托 `prepare_messages_with_meta`（避免重写 RAG 注入/检索内核）——即新增一个薄 `messages` 规整 helper，把 Anthropic 形状摊平成 `prepare_messages_with_meta` 期望的 `[{role, content}]`（system → role=system 注入到列表首位）。

### trace/progress → thinking block 映射
- progress/trace 透出载体为 Anthropic `thinking` content block：`content_block_start{type:"thinking"}` + 多个 `content_block_delta{type:"thinking_delta", thinking:"..."}` + `content_block_stop`。
- 数据源与 Phase 56 完全同源：`retrieval_to_progress(retr)` 派生命中计数 progress（兑现 ANTHROPIC-02 可见效果，对应 OpenAI 端的 prelude）、`tool_event_to_progress(evt)` 映射未来 `TOOL_USE_*` 事件（前向兼容预埋；DEVIATION 同 Phase 56——compat runner 当前不绑定 tools，故实际可见 progress 由检索计数兑现）。
- 正文走标准 `text` content block：`content_block_start{type:"text"}` + `content_block_delta{type:"text_delta", text:"..."}` + `content_block_stop`。
- content block index 管理：thinking block（若有 prelude/trace）占 index 0，text block 紧随其后；无 trace 时 text block 占 index 0（保持序列合法）。
- 绝不输出 `tool_use` content block 承载内部工具（对应 TRACE-02：规范 Anthropic 客户端见 `tool_use` 会挂起等待 `tool_result` 回传而卡死）；绝不内联 tool_input/result/error/query 原文/模型 CoT（INV-5，与 Phase 56 sentinel 守护同标准）。

### 流式 SSE 事件序列（Anthropic 规范）
- `message_start`（含 `message` 骨架：id/type/role/model/content:[]/stop_reason:null/usage）→ 可选 thinking block（trace）→ text block（正文）→ `message_delta`（含 `delta.stop_reason` + 累计 `usage.output_tokens`）→ `message_stop`。
- SSE 行格式为 Anthropic 风格 `event: <type>\n` + `data: <json>\n\n`（区别于 OpenAI 的纯 `data:` + `[DONE]`）——新增 Anthropic 专用 SSE 编码 helper（不复用 OpenAI `sse_encode` 的 `data:`-only 格式）。
- `stop_reason` 映射：MESSAGE_COMPLETE status=completed → `end_turn`；length → `max_tokens`；interrupted → `end_turn`（Anthropic 无 interrupted）。
- ERROR 事件 → Anthropic error SSE（`event: error` + `{type:"error", error:{type:"api_error", message:...}}`），不泄漏 traceback（对齐 Phase 56 安全约束）。

### 降级与零回归
- 缺事件 / runner 不发工具事件时优雅降级：无 trace 则不产 thinking block，仅 text block + 收尾事件，序列仍合法。
- 既有 OpenAI 端点零改动（adapter/views/urls 仅新增，不改既有符号）——`AnthropicCompatAdapter` 与 `MessagesView` 为纯新增，OpenAI 路径逐字不变。
- 非流式 Anthropic 响应：thinking/progress 不污染 `content[].text` 正文文本块；若聚合 thinking，单独放 `thinking` content block 或丢弃（取"progress 不进非流式正文文本块"，最小化语义复杂度——非流式默认丢弃 trace，仅返回 text 正文，与 OpenAI 非流式忽略 prelude 对称）。
- 映射逻辑尽量复用 Phase 56 纯函数（`progress.py` 的 `tool_event_to_progress` / `retrieval_to_progress`），Anthropic 专属仅 SSE 事件骨架构造（做成可独立单测的 helper）。

### 测试边界
- 单测：Anthropic SSE 事件骨架构造 helper（message_start/content_block_*/message_delta/message_stop 形状）；请求 serializer 校验（max_tokens 必填、system 可选、content parts）。
- adapter 流式集成测：注入含检索 prelude + TEXT_DELTA + MESSAGE_COMPLETE 的序列 → 断言 SSE 事件序列顺序正确、trace 经 thinking_delta、正文经 text_delta、**不含** `tool_use` block、`stop_reason` 正确。
- view 级集成测：`MessagesView.post(stream=True)` mock runner + 检索元数据 → 断言 thinking progress 先于 text 正文；`post(stream=False)` → 断言聚合为 Anthropic Messages 形状且 content 正文零污染。
- 零回归测：既有 `tests/compat/` 全绿（OpenAI 端点逐字不变）。
- 安全测：thinking/text 文本不泄漏注入的敏感 sentinel（tool_input/result/query 原文 / CoT），复用 Phase 56 sentinel 范式。

### the agent's Discretion
- Anthropic SSE helper 的命名与放置（新建 `server/compat/anthropic_adapter.py` + 复用/扩展 `progress.py`，或单独 `anthropic_streaming.py`），由 plan/execute 阶段按代码现状定夺。
- thinking block 的具体 index 编号策略与 `ping` 事件是否发送由实现决定（Anthropic 客户端对 ping 容忍可选）。
- 非流式是否保留 thinking content block（默认丢弃 trace 仅返回正文，如实现简单可保留）。
- system 顶层字段为 content blocks 数组时的摊平细节（取 text parts 拼接，对齐 `_content_text`）。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/compat/views.py` `_build_runner()`：解析系统默认 Provider 凭证构建 `LangChainAgentRunner`，失败返回 None（→503）——`MessagesView` 直接复用，不重写。
- `server/compat/views.py` `ChatCompletionsView`：流式 `StreamingHttpResponse` + `_stream_chunks` 范式、非流式聚合范式——`MessagesView` 镜像结构（换 Anthropic SSE 编码与聚合形状）。
- `server/compat/request_handler.py` `prepare_messages_with_meta(messages, repository_ids, project_id) -> (lc_messages, retr)`：OpenAI messages → LangChain BaseMessage + RAG 注入 + 返回检索结果元数据——Anthropic 路径规整 messages 后直接复用（含 RAG 三层 fallback、检索失败降级）。
- `server/compat/progress.py` `retrieval_to_progress(result) -> list[str]`（命中→["正在检索 RAG…","检索完成，命中 N 处"]，未命中→[]）+ `tool_event_to_progress(evt)`（TOOL_USE_START→中文语义，否则 None）：Phase 56 纯函数，Anthropic thinking block 复用同一数据源（INV-5 仅命中计数/工具名语义）。
- `server/compat/adapter.py` `OpenAICompatAdapter.translate_stream`：AgentEvent if/elif 分派 + prelude 注入范式的参考实现；`AnthropicCompatAdapter` 平行新建（不改此文件）。
- `server/compat/auth.py` `OptionalBearerTokenAuth`、`server/compat/error_handlers.py`、`server/compat/schemas.py`：认证/错误/序列化器复用与镜像。
- `server/agents/core/events.py`：`TEXT_DELTA` / `THINKING` / `TOOL_USE_START` / `TOOL_USE_RESULT` / `MESSAGE_COMPLETE` / `ERROR` 常量 + `AgentEvent(type, data)` 形状——adapter 翻译源。
- `server/agents/langchain_runner.py` `LangChainAgentRunner.stream(prompt)`：AgentEvent 异步流，prompt 为 `list[BaseMessage]`——Anthropic 与 OpenAI 共用同一 runner.stream。

### Established Patterns
- 静态方法类 adapter + async generator yield SSE bytes；事件类型 if/elif 分派；`include_usage` / prelude 分支统一处理。
- 双路由注册（带/不带末尾斜杠）规避 `APPEND_SLASH` POST redirect（见 `server/compat/urls.py` 注释）。
- adrf `APIView` + `authentication_classes=[]` + `permission_classes=[OptionalBearerTokenAuth]`（async 上下文禁 JWT lazy-load user，见 `ChatCompletionsView` Pitfall 6）。
- 守护测试在 `server/tests/compat/`；纯函数 + adapter 集成 + view 级 + 零回归 + 安全 sentinel 多层（Phase 56 已建立四层范式）。
- 测试命令：`cd server && uv run pytest tests/compat/ -q`。

### Integration Points
- `server/friday/urls.py`：compat app 的 `/v1/*` 挂载点——`/v1/messages` 经 `server/compat/urls.py` 新增 path 自动生效（确认 compat urls include 前缀为 `v1/`，plan-phase 核对）。
- `MessagesView` 非流式/流式两路径均经 `prepare_messages_with_meta` 单次检索（对齐 Phase 56 Plan 02：流式派生 thinking prelude、非流式忽略 retr，不二次检索、content 零回归）。
- `LangChainAgentRunner.stream()` 当前 compat 路径不绑定 tools（Phase 56 RESEARCH F-1/D-1 DEVIATION）——`tool_event_to_progress` 分支为前向兼容预埋，ANTHROPIC-02 可见 trace 由 `retrieval_to_progress` 检索计数兑现。

</code_context>

<specifics>
## Specific Ideas

- Anthropic trace 用原生 `thinking` content block（`thinking_delta`）承载 progress，是 Anthropic 协议下与 OpenAI `reasoning_content` 对称的"trace 非正文"通道，客户端零适配。
- 复用 Phase 56 `progress.py` 纯函数作为 Anthropic/OpenAI 共享数据源，落实里程碑约束"对外只是不同 adapter、同一 §15 词表，不另建 taxonomy"。
- Anthropic SSE 用 `event:` + `data:` 双行帧（非 OpenAI `data:`-only + `[DONE]`），需新建 Anthropic 专用编码 helper，不误用 `sse_encode`。
</specifics>

<deferred>
## Deferred Ideas

- Anthropic `tool_use` / `tool_result` content block 全量对齐（客户端自带工具）——v2 OPENX-02 / OPENX-01。
- 多模态 content block（image/document）全量对齐——v2 OPENX-02（本 phase 文本 messages，image_url 透传依现状 request_handler 能力）。
- 暴露原始 thinking 链全量——INV-5 永久 Out of Scope。
- 动态 model 列表 / `count_tokens` / `/v1/messages/batches` 等周边端点——未列入里程碑。
</deferred>
