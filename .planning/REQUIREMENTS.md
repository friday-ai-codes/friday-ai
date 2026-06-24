# Requirements: Friday AI

**Defined:** 2026-06-24
**Core Value:** 让团队"开箱即用、安全地"把需求自动变成代码——并且全链路"看得见、控得住、可归因"。v0.14.0 是「可观测性与日志治理」5 里程碑计划（v0.14.0–v0.18.0）的第一站：建立可观测性地基。

> 完整 5 里程碑方案见 `.planning/observability/MILESTONE-PROPOSAL.md`；日志/埋点规范见 `.planning/observability/LOGGING-SPEC.md`；UI 参考见 `.planning/observability/REFERENCE-UI.md`。

## v1 Requirements

Milestone v0.14.0 可观测性地基（用户上下文贯穿 + 日志治理）。每条映射到一个 roadmap 阶段（见 Traceability）。

### 用户上下文贯穿（CTX）

- [ ] **CTX-01**: 请求级上下文中间件——每个 HTTP/SSE/WS/MCP/compat 入口自动把 `user_id`（无则 `system`）、`request_id`、`source`、`trace_id` 绑定到 `structlog.contextvars`，请求结束清理；所有 structlog 事件自动携带这些字段，业务代码无需手动传
- [ ] **CTX-02**: 后台任务用户传播——durable job / `background_runner` / workflow `_run_in_thread` / apscheduler / 飞书·webhook 触发，入队时携带 `initiated_by_user_id`，worker 入口重新 bind 到 contextvars；跨线程/durable worker 正确继承发起用户；无发起人记 `system`

### 系统日志落库（LOG）

- [ ] **LOG-01**: 系统日志落库（`SystemLogEntry`），默认按时间倒序，支持按组件、级别（debug/info/warn/error）、用户、来源、关键词、时间段筛选与全文搜索
- [ ] **LOG-02**: 队列化写入——内存队列默认上限 5000，后台批量落库；队列满则丢弃并累计丢弃数（按时刻记录），落库失败累计失败条数；两个计数作为可观测指标暴露，且均不影响主流程
- [ ] **LOG-03**: 日志全量绑定触发用户（依赖 CTX-01/02），无触发用户记 `system`，可按用户筛选
- [ ] **LOG-04**: 调用下钻后端——MCP 调用显示来自哪个用户；AI 对话事件关联用户 + 所属会话，可取该会话全部请求与原始数据（复用 Interaction Ledger / Conversation / Message，提供下钻 API）
- [ ] **LOG-05**: 事件分类与目录——所有已知事件按 `caller`（调用）/`sampling`（采样）分类、按组件归类，形成事件目录（落地 `LOGGING-SPEC.md`），每条日志带 `category` 与 `component`
- [ ] **LOG-06**: 运行时日志配置（实时生效，复用 `SystemSetting` + signal）——级别（全局/分组件）、堆栈记录阈值、采样初始（首 N 条全记）、采样后续（按比例）、保留天数 / 保留大小；变更立即生效无需重启
- [ ] **LOG-07**: Webhook 原始数据统一落库可查看（`InboundWebhookEvent` 或激活 `WebhookLog`）——飞书、通用工作流 webhook、Git push webhook、容器回调的原始 payload 脱敏后入库，可在后台查看
- [ ] **LOG-08**: 日志清理——支持按条件（时间/级别/组件/用户/关键词）批量清理；保留策略到期定时自动清理（apscheduler）

## Future Requirements

后续里程碑（见 MILESTONE-PROPOSAL.md）：

- **v0.15.0 调用数据采集（RATE/RAG/SLA）**: QPS 分类、TPS（每 provider，含容器侧）、召回条数/分层耗时/相关度/内容留痕、请求错误（系统/业务限制/上游三口径）、上游错误码（429/529 单列）、请求时长与 TTFT 采集
- **v0.16.0 快照·趋势·查询（SNAP/RATE-03/SLA-01/QUERY）**: CPU/内存/DB/Redis/Qdrant/协程/后台任务/并发排队当前快照、趋势采样、可用率、时序查询 API（`percentile_cont` 分位）
- **v0.17.0 告警引擎（ALERT）**: 系统级阈值告警、AlertEvent（P0/P1/P2 + 持续时长 + email_sent + firing/resolved）、邮件通道（SMTP）
- **v0.18.0 运维大盘 + 规范固化（UI/SPEC）**: echarts 时序大盘、快照面板、告警事件页、系统日志下钻页、规范固化与 PR checklist

## Out of Scope

| Feature | Reason |
|---------|--------|
| 指标聚合 / 时序存储 / 趋势 / 告警 / 大盘 | 属于 v0.15.0–v0.18.0；M1 只做"用户贯穿 + 日志落库/配置/留痕"地基，避免里程碑过大 |
| 自研进程内直方图聚合器 + 多级 rollup 引擎 | 量级低，后续用原始事件行 + Postgres `percentile_cont` 更优雅且精确（见 MILESTONE-PROPOSAL §A.2） |
| 集中式日志外部栈（ELK/Loki）/ 冷存储 | 内置落库 + 保留策略先满足自托管开箱即用；外部导出列 v2（OBSX-06） |
| Sentry 接入 | 已预留 `sentry_before_send`，列 v2（OBSX-05） |
| 多 worker 内存缓冲合并 | 落库后以 DB 为权威源；内存 `log_buffer` 仅作单进程极速兜底视图 |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| CTX-01 | Phase 71 | ☐ Pending |
| CTX-02 | Phase 71 | ☐ Pending |
| LOG-01 | Phase 72 | ☐ Pending |
| LOG-02 | Phase 72 | ☐ Pending |
| LOG-03 | Phase 72 | ☐ Pending |
| LOG-05 | Phase 72 | ☐ Pending |
| LOG-06 | Phase 73 | ☐ Pending |
| LOG-08 | Phase 73 | ☐ Pending |
| LOG-07 | Phase 74 | ☐ Pending |
| LOG-04 | Phase 74 | ☐ Pending |

**Coverage:**

- v1 requirements: 10 total
- Mapped to phases: 10
- Unmapped: 0 ✓

---
*Requirements defined: 2026-06-24 — milestone v0.14.0 可观测性地基*
