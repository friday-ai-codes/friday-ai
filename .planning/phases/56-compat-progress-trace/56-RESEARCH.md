# Phase 56 Research: compat 内部工具调用 → progress/trace 事件透出

**Researched:** 2026-06-17
**Requirements:** TRACE-01, TRACE-02
**Goal answered:** "要把这个 phase 规划好，我需要知道什么？"
**Status:** Ready for planning

---

## TL;DR（规划前必读的一句话）

CONTEXT.md 锁定的设计是"在 `translate_stream` 把 `TOOL_USE_START` / `TOOL_USE_RESULT` 映射成 `reasoning_content` progress"。
**但经代码核实：当前 compat 路径下 runner 永远不发这两个事件**——因为 `_build_runner()` 构造 `LangChainRunnerConfig` 时**没有传 tools**（`config.tools == []`），而真正的 RAG/grep/仓库分析检索发生在 `prepare_messages()` 里、**在 runner 流开始之前同步执行、且完全不发任何事件**。

→ 所以"只做 adapter 映射"在今天的 compat 链路里会**产出 0 个 progress chunk**（永远走优雅降级分支），TRACE-01 要求的"正在检索 RAG"用户可见效果**不会出现**。这是本 phase 规划必须先决断的**核心架构事实**（见 §3 决策点 D-1）。

---

## 1. 需求锚点（逐字对齐 REQUIREMENTS.md / STATE.md）

- **TRACE-01**：把内部工具调用（RAG 检索 / grep / 仓库分析等）经 §15 事件 taxonomy 映射为 OpenAI 兼容流式响应中的 progress / `reasoning_summary` 文本，外部调用方能看到"正在检索 RAG / grep / 分析仓库"等进度。
- **TRACE-02**：内部工具调用**绝不**以标准 `tool_calls` 形式回传（防规范客户端误判挂起卡死），也**不暴露**模型私有 CoT（INV-5）；以 adapter 实现，缺事件优雅降级、不破坏既有 `/v1/chat/completions` 行为。
- **INV-5**（STATE §关键约束 + DOMAIN §10/§15）：对外只透出 progress/trace，封装为 `reasoning_summary` / thinking block；**绝不**用标准 `tool_calls` 回传。
- **§15 taxonomy 复用**（DOMAIN §15）：对外 OpenAI adapter → `reasoning_summary` 文本流，Anthropic adapter → thinking block，**皆由同一事件流映射，不另建词表**。

---

## 2. 关键事实清单（READ 后实证，不是推断）

### F-1：compat 的 runner 没有绑定任何工具 → runner 流里不会有 TOOL_USE_* 事件

`server/compat/views.py` `_build_runner()`（line 32-47）只构造：

```33:47:server/compat/views.py
    runner_config = LangChainRunnerConfig(
        resolved=resolved,
        model=model,
    )
    return LangChainAgentRunner(runner_config)
```

`LangChainRunnerConfig.tools` 默认 `field(default_factory=list)`（`server/agents/langchain_runner.py:163`），即 `[]`。

而 runner 主循环 `model_with_tools = model.bind_tools(self._config.tools) if self._config.tools else model`（`langchain_runner.py:455-457`）——**无工具就不 bind**，因此 LLM 不会产生 `aimsg.tool_calls`，`TOOL_USE_START` / `TOOL_USE_RESULT` 的发射分支（line 547-621）**永不进入**。

**对照**：tools 仅在 workflow AI 节点（`workflows/nodes/ai/base_agent.py:693 tools=tools`）和 chat 路径绑定；compat 路径全程零工具。

### F-2：compat 的 RAG/grep 检索发生在 stream 之前、是同步一次性调用、不发事件

`prepare_messages()`（`server/compat/request_handler.py:83-140`）在 view 调 runner **之前**执行：
- 取最后一条 user message 作为 query；
- 调 `LayeredSearchService.search(...)`（thin wrapper → `HybridSearchService(get_provider()).search(...)`）；
- 命中则把 `result.final_context` 包成一条 `SystemMessage` **前置**注入 `lc_messages`；
- 失败则 `logger.warning` 降级返回原始 messages（不抛错）。

`HybridSearchService.search`（`server/services/retrieval/hybrid_search.py:256-318`）是**纯 async 函数、返回一个结果对象、不 yield、不发 AgentEvent / 不发 §15 事件**。它内部有 wave 0/1/2/3（RAG 召回、符号查找、一跳/二跳/跨仓扩散），但这些只写 `structlog` 日志（`hybrid_search_wave_started/done`），**对外无事件流**。

→ 结论：在 compat 链路里，"RAG/grep/仓库分析"既不是 runner 工具调用，也没有任何可被 `translate_stream` 消费的事件。它只是一个发生在流之前的同步函数调用。

### F-3：§15 taxonomy 事件与 AgentEvent 是两套不同的事件系统

| 维度 | §15 taxonomy 事件 | AgentEvent |
|------|-------------------|------------|
| 常量源 | `server/delivery/services/event_taxonomy.py`（`EVENT_KNOWLEDGE_RECALLING="knowledge.recalling"` 等） | `server/agents/core/events.py`（`TOOL_USE_START` 等） |
| 产出者 | 编排引擎 / PlanSession（orchestration 层），经 `build_envelope` 持久化为 `PlanSessionEvent` | `LangChainAgentRunner.stream()` |
| 是否进 `translate_stream` | **否**（compat 流根本看不到这套事件） | **是**（`translate_stream` 唯一消费的就是它） |

→ DOMAIN §15 写的"对外 adapter 复用同一 taxonomy"是**语义/词表层面的复用**（progress 文本的人类可读释义对齐 `knowledge.recalling` 等语义），**不是说 §15 事件对象会流进 compat adapter**。规划时不要误以为能直接 `import` §15 事件常量来驱动 compat progress——它们没有发射到 AgentEvent 流。

### F-4：`else: continue` 当前丢弃的事件类型

`adapter.py:124-127` 的 `else` 分支当前覆盖：`TOOL_USE_START` / `TOOL_USE_RESULT` / `BUDGET_WARNING`，以及 `events.py` 中其余所有非 `TEXT_DELTA/THINKING/MESSAGE_COMPLETE/ERROR` 的类型。在 compat 路径里，**实际只可能命中 `BUDGET_WARNING`**（context 超预算 auto_trim 时；但 compat 默认 `context_strategy="strict_error"`，也基本不触发）。`TOOL_USE_*` 因 F-1 永不到达。

### F-5：AgentEvent payload 形状（若未来 compat 绑定工具，映射可直接用）

来自 `langchain_runner.py` 实证：
- `TOOL_USE_START.data` = `{tool_call_id, tool_name, tool_input, model, session_id}`（line 555-566）
- `TOOL_USE_RESULT.data`（成功）= `{tool_call_id, tool_name, success:True, result, model, session_id}`（line 601-613）
- `TOOL_USE_RESULT.data`（失败）= `{tool_call_id, tool_name, success:False, error, model, session_id}`（line 578-590）
- `THINKING.data` = `{thinking, model, session_id}`；`TEXT_DELTA.data` = `{text, model, session_id}`

⚠️ **安全要点（INV-5）**：`tool_input`（入参原文）、`result`（出参原文）、`error`（异常文本）**绝不能**直接进 progress 文本——它们可能含敏感代码片段 / 注入内容。映射只能取 `tool_name` 翻成高层语义。

### F-6：检索结果可用于"完成态"语义的字段

`RagSearchResult` / `HybridSearchResult`（`server/services/retrieval/types.py`）暴露：`final_context:str`、`total_tokens:int`、`repository_ids:list`、`layers:list[LayerSnapshot]`（`LayerSnapshot.result_count`、`.items`）、`hop1_neighbors`/`hop2_neighbors`/`cross_repo_neighbors`。
→ 若要透出"检索完成，命中 N 处"，可由 `len(layers[0].items)` 或 `total_tokens>0` / `repository_ids` 派生**计数类、非内容类**摘要（不泄漏代码原文，满足 INV-5）。

---

## 3. 核心决策点（规划必须先拍板）

### D-1（最关键）：纯 adapter 映射不够——要不要让"真实 RAG 检索"产出 progress？

CONTEXT.md 锁定"映射 TOOL_USE_* → reasoning_content + 缺事件优雅降级"。但由 F-1/F-2，今天的 compat 链路里 TOOL_USE_* 永不发生 → 纯 adapter 方案在 compat 下永远只走降级分支、**0 progress**，TRACE-01 的可见效果落空。三条可选路线：

- **Option A — 纯 adapter 映射（字面 CONTEXT scope）**
  在 `translate_stream` 把 `TOOL_USE_START`（必要时 `TOOL_USE_RESULT`）映射为 `reasoning_content` progress chunk。
  - ✅ 改动最小、隔离性好、对未来"compat 绑定工具"前向兼容、零回归、天然优雅降级。
  - ❌ **当前 compat 路径产 0 progress**（无工具事件）；TRACE-01"正在检索 RAG"用户可见目标**未达成**。仅满足"机制就位"，不满足"效果可见"。

- **Option B — 把真实 RAG 检索透出为 progress（推荐叠加在 A 之上）**
  在 compat 流里围绕 `prepare_messages` 的 `HybridSearchService.search` 合成 progress：流首先 yield 一条"正在检索 RAG…"`reasoning_content` chunk，检索完成后 yield"检索完成，命中 N 处"（数据来自 F-6 的计数字段），再进 runner 正文流。
  - 需要小幅重排请求时序：当前 retrieval 在 `prepare_messages`（runner 构建前）。两种落法：
    - (b1) 在 `views._stream_chunks` / 或新的 progress-aware 包装里，把"检索阶段"也纳入流，先发检索 progress 再调 `translate_stream`；
    - (b2) 让 `prepare_messages` 返回检索结果的**非敏感元数据**（命中数 / repo 数），view 据此在首个正文 chunk 前合成 progress chunk。
  - ✅ 真正交付 TRACE-01 可见效果；progress 文本仍走 `reasoning_content`（符合锁定字段决策）。
  - ❌ 触及请求时序与 view 流；零回归需谨慎（非流式聚合路径 message.content 绝不能被污染——见 D-3）。

- **Option C — A + B 都做（机制 + 效果）**
  adapter 侧加 TOOL_USE_* 映射（前向兼容 + Phase 57 复用），view/stream 侧加真实 RAG 检索 progress。
  - ✅ 同时满足 TRACE-01 可见效果与"adapter over 事件 taxonomy"机制；为 Phase 57（Anthropic thinking block 复用同一映射）打好抽象。
  - ❌ 改动面最大。

**Researcher 建议**：取 **Option C**，但把"映射纯函数 helper"（事件/检索元数据 → progress 文本 | None）做成与 adapter/ view 解耦的可独测单元（CONTEXT 已要求）。若 plan 阶段要收敛 scope，**至少必须含 Option B**，否则 TRACE-01 验收（"看得到正在检索 RAG"）无法通过；单纯 Option A 只能算"机制预埋"。
此结论应作为 plan 的显式 deviation 记录（CONTEXT 默认假设 TOOL_USE_* 会流入，与实证不符）。

### D-2：progress 透出字段 = `delta.reasoning_content`（已锁，无争议）

复用既有 `THINKING → delta.reasoning_content`（`adapter.py:78-90`）范式。chunk 结构保持 `object="chat.completion.chunk"`、`finish_reason=None`、`include_usage=True` 时带 `usage=None`（与 TEXT_DELTA/THINKING chunk 一致）。**绝不**写 `delta.tool_calls` / `finish_reason="tool_calls"`（TRACE-02 硬约束；注意 `finish_reason` 字面量类型已含 `"tool_calls"`，代码里**不得**把它赋给收尾 chunk）。

### D-3：非流式路径零回归（views.py 聚合）

`ChatCompletionsView.post` 非流式分支（line 99-135）复用 `translate_stream` 聚合：`delta.content` → `message.content`，`delta.reasoning_content` → `message.reasoning_content`。
→ progress 既然走 `reasoning_content`，**会被聚合进非流式的 `message.reasoning_content`**。CONTEXT 决策取"progress 不进非流式正文（content），reasoning_content 维持既有 THINKING 聚合"。
**规划须明确**：非流式下 progress 进 `reasoning_content` 是否可接受？CONTEXT line 41 倾向接受（与 THINKING 同归 reasoning_content）；只要 `message.content`（正文）逐字不变即满足零回归底线。验证须有"非流式 content 不被 progress 污染"的断言。

### D-4：工具名 → 中文语义映射表

集中映射表（纯数据），对齐 §15 语义释义：
- `search_rag` / RAG 检索 → "正在检索 RAG"（语义对应 `knowledge.recalling`）
- `grep` / 文本搜索 → "正在 grep 搜索"
- `get_file` / 读文件 → "正在读取文件"
- 仓库分析 / 路由 → "正在分析仓库"（对应 `repo.routing` / `repo.research.*`）
- **未知工具 → 保守静默跳过**（CONTEXT line 35：避免泄漏内部工具名细节；不回退打印 `{name}`）。

映射表条目精确措辞、放置位置（adapter.py 内 or 新 module）由 plan/execute 定（CONTEXT line 50-51 已授权）。建议放新纯函数模块（如 `server/compat/progress.py`）便于独测与 Phase 57 复用。

---

## 4. 推荐改动落点（给 plan 的最小可执行清单）

1. **新建纯函数 helper**（建议 `server/compat/progress.py`）：
   - `tool_event_to_progress(evt: AgentEvent) -> str | None`：仅消费 `tool_name`，查映射表；未知/无映射 → `None`（不 emit）。安全：绝不读 `tool_input`/`result`/`error`。
   - （Option B/C）`retrieval_to_progress(...) -> list[str]`：由检索阶段元数据（命中数等非敏感字段）产出"正在检索 RAG"/"检索完成，命中 N 处"文本。
   - 一个 `make_reasoning_chunk(common, text, include_usage)` 小工具复用 `sse_encode`，产出合法 reasoning_content chunk。

2. **`adapter.py translate_stream`**：把 `else: continue`（line 124-127）改为：对 `TOOL_USE_START`（含 `TOOL_USE_RESULT` 若有完成摘要）调 helper，`None` 则继续 `continue`（保持降级逐字等价），非 `None` 则 yield reasoning_content chunk。其余未知类型仍 `continue`。

3. **（Option B/C）compat 检索 progress 透出**：在 `views._stream_chunks` 或 `translate_stream` 前置阶段合成 RAG 检索 progress（时序见 D-1）。注意保持 `prepare_messages` 失败降级语义不变。

4. **零回归保护**：无工具事件、无检索命中的既有序列，SSE 输出与现状**逐字等价**（不产空 progress chunk）。

---

## 5. Pitfalls / 约束（execute 时易踩）

- **P-1 误判事件来源**：不要试图在 compat adapter `import` §15 `event_taxonomy` 常量来"驱动"progress——那套事件不在 AgentEvent 流里（F-3）。§15 只用于**语义对齐**（progress 文本释义），不是数据源。
- **P-2 INV-5 泄漏面**：progress 文本只能含"在做什么"高层语义。**禁止**内联 `tool_input` / `result` / `error` / THINKING 原文 / query 原文。安全测试须注入 sentinel 断言不出现。
- **P-3 tool_calls 禁线**：`finish_reason` 类型含 `"tool_calls"` 字面量，但任何路径都不得赋值；不得写 `delta.tool_calls`。
- **P-4 include_usage 一致性**：progress chunk 必须与 TEXT_DELTA/THINKING 同样处理 `usage=None`（include_usage=True 时），否则破坏 Pitfall 1 契约（末尾 `choices=[]+usage` chunk）。
- **P-5 流序合法性**：progress chunk 的 `finish_reason` 必须 `None`；收尾仍由 `MESSAGE_COMPLETE` 唯一产出一个 finish chunk。
- **P-6 非流式聚合**：progress 进 `reasoning_content` 聚合可接受，但 `message.content`（正文）必须逐字不变（D-3）。
- **P-7 异步约束**：全链路 async（adrf），ORM 经 `sync_to_async`；helper 设计为纯函数避免任何 ORM/IO（便于独测）。
- **P-8 ruff/约定**：line length 100，注释/docstring 中文（项目约定）。

---

## 6. Validation Architecture（供 VALIDATION.md 生成 / nyquist 校验）

四层可验证测试架构，全部可在 `server/tests/compat/` 落地（扩充既有 `test_adapter.py` + 新增映射纯函数测）：

### 6.1 纯函数映射单测（最快、最密）
- 目标：`tool_event_to_progress` / `retrieval_to_progress` / 映射表。
- 用例：
  - 各内部工具名（`search_rag`/`grep`/`get_file`/仓库分析）→ 预期中文 progress 文本。
  - 未知工具名 → `None`（静默）。
  - 非工具事件（`TEXT_DELTA`/`THINKING`/`MESSAGE_COMPLETE`）→ 不被映射误命中。
  - 安全：构造含敏感 sentinel 的 `tool_input`/`result` → 断言**不出现**在输出。
- 无需 DB / 无需 async runner，纯函数直调。

### 6.2 adapter 流式集成测（注入 AgentEvent 序列）
- 复用 `test_adapter.py` 的 `_make_runner(*events)` + `_collect` 范式（已存在，line 32-56）。
- 注入含 `TOOL_USE_START` 的序列 → 断言：
  - SSE 输出**含** `delta.reasoning_content` progress chunk（文本为预期语义）。
  - **不含** `delta.tool_calls` 字段；任一 chunk 的 `finish_reason` ≠ `"tool_calls"`。
  - `delta.content`（正文）**不被污染**（progress 不混入 content）。
  - progress chunk `finish_reason is None`、`object=="chat.completion.chunk"`。
  - include_usage=True 时 progress chunk 带 `usage=None`，末尾仍恰好一个 `choices=[]+usage` chunk。

### 6.3 零回归测（byte-equivalence）
- 无工具事件的既有序列（`THINKING`→`MESSAGE_COMPLETE`、`TEXT_DELTA`→`MESSAGE_COMPLETE`、`ERROR` 关闭流）→ SSE 输出与现状**逐字等价**（不新增任何 chunk）。
- 既有 5 个 adapter 测试（reasoning_content / text_delta / include_usage true/false / error_closes_stream）必须保持全绿。
- 非流式路径：断言 `message.content` 与现状逐字一致；`reasoning_content` 聚合行为符合 D-3 决策。

### 6.4 安全不泄漏测（INV-5）
- 注入 `TOOL_USE_START.data` 含敏感 `tool_input`（如 API key / 私有代码 sentinel）、`TOOL_USE_RESULT.data` 含敏感 `result`、以及 `THINKING` 含 CoT sentinel。
- 断言全量 SSE 字节流中**不出现**任一 sentinel（progress 只透出工具名语义）。

### Nyquist 采样覆盖矩阵（要求每个需求/约束至少一个可验证断言）
| 需求/约束 | 验证层 | 断言要点 |
|-----------|--------|----------|
| TRACE-01（progress 可见） | 6.2（+6.1） | 含 reasoning_content progress chunk，文本为预期语义 |
| TRACE-01（Option B 真实 RAG） | 6.2 集成 | 检索阶段产出"正在检索 RAG/命中 N 处" |
| TRACE-02（不误用 tool_calls） | 6.2 | 无 tool_calls 字段 / finish_reason≠tool_calls |
| TRACE-02（缺事件降级） | 6.3 | 无事件序列逐字等价、零空 chunk |
| INV-5（非 CoT、不泄漏） | 6.4 | sentinel 全不出现 |
| 零回归（既有行为） | 6.3 | 既有测试全绿 + 非流式 content 不变 |

---

## 7. Open Questions（plan 阶段决断）

- **OQ-1（必答）**：scope 取 Option A / B / C？（researcher 建议 C，最低 B；纯 A 不满足 TRACE-01 可见验收）见 D-1。
- **OQ-2**：Option B 的检索 progress 时序落在 `views._stream_chunks` 还是 `translate_stream` 前置？元数据如何从 `prepare_messages` 传出（返回值扩展 vs view 内重取）？
- **OQ-3**：`TOOL_USE_RESULT` 是否透出完成态文本？取决于是否有非敏感摘要可用（F-6 计数派生 vs 静默）。CONTEXT line 52 授权按 payload 实际定。
- **OQ-4**：helper 放置——`server/compat/progress.py` 新模块（利于 Phase 57 复用）vs adapter.py 内？建议新模块。
- **OQ-5**：非流式下 progress 进 `reasoning_content` 是否最终接受（D-3）？还是显式丢弃只留正文？CONTEXT 倾向接受。

---

## RESEARCH COMPLETE

**核心发现**：CONTEXT 锁定的"映射 `TOOL_USE_*` → reasoning_content"在机制上正确且前向兼容，但**当前 compat 链路 runner 不绑定任何工具（`_build_runner` 无 tools）、RAG/grep 检索在 `prepare_messages` 中 stream 前同步执行且不发任何事件**——纯 adapter 映射会产出 0 progress、TRACE-01 可见效果落空。规划须决断是否叠加"真实 RAG 检索 progress 透出"（Option B/C，researcher 推荐 C/最低 B）。透出字段锁定 `delta.reasoning_content`，严守 INV-5（不泄漏 tool_input/result/CoT）与 TRACE-02（不写 tool_calls）。已给出最小改动清单、纯函数 helper 抽象、四层 Validation Architecture（映射单测 / adapter 集成 / 零回归 byte-eq / 安全 sentinel）与 Nyquist 覆盖矩阵。
