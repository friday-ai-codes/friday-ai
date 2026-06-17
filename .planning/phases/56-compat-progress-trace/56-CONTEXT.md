# Phase 56: compat 内部工具调用 → progress/trace 事件透出 - Context

**Gathered:** 2026-06-17
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — 推荐答案自动采纳)

<domain>
## Phase Boundary

本 phase 让 OpenAI 兼容调用方（`/v1/chat/completions` 流式）能看到 Friday 内部工具调用（RAG 检索 / grep / 仓库分析等）的进度，机制是把 `AgentEvent` 流中的工具/进度事件经 §15 事件 taxonomy 语义映射为 progress / `reasoning_summary` 文本透出。

**交付物边界：**
- 在 `server/compat/adapter.py` 的 `OpenAICompatAdapter.translate_stream` 中，把当前被 `else: continue` 丢弃的内部工具事件（`TOOL_USE_START` / `TOOL_USE_RESULT`，以及可能的进度类事件）映射为对外 progress 文本 chunk。
- progress 文本以人类可读语义呈现（"正在检索 RAG / grep / 分析仓库"），语义来源对齐 §15 taxonomy（`server/delivery/services/event_taxonomy.py` 常量集）。
- 绝不以标准 `tool_calls` 字段回传；绝不暴露模型私有 CoT 原文。
- 无事件可透出时优雅降级，既有流式/非流式 `/v1/chat/completions` 行为零回归。

**不在本 phase（Out of Scope）：**
- Anthropic `/v1/messages` 端点（Phase 57）。
- 标准双向 `tool_calls`（客户端自带工具回传，v2 OPENX-01）。
- 暴露原始 thinking 链（INV-5）。
</domain>

<decisions>
## Implementation Decisions

### 透出字段与协议映射
- 内部工具 progress 映射到 `delta.reasoning_content`（复用既有 THINKING→`reasoning_content` 的 DeepSeek/o1 事实标准通道），不新建非标准字段、不污染 `delta.content`（正文）。
- 绝不写 `delta.tool_calls` / `finish_reason="tool_calls"`——TRACE-02 硬约束：规范客户端见 tool_calls 会误判挂起等待回传而卡死。
- progress chunk 与正文 chunk 同流交替 yield，保持 OpenAI chunk 结构合法（`object="chat.completion.chunk"`，`finish_reason=None`）。
- `include_usage` 语义对既有 chunk 不变；progress chunk 在 `include_usage=True` 时同样带 `usage=None`（与现有 TEXT_DELTA/THINKING chunk 一致）。

### 事件 → progress 文本映射内容
- 覆盖 `TOOL_USE_START`（工具开始）为主，输出"正在 {工具语义}…"进度文本；`TOOL_USE_RESULT` 默认仅在能给出简短完成语义时透出（如"检索完成，命中 N 处"），无有效摘要则不 emit（避免噪音）。
- 工具名 → 中文语义经一个集中映射表（如 `search_rag`/`grep`/`get_file`/仓库分析 → "正在检索 RAG" / "正在 grep 搜索" / "正在读取文件" / "正在分析仓库"），未知工具回退为通用"正在调用工具：{name}"或静默跳过（取保守静默，避免泄漏内部工具名细节）。
- 语义命名对齐 §15 taxonomy（`knowledge.recalling` / `repo.routing` / `repo.research.*` 等常量）的人类可读释义，作为对外 adapter 的"不同 adapter、同一词表"落地（复用不另建 taxonomy）。
- progress 文本仅含"在做什么"的高层语义，绝不内联工具入参/出参原文、绝不内联模型 CoT（INV-5 + 防敏感泄漏）。

### 降级与零回归
- 缺事件 / runner 不发工具事件时，adapter 行为与现状逐字等价（只走 TEXT_DELTA / THINKING / MESSAGE_COMPLETE / ERROR 路径），不产生空 progress chunk。
- 非流式 `/v1/chat/completions`（views.py 聚合路径）：progress 文本不进 `message.content`；若聚合 `reasoning_content`，progress 与 THINKING 同归 `reasoning_content`（或显式丢弃 progress 只保留正文），保持非流式响应稳定——取"progress 不进非流式聚合正文，reasoning_content 维持既有 THINKING 聚合"以最小化非流式语义变化。
- 映射逻辑做成可独立单测的纯函数 helper（事件 → progress 文本 / None），adapter 主循环只负责 yield，便于守护测试与零回归断言。

### 测试边界
- 单测：纯函数映射表（各内部工具 → 预期 progress 文本；未知工具 → 静默/通用；非工具事件不误命中）。
- adapter 流式集成测：注入含 TOOL_USE_START 的 AgentEvent 序列 → 断言 SSE 输出含 `reasoning_content` progress chunk 且**不含** `tool_calls` 字段、`finish_reason` 不为 `tool_calls`、`content` 正文不被污染。
- 零回归测：无工具事件的既有序列 → SSE 输出与现状逐字等价（复用/扩充 `server/tests/compat/test_adapter.py`）。
- 安全测：progress 文本不泄漏工具入参/出参原文 / 模型 CoT（断言不出现注入的敏感 sentinel）。

### the agent's Discretion
- progress 文本的具体中文措辞、工具名→语义映射表的精确条目、helper 的命名与放置（adapter.py 内或新 module），由 plan/execute 阶段按代码现状定夺。
- 是否对 `TOOL_USE_RESULT` 透出完成态文本由实际事件 payload 是否含可用摘要决定（无摘要则静默）。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/compat/adapter.py` `OpenAICompatAdapter.translate_stream`：唯一 AgentEvent→OpenAI SSE 翻译点；THINKING→`delta.reasoning_content` 已是既有 progress/trace 透出范式可直接复用；`else: continue`（line 124-127）即内部工具事件当前丢弃点，本 phase 主改点。
- `server/compat/streaming.py` `sse_encode` / `_omit`：SSE chunk 序列化工具，progress chunk 复用。
- `server/agents/core/events.py`：`TOOL_USE_START` / `TOOL_USE_RESULT` / `THINKING` / `TEXT_DELTA` / `MESSAGE_COMPLETE` / `ERROR` 常量；`AgentEvent(type, data)` 形状。
- `server/delivery/services/event_taxonomy.py`：§15 taxonomy 稳定常量（`EVENT_KNOWLEDGE_RECALLING="knowledge.recalling"` 等）+ `build_envelope`，docstring 已写明"v0.11 对外 adapter 复用同一 shape（INV-5）"——本 phase 即兑现该预留。

### Established Patterns
- 静态方法类 adapter + async generator yield `sse_encode(...)` bytes；事件类型 if/elif 分派；`include_usage` 分支统一处理。
- 守护测试在 `server/tests/compat/test_adapter.py`；纯函数 + 集成双层。
- INV-5 在 PROJECT/REQUIREMENTS/event_taxonomy docstring 多处强调：对外只 progress/trace，非 CoT，不误用 tool_calls。

### Integration Points
- `server/compat/views.py` `ChatCompletionsView`：流式 `_stream_chunks` 与非流式聚合两路径均经 `translate_stream`，progress 透出对两路径的影响需各自核对零回归。
- `LangChainAgentRunner.stream()`（`server/agents/langchain_runner.py`）：AgentEvent 来源；需确认内部工具（RAG/grep）实际发射的事件类型与 payload 字段（plan-phase research 必查）。
</code_context>

<specifics>
## Specific Ideas

- 复用 THINKING 的 `reasoning_content` 通道作为 progress 透出载体，不新建字段——与既有 compat 实现一致、客户端零适配成本。
- 映射表对齐 §15 taxonomy 人类可读释义，落实"对外只是不同 adapter，不另建词表"的里程碑约束。
</specifics>

<deferred>
## Deferred Ideas

- 标准双向 `tool_calls`（客户端自带工具回传执行）——v2 OPENX-01。
- 暴露原始 CoT / thinking 链全量——INV-5 永久 Out of Scope。
- Anthropic `/v1/messages` 的 thinking block 透出——Phase 57（复用本 phase 同一映射）。
</deferred>
