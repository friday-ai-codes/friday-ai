# Milestones

## v0.15.0 项目（交付上下文聚合根） (Shipped: 2026-06-26)

**Phases completed:** 6 phases (76–81), 38/38 v1 需求；里程碑审计 **passed**（integration_ok，无真实 gap）

**Key accomplishments:**

- **命名腾挪 Project→Space（Phase 76）**：后端领域模型 `projects.Project`→`Space` 全栈一致重命名，11 个元数据级 rename 迁移（零 DeleteModel/CreateModel）数据零丢失、6266 测试零新增回归，腾出 `Project` 名给新聚合根。
- **项目聚合根 + 身份映射 + 成员（Phase 77）**：新 `initiatives` app —— `Project` 聚合根（隶属 Space + 飞书看板 + 状态机）+ `ProjectService`(INV-6) + `ProjectMember`(身份角色/主R 可转移) + 飞书人员↔Friday 用户映射 `resolve_feishu_user` + 权限 fail-closed + WS 实时推送 + 最小创建前端。
- **飞书触发建项目 + 工作项组合（Phase 78）**：飞书"项目跟踪"看板枚举（无整板 API → 子项字段派生 fail-soft 降级）+ 事件幂等建项目拉人带身份 + `create_project` 工作流节点 + `ProjectWorkItemLink`（story/缺陷统一复用 `delivery.WorkItem`）。
- **工件 + RAG + 知识关联（Phase 79）**：`ArtifactType` 可配置注册表（内置 8 类 seed + 增删禁用/双删保护）+ `Artifact` 多载体实例 + 在线查看 API + 文字载体全文进 `delivery_knowledge`/UI 稿仅元数据 + 项目纳入知识图谱经 `KnowledgeEdge` 统一 KLINK 关联可查询。
- **项目记忆 + MR 实体 + 召回接入会话（Phase 80）**：项目记忆（自由文本 + 修订可追溯 + 成员限定 + LLM 提议草稿人工确认，`call_source=memory_distill`）+ `MergeRequest` 实体 + 受保护 git webhook（HMAC/token fail-closed + 脱敏 + 幂等）+ context packer（grep+RAG + token 预算降级 + fail-closed + RetrievalTrace）+ 接入 chat runner 工具白名单。
- **Cursor 回流 + 前端工作台（Phase 81）**：MCP `lookup_project_by_branch`（分支反查召回，补齐 MCP 链 RetrievalTrace）+ `report_project_knowledge`（归因+脱敏+质量门槛→memory draft）+ Cursor rules 模板 + 完整项目工作台前端（列表筛选/创建 + 6 Tab 详情 + 记忆草稿确认 + 工件类型管理页，全量 zh-CN）。

**质量基线：** 后端 6266→6421 passed，逐 Phase 零新增回归（文档化 baseline = 38 既有失败 + 1 已知 flaky cross-suite ordering）；前端 vue-tsc 绿、1109 passed；`makemigrations --check` 全程干净。

**已知 deferred（真实环境人工验收，非 gap）：** 真实飞书看板枚举/doc 在线查看、真实 Cursor MCP 端到端、真实 GitHub/GitLab webhook 投递、真实 LLM 蒸馏质量、飞书 bitable 列解析（v2 PROJX）。

---

## v0.14.0 可观测性与日志治理 (Shipped: 2026-06-24)

**Phases completed:** 5 phases (71–75), 20 plans, 34/34 v1 需求
**Audit:** passed — 34/34 requirements satisfied, integration_ok（数据链 contextvars→日志→指标→查询→告警→大盘端到端自洽）见 [milestones/v0.14.0-MILESTONE-AUDIT.md](./milestones/v0.14.0-MILESTONE-AUDIT.md)

**Key accomplishments:**

- **CTX 用户上下文贯穿**：`RequestLogContextMiddleware`（最外层）+ `common/log_context.py` bind/clear + DRF 认证后 rebind mixin 自动注入 `user_id(无则 system)/request_id/source/trace_id`；后台任务（durable / `background_runner` / workflow scheduler / 飞书 webhook / apscheduler）经 `bind_task_context` 显式传播 `initiated_by_user_id`，跨线程/durable worker 正确继承。
- **LOG 系统日志治理**：`SystemLogEntry`（migration 0009）队列化落库（`deque(maxlen=5000)` + daemon `bulk_create` + dropped/write_failed/written/queued 四计数，全 `except` 吞掉绝不反噬）+ 倒序多维筛选全文查询 + 调用下钻（MCP/对话复用 Interaction Ledger）+ `category`(caller/sampling)/`component` 分类与事件目录 + 运行时配置热更新（级别/堆栈阈值/采样/保留）+ `InboundWebhookEvent` 原始留痕（飞书/git push/容器回调/通用 workflow）+ 按条件清理与保留策略定时清理。
- **RATE 吞吐与速率**：`RequestMetric`（migration 0010）每请求一行 + 33 处入口埋点（health/observability/poll 打 `synthetic` 隔离）；扩展 `ModelUsageRecord`（`call_source`/`ttft_ms`/`upstream_status_code`，恰 22 类 call_source）补全容器侧 token 链 `task`→回调→`arecord_llm_usage(container_callback)`；`GaugeSample`（migration 0011）apscheduler ~45s 周期采样并发/排队趋势。
- **RAG 召回可观测**：`rag_search::_record_rag_metric` 采集召回条数 + 分层耗时(embedding/sparse/qdrant/rerank) + top_score；`RetrievalTrace` 留痕扩展到 MCP + AI 对话两条链（query 原文 + chunk 内容 + score + 会话/用户，入库前 redact）。
- **SLA 可用率/错误/时长**：`classify_error` 三口径单一收口（system/business/upstream/none）+ 上游 429/529 单列 + `duration_ms`/流式入口 `ttft_ms`（首 chunk perf_counter 计时），可用率口径"排除业务限制"。
- **SNAP 当前快照**：`snapshot_service` 五源 best-effort 聚合——host(psutil CPU/内存/协程/线程/后台) / DB(pg_stat_activity+max_connections+psycopg pool+PgBouncer) / Redis(三路 INFO) / Qdrant(ping + 60s 缓存 + 8s 长超时) / 并发排队（provider 槽位·durable·runner·RAG）。
- **QUERY 查询 API**：时序 `MetricsQueryView`（Postgres `percentile_cont` 精确分位 + SQLite degrade，全白名单防注入）+ 快照 `MetricsSnapshotView` 五源聚合 + 队列计数。
- **ALERT 告警引擎与通知**：`SystemAlertRule`（migration 0012，独立 `system_alert_rules` 不套 workflow `AlertRule`）运行时 CRUD + `alert_evaluator` 9 类 metric 分派 + `AlertEvent`（P0/P1/P2 + 中文标题 + 机器可读规则信息 + 持续时长 + firing/resolved + `UniqueConstraint condition=firing` 去重）+ `alert_notifier` 邮件通道（Django SMTP + `SystemSetting` 收件人/开关，回写 `email_sent`）复用飞书/webhook 三通道并存。
- **UI 运维大盘**：`pages/admin/observability/index.vue` 上半区（健康分 + 实时速率卡 + 6 信息卡 + 时间范围 + 上游 429·529 单列 + 时长·TTFT P99）+ `SnapshotRow`(阈值变色)/`TrendCharts`(吞吐·错误三口径·时长·并发排队) + `AlertEventsTable`/`AlertRulesPanel`/`AlertRuleFormDialog`/`AlertEventDetailSheet` + `SystemLogTable`(4 计数+倒序+服务端多维筛选)/`LogDrilldownSheet`/`RuntimeLogConfigForm`；前端 `useQuery` 消费真实后端端点（无 mock）。
- **SPEC 规范固化**：`LOGGING-SPEC.md`（§9 PR/Code Review checklist + §10 全量事件目录 + §4.1 call_source 22 枚举 / §5 component 清单）+ `.cursor/rules/observability-logging.mdc` 强制规则 + AGENTS.md/CLAUDE.md 复核，后续任何功能必须按规范补埋点。

**Stats:** 34/34 v1 requirements delivered, 5 phases / 20 plans, 2026-06-24。后端 269 passed（20 套件 -p no:randomly）+ 前端 22 passed + `vue-tsc` exit 0。

**Known deferred items at close:** 3（accepted，非 gap，运行期才能终态确认）— SQLite `percentile_cont` 降级（生产 Postgres 精确）/ ~10 项真机运行期 UAT（真实 SMTP·指标越线 firing→resolved·PG·Redis·Qdrant·浏览器视觉）/ 既有 structlog 跨模块测试污染（pre-existing，`-p no:randomly` 固定序全绿）。详见 milestones/v0.14.0-MILESTONE-AUDIT.md §6。

**What's next:** v0.15.0 立项（`/gsd-new-milestone`）。可观测性增量（Prometheus/OTLP、分布式 tracing、告警降噪、Sentry、日志冷存储）已列 v2 Future Requirements（OBSX-01~06）。

---

## v0.13.0 并发治理与索引体验 (Shipped: 2026-06-23)

**Phases completed:** 6 phases, 8 plans, 11/11 v1 需求

**Key accomplishments:**

- 并发治理按资源分治、不设全局总上限：索引/图谱用 Procrastinate 原生 `lock` 槽位锁池（稳定 hash 同仓恒定同槽串行、N 从 SystemSetting 读、超限原生 todo 排队）；LLM 按 `ProviderCredential.max_concurrency` 凭证级限流（Redis 租约信号量 + 进程内 fallback + 超时友好「系统繁忙」）；容器复用 `runner.concurrent`、MCP 不限。
- AI 对话跨会话「串流」修复：前端 streaming 状态与副作用按 `conversation_id` 隔离（`handleSSEEvent` owner 守护 + `sendMessage` finally isCurrent 守护 + per-stream run_id），后台流继续但仅写回所属会话。
- 默认禁用 LSP 仅用 tree-sitter（VOLAR/GOPLS_BACKEND_ENABLED 默认 False，可经 env 可逆重开），缓解图谱构建慢与冷启动等待。
- 实时进度统一：索引进度条改单调加权阶段（消除「文件级 90%→chunk 级 0%」归零跳变）；图谱独立轨；AI 描述生成状态（排队中/生成中/完成/失败）前端可见。
- 超管「全部更新索引」+ CSV 批量建仓：批量入队复用并发槽位锁排队消费、不打爆资源。
- access token 改可选 + 密钥提供方 FK 重构：`Repository.git_instance_credential` FK + 解析优先级 per-repo→FK→host→none（老仓库零回归），建仓可选实例凭证、TestConnection FK/host fallback。

---

## v0.12.0 弹性任务底座（durable 任务队列与多副本就绪） (Shipped: 2026-06-20)

**Phases completed:** 5 phases, 16 plans, 43 tasks

**Key accomplishments:**

- DurableTaskService 适配层立起：唯一权威 `_use_procrastinate` 后端判定 + 复用 background_runner 的 SQLite in-process fallback + 队列常量/进程角色 helper + no-direct-import 守护与 postgres_queue marker，procrastinate[django] 3.8.1 落地。
- 三处 `AppConfig.ready()` 的 web-only 启动副作用（repositories `_reset_stuck_indexing`、codegraph galaxy warm + orphan graph reconcile、resumable `_schedule_recovery`）接入 60-01 的 `durable.roles.should_run_startup_side_effects` 门禁：worker/migrate/test 进程短路并记 info 日志，handler/backend 注册无条件保留，web 默认零回归。
- ProcrastinateBackend 落地 Postgres durable 路径（defer/get/cancel/retry_stalled 委托 procrastinate.contrib.django.app），独立 worker 进程命令（get_worker_connector → PsycopgConnector，listen_notify=False），retry_stalled_durable_jobs 周期单例 leader（@app.periodic + queueing_lock + heartbeat 判定），settings 复用 _use_procrastinate 条件注册 procrastinate.contrib.django，并以 postgres_queue 测试覆盖 defer/priority/run_at/worker-connector/forged-heartbeat rescue/queueing_lock/并发竞争。
- 从零创建 `.github/workflows/ci.yaml`（仓库 workflow 已于 5579e45f2 全删）：`server-ci` 跑 SQLite 默认路径作零回归门禁（addopts 默认排除 postgres_queue），`postgres-queue` 用 postgres:17-alpine service container + migrate + `uv run pytest -m postgres_queue --allow-hosts=127.0.0.1,localhost` 跑 Plan 03 的 durable Postgres 行为，两 job 经 marker 分层共存；聚焦 server+Postgres，不恢复历史无关 job。
- index/graph/page_index 三个 durable 任务在 procrastinate（defer_async(
- 5 处生产 index/graph 入队点（含 CONTEXT 漏列的 index_views/codegraph）全部从 `run_in_background(wrap_resumable(...))` / `submit_resumable(...)` 改为 `DurableTaskService.defer`，统一 queue 常量 + deterministic idempotency_key（index:/graph:{repo_id}），recovery resume 收敛为 durable 单一驱动入口，生产入队路径零 resumable 提交残留
- 新增 `durable/reconcile.py` 在途判定 helper（经 `DurableTaskService.has_active_by_key` 按 queueing_lock 查、async_to_sync 同步入口、对 procrastinate 零直接依赖），并把 repositories/codegraph 两处启动 reconcile 改为"标 RUNNING→FAILED 前先查 durable job 接管，有在途（todo/doing/scheduled）则保留 RUNNING"，非 durable 后端维持旧标 FAILED 行为零回归。
- 新增 `ResumableTaskStatus.MIGRATED` + `legacy_durable_job_id` 列（migration 0002），实现一次性迁移命令 `migrate_resumable_to_durable`——按 deterministic key（`index:/graph:{target_id}`）把存量 PENDING/RUNNING 的 index/graph `resumable_tasks` defer 成 durable job、旧行标 MIGRATED 记 legacy id（不双跑、幂等可重入、SQLite 安全降级），并把 `background_runner` 注释降级为 dev fallback / 轻任务定位
- run_crawl_ingest 双后端 durable 任务（薄封装天然幂等的 ingest_from_urls）+ IngestRun 扩 QUEUED/STOPPED 状态与 durable_job_id/idempotency_key 列 + delivery 队列动作端点（enqueue/list/detail/start/stop/retry），状态以 IngestRun(DB) 为唯一真相源、刷新/重建可恢复
- run_page_index 由占位 noop 填充为真实生成（CorpusTreeService.build_full + target-hash 跳过）+ CorpusTreeSnapshot.source_hash 列与确定性指纹 helper + KnowledgeTreeRebuildView 裸 run_in_background 收口到 DurableTaskService.defer(QUEUE_PAGE_INDEX)，按 target hash 幂等（未变跳过、变则重建落 source_hash），重复执行无重复 snapshot
- run_worker 暴露 `--graceful-timeout`（透传 Procrastinate `shutdown_graceful_timeout`，零信号代码）+ helm/compose 同构拆出独立 worker/scheduler workload（scheduler 单例 replicas=1+Recreate 首次承载 apscheduler cron），优雅终止不变式 terminationGracePeriodSeconds>graceful>心跳成立。
- 给 worker 加 KEDA postgresql scaler（按 `procrastinate_jobs status='todo'` 队列深度伸缩、minReplicaCount>=1 禁 scale-to-zero、凭证经 TriggerAuthentication）+ web/worker PodDisruptionBudget + 把"多副本误用内存 channel layer 静默丢 WS"从注释约束升级为 settings 运行期 + helm 模板期双层 fail-closed；KEDA/PDB 全 values-gated 默认 off，默认安装/单副本零回归。
- 给 MR/PR 创建与飞书建群上 reuse-first 幂等围栏：创建前查既有 open MR / WorkItem.feishu_chat_id，命中即复用不重复执行，无 outbox 表，全程 fail-soft。
- KubernetesExecutor 经 client-go 以 batch/v1 Job 跑任务容器（StartContainer/WaitContainer/StreamLogs），executor 选择接通 docker 默认零回归，callbackURL host 可配置
- KubernetesExecutor 补齐 Remove/StartupCleanup/ZombieScan/ReadContainerFile（friday.runner label 隔离多副本、僵尸 Job 回收推 TaskFailed、产物读取 best-effort 退化），并落地 values-gated runner SA + 最小权限 Role/RoleBinding、k8s 模式去 docker.sock 并经 downward-API podIP 注入回调 host

---

## v0.10.0 操作审计治理 (Shipped: 2026-06-17)

**Phases completed:** 3 phases, 7 plans, 7 tasks

**Key accomplishments:**

- 新建零业务依赖的 audit 横切 Django app，落 AuditEvent append-only 不可篡改模型（actor 标量软引用 + 双时间戳 + 5 查询索引 + 模型层 save/delete 守护）与 0001_initial 迁移
- AuditService 单一写入入口（emit/aemit）落地：唯一 AuditEvent writer（INV-6）+ 入口强制脱敏（key-name/值级密钥/高熵）+ fail-soft 吞异常不阻断主操作 + 稳定 action taxonomy 容器，配 INV-6 grep 守护
- 把 Phase 53 的 AuditService.aemit/emit 单一写入入口接线到 accounts（建用户/启停/改资料/首启 superuser）+ projects/members（成员增删改 + 角色变更）+ projects（空间配置 + 仓库权限/关联变更），产出全量审计记录（actor=request.user + 目标 + 前后值），凭证型字段仅记字段名 + redacted 布尔。
- 把 AuditService 接线到 Provider/Git 实例/per-repo Git/PAT/飞书凭证与同步、排除规则增删，并把 v0.5 purge 埋点收口到 AuditEvent 单一写入入口，产出全量审计记录且凭证字段在 DB 绝无明文。
- 审计查询列表 + 详情 REST（IsSuperUser fail-closed、只读、过滤 + offset/limit 分页），挂 `/api/audit/`。
- CSV / JSON 流式导出（IsSuperUser、复用列表过滤、max_rows 上限），`GET /api/audit/events/export/?fmt=csv|json`。
- `/admin/audit` superuser 审计页：过滤 + 表格 + 分页 + before/after 详情弹窗 + CSV/JSON 导出 + 侧栏入口 + i18n。

---

## v0.9.0 v0.9.0 (Shipped: 2026-06-17)

**Phases completed:** 5 phases, 18 plans, 38 tasks

**Key accomplishments:**

- 范围扩展（orchestrator 决策，非偏差）
- 新建 SddSpec 脊柱模型（5 态枚举 + unique_together 幂等键 + 0018 迁移）与 DocumentService.create_internal_spec 内部生成文档单一写入入口（INV-6）
- SddSpecService.create_draft 幂等单一写入入口（命中既有 SddSpec 短路返回不留孤儿 Document）+ SddSpec INV-6 grep 守护
- agenerate_specs_for_plan 逐 SDD 仓产 openspec spec（可注入 SddSpecSynthesizer + LLMSddSpecSynthesizer），逐仓 try/except 隔离 + emit spec.drafted；event taxonomy 对齐守护同步更新
- ArchitectMergeAdapter._handle_pass 在 merge.completed 之后 best-effort 调 spec 生成 hook（默认 agenerate_specs_for_plan，可注入 stub），整段 try/except 吞 warning 绝不阻断融合返回；全链路守护封板 Phase 49
- SDD 仓库方案融合通过后 best-effort 逐仓产 openspec spec draft：落 SddSpec(draft) 脊柱 + Document(sdd_spec, internal_generated) 经双单一写入入口（INV-6），关联 WorkItem/PlanVersion/Repository 并 emit spec.drafted；非 SDD / 异常零回归 fail-soft
- RepoCodingTaskService 首次消费 follow_openspec（按 Repository.facets.methodology==SDD 置位 + 漂移回填）并新增 mark_gate_blocked gate 拦截唯一写入入口（条件 pending→failed + {reason, spec_status} 结构化诊断）
- AICodingNode._dispatch_wave 加 fail-closed openspec gate（follow_openspec=True 仓强制 SddSpec.status==APPROVED 才放行，未批准/异常经 mark_gate_blocked 拦截不 dispatch，单仓异常隔离不崩 wave）+ approved SDD 仓 dispatch metadata 注入 env_FRIDAY_TASK_FOLLOW_OPENSPEC=true
- TaskConfig 加 follow_openspec 字段（经 env_prefix 映射 FRIDAY_TASK_FOLLOW_OPENSPEC，默认 False），_get_system_prompt 在 follow_openspec 为真时追加独立 _openspec_guidance helper 文本（指示 agent 遵循 openspec/ 下已批准 spec、优先查仓库内 openspec skill 按 delta 实现），缺省路径逐字等现状
- SDD 仓编码前强制 spec 已 approved 才放行（follow_openspec=True 仓校验 SddSpec.status==APPROVED，未批准/校验异常 fail-closed 经 mark_gate_blocked 拦截不 dispatch、单仓隔离不崩 wave、并经 aadvance 传递闭包阻断下游），并通过 dispatch env → task system_prompt 注入 openspec 指引使 approved SDD 仓按 openspec 流程编码；非 SDD 仓全链路零回归
- SddSpec.implementation_prs JSON 字段 + SddSpecService.link_implementation_pr 单一写入入口（pr_url 去重幂等 + approved→implemented）+ AICodingNode 收尾 best-effort 回填挂接（fail-soft 零回归）
- SddSpecDetailSerializer 暴露 implementation_prs（实现 PR 列表）+ work_item url(取 prd_url)/title + plan_version 摘要，形成 spec → 需求 → PR 完整追溯 JSON；缺数据降级（[]/省键）不报错
- SpecDeliveryPanel.vue 沿 WorkItem（需求，可点 prd_url）→ spec（状态徽标）→ 实现 PR 列表（pr_url 可点）渲染交付验收闭环；缺数据 fail-soft 降级真实中文占位；真实 zh-CN.json 文案接通
- 让 SDD spec 沿 spec → 需求(WorkItem) → 实现 PR 形成可追溯交付验收闭环：编码产出的 PR 经单一写入入口幂等回填到 spec（approved→implemented），detail API 暴露完整追溯 JSON，前端 SpecDeliveryPanel 沿链路 fail-soft 渲染交付验收视图——非 SDD 仓全链路零回归

---

## v0.8.0 多仓串行编码 → 融合 PR (Shipped: 2026-06-17)

**Phases completed:** 5 phases, 16 plans, 38 tasks
**Audit:** passed — 9/9 requirements satisfied, integration_ok (5/5 flows), Nyquist 5/5 compliant (see [milestones/v0.8.0-MILESTONE-AUDIT.md](./milestones/v0.8.0-MILESTONE-AUDIT.md))
**Known deferred items at close:** 4 (see STATE.md Deferred Items — Phase 43 真实容器 E2E human-needed/UAT ×2 + 2 stale-marked quick tasks 实为已完成)

**Key accomplishments:**

- 新增 `_schedule_chat_plan_resume`（mirror `_schedule_workflow_resume`：fire-and-forget + 幂等 + fail-soft），把 `_schedule_agent_session_resume` 的 `plan_research` 分支当前的提前 `return` 改为「entrypoint==CHAT 守门 → 经 43-02 同源 helper 续驱 engine 到 done → BarrierManager.task_completed(str(plan_session.id)) 回灌主方案」，一举消化 v0.7 audit D-2 两处缺口（a: chat barrier 从不被通知；b: chat 入口此后无消费者驱动 engine.advance 到 done）。
- 把工作流节点（`plan_research.py`）与 chat 工具（`plan_research_tools.py`）两处逐行同构的内联 advance 循环，重构为复用 43-02 的共享 helper `adrive_plan_session_to_pause_or_terminal`——使节点 / 工具 / 43-03 回调消费者三处真正同源一份续驱逻辑；入口私有挂起 marker 映射（NodeResult / ToolResult via `_maybe_suspend`）各自保留，行为零回归；同步把 `start_plan_research` 占位文案 / 工具 description 由「自动回流尚未接入」如实更新为「调研完成后自动融合并返回 canonical 主方案」（43-03 已接通）。
- RepoCodingTask 操作态模型落库（plan_version FK + repository FK + wave/depends_on M2M self DAG + produced_artifacts/follow_openspec 预留位 + attempt/error 可靠恢复），4 态枚举无 stale，迁移 0017 自动生成且 makemigrations --check 干净，模型层零业务方法守 INV-6
- 把 `MergedPlan.execution_plan[].dependencies`（task id 引用）真正消费——graphlib Kahn 分层建 task-id DAG → 投影仓级 wave（同仓取 max）+ 跨仓 depends_on 边（去自环），复用 `plan_validator.validate_plan` 做 dependency_cycle fail-fast，空依赖退化单 wave 全并行（零回归）
- 立 `RepoCodingTaskService` 单一写入入口（INV-6）——消费 44-02 拓扑分层结果，`create_tasks_for_plan` 幂等 get_or_create + 写 wave + 同步块内 `depends_on.set(...)` 连仓级 DAG 边；`mark_running/done/failed/blocked` 状态推进，`mark_done`（仅 running→done）/`mark_blocked`（仅 pending→failed）用条件更新 + 影响行数判定保重复 callback no-op；`mark_blocked` 承载 WAVE-02 下游阻断（`error={"reason":"upstream_failed","upstream":[...]}`）；配 INV-6 grep 守护断言除 service 外无旁路写表
- 立 `wave_progression.py` 入口无关 wave 推进续驱——`aadvance_coding_waves` 严格按「① 回填 running→终态（按服务端权威 `SubAgentSession.status`）→ ② 传递闭包 BFS/worklist 沿 `dependents` 多跳阻断全部 failed 上游的下游 → ③ 决策出口（RUNNING 在途→waiting / 有 depends_on 全 done 的 pending→dispatch 最小 wave / 无 pending 无 running→all_terminal）」执行；阻断在任何 early-return 之前完成是 liveness 关键（链 A→B→C 单次内 B、C 全 blocked → 收尾可达不死锁，T-44-DEADLOCK）；状态只经 `RepoCodingTaskService` 条件更新幂等（INV-6），复用 Phase 43 callback 驱动 resume 不造两套
- 把 `AICodingNode` 从「一把梭全并行 dispatch + 一次性 resume」改成「按拓扑 wave 分批 dispatch、wave N 全终态才推 N+1」——首发段 `_execute_with_branch` 经 `build_repo_waves` 分层 + 环 fail-fast + `RepoCodingTaskService.create_tasks_for_plan` 建行（INV-6）后仅 dispatch 最小 wave 并 `mark_running`；resume 段 `_resume_after_containers` 按 `plan_version_id` 分流 wave/legacy，wave 路径经 `aadvance_coding_waves` 判 gate → dispatch 下一 wave 再 `waiting_event`（不双 backfill、waiting != finalize）或 `_finalize_wave` 从 DB 重算 done/failed 走部分成功收尾（done 出 MR、failed/blocked 如实标注、不自动回滚）；空依赖 + 无 plan_version 退化为既有全并行字节级等价（零回归）；wave N→N+1 由 Phase 43 `_schedule_workflow_resume` 容器回调触发节点重入自驱，不另造调度（无 while True/sleep/timer）
- 多仓 wave 编码收尾时各仓 MR 的 `target_branch` 改为锚定各仓自己的 `Repository.default_branch`（fallback 链 `default_branch or base_branch or "main"`），修复 default_branch 不一致时所有 MR 共用第一个仓 base_branch 打错目标分支的 PR-01 病根。
- 多仓 wave 编码收尾批量建 MR 后，对成功名单（≥2 仓）回写描述追加「## 关联 PR」兄弟仓链接段（排除自身）+「## 关联方案 / 工作项」追溯段（plan_version_id → PlanVersion → TechnicalPlan → WorkItem），提取为可复用 helper `pr_cross_reference.py`，全程 fail-soft。
- 编码容器遇阻时不再走 `report_failed` 死路——给编码 agent 一个 `ask_user` 工具，复用既有 question 协议契约（`type=question` + `answer.json` 共享卷回灌）向人发问并阻塞等待回答，等待期心跳保活使容器保持 RUNNING，回答后据此续跑；超时则 default 续跑或优雅失败，绝不挂起/replan。
- server 侧 question 接收/回答回灌/resume 全部既有可复用——唯一缺口是 `send_question_card_enhanced` 只认 `main_session.metadata.chat_id`，wave 编码任务（node_execution）取不到 chat_id 不发卡。改为统一经 `_resolve_notification_chat_id` 解析（既零回归 chat 路径、又 fallback node 级 chat_id、并修复原直接访问 `session.main_session` 的 async lazy-FK 风险），并以测试坐实「遇阻 RUNNING → aadvance waiting（不 dead-end）→ 回答 completed → Phase 44 推进」与「no-replan 守护」。

---

## v0.7.0 v0.7.0 (Shipped: 2026-06-16)

**Phases completed:** 7 phases, 19 plans, 12 tasks

**Key accomplishments:**

- 1. [Rule 2/3 - Missing wiring surfaced by fail-loud] 补登记 send_plan_card
- 1. [Rule 1 - Bug] _emit_event 日志 kwarg 与 structlog 保留键冲突
- 1. [Rule 3 - Blocking] 模型导入校验改用 `manage.py shell -c`
- 1. [Rule 1 - Bug] INV-6 guard 名字撞车豁免
- 1. [Rule 1 - 文件定位] eager 投影接 coding_tools.py（非计划标注的 chat_tools.py）
- 1. [Rule 3 - Blocking] engine.py 既有 import 排序告警
- 1. [Rule 3 - Blocking] RECALL_ENTITY_KINDS 未在 package __init__ 导出
- 1. [Rule 1 - 契约变更] 更新既有 engine 测试 merge mock
- PlanSessionEvent append-only 模型把编排全程 §15 trace 事件持久化为统一信封行，event_taxonomy 稳定常量收口全 emit 点（消除 38/39/40 字符串漂移），_emit_event 升级为 best-effort 持久化。
- Clarification 模型 + ClarificationService（INV-6）补齐 HITL 澄清回路：不清晰时建 pending 挂起 + emit clarification.asked，回答后仅 affected_partials 经 mark_stale 重跑、其余复用；engine._clarify 接真实可注入 ClarifyAdapter（needs-clarification policy）。
- AIPlanResearchNode 把整条编排端到端串起：从需求建 PlanSession(entrypoint=workflow) 注入真实 adapters 驱动 engine.advance，经 拆分→路由→召回→澄清→并行调研→融合 产出带跨仓依赖的 canonical MergedPlan；clarifying/researching 处复用既有 waiting_event 挂起恢复。
- Chat 经 `start_plan_research` @tool 复用与工作流入口完全相同的 `PlanOrchestrationEngine` 发起多仓方案编排——两入口共用 `start_orchestration` + `build_orchestration_engine` 薄 helper，验证入口无关一致性（结构等价 MergedPlan + 同序 §15 事件），并以 `work_item=None` + `entrypoint=chat` 落地 INV-2。

---

## v0.6.0 领域脊柱 + 知识图谱补全 (Shipped: 2026-06-15)

**Phases completed:** 9 phases, 25 plans, 50 tasks

**Key accomplishments:**

- 1. [Rule 3 — 层级/去重，honoring plan-checker WARNING] 字段 key 常量落点 + feishu.models 反向 import
- 1. [Rule 3 — 满足 plan Task 2 verify 门禁] feishu/client.py 顺带 ruff format 收敛两处预存多行表达式
- 新建 delivery Django app 与四个操作态脊柱模型（canonical WorkItem + SyncState + Relation + StatusEvent），DB unique_together 强制 INV-1 三元组唯一，初始 migration 已应用建出四张表，7 个模型单测全绿。
- 实现 WorkItem 唯一写入入口 `WorkItemService.upsert`（INV-6，DOMAIN §13.1 全步骤）：三元组幂等收敛、mirror-only 刷新结构性保护 friday_enhanced、per-facet WorkItemSyncState 且回源失败不整体回滚、关系派生 + target_external_id 占位/回填、状态变更 append-only StatusEvent；复用 Phase 27 feishu_parsing 派生，18 个 service 守护测试全绿（respx mock 回源，零真实网络）。
- 把 28-02 的 `WorkItemService.upsert` 接到两条真实入口：① 最小 delivery REST（手动按三元组 upsert + 读取 WorkItem，adrf APIView，`IsAuthenticated`，写端点经单一 upsert 无旁路 ORM 写）；② 飞书 webhook 三个工作项 handler 紧随既有 knowledge ingestion 后经 `run_in_background` 后台调 `upsert(source="feishu_webhook")`（保留投影，INV-3）。补 INV-6 旁路写表 grep 守护（精确锚定零误伤）、INV-3 投影保留守护、跨入口收敛集成测试；delivery 全套 38 passed、webhook 回归全绿。
- 新增 append-only `WorkItemCommentEvent` 模型 + 两枚举（CommentEventType / ApprovalSemantic），逐字段对齐 DOMAIN §12.4，0002 迁移已应用建出 `delivery_work_item_comment_event` 表（含 (work_item, event_time) 索引），模型层 5 个单测守护 append-only / 默认值 / CASCADE / 索引全绿。
- 实现评论事件流服务层：`CommentEventService.append_events` 作为评论落库唯一写入收口（去重锚 get_or_create 幂等可重入），`ingest_comments` 复用 Phase 27 get_comments 拉取摄取（缺 project/work_item/回源失败降配 SyncState comments facet，不抛不回滚），`append_webhook_comment` 接线路径，`classify_approval_semantic` 审批语义单一判定（reject 优先），`project_comment_tree` 从事件流读时投影当前评论树（线程层级 + 编辑取最新 + 删除标记 + event_time 排序，绝不改事件行）——33 个守护测试全绿，无回归。
- 把 29-02 评论事件流接到两条真实入口：① 飞书 webhook `_handle_workitem_comment` 在保留既有 approval（复用单一判定 `classify_approval_semantic`）+ knowledge 投影（INV-3）的同时，经 `run_in_background` 后台 `append_webhook_comment` 追加 CommentEvent（缺三元组/缺评论跳过+warning）；② 只读 REST `WorkItemCommentTreeView`（IsAuthenticated）按三元组返回 `project_comment_tree` 投影（含线程层级 + approval 语义，不旁路 fetch/落库）；并补 INV-6 评论旁路写表 grep 守护（精确锚定 + writer 自证）——delivery+approval 全套 97 passed，无回归。
- 新增 `Document` / `DocumentVersion` 两个操作态实体落 delivery app，逐字段对齐 DOMAIN §3/§12.5：区分外部飞书文档与内部生成文档（document_type/source_kind/content_storage 三枚举），版本链经 supersedes self FK + unique_together(document, version)，work_item FK 关联脊柱；0004 迁移已 migrate 建出两表，7 个模型单测全绿，delivery 套件 101 个无回归。
- 新增 `DocumentService.upsert_from_feishu` 作为 Document/DocumentVersion 落库的唯一写入收口（INV-6）：external_feishu 文档按 `(feishu_tenant, external_ref=doc_token)` 去重定位，`content_hash` 相等不翻版本、不等建新 `DocumentVersion` + supersedes 链并推进 `current_version`，落 `content_storage=both`、`feishu_tenant` 由 doc URL host 派生；摄取成功按 `document_type` 映射记 `WorkItemSyncState(prd_body|tech_doc)` facet 完整度（缺正文 missing）。配 Document/DocumentVersion 旁路写表 INV-6 grep 守护（精确锚定无误伤）。11 个 service 测试 + 2 个守护测试全绿，delivery 套件 114 passed 无回归。
- 新增 `server/knowledge/sources/feishu_document.py` normalizer 并注册进 `get_normalizer` 注册表：从工作项三元组 + work_item 锚事件 payload 的 `prd_url`/`tech_doc_url` 提取飞书 doc token（复用 `_extract_doc_token`），经既有 `create_feishu_doc_client_for_project` + `get_document_content` 拉正文（复用 `_fetch_doc_body`，不重写取材），产出 ① 操作态 `Document`/`DocumentVersion`（经 30-02 `DocumentService` 单一入口 INV-6 + `work_item` FK）；② knowledge 投影 `KnowledgeEntity(kind=document)` + `KnowledgeEdge(relation=REFERENCES)` 连 work_item 实体 → document 实体（方向 work_item→document，对齐 mcp_plan HAS_PLAN 出边范式）。work_item 锚事件复用 `feishu_work_item.normalize` 产出（content 逐字一致 hash 相等不 clobber 既有快照），`feishu_work_item.py` 未修改（INV-3）。doc 拉取失败降级缺正文段 + warning，缺段不缺实体不抛不回滚。8 个 normalizer 守护测试全绿，knowledge + delivery 套件 392 passed（仅既有无关 test_triggers.py 1 failed，按指示忽略）。
- 新增 `WorkItemPrdDocumentView`（adrf `APIView`，`IsAuthenticated`，async get）+ `DocumentSnapshotSerializer` + `work-items/prd-document/` 路由：给定带 `prd_url` 的 WorkItem（三元组），经独立操作态 `Document` 实体（`Document.objects.filter(work_item, document_type=prd).select_related("current_version").order_by("-updated_at").afirst()` → `current_version.content`）只读检索 PRD 正文快照——纯读已落库 Document，不旁路 fetch、不写表，兑现 DOC-02 成功标准 3。三元组校验、afirst 命中、404 语义沿用 28-03 既有 `WorkItemDetailView`/`WorkItemCommentTreeView` 范式；序列化全字段 read_only（INV-6），`content`/`version` 取自 `current_version`（缺 → `""`/null 不臆造）；支持可选 `?document_type=` 复用端点取其他类型快照（默认 prd，非法 400）。7 个检索守护测试全绿，delivery 套件 121 passed 无回归。
- 1. [Rule 3 - Blocking] migration 文件名重命名
- 1. [Contract resolution] 自然键消费方式改为消费预组装 key（非重拼接）
- 1. [Rule 3 - Blocking] 新增 `knowledge.diff_archive.aarchive_exists` 以保 INV-3 守护
- 1. [Rule 1 - Bug] 修正 `web/src/api/index.ts` 既有 perfectionist/sort-exports 报错
- 给 git platform client 增加 `get_merge_request_metadata`（双客户端拉真实 `merge_commit_sha`/`target_branch`/`merged_at`），新增 `aresolve_mr_commit_anchor` 历史 commit 锚解析 helper，把一键摄取 MR 步从合成 `mr-{iid}` 改为真实 merge commit 锚定（WR-02），并在 MODIFIES_CHUNK 边 metadata 冻结 `chunk_content_hash` 指纹供 HDIFF-02 对账。
- 为 MODIFIES_CHUNK 边落地 HDIFF-02：新增 `amodifies_chunk_edges` as-of 查询 helper（历史 as_of 见当年成立边、当前视图只见未失效边），新增 `areconcile_modifies_chunk_edges` 重索引对账（target_chunk_id 不存在 ∪ content_hash 漂移 → 经 `graph_store.invalidate_edge` 置 `invalid_at`，置位不删），并把对账挂在 `clone_and_index_repository` 收尾 base 路径作 best-effort 钩子（失败仅 warning，绝不阻断索引 success）。
- 纯读片段→需求反查：复用 find_chunk_at + graph_store 反向多跳（chunk←code_change←tech_plan←work_item→document），fail-closed 排除 + 默认当前视图，经 REST(IsAuthenticated) 与 MCP 工具 reverse_lookup_requirements 暴露结构化 {chunks, related_work_items, related_documents, paths}
- 把 Phase 29 `project_comment_tree(work_item)` 投影出的当前评论树文本并入 `feishu_work_item` 知识实体的投影内容（`## 评论` 段），并在评论事件流新增后 best-effort 触发 work_item 重投影——使评论经既有检索召回且天然关联到 WorkItem，不新增 EntityKind、无新 model、无 migration。
- 1. [合并提交] Task 1 与 Task 2 共用同一新建服务模块 `screenshot_recall.py`，以单个 `feat` 提交交付。
- 1. [选型] 降级卡片「前往系统设置」用 `<a href="/admin">` 而非 `RouterLink`。

---

## v0.5.0 索引检索地基与排除文件 (Shipped: 2026-06-15)

**Phases completed:** 5 phases, 23 plans, 54 tasks

**Key accomplishments:**

- 建立排除配置单一事实源（RepoExclusionRule + 全局默认 SystemSetting 键）与单一匹配器 `is_excluded(repository_id, rel_path)`：编译一次/复用、dir/glob/regex 三类规则、运行期 fail-closed、构造期非法 regex fail-loud，内置开箱即用安全默认。
- 把 Plan 01 的单一匹配器挂接到索引扫描面（full + incremental 两条 `scan_directory` 路径），被排除文件从源头不进 `files_to_process` / `local_hashes`，fail-closed；同时修正 PF-04 —— `scan_directory` 不再谎称已应用 `.gitignore`，注释/docstring 如实描述「目录名 + 扩展名白名单 + 排除匹配器」真实口径。
- 把 Plan 01 的单一匹配器挂接到 RAG 单一 chokepoint（`search_rag` + 图谱邻居 hop1/hop2/cross-repo 渲染）与进程内 chat/agent 工具读取面（`browse_file_content` 拒读、`list_space_structure` 文件树过滤、`search_repository_code` 兜底过滤）——被排除文件在检索 / 工具读取面 fail-closed 不可见，命中即拒读/丢弃，绝不降级泄漏明文；并落地跨面守护测试（索引扫描 + browse + RAG 三面同一文件均不可见）。
- 把排除过滤延伸到编码容器读取面：server 两条编码派发路径（chat `build_dispatch_metadata` + workflow `AICodingNode._run_repo_coding`）无条件下传有效排除规则经 `env_FRIDAY_TASK_EXCLUDE_PATTERNS` 注入；task 容器在 clone+checkout 后按规则物理删除工作树中被排除文件（跳过 `.git/`），删除持久失败时 fail-closed 抛错使 setup 失败——绝不让容器内 agent 看到被排除文件。
- 为排除配置提供 REST API（CRUD + regex fail-loud 校验 + 缓存失效）与仓库详情页最小编辑面板：列出全局默认（只读可关闭）+ per-repo 增删，保存即时生效，措辞如实（仅承诺 Friday 不可见，不承诺 git 物理删除），完成 EXCL-01「用户可配置」闭环。
- 把外部暴露的 MCP HTTP 直读面（grep_repository / get_repository_file / list_repository_files / find_related_chunks）挂接 Plan 01 的单一匹配器，对被排除文件 fail-closed 不可见——镜像直读与索引回退两条路径都拦，关闭 bare-mirror 残留泄漏通道（EXCL-02 工具面补齐）。
- 闭合 22-VERIFICATION 唯一阻断缺口（EXCL-02）：`CodeSearchView._search`（认证 REST 端点 `POST /api/repositories/<id>/search/`，前端 `searchCode` 在用）原直读 `BranchAwareSearchService.search` 返回 `content`/`file_path` 无任何 `is_excluded` 过滤，被排除文件明文与路径会经该 RAG 旁路直读面泄漏。本 gap 镜像 22-03 `search_rag` chokepoint 模式，给该端点自挂同一 `build_matcher_for_repo` + `matcher.is_excluded` 过滤——被排除文件 fail-closed 不可见，并补对称守护测试。
- 统一文件删除入口 purge_file 一次删净 Qdrant 主+overlay / FileIndex / ChunkRegistry(+ChunkEdge) / codegraph 五面，三条索引删除路径收敛收口 PF-03 + PF-05，删后无残留 + 幂等有守护测试证明。
- `compute_reconciliation`（已索引 ∪ ChunkRegistry ∩ 现行匹配器，列出已索引但现命中排除的差异，匹配器构造失败置 degraded 不谎报已一致）+ `run_cleanup(normal)`（逐差异文件 purge_file 删净四面、对账归零）+ `CleanupRun` 持久化 + 对账/清理/状态 REST API（GET 差异 / POST 派发后台返回 run_id / GET 状态回流敏感未清面）+ 审计埋点，敏感分支懒导入契约就位。
- `purge_sensitive_planes` 在普通排除清理之上额外清操作记录面——CodeChangeArchive file 级 scrub（剔除被排除文件 diff 段 + 重算计数，仅含该文件整行删，含他文件不误删）、TaskResult/ActionLog 经 repo_url↔git_url 归一关联本仓的可控清理（关联不确定保守不动）、message parts/content 子串脱敏；无精确 file 关联面（prompt snapshot/备份/git object）如实记 unscrubbed + caveat 绝不假装清除，兑现 23-02 sensitive 懒导入契约。
- `reconcileApi`（getReconcile/cleanup/getCleanupStatus，类型对齐 23-02/23-03 契约）+ `ReconcilePanel.vue`（对账差异展示 + degraded『对账不可信』警示并禁用清理 + 普通/敏感双清理入口分离 + 敏感强确认含不可逆/不承诺 git/备份物理消失如实措辞 + 派发后轮询 getCleanupStatus 如实回显 CleanupRun 真实 unscrubbed 面 + caveat）+ 仓库详情页挂载 + zh-CN 文案 + 5 例守护测试，兑现 EXCL-06 可见闭环（W1/W2/W3、§9.1/§9.2）。
- SensitiveFileSuggestion 模型 + 迁移 0034 + services/sensitive_detect.py 确定性检测器（独立有界遍历 + 文件名启发式复用 Phase 22 基线 + 内容密钥扫描 + 全程脱敏 reason + aupdate_or_create upsert）
- run_full_index FINALIZING 末尾经 run_in_background best-effort 触发确定性检测（检测失败不阻断索引 success），并新增可选 LLM 二分类段 classify_ambiguous_files（provider 缺失/失败 graceful 退化、强密钥绝不外送、最小化布尔特征）
- 为 EXCL-03「建议 + 确认」面提供 REST 工作流：列出某仓 AI 敏感文件建议（severity 排序、real_secret 优先、`?status` 过滤），接受（→ 幂等创建 `RepoExclusionRule(source=ai_suggested, rule_type=glob)` + 标 accepted + `invalidate_matcher_cache`），忽略（标 dismissed）。全程绝不静默删除已索引/派生数据——删除仍由既有 Phase 23 reconcile/cleanup 用户显式触发。
- 兑现 EXCL-03 用户可见闭环：仓库详情页排除区新增「AI 敏感文件建议」面板——按 severity 排序展示建议、real_secret 高优先级告警、接受（幂等建 `ai_suggested` 排除规则）/忽略（dismiss）操作，接受后引导用户用既有「对账与清理」面板做显式删除（绝不静默删）。接通 24-03 REST 契约与 Phase 22/23 既有面板。
- 索引时把每个 chunk 的 1-based 闭区间源码起止行写入 ChunkRegistry（line_start/line_end），打通 `file:line → chunk_id` 反查的数据地基——create + update 双路径落库，重切分行号位移触发更新，复用既有 CheckConstraint 无新 migration
- 给定 repo+file+line 定位覆盖该行的 chunk(s)：`find_chunk_at` 服务按 1-based 闭区间命中、最具体（区间最小）优先，复用 Phase 22 单一排除匹配器对被排除文件全程 fail-closed；`GET /api/repositories/<id>/chunk-at/` REST 端点认证保护，被排除文件与无命中对外同形返回空 chunks 不泄漏存在性。
- git 历史按 commit 产出 RAG 文档（message + author + 变更文件路径摘要），经 Phase 22 单一匹配器 fail-closed 剔除被排除文件、截断、embedding 入 Qdrant 主 collection 并打 kind=commit payload，确定性 uuid5 point id + 合成 file_path 保 dedup，增量 boundary..HEAD 只索引新 commit、upsert 成功才推进边界。
- 把 25-03 的 `index_commits` 以 best-effort 方式挂接进 `clone_and_index_repository`——仅 base 索引路径、紧随敏感检测之后、临时克隆 `rmtree` 之前 `await` 完成（沿用 Phase 24 BL-01 时序），全量与增量均流经；commit 索引失败仅 warning 绝不阻断索引 success；并以端到端守护测试验证 commit 文档经既有 `search_rag` 用关键字/author 召回、被排除文件不泄漏、增量只新增。
- GitInstanceCredential 按 host 维度集中存 Fernet 加密 token，配套单一解析器 per-repo 优先 → 实例池 host fallback，多仓复用一份凭证且向后兼容
- 把 26-01 解析器接入「克隆 / 索引 / bare 镜像 fetch / 图谱克隆」三条取 token 路径，消除散落的内联 `GitCredential → decrypt_value`，无 per-repo token 的同 host 多仓改为复用实例凭证，per-repo token 仍优先（向后兼容）
- 把 26-01 解析器接入「git 平台 MR/PR 客户端 + 编码容器 dispatch 的 git token 注入 + diff archive 拉取」五处取 token 路径，无 per-repo token 的同 host 多仓改为按 host 复用实例凭证，per-repo token 仍优先（向后兼容）；token 绝不进日志
- 实例级 Git 凭证 REST CRUD（token write-only Fernet 加密、IsSuperUser、API/DB/日志/前端全程无明文）+ Vue 3 管理页（has_token 徽标、token 不回显）+ base-branch 校验改经统一解析器
- 为 MCP RAG 检索工具 `search_rag_chunks` 增加多仓（`repository_ids`）/ 全仓（`all_repositories`，受 `max_repos` 限制）检索参数，跨多仓合并召回并按 `item.repository_id` 标注结果来源仓库；多仓解析严格对齐 `grep_repository` 范式（serializer 产出 `target_repository_ids`，view 逐仓校验 + 一次性 `HybridSearchService.search(repository_ids=valid_ids)`），每仓仍经 Phase 22 `search_rag` chokepoint `build_matcher_for_repo` fail-closed 排除——被排除文件跨仓不可见；省略多仓参数时维持既有单仓行为与响应形状（向后兼容）。
- 把 26-VERIFICATION 标记的残留 6 文件 ≥8 处内联 `decrypt_value(credential.encrypted_token)` 取 token 全部改经统一解析器 `aresolve_git_token`，使仅靠实例凭证池（无 per-repo token）的同 host 仓库在 PR 创建/cross-reference/冲突预检/code review diff 拉取/两处容器 dispatch/既有仓库测试连接路径不再失败或注入空 token

---

## v0.4.0 工作流系统契约重构 (Shipped: 2026-06-13)

**Phases completed:** 5 phases, 25 plans, 58 tasks

**Key accomplishments:**

- 模板解析失败从静默空串/字面量保留改为三分类显式报错（中文 + 结构化 JSON 落 error_message），并落地嵌套 dict/list 路径下钻，两 API 共享同一纯函数解析核心。
- bulk-update 事务内实现客户端 short_id 权威落库 + 工作流内先到先得唯一性 + 缺失/冲突/非法时服务端重生成并全工作流重写 config 引用（复用公共化的 rewrite_template_refs），15 个集成测试锁定"保存成功 ⇒ 引用可解析"不变式。
- 新建 variableRef 单一构造 util 收口全部引用生成点（三入口 + schema 展示 + picker 前缀字面量），消灭 UUID 与 id.slice(0,8) 兜底；toBackendNodes 上送 short_id 补齐 VAR-01 前端半边；运行时 picker 双键去重。
- 逐文件核查 19 个 render_template/get_template_value 调用方：17 个 OK、2 个违规已最小修复（code_review chat_id 渲染前移、plan_generation as_of 渲染移出吞错 try），后端 workflows 358 测试 + 前端 983 测试全绿，A1 假设闭环。
- routing.py 边感知就绪/级联/死锁/target_handle 归集四类纯函数核心 + DAGNode.incoming_edges 入边明细，零 DB 单测全绿，为 18-02..05 主循环与回调续跑提供唯一语义源
- 调度主循环就绪/级联/后继/输入判定全部委托 18-01 routing 纯函数，条件分支真路由（仅选中支执行、未选中支级联 SKIPPED 且参与完成判定），target_handle 归集经端到端集成测试闭环；建立全阶段共享的 conftest 引擎测试基建。
- 主循环完成/挂起/死锁三类终局判定收口为单一 `_finalize_run_state`（双出口共用）：waiting_event/waiting_approval 统一挂起且不加回 pending（消灭热循环 + 永久 running 僵尸），死锁经 routing 诊断转 FAILED 写结构化 error_message，execution_suspended hook 打通；删除 5s 轮询分支与旧死锁分支。全量 tests/workflows/ 412 例零回归。
- `_continue_after_node` 退化为薄入口——执行级原子抢锁 → 带标记节点经 `_execute_node` 重跑（修复容器回调断裂 A1）→ `_rebuild_state_from_db` 重建真实 NE 状态重入 `_run_execution` 同一 while 调度循环与 `_finalize_run_state` 收口；coding_callback 第三套手工迷你调度器根除，三套回调收敛为一套统一入口。审计定性"两套路由实现漂移"最终消除。tests/workflows/ 419 例全绿、workflows+feishu+回调 519 例零回归。
- 后端 get_schema() 派生 default_config、NodeTypeSerializer 暴露 ui_schema/default_config（纯增量零回归），并新增 dump_node_fixture 管理命令把 33 个真实节点的精简定义快照入库，作为 CI 漂移守护对账基准。
- 幂等 Django 数据迁移 0026，把存量 `WorkflowNode.node_type='fetch_project_info'` 重写为真实节点 `fetch_space_info`，使老工作流收敛后仍能正确解析（D-03）。
- 把 `registry.ts` 对外 helper 改为从 `useNodeTypesStore`（唯一运行时源）读取并删除 `NODE_REGISTRY` legacy 硬编码区块，抽出前端专属 `CONFIG_COMPONENTS` 懒加载映射、降级 `validateNodeConfig` 为轻量 JSON-Schema 校验，并收敛全部消费方使 `pnpm type-check` 一次性通过。
- 把 `BaseWorkflowNode.vue` 的 Handle 改由 `useNodeTypesStore` 的 `inputs/outputs`（后端 NodePort）响应式渲染、store 未就绪时回退最小端口；`portConfig.ts` 的 `getDefaultPortsForNodeType` 退出正常渲染路径并保留 `migratePortId` 作存量 edge 兼容；`[id].vue` 取数顺序化（fetchNodeTypes 先行）并由后端 `category` 派生 `hasTriggers`。
- 前端展示层 `fetch_project_info` 全量改名 `fetch_space_info`、删除死代码 `IntegrationNode.vue`，并把 `node-sync.test.ts` 从手维 `EXPECTED_NODES` 重写为 fixture 驱动离线漂移守护、修正 `validate-node-definitions.ts` 的 API URL，同时修复 19-03 引入的 `workflow-data-table.test.ts` 缺 pinia 回归。
- 1. [Rule 2 - 缺失关键功能] bulk-update config 校验让位机制（serializer skip_config_validation context）
- 修复两个断裂内置模板（daily_summary 字段对齐 body/text；code_review_pipeline 按方案 A 去 http 中转节点、trigger→review[target_handle=coding_result]→notify、引 review_report、文档化 webhook payload 前提），让 loader 在 acreate 前调用与保存同源的 WorkflowGraphValidator 拒绝非法模板（TPL-03，无半残 workflow），并扩展 test_template_loader 守护每模板零 error + 5 类 schema 可判定断裂注入 + loader 拒绝（TPL-01/02/03）。
- 扩展 `useWorkflowValidationStore` 摄入后端 `WorkflowGraphValidator` 的 `{errors, warnings}`（severity + 多 reason，支持 node 级与 edge 级），让 `saveWorkflow` 在 bulk-update 返回 400 时解析结构化 body 灌入 store 并阻断保存，`IssuesPanel` 改由 store 真实驱动渲染并按 severity 区分 error/warning——消除「`useWorkflowValidationStore` 无调用方、`IssuesPanel` 的 `v-if=hasWarnings` 永 false」的死代码（VAL-03）。
- 为 TRIG-01/02/03 + OBS-01（后端）建立 13 个先行失败测试锚点：feishu 触发同步、schedule 枚举移除、dispatch 失败持久化、WS 失败广播——锁死修复后契约，待 21-03/04 转绿。
- 4 个 RED vitest spec 锁死 OBS-01/02/03 前端契约：ExecutionStatus 全覆盖 badge、node_failed 写 error 字段 + stats suspended 语义、WS 断线降级轮询、结构化变量错误 parse + error_code 行
- 修复触发链路根因：`async_sync_workflow_triggers` 改读单数 `event_type`（复数兜底）并把可正向表达的 filter 字段写入 `filter_config`，消除"读复数→恒空→trigger 被 deactivate→飞书事件无法匹配"；dispatch 失败不再静默吞掉——飞书路径落 `TriggerLog`（error/ignored + 截断 error_message），webhook 路径返回区分原因的结构化响应。
- 移除僵尸触发类型 schedule（枚举 + 0027 AlterField 安全收窄），并让 WebSocketBroadcastHook 在节点失败/超时时广播 error_message/error_code，将 21-01 的 RED 测试转绿。
- 前端移除所有工作流 schedule 假触发类型残留（联合类型/标签/图标 + 夹具），并将 executions 列表 statusOptions 与后端 ExecutionStatus 对齐（补 suspended/timeout）、stats 等待态按 execution 级 suspended + node 级 waiting_approval 区分
- NodeOverviewTab 展示 error_code + 结构化变量错误友好解析（非 JSON 回退纯文本）；DAG ExecutionNode 补 suspended/timeout 色 + 失败节点 error tooltip；useExecutionState 在 WS 断线时降级 REST 轮询（fetchExecution 权威值），重连/终态停止。

---

## v0.3.0 交付知识图谱 (Shipped: 2026-06-12)

**Phases completed:** 5 phases (12–16), 23 plans

**Delivered:** 把需求/缺陷、技术方案、编码 diff 全链路 RAG 化，并以带时间语义（bi-temporal）的知识图谱关联；任意入口可召回相似历史需求及其完整迭代轨迹。

**Key accomplishments:**

- 知识模型与图存储：四类实体 + bi-temporal 边 + supersedes 版本链 + GraphStore 递归 CTE 收口 + `delivery_knowledge` collection 生命周期
- 统一摄取与版本化：幂等异步摄取管线（chat/MCP/workflow/飞书/编码回调六类触发点），版本翻转与向量下线，全量 diff 归档与 MODIFIES_CHUNK 代码图谱对齐
- 时间感知混合检索：`DeliveryKnowledgeSearchService` 融合向量召回 + 图扩散 + 时间衰减 + LLM 二阶段分级，PG 轨迹/关联查询，fail-closed 权限过滤
- 多入口暴露：MCP PAT 三工具 / chat agent tools / workflow 检索节点 + ai_plan_generation 飞轮 / npm friday-knowledge skill，四入口复用 `exposure.py` 序列化
- 前端只读时间线：实体详情页 + 关联时间线 + as-of 时点查询，REST `/api/knowledge/*` 与 JWT 实体详情 API

**Stats:** 28/28 v1 requirements delivered, 2026-06-11 → 2026-06-12.

**Known deferred items at close:** 1 — Phase 14 真实 git platform 超大 diff 截断需 dev 环境人工验收（TD-14，详见 audit）

**Known follow-ups (tech debt):** — ✅ 全部已于 2026-06-14 解决（commit 5435fef23）

- ~~W1: 前端 `searchDeliveryKnowledge` 无 UI 消费（index 为占位页）~~ → index 改为真实搜索页
- ~~W2: timeline 节点级 `provenance` 未填充~~ → 前端渲染 + 修后端跨版本串味 bug
- ~~W3: graph enrich 边类型统一标为 RELATES_TO~~ → related.py 多跳取真实 edge.relation + 前端 relation 标签

---

## v0.1.0 首启初始化向导 (Shipped: 2026-06-09)

**Phases completed:** 5 phases, 9 plans

**Delivered:** 用「首次访问引导用户自设账号」替代启动期自动建管理员，并在向导内一次配好管理员、LLM 供应商、安全校验与可选的飞书/RAG 集成。

**Key accomplishments:**

- 首启门禁：无任何 superuser 时首次访问自动进入向导，已初始化实例 fail-closed 拒绝（防重入/防接管）
- 管理员自设：向导内自定义用户名+密码（强度校验），提交即建 superuser 并自动登录直达首页
- 供应商一键预设：DeepSeek V4 Pro / MiMo V2.5 Pro / Kimi 2.6 / Anthropic 官方 / 自定义端点，Fernet 加密落库 + 健康校验 + 绑定 Claude Code 模型映射
- 安全与可选集成：SECRET_KEY/FRIDAY_ENCRYPTION_KEY 风险校验（非阻塞）+ 可一键跳过的飞书、向量检索（Qdrant/Embedding）配置步骤
- 向后兼容：`entrypoint.sh` 默认不再自动建号，`init_superuser`/`reset_superuser_password` 保留为运维兜底，老部署升级不回退

**Known deferred items at close:** 2 — Phase 01 / 02 人工验收（UAT）签字未完成（功能已实现，详见 STATE.md Deferred Items）

---

## v0.2.0 用户身份令牌与 Agent 工具打通 (Shipped: 2026-06-10)

**Phases completed:** 6 phases (6-11), 21 plans

**Delivered:** 给每个用户一套 GitHub/GitLab 风格的个人访问令牌（PAT），以「用户身份 + 用户权限」贯通认证、会话隔离、管理员只读后台与 agent 工具链路，使 skill/mcp 能以用户令牌在容器内执行。

**Key accomplishments:**

- PAT 模型增强：令牌加名称/备注/可选有效期（默认永久、不可延期）+ 前缀…后缀指纹，明文仅展示一次（仅存 sha256），用户自助创建/吊销
- 令牌即用户身份（认证地基）：PAT 认证返回 owner 并施加其 RBAC（替代「有效即全权限」），friday_pat_ 前缀闸门让 PAT/JWT 互不干扰，MCP/工具入口收紧为 fail-closed
- 对话/会话用户隔离：Conversation 加 created_by + 历史回填最早 superuser，全 25 路径按 owner 过滤（含 SSE/WebSocket），越权 404 不泄漏存在性
- 管理员只读会话后台：物理隔离的 /api/admin/conversations/（IsSuperUser）浏览所有会话，只读防误操作，交互需 fork 到自己名下
- MCP 绑定 + RemoteTool 执行端点：ToolTokenBinding 持久绑定令牌给 skill/mcp，新增经 PAT 认证 fail-closed 的按工具 name 执行端点供容器回调
- task 容器接通（链路机制闭环）：容器消费 remote_tools 经 SDK MCP server 加载工具，PAT 经 server→runner→task 直传注入并全程脱敏，令牌吊销 graceful（在途跑完仅阻断新调用）

**Stats:** ~6,200 行净增（60 文件，server/web/runner/task），150 commits，2026-06-09 → 2026-06-10。

**Known deferred items at close:** 6 — Phase 6-11 人工验收（UAT）顺延（自动化全绿，浏览器/容器级 E2E 待人工确认，详见 STATE.md Deferred Items）。

**Known follow-ups (tech debt, by-design):** — 部分已于 2026-06-14 解决

- ✅ ~~Phase 11 实时明文 PAT 通道（contextvar）未接入：_resolve_user_pat 恒返回 ''，RemoteTool 链路休眠~~
  → 已接入（commit 8cb50e928）：请求级 ContextVar → ExecutionContext 瞬态字段，AICoding dispatch 注入 USER_TOKEN；
  明文绝不落库/进日志。剩余：chat/MCP dispatch 路径未覆盖；带 PAT 容器端 E2E 待真实环境验收

- MCPB-02 集成 PARTIAL：执行端点已按 PAT 认证为 owner，但 execute_tool 未接收 user 上下文（仍 deferred）
- ✅ ~~Nyquist 卫生：各阶段 *-VALIDATION.md frontmatter nyquist_compliant 仍为 false~~ → v0.4.0 的 18-21 已回填（commit 37a3bd6b2）

---
