# Roadmap: Friday AI

## Milestones

- 🚧 **v0.12.0 弹性任务底座（durable 任务队列与多副本就绪）** — Phases 60–64 (planning) — durable 任务队列 + 多副本竞争消费/周期 rescue/leader 选主/优雅终止/弹性伸缩 + runner k8s Job executor
- ✅ **v0.11.0 开放与协作** — Phases 56–59 (shipped 2026-06-17) — 里程碑审计 PASS（6/6 需求、INV-5/INV-6 成立）见 [audit](./milestones/v0.11.0-MILESTONE-AUDIT.md)
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

> 跨里程碑前瞻路线（v0.5–v0.11）与设计底座见 `ROADMAP-vNext.md`、`DOMAIN-MODEL.md`、`PREFLIGHT.md`。本里程碑设计底座为前置 PoC 调研结论（Procrastinate 3.8.1 / Py3.14 / Django 6.0 / psycopg 3.3，PASS）+ 现有 `server/resumable/`（lease/CAS/recovery 范式）。

## Phases

### 🚧 v0.12.0 弹性任务底座（durable 任务队列与多副本就绪）(Phases 60–64 — planning)

**Milestone Goal:** 把现有"可恢复长任务底座"（`server/resumable/`：DB 真相源 + lease/heartbeat + CAS claim + 启动恢复）演进为生产级 **durable 任务队列**——**采用 Procrastinate（3.8.1），藏在 Friday 自己的 `DurableTaskService` 适配层后**（业务代码不直接依赖 Procrastinate；Postgres 走 Procrastinate、SQLite/无 `DATABASE_URL` 退化 in-process 非 durable fallback）。统一承载索引/图谱/PageIndex/爬取等后台任务，支持多副本竞争消费、租约心跳、周期 rescue、leader 选主、优雅终止与按队列深度弹性伸缩；以「链接爬取+入库」durable 队列为首个用户可见垂直切片；完成 k8s/compose 部署硬化与 runner 改 k8s Job executor，全方位支持 k8s/k0s 多副本/弹性伸缩。执行语义 **at-least-once**（不承诺 exactly-once）——靠 handler 幂等 + 外部副作用 fencing/outbox。

- [x] **Phase 60: durable 底座地基** (0/4 plans) - 立 `DurableTaskService` 适配层（Postgres→Procrastinate / SQLite→in-process fallback）+ `FRIDAY_PROCESS_ROLE` 启动副作用门禁 + 周期 rescue/leader 单例（替代 flock 与仅启动补扫）+ Postgres 专项 CI；所有后续阶段的地基 — DURABLE-01, DURABLE-02, DURABLE-03, DURABLE-04 (completed 2026-06-19)
  - [x] 60-01-PLAN.md — DurableTaskService 适配层 + in-process fallback + 队列常量 + roles helper + no-import 守护（wave 1）
  - [x] 60-02-PLAN.md — FRIDAY_PROCESS_ROLE 门禁三处 AppConfig.ready() 启动副作用（wave 2）
  - [x] 60-03-PLAN.md — Procrastinate 后端 + 独立 worker + 周期 stalled rescue 单例 + postgres_queue 测试（wave 2）
  - [x] 60-04-PLAN.md — Postgres 专项 CI workflow（postgres:17-alpine service + postgres_queue marker，wave 3）
- [x] **Phase 61: 迁移 index/graph + 收口 ResumableTask** (0/4 plans) - 把现有 index/graph 从 ResumableTask/background_runner 迁到 `DurableTaskService`；一次性迁移存量在途行（不双跑）；启动 reconcile 改为仅无 durable job 接管才回收；建立 handler 幂等基线 — MIGRATE-01, MIGRATE-02, IDEMP-01 (completed 2026-06-19)
  - [x] 61-01-PLAN.md — durable index/graph/page_index 任务壳 + 双后端 payload adapter + DurableConfig.ready 注册修复（wave 1）
  - [x] 61-02-PLAN.md — 迁移全部 5 处 index/graph 入队点改 defer + deterministic key + 重复投递/执行幂等守护（wave 2）
  - [x] 61-03-PLAN.md — 启动 reconcile 改"仅无 durable job 接管才标 FAILED" + 同步判定 helper（wave 2）
  - [x] 61-04-PLAN.md — 一次性迁移命令 + resumable MIGRATED/legacy_durable_job_id 迁移 + background_runner 降级（wave 3）
  - [x] 61-01-PLAN.md — durable index/graph/page_index 任务层 + 双后端 payload adapter + DurableConfig.ready 双后端注册 + 幂等基线（wave 1）
  - [x] 61-02-PLAN.md — 迁移全部 5 处 index/graph 入队点改 DurableTaskService.defer + 重复投递去重/grep 零残留守护（wave 2）
  - [x] 61-03-PLAN.md — 一次性迁移命令 + ResumableTask MIGRATED/legacy id 迁移 + reconcile "无 durable 接管才标 FAILED" + background_runner 降级（wave 2）
- [x] **Phase 62: 爬取+入库 durable 队列 + PageIndex 接入** (0/3 plans) - 链接爬取+入库改 durable 任务（入队/开始/停止/重试/断点恢复，刷新与容器重建不丢，前后端可用，首个用户可见垂直切片）；PageIndex/TOC 按 hash 幂等接入 — CRAWL-01, CRAWL-02, PAGEIDX-01 (completed 2026-06-20)
  - [x] 62-01-PLAN.md — run_crawl_ingest durable 任务体 + IngestRun 扩列(QUEUED/STOPPED/durable_job_id/idempotency_key)迁移 + 队列动作端点(enqueue/list/detail/start/stop/retry) + 幂等守护（wave 1）
  - [x] 62-02-PLAN.md — 填充 run_page_index(build_full + target-hash 跳过) + CorpusTreeSnapshot.source_hash + tree_views.py 裸 background_runner → durable defer（wave 2）
  - [x] 62-03-PLAN.md — BatchIngestPanel 后端恢复队列 + 行内开始/停止/重试 + zh-CN.json crawlQueue.* + vitest 守护（wave 2）
- [x] **Phase 63: 部署硬化 + 外部副作用 fencing** (0/3 plans) - worker 优雅终止（SIGTERM 释放租约）；compose 与 helm 同构拆 web/worker/scheduler；KEDA Postgres scaler + PDB + 多副本 Redis channel layer 强约束；外部副作用（飞书通知/建群、MR/PR 创建）上 fencing/outbox — DEPLOY-01, DEPLOY-02, DEPLOY-03, IDEMP-02 (completed 2026-06-20)
- [ ] **Phase 64: runner k8s Job executor** (0/? plans) - runner 抽 executor 接口（docker/k8s 两实现，docker 零回归）+ k8s Job executor 实现（去 docker.sock，经 k8s API 起 Job/Pod，RBAC/日志流/清理，k0s/containerd 友好）；相对独立排最后 — RUNNER-01, RUNNER-02

## Phase Details

### Phase 60: durable 底座地基

**Goal**: 立起统一 durable 任务底座——`DurableTaskService` 适配层隔离队列实现 + 进程角色门禁收口启动副作用 + 周期 rescue/leader 单例，作为所有后续阶段的地基
**Depends on**: Nothing（复用现有 `server/resumable/` lease/CAS/recovery 范式 + 前置 PoC PASS 结论；Postgres 默认部署 `docker-compose.yaml:37` / `settings.py:243`）
**Requirements**: DURABLE-01, DURABLE-02, DURABLE-03, DURABLE-04
**Success Criteria** (what must be TRUE):

  1. Postgres 部署下独立 worker 进程能消费 durable 任务，业务代码经 `DurableTaskService.defer/get/cancel/retry_stalled`（含 idempotency_key + queue/priority）入队/查询/取消，且不直接 import Procrastinate
  2. 无 `DATABASE_URL`/SQLite dev 下退化为 in-process 非 durable fallback，`make dev`/pytest 开箱即用不需 Postgres
  3. `FRIDAY_PROCESS_ROLE=worker|migrate` 进程不执行 `repositories/codegraph/resumable` 的 web-only reconcile/sweep/startup jobs（无"业务表不存在"warning、无误杀在途任务）
  4. kill 掉一个 worker 后，另一 worker 经周期 `retry_stalled_durable_jobs`（`queueing_lock` 单例 leader）接管在途 stalled 任务重投，多副本下只有一个 leader 扫 stalled（替代 flock 与仅启动补扫）
  5. Postgres 专项 CI job（GH Actions service container + `postgres_queue` marker）绿，覆盖 defer/priority/retry-backoff/stalled rescue/并发 worker 竞争/SQLite fallback，与默认 SQLite 测试路径共存

**Plans**: 4 plans (3 waves)

- 60-01 (wave 1): DurableTaskService 适配层 + in-process fallback + 队列常量 + roles helper + no-import 守护 — DURABLE-01
- 60-02 (wave 2): FRIDAY_PROCESS_ROLE 门禁三处 AppConfig.ready() 启动副作用 — DURABLE-02
- 60-03 (wave 2): Procrastinate 后端 + 独立 worker + 周期 stalled rescue 单例 + postgres_queue 测试 — DURABLE-01, DURABLE-03
- 60-04 (wave 3): Postgres 专项 CI workflow（postgres:17-alpine + postgres_queue marker）— DURABLE-04

### Phase 61: 迁移 index/graph + 收口 ResumableTask

**Goal**: 把现有 index/graph 后台任务从 ResumableTask/background_runner 迁到 `DurableTaskService`，一次性迁移存量在途行（不三套并存），并建立 handler 幂等基线
**Depends on**: Phase 60（依赖 `DurableTaskService` 适配层 + 进程角色门禁 + 周期 rescue）
**Requirements**: MIGRATE-01, MIGRATE-02, IDEMP-01
**Success Criteria** (what must be TRUE):

  1. 代码库索引与知识图谱经 `DurableTaskService.defer`（queue=index/graph，`idempotency_key=index:{repo_id}`/`graph:{repo_id}`）入队执行，`IndexHistory`/`GraphBuildHistory` 仍为进度/结果真相源，FileIndex/GraphFileIndex checkpoint 跳过保留
  2. 升级时一次性 migration command 把存量 PENDING/RUNNING `resumable_tasks`（index/graph）按 deterministic idempotency key 转 durable job，旧行标 migrated/cancelled 记 legacy id（不双跑）
  3. 启动 reconcile 改为"仅确认无 durable job 接管时才把 RUNNING 标 FAILED"，不再误杀在途任务；`background_runner` 降级为仅 SQLite dev fallback / 轻任务，生产 durable 任务不三套并存
  4. index/graph handler 在重复投递/重复执行（at-least-once）下经 checkpoint/deterministic key/upsert 结果一致，守护测试覆盖"同一任务重复投递/重复执行不产生重复数据或重复副作用"

**Plans**: 4 plans (3 waves)

- 61-01 (wave 1): durable index/graph/page_index 任务壳 + 双后端 payload adapter + DurableConfig.ready 双后端注册修复 + 双后端契约/page_index 占位幂等守护 — MIGRATE-01, IDEMP-01
- 61-02 (wave 2): 迁移全部 5 处 index/graph 入队点改 DurableTaskService.defer + deterministic key + 重复投递/执行/grep 零残留守护 — MIGRATE-01, IDEMP-01
- 61-03 (wave 2): 启动 reconcile 改"仅无 durable job 接管才标 FAILED" + has_active_durable_job 同步判定 helper — MIGRATE-02
- 61-04 (wave 3): 一次性迁移命令 + ResumableTask MIGRATED/legacy_durable_job_id 迁移 + background_runner 降级 — MIGRATE-02

### Phase 62: 爬取+入库 durable 队列 + PageIndex 接入

**Goal**: 把链接爬取+入库改为 durable 任务（首个用户可见垂直切片，前后端贯通），并把 PageIndex/TOC 按 hash 幂等接入 durable queue
**Depends on**: Phase 60（durable 底座）、Phase 61（迁移范式 + 幂等基线）
**Requirements**: CRAWL-01, CRAWL-02, PAGEIDX-01
**Success Criteria** (what must be TRUE):

  1. 用户贴链接后爬取+入库作为 durable 任务入队，后端支持入队/查询/开始/停止/重试/断点恢复，刷新页面与 `docker compose up -d`/Pod 重建后任务不丢、自动续跑（DB 真相源）
  2. 前端爬取任务队列面板（`BatchIngestPanel`）可贴链接入队、展示队列列表 + 实时状态、行内开始/停止/重试，刷新后从后端恢复（不再依赖组件内存 `batchId`/`ref`），i18n 默认中文
  3. 入库 at-least-once 幂等（复用现有 upsert/`IngestRun` 范式），重复执行不产生重复数据
  4. PageIndex/TOC/summary/tree 生成接入 durable queue（收口 `tree_views.py` 等裸 `background_runner` 路径），按 target hash 幂等（hash 未变跳过），重复执行安全

**Plans**: 3 plans (2 waves)

- 62-01 (wave 1): run_crawl_ingest durable 任务体 + IngestRun 扩列迁移 + 队列动作端点 + 幂等守护 — CRAWL-01
- 62-02 (wave 2): run_page_index 真实生成(build_full + target-hash 跳过) + source_hash 列 + tree_views durable defer — PAGEIDX-01
- 62-03 (wave 2): BatchIngestPanel 后端恢复队列 + 行内动作 + zh-CN.json + vitest 守护 — CRAWL-02

**UI hint**: yes

### Phase 63: 部署硬化 + 外部副作用 fencing

**Goal**: 完成多副本/弹性伸缩部署硬化（优雅终止 + compose/helm 拆 workload + KEDA/PDB/Redis 强约束），并给外部副作用任务上 fencing/outbox 确保 at-least-once 不产生重复外部动作
**Depends on**: Phase 60（worker/scheduler 角色 + leader）、Phase 61（迁移完成）、Phase 62（多队列负载就绪）
**Requirements**: DEPLOY-01, DEPLOY-02, DEPLOY-03, IDEMP-02
**Success Criteria** (what must be TRUE):

  1. worker 捕获 SIGTERM 后停止领取新任务、跑完在途或释放/缩短租约让其他副本快速接管（非干等租约过期）；helm 为 worker 配 `terminationGracePeriodSeconds`（> 心跳间隔）
  2. compose 与 helm 同构拆 web/worker/scheduler 三类 workload（同镜像不同 command + `FRIDAY_PROCESS_ROLE`），scheduler 单例 leader 承载 cron + 周期 rescue，compose 升级（`up -d` 拉新镜像重建）不破坏既有部署
  3. KEDA Postgres scaler 按队列深度（`COUNT(status='todo')`）伸缩 worker（支持 cooldown 防抖、可按 queue 维度）+ PodDisruptionBudget + 多副本强制 Redis channel layer（未开启时 fail-closed 提示）
  4. 有外部副作用的任务（飞书通知/自动建群、MR/PR 创建）上 fencing token 或 outbox，at-least-once 重复执行不产生重复外部动作（不重复发通知/不重复建群/不重复开 PR）

**Plans**: 3 plans (2 waves)

- 63-01 (wave 1): run_worker --graceful-timeout + helm worker/scheduler-deployment（scheduler replicas=1 Recreate + runapscheduler cron 接线）+ compose worker/scheduler service — DEPLOY-01, DEPLOY-02
- 63-03 (wave 1): 外部副作用 fencing（MR/PR existing-by-branch 复用 + 建群 feishu_chat_id 前置查）— IDEMP-02
- 63-02 (wave 2): KEDA ScaledObject（procrastinate_jobs todo 深度）+ PDB（worker/web）+ 多副本无 Redis 双层 fail-closed（settings + helm），values-gated 默认 off — DEPLOY-03

### Phase 64: runner k8s Job executor

**Goal**: 把 runner 从硬绑 docker.sock 抽象为 executor 接口（docker/k8s 两实现），并落地 k8s Job executor，使任务容器可在 k0s/containerd 多副本环境经 k8s API 运行
**Depends on**: Phase 60–63（相对独立，但排在底座/部署硬化之后最后执行；与现有 server↔runner WebSocket/HTTP 回调契约对接）
**Requirements**: RUNNER-01, RUNNER-02
**Success Criteria** (what must be TRUE):

  1. runner 抽象出 executor 接口（docker / k8s 两实现），与现有 server↔runner WebSocket 派发 + HTTP 回调契约解耦，docker executor 行为零回归
  2. k8s Job executor 经 k8s API 起 Job/Pod 跑任务容器（去 `/var/run/docker.sock`），含 ServiceAccount/RBAC、日志流式回传、Pod 清理、失败重试
  3. 在 k0s/containerd 环境可经 k8s Job executor 运行任务容器（不依赖 docker.sock）

**Plans**: TBD

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

- [x] Phase 53: `AuditEvent` 模型 + emit 地基 (2/2 plans) — AUDIT-01, AUDIT-02 — completed 2026-06-17
- [x] Phase 54: 敏感操作全量覆盖 emit (2/2 plans) — AUDITCOV-01, AUDITCOV-02 — completed 2026-06-17
- [x] Phase 55: 审计查询 API + 前端视图 + 导出 (3/3 plans) — AUDITUI-01, AUDITUI-02 — completed 2026-06-17

完整阶段详情见 [milestones/v0.10.0-ROADMAP.md](./milestones/v0.10.0-ROADMAP.md)。里程碑审计 passed 见 [milestones/v0.10.0-MILESTONE-AUDIT.md](./milestones/v0.10.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.9.0 SDD / OpenSpec 支持（重型）(Phases 48–52) — SHIPPED 2026-06-17</summary>

完整阶段详情见 [milestones/v0.9.0-ROADMAP.md](./milestones/v0.9.0-ROADMAP.md)。里程碑审计 passed（11/11 需求、integration_ok、INV-6/INV-2 成立）见 [milestones/v0.9.0-MILESTONE-AUDIT.md](./milestones/v0.9.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.8.0 多仓串行编码 → 融合 PR (Phases 43–47) — SHIPPED 2026-06-17</summary>

完整阶段详情见 [milestones/v0.8.0-ROADMAP.md](./milestones/v0.8.0-ROADMAP.md)。里程碑审计 passed（9/9 需求、integration_ok、Nyquist 5/5）见 [milestones/v0.8.0-MILESTONE-AUDIT.md](./milestones/v0.8.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.7.0 方案编排（需求 → 主方案）(Phases 36–42) — SHIPPED 2026-06-16</summary>

完整阶段详情见 [milestones/v0.7.0-ROADMAP.md](./milestones/v0.7.0-ROADMAP.md)。里程碑审计 passed（19/19 需求、INV-2/5/6 成立）见 [milestones/v0.7.0-MILESTONE-AUDIT.md](./milestones/v0.7.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.6.0 领域脊柱 + 知识图谱补全 (Phases 27–35) — SHIPPED 2026-06-15</summary>

完整阶段详情见 [milestones/v0.6.0-ROADMAP.md](./milestones/v0.6.0-ROADMAP.md)。

</details>

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 60. durable 底座地基 | 4/4 | Complete    | 2026-06-19 |
| 61. 迁移 index/graph + 收口 ResumableTask | 4/4 | Complete    | 2026-06-19 |
| 62. 爬取+入库 durable 队列 + PageIndex 接入 | 3/3 | Complete    | 2026-06-20 |
| 63. 部署硬化 + 外部副作用 fencing | 3/3 | Complete    | 2026-06-20 |
| 64. runner k8s Job executor | 0/? | Not started | - |

**Execution order:** 60 → 61 → 62 → 63 → 64（严格顺序，每阶段建立在前序底座之上）。依赖链：durable 底座地基(60，所有后续的地基) → 迁移 index/graph + 收口 ResumableTask + 幂等基线(61，迁移范式) → 爬取+入库 durable 队列 + PageIndex（62，首个用户可见垂直切片，复用 61 范式）→ 部署硬化 + 外部副作用 fencing(63，多副本/弹性/优雅终止) → runner k8s Job executor(64，相对独立但排最后)。

**UI 触面（标 UI hint）:** Phase 62（前端爬取任务队列面板 `BatchIngestPanel`：贴链接入队/队列列表+实时状态/行内开始停止重试/刷新后从后端恢复，本里程碑唯一 Web 前端重触面）。后续 `/gsd-ui-phase` 可介入此处。其余阶段为后端适配层/迁移(60/61)、部署编排（63，helm/compose 非 Web 前端）、Go runner（64）。

里程碑 v0.1.0–v0.11.0（Phases 1–59）均已交付。v0.12.0 弹性任务底座（Phases 60–64）planning 中。

---
*Previous milestones archived in .planning/milestones/*
