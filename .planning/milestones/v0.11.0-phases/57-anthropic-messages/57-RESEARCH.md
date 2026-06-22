# Phase 57 Research: Anthropic 兼容端点 `/v1/messages`

**Researched:** 2026-06-17
**Requirements:** ANTHROPIC-01, ANTHROPIC-02
**Goal answered:** "要把这个 phase 规划好，我需要知道什么？"
**Status:** Ready for planning

---

## TL;DR（规划前必读的一句话）

Phase 57 是 Phase 56 的"换 adapter"延伸：**内核（`_build_runner` + `prepare_messages_with_meta` + `LangChainAgentRunner.stream`）完全复用，零改动**，只新增三件纯增量产物——`MessagesView`（adrf APIView）、`AnthropicCompatAdapter`（AgentEvent → Anthropic SSE）、`AnthropicMessagesRequestSerializer` + Anthropic 专用 SSE 编码 helper。

**核心实证（已 READ 验证）：**
1. compat 挂载前缀就是 `v1/`（`server/friday/urls.py:83` `path("v1/", include("compat.urls"))`），新增 `path("messages", ...)` 即让 `/v1/messages` 自动生效，**不动既有 OpenAI 符号**。
2. **DEVIATION D-1 同 Phase 56 完全适用**：`_build_runner()` 构造 `LangChainRunnerConfig` 不传 tools（`config.tools==[]`）→ runner 不 `bind_tools` → `TOOL_USE_*` 在 57 链路也**永不发射**。所以 ANTHROPIC-02 的可见 trace **不能**靠 `tool_event_to_progress`（前向兼容预埋），必须由 `retrieval_to_progress(retr)`（真实 RAG 命中计数）经 thinking block 兑现——和 56 view 层兑现 prelude 的路径同源。
3. `MESSAGE_COMPLETE.data` 实证形状 = `{final_answer, status, usage:{input, output, ...}, model, session_id}`（`langchain_runner.py:531-540`），`usage` key 是 **`input`/`output`**（不是 Anthropic 的 `input_tokens`/`output_tokens`），adapter 翻译时需做 key 改名映射；`status` ∈ `{completed, interrupted, max_iterations, error}`。
4. Anthropic SSE 是 `event: <type>\n` + `data: <json>\n\n` **双行帧**，区别于 OpenAI 的 `data:`-only + `[DONE]`——**绝不能复用 `sse_encode`**（它只产 `data:` 行、无 `event:` 行、无 `[DONE]`），必须新建 Anthropic 专用编码 helper。

→ 规划落点：纯增量 `server/compat/anthropic_adapter.py`（adapter + SSE 编码 helper + 非流式聚合 helper）+ `MessagesView`（镜像 `ChatCompletionsView` 结构）+ serializer 复用 `_content_text`/`_content_blocks` 语义把 Anthropic 形状摊平成 `[{role, content}]`。四层测试沿用 56 范式。

---

## 1. 需求锚点（逐字对齐 ROADMAP / REQUIREMENTS）

- **ANTHROPIC-01**：新增 `/v1/messages`——请求/响应按 Anthropic Messages 形状映射（system / messages / max_tokens 等），复用既有 chat/agent 内核，**非流式响应可用**。
- **ANTHROPIC-02**：`/v1/messages` 流式（SSE）可用，trace/progress 经 **thinking block adapter** 透出（复用 TRACE-01 的同一事件 taxonomy 映射，INV-5 非原始 CoT）。
- **ROADMAP Phase 57 Success Criteria**：
  1. `POST /v1/messages` 按 Anthropic 形状映射请求与非流式响应，复用内核；
  2. 流式 SSE 可用（`message_start` / `content_block_delta` / `message_stop` 事件序列）；
  3. trace 经 thinking block adapter 透出，复用 Phase 56 同一 §15 映射（INV-5 非原始 CoT）；
  4. **既有 OpenAI compat 端点零回归**。
- **INV-5（永久约束）**：对外只透出 progress/trace 的高层语义，封装为 thinking block；**绝不**暴露模型私有原始 CoT、`tool_input`/`result`/`error`/`query` 原文。
- **TRACE-02 同源约束**：内部工具调用**绝不**以标准 `tool_use` content block 回传（规范 Anthropic 客户端见 `tool_use` 会挂起等待 `tool_result` 回传而卡死）。

---

## 2. 关键事实清单（READ 后实证，不是推断）

### F-1：`/v1/messages` 路由零摩擦——compat include 前缀确认为 `v1/`

`server/friday/urls.py:83`：

```83:83:server/friday/urls.py
    path("v1/", include("compat.urls")),
```

`server/compat/urls.py` 现有双注册范式（规避 `APPEND_SLASH` POST redirect）：

```5:12:server/compat/urls.py
urlpatterns = [
    # 双路由兼容策略：OpenAI SDK 默认不带末尾斜杠，project instructions 要求带斜杠
    # Django APPEND_SLASH=True 对 POST 会 redirect（变 GET 报错），必须直接双注册
    path("chat/completions", ChatCompletionsView.as_view()),
    path("chat/completions/", ChatCompletionsView.as_view()),
    path("models", ModelsView.as_view()),
    path("models/", ModelsView.as_view()),
]
```

→ 新增 `path("messages", MessagesView.as_view())` + `path("messages/", MessagesView.as_view())` 即让 `POST /v1/messages` 生效。**既有 4 行逐字不变**（零回归底线之一）。

### F-2：DEVIATION D-1 同 Phase 56——compat runner 不绑定 tools，`TOOL_USE_*` 永不发射

与 56-RESEARCH F-1 同源，逐字仍然成立：`_build_runner()`（`views.py:33-48`）只传 `resolved` + `model`，不传 tools；`LangChainRunnerConfig.tools` 默认 `[]`；runner 主循环 `model.bind_tools(...) if self._config.tools else model`——无工具就不 bind，`TOOL_USE_START/RESULT` 发射分支永不进入。

→ **Anthropic 链路同样产 0 个 `tool_event_to_progress` progress**。ANTHROPIC-02 要求的"可见 trace"**必须**由 `retrieval_to_progress(retr)`（流前同步 RAG 检索的命中计数元数据）经 thinking block 兑现。这是 57 规划必须显式记录的核心 deviation（见 §3 D-1）。

### F-3：内核三件套已就绪、可直接复用，无需改动

| 复用资产 | 位置 | 复用方式 |
|---------|------|---------|
| `_build_runner()` | `views.py:33-48` | `MessagesView` 直接 import 调用；返回 None → 503（同 OpenAI）|
| `prepare_messages_with_meta(messages, repository_ids, project_id) -> (lc_messages, retr)` | `request_handler.py:163-173` | Anthropic messages 规整成 `[{role, content}]` 后直接调，单次检索两路径复用 |
| `retrieval_to_progress(retr) -> list[str]` | `progress.py:69-101` | 命中→`["正在检索 RAG…","检索完成，命中 N 处"]`，未命中→`[]`；Anthropic 侧把这些文本喂进 thinking block delta |
| `tool_event_to_progress(evt) -> str\|None` | `progress.py:50-66` | 前向兼容预埋（F-2 当前不触发）；Anthropic adapter 在 `TOOL_USE_START` 分支调用，命中则产 thinking_delta |
| `LangChainAgentRunner.stream(prompt)` | `langchain_runner.py:426` | prompt = `list[BaseMessage]`；与 OpenAI 共用同一 runner，事件流一致 |

**关键：`progress.py` 的两个纯函数与 `make_reasoning_chunk` 解耦——前两者产"文本"（adapter 无关），第三者产 OpenAI chunk（Anthropic 不复用）。** Anthropic adapter 复用前两者产文本，自己用 Anthropic SSE helper 包成 thinking_delta。

### F-4：`MESSAGE_COMPLETE` / `TEXT_DELTA` / `THINKING` 的 data 形状（adapter 翻译源，已实证）

来自 `langchain_runner.py`：
- `TEXT_DELTA.data` = `{"text": str, "model", "session_id"}`（`_adapt_chunk` line 396-404）→ Anthropic `content_block_delta{type:text_delta, text}`
- `THINKING.data` = `{"thinking": str, "model", "session_id"}`（line 414-419）→ 模型私有 CoT，**INV-5 不外透**（见 P-3：THINKING 事件本身**不**映射为 thinking block，thinking block 只承载 progress 语义）
- `MESSAGE_COMPLETE.data` = `{"final_answer", "status", "usage": {...}, "model", "session_id"}`（line 531-540）
  - `status` ∈ `{"completed", "interrupted", "max_iterations", "error"}`（line 526/596/627/649）
  - `usage` 由 `_extract_usage` 产出，**key 是 `input`/`output`**（line 125-126），非 Anthropic 的 `input_tokens`/`output_tokens`——adapter 翻译时改名。
- `ERROR.data` = `{"message", ...}`（adapter.py:128 现读 `evt.data.get("message", ...)`）

⚠️ usage 语义差异（研究问题 4 答案）：Friday `usage.input`/`usage.output` 是**累计 token**；Anthropic `message_delta.usage.output_tokens` 也是累计（官方文档明示 cumulative）——语义对齐，只需 **key 改名 `input`→`input_tokens`、`output`→`output_tokens`**，不需重新累加。

### F-5：Anthropic Messages 流式 SSE 协议规范（WebSearch 官方文档实证，2026）

**事件序列**（每个事件都是 `event: <type>\n` + `data: <json>\n\n` 双行帧，`data` JSON 内 `type` 字段与 `event:` 名一致）：

```
event: message_start
data: {"type":"message_start","message":{"id":"msg_...","type":"message","role":"assistant","content":[],"model":"...","stop_reason":null,"stop_sequence":null,"usage":{"input_tokens":N,"output_tokens":1}}}

event: content_block_start
data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}

event: content_block_stop
data: {"type":"content_block_stop","index":0}

event: message_delta
data: {"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null},"usage":{"output_tokens":15}}

event: message_stop
data: {"type":"message_stop"}
```

**thinking content block（trace 载体）**：

```
event: content_block_start
data: {"type":"content_block_start","index":0,"content_block":{"type":"thinking","thinking":""}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"正在检索 RAG…"}}

event: content_block_stop
data: {"type":"content_block_stop","index":0}
```

**每个事件最小合法 payload（含 index）：**

| 事件 | 最小 `data` JSON |
|------|-----------------|
| `message_start` | `{"type":"message_start","message":{"id":"msg_xxx","type":"message","role":"assistant","content":[],"model":"friday-default","stop_reason":null,"stop_sequence":null,"usage":{"input_tokens":0,"output_tokens":0}}}` |
| `content_block_start`（text） | `{"type":"content_block_start","index":I,"content_block":{"type":"text","text":""}}` |
| `content_block_start`（thinking） | `{"type":"content_block_start","index":I,"content_block":{"type":"thinking","thinking":""}}` |
| `content_block_delta`（text） | `{"type":"content_block_delta","index":I,"delta":{"type":"text_delta","text":"..."}}` |
| `content_block_delta`（thinking） | `{"type":"content_block_delta","index":I,"delta":{"type":"thinking_delta","thinking":"..."}}` |
| `content_block_stop` | `{"type":"content_block_stop","index":I}` |
| `message_delta` | `{"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null},"usage":{"output_tokens":N}}` |
| `message_stop` | `{"type":"message_stop"}` |
| `ping`（可选） | `{"type":"ping"}` |
| `error` | `{"type":"error","error":{"type":"api_error","message":"..."}}` |

关键规范点（官方）：
- `message_start.usage.output_tokens` 通常为 1（占位），最终累计 `output_tokens` 在**最后一个 `message_delta`**。
- `content_block_delta.index` 必须对应该 block 在最终 `content[]` 的下标；多 block 时 index 递增。
- `ping` 可出现在流任意位置（keepalive），客户端容忍/可选；**实现可不发**。
- 真实 extended thinking 的 thinking block 会在 `content_block_stop` 前发 `signature_delta`（签名校验）——**我们合成的 progress thinking block 不是真实 CoT，不发 signature**（见 P-4）。
- 客户端应对未知事件类型优雅容错（官方明示"new event types may be added"）。

### F-6：非流式 Anthropic Messages 响应形状（WebSearch 官方实证）

```json
{
  "id": "msg_01XFDUDYJgAACzvnptvVoYEL",
  "type": "message",
  "role": "assistant",
  "content": [{"type": "text", "text": "..."}],
  "model": "friday-default",
  "stop_reason": "end_turn",
  "stop_sequence": null,
  "usage": {"input_tokens": 25, "output_tokens": 12}
}
```

必填/关键字段：`id`（`msg_` 前缀）、`type:"message"`、`role:"assistant"`、`content`（数组，文本走 `{type:"text", text}`）、`model`、`stop_reason`、`stop_sequence`（无停止序列为 `null`）、`usage.input_tokens` / `usage.output_tokens`。

### F-7：Anthropic Messages 请求形状（规整目标）

请求字段：`model`（必填，固定忽略复用 `friday-default`）、`max_tokens`（**必填**，int≥1）、`messages`（`[{role: user|assistant, content: string | content blocks}]`）、`system`（**顶层** system prompt，string 或 content blocks 数组，可选）、`stream`（默认 false）、`temperature`（可选，Anthropic 0–1）。

**规整成 `prepare_messages_with_meta` 期望的 `[{role, content}]`：**
1. `system` 顶层 → 列表首位插入 `{"role":"system", "content": <摊平文本>}`（system 为 content blocks 数组时取 text parts 拼接，复用 `_content_text` 语义）。
2. `messages[i]` 逐条透传 `{role, content}`——content 为 string 直接传；content 为 Anthropic content blocks（`[{type:"text",text},{type:"image",source}]`）时，规整成 OpenAI 风格 parts（`{type:"text",text}` / `{type:"image_url",image_url}`）以便 `_content_blocks` 消费，**或**本 phase 文本优先：仅取 text parts（image 透传依现状能力，多模态全量对齐 Out of Scope）。
   - `_content_text`（`request_handler.py:35-45`）：取 `type=="text"` 的 part text 拼接——RAG query / system 摊平复用它。
   - `_content_blocks`（`request_handler.py:48-80`）：把 OpenAI `text`/`image_url` parts 映射为 LangChain content blocks——若 Anthropic content 已规整为 OpenAI parts 形状即可直接复用。

→ **复用边界（研究问题 3 答案）**：Anthropic 专属代码只负责"形状规整"（system 提顶位、Anthropic block → OpenAI part 形状），规整后**完全委托** `prepare_messages_with_meta`，不重写 RAG 注入/检索内核。

---

## 3. 核心决策点（规划已自主拍板，无人值守）

### D-1（最关键，DEVIATION，同 Phase 56 F-1/D-1）：可见 trace 由 `retrieval_to_progress` 兑现，`tool_event_to_progress` 为前向兼容预埋

**决策（自主采纳，不留待用户）**：Anthropic adapter 同时接入两个数据源，与 56 Option C 对称：
- **机制层（前向兼容）**：adapter `TOOL_USE_START` 分支调 `tool_event_to_progress(evt)`，命中则产 thinking_delta。**当前 compat 链路 runner 无 tools，此分支不触发**（F-2）——纯预埋，未来 compat 绑定工具时自动生效。
- **效果层（兑现 ANTHROPIC-02）**：`MessagesView` 经 `prepare_messages_with_meta` 取 `retr`，`retrieval_to_progress(retr)` 派生 prelude 文本列表，**流式时**在正文 text block 之前以 thinking block（`content_block_start{type:thinking}` + 逐条 `thinking_delta` + `content_block_stop`）透出。命中 RAG → 可见"正在检索 RAG…/检索完成，命中 N 处"；未命中 → 空列表 → **不产 thinking block**，仅 text block（优雅降级，序列仍合法）。

**理由**：纯 adapter 映射在今天的 compat 链路产 0 progress（F-2），ANTHROPIC-02"可见 trace"落空。复用 56 已交付的 `retrieval_to_progress` + view 层 prelude 注入范式，是兑现可见效果的唯一现成路径，且与 OpenAI 端 prelude 同源（里程碑约束"同一 §15 词表，不另建 taxonomy"）。

**此 D-1 必须在 PLAN 显式记录**（CONTEXT 默认假设 `TOOL_USE_*` 会流入，与实证不符——已在 CONTEXT `<code_context>` line 91 预告，本 RESEARCH 确认）。

### D-2：content block index 管理策略 = 单线性计数器（trace block 0，text block 紧随）

**决策**：维护一个 `next_index` 计数器，从 0 起：
- 若 `prelude_texts` 非空（命中 RAG）→ thinking block 占 **index 0**（start/delta×N/stop），`next_index` 递增到 1；
- text 正文 block 占 **下一个 index**（无 trace 时即 index 0；有 trace 时 index 1）；start 一次、每个 `TEXT_DELTA` 一个 `text_delta`、收尾一个 stop。

**约束**：同一时刻只有一个 block "open"；开下一个 block 前必须先发当前 block 的 `content_block_stop`。text block 的 `content_block_start` **惰性发射**——在首个 `TEXT_DELTA` 到达时才发（避免空 text block；若 runner 一个 text delta 都没发，需在收尾前补发 start+stop 保证至少一个合法 text block，或允许零 text block）。**推荐**：text block 总是在 prelude 之后、runner 流之前发 `content_block_start`（即使后续无 delta），保证非空 content 数组形状稳定、与非流式 `content:[{type:text,text:""}]` 对称。

### D-3：`stop_reason` 映射表（MESSAGE_COMPLETE.status → Anthropic stop_reason）

| Friday `MESSAGE_COMPLETE.status` | Anthropic `stop_reason` | 备注 |
|----------------------------------|-------------------------|------|
| `completed` | `end_turn` | 正常结束 |
| `max_iterations` | `end_turn` | Anthropic 无对应；归 `end_turn`（语义最近，非 `max_tokens`——后者指输出 token 上限触顶）|
| `interrupted` | `end_turn` | Anthropic 无 interrupted；归 `end_turn` |
| `error` | （走 ERROR 事件路径） | 不进 message_delta，发 `error` SSE |

注：研究问题 4/CONTEXT 提到 `length → max_tokens`——但 Friday `MESSAGE_COMPLETE.status` **不产出 `length`/`max_tokens`** 字面量（实证仅上述 4 值）。若未来 runner 因 `max_tokens` 截断产出新 status，再扩表映射 `max_tokens`。当前**默认全部非 error → `end_turn`**，预留 `max_tokens` 映射位（前向兼容）。

### D-4：Anthropic SSE 编码 helper 独立新建，绝不复用 `sse_encode`

**决策**：新建 `anthropic_sse_encode(event_type: str, data: dict) -> bytes`，产 `b"event: <type>\n" + b"data: " + json + b"\n\n"`。`sse_encode`（`streaming.py:12`）只产 `data:` 行、无 `event:` 行、且有 `_omit` 剔除逻辑——Anthropic 不需要。两者并存，OpenAI 路径逐字不变。

### D-5：非流式聚合默认丢弃 trace，仅返回 text 正文

**决策**：非流式 `MessagesView.post(stream=False)` 复用 56 view 的"单次检索、非流式忽略 `retr`"范式——遍历 adapter 翻译出的事件（或直接消费 runner.stream 聚合 `final_answer`/`TEXT_DELTA`），**只聚合 text 正文进 `content:[{type:text,text}]`**，progress/thinking **不进** content（与 OpenAI 非流式忽略 prelude 对称，最小化语义复杂度）。`usage` 取 `MESSAGE_COMPLETE.usage` 改名。`stop_reason` 由 D-3 映射。

实现可二选一（plan 定）：
- (a) 聚合 `TEXT_DELTA.text` + 读 `MESSAGE_COMPLETE`（与 OpenAI 非流式镜像，复用 adapter）；
- (b) 直接读 runner 完成后的 `final_answer`（更简单，但绕过 adapter，测试覆盖面不同）。**推荐 (a)**，与流式共用 adapter 翻译核、测试同构。

### D-6：文件放置与命名（自主决策）

**新建 `server/compat/anthropic_adapter.py`**，内含：
- `anthropic_sse_encode(event_type, data) -> bytes`（D-4 SSE 编码 helper）；
- 一组 Anthropic 事件骨架构造纯函数（可独立单测）：`message_start_event(msg_id, model, input_tokens)` / `content_block_start(index, block_type)` / `content_block_delta_text(index, text)` / `content_block_delta_thinking(index, text)` / `content_block_stop(index)` / `message_delta_event(stop_reason, output_tokens)` / `message_stop_event()` / `anthropic_error_event(message)`；
- `class AnthropicCompatAdapter` with `async def translate_stream(runner, prompt, *, model, prelude_texts=None) -> AsyncGenerator[bytes]`（与 `OpenAICompatAdapter.translate_stream` 平行，AgentEvent if/elif 分派）；
- 可选 `aggregate_message(...)`（非流式聚合 helper）。

`progress.py` **不改**（`retrieval_to_progress` / `tool_event_to_progress` 直接复用，产文本）。`schemas.py` **新增** `AnthropicMessagesRequestSerializer`（不改既有 `ChatCompletionsRequestSerializer`）。`views.py` **新增** `MessagesView`（不改既有两个 view）。`urls.py` **新增** 两行 path（既有 4 行不动）。

**命名理由**：与既有 `adapter.py`（OpenAI）平行，`anthropic_adapter.py` 一眼可辨；SSE 编码 helper 与 adapter 同文件（都是 Anthropic 专属、互相紧耦合），避免新建过多模块。

---

## 4. 推荐改动落点（给 plan 的最小可执行清单）

1. **`server/compat/anthropic_adapter.py`（新建）**：
   - `anthropic_sse_encode` + 8 个事件骨架纯函数（D-6 列表）——纯函数，独立单测。
   - `AnthropicCompatAdapter.translate_stream`：
     - 先发 `message_start`（usage.input_tokens 暂填 0 或占位；最终值在 message_delta）；
     - `prelude_texts` 非空 → 发 thinking block（start index0 + 逐条 thinking_delta + stop）；
     - text block start（D-2）；
     - `async for evt in runner.stream`：`TEXT_DELTA`→`text_delta`（同 index）；`TOOL_USE_START`→`tool_event_to_progress` 命中则 thinking_delta（前向兼容，F-2 不触发）；`MESSAGE_COMPLETE`→记 usage+stop_reason，break；`ERROR`→发 `error` 事件 return；`THINKING`/其余→静默 continue（**THINKING 不外透**，P-3）；
     - 收尾：text block `content_block_stop` + `message_delta`（stop_reason + 累计 output_tokens）+ `message_stop`。
2. **`server/compat/schemas.py`（新增 serializer）**：`AnthropicMessagesRequestSerializer`——`model`(Char) / `max_tokens`(Int, required, min 1) / `messages`(many, role∈{user,assistant}, content string|blocks) / `system`(可选, string|blocks) / `stream`(default False) / `temperature`(可选 0–1) / 复用 `repository_ids` / `project_id`。content 校验镜像 `_MessageSerializer.validate_content`（text/image part）。
3. **`server/compat/views.py`（新增 `MessagesView`）**：镜像 `ChatCompletionsView` 结构——serializer 校验失败→Anthropic error（400）；Anthropic 形状规整 helper（system 提顶 + block→part）→ `prepare_messages_with_meta` → `_build_runner`（None→503）；`stream=True` → `StreamingHttpResponse(content_type="text/event-stream")` 经 `AnthropicCompatAdapter.translate_stream(prelude_texts=retrieval_to_progress(retr))`；`stream=False` → 聚合 Anthropic Messages 形状（D-5）。**复用 `_build_runner`、`OptionalBearerTokenAuth`、`authentication_classes=[]`**。
4. **`server/compat/urls.py`（新增 2 行）**：`path("messages", MessagesView.as_view())` + `path("messages/", ...)`。
5. **零回归保护**：OpenAI adapter/views/urls/serializer 既有符号逐字不变；`progress.py` 不改。

**Anthropic 形状规整 helper 放哪？** 建议放 `anthropic_adapter.py` 或 `request_handler.py` 内新增 `anthropic_to_openai_messages(system, messages) -> list[dict]`（纯函数，独立单测）。推荐 `request_handler.py`（与 `_content_text`/`_content_blocks` 同域，复用其语义）。

---

## 5. Pitfalls / 约束（execute 时易踩）

- **P-1 SSE 帧格式误用**：Anthropic 是 `event: <type>\n` + `data: <json>\n\n` 双行帧，**绝不能**调 `sse_encode`（只产 `data:` 行、无 `event:`、无 `[DONE]`）。新建 `anthropic_sse_encode`（D-4）。Anthropic 流**不发 `[DONE]`**，以 `message_stop` 收尾。
- **P-2 usage key 改名**：Friday `MESSAGE_COMPLETE.usage` 用 `input`/`output`（F-4），Anthropic 用 `input_tokens`/`output_tokens`。`message_start.usage.input_tokens` 取 `usage.input`（若 message_start 时尚无 usage 则填占位 0/1），`message_delta.usage.output_tokens` 取最终 `usage.output`。**别直接透传 dict**（会暴露 `input`/`output` 非法 key）。
- **P-3 INV-5：THINKING 事件不外透**：`THINKING.data.thinking` 是模型私有原始 CoT（F-4）——**绝不**映射为 thinking_delta。thinking content block **只承载 progress 语义文本**（`retrieval_to_progress`/`tool_event_to_progress` 的输出），不承载 `THINKING` 事件、不承载 `tool_input`/`result`/`error`/`query` 原文。安全测须注入 sentinel 断言不出现。
- **P-4 thinking block 无 signature**：真实 extended thinking 在 stop 前发 `signature_delta`（F-5）。我们合成的 progress thinking block **不是真实 CoT，不发 signature**。规范 Anthropic 客户端**显示**时不强制要求 signature；仅当客户端把 thinking block 回传做 tool round-trip 时才校验——本 phase 无 tool round-trip（Out of Scope），故安全。**不要**伪造 signature（会误导校验）。
- **P-5 绝不发 `tool_use` content block**（TRACE-02 硬约束）：规范客户端见 `tool_use` 会挂起等 `tool_result` 回传而卡死。内部工具进度只走 thinking block。`content_block` 的 `type` 只允许 `text` / `thinking`。
- **P-6 content block index 与 open/close 配对**：同一时刻只一个 block open；开新 block 前必发当前 block `content_block_stop`；index 严格递增且对应最终 content 下标（D-2）。漏发 stop 或 index 错乱会让客户端解析失败。
- **P-7 优雅降级序列合法性**：无 prelude（未命中 RAG）时不发 thinking block，序列为 `message_start → content_block_start(text,0) → text_delta×N → content_block_stop(0) → message_delta → message_stop`，仍合法。runner 零 text delta 时仍需保证至少发 text block 的 start+stop（D-2 推荐总发 start）。
- **P-8 非流式 content 零污染**：progress/thinking **绝不**进非流式 `content[].text`（D-5）；`content` 只含 text 正文。验证须有"非流式 content 不含 progress sentinel"断言。
- **P-9 async + adrf 约束**：`MessagesView` 必须 `adrf.views.APIView` + `authentication_classes=[]` + `permission_classes=[OptionalBearerTokenAuth]`（async 上下文禁 JWT lazy-load user，见 `ChatCompletionsView` Pitfall 6）。ORM 经 `sync_to_async`；SSE 编码/事件骨架设计为纯函数避免 IO。
- **P-10 错误不泄漏 traceback**：流式 `ERROR` → `event: error` + `{type:"error",error:{type:"api_error",message:...}}`（不含 stack trace，对齐 `error_handlers.py` ASVS V8.3）；非流式校验失败 → Anthropic error envelope（400）。**别复用 `openai_error_response`**（它产 OpenAI `{error:{message,type,code}}` 形状，与 Anthropic `{type:"error",error:{type,message}}` 不同）——新增 Anthropic error helper 或内联。
- **P-11 ruff/约定**：line length 100，注释/docstring 中文（项目约定）；新增 import 排序（ruff I001，56 踩过）。
- **P-12 零回归 byte-eq 边界**：57 是纯增量，但仍须跑既有 `tests/compat/`（OpenAI 5 adapter + view + progress + auth）全绿，确认无符号漂移。

---

## 6. Validation Architecture（供 VALIDATION.md 生成 / nyquist 校验）

四层可验证测试架构，全部落 `server/tests/compat/`（新增 `test_anthropic_adapter.py` + `test_messages.py` + `test_anthropic_schemas.py`，扩充范式沿用 56）：

### 6.1 纯函数单测（Anthropic SSE helper + 形状规整 + serializer）
- `anthropic_sse_encode` → 断言产 `event: <type>\n` + `data: <json>\n\n`（双行帧、`data` JSON 内 `type` 与 event 名一致）。
- 8 个事件骨架函数 → 断言最小合法 payload 形状（含 `index` 字段、`message_start.message` 骨架、`message_delta.usage.output_tokens`、`content_block_delta` 的 `text_delta`/`thinking_delta` 区分）。
- `anthropic_to_openai_messages(system, messages)` → system 提顶为 role=system 首位、Anthropic block → OpenAI part 形状、content blocks 取 text 拼接（对齐 `_content_text`）。
- `AnthropicMessagesRequestSerializer` → `max_tokens` 缺失 400 / `max_tokens<1` 400 / `system` 可选 / content string 与 parts 均合法 / role 非 user|assistant 400。
- 无需 DB / async runner，纯函数直调。
- **mock 点**：无（纯函数）。

### 6.2 adapter 流式集成测（注入 AgentEvent 序列）
- 复用 56 `_make_runner(*events)` + `_collect`/`_collect_raw` 范式。
- 注入 `prelude_texts=["正在检索 RAG…","检索完成，命中 1 处"]` + `TEXT_DELTA("你好")` + `TEXT_DELTA("世界")` + `MESSAGE_COMPLETE(status=completed, usage={input:5,output:2})` → 断言：
  - SSE 事件**顺序**：`message_start → content_block_start(thinking,0) → thinking_delta×2 → content_block_stop(0) → content_block_start(text,1) → text_delta×2 → content_block_stop(1) → message_delta(end_turn) → message_stop`。
  - trace 经 `thinking_delta`、正文经 `text_delta`、index 正确递增。
  - **不含** `tool_use` content block；任一 `content_block.type` ∈ `{text,thinking}`。
  - `message_delta.delta.stop_reason == "end_turn"`、`message_delta.usage.output_tokens == 2`。
- 无 prelude（`prelude_texts=[]`）注入 `TEXT_DELTA`+`MESSAGE_COMPLETE` → 断言无 thinking block，text block 占 index 0，序列合法。
- `MESSAGE_COMPLETE(status=interrupted)` / `max_iterations` → `stop_reason == "end_turn"`（D-3）。
- `ERROR` 事件 → 发 `event: error` + `{type:error,error:{type:api_error}}` 后流结束、无 message_stop。
- **mock 点**：`_make_runner` 注入 AgentEvent 序列；`prelude_texts` 直接传参（无需 mock 检索）。

### 6.3 view 级集成测（流式 + 非流式）
- `MessagesView.post(stream=True)`：mock `_build_runner`（返回注入 runner）+ mock `prepare_messages_with_meta` 返回 `([HumanMessage], <带命中 final_context+layers 的 fake retr>)` → 断言 `content_type=text/event-stream`、thinking progress（`thinking_delta`）**先于** text 正文、含 message_stop。
- `MessagesView.post(stream=False)`：同上 mock → 断言响应为 Anthropic Messages 形状（`{id:msg_*, type:message, role:assistant, content:[{type:text,text}], model, stop_reason, stop_sequence, usage:{input_tokens,output_tokens}}`）且 `content[].text` **零污染**（不含 progress/thinking 文本）。
- `max_tokens` 缺失 → 400 Anthropic error envelope。
- `_build_runner` 返回 None → 503。
- **mock 点**：`patch("compat.views._build_runner", AsyncMock, return_value=mock_runner)` + `patch("compat.views.prepare_messages_with_meta", AsyncMock, return_value=(lc, retr))`；fake `retr` 用 `SimpleNamespace(final_context="...", layers=[SimpleNamespace(result_count=1)], repository_ids=[])`。

### 6.4 安全 sentinel + 零回归
- **安全（INV-5）**：注入 `THINKING.data.thinking` 含 CoT sentinel、`TOOL_USE_START.data` 含 `tool_input`/`result` sentinel、fake retr 的 `final_context` 含敏感 sentinel → 断言全量 SSE 字节流（流式）与 `content[].text`（非流式）**不出现**任一 sentinel（只透出工具名/命中计数语义）。复用 56 sentinel 范式。
- **零回归**：既有 `tests/compat/`（OpenAI adapter/view/progress/auth）全绿，确认 OpenAI 路径逐字不变（`pytest tests/compat/ -q`）。

### Nyquist 采样覆盖矩阵（每个需求/约束至少一个可验证断言）
| 需求/约束 | 验证层 | 断言要点 |
|-----------|--------|----------|
| ANTHROPIC-01（非流式响应形状） | 6.3 | 响应为 Anthropic Messages 形状、content 正文聚合正确 |
| ANTHROPIC-01（请求映射 / max_tokens 必填） | 6.1 | serializer 校验 + 形状规整 system 提顶 |
| ANTHROPIC-02（流式 SSE 序列） | 6.2（+6.3） | message_start→content_block_*→message_delta→message_stop 顺序正确 |
| ANTHROPIC-02（trace 经 thinking block） | 6.2 | 含 thinking_delta，文本为命中计数语义 |
| ANTHROPIC-02（可见效果 D-1） | 6.3 | view 级命中 RAG → thinking progress 先于正文 |
| TRACE-02（不发 tool_use block） | 6.2 | 全流无 tool_use content block、type∈{text,thinking} |
| INV-5（非 CoT、不泄漏） | 6.4 | sentinel 全不出现（THINKING/tool_input/final_context） |
| 优雅降级（无 prelude） | 6.2 | 无 thinking block、text block index 0、序列合法 |
| stop_reason 映射 | 6.2 | completed/interrupted/max_iterations → end_turn |
| 零回归（OpenAI 端点） | 6.4 | 既有 tests/compat 全绿、OpenAI 符号逐字不变 |

---

## 7. Open Questions（plan 阶段已自主决断，无遗留）

- **OQ-1 文件放置/命名** → D-6：新建 `server/compat/anthropic_adapter.py`（adapter + SSE 编码 helper + 事件骨架纯函数）；serializer 入 `schemas.py`；形状规整 helper 入 `request_handler.py`。**已决。**
- **OQ-2 content block index 策略** → D-2：单线性计数器，thinking block（有 prelude 时）占 0，text block 紧随。**已决。**
- **OQ-3 stop_reason 映射** → D-3：非 error 全归 `end_turn`，预留 `max_tokens` 位。**已决。**
- **OQ-4 ping 是否发** → 不发（客户端容忍可选，最小化实现；keepalive 非本 phase 必需）。**已决。**
- **OQ-5 非流式是否保留 thinking block** → D-5：默认丢弃 trace，仅返回 text 正文（与 OpenAI 非流式对称）。**已决。**
- **OQ-6 非流式聚合复用 adapter 还是读 final_answer** → D-5(a)：复用 adapter 翻译核聚合 TEXT_DELTA（与流式同构、测试复用）。**已决（plan 可微调）。**
- **OQ-7 Anthropic error envelope** → P-10：新增 Anthropic error helper（`{type:error,error:{type,message}}`），不复用 `openai_error_response`。**已决。**

---

## RESEARCH COMPLETE

**核心发现**：Phase 57 是 Phase 56 的纯增量"换 adapter"延伸——内核（`_build_runner` + `prepare_messages_with_meta` + `runner.stream`）零改动复用，只新增 `MessagesView` / `AnthropicCompatAdapter` / `AnthropicMessagesRequestSerializer` / Anthropic 专用 SSE 编码 helper。compat 挂载前缀实证为 `v1/`，`/v1/messages` 加 path 即生效，OpenAI 符号逐字不变（零回归）。**DEVIATION D-1 同 56 完全适用**：compat runner 不绑定 tools → `TOOL_USE_*` 永不发射 → ANTHROPIC-02 可见 trace 必须由 `retrieval_to_progress`（真实 RAG 命中计数）经 thinking block 兑现，`tool_event_to_progress` 为前向兼容预埋。已实证 Anthropic SSE 双行帧协议（`message_start`/`content_block_*`/`message_delta`/`message_stop`，thinking_delta 承载 trace）、非流式 Messages 响应形状、`MESSAGE_COMPLETE.usage` 的 `input`/`output` → Anthropic `input_tokens`/`output_tokens` 改名、status→stop_reason 映射表。给出文件放置（`anthropic_adapter.py`）、content block index 单线性计数策略、12 条 pitfalls（SSE 帧/usage 改名/INV-5 THINKING 不外透/无 signature/不发 tool_use/index 配对/非流式零污染/async adrf/错误不泄漏 traceback）、四层 Validation Architecture（Anthropic SSE 纯函数 / adapter 集成 / view 流式+非流式 / 安全 sentinel+零回归）与 Nyquist 覆盖矩阵。所有 Open Question 已自主决断（无人值守），无遗留待裁决项。
