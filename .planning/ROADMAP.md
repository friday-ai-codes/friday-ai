# Roadmap: Friday AI

## Milestones

- 🚧 **v0.14.0 可观测性与日志治理** — Phases 71–75 (in progress) — 一个里程碑完整交付（用户上下文/日志/QPS·TPS·召回·SLA·快照·趋势/告警/大盘）；完整方案见 [proposal](./observability/MILESTONE-PROPOSAL.md)、规范见 [logging-spec](./observability/LOGGING-SPEC.md)
- ✅ **v0.13.0 并发治理与索引体验** — Phases 65–70 (shipped 2026-06-23) — 里程碑审计 tech_debt（11/11 需求满足、integration_ok；遗留既有前端测试失败 + URL 拆段拼接 UI + 真机人工验收）见 [audit](./milestones/v0.13.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.13.0-ROADMAP.md)
- ✅ **v0.12.0 弹性任务底座（durable 任务队列与多副本就绪）** — Phases 60–64 (shipped 2026-06-20) — 里程碑审计 tech_debt（16/16 需求满足、integration_ok；遗留真机/真实平台运行期人工验收）见 [audit](./milestones/v0.12.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.12.0-ROADMAP.md)
- ✅ **v0.11.0 开放与协作** — Phases 56–59 (shipped 2026-06-17) — 里程碑审计 PASS（6/6 需求、INV-5/INV-6 成立）见 [audit](./milestones/v0.11.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.11.0-ROADMAP.md)
- ✅ **v0.10.0 操作审计治理** — Phases 53–55 (shipped 2026-06-17) — [archive](./milestones/v0.10.0-ROADMAP.md)
- ✅ **v0.9.0 SDD / OpenSpec 支持（重型）** — Phases 48–52 (shipped 2026-06-17) — [archive](./milestones/v0.9.0-ROADMAP.md)
- ✅ **v0.8.0 多仓串行编码 → 融合 PR** — Phases 43–47 (shipped 2026-06-17) — [archive](./milestones/v0.8.0-ROADMAP.md)
- ✅ **v0.7.0 方案编排（需求 → 主方案）** — Phases 36–42 (shipped 2026-06-16) — [archive](./milestones/v0.7.0-ROADMAP.md)
- ✅ **v0.6.0 领域脊柱 + 知识图谱补全** — Phases 27–35 (shipped 2026-06-15) — [archive](./milestones/v0.6.0-ROADMAP.md)
- ✅ **v0.5.0 索引检索地基与排除文件** — Phases 22–26 (shipped 2026-06-15) — [archive](./milestones/v0.5.0-ROADMAP.md)
- ✅ **v0.4.0 工作流系统契约重构** — Phases 17–21 (shipped 2026-06-13) — [archive](./milestones/v0.4.0-ROADMAP.md)
- ✅ **v0.3.0 交付知识图谱** — Phases 12–16 (shipped 2026-06-12) — [archive](./milestones/v0.3.0-ROADMAP.md)
- ✅ **v0.2.0 用户身份令牌与 Agent 工具打通** — Phases 6–11 (shipped 2026-06-10) — [archive](./milestones/v0.2.0-ROADMAP.md)
- ✅ **v0.1.0 首启初始化向导** — Phases 1–5 (shipped 2026-06-09) — [archive](./milestones/v0.1.0-ROADMAP.md)

> 历史里程碑详情归档在 `.planning/milestones/`，要点见 `MILESTONES.md`。本里程碑完整方案与排查结论见 `.cursor/plans/并发治理与索引体验改造_d5edeece.plan.md`。

## Phases

### 🚧 v0.14.0 可观测性与日志治理 (Phases 71–75 — IN PROGRESS)

**Milestone Goal:** 在一个里程碑内完整交付可观测性与日志治理，5 个 Phase 线性推进（71→75），autonomous 一次跑完整个里程碑：用户上下文贯穿 + 系统日志队列化落库 + QPS/TPS/召回/SLA/时长/TTFT 时序指标 + CPU/内存/DB/Redis/Qdrant 当前快照 + 并发/排队/吞吐/错误趋势 + 阈值告警与告警事件（P0/P1/P2，邮件）+ 运维大盘。第一性原理：量级低、人触发，用"原始事件行 + Postgres `percentile_cont` 聚合 + 复用已有 append-only 表"把自研基础设施压到最小。

- [x] **Phase 71: 可观测性地基（用户上下文贯穿 + 系统日志治理）** (5/5 plans) — CTX-01, CTX-02, LOG-01~08 — completed 2026-06-24（verification 8/8 passed） — **planned: 5 plans / 3 waves**
- [x] **Phase 72: 调用数据采集（AI/LLM + 召回 + 请求入口）** (4/4 plans) — RATE-01, RATE-02, RAG-01, RAG-02, SLA-02, SLA-03, SLA-04 — completed 2026-06-24（verification 6/6 passed）
- [ ] **Phase 73: 快照·趋势·查询 API** - CPU/内存/DB/Redis/Qdrant/协程/后台/并发排队当前快照 + GaugeSample 趋势采样 + 可用率 + 时序/快照查询 API(percentile_cont 分位) — SNAP-01, SNAP-02, SNAP-03, SNAP-04, SNAP-05, RATE-03, SLA-01, QUERY-01, QUERY-02
- [ ] **Phase 74: 告警引擎与通知（阈值 + 告警事件 + 邮件）** - 系统级阈值告警规则 + AlertEvent(P0/P1/P2/持续时长/firing-resolved/email_sent/去重) + SMTP 邮件 + 复用飞书/webhook — ALERT-01, ALERT-02, ALERT-03
- [ ] **Phase 75: 运维大盘前端 + 规范固化** - echarts 大盘(健康分/实时速率/信息卡/趋势/快照) + 告警事件页 + 系统日志下钻页 + 运行时配置面板 + 规范固化与 PR/Review checklist — UI-01, UI-02, UI-03, UI-04, SPEC-01

## Phase Details

### Phase 71: 可观测性地基（用户上下文贯穿 + 系统日志治理）

**Goal**: 建立可观测性地基——让每次调用都能绑定到触发用户（无则 system），并把系统日志从"每进程 800 条内存环形缓冲"升级为"队列化落库、可搜索、可按条件清理、可运行时配置"的日志中心，统一 webhook 原始留痕与调用下钻。后续 Phase 的指标/告警/大盘都依赖它。
**Depends on**: Nothing（地基；为 72–75 提供用户归因与日志载体）
**Requirements**: CTX-01, CTX-02, LOG-01, LOG-02, LOG-03, LOG-04, LOG-05, LOG-06, LOG-07, LOG-08
**Success Criteria** (what must be TRUE):

  1. 任意 HTTP/MCP/对话/compat 请求产生的日志都带 `user_id`（登录用户或 `system`）+ `request_id` + `source`；飞书/webhook/durable 后台任务日志能显示发起来源，跨线程/durable worker 正确继承
  2. 系统日志落库（`SystemLogEntry`）可按最新时间倒序查看，并按组件/级别(debug·info·warn·error)/用户/来源/关键词/时间段筛选与全文搜索
  3. 队列化写入（上限 5000）+ 批量落库；暴露队列(x/5000)/写入/丢弃/失败四计数，队列满丢弃且丢弃计数递增、落库失败计失败条数，均不反噬业务
  4. 每条日志带 `category`(caller/sampling) + `component`；形成事件目录（`LOGGING-SPEC.md`）
  5. 运行时改日志级别(全局/分组件)/堆栈阈值/采样初始·后续/保留天数·大小，实时生效无需重启
  6. 飞书/通用 webhook/Git push/容器回调原始 payload 脱敏后入库可查看；MCP 调用可见触发用户，AI 对话可下钻到会话全部请求与原始数据
  7. 日志可按条件（时间/级别/组件/用户/关键词）批量清理 + 保留策略到期定时自动清理
  8. 凭证脱敏不破（`redact_credentials`/`redact_secrets_in_text`/`redact_for_ledger`，CI 守护通过）

**Plans**: 5 plans（3 waves）
- [ ] 71-01-PLAN.md — 用户上下文贯穿：请求级 contextvars 中间件 + DRF 补绑 mixin + 后台任务用户传播（CTX-01/02）[wave 1]
- [ ] 71-02-PLAN.md — SystemLogEntry + InboundWebhookEvent 模型 + 队列化批量落库 worker（四计数）+ enqueue processor（LOG-01/02）[wave 1]
- [ ] 71-03-PLAN.md — 运行时日志配置热更新（SettingKeys.LOG_*）+ category/component 分类与采样 + 事件目录补全（LOG-05/06）[wave 2]
- [ ] 71-04-PLAN.md — 日志查询/筛选/全文 + 四计数 API + 按条件清理 + 保留策略定时清理（LOG-01/03/08）[wave 2]
- [ ] 71-05-PLAN.md — webhook 原始留痕统一（InboundWebhookEvent + 飞书双写）+ 调用下钻 API（MCP/对话）（LOG-04/07）[wave 3]

**UI hint**: maybe（可在现有运维页做最小日志查看/配置触面，完整大盘在 Phase 75）

### Phase 72: 调用数据采集（AI/LLM + 召回 + 请求入口）

**Goal**: 把所有"能成时序"的调用数据采集到精简事件表——QPS/TPS/召回/请求错误三口径/上游错误码/时长/TTFT。本 Phase 只写数据，查询/出图在 Phase 73。
**Depends on**: Phase 71（用户上下文贯穿——指标/留痕需绑定 user 与 source）
**Requirements**: RATE-01, RATE-02, RAG-01, RAG-02, SLA-02, SLA-03, SLA-04
**Success Criteria** (what must be TRUE):

  1. QPS 按入口分类可采集（`RequestMetric` 每请求一行）：REST/MCP/对话 SSE/OpenAI·Anthropic 兼容/召回/embedding·reranker/各类 webhook/WS；轮询·health 路由打标隔离不污染业务统计
  2. TPS 按 provider 采集（扩展 `ModelUsageRecord` 的 `call_source`/`ttft_ms`/`upstream_status_code`），22 类 call_source 写入 input/output/cache token；**含容器侧** token（补全 task→回调→ModelUsageRecord 链路）
  3. 召回条数、分层耗时(embedding/sparse/qdrant/rerank)、相关度 score 可采集，按来源(MCP/对话/workflow)区分
  4. 召回内容留痕扩展到 MCP + AI 对话两条链（`RetrievalTrace` 记 query 原文+chunk 内容+score+会话/用户）
  5. 请求错误三口径分离（系统错误/业务限制如 LLMBusyError/上游错误）+ 上游码采集（429/529 单列）
  6. 请求时长与 TTFT 可采集（流式入口埋首 chunk 计时）

**Plans**: TBD（plan-phase 拆分）

### Phase 73: 快照·趋势·查询 API

**Goal**: 把 Phase 72 采集的数据变成"可按任意时间段查询 + 出趋势"，并补齐"只看当前"的快照与查询 API。
**Depends on**: Phase 72（时序查询依赖采集的事件数据）
**Requirements**: SNAP-01, SNAP-02, SNAP-03, SNAP-04, SNAP-05, RATE-03, SLA-01, QUERY-01, QUERY-02
**Success Criteria** (what must be TRUE):

  1. server/主机快照：CPU、内存(psutil)、协程数、线程数、后台任务数当前值可查
  2. DB(连接·活跃·空闲·max_connections)、Redis(连接·maxclients·内存·命中率)、Qdrant(可用性·collection 数·占用空间，带缓存+长超时)当前值可查
  3. 并发/排队当前值：provider 凭证槽位、durable 队列 todo/doing、runner 待派发/本地队列、RAG 并发
  4. 趋势（只记不告警）：`GaugeSample` 周期采样并发/排队/积压；吞吐(各 provider QPS·TPS 千)/错误趋势可按时间段查询
  5. 每时刻可用率/业务故障率可查（口径"排除业务限制"）
  6. 时序查询 API 支持任意时间段/step/维度 + P95/P90/P50/Avg/Max（`percentile_cont`）；快照 API 聚合返回当前值

**Plans**: TBD（plan-phase 拆分）

### Phase 74: 告警引擎与通知（阈值 + 告警事件 + 邮件）

**Goal**: 数据可查后评估阈值告警——新建系统级告警（不套 workflow `AlertRule`），沉淀告警事件并按级别通知，共享飞书/webhook/邮件分发。
**Depends on**: Phase 73（告警评估依赖时序查询与快照）
**Requirements**: ALERT-01, ALERT-02, ALERT-03
**Success Criteria** (what must be TRUE):

  1. 可为 QPS/错误率/TTFT/CPU/内存/DB/Redis/Qdrant/队列深等配置阈值规则（运行时可改），超阈值触发；趋势类(RATE-03)默认不参与
  2. 告警事件落库（`AlertEvent`）含级别 P0/P1/P2、中文标题、机器可读规则信息(规则·当前值·窗口·维度)、开始/结束与持续时长、状态 firing/resolved、邮件状态；同规则同对象去重(一条 firing，恢复收尾)
  3. 邮件通道接入（Django SMTP + `SystemSetting` 收件人/开关），按级别发邮件并回写 `email_sent`；复用飞书/webhook 三通道并存

**Plans**: TBD（plan-phase 拆分）

### Phase 75: 运维大盘前端 + 规范固化

**Goal**: 后端 API 就绪后做统一运维大盘（借鉴 `REFERENCE-UI.md` 卡片范式但按 Agent 维度重构），并把日志/埋点规范固化为长期约束。
**Depends on**: Phase 71, Phase 72, Phase 73, Phase 74（消费全部后端能力）
**Requirements**: UI-01, UI-02, UI-03, UI-04, SPEC-01
**Success Criteria** (what must be TRUE):

  1. 大盘上半区：复合健康分 + 实时速率卡(窗口 tab + 当前/峰值/平均 QPS·TPS + sparkline) + 信息卡排(请求/SLA 排除业务限制/请求错误系统·业务限制分列/请求时长 P99+分位/TTFT P99+分位/上游错误 429·529 单列) + 时间范围选择器
  2. 当前快照行(CPU/内存/DB/Redis/Qdrant/协程/后台)卡内内联阈值超阈变色 + 吞吐(各 provider QPS+TPS 千)/错误(三口径)/请求时长分布/并发·排队趋势
  3. 告警事件页(时间/级别/状态/维度/规则ID/标题+规则信息/持续时长/邮件状态)+多维筛选 + 阈值规则配置入口
  4. 系统日志页：顶部计数(队列 x/5000·写入·丢弃·失败)+倒序+多维筛选(级别/组件/user_id/source/call_source/provider/credential/model/关联键/关键词)+调用下钻(会话原始/召回内容/webhook 原始)+按筛选清理 + 运行时日志配置表单
  5. 规范固化：`LOGGING-SPEC.md`+cursor 规则+AGENTS/CLAUDE 复核，全量事件目录补全，PR/Code Review checklist 落地

**Plans**: TBD（plan-phase 拆分）

**UI hint**: yes

完整需求见 [REQUIREMENTS.md](./REQUIREMENTS.md)；方案与约束见 [observability/MILESTONE-PROPOSAL.md](./observability/MILESTONE-PROPOSAL.md) 与 STATE.md「关键约束」。

<details>
<summary>✅ v0.13.0 并发治理与索引体验 (Phases 65–70) — SHIPPED 2026-06-23 — 审计 tech_debt</summary>

- [x] Phase 65: AI 对话串流隔离修复 (1/1 plans) — STREAM-01 — completed 2026-06-23
- [x] Phase 66: 默认禁用 LSP（仅 tree-sitter） (1/1 plans) — LSP-01 — completed 2026-06-23
- [x] Phase 67: 并发治理（槽位锁池 / provider 限流 / 容器上限） (3/3 plans) — CONC-01/02/03 — completed 2026-06-23
- [x] Phase 68: 实时进度统一 + 进度条修复 (1/1 plans) — PROG-01/02 — completed 2026-06-23
- [x] Phase 69: 批量加仓 + 全部更新索引（超管） (1/1 plans) — BATCH-01/02 — completed 2026-06-23
- [x] Phase 70: access token / 密钥提供方重构（FK） (1/1 plans) — TOKEN-01/02 — completed 2026-06-23

完整阶段详情见 [milestones/v0.13.0-ROADMAP.md](./milestones/v0.13.0-ROADMAP.md)；里程碑审计 tech_debt（11/11 需求、integration_ok）见 [milestones/v0.13.0-MILESTONE-AUDIT.md](./milestones/v0.13.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.12.0 弹性任务底座（durable 任务队列与多副本就绪）(Phases 60–64) — SHIPPED 2026-06-20</summary>

- [x] Phase 60: durable 底座地基 (4/4 plans) — DURABLE-01~04 — completed 2026-06-19
- [x] Phase 61: 迁移 index/graph + 收口 ResumableTask (4/4 plans) — MIGRATE-01/02, IDEMP-01 — completed 2026-06-19
- [x] Phase 62: 爬取+入库 durable 队列 + PageIndex 接入 (3/3 plans) — CRAWL-01/02, PAGEIDX-01 — completed 2026-06-20
- [x] Phase 63: 部署硬化 + 外部副作用 fencing (3/3 plans) — DEPLOY-01~03, IDEMP-02 — completed 2026-06-20
- [x] Phase 64: runner k8s Job executor (2/2 plans) — RUNNER-01/02 — completed 2026-06-20

完整阶段详情见 [milestones/v0.12.0-ROADMAP.md](./milestones/v0.12.0-ROADMAP.md)；里程碑审计 tech_debt（16/16 需求、integration_ok）见 [milestones/v0.12.0-MILESTONE-AUDIT.md](./milestones/v0.12.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.11.0 开放与协作 (Phases 56–59) — SHIPPED 2026-06-17 — 审计 PASS</summary>

- [x] Phase 56: compat 内部工具调用 → progress/trace 事件透出 (2/2 plans) — TRACE-01, TRACE-02 — completed 2026-06-17
- [x] Phase 57: Anthropic 兼容端点 `/v1/messages` (2/2 plans) — ANTHROPIC-01, ANTHROPIC-02 — completed 2026-06-17
- [x] Phase 58: 飞书原生流式卡片（CardKit）(2/2 plans) — CARD-01 — completed 2026-06-17
- [x] Phase 59: 工作流自动建群节点 (2/2 plans) — GROUP-01 — completed 2026-06-17

里程碑审计 PASS（6/6 需求、INV-5/INV-6 成立）见 [milestones/v0.11.0-MILESTONE-AUDIT.md](./milestones/v0.11.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.10.0 操作审计治理 (Phases 53–55) — SHIPPED 2026-06-17</summary>

完整阶段详情见 [milestones/v0.10.0-ROADMAP.md](./milestones/v0.10.0-ROADMAP.md)。

</details>

<details>
<summary>✅ v0.9.0 SDD / OpenSpec 支持（重型）(Phases 48–52) — SHIPPED 2026-06-17</summary>

完整阶段详情见 [milestones/v0.9.0-ROADMAP.md](./milestones/v0.9.0-ROADMAP.md)。

</details>

<details>
<summary>✅ v0.8.0 多仓串行编码 → 融合 PR (Phases 43–47) — SHIPPED 2026-06-17</summary>

完整阶段详情见 [milestones/v0.8.0-ROADMAP.md](./milestones/v0.8.0-ROADMAP.md)。

</details>

<details>
<summary>✅ v0.7.0 方案编排（需求 → 主方案）(Phases 36–42) — SHIPPED 2026-06-16</summary>

完整阶段详情见 [milestones/v0.7.0-ROADMAP.md](./milestones/v0.7.0-ROADMAP.md)。

</details>

<details>
<summary>✅ v0.6.0 领域脊柱 + 知识图谱补全 (Phases 27–35) — SHIPPED 2026-06-15</summary>

完整阶段详情见 [milestones/v0.6.0-ROADMAP.md](./milestones/v0.6.0-ROADMAP.md)。

</details>

## Progress

里程碑 v0.1.0–v0.13.0（Phases 1–70）均已交付。当前进行：**v0.14.0 可观测性与日志治理（Phases 71–75，5 阶段 / 34 需求，2/5 完成）**。各历史里程碑详情归档在 `.planning/milestones/`，要点见 `MILESTONES.md`。

---
*Previous milestones archived in .planning/milestones/*
