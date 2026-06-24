# 可观测性与日志治理 · 里程碑 v0.14.0（5 个 Phase 一次做完）

**状态:** ✅ 已立项（里程碑 v0.14.0，Phases 71–75）
**时序存储决策:** ✅ 内置 Postgres（不强依赖 Prometheus，后者列 v2 可选导出）
**执行方式:** **单个里程碑 v0.14.0，5 个 Phase（71→75）线性推进**，新开一个会话用 autonomous 一次性跑完整个里程碑。
**Core Value 对齐:** 让自托管团队"看得见、控得住"——运行数据可量化/可回溯/可告警，任何调用都能追到人。

> 配套规范（已落地）：
> - 工程规范：`.planning/observability/LOGGING-SPEC.md`
> - UI 参考借鉴与差异适配：`.planning/observability/REFERENCE-UI.md`（含 LLM 网关平台参考图 + Agent 维度适配）
> - Agent 强制规则：`.cursor/rules/observability-logging.mdc`（alwaysApply）+ `AGENTS.md`/`CLAUDE.md` 挂接

---

## A. 第一性原理评审（方案是否合理 / 优雅 / 好用）

### A.1 先问：这套观测到底为谁、解决什么

Friday AI 是**自托管、人触发**的"需求→PR"系统。请求量级是：**少量管理员 + 若干 IDE/MCP 客户端 + webhook + 工作流触发**——不是十万 QPS 的在线服务。运维真正要回答的只有 5 个问题：

1. 现在健康吗？（快照）
2. AI 调用成不成、花多少钱、有没有撞 provider 限流（429）？（LLM 指标）
3. 有没有东西在堆积（索引风暴、队列积压）？（队列/并发）
4. 出事时发生了什么、谁触发的？（日志 + 归因 + 调用详情）
5. 出问题能不能自动告诉我？（告警）

**真正稀缺/困难的是：provider 配额与成本、上游错误、队列背压、归因**。**不是**高基数高频指标。这条认知决定了架构取舍。

### A.2 由此得到的核心简化（相对上一版方案）

> 上一版我提了"指标门面 + 进程内固定桶直方图聚合器 + 多级 rollup 引擎"。从第一性原理看，**这是过度设计**——那是为高 QPS 服务省存储用的，而我们量级低。

**改为：原始事件行 + SQL 聚合。**

- 量级低 ⇒ 直接落**精简事件行**，用 Postgres `percentile_cont` 算**精确**分位（P50/P90/P95/P99），`date_trunc` 做时间桶。不写自研直方图/聚合器/rollup 引擎。
- **最大化复用已有 append-only 表**：`ModelUsageRecord`(token/成本/上游错误)、`ToolCallRecord`(MCP 时长)、`RetrievalTrace`(召回内容) **本身就是指标与详情的数据源**——只需补字段 + 补全覆盖面，不另造轮子。
- 只新增 3 张轻表：`RequestMetric`（每请求一行：QPS/错误/时长/TTFT/SLA）、`GaugeSample`（周期采样：队列深/并发/积压趋势）、`AlertEvent`（告警事件）；外加 `SystemLogEntry`（日志流落库）、`InboundWebhookEvent`（webhook 原始）。
- 维度放 `labels` jsonb，**加维度不改表**；保留期短（低量级，30–90d）+ 可选每日 rollup 只为长区间趋势。

**收益（更优雅 + 更好用）：** 少写一个易错的聚合引擎；分位是精确值；任意维度 ad-hoc SQL 可查；前端用已就绪的 echarts 出图。

### A.3 其它第一性原理结论（已纳入方案）

- **用户上下文贯穿是地基，必须最先做（Phase 71）**。否则日志/指标都答不出"谁触发的"，后面全是补丁。`structlog.contextvars` + 入口中间件 + 后台任务 job metadata 重新 bind，是最小且自洽的实现。
- **不要硬套现有 `AlertRule`**：它强绑定工作流（`project` 非空、`AlertRuleExecution.workflow_execution` 非空、条件都是 execution_*）。基础设施/指标告警（CPU>95%、错误率、TTFT、队列深）语义不同，**另起系统级告警模型**，只共享通知分发（飞书/webhook/邮件）。强行复用会拧巴、不优雅。
- **指标 vs 留痕 vs 日志三者分清**（避免重复造数据）：
  - 指标 = 聚合用的精简行（`RequestMetric` + 扩展后的 `ModelUsageRecord`）→ 趋势/分位。
  - 留痕 = 富详情（Interaction Ledger：`InteractionRun/ToolCallRecord/RetrievalTrace/ModelUsageRecord`）→ 调用下钻、召回内容回放。
  - 日志 = structlog 事件流（`SystemLogEntry`，队列落库）→ 排障检索。
  - 三者通过 `request_id/run_id/conversation_id` 关联，不互相复制。
- **快照不长存**：CPU/内存/DB/Redis/Qdrant 用户明确"只看当前"——按需采集即可，省一套时序写入。
- **System Log 队列背压**按你的要求显式实现：`deque(maxlen=5000)` + 批量 worker，满则丢弃计数、写库失败计数，两个计数本身作为指标暴露。

### A.4 已识别的坑（方案里已写明缓解）

| 坑 | 缓解 |
|----|------|
| SQLite 本地 dev 无 `percentile_cont` | 降级：dev 用近似/跳过分位，prod 是 Postgres；功能不阻塞 |
| 轮询端点（运维页 4s、健康 30s、索引 SSE）刷高 QPS/污染 SLA | 入口埋点对 health/observability/poll 路由打标隔离，不计入业务 SLA |
| `labels` jsonb 基数失控 | 禁止把用户输入原文当 label；label 取值受控枚举（见 LOGGING-SPEC §4） |
| `RetrievalTrace` 每 chunk 一行可能多 | 召回内容走"详情/留痕"（按需采样），指标只记聚合条数/耗时，不按 chunk 入指标 |
| 原始行无限增长 | 每日定时清理 + 保留策略（LOG-08 同款机制复用到指标表） |
| 凭证泄漏（日志/留痕/webhook 原始） | 强制 `redact_credentials`/`redact_secrets_in_text`/`redact_for_ledger` |

**结论：方案合理且现在更优雅。** 核心是"借力低量级 + 复用已有 append-only 表 + SQL 聚合"，把自研基础设施压到最小，同时完全覆盖你列的所有诉求。

---

## B. 5 个 Phase（里程碑 v0.14.0，线性依赖 71→75）

整个可观测性与日志治理在**一个里程碑 v0.14.0** 内分 5 个 Phase 一次做完，Phase 号续上一里程碑（70）从 **71** 起，autonomous 顺序执行 71→75。

### Phase 71 · 可观测性地基：用户上下文贯穿 + 日志治理

**为什么先做：** 它是所有观测的"地基" —— 让每条日志/调用都能绑定到人，并把日志从"每进程 800 条内存"升级为"可搜索、可清理、可配置的落库日志"。后续 Phase 的指标/告警/大盘都依赖它。

**需求：**

- **CTX-01**: 请求级上下文中间件——每个 HTTP/SSE/WS/MCP/compat 入口把 `user_id`（无则 `system`）、`request_id`、`source`、`trace_id` 绑定到 `structlog.contextvars`，请求结束清理；所有 structlog 事件自动带这些字段。
- **CTX-02**: 后台任务用户传播——durable job / `background_runner` / workflow `_run_in_thread` / apscheduler / 飞书·webhook 触发，入队时序列化 `initiated_by_user_id`，worker 入口重新 bind；无发起人记 `system`。验收：任意日志/调用都能回答"谁触发的"。
- **LOG-01**: 系统日志落库（`SystemLogEntry`），默认时间倒序；支持按组件、级别(debug/info/warn/error)、用户、来源、关键词、时间段筛选与全文搜索。
- **LOG-02**: 队列化写入——内存队列默认上限 5000，后台批量落库；满则丢弃并累计**丢弃数**（按时刻记录），落库失败累计**失败条数**；两个计数作为可观测指标暴露。保留现有 `log_buffer` 作极速兜底。
- **LOG-03**: 日志全量绑定触发用户（依赖 CTX），无触发用户记 `system`，可按用户筛选。
- **LOG-04**: 调用下钻后端——MCP 调用显示来自哪个用户；AI 对话事件关联用户 + 会话，可取该会话全部请求与原始数据（复用 Interaction Ledger / Conversation / Message，提供下钻 API）。
- **LOG-05**: 事件分类与目录——所有已知事件按 `caller`/`sampling` 分类、按组件归类，形成事件目录（LOGGING-SPEC）。
- **LOG-06**: 运行时日志配置（实时生效，复用 `SystemSetting`+signal）——级别（全局/分组件）、堆栈记录阈值、采样初始（首 N 全记）、采样后续（按比例）、保留天数/保留大小。把当前固定的 `_resolve_structlog_level()` 改为可热更新级别。
- **LOG-07**: Webhook 原始数据统一落库可查看（`InboundWebhookEvent` 或激活 `WebhookLog`）——飞书（已具备，纳入统一视图）、通用工作流 webhook、Git push webhook、容器回调，原始 payload 脱敏后入库。
- **LOG-08**: 日志清理——按条件（时间/级别/组件/用户/关键词）批量清理；保留策略到期定时自动清理（apscheduler）。

**关键产物：** contextvars 中间件 + 后台任务 user 传播契约 + `SystemLogEntry`/`InboundWebhookEvent` 模型 + 队列 worker + 运行时配置 + 日志/下钻/清理 API。

---

### Phase 72 · 调用数据采集：AI/LLM + 召回 + 请求入口

**为什么第二：** 地基就绪后，把所有"能成时序"的数据采集到事件表。本 Phase 只**写数据**，查询/出图在 Phase 73。

**需求：**

- **RATE-01**: QPS 分类采集——`RequestMetric`（每请求一行：ts/source/route/method/status_class/duration_ms/user_id）覆盖所有入口：REST、MCP 工具、对话 SSE、OpenAI/Anthropic 兼容、召回、embedding/reranker、各类 webhook、WS 连接；轮询/health 路由打标隔离。
- **RATE-02**: TPS 采集（全量，不漏容器）——扩展 `ModelUsageRecord` 补 `call_source`/`ttft_ms`/`upstream_status_code`，确保**所有 LLM 调用点**（22 类 `call_source`，见 LOGGING-SPEC §4.1）写入 input/output/cache token，按 provider 区分。**含容器侧**：`workflow_coding_container`/`repo_summary_container`/`deep_analysis_container`/`sdk_agent_task` 当前 `task` 写了 `usage.json` 但 server 侧读取/回调链不完整——本里程碑补全 `task` → 容器回调 → `subagent.TokenUsage`/`ModelUsageRecord` 链路，使容器 LLM 的 token/TTFT 也纳入 TPS 统计。
- **RAG-01**: 召回指标采集——召回条数、总耗时及分层耗时（embedding/sparse/qdrant/rerank）、相关度 score 分布；按来源（MCP/对话/workflow）打标。埋点位 `search_rag` 出口 + `QdrantService.search/hybrid_search` + `EmbeddingService` + `recall_similar_chunks`。
- **RAG-02**: 召回内容留痕扩展到 MCP + AI 对话两条主链——`RetrievalTrace` 记 query 原文 + 召回 chunk 内容 + score + 会话/用户；chat/workflow 代码 RAG 透传 user_id。
- **SLA-02**: 请求错误采集（三口径分离）——错误必须区分 ①**系统错误**（5xx/异常，计入 SLA 故障）②**业务限制**（非故障的按规则拒绝：`LLMBusyError` 系统繁忙/并发限流、权限拒绝、输入校验失败——**排除在 SLA 故障外**）③**上游错误**（见 SLA-03）。`RequestMetric` 记 `error_class(system/business/upstream)` + `status_code`，支撑每时刻错误率（按入口/口径/状态码）。
- **SLA-03**: 上游（provider）错误采集——`ModelUsageRecord.upstream_status_code`/`failure_type` 记录上游码与类型，**429/529 单独成列**，其余上游码另计；按 provider/model 区分。
- **SLA-04**: 时长与 TTFT 采集——`RequestMetric.duration_ms` + LLM `ttft_ms`（流式入口埋首 chunk 计时）。

**关键产物：** `RequestMetric` 模型 + 统一入口埋点（DRF 基类/ASGI + MCP `_record` + chat SSE wrap + compat + webhook + WS）+ `acquire_llm_slot`/两个 Runner 流式循环埋点 + 召回链路埋点 + Ledger 覆盖扩展。

---

### Phase 73 · 快照、趋势与查询 API

**为什么第三：** 把 Phase 72 采集的数据变成"可按任意时间段查询 + 出趋势"，并补齐"只看当前"的快照。

**需求：**

- **SNAP-01**: server/主机快照——CPU、内存（接入 psutil）、协程数（asyncio tasks）、线程数、后台任务数（durable active / `background_runner` in-flight / workflow 线程 / edge build）。
- **SNAP-02**: 数据库快照——连接数、活跃/空闲/等待（`pg_stat_activity` + `max_connections`；psycopg pool `get_stats()`；PgBouncer 模式 `SHOW POOLS`）。
- **SNAP-03**: Redis 快照——连接数（`connected_clients`/`maxclients`）、内存占用、命中率（`INFO`），覆盖 cache/channels/llm 多路客户端。
- **SNAP-04**: Qdrant 快照——可用性、collection 数、占用空间（带缓存 + 长超时，避免拖垮）。
- **SNAP-05**: 并发/排队当前值——各 provider 凭证当前占用槽位、各 durable 队列 todo/doing、runner 待派发与本地队列、RAG 并发。
- **RATE-03**: 趋势（只记不告警）——`GaugeSample` 周期采样（apscheduler，30–60s）记并发/队列深/积压；吞吐(各 provider QPS/TPS，单位 K)/错误趋势由 Phase 72 事件表 SQL 聚合。
- **SLA-01**: 每时刻可用率/业务故障率——由 `RequestMetric` 成功/失败比派生，**口径为"排除业务限制"**（系统繁忙限流/权限/校验不算故障）+ 健康探针，按入口/时间段查询。
- **QUERY-01**: 时序查询 API——`GET /api/system/metrics/query`，按任意时间段/step/维度查询 QPS/TPS/SLA/错误/时长 TTFT 分位（`percentile_cont`）；含保留清理 + 可选每日 rollup。
- **QUERY-02**: 快照 API——`GET /api/system/metrics/snapshot` 聚合返回 SNAP-01~05 当前值。

**关键产物：** 快照采集器（psutil/pg_stat_activity/redis INFO/qdrant）+ `GaugeSample` 周期任务 + 时序查询/快照 API + 保留清理任务。

---

### Phase 74 · 告警引擎与通知

**为什么第四：** 数据可查后才能评估阈值告警。新建**系统级**告警（不套 workflow `AlertRule`），共享通知分发。

**需求：**

- **ALERT-01**: 系统告警阈值规则（新模型，独立于 workflow `AlertRule`）——可为 QPS/错误率/TTFT/CPU/内存/DB/Redis/Qdrant/队列深等配置阈值（运行时可改，`SystemSetting`/专表），超出触发；趋势类（RATE-03）默认不参与。
- **ALERT-02**: 告警事件落库（`AlertEvent`）——级别 P0/P1/P2、中文标题、机器可读规则信息（参考格式：`cpu_usage_percent > 85.00 (current 95.40) over last 5m (overall)`，含规则·当前值·窗口·维度）、规则ID、开始/结束时间与持续时长（如 1h）、状态 firing/resolved、邮件状态（已发送/已忽略/—）；同规则同对象去重（一条 firing，恢复时收尾）。告警事件表列对齐参考：时间/级别/状态/维度/规则ID/标题+规则信息/持续时间/邮件状态（见 REFERENCE-UI §1.4）。
- **ALERT-03**: 邮件通道——接入 Django SMTP（`EMAIL_*` + `SystemSetting` 收件人/开关），按级别发邮件并回写 `email_sent`；复用现有飞书/webhook 通知分发，三通道并存。

**关键产物：** 系统告警规则模型 + 周期评估器（查 Phase 73 时序 + 快照）+ `AlertEvent`（含去重/持续时长/恢复）+ SMTP 邮件 + 通知分发集成。

---

### Phase 75 · 运维大盘前端 + 规范固化

**为什么最后：** 所有后端 API 就绪后做统一大盘，并把规范固化为长期约束。

**需求：**

> UI 布局借鉴 `REFERENCE-UI.md`（含两张参考图）的卡片范式，但按 Agent 平台维度重构（`call_source`/会话/工作流/召回/容器），不照抄请求中心架构。

- **UI-01**: 大盘上半区——复合健康分（0–100 圆环）+ 实时速率卡（1min/5min/30min/1h tab，当前/峰值/平均 QPS·TPS + sparkline）+ 信息卡排（请求 / SLA(排除业务限制) / 请求错误(系统·业务限制分列) / 请求时长 P99+分位 / TTFT P99+分位 / 上游错误(429·529 单列)）；时间范围选择器（5m/1h/24h/自定义）。
- **UI-02**: 当前快照行 + 趋势——CPU/内存/DB(连接·活跃·空闲)/Redis(连接 x/maxclients)/Qdrant/协程/后台任务，**卡内内联告警阈值**超阈值变色；吞吐趋势（各 provider QPS+TPS 千，可切 call_source）、错误趋势（系统/上游/业务限制 三口径）、请求时长分布、并发/排队（provider + 索引/AI描述/异步）。
- **UI-03**: 告警事件页——表列对齐 REFERENCE-UI §1.4（时间/级别 P0-P2/状态 firing·resolved/维度/规则ID/标题+规则信息/持续时长/邮件状态）+ 多维筛选；阈值规则配置入口。
- **UI-04**: 系统日志页——顶部计数（队列 x/5000 · 写入 · 丢弃 · 失败）+ 倒序列表 + 多维筛选（级别/组件/user_id/source/call_source/provider/credential/model/关联键/关键词）+ 调用下钻（会话全部请求·原始数据/召回内容/webhook 原始）+ 按当前筛选清理 + 运行时日志配置表单（级别/堆栈阈值/采样初始/采样后续/保留天数·大小 + caller·sampling + 保存并生效/回滚默认）。
- **SPEC-01**: 规范固化——`LOGGING-SPEC.md` + cursor 规则 + AGENTS/CLAUDE 挂接复核；全量事件目录补全；PR/Code Review checklist 落地，后续任何功能必须按规范补埋点。

**关键产物：** 重构 `web/src/pages/admin/observability/` + 新日志/告警页 + 规范复核与覆盖核查。

---

## C. 数据模型总览（新增/扩展）

| 模型 | Phase | 用途 | 关键字段 |
|------|-------|------|----------|
| `SystemLogEntry`（新） | 71 | 日志流落库 | `ts, level, component, category(caller/sampling), event, message, user_id(→system), source, trace_id, request_id, payload(jsonb,脱敏), correlation` |
| `InboundWebhookEvent`（新/激活 WebhookLog） | 71 | webhook 原始 | `received_at, kind, source_ip, headers(jsonb), raw_body, user_id, verified, correlation` |
| `RequestMetric`（新，精简行） | 72 | QPS/错误/时长/SLA | `ts, source, route, method, status_code, error_class(system/business/upstream/none), duration_ms, ttft_ms, user_id, labels(jsonb: call_source/provider/credential/model/关联键)` |
| `ModelUsageRecord`（扩展） | 72 | TPS/上游错误/成本 | 补 `call_source, ttft_ms, upstream_status_code` |
| `RetrievalTrace`（扩展覆盖面） | 72 | 召回内容 | chat/workflow 也写、透传 user |
| `GaugeSample`（新，周期采样） | 73 | 并发/队列/积压趋势 | `ts, name, value, labels(jsonb)` |
| `MetricDailyRollup`（新，可选） | 73 | 长区间趋势 | 每日聚合，按需 |
| `SystemAlertRule`（新） | 74 | 系统告警阈值 | `metric, op, value, window, severity, enabled, channels, cooldown` |
| `AlertEvent`（新） | 74 | 告警事件 | `severity(P0/P1/P2), title_zh, rule_info, target, started_at, ended_at, duration_s, status, email_sent, notified_channels` |

> 复用不新建：`InteractionRun`/`InteractionEvent`/`ToolCallRecord`（MCP 详情/时长）、`Conversation`/`Message`（会话原始）、`SystemSetting`/`settings_service`（运行时配置）、`TriggerLog`（飞书 webhook 原始范本）。

---

## D. Traceability（需求 → Phase）

| Phase | 需求 |
|-------|------|
| 71 可观测性地基 | CTX-01, CTX-02, LOG-01, LOG-02, LOG-03, LOG-04, LOG-05, LOG-06, LOG-07, LOG-08 |
| 72 调用数据采集 | RATE-01, RATE-02, RAG-01, RAG-02, SLA-02, SLA-03, SLA-04 |
| 73 快照·趋势·查询 | SNAP-01, SNAP-02, SNAP-03, SNAP-04, SNAP-05, RATE-03, SLA-01, QUERY-01, QUERY-02 |
| 74 告警引擎与通知 | ALERT-01, ALERT-02, ALERT-03 |
| 75 运维大盘 + 规范固化 | UI-01, UI-02, UI-03, UI-04, SPEC-01 |

**统计:** 34 条 v1 需求，分布里程碑 v0.14.0 的 5 个 Phase，无悬空。依赖链：71→72→73→74→75（线性，autonomous 一次跑完整个里程碑）。

---

## E. v2（后续里程碑，本里程碑不做）

| ID | 内容 | 理由 |
|----|------|------|
| OBSX-01 | Prometheus / OTLP 导出 + 外部 Grafana | 内置足够；外部栈可选增强 |
| ~~OBSX-02~~ | ~~容器内 LLM token/TTFT 上报~~ → **已纳入 Phase 72 RATE-02**（TPS 要全量，不能漏容器） | — |
| OBSX-03 | 跨 server↔runner↔task 分布式 tracing | 体量大 |
| OBSX-04 | 告警自适应/降噪/值班排班 | 先静态阈值 + 去重 |
| OBSX-05 | Sentry 接入（已预留 `sentry_before_send`） | 可选 |
| OBSX-06 | 日志冷存储/ELK·Loki 导出 | 落库 + 保留先满足 |

## F. Out of Scope（明确不做）

| 项 | 理由 |
|----|------|
| 强依赖 Prometheus/Grafana/ELK | 违背自托管开箱即用；内置 + echarts 满足核心 |
| 自研进程内直方图聚合器 + 多级 rollup 引擎 | 量级低，原始行 + `percentile_cont` 更优雅且精确（见 A.2） |
| 硬套 workflow `AlertRule` 做基础设施告警 | 语义/约束不符（强绑 workflow），另起系统级告警（见 A.3） |
| 把 CPU/DB/Redis/Qdrant 做成长时序 | 用户明确"只看当前"，按需采集 |
| 容器内 LLM 计费链路超出 token/TTFT 采集的部分 | 仅做可观测采集，不做扣费/配额 |

---

## G. 执行建议

1. 里程碑 v0.14.0 已立项（PROJECT/REQUIREMENTS/ROADMAP/STATE 就绪），5 个 Phase 71–75。
2. 新开一个会话 `/gsd-autonomous` 一次性跑完整个里程碑，顺序 71→72→73→74→75（有依赖，勿乱序）；或手动 `/gsd-plan-phase 71` 起步。
3. 规范文件已在仓库，执行时受 `.cursor/rules/observability-logging.mdc` 约束自动补埋点。
