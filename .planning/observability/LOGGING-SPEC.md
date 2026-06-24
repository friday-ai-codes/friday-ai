# Friday AI 日志与可观测性工程规范（LOGGING-SPEC）

> **这是强制工程规范。** 任何新增或修改功能（API、节点、服务、任务、webhook、工具）都必须按本规范补齐**日志**与**指标埋点**。
> 配套：Agent 强制规则 `.cursor/rules/observability-logging.mdc`；里程碑方案 `.planning/observability/MILESTONE-PROPOSAL.md`。
>
> 注：本规范定义"目标态"。可观测性平台正在 v0.14.0 里程碑分阶段落地，部分基础设施（指标门面、SystemLogEntry 落库、CTX 贯穿）在对应阶段完成前，先遵守"日志事件命名 + 字段 + 脱敏 + 用户绑定 + caller/sampling 分类"的约定，平台就绪后无需改业务代码即可生效。

---

## 1. 基本原则

1. **结构化优先**：一律用 `structlog.get_logger(__name__)`，事件名是 snake_case 名词短语（`xxx_started` / `xxx_completed` / `xxx_failed`），字段用 kv，**不要**把变量拼进 message 字符串。
2. **脱敏不可绕过**：禁止把凭证/token/密钥写进日志或留痕。统一走 `server/common/logging.py` 的 `redact_credentials`（structlog processor，自动）与 `redact_secrets_in_text`（字符串 helper，手动用于上游响应体/异常文本）。入库留痕走 `redact_for_ledger`。
3. **绑定用户**：每条日志都应能回答"谁触发的"。依赖请求级 contextvars（`user_id` / `request_id` / `source` / `trace_id`）自动注入；无触发用户的系统行为记 `user_id="system"`（或 `actor=system`）。后台任务必须显式传递发起用户（见 §6）。
4. **指标与留痕分离**：高频数值走**指标门面**（聚合，不逐条）；调用详情/召回内容/会话原始数据走 **Interaction Ledger** 或**系统日志（采样）**。
5. **永不反噬业务**：日志/指标/缓冲失败必须 best-effort 吞掉（参考现有 `append_log` / `buffer_log` 的 `except: pass`），绝不让观测代码抛出打断主流程。
6. **级别纪律**：`debug` 仅本地排障（生产默认 INFO 过滤掉）；`info` 关键生命周期；`warn` 可恢复异常/降级；`error` 需要关注的失败。高频循环内禁止 INFO 刷屏（历史教训：4000+ 文件的 `graph_bundle_written` 刷爆 stdout）。

---

## 2. 事件分类：caller 与 sampling

每个日志事件必须归入一类（写入 `category` 字段）：

- **`caller`（调用类）**：一次外部/用户可归因的调用。必须绑定用户（或 `system`）、带关联键（`run_id`/`conversation_id`/`execution_id`/`request_id`）。**全量记录**（不采样，除非超高频）。
  - 例：MCP 工具调用、AI 对话发起、REST 写操作、compat 请求、webhook 接收、工作流触发、登录。
- **`sampling`（采样类）**：高频内部步骤/诊断信息。按运行时采样配置记录（首 N 条全记，之后按比例）。
  - 例：单次 LLM turn、单次 qdrant 查询、单次 embedding、节点内部步骤、循环内进度。

> 判断口诀：**"用户会想在审计/排障里逐条看到吗？"** → 是则 `caller`；"只是用来看趋势/偶尔抽查" → `sampling`。

---

## 3. 标准字段（structlog 事件约定）

| 字段 | 含义 | 来源 |
|------|------|------|
| `event` | 事件名（snake_case） | 手写 |
| `level` | 级别 | structlog 自动 |
| `category` | `caller` / `sampling` | 手写 |
| `component` | 组件名（见 §5 组件清单） | 手写 / contextvars |
| `user_id` | 触发用户；系统为 `system` | contextvars（自动） |
| `source` | 入口来源（`mcp`/`chat`/`compat`/`rest`/`webhook`/`workflow`/`task`/`scheduler`） | contextvars（自动） |
| `request_id` / `trace_id` | 请求/链路关联 | contextvars（自动） |
| 关联键 | `run_id`/`conversation_id`/`execution_id`/`session_id`/`repository_id` 等 | 手写 |
| `duration_ms` | 耗时（完成/失败事件） | 手写 |
| `error` / `error_type` | 失败信息（脱敏后） | 手写 |

---

## 4. 指标埋点约定（call_source 标签体系）

**架构（第一性原理）：** 本系统量级低，指标走**精简事件行 + SQL 聚合**，不自研进程内直方图/聚合器。分位用 Postgres `percentile_cont`（精确），时间桶用 `date_trunc`。
- 请求级（QPS/错误/时长/TTFT/SLA）→ 写 `RequestMetric`（每请求一行）。
- LLM（TPS/上游错误/成本/TTFT）→ 写/扩展 `ModelUsageRecord`（每次调用一行，补 `call_source`/`ttft_ms`/`upstream_status_code`）。
- 召回 → `RetrievalTrace`（内容/score）+ 聚合条数/分层耗时。
- 趋势 gauge（并发/队列/积压）→ 周期采样 `GaugeSample`。
- 快照（CPU/内存/DB/Redis/Qdrant）→ 按需采集，不长存。

平台表/采集器就绪前，先用 structlog 事件携带等价字段（含下表 labels），平台据此回填；**严禁把用户输入原文当 label**（基数失控），label 取受控枚举。

### 4.1 LLM/AI 调用来源枚举（`call_source` 标签，必须带）

QPS/TPS/TTFT/上游错误统计都按 `call_source` 区分。新增任何 LLM 调用点必须赋一个 `call_source`：

| call_source | 入口 | 备注 |
|-------------|------|------|
| `chat` | `ConversationService.send_message_stream` / `ChatAnthropicRunner` | 流式 |
| `chat_compat_openai` | `compat/views.ChatCompletionsView` | `/v1/chat/completions` |
| `chat_compat_anthropic` | compat Messages | `/v1/messages` |
| `workflow_agent_node` | `AIAgentBaseNode` → `LangChainAgentRunner` | 流式 ReAct |
| `workflow_prompt_node` | `AIPromptNode` | 单轮 ainvoke |
| `workflow_variable_extractor` | `AIVariableExtractorNode` | 单轮 |
| `workflow_coding_container` | `AICodingNode` → task 容器 | SDK |
| `plan_merge` | `ArchitectMergeAdapter` | 单轮 |
| `plan_spec_generation` | `LLMSddSpecSynthesizer` | 单轮 |
| `aux_title` | `title_service` | 对话标题 |
| `aux_sensitive_llm` | `sensitive_detect` | 敏感文件分类 |
| `aux_screenshot_vision` | `screenshot_recall` | 多模态 |
| `aux_knowledge_grader` | `llm_grader` | 检索分级 |
| `aux_corpus_tree` | `corpus_tree` | 语料树 |
| `aux_repo_router` | `repo_router_v2` | 选仓 |
| `aux_crawl` | `crawl_service` | 交付知识爬取 |
| `repo_summary_container` | `summary_service.dispatch_repo_summary` | task 容器 |
| `deep_analysis_container` | chat 深度分析 → SubAgent | task 容器 |
| `sdk_agent_task` | `tasks/agent_tasks` → `SDKAgentRunner` | 后台 agent |
| `provider_health_probe` | `provider_health` | 探活 |
| `embedding` | `EmbeddingService` | 向量 |
| `reranker` | `RerankerService` | 精排 |

> 埋点位置：`acquire_llm_slot`（QPS/排队/`LLMBusyError`）+ 两个 Runner 的 `astream` 循环（TTFT/TPS/上游错误）+ 各 `ainvoke` 站点。详见 MILESTONE-PROPOSAL §1。

### 4.2 标准指标名（建议）

| 指标 | 类型 | 关键 labels |
|------|------|-------------|
| `requests_total` | counter | `source, route, method, status_class` |
| `request_duration_ms` | histogram | `source, route` |
| `request_ttft_ms` | histogram | `source, call_source` |
| `llm_requests_total` | counter | `call_source, provider, model, outcome` |
| `llm_tokens_total` | counter | `call_source, provider, model, kind(input/output/cache)` |
| `llm_upstream_errors_total` | counter | `provider, model, status_code` |
| `llm_concurrency` | gauge | `credential_id, provider` |
| `llm_queue_wait_ms` | histogram | `credential_id` |
| `rag_recall_total` | counter | `source` |
| `rag_recall_count` | histogram | `source`（召回条数分布） |
| `rag_stage_duration_ms` | histogram | `stage(embedding/sparse/qdrant/rerank), source` |
| `rag_top_score` | histogram | `source` |
| `queue_depth` | gauge | `queue(index/graph/summary/crawl/page_index/...)` |
| `task_backlog` | gauge | `kind(durable/background_runner/workflow/runner_pending)` |
| `webhook_received_total` | counter | `kind, verified` |
| `log_dropped_total` | counter | （队列满丢弃） |
| `log_write_failed_total` | counter | （落库失败） |
| `availability` | gauge/derived | `probe`（成功率） |

### 4.3 分位与聚合

分位（P50/P90/P95/P99）用 Postgres `percentile_cont` 对事件行的 `duration_ms`/`ttft_ms` 直接计算（精确），按 `date_trunc` 分时间桶聚合；Avg=AVG、Max=MAX、QPS=COUNT/窗口秒数。SQLite 本地 dev 无 `percentile_cont` → 降级为近似或跳过分位（仅 dev）。不自研直方图/聚合器。

---

## 5. 组件清单（`component` 取值）

按现有 Django app / 子系统归类（新增功能就近归类，没有就新增并在此登记）：

`auth` `accounts` `mcp` `chat` `orchestration` `workflows` `compat` `repositories` `indexing` `codegraph` `rag` `knowledge` `delivery` `agents` `llm` `providers` `subagent` `runners` `task` `feishu` `webhook` `durable` `scheduler` `system` `settings` `notifications` `audit` `access_tokens` `health` `metrics` `logging`

---

## 6. 用户上下文贯穿（强制）

1. **HTTP/SSE/MCP/compat 入口**：用户来自 `request.user`（PAT → 令牌所有者；JWT → 登录用户）。平台中间件自动 `bind_contextvars(user_id, request_id, source, trace_id)`，请求结束 `clear_contextvars`。业务代码无需手动传，但**新入口必须确保走统一中间件/基类**。
2. **后台任务（必须显式）**：durable job / `background_runner` / workflow / apscheduler / 飞书·webhook 触发，入队时**必须**把发起用户写进 job 元数据（`initiated_by_user_id`），worker 入口恢复 contextvars。无发起人记 `system`。
   - 工作流：`WorkflowExecution.triggered_by`（手动有；飞书/webhook 当前为 None，新功能应尽量映射或显式标 system）。
   - PAT 透传：`server/access_tokens/context.py` 的 ContextVar（窄场景，跨线程下传 PAT，**绝不入库/入日志**）。
3. **跨线程/进程不自动传播**：`_run_in_thread` / `background_runner` 用干净 `contextvars.Context()`，必须显式重新 bind 用户。

---

## 7. 留痕（Interaction Ledger）使用约定

调用详情与召回内容走 `server/interactions/`（append-only，已脱敏）：

- `InteractionRun`：一次外部调用的 trace 锚点（`run_id`、`token_fingerprint`、`source`、`raw_request`）。新增**外部入口**（不止 MCP）应调 `begin_interaction_run(request, source=...)`。
- `ToolCallRecord`：工具调用明细（`tool_name`、`input`、`output`、`duration_ms`、`status`、`retry_index`）。
- `RetrievalTrace`：召回证据（`kind=routing/chunk/edge/file`，`payload` 含 score/内容）。**召回内容留痕必须覆盖 MCP + AI 对话两条链**；chat/workflow 代码 RAG 需透传 user_id。
- `ModelUsageRecord`：模型用量（`provider`、`model`、token、`cost_estimate`、`duration_ms`、`failure_type`）。新埋点补 `call_source` / `ttft_ms` / `upstream_status_code`。

入库前 payload 必须经 `redact_for_ledger`。

---

## 8. 系统日志（SystemLogEntry）约定

平台落地后（LOG 阶段），系统日志统一队列化落库：

- 写入：业务用 `structlog`（自动进队列）；队列 `deque(maxlen=5000)`，满则丢弃并 `log_dropped_total++`，落库失败 `log_write_failed_total++`。
- 必带：`category(caller/sampling)`、`component`、`user_id`、`source`、关联键。
- 运行时配置（`SettingKeys.LOG_*`，实时生效）：级别（全局/分组件）、堆栈记录阈值、采样初始/后续、保留天数/大小。
- Webhook 原始数据：飞书/通用/Git/容器回调的原始 payload 入库（脱敏后）可在系统日志下钻查看。
- 清理：按时间/级别/组件/用户/关键词条件清理；保留策略到期自动清理。

---

## 9. 新功能开发检查清单（提交前自检 / Code Review 必查）

新增或修改功能时，必须确认：

- [ ] 关键生命周期有 `xxx_started` / `xxx_completed` / `xxx_failed` 结构化事件，含 `duration_ms`。
- [ ] 事件已分类 `caller` / `sampling`，并设 `component`。
- [ ] 能绑定到触发用户（入口走统一中间件；后台任务显式传 `initiated_by_user_id`；系统行为标 `system`）。
- [ ] 涉及外部凭证/上游响应体/异常文本：已 `redact_secrets_in_text` / 走脱敏 processor，无明文泄漏。
- [ ] 新增 LLM 调用点：赋了 `call_source`，上报 `llm_requests_total` / `llm_tokens_total` / TTFT / 上游错误码（或携带等价 structlog 字段）。
- [ ] 新增请求入口：纳入 `requests_total` / `request_duration_ms` 统计（QPS/错误率/时长）。
- [ ] 新增召回/检索：上报召回条数/分层耗时/score，召回内容按需写 `RetrievalTrace`。
- [ ] 新增队列/异步任务：队列深度/积压可被快照采集；任务携带发起用户。
- [ ] 新增 webhook 入口：原始 payload 脱敏后落库可查看。
- [ ] 新增可能需要关注的失败/资源指标：评估是否需要可配置告警阈值。
- [ ] 高频循环内未用 INFO 刷屏（用 `sampling` + debug 或采样）。

---

## 10. 事件目录（Phase 71 已知事件）

> 本节登记 **Phase 71（可观测性地基）涉及/新增**的已知日志事件及其 `category` / `component`。
> **不试图穷举全仓**——存量事件渐进迁移，每条业务事件缺省由 `annotate_category_component`
> processor 兜底（无 `category` → `sampling`；`component` 取 logger name 首段）。**72+ 增量补全**
> 各子系统事件目录。新增 `caller` 关键调用须业务显式 `category="caller"`。

### 10.1 用户上下文 / 中间件（CTX-01/02，component=`system`/`webhook`）

| 事件 | category | component | 说明 |
|------|----------|-----------|------|
| `log_runtime_config_apply_failed` | sampling | settings | 运行时改 `LOG_*` 后重设级别失败（best-effort 告警） |
| `system_setting_cache_invalidate_failed` | sampling | settings | 设置写入后缓存失效失败 |
| `qdrant_client_reset_due_to_setting_change` | sampling | settings | Qdrant 凭证变更触发 client 重建 |
| `qdrant_client_reset_failed` | sampling | settings | Qdrant client 重建失败 |
| `sqlite_pragma_setup_failed` | sampling | system | SQLite WAL/busy_timeout PRAGMA 设置失败 |

### 10.2 系统日志落库 / 队列（LOG-01/02，component=`logging`）

| 事件 | category | component | 说明 |
|------|----------|-----------|------|
| `system_log_flush_failed` | sampling | logging | 批量落库失败（计入 `log_write_failed_total`，丢批不重试） |

> 落库队列四计数（`queued`/`enqueued`/`written`/`dropped`/`write_failed`）+ 采样丢弃
> `sampled_out` 经 `system.log_sink.snapshot_counters()` 采集（71-04 计数端点 / Phase 73 快照消费）。
> **`dropped`（队列满）与 `sampled_out`（采样未中）语义区分**：前者是背压信号，后者是 `sampling`
> 类按 `LOG_SAMPLING_INITIAL`/`LOG_SAMPLING_RATE` 主动抽样的正常行为。

### 10.3 Webhook 原始留痕（LOG-07，component=`webhook`/`feishu`）

| 事件 | category | component | 说明 |
|------|----------|-----------|------|
| `webhook_received` | caller | webhook | 入站 webhook 接收（飞书/通用/Git/容器回调）；71-05 写入 `InboundWebhookEvent` |

### 10.4 运维观测 API（component=`system`/`metrics`）

| 事件 | category | component | 说明 |
|------|----------|-----------|------|
| `observability_served` | caller | system | 运维大盘/可观测性端点被超管访问 |

### 10.5 后台任务（CTX-02，component=`durable`/`background`/`workflow`/`scheduler`）

| 事件 | category | component | 说明 |
|------|----------|-----------|------|
| `background_runner_started` | sampling | system | 后台 runner 协程启动（携 `initiated_by_user_id` 或 `system`） |

> 后台任务（durable / `background_runner` / workflow `_run_in_thread` / apscheduler / 飞书 webhook）
> 入口须经 `common.log_context.bind_task_context` 显式绑定发起用户（无则 `system`）+ `source`，
> 事件即自动携 `user_id` / `source` / `trace_id`（见 §6）。

### 10.6 运行时日志配置键（LOG-06，`SettingKeys.LOG_*`）

| 设置键 | 类型 | 默认 | 说明 |
|--------|------|------|------|
| `log.level` | str | env→INFO | 全局过滤级别；写时 signal 即时重设 wrapper，无需重启 |
| `log.component_levels` | JSON map | `{}` | 分组件级别覆盖（`get_json_setting` 读取） |
| `log.stack_threshold` | str | ERROR | 记录堆栈的最低级别（配置就位；消费按需） |
| `log.sampling_initial` | int | 50 | `sampling` 类首 N 条全记 |
| `log.sampling_rate` | float | 0.1 | `sampling` 类之后按比例记录（0..1） |
| `log.retention_days` | int | 30 | 保留天数（清理在 71-04 消费） |
| `log.retention_max_rows` | int | 1_000_000 | 行数上限兜底（71-04 消费） |
