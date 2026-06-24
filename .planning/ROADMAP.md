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

### 🚧 v0.14.0 可观测性与日志治理 (Phases 71–75) — IN PROGRESS

在一个里程碑内完整交付可观测性与日志治理，5 个 Phase 线性推进（71→75），autonomous 一次跑完整个里程碑。第一性原理：量级低、人触发，用"原始事件行 + Postgres `percentile_cont` 聚合 + 复用已有 append-only 表"把自研基础设施压到最小。

- [ ] Phase 71: 可观测性地基——用户上下文贯穿 + 系统日志治理 (0/? plans) — CTX-01, CTX-02, LOG-01~08
- [ ] Phase 72: 调用数据采集——AI/LLM(TPS) + 召回 + 请求入口(QPS/SLA/时长/TTFT/上游错误) (0/? plans) — RATE-01, RATE-02, RAG-01, RAG-02, SLA-02, SLA-03, SLA-04
- [ ] Phase 73: 快照·趋势·查询 API (0/? plans) — SNAP-01~05, RATE-03, SLA-01, QUERY-01, QUERY-02
- [ ] Phase 74: 告警引擎与通知（阈值 + 告警事件 + 邮件） (0/? plans) — ALERT-01, ALERT-02, ALERT-03
- [ ] Phase 75: 运维大盘前端 + 规范固化 (0/? plans) — UI-01~04, SPEC-01

**Success criteria（按阶段）:**

- **Phase 71:** ① 任意 HTTP/MCP/对话/compat 请求日志都带 `user_id`(登录用户或 system)+request_id+source；② 飞书/webhook/durable 后台任务日志能显示发起来源、跨线程正确继承；③ 系统日志落库可按最新倒序查看 + 按组件/级别/用户/来源/关键词/时间段筛选搜索；④ 暴露队列(x/5000)/写入/丢弃/失败四计数，满则丢弃、失败计数且不反噬业务；⑤ 每条日志带 caller/sampling + component；⑥ 运行时改级别/堆栈阈值/采样/保留实时生效；⑦ webhook 原始 payload 脱敏入库可查看；⑧ 日志可按条件清理 + 到期自动清理；⑨ MCP/对话可下钻触发用户与会话原始数据。
- **Phase 72:** ① QPS 按入口分类可采集（REST/MCP/对话/兼容/召回/embedding·reranker/webhook/WS）；② TPS 按 provider 采集，含容器侧 LLM token；③ 召回条数/分层耗时/相关度可采集，召回内容（MCP+对话）可留痕回放；④ 请求错误三口径（系统/业务限制/上游）与上游码（429/529 单列）可采集；⑤ 请求时长与 TTFT 可采集。
- **Phase 73:** ① CPU/内存/DB(连接·活跃·空闲)/Redis(连接·内存)/Qdrant(collection·占用)/协程/后台/并发排队当前值可查；② 并发/排队/吞吐/错误趋势可按时间段查询；③ 可用率按时刻可查；④ 时序查询 API 支持任意时间段与 P95/P90/P50/Avg/Max。
- **Phase 74:** ① 可配置阈值规则（CPU/错误率/TTFT/队列深等）超阈值触发；② 告警事件落库含 P0/P1/P2 + 中文标题/规则 + 持续时长 + firing/resolved + email_sent，同规则去重；③ 触发按级别发邮件并回写 email_sent。
- **Phase 75:** ① 运维大盘出时序图 + 时间范围 + 健康分 + 信息卡（请求/SLA/错误/时长/TTFT/上游 429·529）；② 快照行内联阈值变色 + 吞吐/错误/并发排队趋势；③ 告警事件页 + 系统日志下钻页 + 运行时配置面板可用；④ 规范固化、全量事件目录、PR/Review checklist 落地。

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

里程碑 v0.1.0–v0.13.0（Phases 1–70）均已交付。当前进行：**v0.14.0 可观测性与日志治理（Phases 71–75，5 阶段 / 34 需求，0/5 完成）**。各历史里程碑详情归档在 `.planning/milestones/`，要点见 `MILESTONES.md`。

---
*Previous milestones archived in .planning/milestones/*
