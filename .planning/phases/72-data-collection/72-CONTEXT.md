# Phase 72: 调用数据采集（AI/LLM TPS + 召回 + 请求入口） - Context

**Gathered:** 2026-06-24
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous——grey area 按 MILESTONE-PROPOSAL §B/§C + STATE.md 关键约束自动采纳最优解）

<domain>
## Phase Boundary

把所有"能成时序"的调用数据采集到**精简事件表**——QPS/TPS/召回/请求错误三口径/上游错误码/时长/TTFT。**本 Phase 只写数据**（埋点），查询/出图/快照在 Phase 73，告警在 74，大盘在 75。

**交付（RATE-01/02, RAG-01/02, SLA-02/03/04）：**
- `RequestMetric` 模型（每请求一行）+ 统一入口埋点（DRF 基类/ASGI + MCP `_record` + chat SSE wrap + compat OpenAI/Anthropic + webhook + WS + 召回 + embedding/reranker）
- 扩展 `ModelUsageRecord`（`call_source`/`ttft_ms`/`upstream_status_code`）+ 22 类 call_source 全覆盖 + **容器侧** token 链路补全（task→回调→ModelUsageRecord）
- 召回指标（条数/分层耗时 embedding·sparse·qdrant·rerank/score）+ `RetrievalTrace` 留痕扩展到 MCP+AI 对话两条链
- 请求错误三口径（系统/业务限制/上游）+ 上游码（429/529 单列）+ duration_ms + ttft_ms（流式首 chunk 计时）

依赖 Phase 71（用户上下文贯穿——指标/留痕绑定 user 与 source；contextvars 已就绪可直接读 user_id/request_id/source）。

</domain>

<decisions>
## Implementation Decisions

### RequestMetric 模型（RATE-01 / SLA-01/02/04）
- 落 `system` app（与 SystemLogEntry 同域，复用 settings/清理/查询设施）。字段：`ts(index)`, `source`(LogSource 枚举复用), `route`, `method`, `status_code`, `error_class`(none/system/business/upstream), `duration_ms`, `ttft_ms`(nullable), `user_id`(→system), `labels`(jsonb: call_source/provider/credential/model/关联键，**受控枚举，禁用户输入原文**)。复合索引 `(ts, source)` + `(ts, error_class)` 支持 Phase 73 SQL 聚合。
- **每请求一行**，best-effort 写入（绝不反噬业务，`except: pass`）。量级低，直接落行不做进程内聚合（第一性原理 §A.2）。
- 轮询/health 路由（运维页 4s 轮询、健康探针、observability poll、索引 SSE）打 `labels.synthetic=true` 或 `error_class` 隔离，Phase 73 SLA 聚合排除，不污染业务统计。

### 统一入口埋点（RATE-01 / SLA-02/04）
- **复用 Phase 71 `LogContextMixin`/中间件**已注入的 request_id/source/user_id。新增 `RequestMetricMiddleware`（或扩展 71 中间件）在请求结束记 `RequestMetric`（HTTP 入口 duration/status/error_class）。DRF 基类 mixin 补 route/source 细分。
- **MCP**：`mcp_tools/views.py` 的 `_record`（已有 ToolCallRecord 时长）旁路加 RequestMetric（source=mcp，labels.call_source=工具名）。
- **chat SSE**：在 SSE wrap 处记首 chunk ttft + 总 duration（source=chat_sse）。
- **compat**：OpenAI `/v1/chat/completions` + Anthropic `/v1/messages` 入口（source=compat_openai/compat_anthropic），流式首 chunk ttft。
- **webhook/WS**：webhook 入口（已在 71 留痕）补 RequestMetric；WS connect/disconnect 计数（source=ws）。
- **召回/embedding/reranker** 作为入口也记一行（source 对应，labels.call_source）。

### error_class 三口径（SLA-02）
- `system`：5xx/未捕获异常（计入 SLA 故障）。
- `business`：按规则拒绝的非故障——`LLMBusyError`（系统繁忙/并发限流）、权限拒绝（403/PermissionDenied）、输入校验失败（400/ValidationError）——**排除 SLA 故障**。
- `upstream`：上游 provider 错误（见 SLA-03，429/529 单列）。
- 单一收口 helper `classify_error(exc_or_status) -> error_class` 供各入口复用，避免口径漂移。

### ModelUsageRecord 扩展（RATE-02 / SLA-03 / SLA-04）
- 加字段 `call_source`(枚举，22 类见 LOGGING-SPEC §4.1)、`ttft_ms`(nullable)、`upstream_status_code`(nullable int)、`failure_type`(nullable，429/529/其他上游)。migration 自动生成。
- **埋点位**：`acquire_llm_slot`（QPS/排队/`LLMBusyError`）+ 两个 Runner（`chat_runner`/`langchain_runner`）的 `astream` 循环（TTFT=首 chunk 计时 / TPS / 上游码）+ 各 `ainvoke`。每个 LLM 调用点赋 `call_source`（枚举），上报 input/output/cache token 按 provider 区分。
- **容器侧 token 链路补全（RATE-02 核心）**：task 当前写 `usage.json`，但 server 侧读取/回调链不完整。补全 `workflow_coding_container`/`repo_summary_container`/`deep_analysis_container`/`sdk_agent_task` 的 task→容器回调→`subagent.TokenUsage`/`ModelUsageRecord` 链路，使容器 LLM token/TTFT 纳入 TPS。

### 召回可观测（RAG-01 / RAG-02）
- **指标（RAG-01）**：召回条数、总耗时 + 分层耗时（embedding/sparse/qdrant/rerank）、score 分布；按来源（MCP/对话/workflow）打标。埋点位 `rag_search.py`（search_rag 出口，单一 chokepoint）+ `QdrantService.search/hybrid_search`（qdrant 层耗时）+ `EmbeddingService`（embedding 层）+ rerank。指标可走 RequestMetric(source=rag) + labels 分层耗时，或专用轻量记录；分层耗时进 labels（受控键）。
- **留痕（RAG-02）**：`RetrievalTrace`（已有）扩展覆盖面到 MCP + AI 对话两条链——记 query 原文 + 召回 chunk 内容 + score + 会话/用户。chat/workflow 代码 RAG 透传 user_id（Phase 71 contextvars 已可读）。召回内容走"详情/留痕"按需采样，**不按 chunk 入指标**（避免基数失控，§A.4）。

### Claude's Discretion
- migration 编号自动生成；RequestMetric 具体索引组合、labels 受控键集合定型在 plan；分层耗时是否单独 GaugeSample-like 还是塞 labels 由 plan 定（倾向 labels）。
- 埋点 helper 命名（`record_request_metric`/`record_model_usage` 等）遵循现有 idiom。
- 容器回调链路改动若涉及 task/runner 契约，保持向后兼容（缺字段降级，零回归）。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- Phase 71：`common/log_context.py`（user_id/request_id/source contextvars 已注入）、`LogContextMixin`/`RequestLogContextMiddleware`、`system/log_sink.py`（队列范式）、`system/log_retention.py`（保留清理，指标表可复用同款）。
- `server/interactions/models.py`：`ModelUsageRecord`（待扩展）、`InteractionRun`/`InteractionEvent`/`ToolCallRecord`/`RetrievalTrace`（已有，扩覆盖面）+ `redaction.py`/`ledger.py`/`entry.py`。
- `server/agents/llm_concurrency.py`：`acquire_llm_slot` + `LLMBusyError`（QPS/排队/业务限制埋点位）。
- `server/agents/chat_runner.py` / `langchain_runner.py`：两个 Runner 的 `astream`/`ainvoke`（TTFT/TPS/上游码埋点位）。
- `server/services/retrieval/rag_search.py`（search_rag 单一 chokepoint）+ `hybrid_search.py` + `rerank.py`；`QdrantService`、`EmbeddingService`。
- `server/mcp_tools/views.py` `_record`（MCP 时长，旁路加 RequestMetric）。
- compat：`server/compat/`（OpenAI/Anthropic 端点 + translate_stream）。
- 容器侧：`server/subagent/`（TokenUsage 回调）、task usage.json、runner callbacks。

### Established Patterns
- best-effort 观测 `except: pass`；async ORM `sync_to_async`；structlog snake_case + category/component；labels 受控枚举禁用户输入原文。
- Phase 71 已建"指标/留痕/日志三分"地基，本 Phase 写"指标 + 留痕扩覆盖"。

### Integration Points
- HTTP/DRF/ASGI 入口（中间件/mixin）；MCP `_record`；chat SSE wrap；compat 端点；webhook（71 已留痕处）；WS consumer connect/disconnect；rag_search 出口；Qdrant/Embedding/rerank；acquire_llm_slot；两个 Runner astream/ainvoke；容器回调（subagent + runner）。

</code_context>

<specifics>
## Specific Ideas

- 严守 `.cursor/rules/observability-logging.mdc`：新增 LLM 调用点赋 `call_source`（枚举见 LOGGING-SPEC §4.1）；新增请求入口纳入 QPS/错误率/时长；新增召回上报条数/分层耗时/score 并写 RetrievalTrace（MCP+AI 对话两条链）。
- 指标=精简事件行（RequestMetric + 扩展 ModelUsageRecord），留痕=Interaction Ledger，三者用 request_id/run_id/conversation_id 关联不复制。
- TPS 要全量不漏容器（RATE-02 是本 Phase 难点：容器 token 回调链路补全）。
- 第一性原理：原始事件行，不自研聚合器（Phase 73 用 Postgres percentile_cont）。

</specifics>

<deferred>
## Deferred Ideas

- 时序查询 API / 快照 / 趋势采样（GaugeSample）/ 可用率聚合 → Phase 73。
- 告警阈值评估 → Phase 74。
- 大盘前端出图 → Phase 75。
- 每日 rollup（MetricDailyRollup）→ Phase 73 可选。

</deferred>
