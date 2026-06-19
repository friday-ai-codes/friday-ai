---
gsd_state_version: 1.0
milestone: v0.12.0
milestone_name: 弹性任务底座（durable 任务队列与多副本就绪）
status: executing
stopped_at: v0.12.0 里程碑 roadmap 创建完成（ROADMAP.md Phases 60–64 + STATE.md milestone overview + REQUIREMENTS.md traceability 16/16）
last_updated: "2026-06-19T18:49:24.127Z"
last_activity: 2026-06-19
progress:
  total_phases: 5
  completed_phases: 1
  total_plans: 4
  completed_plans: 4
  percent: 20
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-20 — start milestone v0.12.0)

**Core value:** 让团队"开箱即用、安全地"把需求自动变成代码。v0.12.0：把现有"可恢复长任务底座"（`server/resumable/`）演进为生产级 **durable 任务队列**——采用 Procrastinate，藏在 `DurableTaskService` 适配层后（Postgres→Procrastinate / SQLite→in-process 非 durable fallback）；统一承载索引/图谱/PageIndex/爬取等后台任务，支持多副本竞争消费、租约心跳、周期 rescue、leader 选主、优雅终止与按队列深度弹性伸缩；以「链接爬取+入库」durable 队列为首个用户可见垂直切片；完成 k8s/compose 部署硬化与 runner 改 k8s Job executor。
**Current focus:** Phase 60 — durable 底座地基

## Current Position

Phase: 61
Plan: Not started
Status: Executing Phase 60
Last activity: 2026-06-19

## Milestone Overview (v0.12.0 — Phases 60–64)

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 60 | durable 底座地基 | DURABLE-01, DURABLE-02, DURABLE-03, DURABLE-04 | ⬜ Not started |
| 61 | 迁移 index/graph + 收口 ResumableTask | MIGRATE-01, MIGRATE-02, IDEMP-01 | ⬜ Not started |
| 62 | 爬取+入库 durable 队列 + PageIndex 接入 | CRAWL-01, CRAWL-02, PAGEIDX-01 | ⬜ Not started |
| 63 | 部署硬化 + 外部副作用 fencing | DEPLOY-01, DEPLOY-02, DEPLOY-03, IDEMP-02 | ⬜ Not started |
| 64 | runner k8s Job executor | RUNNER-01, RUNNER-02 | ⬜ Not started |

**Execution order:** 60 → 61 → 62 → 63 → 64（严格顺序，每阶段建立在前序底座之上）。依赖链：durable 底座地基(60，所有后续的地基) → 迁移 index/graph + 收口 ResumableTask + 幂等基线(61，迁移范式) → 爬取+入库 durable 队列 + PageIndex(62，首个用户可见垂直切片) → 部署硬化 + 外部副作用 fencing(63) → runner k8s Job executor(64，相对独立但排最后)。

**UI 触面（标 UI hint）:** Phase 62（前端爬取任务队列面板 `BatchIngestPanel`，本里程碑唯一 Web 前端重触面）。其余为后端适配层/迁移(60/61)、部署编排(63，helm/compose)、Go runner(64)。

**关键约束 / 设计底座（记入约束，plan-phase 必读）:**

- **采用 Procrastinate 3.8.1，藏在 `DurableTaskService` 适配层后**：业务代码不直接 import Procrastinate；Postgres→Procrastinate、SQLite/无 `DATABASE_URL`→in-process 非 durable fallback；统一接口 `defer/get/cancel/retry_stalled` + idempotency_key + queue/priority。
- **三条硬前置（PoC 结论）**：① worker 必须独立进程（用 `get_worker_connector()`/官方 management command，不能直接拿 DjangoConnector 跑 worker）；② SQLite 只能是非 durable dev fallback（真实 compose/helm 默认 Postgres，`docker-compose.yaml:37`/`settings.py:243`）；③ 先收口 `AppConfig.ready()` 启动副作用（否则 worker/migrate 进程会跑业务 reconcile 误杀在途任务）。
- **执行语义 at-least-once，不承诺 exactly-once**：DB claim 仅保证"同一轮领取只一个成功"；"慢≠死"误判 + 完成未标记即崩仍会重复执行——index/graph/crawl/page_index handler 必须幂等（checkpoint/deterministic key/upsert），外部副作用（飞书通知/建群、MR/PR 创建）上 fencing token 或 outbox。
- **一个底座、多条逻辑队列**（index/graph/crawl_ingest/page_index/maintenance）：各自并发与伸缩，避免长任务（索引）堵短任务（爬取/页面生成）。
- **scheduler/rescue 单例改 DB leader（`queueing_lock`），弃用本地 `flock`**：`flock` 仅单机有效、跨 Pod 失效；周期 rescue 与 cron 收敛到一个 leader workload。
- **收口 `ResumableTask`**：Procrastinate/适配层接管生产职责，不三套并存；`background_runner` 降级为 dev fallback/轻任务；存量在途行一次性迁移，不双跑。
- **聊天/RAG 流式问答明确不进队列**：请求级、流式、断开让用户重试。workflow execution / RepoCodingTask 保留自有引擎，只做"从持久化态重驱"的恢复桥接，不扁平成普通 job。
- **i18n 默认中文**（爬取队列面板文案接入既有 vue-i18n）。
- **显式非目标 / Out of Scope**：承诺 exactly-once、单一队列塞所有任务、聊天/RAG 进 durable 队列、workflow/RepoCodingTask 整体塞队列、引入 Celery/Temporal/Kafka 等重运维组件、SQLite 下 durable 保证、`listen_notify=True` 低延迟唤醒（留 v2 DURABLEX-01）。

**设计底座引用:** 本里程碑前置 PoC 调研结论（Procrastinate 3.8.1 / Python 3.14 / Django 6.0 / psycopg 3.3，adrf `defer_async`、worker queue/priority/periodic/retry/stalled rescue 实测 PASS）+ 现有 `server/resumable/`（lease/CAS/recovery 范式）、`.planning/PROJECT.md`（Current Milestone v0.12.0 + Key context + Key Decisions 8 条 Pending）、`.planning/REQUIREMENTS.md`（16 v1 需求 + Out of Scope + Traceability）。

## Milestone Overview (v0.11.0 — Phases 56–59)

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 56 | compat 内部工具调用 → progress/trace 事件透出 | TRACE-01, TRACE-02 | ✅ Complete (2/2 plans) |
| 57 | Anthropic 兼容端点 `/v1/messages` | ANTHROPIC-01, ANTHROPIC-02 | ✅ Complete (2/2 plans) |
| 58 | 飞书原生流式卡片（CardKit） | CARD-01 | ✅ Complete (2/2 plans) |
| 59 | 工作流自动建群节点 | GROUP-01 | ✅ Complete (2/2 plans) |

**Execution order:** 56 → 57 → 58 → 59。依赖链：先把内部工具调用经 §15 事件 taxonomy 映射为 OpenAI 兼容 progress/trace 透出 adapter(56) → Anthropic `/v1/messages` 端点复用同一 taxonomy→thinking block adapter(57，依赖 56 的透出抽象)；飞书原生流式卡片(58) 与工作流自动建群(59) 相对独立（依赖既有飞书机器人对话 / 飞书 client + 节点机制），排在 Agent API 两 phase 之后。

**UI 触面:** 本里程碑无 Web 前端重触面——56/57 为后端 compat 端点；58 为飞书侧卡片（非 Web 前端）；59 为工作流节点（复用既有节点配置 UI）。`/gsd-ui-phase` 预计不介入。

**关键约束 / 设计底座（记入约束，plan-phase 必读）:**

- **INV-5 对外只透出 progress/trace，非模型私有 CoT**：内部工具调用对外封装为 `reasoning_summary` / thinking block（progress/trace 事件），**绝不用标准 `tool_calls` 回传**——内部工具是服务端闭环执行，回传标准 tool_calls 会让规范客户端误判挂起等待 → 卡死。
- **复用 v0.7 起的 §15 事件 taxonomy**（`PlanSessionEvent` / `event_taxonomy`，DOMAIN §10/§15）：对外 OpenAI/Anthropic 端点只是不同 adapter，不另建词表；taxonomy 已在 v0.7 稳定落地。
- **既有 compat 零回归**：`/v1/chat/completions` 流式 + `reasoning_content` 已有，透出机制以 adapter 叠加、缺事件优雅降级，绝不破坏既有行为。
- **代码现状坐标**：OpenAI compat 已有（`tool_calls` 完全没有、`adapter.py` 明确 continue 跳过、无 Anthropic 端点）；机器人对话已有（双向、群聊需 @），流式卡片部分有（PATCH 全量替换，非原生 CardKit）；自动建群完全没有（仅 `add_bot_to_chat` 加入已有群）。
- **群 chat_id 写回**：自动建群节点的 chat_id 可写回 `WorkItem.feishu_chat_id`（DOMAIN §1.2 writeback 字段），失败 fail-soft 不阻断工作流。
- **显式非目标 / Out of Scope**：标准双向 `tool_calls`（客户端自带工具回传）、暴露原始 CoT、Anthropic 端点工具/多模态全量对齐、飞书卡片交互组件/多卡片编排（均列 v2 OPENX-* 或 Out of Scope，见 REQUIREMENTS.md）。
- **i18n**：飞书卡片/节点文案接入既有 i18n，默认中文。

**设计底座引用:** `.planning/ROADMAP-vNext.md §v0.11`（Target features / 现状坐标 / 已确认决策 / 候选 phases / 交付物-成功标准-风险）、`.planning/DOMAIN-MODEL.md §10`（事件/trace taxonomy）+ §15（事件 payload 规格 + 对外 adapter 映射）、`.planning/PREFLIGHT.md`（无映射 v0.11 的 blocking/should-fix 项）、`.planning/PROJECT.md`（Current Milestone v0.11.0 + Key context）。

## Milestone Overview (v0.10.0 — Phases 53–55)

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 53 | `AuditEvent` 模型 + emit 地基 | AUDIT-01, AUDIT-02 | ✅ Complete |
| 54 | 敏感操作全量覆盖 emit | AUDITCOV-01, AUDITCOV-02 | ✅ Complete |
| 55 | 审计查询 API + 前端视图 + 导出 | AUDITUI-01, AUDITUI-02 | ✅ Complete |

**Execution order:** 53 → 54 → 55（严格顺序）。依赖链：统一 `AuditEvent` 模型 + 单一写入入口 + fail-soft emit 地基(53) → 各敏感操作经统一入口 emit 审计、v0.5 排除/清理埋点收口(54) → 审计查询 API + 前端视图 + 导出(55)。无模型/emit 地基无从 emit，无覆盖的审计数据无从查询展示。

**UI 触面（标 UI hint）:** Phase 55（审计查询前端视图：列表/过滤/before-after 详情 + 导出，本里程碑唯一重前端）。后续 `/gsd-ui-phase` 可介入此处。

**关键约束 / 设计底座（记入约束，plan-phase 必读）:**

- **系统管理员 = 现有 `is_superuser`**：不新建审计角色/权限层（沿用既有里程碑「系统管理员=superuser」决策）；审计查询/导出 superuser fail-closed。
- **审计为横切能力**：各功能产生敏感操作时 emit，本里程碑统一收口 + 补齐覆盖 + UI；emit 失败 best-effort 不阻断主操作（fail-soft）。
- **不可篡改 = 应用层 append-only**：`AuditEvent` 无 update/delete 业务路径、写入经单一 service 入口（INV-6 精神，grep 守护无旁路写表）；密码学级防篡改（hash chain/WORM）留 v2（AUDITX-01）。
- **凭证脱敏**：Provider/Git/飞书凭证、Agent API key/PAT 等敏感操作的审计 before/after 必须脱敏，绝不落明文 token（对齐既有 PAT-02 / 凭证加密约束）。
- **v0.5 既有埋点收口**：现有分散的 `purge.started/purge.completed` 结构化日志、`TriggerLog`/`ActionLog` 等收口到统一 `AuditEvent` 表（DOMAIN §11；现状「无统一 Admin Audit 表」）。
- **显式非目标 / Out of Scope**：新建独立审计角色、密码学级防篡改、实时告警/SIEM/webhook 外发、审计保留/归档/自动清理策略、读操作全量审计（均列 v2 AUDITX-* 或 Out of Scope，见 REQUIREMENTS.md）。

**设计底座引用:** `.planning/ROADMAP-vNext.md §v0.10`（Target features / 现状坐标 / 已确认决策 / 候选 phases / 交付物-成功标准-风险）、`.planning/DOMAIN-MODEL.md §11`（`AuditEvent` 横切治理）、`.planning/PREFLIGHT.md`（无映射 v0.10 的 blocking/should-fix 项）、`.planning/PROJECT.md`（Current Milestone v0.10.0 + Key context）。

## Milestone Overview (v0.9.0 — Phases 48–52)

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 48 | SDD 仓库检测 + facets 打标 + 前端标签 | SDD-01, SDD-02 | ✅ Complete (verify human_needed) |
| 49 | 方案产 openspec spec + Document(sdd_spec) | SPEC-01, SPEC-02 | ✅ Complete (verify human_needed) |
| 50 | spec 状态机 + 变更记录 + 评审状态 + 前端展示 | SPECST-01, SPECST-02, SPECST-03 | ✅ Complete (verify human_needed) |
| 51 | 编码前置 gate + openspec skill 编码策略 | GATE-01, GATE-02 | ✅ Complete (容器 E2E human_needed) |
| 52 | spec↔需求/PR 关联 + 交付验收视图 | LINK-01, LINK-02 | ✅ Complete (容器 E2E human_needed) |

**Execution order:** 48 → 49 → 50 → 51 → 52（严格顺序）。依赖链：SDD 仓库打标(48) → SDD 仓库方案产 openspec spec draft(49) → spec 状态机 + 评审记录 + 前端展示(50) → 编码前置 gate + openspec 注入(51) → spec↔需求/PR 关联 + 交付验收视图(52)。每个 phase 建立在前序产物之上——无打标无从判定产 spec，无 spec 实体无从挂状态机，无 `approved` 状态无从 gate，无放行编码无实现 PR 可关联。

**UI 触面（标 UI hint）:** Phase 48（仓库列表/详情方法论标签）、Phase 50（spec 列表/详情/状态流转 + 评审记录 UI，本里程碑最重前端）、Phase 52（交付验收视图，沿 spec→WorkItem→PR 链路追溯）。后续 `/gsd-ui-phase` 介入这三处。

**关键约束 / 设计底座（记入约束，plan-phase 必读）:**

- **复用 v0.7/v0.8 预留扩展点**（DOMAIN §6.1）：`Document.SDD_SPEC` 枚举（§3/§12.5 已含）、`RepoCodingTask.follow_openspec` 字段（v0.8 Phase 44 已建，本里程碑首次消费）、`Repository.facets` JSON（通用字段已有）、task `setting_sources=["project"]`（容器原生加载仓库内 `.claude/skills`，v0.9 仅加 system_prompt 注入点）。**核查结论：均为「字段/枚举占位」**——openspec 检测钩子、产 spec 逻辑、system_prompt 注入点均需从零建。
- **新增 spec 状态/评审为建模空白**：spec 生命周期独立建模（`SddSpec` + 评审记录实体），非复用 `TechnicalPlan`。
- **spec 状态机命名沿 vNext**：`draft → in_review → approved → implemented → archived`——刻意区别于既有 `TechnicalPlan.status`（`draft|under_review|approved|superseded|archived`），spec 语义确需 `in_review`/`implemented`，不复用避免口径串味。
- **INV-6 单一写入入口精神**：spec 创建/状态流转/评审写入收口到专用 service（如 `SddSpecService`），禁旁路写表；spec draft 经 `DocumentService` 单一入口落 `Document(sdd_spec)`。
- **编码前置 gate fail-closed 语义**：未 `approved` 拦截且如实标注阻断原因，不静默放行；非 SDD 仓库零回归。
- **审计收口顺延 v0.10**：spec 评审记录本里程碑自持久化即可，接入统一 `AuditEvent` 是 v0.10 横切治理范围（REQUIREMENTS Out of Scope 已明确）。
- **显式非目标**：编码中全自动 replan / spec-code 双向 drift 检测 / openspec lint 深度校验 / 非 openspec 的其他 SDD 框架 / 多级会签审批流 / 新建独立 SDD 角色权限层（均列 v2 SDDX-* 或 Out of Scope）。

**设计底座引用:** `.planning/ROADMAP-vNext.md §v0.9`（Target features / 现状坐标 / 已确认决策 / 候选 phases / 交付物-成功标准-风险）、`.planning/DOMAIN-MODEL.md` §6.1（SDD 扩展点）/§3 + §12.5（`Document` 含 `sdd_spec` 枚举与字段详表）/§6（`RepoCodingTask.follow_openspec`）、`.planning/PROJECT.md`（Current Milestone v0.9.0 + Key context）。

## Milestone Overview (v0.8.0 — Phases 43–47, shipped 2026-06-17)

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 43 | 编码 env 对齐 + 通用 resume 回流地基 | PF-06, RESUME-01 | ✅ Complete |
| 44 | RepoCodingTask + execution_plan DAG 拓扑分层 + wave 调度 | WAVE-01, WAVE-02 | ✅ Complete |
| 45 | 上游产物提取 + 注入下游 wave | ARTIFACT-01, ARTIFACT-02 | ✅ Complete |
| 46 | 多仓融合 PR + 跨仓 PR 关联 | PR-01, PR-02 | ✅ Complete |
| 47 | 编码遇阻 → question 抛人（HITL，非全自动 replan） | HITL-01 | ⬜ Not started |

**Execution order:** 43 → 44 → 45 → 46 → 47（严格顺序）。依赖链：编码 env 对齐 + 通用 resume 回流地基(43) → RepoCodingTask + DAG 拓扑分层 + wave 调度(44) → 上游产物提取/注入下游(45) → 多仓融合 PR + 跨仓关联(46) → 编码遇阻 question 抛人(47)。PF-06（编码 env）+ RESUME-01（resume 通路）是 callback 驱动多 wave 的前置地基；每个 phase 建立在前序编码骨架之上。

**前置修复（PREFLIGHT）:** PF-06（workflow 编码路径未注入 branch strategy / git token env，对齐 chat 路径——should-fix-before-v0.8，作 Phase 43）、PF-07（`execution_plan[].dependencies` 仅 schema 声明、下游全并行不读——can-fix-in-milestone，由 Phase 44 wave 拓扑分层消化）。

**v0.7 结转 tech-debt（audit D-2）:** chat deep-research 自动回流接线缺口——主入口「工作流先行」已闭环，chat fire-and-forget 编排进 researching、容器在途完成后无消费者驱动续跑。由 Phase 43 RESUME-01 通用 resume 回流通路消化。

**UI 触面:** Phase 46（多仓 PR 关联展示，maybe，reuse-first）、Phase 47（question 抛人复用 `ask_user_question` 澄清卡片，yes，无新 Vue 组件）。

**关键约束 / 非目标:** scope=`plan_to_pr`（主方案 → 多仓 wave 编码 → 融合 PR）；**不做编码中全自动回溯重规划**——编码遇阻走已有 question 协议抛人，全自动 replan 留 backlog；diff base 用各仓正确 `target_branch`（非假设 master）；新模型经单一写入入口（INV-6 精神，禁旁路写表）。已锁决策：复用 `waiting_event` + callback resume 扩成多 wave 不另造调度；`RepoCodingTask.follow_openspec` 预留 SDD 扩展点（v0.9 做全）。

**复用底座（v0.7 已交付）:** canonical `TechnicalPlan`/`MergedPlan`（含 `execution_plan` 跨仓依赖拓扑）+ `PlanSession` 编排状态机 + §15 事件 taxonomy；既有 `DispatchTask` 协议、RemoteTool MCP、callback 驱动 workflow resume、`waiting_event`、`AICodingNode` 并行派发、chat `coding_session_service`（branch strategy / git token env 在 chat 路径已有）。

**设计底座:** `.planning/ROADMAP-vNext.md §v0.8`（Target features/现状坐标/已确认决策/候选 phases）、`.planning/DOMAIN-MODEL.md` §6（`RepoCodingTask` wave/`depends_on` DAG/`produced_artifacts` + 可靠恢复规则 + SDD 扩展点）/§14（RepoCodingTask 子任务级状态）、`.planning/PREFLIGHT.md`（PF-06/07）。

## Milestone Overview (v0.7.0 — shipped 2026-06-16)

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 36 | 前置修复 + 编排引擎骨架 + PlanSession 状态机 | PF-01, PF-02, ORCH-01, ORCH-02 | ✅ Complete |
| 37 | canonical TechnicalPlan + TechnicalPlanService + 旧路径软链/迁移 | PLAN-01, PLAN-02, PLAN-03 | ✅ Complete |
| 38 | 路由 + 召回接入 | ROUTE-01, RECALL-01 | ✅ Complete |
| 39 | 并行调研子 agent | RESEARCH-01, RESEARCH-02, RESEARCH-03 | ✅ Complete |
| 40 | 架构师融合 + MergedPlan + PlanValidator + 跨仓依赖 | MERGE-01, MERGE-02, MERGE-03 | ✅ Complete |
| 41 | HITL 澄清 + 事件 taxonomy + 工作流入口 | CLARIFY-01, ENTRY-01, EVENT-01 | ✅ Complete |
| 42 | Chat 入口薄封装 | ENTRY-02 | ✅ Complete |

**Execution order:** 36 → 37 → 38 → 39 → 40 → 41 → 42（严格顺序）。依赖链：前置修复+引擎骨架(36) → canonical 方案脊柱(37) → 路由+召回(38) → 并行调研(39) → 架构师融合(40) → 澄清+事件+工作流入口(41) → Chat 入口(42)。每个 phase 都建立在前序编排骨架之上。

**前置修复（PREFLIGHT，作 Phase 36 内 blocking 必修）:** PF-01（`search_code` 工具名漂移 + 未知工具静默 continue）、PF-02（`verify_plan` schema 漂移 `tasks` vs `execution_plan`）——方案质量 + PlanValidator 的地基，开工前必修。

**UI 触面:** Phase 41（工作流入口：工作流节点 + 可能的 plan-session 视图）、Phase 42（Chat 入口薄封装：对话发起编排）标 UI hint。

**关键约束:** INV-2（方案可追溯到 `WorkItem`，chat 自然语言允许 null 但显式标记）、INV-5（对外暴露 progress/trace 事件非模型私有 CoT）、INV-6（方案解析/创建只经 `TechnicalPlanService`，禁旁路写表）。已锁决策：filter_then_container 调研、architect_subagent 融合 + 结构化 MergedPlan + PlanValidator、工作流+Chat 双入口复用同一 engine（工作流先行）、事件 taxonomy 本里程碑即落。

**设计底座:** `.planning/ROADMAP-vNext.md §v0.7`（流水线 6 段/概念/现状坐标/已确认决策）、`.planning/DOMAIN-MODEL.md` §5（canonical TechnicalPlan + service + 迁移规则）/§6（编排状态机 + 子任务级状态 + 可靠恢复规则 + SDD 扩展点）/§7（PartialPlan/MergedPlan/PlanValidator schema）/§14（PlanSession 转移表）/§15（事件 payload 规格）、`.planning/PREFLIGHT.md`（PF-01/02）。

## Milestone Overview (v0.6.0 — shipped 2026-06-15)

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 27 | 飞书接口前置修复 | FIX-01..04 | ✅ Complete |
| 28 | WorkItem 脊柱 + 单一 upsert 入口 | WIT-01..05 | ✅ Complete |
| 29 | 评论事件流 | CMT-01..02 | ✅ Complete |
| 30 | Document + REFERENCES 边 | DOC-01..02 | ✅ Complete |
| 31 | Release 账本 + Bitable adapter 骨架 | REL-01..02 | ✅ Complete |
| 32 | 一键摄取编排 | ING-01 | ✅ Complete |
| 33 | 历史 diff 冻结 + bi-temporal 失效 | HDIFF-01..02 | ✅ Complete |
| 34 | 评论入图 + 片段→需求反查 | RREF-01..02 | ✅ Complete |
| 35 | 截图识别需求 | VIS-01 | ✅ Complete |

## Milestone Overview (v0.4.0 — shipped 2026-06-13)

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 17 | 变量引用链路修复 | VAR-01..04 | ✅ Complete |
| 18 | 执行引擎状态机修复 | ENG-01..05 | ✅ Complete |
| 19 | 节点定义单一事实源 | SSOT-01..03 | ✅ Complete |
| 20 | 保存即合法与模板修复 | VAL-01..03, TPL-01..03 | ✅ Complete |
| 21 | 触发模型与执行可观测 | TRIG-01..03, OBS-01..03 | ✅ Complete |

## Performance Metrics

**Milestone v0.3.0:**

| Metric | Value |
|--------|-------|
| Phases completed | 5/5 |
| Plans completed | 23/23 |
| Requirements delivered | 28/28 |
| Phase 12 P01 | 10min | 3 tasks | 10 files |
| Phase 12 P02 | 12min | 3 tasks | 2 files |
| Phase 12 P03 | 8min | 3 tasks | 7 files |
| Phase 13 P13-02 | 12min | 2 tasks | 3 files |
| Phase 13 P13-03 | ~16min | 3 tasks | 7 files |
| Phase 14 P02 | ~8min | 2 tasks | 4 files |
| Phase 14 P03 | 16min | 3 tasks | 4 files |
| Phase 14 P04 | 14min | 2 tasks | 4 files |
| Phase 14 P05 | 12min | 2 tasks | 3 files |
| Phase 14 P06 | 14min | 2 tasks | 5 files |

**Milestone v0.5.0:**

| Metric | Value |
|--------|-------|
| Phase 22 P01 | ~9min | 2 tasks | 5 files |
| Phase 22 P02 | ~6min | 2 tasks | 3 files |
| Phase 22 P04 | ~13min | 2 tasks | 8 files |
| Phase 22 P06 | ~9min | 2 tasks | 2 files |
| Phase 22 P03 | ~35min | 3 tasks | 8 files |
| Phase 23 P01 | ~10min | 2 tasks | 3 files |
| Phase 23 P02 | ~30min | 2 tasks | 7 files |
| Phase 23 P03 | ~25min | 2 tasks | 2 files |
| Phase 23 P04 | ~20min | 2 tasks | 5 files |
| Phase 24 P01 | ~22min | 2 tasks | 4 files |
| Phase 24 P02 | ~18min | 2 tasks | 4 files |
| Phase 24 P03 | ~12min | 2 tasks | 4 files |
| Phase 24 P04 | ~10min | 2 tasks | 5 files |
| Phase 25 P01 | ~9min | 2 tasks | 5 files |
| Phase 25 P02 | ~5min | 2 tasks | 5 files |
| Phase 25 P03 | ~13min | 2 tasks | 4 files |
| Phase 25 P04 | ~10min | 2 tasks | 2 files |
| Phase 26 P01 | 20 | 2 tasks | 4 files |
| Phase 26 P05 | ~12min | 3 tasks | 4 files |
| Phase 26 P02 | ~15min | 3 tasks | 4 files |
| Phase 26 P03 | ~25min | 3 tasks | 7 files |
| Phase 26 P04 | ~9min | 3 tasks | 9 files |
| Phase 26 P06 (gap) | ~20min | 2 tasks | 7 files |
| Phase 27 P27-01 | ~15min | 3 tasks | 3 files |
| Phase 27 P27-02 | 12min | 3 tasks | 2 files |
| Phase 27 P27-03 | ~5min | 2 tasks | 2 files |
| Phase 28 P28-01 | ~12min | 3 tasks | 12 files |
| Phase 29 P29-01 | ~8min | 2 tasks | 4 files |
| Phase 29 P02 | 18min | 2 tasks | 5 files |
| Phase 30 P01 | 10min | 2 tasks | 4 files |
| Phase 30 P02 | 25min | 2 tasks | 4 files |
| Phase 30 P30-03 | ~20min | 2 tasks | 3 files |
| Phase 31 P31-01 | 5m | 3 tasks | 4 files |
| Phase 31 P02 | 7m | 3 tasks | 4 files |
| Phase 31 P03 | 6m | 3 tasks | 5 files |
| Phase 32 P01 | 25m | 2 tasks | 7 files |
| Phase 32 P02 | 40m | 2 tasks | 9 files |
| Phase 32 P03 | 12m | 3 tasks | 7 files |
| Phase 33 P01 | 30min | 3 tasks | 12 files |
| Phase 34 P34-01 | 22min | 3 tasks | 10 files |

**Milestone v0.8.0:**

| Metric | Value |
|--------|-------|
| Phase 44 P44-01 | ~8min | 3 tasks | 4 files |
| Phase 44 P44-02 | ~6min | 2 tasks | 3 files |
| Phase 44 P44-03 | ~7min | 3 tasks | 4 files |
| Phase 44 P44-04 | ~8min | 2 tasks | 3 files |
| Phase 44 P44-05 | ~22min | 3 tasks | 2 files |
| Phase 45 P45-03 | ~12min | 2 tasks | 1 file |
| Phase 46 P46-01 | ~5min | 2 tasks | 2 files |
| Phase 46 P46-02 | ~14min | 2 tasks | 4 files |

**Milestone v0.11.0:**

| Metric | Value |
|--------|-------|
| Phase 56 P56-01 | 11 min | 3 tasks | 4 files |
| Phase 56 P56-02 | 13 min | 3 tasks | 7 files |
| Phase 57 P57-01 | 5 min | 3 tasks | 9 files |
| Phase 57 P57-02 | 8 min | 2 tasks | 4 files |
| Phase 58 P58-01 | 14 min | 2 tasks | 4 files |
| Phase 59 P59-01 | 4 min | 2 tasks | 5 files |
| Phase 59 P59-02 | 5 min | 1 task | 2 files |

**Milestone v0.9.0:**

| Metric | Value |
|--------|-------|
| Phase 51 P51-01 | ~10min | 2 tasks | 3 files |
| Phase 51 P51-02 | ~20min | 3 tasks | 3 files |
| Phase 51 P51-03 | ~10min | 2 tasks | 5 files |
| Phase 53 P01 | 7 min | 3 tasks | 10 files |
| Phase 53 P02 | 9 min | 4 tasks | 9 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table; v0.2.0 full phase detail in `.planning/milestones/v0.2.0-ROADMAP.md`.

- [Phase 12]: EntityKind/EdgeRelation 枚举字面值锁死（kind 进 uuid5 PK 派生，改名即数据迁移）；MODIFIES_CHUNK 为 Phase 14 占位
- [Phase 12]: generate_entity_id 拼接格式 kind:source_kind:source_id + 独立 KNOWLEDGE_NAMESPACE；CodeChangeArchive 不预建（Phase 14 自带 migration）
- [Phase 12]: GraphStore 递归 CTE anchor path 不含起点（环回到起点计 1 次后终止）；direction=both 多跳与 MySQL 后端显式 NotImplementedError
- [Phase 12]: payload schema 8 索引字段第一天定型（含权限维度），回归测试锁键集合；ensure 不匹配 raise 绝不删库，重建唯一入口 rebuild_delivery_knowledge --yes 命令
- [Phase ?]: 13-02: hash 相等绝不产生新版本——needs_revector 走 revectorize_version 补写向量，不建版本行不置 invalid_at
- [Phase ?]: 13-02: 边非严格同事务——apply_edge_specs 幂等可重入，skipped/needs_revector 事件仍执行边阶段自愈
- [Phase ?]: 14-02: 截断 helper truncate_diff_lines 放 base.py 模块级双客户端共用；既有 get_merge_request_diff 内联截断不动（零回归）
- [Phase ?]: 14-02: base get_branch_diff 抽象化分两步——Task 1 NotImplementedError 占位、Task 2 双实现齐备后转 @abstractmethod，避免瞬时打破 GitHubClient 实例化
- [Phase 14]: 14-04: 审批事件 source_id 恒为生成节点 key（OQ-2），接线处换算、normalizer 单纯
- [Phase 14]: 14-04: workflow_plan normalizer 兼容 trigger_data.raw_payload 与 payload 双键取飞书工作项锚
- [Phase 14]: 14-05：飞书三 handler 只投三元组 ID（取材全在 normalizer 后台），文档拉取失败降级为缺段快照 + warning
- [Phase ?]: 14-06: workflow mr_results 回退键按引擎实际落点 merge_requests（checker 建议的 succeeded_repos 实为计数 int）
- [Phase ?]: 14-06: workflow 仓库归属经 output_data.pending_sessions 匹配 + session.repo_url 兜底（双源均服务端写入，T-14-22）
- [Phase 22]: 22-01: 排除判定唯一入口 services.exclusion.is_excluded(repository_id, rel_path)，Wave 2 plans 直接引用不得另起炉灶；失败模式二分（构造期非法 regex fail-loud / 运行期 fail-closed True + exclusion.blocked 埋点）
- [Phase 22]: 22-01: dir 规则 = 相对仓库根前缀（目录本身 + 子树）；glob 用 fnmatch.translate 大小写敏感跨 / 匹配；per-repo source=global+enabled=False 行作为关闭全局默认的 override 标记
- [Phase 22]: 22-01: BUILTIN_GLOBAL_DEFAULTS 内置安全默认即使无任何配置也生效（向后兼容 + 开箱即用，per D-04）
- [Phase 22]: 22-02: scan_directory 用注入式 is_excluded_rel 回调（Callable，非 matcher 对象）保持纯函数无硬依赖避免循环导入；扫描期回调异常 fail-closed（跳过文件/剪子树）
- [Phase 22]: 22-02: indexer full + incremental 两路径预取 build_matcher_for_repo（async）并注入同步 scan_directory，被排除文件从源头不进 files_to_process/local_hashes（存量清理留 Phase 23）
- [Phase 22]: 22-02: PF-04 关闭——scan_directory 不再谎称 .gitignore，注释/docstring 如实描述「目录名 + 扩展名白名单 + 排除匹配器」
- [Phase 22]: 22-06: MCP HTTP 直读面（grep/get_file/list/find_related）挂接单一匹配器 fail-closed；get_file 对 requested+resolved 双判定防后缀绕过；grep 过滤后重算 total/files_with_matches 避免泄漏存在性；matcher 构造异常用 _FailClosedMatcher 兜底（排除一切，不放行）
- [Phase 22]: 22-06: 只在 view 层过滤（不改 repo_mirror.py 助手），不重复 22-03 已覆盖的 search_rag_chunks；为保持最小 diff 未对 views.py 跑整文件 ruff format（预存 I001/非规范，超范围）
- [Phase 22]: 22-04: serialize_rules_for_repo 绝不返回空（异常/无配置回退 BUILTIN_GLOBAL_DEFAULTS），不下传 = 容器面裸奔；matcher 与容器下传共用 _resolve_effective_specs（单一合并真相，_load_specs_from_db 保留别名）
- [Phase 22]: 22-04: 两条编码派发路径（chat build_dispatch_metadata + workflow _run_repo_coding）均无条件注入 env_FRIDAY_TASK_EXCLUDE_PATTERNS（仅规则模式，无凭证）
- [Phase 22]: 22-04: task 容器侧独立轻量匹配器（不 import server，语义对齐 dir/glob/regex），prune_excluded clone 后删被排除文件、跳过任意层级 .git/（T-22-15）；删除重试 chmod +w → 持久失败抛 ExclusionPruneError 使 setup 失败（fail-closed，T-22-16，绝不残留可读）
- [Phase 22]: 22-03: search_rag 是 RAG 单一 chokepoint——每 repo 预取 matcher、收集前过滤，覆盖 chat/agent/workflow 所有经 HybridSearchService 的调用方；图谱邻居（hop1/hop2/cross-repo）在 _search_graph_capable 预先剔除（渲染+返回字段双覆盖），无 repo 归属对 repo_ids matcher 做 any 命中（保守 fail-closed）
- [Phase 22]: 22-03: browse_file_content 入口拒读 + fuzzy resolved_path 复判防后缀绕过（T-22-09），返回 chunks=[]+error 无明文；list_space_structure 文件树过滤；search_repository_code 兜底过滤防未来旁路回流；matcher 构造/判定异常一律 fail-closed
- [Phase 22]: 22-03: ⚠️ 旁路读取面未覆盖（需收尾 plan）——index_views.py _vector_search 与 deprecated layered_search._l3_hybrid_search 直读 BranchAwareSearchService.search 不经 search_rag，被排除文件可漏出（见 22-03 SUMMARY Threat Flags / deferred-items.md）
- [Phase 22]: 22-GAP: ✅ 上述 index_views 旁路面（现 CodeSearchView._search，认证 REST `POST /api/repositories/<id>/search/`，前端 searchCode 在用）已闭合——返回前挂 build_matcher_for_repo + is_excluded fail-closed（构造失败整仓库丢弃 / 单项判定异常丢弃 + log surface=code_search，total 由过滤后集合重算），补对称守护测试（56d230553）；layered_search._l3_hybrid_search 经 22-VERIFICATION 研判为 deprecated 内部 helper、生产不可达，非缺口
- [Phase 23]: 23-01: 统一删除入口 services.purge.purge_file(repository_id, rel_path) + PurgeResult，是 Qdrant 主+overlay / FileIndex / ChunkRegistry(+ChunkEdge) / codegraph 五面的唯一删除收口点；Wave 2/3 清理与对账一键清理须复用，不得另起删除逻辑。best-effort 逐面隔离 + PurgeResult.failures（不静默假装全净）
- [Phase 23]: 23-01: PF-03 收口——run_incremental_index / run_git_diff_index 的 DELETE 分支收敛到 purge_file（消除「只删 Qdrant 不删 FileIndex/ChunkRegistry」孤儿）；PF-05 收口——overlay 删除遍历 RepositoryBranchIndex.collection_name 逐删 file_path
- [Phase 23]: 23-01: ChunkRegistry 删除务必走 queryset.adelete() 逐实例触发 pre_delete 信号联动清边（绝不绕过信号）；codegraph 分支枚举归一化（is_base/branch_name==base → ""，feature 用原名）避免 RepositoryBranchIndex(base="main") 与 codegraph(base="") 口径漂移漏删；保留 indexer 既有 codegraph 孤儿清理块（精确单分支删除，与 purge_file 幂等不冲突）
- [Phase 23]: 23-01: ⚠️ purge_file 暂未覆盖 repo_summaries / index_nodes 面（DOMAIN §9.3 普通列其余面），后续清理 plan 如需可扩展
- [Phase 23]: 23-02: compute_reconciliation = FileIndex ∪ ChunkRegistry file_path 双源并 ∩ 复用 22 build_matcher_for_repo；degraded 仅由匹配器构造抛错触发（单文件 is_excluded 运行期异常由 matcher 内部 fail-closed 命中兜底，不污染 degraded），W3 贯通 dataclass→serializer→client 不谎报「已一致」假干净
- [Phase 23]: 23-02: run_cleanup 逐差异文件调 23-01 purge_file（best-effort 逐文件隔离），终态 failures 非空→failed 否则 completed；清理后 best-effort 后台调度 repo_summaries+repo_index_nodes 重建（可重建聚合，失败不致命）
- [Phase 23]: 23-02: CleanupRun 持久化（status/mode/match_count/failures/sensitive/error，(repository,-started_at) 索引取最近一次）；清理经 run_in_background 后台派发（API 先建 running 行拿 run_id 立即 202，D-04/T-23-08），状态端点回流结果（含敏感 unscrubbed/caveat，W1/W2）
- [Phase 23]: 23-02: 敏感模式懒导入契约 services.sensitive_purge.purge_sensitive_planes(repository_id, purged_paths)（23-03 提供，普通模式零依赖）；未就绪→failures + CleanupRun.error，普通清理结果不受损。审计事件 purge.started/purge.completed（mode/repository_id/match_count/failures）
- [Phase 23]: 23-03: 敏感清理委托落点 services.sensitive_purge.purge_sensitive_planes —— 四面 helper（CodeChangeArchive/TaskResult/ActionLog/loose-text）逐面 try/except 隔离，返回 dict {scrubbed:{plane:{scrubbed,deleted}}, unscrubbed, caveat, errors} 落 CleanupRun.sensitive
- [Phase 23]: 23-03: CodeChangeArchive file 级 scrub recompute **不调 parse_diff_files**（其解析平台 MRDiffFile 对象而非 unified-diff 文本，W4 类型不符）；改为过滤既有 files JSON 列表重算计数 + 按 `diff --git a/old b/new` 边界切段剔除目标文件 diff（new/old 任一命中即剔除），decompress_diff/compress_diff 重压缩；仅含被排除文件整行删，含他文件保留他文件部分（T-23-13 不误删）
- [Phase 23]: 23-03: TaskResult/ActionLog 关联键 = _normalize_repo_url(session.repo_url)==_normalize_repo_url(repo.git_url)（去 .git/末尾斜杠/小写）；归一不匹配的记录完全不动（T-23-12 保守，宁漏勿误删他仓产物）
- [Phase 23]: 23-03: message parts/content 无 repo 关联键（Conversation 绑 Project 非 Repository）→ best-effort 子串脱敏（_redact_value 只替换命中被排除路径的 str 叶子，保留同载荷其余字段，不整库清空 T-23-13）；prompt_snapshot/backups/git_objects 记 unscrubbed + SENSITIVE_PLANES_CAVEAT 如实声明 git object/历史/备份不承诺物理消失（§9.1 T-23-11，绝不假装清除）
- [Phase 23]: 23-04: 前端 web/src/api/reconcile.ts + ReconcilePanel.vue 兑现 EXCL-06 可见闭环；degraded 前端落地——degraded=true → 显式『对账不可信』警示 + 禁用双清理按钮、绝不渲染空态/已一致（W3）；普通/敏感双入口分离（§9.2），敏感强确认直取 §9.1『不可逆 + 仅清 Friday 派生/操作记录可定位内容，不承诺从 git 历史或备份物理消失』
- [Phase 24]: 24-01: 确定性检测器 services.sensitive_detect.detect_sensitive_files(repository_id, repo_path) async 入口——独立有界遍历（**不**复用 indexer 扩展名白名单扫描，否则漏 .env/id_rsa/*.pem）；遍历跳过集仅 .git/node_modules，**不**纳入 BUILTIN dir 默认（.ssh/secrets 恰是要识别的目标，偏离 PLAN 措辞 Rule 1）；1MiB+二进制 NUL 嗅探+symlink 跳过（T-24-02）
- [Phase 24]: 24-01: reason 经唯一构造入口 _redact_reason(kind, line_no) 只写「类型+行号」，绝不回填命中文本/group 值（T-24-01）；审计 sensitive.detected 仅计数/severity。内容扫描模块级编译正则 _SECRET_PATTERNS（私钥块/AWS AKIA+赋值/GitHub gh[pousr]_/Slack xox/通用 api_key|secret|password|token 赋值）+ 高熵 Shannon≥4.0 跳注释行；content 命中即 real_secret，高熵单独命中降 likely_sensitive
- [Phase 24]: 24-01: 持久化单一入口 _upsert_suggestion 经 aupdate_or_create(repository_id, path)——dismissed 仅在升级为 real_secret（旧非 real_secret）时重置 pending 打扰，否则保留 dismissed 不复扰；accepted 保留不动；severity 合并取最高（real_secret>likely_sensitive>config_review），detector 有内容命中取 content 否则 heuristic
- [Phase 24]: 24-01: 文件名启发式复用 services.exclusion.BUILTIN_GLOBAL_DEFAULTS 的 glob 基线（_build_filename_globs 仅 glob 型，fnmatch.translate + re.IGNORECASE，basename 兜底 BL-01），命中返回 config_review 基线
- [Phase 24]: 24-02: run_full_index FINALIZING 末尾（_refresh_tree_facts 之后、return success 之前）经 run_in_background(lambda: detect_sensitive_files(self.repository_id, repo_path), name="sensitive-detect:{id}") best-effort 派发——**不** await 结果，整段 try/except 吞派发异常 warning sensitive_detect_dispatch_failed，检测失败/派发失败绝不阻断索引 success（D-04/T-24-05）。触发 guard 沿用 auto-after-index 范式：复刻派发模板 helper + 源码 token 漂移 guard（不跑重依赖完整索引）
- [Phase 24]: 24-02: 可选 LLM 二分类 services.sensitive_detect.classify_ambiguous_files(repository_id, candidates: list[AmbiguousCandidate])——确定性段始终启用、LLM 段对 ambiguous 子集可选；aresolve_or_error→ProviderMissingError / 缺 default_model / 任何调用解析异常一律 return 0 graceful 退化不冒泡（T-24-07），确定性结果不依赖 LLM 成功
- [Phase 24]: 24-02: 隐私加固（偏离 PLAN『截断 N 字符』措辞 Rule 2）——_build_llm_feature 只送「文件名+扩展名+has_sensitive_keyword 布尔」，sample_text 正文仅本地计算布尔信号绝不进请求；real_secret 强命中排除出候选；新增 _redact_llm_reason 对 LLM 理由做高熵串+_SECRET_PATTERNS 替换 [已脱敏] 服务端兜底（T-24-06 纵深防御）。命中产 likely_sensitive/detector=llm 经统一 _upsert_suggestion 入库，仅 pending 绝不建规则/删数据（T-24-08）
- [Phase 24]: 24-03: 敏感建议 REST API 走独立 APIView + 显式 `<uuid:repository_id>/sensitive-suggestions/`(list) + `.../{suggestion_id}/action/`(action) 路由（对齐 Phase 22 exclusions idiom）；SensitiveFileSuggestionSerializer 全字段 read_only（状态仅经专用 action 改，禁直接 PATCH，T-24-09/10）；list 默认仅 pending、?status=all 全量，severity 优先级 Python 侧映射排序（real_secret>likely_sensitive>config_review）+ detected_at desc；accept 用 aget_or_create（唯一约束含 source）实现幂等避免二次 accept 500（T-24-12）→ 建 RepoExclusionRule(source=ai_suggested,rule_type=glob) + 标 accepted + invalidate_matcher_cache；accept 绝不删数据（NEVER silent-delete，response 仅附 cleanup_available 引导，删除仍由 Phase 23 reconcile/cleanup 显式触发 T-24-10）
- [Phase 24]: 24-04: 前端 sensitiveSuggestionsApi（list/accept/dismiss）+ SensitiveSuggestionsPanel.vue 兑现 EXCL-03 用户可见闭环；real_secret 列表顶部 destructive 横幅 + 行内危险底色双重突出（data-testid=real-secret-alert 供测试稳定定位，T-24-15）；accept 经 useConfirmDialog 二次确认明示「新增排除规则、不会自动删除已索引内容、需在清理面板显式执行」（T-24-14），dismiss 无确认（无破坏性）；accept/dismiss 后 invalidate 自身建议 key + repository-exclusions key 使新建 ai_suggested 规则即时显现于排除面板；前端保序渲染后端已排序结果（不前端重排）；面板 prop 命名 repoId（依 PLAN，区别既有面板 repositoryId）；守护测试以真实 zh-CN.json 作 messages 断言告警/确认措辞防被改空（T-24-13 reason 仅渲染脱敏文本）
- [Phase 25]: 25-01: ChunkRegistry 行号回填无新 migration（line_start/line_end + chunkreg_line_range_valid 约束已存在于 0003/0004，per D-02）；行号直接取 CodeChunk.start_line/end_line（1-based 闭区间），与同处写入 Qdrant payload start_line/end_line 同源保证两侧一致；ChunkRegistryRow TypedDict 新增 line_start/line_end 键作 _build_points→_bulk_upsert 同源契约（mypy 拦截漏传）
- [Phase 25]: 25-01: _bulk_upsert_registry_atomic update 判定显式纳入「行号变化」（obj.line_start/line_end != row[...]），避免仅行号位移、hash/路径/index 未变时漏更新（否则 25-02 反查命中错位，T-25-03）；错乱区间（line_end<line_start）由既有 CheckConstraint 拒绝 IntegrityError（T-25-01），indexer 不静默落错；None 行号合法落 NULL（历史/非 AST 回退兼容，不强制回填历史）
- [Phase 25]: 25-02: find_chunk_at(repository_id, file_path, line, *, branch_name) 反查入口先 build_matcher_for_repo 再查询——构造失败/路径归一 None/is_excluded 命中（含判定异常）一律 fail-closed 返回空 + log_exclusion_blocked(surface=chunk_at)，绝不放行（T-25-04，对齐 rag_search 范式）；查询条件含 line_start/line_end__isnull=False（NULL 历史 row 天然不命中）+ 闭区间 lte/gte；多 chunk 命中返回全部，按区间宽度 (line_end-line_start) 升序、次序稳定按 chunk_index（最具体优先，per Claude's Discretion）；仅读 ChunkRegistry 不触 Qdrant
- [Phase 25]: 25-02: GET /api/repositories/<id>/chunk-at/?path=&line=&branch_name= 走独立 ChunkAtView APIView（adrf）+ 显式路由（router include 之后，UUID 通配安全），IsAuthenticated 保护（T-25-06）；被排除文件与无命中对外同形返回 {"chunks": []} 200 不泄漏存在性（T-25-05）；path 必填、line 正整数校验（<1/非法→400），不存在仓库→404；service 不抛 past view（normalize None→空，T-25-07）
- [Phase 25]: 25-03: commit 历史索引专用边界 Repository.commit_index_boundary_sha（migration 0035 AddField，nullable 无回填）**独立于** last_indexed_commit_sha（代码 chunk 边界），绝不复用避免口径串味；index_commits 仅 upsert 成功才推进 boundary 到 HEAD（无新 commit/embedding 缺失/upsert 失败均不推进，绝不丢 commit，T-25-09）
- [Phase 25]: 25-03: commit 文档落主 collection + payload kind=commit（与代码 chunk 同检索面经既有 search_rag 召回、可区分/过滤，无需改检索）；确定性 uuid5(ns, repo_id:sha) point id + 合成 file_path=.friday/commits/{sha}+chunk_index=0 保既有去重 key 唯一且不被排除规则误命中（T-25-10）；变更摘要复用 Phase 22 build_matcher_for_repo/is_excluded fail-closed 剔除被排除文件、只含路径不内联 diff 正文（T-25-08）
- [Phase 25]: 25-03: 增量 git log boundary..HEAD，boundary 失效（force-push/rebase 报错）回退首轮 --max-count=COMMIT_INDEX_FIRST_RUN_CAP(500)+--no-merges bounded 全量（T-25-11）；--format 用 git 占位符 %x00(字段)/%x1e(记录) 而非内嵌真实 NUL（子进程参数不可含 NUL，否则 ValueError: embedded null byte），解析侧按实际字节切分；git diff-tree 加 --root 纳入根 commit；hybrid 判定/sparse 生成复用 IndexerService._is_hybrid_enabled/_generate_sparse_vectors 不另写
- [Phase 25]: 25-04: commit 索引唯一挂接点 services.indexer._run_commit_index——仅 base 路径（if not branch:）在 _run_sensitive_detection 之后、finally rmtree(temp_dir) 之前 await（沿用 Phase 24 BL-01 时序：index_commits 需读真实克隆 git 历史，绝不后台派发去遍历即将删除的目录）；全量+增量均流经此函数，首轮/增量区分由 index_commits 内部 commit_index_boundary_sha 处理；整段 try/except 吞异常仅 warning commit_index_dispatch_failed，commit 索引失败/缺供应商绝不阻断 return index_result 的 success 终态（best-effort，对齐 _run_sensitive_detection / T-25-12）
- [Phase 25]: 25-04: 召回端到端守护无真实 Qdrant——捕获 index_commits upsert 的 commit point，mock BranchAwareSearchService.search 对其按 query substring 命中 content 返回，模拟语义召回；build_matcher_for_repo 用真实实现（仅 builtin 全局默认）真正经过 search_rag 排除/去重 chokepoint，验证合成 file_path=.friday/commits/{sha} 不被排除可召回、被排除文件不泄漏（T-25-13）、增量只新增（T-25-14）
- [Phase 23]: 23-04: 派发后双查询模式——mutation 成功 → 开启第二个 useQuery 轮询 getCleanupStatus（refetchInterval=(q)=> status==='running'?2000:false）+ invalidate reconcile 观察归零；CleanupRun.sensitive.unscrubbed/caveat 如实渲染真实后端结果（非静态文案，W1/W2）。测试以真实 zh-CN.json 作 i18n messages 守护威胁缓解措辞不被改空；W5 vue-tsc 门禁真实生效（spec createI18n messages 类型不符被捕获修复）
- [Phase ?]: 26-01: 实例凭证落在 repositories app，表 git_instance_credentials，host 唯一 + Fernet 加密 token
- [Phase ?]: 26-01: 凭证解析单一入口 resolve_git_token_sync——per-repo token 优先 → 实例池 host fallback → None，Wave 2 统一调用
- [Phase ?]: 26-05: search_rag_chunks 多仓参数（repository_ids/all_repositories/max_repos），mirror grep；多仓经 search_rag chokepoint 每仓 fail-closed，结果按 item.repository_id 标注来源
- [Phase 26]: 26-02: clone/index、bare 镜像 fetch、图谱克隆三路径统一经凭证解析器取 token（aresolve_git_token / resolve_git_token_sync），消除内联 GitCredential→decrypt_value；per-repo 优先、host 实例池 fallback；同 host 多仓共享一份凭证；token 仅进单次 clone/fetch argv 不入日志
- [Phase 26]: 26-04: 实例凭证 REST CRUD——读/写序列化器分离（read 只含 has_token 布尔无明文 token、write access_token=write_only）；GitInstanceCredentialsView/DetailView 走 IsSuperUser，encrypt_value 写入、空 token 的 PATCH 不清空既有 token、日志仅记 host/has_token；host 唯一性视图层 aexists+IntegrityError 双兜底给中文报错；路由字面段须在 router include 之前；base-branch 校验改经 aresolve_git_token（实例池仓库也可校验），TestConnection 验证入参 token 流程不变；前端 /admin/git-credentials 管理页 token password 不回填、留空=不改、提交清空，列表仅 has_token 徽标；守护测试后端 8 + 前端 2 全绿（DB 密文/响应/日志/前端无明文 + 非管理员 403）
- [Phase 26]: 26-03: git 平台 MR/PR 客户端（_get_client / create_mr_for_task / coding.py MR 段）+ 编码容器 dispatch token 注入（coding.py dispatch / coding_session_service 两处）+ diff archive 拉取五处取 token 统一经 aresolve_git_token，per-repo 优先 → host 实例池 fallback；解析器 None 时各调用方保留既有缺凭证报错/降级（行为不回退）；token 仅传 client/进 dispatch payload 不入日志；守护测试覆盖同 host 共享 + per-repo 优先 + 缺凭证报错不回退 + 不泄漏
- [Phase 26]: 26-06(gap): 26-VERIFICATION 发现 26-02/03 之外仍有残留 6 文件 ≥8 处内联 decrypt_value(encrypted_token) 绕过解析器（pr.py PR+cross-ref、coding_graph.py 冲突预检+PR、code_review.py get_merge_request_diff、summary_service.py + chat_tools.py 两处容器 dispatch、views.py TestConnection 既有仓库分支）→ 全部改经 aresolve_git_token；TestConnection 仅『既有仓库 repository_id』分支接解析器、『用户当场输入 token』分支不变；code_review 去无用 select_related('credential')；缺凭证保留各自既有文案（行为不回退）；新建 test_git_credential_gap_wiring.py（dispatch 注入 + 平台 client 两类代表入口，6 测）；grep 确认全 server 除解析器自身已无 resolver-bypassing 取 token
- [Phase 27]: 27-02: get_work_item/get_comments 移除 work_item_type=story 默认改必填(fail-loud TypeError)，WorkItemInfo 新增带默认 feishu_fields(完整元数据)+fields 拍平双写向后兼容；接入 27-01 helper——硬路径 strict_response_json fail-loud、comments/relations 端点 safe_response_json fail-soft 返回[]，relations 标注 origin=feishu_relation_api；全 services.feishu 调用方已显式传 type，零回归
- [Phase 27]: 27-03: near-dup feishu.client 接入 27-01 共享 helper，落 FIX-01/03/04，与 canonical services/feishu.py 同源同断言消除解析漂移；work_item_type 必填 fail-loud、WorkItemInfo 新增带默认 feishu_fields、get_comments safe_response_json fail-soft；本 client 无 relation 端点故不涉 FIX-02；全调用方已显式传 type 零回归
- [Phase 28]: 28-01: 新建 delivery app（注册 INSTALLED_APPS 在 feishu 之后），models 包按实体拆 work_item/sync_state/relation/status_event + curated re-export；id 一律 UUIDField(default=uuid4)；INV-1 由 WorkItem.Meta.unique_together(feishu_project_key, work_item_type, work_item_id) 在 DB 层强制（测试以 pytest.raises(IntegrityError) 守护）；feishu_fields=JSONField(default=list)、field_provenance=JSONField(default=dict)；WorkItemOrigin 含 bitable_import/mr_reverse 枚举占位（真实调用方 Phase 31/32）；本 plan 只建表，落库逻辑归 28-02 service（INV-6）；模型层无 create/save 业务逻辑
- [Phase 29]: 29-01: append-only WorkItemCommentEvent 模型只建表+枚举（CommentEventType 五值/ApprovalSemantic 三值默认 none），模型层无 create/save/就地改写方法——落库归 29-02 CommentEventService 单一入口（守 INV-6）；编辑/删除作为新事件行（CMT-02，模型单测守护两行并存）；edited/deleted 留枚举占位 deferred；复用 status_event append-only 范式 + (work_item, event_time) 索引
- [Phase ?]: 29-02: 评论事件落库唯一收口 append_events（INV-6 精神），去重锚 get_or_create 幂等；ingest 复用 Phase 27 get_comments 降配不回滚
- [Phase ?]: 29-02: 当前评论树为事件流读时投影 project_comment_tree（非事实表），编辑取最新/删除标记/线程层级/排序，绝不改事件行
- [Phase 30]: Document/DocumentVersion 操作态实体落 delivery app，逐字段对齐 DOMAIN §3/§12.5；版本链 supersedes self FK + unique_together(document, version)；本 plan 仅建表无落库逻辑（守 INV-6）
- [Phase 30]: DocumentService.upsert_from_feishu 单一写入入口（INV-6）：(feishu_tenant, external_ref) 去重 + content_hash 不翻版本 + supersedes 链 + facet 记录
- [Phase 30]: feishu_tenant 由 doc URL host 派生；_content_hash 复用 knowledge sha256 但不 import（INV-3）
- [Phase ?]: [Phase 30]: feishu_document normalizer 复用 feishu_work_item.normalize 锚事件 + _extract_doc_token/_fetch_doc_body 取材（不重写）；产出操作态 Document（DocumentService INV-6）+ knowledge document 实体 + work_item→REFERENCES→document 出边；feishu_work_item.py 不动（INV-3）
- [Phase ?]: [Phase 30]: doc token 取自 wi 锚事件 payload 的 prd_url/tech_doc_url（避免重复 get_work_item）；同 docx 二次拉取为 accepted tradeoff；doc 拉取/操作态写入失败降级 warning，缺段不缺实体不抛不回滚
- [Phase ?]: Release natural key 落独立字段 bitable_record_key（条件唯一），便于 31-03 幂等 upsert
- [Phase ?]: 31-02: ReleaseService 消费预组装 bitable_record_key 作自然键唯一来源（不在服务内重拼接，归 31-03 adapter）
- [Phase ?]: 32-03 前端一键摄取面板沿用派发→轮询范式（useMutation + 条件 refetchInterval），守护测试以真实 zh-CN.json 锁关键文案
- [Phase ?]: 33-01: commit 锚定复用 CodeChangeArchive.commit_sha/base_branch（不新增字段/migration）；chunk_content_hash 冻结进 KnowledgeEdge.metadata 供 HDIFF-02 对账
- [Phase 34]: 34-01: 片段→需求反查 service 复用 find_chunk_at + graph_store 逐跳 neighbors(direction in/out) 反向多跳，纯读/默认当前视图(as_of=None 排除失效边)/fail-closed；chunk_id 直接入参经 ChunkRegistry 复判 file_path 排除不绕过边界；REST(IsAuthenticated) + MCP reverse_lookup_requirements 同形结构化 {chunks,related_work_items,related_documents,paths}
- [Phase 42]: 42-01: 抽薄共享 helper plan_orchestration/entrypoint.py（start_orchestration 薄包 create_session + build_orchestration_engine 注入与 Phase 41 完全相同的 5 真实 adapters），workflow 节点与 chat 工具同调一份——落「底层 engine 复用、不造两套」；helper 只建 session + 构建 engine，不驱动 advance（工作流 waiting_event / chat interrupt 两运行时不混进 helper）
- [Phase 42]: 42-01: chat 工具 start_plan_research（@tool category=PROJECT，space_id/conversation_id MCP 适配层注入 LLM 不可见）薄封装——建 entrypoint=chat + work_item=None session（INV-2 自然语言需求显式可追溯，canonical 仍 origin=orchestration、work_item=None 即标记）+ 复用同一 engine 驱动；挂起复用 chat 既有 HITL（clarifying→ask_clarification interrupt marker / researching→deep_analysis fire-and-forget __blocking_task__ + register_blocking_task），绝不重实现 HITL
- [Phase 42]: 42-01: 入口无关一致性守护（test_orchestration_entry_consistency）——同一 requirement 经 workflow/chat 两 entrypoint 产 dict 相等 MergedPlan content + 按 created_at 同序 §15 事件序列；无新模型/无 migration（makemigrations --check 干净）；真实 LLM/容器 E2E deferred（IO 边界 mock）
- [Phase 43]: 43-01(PF-06): workflow 编码 `_run_repo_coding` 逐键对齐 chat `build_dispatch_metadata`——注入顶层 `env_FRIDAY_TASK_GIT_ACCESS_TOKEN/AUTH_TYPE("token")/SSL_VERIFY("false")`（token 非空时）+ `git@` SSH URL → HTTPS `repo_url` 改写；修复 nested `git_credentials` dict 不被 runner 消费（dead payload）的私有仓 clone 失败
- [Phase 43]: 43-01(PF-06): `env_FRIDAY_TASK_BRANCH_STRATEGY`=本次调用 `branch_name`、`TARGET_BRANCH`=`base_branch`（多仓 fan-out per-repo，非 chat 单仓 execution_spec）无条件注入，修复容器侧落默认 `friday/task-{id}` 分支；SSL_VERIFY 取值对齐 chat 基线硬编码 `"false"`（Open Q1 RESOLVED），不取 per-repo credential.ssl_verify
- [Phase 43]: 43-01(PF-06): token 为空降级不回退（不注入 access_token 键/不改写 repo_url）；nested `git_credentials` dict 零回归保留；dispatch 日志仅 `has_git_token` 布尔，token 绝不入日志；不改 task/runner（env 消费契约只读核对）；6 守护测试全绿（test_coding_node.py 12 passed+1 xfailed 无回归）
- [Phase 43]: 43-02: 入口无关续驱 helper adrive_plan_session_to_pause_or_terminal——engine 由调用方传入，不造两套，状态只经 session_service.transition
- [Phase 43]: 43-02: clarifying-pending 短路照搬节点/工具 _maybe_suspend，保护澄清 HITL（不回归）
- [Phase 43]: 43-03(RESUME-01): 新增 _schedule_chat_plan_resume（mirror _schedule_workflow_resume：fire-and-forget + 幂等 + fail-soft）；_schedule_agent_session_resume 的 plan_research 分支由提前 return 改为委派到新函数，completed/failed 两路天然覆盖；消化 v0.7 audit D-2 缺口 a（chat barrier 从不被通知）+ b（chat 入口此后无消费者驱动 engine.advance 到 done）
- [Phase 43]: 43-03(RESUME-01): 续驱→回灌严格时序（同协程顺序）——先 adrive_plan_session_to_pause_or_terminal 续驱到终态、再用终态 status 构建 BlockingTaskResult；barrier 回灌 task_id=str(plan_session.id)（chat barrier 注册键，非 session.session_id）；成功 output=current_plan_version 文本、失败 output=""（复用 deep_analysis 回灌通道）
- [Phase 43]: 43-03(RESUME-01): T-43-TAMPER 守门以服务端权威字段 PlanSession.entrypoint==CHAT，不信 runner 可改字段；engine 由 build_orchestration_engine 单一工厂构造（无 node_execution_id 即 chat 入口），不造两套；日志仅记 plan_session_id/status/barrier_satisfied（T-43-INFO）；14 集成测试全绿（新增闭环/回归/幂等/fail-soft/失败路径 6 用例）
- [Phase 43]: 43-03: chat 入口 plan_research 续驱接线 — _schedule_chat_plan_resume（entrypoint==CHAT 守门 + 43-02 同源 helper 续驱到终态 + BarrierManager.task_completed(str(plan_session.id)) 回灌），消化 v0.7 audit D-2 a/b — chat 入口续驱与工作流入口共享 43-02 同源 helper + 单一 engine 工厂，不造两套；权威字段守门防 runner 篡改
- [Phase 43]: 43-04(RESUME-01「不造两套」收尾): 工作流节点 plan_research.execute 与 chat 工具 start_plan_research 两处内联 advance 循环重构为复用 43-02 共享 helper adrive_plan_session_to_pause_or_terminal——节点/工具/回调消费者三处真正同源一份续驱逻辑；入口私有挂起 marker 映射（NodeResult/ToolResult via _maybe_suspend）各自保留，helper 短路返回后再跑一次 _maybe_suspend 即等价；step 上限处理下沉 helper（transition(fail)→_map_terminal failed 分支）；test_clarifying_suspends_waiting_event 红线零回归（11 测全绿）
- [Phase 43]: 43-04: start_plan_research 占位文案/工具 description 由「自动回流尚未接入/当前不会自动继续」如实更新为「调研完成后将自动融合并返回 canonical 主方案」（43-03 已接通），仅改文案不动 marker/挂起协议（T-43-MISLEAD accept）
- [Phase 44]: 44-02: wave_layering 拓扑分层纯函数（services.plan_orchestration）——`build_repo_waves(execution_plan) -> ({repo_id: wave}, cycle_report|None)` 把 `execution_plan[].dependencies`（task id 引用，非 repository_id，schema 权威）建任务级 DAG，graphlib.TopologicalSorter Kahn 分层，仓 wave 取该仓所有 task 层级 **max**；空依赖退化全 wave 0（零回归命门）；环检测**复用** plan_validator.validate_plan（三色 DFS + 显式栈防 DoS）仅取 dependency_cycle 项 fail-fast 不重写；`build_repo_dep_edges` 仅跨仓成边（ra and rb and ra != rb）去同仓自环返回 sorted；半可信防御逐字对齐 plan_validator（.get(...) or []、缺 id 跳过、无效引用过滤、绝不抛）；纯函数无 IO/ORM/LLM 可与模型层并行；分层结果待 44-03 RepoCodingTaskService 写入 RepoCodingTask.wave/depends_on
- [Phase 44]: 44-03: RepoCodingTaskService 单一写入入口（INV-6）——消费 44-02 build_repo_waves/build_repo_dep_edges 落 wave/depends_on；create_tasks_for_plan get_or_create 幂等（已存在仅 wave 漂移回填）+ 同步块内 depends_on.set(...) 连仓级 DAG 边（避免 async lazy 访问）+ 返回 {repository_id: task} 按仓可索引；mark_running/done/failed/blocked 状态推进，mark_done 仅 running→done、mark_blocked 仅 pending→failed 用条件 .filter(status=...).update(...) + 影响行数判定保重复 callback no-op + 已运行/终态不强翻（保在途结果）；mark_blocked error={reason:upstream_failed,upstream:[...]} 承载 WAVE-02 下游阻断；INV-6 grep 守护镜像 test_research_inv6_guard.py（单模型 RepoCodingTask，正则天然排除 RepoCodingTaskStatus( 枚举）断言除 service 外无旁路写；8 测全绿（service 6 + guard 2）
- [Phase 44]: 44-04: wave_progression 入口无关 wave 推进 helper（services.plan_orchestration）——`aadvance_coding_waves(plan_version_id, *, service)` 严格序「① 回填 running→终态（按服务端权威 SubAgentSession.status，completed→done/error|timeout|cancelled→failed，经 subagent_session_id 标量取，T-44-TAMPER）→ ② 传递闭包 BFS/worklist 沿 dependents 反向边多跳阻断全部 failed 上游的 pending 下游（seen 去重，链 A→B→C 单次内 B、C 全 blocked）→ ③ 决策出口」；执行序是 liveness 命门——阻断必须在任何 early-return 前完成否则未派发 pending 下游永不阻断→all_terminal 永不触发→死锁（T-44-DEADLOCK）；决策出口：RUNNING 在途 aexists()→waiting（**不**靠最小 pending wave 防抢先 return waiting 死锁）/ depends_on 全 done 的 pending→dispatch 最小 wave / 无 pending 无 running→all_terminal；`acurrent_wave_all_terminal` 终态含 failed（T-44-GATE 失败仓不永挂）仅供 RUNNING 在途 wave 求值；状态只经 RepoCodingTaskService 条件更新幂等（INV-6）+ wave 从 DB 重算非内存；复用 Phase 43 callback 驱动 resume 不造两套；6 测全绿（gate/失败隔离/单跳下游阻断/2 跳传递闭包 liveness/幂等 updated_at 不变/全终态收尾）。callback 接线归 plan 05
- [Phase 44]: 44-05: AICodingNode wave 调度接线（消化 PF-07，Phase 44 收官）——`_execute_with_branch` 首发段经 `build_repo_waves` 分层 + 环 fail-fast（`error.reason=dependency_cycle` 不进 dispatch）+ `RepoCodingTaskService.create_tasks_for_plan` 建行（INV-6）后仅 dispatch 最小 wave + `mark_running`；wave 模式双 guard（plan_version 可解析 AND repo_waves 完整覆盖待编码仓），否则回退 legacy 全并行零回归（task 无 id→repo_waves 不覆盖时不误激活）；抽 `_resolve_anthropic_credentials`/`_dispatch_wave`/`_build_waiting_output` 首发与推进共用（不造两套），dispatch 失败仓 `mark_failed` 保 liveness；`_resume_after_containers` 按 `plan_version_id` 分流 wave/legacy，`_resume_wave` 经 `aadvance_coding_waves` 判 gate——`waiting`→`_resuspend_wave`（waiting != finalize）/`dispatch`→`_dispatch_next_wave`(复用 `_dispatch_wave`)+再 `waiting_event`/`all_terminal`→`_finalize_wave`，整段 fail-soft（aadvance 异常 swallow+warning 不回灌容器回调 5xx）；不双 backfill（aadvance 独占 running→终态回填，`_finalize_wave` 仅从 DB `RepoCodingTask` 全行重算 done/failed 捕获全 wave 结果）；部分成功收尾 done 出 MR/failed/blocked 如实标注(`upstream_failed`)/不自动回滚（v0.8 非目标）；wave N→N+1 由 Phase 43 `_schedule_workflow_resume` 容器回调触发节点重入自驱不另造调度（`while True`→有限收敛 `for`，上界=task 总数；无 sleep/timer/apscheduler）；4 集成测试全绿（零回归/多 wave 推进/部分成功阻断/环 fail-fast）+ test_coding_node 12 passed 零回归；340 passed 全量验收
- [Phase 45]: 45-03: ARTIFACT-01/02 端到端集成验收（测试-only，无新增生产符号）——扩充 test_coding_wave.py 三测：test_artifact_passthrough（wave1 后端 done 含 openapi TaskResult → aadvance 回填触发提取落 produced_artifacts → wave2 前端 DispatchTask.prompt 含 api/openapi.yaml 契约 + 「上游产物」段 + raw_output 不泄漏，SC-3/T-45-10）；test_artifact_passthrough_idempotent（done 仓非 RUNNING → 复调 aadvance 不再提取 → produced_artifacts 含 extracted_at 逐字不漂移，覆盖写 no-op）；test_artifact_extract_fail_soft（monkeypatch build_produced_artifacts 抛错 → wave1 仍 DONE、wave2 仍 dispatch 且注入段空、produced_artifacts=={}、advance 不冒泡，容器回调不 5xx，T-45-09）；_settle_session 增 defaulted modified_files（默认 ["f.py"]）保既有 4 wave 测试零回归；phase gate 360 passed/1 xfailed（既有 xfail）+ INV-6 守护 + Phase 44 wave/coding 零回归
- [Phase 46]: 46-02(PR-02): 新建可复用 helper `workflows/services/pr_cross_reference.py`（barrel 再导出）——`generate_cross_reference_section`（纯函数「## 关联 PR」、排除自身、单 PR 空段）+ `render_traceability_section`（async，`plan_version_id → PlanVersion → TechnicalPlan → WorkItem` 逐跳 `*_id` 标量 + `afirst`，链断/异常返回空、整函数 fail-soft，WorkItem 无 url 字段→三元组+标题、仅 prd_url 非空才附链接不臆造 URL）+ `add_cross_references`（async，自取 Repository + aresolve_git_token + get_git_platform_client，GitHub `_get_repo().get_pull().edit(body=)` / GitLab `_get_project().mergerequests.get().save()` 经 `asyncio.to_thread`，逐 PR try/except 隔离）；`_create_mr_for_repo` 成功返回加 `"description": body` 供回写拼原 body；`_finalize_and_notify` MR 循环后 `successful_mrs ≥2` 守门（D-05）→ `add_cross_references(..., plan_version_id=(plan_data or {}).get(...))` 整段 fail-soft（`# noqa: BLE001`，绝不上抛回灌 5xx，T-46-04）。D-09 备选落地：仅 wave 路径用新 helper，`CreatePRNode` 保持原样不改（同源标注 + 统一留 backlog），最小 diff/零回归；13 守护测试（纯函数/追溯真实 DB 链/回写 mock client/接线集成）+ test_coding_wave.py 7 零回归全绿。`test_batch_pr.py` 5 例 PRE-EXISTING 失败（Phase 26 移除 pr.py 的 GitCredential/decrypt_value 符号、stale patch target），out-of-scope 记 deferred-items.md
- [Phase 46]: 46-01(PR-01): `_create_mr_for_repo` 内 `MRCreateRequest` 前新增 per-repo 解析 `resolved_target = repository.default_branch or base_branch or "main"`，`target_branch=base_branch` → `resolved_target`——各仓 MR 锚定各仓自己的 `Repository.default_branch`（修复多仓 default_branch 不一致时所有 MR 共用第一个仓 base_branch 打错目标分支病根）；fallback 链严格保序三级兜底保单仓/同 default_branch 多仓与 Phase 45 逐字等价（零回归命门）；不改 `_finalize_and_notify` 调用处 / `_execute_with_branch` node 级 base_branch / 缺凭证 fail-soft 分支（最小 diff）；守护测试 `test_coding_pr_target_branch.py` 直测私有方法（MagicMock 仓 + AsyncMock client 捕获 MRCreateRequest）4 测全绿（per-repo A=develop/B=release/x + 零回归 + fallback + 缺凭证 fail-soft），test_coding_wave.py 7 测零回归
- [Phase 44]: 44-01: RepoCodingTask 逐项镜像 RepoResearchTask 形状立操作态模型——plan_version 用真实 FK（CASCADE, related_name=coding_tasks，区别于 PlanSession.current_plan_version 软 UUID 引用，本 phase 无 36↔37 迁移耦合约束）；状态 4 态去 stale（编码期无重索引语义）；新增 wave int / depends_on M2M self（symmetrical=False, related_name=dependents 有向 DAG）/ produced_artifacts JSON（Phase 45 才写内容）/ follow_openspec bool（v0.9 才消费）；模型层零业务方法守 INV-6；迁移 0017 用 makemigrations 自动生成（M2M self through 表须 Django 自动建），dependencies 含 delivery 0016 + repositories 0036 + subagent 0013

- [Phase 51]: 51-01: create_tasks_for_plan 首次消费 follow_openspec——`_create_tasks_sync` 同步块内按 `Repository.facets.get("methodology")=="SDD"`（Phase 48 大写写入）置 defaults `follow_openspec`，已存在 task 的 wave/follow_openspec 漂移合并到同一 save 的 update_fields 幂等回填（相等不写）；facets 用 `.values_list("facets", flat=True).first()` 标量查（async 安全禁裸 lazy-FK，D-51-6）。新增 `mark_gate_blocked(task, reason, spec_status)`——gate 拦截唯一写入入口（INV-6），逐字镜像 `mark_blocked` 条件 `.filter(id, status=PENDING).update(status=FAILED, error={reason, spec_status})` 仅 pending→failed、非 pending/重复 no-op，error payload 携 reason（spec_not_approved / gate_error）+ spec_status（status|missing|unknown）；INV-6 grep 守护补正向断言 mark_gate_blocked 经 service
- [Phase 51]: 51-02: AICodingNode `_apply_openspec_gate` 独立可测 helper（GATE-01 fail-closed）——仅 wave 模式（service+tasks_by_repo 非空）执行、legacy/非 wave 短路零回归（不触任何 SddSpec 查询）；follow_openspec=False 放行不查 spec，True 校验关联 SddSpec（plan_version_id × repository_id）`.order_by("-updated_at").afirst()` status==APPROVED 放行、未批准经 mark_gate_blocked(spec_not_approved, status|missing) 拦截；单仓 try/except fail-closed（gate_error,unknown）隔离异常绝不冒泡崩 wave；拦截仓并入 `_dispatch_wave` failed 返回 → aadvance 传递闭包阻断下游 upstream_failed。gate 在 _dispatch_wave 顶部一处生效（首发+wave 推进两路覆盖）。GATE-02 server 半：`_run_repo_coding` 加 `follow_openspec` 参数，approved SDD 仓 metadata 注入 `env_FRIDAY_TASK_FOLLOW_OPENSPEC="true"`（PF-06 逐键范式，openspec_env 与 git_env/anthropic_env 同形），非 SDD/legacy 不含该键；docstring 字面 SddSpec(...) 改全角括号避 INV-6 grep 误判（Rule 1 自修）
- [Phase 51]: 51-03: task GATE-02 task 半——`TaskConfig.follow_openspec: bool=False`（env_prefix 自动映射 FRIDAY_TASK_FOLLOW_OPENSPEC，缺省 False 零回归）；`_get_system_prompt` 末尾 `if bool(self.config.follow_openspec): base + "\n\n" + self._openspec_guidance()` 条件追加，`_openspec_guidance` 独立 helper（静态中文 openspec 指引段，无外部输入拼接无注入面），缺省路径返回 base 逐字等现状；`.claude/skills` 复用既有 `setting_sources=["project"]` 原生加载不改；既有 test_callback.py 两处 MagicMock-config 用例显式 `config.follow_openspec=False` 防真值 Mock 误触 openspec 追加致零回归断言失真（T-51-MOCK）
- [Phase 56]: 56-01: compat progress 纯函数机制层 server/compat/progress.py——tool_event_to_progress 仅读 tool_name 查中文映射表（search_rag/grep/get_file/仓库分析路由），TOOL_USE_RESULT/未知/缺名一律 None（保守静默 OQ-3），绝不读 tool_input/result/error（INV-5）；make_reasoning_chunk 复用 sse_encode 产 reasoning_content chunk（结构与 THINKING 逐字一致）；不 import §15 event_taxonomy（P-1，仅语义对齐）。translate_stream 新增 TOOL_USE_*→reasoning_content 分支（None 静默/非空 yield），绝不写 delta.tool_calls/finish_reason=tool_calls（TRACE-02）。**DEVIATION D-1**：compat _build_runner 不绑定 tools → TOOL_USE_* 永不发射 → 本 plan 恒走降级产 0 progress（机制预埋 + 前向兼容 + Phase 57 复用），可见效果由 Plan 02（真实 RAG 检索 progress 合成）兑现。tests/compat/ 17→43 passed
- [Phase 57]: 57-02: Anthropic /v1/messages 流式 SSE + thinking block trace（兑现 ANTHROPIC-02）——translate_stream 加 prelude_texts，命中 RAG 时在正文 text block 前发 thinking content block（index 单线性计数：thinking 0、text 紧随；content_block_start(thinking,0)→thinking_delta×N→content_block_stop(0)），承载 retrieval_to_progress 命中计数 trace；无 prelude 时不发 thinking block、text 占 0，与 Plan 01 byte-eq 零回归（None/[]/省略三者结构等价）。新增 TOOL_USE_START/RESULT 前向兼容分支复用 progress.py 的 tool_event_to_progress（DEVIATION D-1：compat 无 tools 永不触发，纯预埋，仅 thinking block 已开时 emit）。MessagesView.post 经 prepare_messages_with_meta 单次检索取 (lc_messages,retr)，流式 prelude_texts=retrieval_to_progress(retr)→StreamingHttpResponse 经 _stream_anthropic 包 translate_stream(prelude_texts=...)，非流式保持 aggregate_message 忽略 retr（content 零回归命门）。_stream_anthropic 异常→anthropic_error_event 不泄漏 traceback、不发 message_stop，Anthropic 流不发 [DONE] 以 message_stop 收尾。INV-5/TRACE-02：THINKING 静默 continue、绝不发 tool_use block、sentinel（CTX/Q/CoT）全流不外透仅命中计数语义。progress.py 逐字不改、OpenAI 端点零回归，tests/compat 94→109 passed。view 级流式集成测断言 thinking_delta 严格先于首个 text_delta
- [Phase 56]: 56-02: compat 真实 RAG 检索 progress 透出（兑现 TRACE-01 可见效果，Option C 的 B 部分）——retrieval_to_progress(result)->list[str] 命中（final_context 非空）派生 ["正在检索 RAG…","检索完成，命中 N 处"]、未命中/None 返 []（N=sum(layers.result_count)，layers 空回退 len(repository_ids)，max(N,0)），只读非敏感计数标量绝不内联 final_context/query/items/score（INV-5）。request_handler 抽 _prepare 内核返回 (lc_messages, 检索结果|None)，prepare_messages 委托保留旧签名（4 测不回退），新增 prepare_messages_with_meta 暴露元数据。translate_stream 新增 prelude_texts（role chunk 后、正文前以 reasoning_content 透出；空则逐字等价）。views post 统一 prepare_messages_with_meta 单次检索，流式派生 prelude、非流式忽略 retr（content 零回归、不二次检索）。DEVIATION D-1 兑现：检索流前同步发生不发 AgentEvent（F-2），故 view 据非敏感计数元数据合成 progress（b2 元数据驱动）而非事件映射。tests/compat 43→55 passed。view 级 post(stream=True) 端到端断言两条检索 progress 先于正文且全流无 tool_calls
- [Phase 58]: 58-01: CardKit 封装层（Wave 1）——FeishuIMClient 手写 httpx 新增 4 个 CardKit v1 方法（create_card_entity POST /cardkit/v1/cards 建实体返 card_id / send_card_entity 复用 send_message interactive 引用 card_id / stream_card_content PUT elements/{id}/content 全量文本+sequence / settle_card_stream PATCH settings streaming_mode=false），复用 get_tenant_access_token + httpx.AsyncClient + structlog，不引 lark-oapi cardkit SDK、不新建 feishu_cardkit.py（直接进 feishu_im.py 与 send_card/update_card 同类，D-1）；code!=0 统一抛 FeishuIMError（F-5 降级判定基础）；FeishuIMService 4 同构委托。sequence 由调用方严格递增透传、方法层不内置计数器（P-2 留 Wave 2）；content 全量非 delta 不做累积（P-4）；uuid 关键字默认空串非空才写 body（D-6 幂等）。bot_cards 新增 build_streaming_card_v2（schema 2.0 流式卡 + config.streaming_mode/update_multi/streaming_config + 单 markdown 元素带 element_id）+ build_answer_markdown（终态 answer+引用+usage 单 markdown 串，复用 _reference_lines + usage 行格式与 build_answer_card 逐字一致保降级一致，D-3）。零回归：send_card/update_card/send_message/get_tenant_access_token + 既有所有 builder 符号逐字不变。新建 test_feishu_cardkit.py（respx 形状单测，token 缓存预置避真实鉴权，10 例）；31 passed（cardkit+bot_cards+card_retry）
- [Phase 59]: 59-01: 建群封装 + writeback 入口（Wave 1）——FeishuIMClient.create_chat 手写 httpx 一次 `POST /im/v1/chats` 建群即拉人单步（body 仅放非空字段：name 恒放 + user_id_list≤50 + bot_id_list≤5 + 可选 owner_id/description；query user_id_type 默认 open_id，set_bot_manager 仅 owner_id 非空且需设管理员时下发 "true"），复用 get_tenant_access_token + httpx + structlog，对齐 add_bot_to_chat（NOTE-1：仅 raise RateLimitError，不加 @retry 避免单测真实 sleep）；code!=0→FeishuIMError、99991400→RateLimitError、成功取 data（含 chat_id）；FeishuIMService.create_chat 同构委托。WorkItemService.awriteback_feishu_chat_id（feishu_chat_id writeback 单一入口，INV-6/P-5）——三元组定位 + save(update_fields=["feishu_chat_id","updated_at"])，WorkItem 不存在返回 False 不抛（fail-soft 留调用方）、DB 异常不吞；@sync_to_async 包同步块；feishu_chat_id 绝不进 _MIRROR_FIELDS、绝不在 _refresh_mirror 写（否则 sync 覆盖回空）。INV-6 grep 守护扩 feishu_chat_id（正则 `\.feishu_chat_id\s*=\s*[^=]` 排除比较；旁路写禁止 + writer-actually-writes 正向有效性，复用 _is_scanned_for_inv6 剪枝）。零回归：add_bot_to_chat/ensure_bot_in_chat/get_chat_members/_refresh_mirror/_MIRROR_FIELDS/upsert 逐字不变（diff 纯新增）；411 passed。Wave 2（59-02）在 feishu_chat.py 新增 CreateGroupChatNode 接线消费
- [Phase 59]: 59-02: CreateGroupChatNode 节点接线（Wave 2，兑现 GROUP-01 SC-1/2/3）——feishu_chat.py 新增 `CreateGroupChatNode`（@register_node 自动注册 `create_group_chat`，全局唯一不撞 fetch/join_group_chat；`NodeCategory.INTEGRATION`/`execution_mode="server_local"`，镜像 Fetch/Join 节点结构 + 全中文 config_schema），inputs=[default]、outputs=[default(成功),error(失败)]。execute：render 群名 + `_parse_id_list`（member_ids 三形态：模板 get_template_value 保留 list / JSON 列表兼容单引号 / 逗号分隔，逐项 strip 去空，镜像 normalize_repositories）→ 缺群名 **或** 缺成员 → failed+error handle（D-4，建群+拉人核心空成员无意义）→ `FeishuIMService.create(project).create_chat(name, user_id_list=, owner_id=, description=, user_id_type=open_id)`（建群即拉人单步，消费 Wave 1）；`except FeishuIMError → failed+error handle`（D-7 建群失败）。输出 `{chat_id(一等),chat_name,owner_id(data.get 容错空串 P-3),source:"create_group_chat",writeback:{attempted,success}}`（D-8）。可选 writeback（D-7 fail-soft）：仅 project_key+work_item_id 均非空才触发，`int()` 失败 warning 跳过（attempted=False，P-11）；`WorkItemService().awriteback_feishu_chat_id(project_key,work_item_type,int(work_item_id),chat_id)`（函数级 import 避循环依赖）经 `try/except Exception`+log.warning 包裹——DB 异常/返回 False 节点**仍 completed** 返回 chat_id，绝不冒泡（P-6 INV-6 单一入口，节点无 WorkItem.objects/.save 直接写表）。绝不改 FetchGroupChatNode/JoinGroupChatNode（git diff 仅 import 行扩展 FeishuIMError）。测试 patch 源模块类属性 `delivery.services.work_item_service.WorkItemService.awriteback_feishu_chat_id`（节点函数级 import，patch feishu_chat 模块不生效，NOTE-3）。新增 14 例（happy/三形态/缺参/建群失败/writeback happy·fail-soft·不存在·未配/自动注册）；34 passed（含既有零回归）+ Wave 1+2 60 passed
- [Phase 53]: 53-02: AuditService.emit/aemit 是 AuditEvent 唯一写入入口（INV-6）——sync emit + async aemit(via sync_to_async) 收口于唯一 AuditEvent.objects.create；入口内强制脱敏 before/after/metadata（_redact_audit_payload：key-name 命中整体抹值 + 值级密钥正则/高熵 Shannon 只抹叶子，调用方传明文也绝不落明文）；整段 fail-soft 吞异常 + audit.emit_failed warning(仅记 action/target_type)，绝不冒泡阻断主操作；aemit actor 字段访问全在 sync 块内(async 安全)；redaction.py 复刻(非 import)sensitive_detect/work_item_service 正则常量守 INV-3；taxonomy.py 15 种子 Final[str]+ALL_ACTIONS+purge.* RESERVED 预留(具体值 Phase 54 补)；INV-6 grep 守护断言无旁路写+writer-actually-writes 反向断言。AUDIT-01/02 整体闭环 — AUDIT-01/02 要求单一写入入口 + append-only + fail-soft + 凭证脱敏；emit 地基供 Phase 54 任意敏感操作安全埋点（绝不落明文/绝不阻断/写入唯一收口）

### Pending Todos

[From .planning/todos/pending/ — ideas captured during sessions]

None.

### Blockers/Concerns

[Issues that affect future work]

- ✅ ~~v0.2.0 follow-up：实时明文 PAT 通道（contextvar）未接入，RemoteTool 链路休眠~~ —
  已于 2026-06-14 接入（commit 8cb50e928）：带 `friday_pat_` Bearer 的手动触发经请求级
  ContextVar → start_execution → ExecutionContext 瞬态字段下传，AICodingNode 据此注入
  `env_FRIDAY_TASK_USER_TOKEN`。明文绝不落库/进日志（PAT-02 守护测试通过）。
  **剩余**：chat/MCP 编码 dispatch 路径（`coding_session_service`）的 PAT 注入未覆盖；
  真实容器端 RTOOL-02/03/04 运行时仍需带 PAT 的真实 dispatch + 容器 E2E 人工验收（见 Deferred）。

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260610-oug | 修复仓库 URL 提示文案为仅支持 HTTPS，并将所有英文校验/错误提示汉化 | 2026-06-10 | c4c60c4f | [260610-oug-url-https](./quick/260610-oug-url-https/) |
| 260610-shc | OIDC 回调 URL 与登录跳转优先消费「站点 Host」(site_host) 系统设置 | 2026-06-10 | b01dc066 | [260610-shc-site-host-oidc](./quick/260610-shc-site-host-oidc/) |
| 260610-qmv | 修复 compose 部署下任务容器回调失败（发布 runner callback 端口）并抑制 claude CLI 403 遥测噪音 | 2026-06-10 | 68ddaa4c | [260610-qmv-compose-runner-callback-claude-cli-403](./quick/260610-qmv-compose-runner-callback-claude-cli-403/) |
| 260611-0pm | 打磨第 1 批：全仓口径对齐 + 过程痕迹清洗 + 社区脚手架 | 2026-06-11 | 7f0c4381 | [260611-0pm-polish-batch1](./quick/260611-0pm-polish-batch1/) |
| 260611-fky | 打磨仓库列表索引完成界面视觉 | 2026-06-11 | fa5e1b0a | [260611-fky-repository-list-polish](./quick/260611-fky-repository-list-polish/) |
| 260612-crc | 修复 clarification 答复后 resume 后台任务因继承请求 contextvars 崩溃、会话永久卡在等待态 | 2026-06-12 | e6374837 | [20260612-fix-clarification-resume-context](./quick/20260612-fix-clarification-resume-context/) |
| 260611-g31 | 打磨工作流列表与执行监控界面视觉 | 2026-06-11 | 9bc59746 | [260611-g31-workflow-execution-polish](./quick/260611-g31-workflow-execution-polish/) |
| 260611-ghb | 统一工作流卡片高度并收纳节点标签 | 2026-06-11 | c7af69b6 | [260611-ghb-workflow-card-uniform](./quick/260611-ghb-workflow-card-uniform/) |
| 260612-cifix | 修复 CI：smoke 列表移除已删除的 test_tool_bindings.py | 2026-06-12 | ec839757 | — |
| 20260617-csb | 会话列表 SDD/技术方案/编码徽标（PlanSession.conversation_id 软引用 + list annotate）+ 仓库卡片 SDD 强调/水印 | 2026-06-17 | (pending) | [20260617-conversation-sdd-coding-badges](./quick/20260617-conversation-sdd-coding-badges/) |

## Deferred Items

Items acknowledged and deferred at milestone close. 2026-06-14 复盘清理后分三类：✅ 已解决、
🔒 需外部系统/全新实例（本地无法闭环）、🖐 纯观感人工验收（可后续浏览器抽验）。

### 🔒 Acknowledged at v0.8.0 close（2026-06-17）

里程碑关闭前 open artifact 审计 4 项，全部为既有/已知 deferred，确认后归档继续关闭：

| Category | Item | Status |
|----------|------|--------|
| uat_gap | Phase 43 43-UAT.md — 2 pending scenarios（真实 runner+Docker resume / deep-research 容器续驱 E2E） | deferred（里程碑级，需真实环境） |
| verification_gap | Phase 43 43-VERIFICATION.md [human_needed]（同上真实容器 E2E 两项） | deferred（里程碑级，需真实环境） |
| quick_task | 260610-oug-url-https [unknown] | 实为已完成（有 SUMMARY.md，标记过时） |
| quick_task | 260611-ghb-workflow-card-uniform [unknown] | 实为已完成（有 SUMMARY.md，标记过时） |

v0.8.0 follow-up（已记 PROJECT.md Backlog）：chat 编码入口（`coding_session_service`）cross-ref / 遇阻 HITL 接线；Phase 26 遗留 `test_batch_pr.py` 5 例 stale patch target 修复；多仓 wave 编码/PR/HITL 真实 runner+Docker 容器 E2E。

### ✅ Resolved 2026-06-14（历史遗留清理）

| Category | Item | Resolution |
|----------|------|------------|
| tech_debt | VALIDATION.md（18-21）nyquist_compliant frontmatter 未翻转 | 回写 true（commit 37a3bd6b2，复核 tests/workflows/ 479 passed） |
| tech_debt | v0.3.0 W1：交付知识 `searchDeliveryKnowledge` 无 UI 消费 | index 占位页改为真实搜索页（5435fef23），浏览器实测搜索/空态正常 |
| tech_debt | v0.3.0 W2：timeline 节点级 provenance 未填充 | 前端渲染 node.provenance + 修后端 code_change 跨版本串味 bug（5435fef23） |
| tech_debt | v0.3.0 W3：graph enrich/related 边类型 | related.py 多跳取真实 edge.relation + 前端 relation 标签（5435fef23） |
| scope_v2 | Phase 21 project_ids/exclude_* 触发负向过滤 | _include/_exclude + Project UUID→feishu_project_key 映射（9ab638f13） |
| scope_v2 | Phase 20 input.*/trigger.* 严格静态校验 + IssuesPanel 点击居中 | graph_validator 严格校验（宽松降级）+ provide/inject fitView 居中（9ab638f13） |
| follow-up | v0.2.0 实时明文 PAT 通道未接入（RemoteTool 休眠） | ContextVar → ExecutionContext 瞬态字段下传，点亮 AICoding RTOOL（8cb50e928） |
| quick_task | 260610-oug-url-https / 260611-ghb-workflow-card-uniform（状态 unknown） | 复核两者均有 SUMMARY.md，确认已完成（标记过时，非遗留） |

### 🔒 需真实外部系统才能闭环（本地无法验证，保持 deferred）

| Item | 需要的环境 |
|------|-----------|
| Phase 14 真实 git platform 超大 diff 截断（TD-14） | 真实 GitLab/GitHub 大 MR |
| Phase 18 真实容器回调续跑 E2E | runner + Docker + 任务容器 + 真实编码 agent |
| Phase 21 真实飞书事件触发 + WS 断线降级观感 | 真实飞书应用 + 事件推送 |
| RTOOL-02/03/04 运行时（带 PAT 注入容器端到端） | 带 PAT 的真实 dispatch + 容器执行（通道已接入，待真实环境验收） |

### 🖐 纯观感人工验收（可后续浏览器抽验；2026-06-14 已部分实测）

| Item | 2026-06-14 状态 |
|------|----------------|
| Phase 17 变量所选即所得 / 端口防护 / 选择器去重（17-HUMAN-UAT 3 pending） | 有 P17 UAT 种子工作流；运行态错误展示由 tests/workflows 覆盖；未逐项点击 |
| Phase 19 画布编辑观感 | ✅ 浏览器实测：节点库 + 画布编辑器正常渲染（全节点类型可见） |
| Phase 20 IssuesPanel 交互 + 模板端到端执行 | ✅ 浏览器实测：编辑器打开 + 保存流程执行正常；校验逻辑由 graph_validator 测试覆盖 |
| Phase 21 suspended 显示 | 有 P21 suspended UAT 种子工作流 + 执行记录；前端 ExecutionStatus 由 vitest 覆盖 |
| Phase 01/02/06–11 人工验收 | 多为首启向导（需 no-superuser 全新实例）/ 身份令牌；本实例已有 superuser，需独立环境复验 |

## Session Continuity

Last session: 2026-06-20
Stopped at: v0.12.0 里程碑 roadmap 创建完成（ROADMAP.md Phases 60–64 + STATE.md milestone overview + REQUIREMENTS.md traceability 16/16）
Resume file: None
Next: `/gsd-plan-phase 60`（durable 底座地基）

## Operator Next Steps

- v0.12.0 里程碑 roadmap 已定稿，Phases 60–64 待规划/执行。
- 逐 phase 推进：`/gsd-plan-phase 60` → `/gsd-execute-phase 60` …（严格顺序 60→61→62→63→64）。
- 或新会话 autonomous 跑完整个里程碑：`/gsd-autonomous`。
