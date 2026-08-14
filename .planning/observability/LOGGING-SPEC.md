# Friday AI 日志与可观测性工程规范（LOGGING-SPEC）

> **这是强制工程规范。** 任何新增或修改功能（API、节点、服务、任务、webhook、工具）都必须按本规范补齐**日志**与**指标埋点**。
> 配套：Agent 强制规则 `.cursor/rules/observability-logging.mdc`；里程碑方案 `.planning/observability/MILESTONE-PROPOSAL.md`。
>
> 状态（v0.14.0 已落地）：可观测性平台基础设施已交付——用户上下文贯穿（contextvars 中间件 + 后台任务绑定，Phase 71 CTX）、SystemLogEntry 队列化落库 + 运行时配置（Phase 71 LOG）、指标精简事件表（`RequestMetric` / 扩展 `ModelUsageRecord` / `GaugeSample`，Phase 72–73）、快照/趋势查询端点与可观测大盘（Phase 73）、告警评估与通知（Phase 74）。本规范即"现行态"：新增/改动功能按下列约定补齐日志与埋点即自动生效，无需再等基础设施。

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

指标表/采集器（`RequestMetric` / `ModelUsageRecord` / `GaugeSample`）已就绪：高频数值经 `common.request_metrics.record_request_metric` 等写入精简事件行，SQL 聚合即得 QPS/分位/TPS/召回分布。结构化日志只携带可归因生命周期事件，**不重复**承载高频数值。**严禁把用户输入原文当 label**（基数失控），label 取受控枚举。

### 4.1 LLM/AI 调用来源枚举（`call_source` 标签，必须带）

QPS/TPS/TTFT/上游错误统计都按 `call_source` 区分。新增任何 LLM 调用点必须赋一个 `call_source`。**权威定义是 `server/agents/call_source.py` 的 `CallSource` 枚举，当前 46 值**（v0.19.0 补登 `feature_change_classify`，v0.20.0 新增 8 个 `blueprint_*`，Phase 125 新增 `module_summary`，Phase 128 新增 `initiative_profile`），下表与之逐条对齐：

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
| `memory_distill` | `initiatives.MemoryDistiller`（v0.15.0 Phase 80） | 从成员会话提炼项目记忆草稿，单轮，产 pending 草稿 |
| `ide_hook_distill` | `report_project_knowledge` active 模式蒸馏（v0.16.0 Phase 86） | stop hook 组织上下文 → 精炼记忆条目，单轮，best-effort，active 直写前可选精炼 |
| `board_split` | `initiatives.FeatureListExtractor` / BoardSplitService（v0.16.0 Phase 87） | feature list 结构化抽取/重拆（模块→功能点→验收项），单轮，按模块/标题分块可多次 |
| `repo_verify_container` | `RepoVerifyDispatchService` per-repo explore 容器（v0.16.0 Phase 88） | 深入仓库代码验证业务适配性，多仓 fan-out，task 容器 |
| `repo_association` | `initiatives.RepoAssociationService` 候选细化/Agent 自处理（v0.16.0 Phase 88） | 多轮细化候选仓库，可多次调用 |
| `plan_deepen` | `PlanDeepenService` / `ArchitectMergeAdapter`（v0.16.0 Phase 89） | per-repo 七要素 + overall 整体方案深化，经 v0.7 引擎 per-repo explore 容器 + 架构师融合，多仓 fan-out |
| `plan_revision` | 方案修订回路「调研问题发现」检测（v0.16.0 Phase 89，89-02） | 执行中发现要改/增/删仓 → 更新方案/补充修订，多轮 |
| `branch_naming` | 分支名生成（v0.16.0 Phase 89，89-04） | 按固定格式 + 方案上下文生成分支名，server 权威拼装 + 卡片确认，单轮 |
| `plan_clarification` | `clarification_questions` / ClarifyAdapter（v0.16.1 Phase 90） | 基于需求+路由+召回产结构化澄清问题（多题/单多选/推荐），单轮 |
| `plan_decompose` | `decompose_segments` / `PlanOrchestrationEngine._decompose`（v0.16.1 Phase 95） | LLM 跨仓业务线/模块/前后端拆需求 → 结构化 segments，单轮，best-effort 失败回退按行切分 |
| `feature_list_parse` | feature list 导入解析（GitLab 文档/粘贴文档 → 结构化 模块→功能点→验收项） | 单轮，best-effort，内容逐字保留原文（补登已漂移枚举） |
| `learning_case_extraction` | `mcp_tools.learning_case_extraction.aextract_learning_case`（v0.17.0 Phase 101） | 编码完成自动提炼，三链路 MR 已知锚点，单轮，幂等键 session_id，best-effort |
| `pr_review_capture` | PR 创建成功锚点可选 review 沉淀（v0.17.0 Phase 101） | 默认关（SystemSetting），单轮，结论沉淀为 learning case |
| `feature_change_classify` | feature list 方案编排的功能点分类与强制仓库确认（`process_runtime`，commit 2e27493c） | 单轮，best-effort（补登已漂移枚举） |
| `blueprint_decompose` | 蓝图需求对齐拆解（v0.20.0 Phase 111 注册） | 需求 → requirement_spec feature_points；调用点在 112 落地 |
| `blueprint_spec_gate` | 蓝图歧义门 spec_gate（v0.20.0 Phase 111 注册） | 多轮澄清 + feature_point 意图分类 greenfield/brownfield/fix；调用点在 112 落地 |
| `blueprint_repo_research` | 蓝图逐仓调研容器（v0.20.0 Phase 111 注册） | 每仓一容器 fitness 判定 + 职责/现状调研，多仓 fan-out；调用点在 112 落地 |
| `blueprint_reroute` | 蓝图重路由（v0.20.0 Phase 111 注册） | 确认门增删仓/改判后的有界循环重路由；调用点在 112 落地 |
| `blueprint_repo_plan` | 蓝图分仓方案深化（v0.20.0 Phase 111 注册） | per-repo 实现方案；调用点在 113 落地 |
| `blueprint_merge` | 蓝图融合装配（v0.20.0 Phase 111 注册） | 分仓方案 → 六段 blueprint/v1；调用点在 113 落地 |
| `blueprint_ai_review` | 蓝图对抗审查（v0.20.0 Phase 111 注册） | AI 评审员产 review_finding 线程；调用点在 114 落地 |
| `blueprint_charter_draft` | `repositories.services.charter_service.adraft_charter`（v0.20.0 Phase 111） | 仓库章程 AI 起草：ai_summary/facets + MR 历史 + RepoAssociation 裁决三源蒸馏，单轮，best-effort |
| `module_summary` | `services.code_graph.module_summary`（Phase 125 仓社区模块摘要） | 仓社区模块摘要，单轮，best-effort |
| `initiative_profile` | `services.process_runtime.initiative_profile`（Phase 128 专项画像） | feature list → InitiativeProfile，单轮，best-effort；语料不足 clarify |

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

`auth` `accounts` `mcp` `chat` `orchestration` `workflows` `compat` `repositories` `indexing` `codegraph` `rag` `knowledge` `delivery` `agents` `llm` `providers` `subagent` `runners` `task` `feishu` `webhook` `durable` `scheduler` `system` `settings` `notifications` `audit` `access_tokens` `health` `metrics` `logging` `interactions` `code_graph`

> `codegraph`（无下划线）与 `code_graph`（有下划线）**刻意并存**，不是笔误：前者是索引/抽取侧的 Django app（`server/codegraph/`，负责 Symbol / CallEdge / Endpoint 抽取与图谱构建），后者是查询/服务侧的内存图服务（`server/services/code_graph/`，负责装配 networkx 图、缓存与读取层收口）。两条链路的故障模式与排障路径完全不同，分开取值才能按 `component` 精确筛日志（Phase 121 决策 D-07）。

> **`code_graph` 链路附加约定（由 `server/tests/services/code_graph/test_access.py::test_observability_contract` 静态守护，违规当场变红）**：
>
> 1. 事件名必须带 `code_graph_` 前缀且**静态可解析**（字符串字面量或模块级 `Final[str]` 常量）——⛔ 禁止三元表达式 / f-string / 拼接；前缀不得缩写（`graph_build_*` 已被 `services/graph_builder.py` 占用、`galaxy_cache_*` 已被 `codegraph/galaxy/cache.py` 占用）。
> 2. `component` 恒为 `"code_graph"`。
> 3. `category`：**包内** `services/code_graph/*.py` 只许 `sampling`（内核不是调用入口，调用类归因由外层壳层 `mcp_tools` / `workflows` 自己发 `caller` 事件承担，内核靠 `initiated_by_user_id` 保住「谁触发的」）；包外兄弟模块（`services/code_graph_tools.py`、`services/code_graph_cross_repo.py`）可取 `sampling` / `caller` 之一。
> 4. `error=` 必须在**埋点处**显式过 `redact_secrets_in_text`（判据是静态 AST，藏在 helper 里看不见）；稳定短码走 `error_code=`，⛔ 不要塞进 `error=`。
> 5. 公共 kv ⛔ 不要收进 `**fields` 再展开——契约按关键字名逐条查 `component` / `category`，展开的 dict 在 AST 上没有名字。
>
> Phase 125–127 的 `community_rebuild_*` / `process_rebuild_*` / `module_summary_*` / `impact_report_*` / `security_scan_*` / `semgrep_*` / `enqueue_semgrep_scan_*` / `list_processes_*` / `get_process_*` / `rename_preview_*` 均已按上述约定统一补前缀为 `code_graph_*`，并把包内 `caller` 收敛为 `sampling`。

可观测性子系统（71–74 实际使用，按视图/服务细分以便筛选）：
`metric_sampling`（gauge 周期采样）`metric_retention`（指标行清理）`alerting`（告警规则/评估/通知）`alert_retention`（告警事件清理）`call_drilldown`（调用下钻）`conversation_drilldown`（会话下钻）`webhook_events`（webhook 留痕查询）`webhook_recorder`（webhook 入库）`system_logs`（系统日志查询/清理）`log_retention`（系统日志/webhook 留痕保留清理）

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

系统日志统一队列化落库（Phase 71 LOG 已落地）：

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

## 10. 事件目录（Phase 71–74 已埋点事件）

> 本节登记 **可观测性里程碑（Phase 71–74）涉及/新增**的已知日志事件及其 `category` / `component`，
> 事件名与代码 `structlog` 调用一致（经 `rg` 核对，勿臆造）。
> **不试图穷举全仓**——存量事件渐进迁移，每条业务事件缺省由 `annotate_category_component`
> processor 兜底（无 `category` → `sampling`；`component` 取 logger name 首段）。新增 `caller`
> 关键调用须业务显式 `category="caller"`。
>
> 分节：§10.1–10.6 为 Phase 71 地基（用户上下文/落库/webhook/观测 API/后台任务/运行时配置键）；
> §10.7 调用并发/限流 + 留痕（Phase 72）；§10.8 快照/趋势/查询/采样/保留（Phase 73）；
> §10.9 告警评估与通知（Phase 74）。

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
| `system_logs_purged` | caller | log_retention | 系统日志按保留策略清理（行数/天数到期） |
| `system_logs_purge_failed` | caller | log_retention | 系统日志清理失败 |
| `webhook_events_purged` | caller | log_retention | webhook 留痕按保留策略清理 |
| `webhook_events_purge_failed` | caller | log_retention | webhook 留痕清理失败 |

> 落库队列四计数（`queued`/`enqueued`/`written`/`dropped`/`write_failed`）+ 采样丢弃
> `sampled_out` 经 `system.log_sink.snapshot_counters()` 采集（71-04 计数端点 / Phase 73 快照消费）。
> **`dropped`（队列满）与 `sampled_out`（采样未中）语义区分**：前者是背压信号，后者是 `sampling`
> 类按 `LOG_SAMPLING_INITIAL`/`LOG_SAMPLING_RATE` 主动抽样的正常行为。

### 10.3 Webhook 原始留痕（LOG-07，component=`webhook`/`feishu`）

| 事件 | category | component | 说明 |
|------|----------|-----------|------|
| `webhook_received` | caller | webhook | 入站 webhook 接收（飞书/通用/Git/容器回调）；71-05 写入 `InboundWebhookEvent` |
| `inbound_webhook_recorded` | caller | webhook_recorder | webhook 原始 payload 脱敏后入库（`InboundWebhookEvent`） |
| `inbound_webhook_record_failed` | sampling | webhook_recorder | webhook 留痕入库失败（best-effort，不反噬接收） |
| `inbound_webhook_bg_schedule_failed` | sampling | webhook_recorder | webhook 留痕后台落库调度失败 |
| `webhook_events_queried` | sampling | webhook_events | 超管查询 webhook 留痕列表（高频轮询） |

### 10.4 运维观测 API / 下钻（component=`system`/`metrics`/`call_drilldown`/`conversation_drilldown`）

| 事件 | category | component | 说明 |
|------|----------|-----------|------|
| `observability_served` | caller | system | 运维大盘/可观测性端点被超管访问 |
| `call_drilldown_viewed` | caller | call_drilldown | 单次调用（`InteractionRun`/工具调用）下钻详情查看 |
| `conversation_drilldown_viewed` | caller | conversation_drilldown | 会话维度调用链下钻查看 |
| `system_logs_queried` | sampling | system_logs | 超管查询系统日志列表（高频轮询，避免污染调用类统计） |
| `system_logs_cleared` | caller | system_logs | 超管按条件清理系统日志（可归因写操作） |

### 10.5 后台任务（CTX-02，component=`durable`/`background`/`workflow`/`scheduler`）

| 事件 | category | component | 说明 |
|------|----------|-----------|------|
| `background_runner_started` | sampling | system | 后台 runner 协程启动（携 `initiated_by_user_id` 或 `system`） |
| `job_start` | sampling | scheduler | apscheduler 注册作业开始（经 `_with_scheduler_log_context` 绑 `user_id=system`/`source=scheduler`） |
| `job_complete` | sampling | scheduler | apscheduler 注册作业完成（带 `result`） |

> 后台任务（durable / `background_runner` / workflow `_run_in_thread` / apscheduler / 飞书 webhook）
> 入口须经 `common.log_context.bind_task_context`（或 scheduler `_with_scheduler_log_context`）显式绑定
> 发起用户（无则 `system`）+ `source`，事件即自动携 `user_id` / `source` / `trace_id`（见 §6）。
> gauge 采样与告警评估两类周期作业的**内部**事件用 `category="sampling"` 避免 INFO 刷屏（见 §10.8/§10.9）。

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

### 10.7 LLM 并发/限流 + 留痕（Phase 72，component=`llm`/`interactions`）

> LLM chokepoint（`acquire_llm_slot`）+ 两个 Runner 的 `astream` 循环 + 各 `ainvoke` 站点按
> `call_source`（§4.1）打标。QPS/TPS/TTFT/上游错误的**数值**写 `ModelUsageRecord` / `RequestMetric`
> 指标行（非 structlog）；下列结构化事件只覆盖并发槽位与留痕的可归因/失败生命周期。

| 事件 | category | component | 说明 |
|------|----------|-----------|------|
| `llm_slot_acquired` | sampling | llm | 获取 LLM 并发槽位（带 `call_source` / `queue_wait_ms` / `backend`） |
| `llm_slot_busy_timeout` | caller | llm | 槽位等待超时限流（抛 `LLMBusyError`，`backend=redis`/`inprocess`，业务可归因） |
| `llm_slot_redis_unavailable_fallback_inprocess` | sampling | llm | Redis 不可用 fail-soft 降级进程内信号量（默认 component=logger 段，绝不阻断 LLM） |

> 留痕（Interaction Ledger，`server/interactions/ledger.py`）写入均为 best-effort，失败只记 `warning`
> 不反噬主流程；写入**内容**（`InteractionRun`/`ToolCallRecord`/`RetrievalTrace`/`ModelUsageRecord`）
> 经 `redact_for_ledger` 脱敏，不出现在事件目录里。

| 事件 | category | component | 说明 |
|------|----------|-----------|------|
| `ledger_event_write_failed` | sampling | interactions | `InteractionRun` 锚点写入失败 |
| `ledger_tool_call_write_failed` | sampling | interactions | `ToolCallRecord` 写入失败 |
| `ledger_retrieval_trace_write_failed` | sampling | interactions | `RetrievalTrace` 召回证据写入失败（MCP + 对话两链） |
| `ledger_model_usage_write_failed` | sampling | interactions | `ModelUsageRecord` 写入失败 |
| `ledger_llm_usage_write_failed` | sampling | interactions | LLM 用量回写失败 |

> 召回（RAG）聚合指标——召回条数 / 分层耗时（embedding/sparse/qdrant/rerank）/ top score——经
> `common.request_metrics.record_request_metric(source="rag", ...)` 写 `RequestMetric` 行（见 §4.2
> `rag_recall_*`），**不**新增 structlog 事件；召回内容走 `RetrievalTrace` 留痕。存量召回事件
> （如 `context_retrieval_completed` / `knowledge_vector_recall_completed`）按缺省 `sampling` 兜底。

### 10.8 快照 / 趋势 / 查询 / 采样 / 保留（Phase 73，component=`metrics`/`metric_sampling`/`metric_retention`）

| 事件 | category | component | 说明 |
|------|----------|-----------|------|
| `metrics_snapshot_served` | caller | metrics | 实时快照端点（CPU/内存/DB/Redis/Qdrant/并发）被超管访问 |
| `metrics_query_served` | caller | metrics | 趋势/分位查询端点被访问（带 `duration_ms` / `degraded`） |
| `snapshot_host_failed` | sampling | metrics | 主机（CPU/内存）快照采集失败（源不可用跳过，不落 0 行） |
| `snapshot_db_failed` | sampling | metrics | 数据库快照采集失败 |
| `snapshot_redis_failed` | sampling | metrics | Redis 快照采集失败 |
| `snapshot_qdrant_failed` | sampling | metrics | Qdrant 快照采集失败 |
| `snapshot_concurrency_failed` | sampling | metrics | LLM 并发/队列 gauge 快照采集失败 |
| `gauge_sampled` | sampling | metric_sampling | 周期 gauge 采样写入 `GaugeSample`（并发/队列/积压；高频内部步骤） |
| `gauge_sample_failed` | sampling | metric_sampling | gauge 采样失败 |
| `gauge_samples_purged` | caller | metric_retention | `GaugeSample` 行按保留策略清理 |
| `request_metrics_purged` | caller | metric_retention | `RequestMetric` 行清理 |
| `model_usage_records_purged` | caller | metric_retention | `ModelUsageRecord` 行清理 |
| `<label>_purge_failed` | caller | metric_retention | 指标行清理失败（`<label>` 为 `gauge_samples`/`request_metrics`/`model_usage_records`） |

### 10.9 告警评估与通知（Phase 74，component=`alerting`/`alert_retention`）

> 告警评估器（`evaluate_system_alerts`）作为 apscheduler 周期作业，经 `_with_scheduler_log_context`
> 绑 `user_id=system` / `source=scheduler`（CTX-02）。评估**周期**高频事件用 `category="sampling"`
> 避免刷屏；firing/resolved 与通知分发为可归因 `category="caller"`（带 `rule_id` / `duration_ms`）。
> 告警规则写操作（API）为可归因调用 `caller`；事件查询为高频轮询 `sampling`。

| 事件 | category | component | 说明 |
|------|----------|-----------|------|
| `alert_rules_listed` | caller | alerting | 告警规则列表查询（超管） |
| `alert_rule_created` | caller | alerting | 创建告警规则 |
| `alert_rule_updated` | caller | alerting | 更新告警规则 |
| `alert_rule_deleted` | caller | alerting | 删除告警规则 |
| `alert_events_queried` | sampling | alerting | 告警事件查询（高频轮询，避免污染调用类统计） |
| `alert_eval_cycle` | sampling | alerting | 一次评估周期完成（带规则数/触发数；高频循环纪律） |
| `alert_eval_failed` | sampling | alerting | 评估周期整体失败（best-effort，不反噬 scheduler） |
| `alert_rule_eval_failed` | sampling | alerting | 单条规则评估失败 |
| `alert_metric_unsupported` | sampling | alerting | 规则引用了不支持的指标 |
| `alert_metric_resolve_failed` | sampling | alerting | 指标取值解析失败 |
| `alert_firing` | caller | alerting | 告警触发（阈值越界，带 `rule_id` / 当前值） |
| `alert_resolved` | caller | alerting | 告警恢复 |
| `alert_notify_dispatch_failed` | caller | alerting | 通知分发整体失败 |
| `alert_notified` | caller | alerting | 通知成功送达（含渠道） |
| `alert_notify_failed` | caller | alerting | 单渠道通知失败 |
| `alert_notify_persist_failed` | caller | alerting | 通知结果回写 `AlertEvent` 失败 |
| `alert_email_failed` | caller | alerting | 邮件渠道发送失败 |
| `alert_feishu_failed` | caller | alerting | 飞书渠道发送失败 |
| `alert_webhook_failed` | caller | alerting | 自定义 webhook 渠道发送失败 |
| `alert_events_purged` | caller | alert_retention | 告警事件按保留策略清理 |
| `alert_events_purge_failed` | caller | alert_retention | 告警事件清理失败 |
