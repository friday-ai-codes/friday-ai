# Roadmap: Friday AI

## Milestones

- 🚧 **v0.13.0 并发治理与索引体验** — Phases 65–70 (planning 2026-06-23)
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

### 🚧 v0.13.0 并发治理与索引体验 (Phases 65–70 — IN PROGRESS)

**Milestone Goal:** 按资源分治引入可配置的并发治理——仓库索引/图谱用 Procrastinate 原生 `lock` 槽位锁池排队（可配上限、原生排队、不和 KEDA 冲突、同仓串行），LLM 按 `ProviderCredential.max_concurrency` 凭证级限流（排队等待 + 友好提示），容器复用 `runner.concurrent`，MCP 不限，**不设全局总上限**；修复 AI 对话跨会话串流；新增超管"全部更新索引"+ 批量建仓（CSV 导入数百仓库受限并发消费）；统一索引/图谱/AI 描述的实时进度并修复进度条回退；默认禁用 LSP 仅用 tree-sitter；把仓库 access token 重构为可选的"密钥提供方(FK)"模型。

> 前置：本地落后 `origin/main` 6 个提交（PgBouncer / worker-scheduler 分流 / 角色感知连接池），**动手前先 `git pull origin main`**，以拉取后为基线。

- [x] **Phase 65: AI 对话串流隔离修复** - 流式状态与副作用按 `conversation_id` 隔离，切会话不串台（后台流继续但仅写回所属会话）— STREAM-01 — completed 2026-06-23
- [x] **Phase 66: 默认禁用 LSP（仅 tree-sitter）** - Volar/gopls backend 默认关闭可开关恢复，向量路径回落 TreeSitterBackend，缓解图谱构建慢 — LSP-01 — completed 2026-06-23
- [x] **Phase 67: 并发治理（槽位锁池 / provider 限流 / 容器上限）** - 索引/图谱 Procrastinate `lock` 槽位池 + LLM 凭证级限流器 + 容器 runner.concurrent，无全局总上限 — CONC-01, CONC-02, CONC-03 — completed 2026-06-23
- [x] **Phase 68: 实时进度统一 + 进度条修复** - 进度单调不回退 + 图谱实时进度 + AI 描述状态可见 — PROG-01, PROG-02 — completed 2026-06-23
- [x] **Phase 69: 批量加仓 + 全部更新索引（超管）** - 超管一键全量重索引 + 批量建仓（CSV 数百仓库），受 67 并发上限排队消费 — BATCH-01, BATCH-02 — completed 2026-06-23
- [x] **Phase 70: access token / 密钥提供方重构（FK）** - 仓库 token 可选 + 显式 FK 选实例凭证 + provider URL 拼接与失焦校验 — TOKEN-01, TOKEN-02 — completed 2026-06-23

## Phase Details

### Phase 65: AI 对话串流隔离修复

**Goal**: 修复 AI 对话跨会话"串流"——把前端全局单例 streaming 状态与副作用改为按 `conversation_id` 隔离，切换会话时正在进行的另一会话回答不再串入当前会话 UI
**Depends on**: Nothing（前端为主，复用已修复的 ClarificationCard 跨会话过滤模式；后端 SSE 已按 conversation_id 隔离）
**Requirements**: STREAM-01
**Success Criteria** (what must be TRUE):

  1. 会话 A 流式输出进行中切换到会话 B，B 的界面不再出现 A 的 token / 回答（实时显示与刷新后均正确）
  2. `useSSEStream` 的流处理闭包绑定发起时的 `conversation_id`，模块级 `currentRunId` 改为每流独立、不再跨并发流互相覆盖
  3. `handleSSEEvent` / `sendMessage` 的 finally merge / `title_generated` / `scheduleRuntimePoll` 等副作用均校验"事件所属会话 === 当前会话"，不符则不写当前 UI（数据仍由后端 finalize 落库）
  4. 既有正常单会话流式、停止(stop)、刷新恢复行为零回归，vitest 守护覆盖"切会话不串台"

**Plans**: TBD（plan-phase 拆分）

**UI hint**: yes

### Phase 66: 默认禁用 LSP（仅 tree-sitter）

**Goal**: 把代码索引/图谱构建默认切到仅 tree-sitter（关闭 Volar/gopls LSP backend），缓解图谱构建慢与 LSP 冷启动等待，后续调好再经环境开关重开
**Depends on**: Nothing
**Requirements**: LSP-01
**Success Criteria** (what must be TRUE):

  1. `VOLAR_BACKEND_ENABLED` / `GOPLS_BACKEND_ENABLED` 默认 `False`（`server/friday/settings.py`），`codegraph/apps.py::ready()` 不再注册 Volar/gopls backend，启动无 LSP 冷启动等待
  2. 向量抽取路径（`services/unified_extraction`）在 LSP 关闭时正确回落 `TreeSitterBackend`，索引与图谱构建成功、不报错
  3. `.env.example` / compose / helm configmap 注释说明两个开关用途与"调好后重开"
  4. 显式设置 env 开启后 LSP 行为恢复（开关可逆，无需改代码）

**Plans**: TBD（plan-phase 拆分）

### Phase 67: 并发治理（槽位锁池 / provider 限流 / 容器上限）

**Goal**: 按资源分治引入可配置并发治理——索引/图谱用 Procrastinate 原生 `lock` 槽位锁池排队、LLM 按 provider 凭证各自限流、容器复用 runner.concurrent，跨 compose/k8s 多 worker 生效，不设全局总上限
**Depends on**: Nothing（核心基建；为 Phase 68 状态字段、Phase 69 批量并行度提供约束）
**Requirements**: CONC-01, CONC-02, CONC-03
**Success Criteria** (what must be TRUE):

  1. 批量触发多个仓库索引时，同时进 `doing` 的索引 job ≤ `CONCURRENCY_INDEX_MAX`（系统设置默认 5），其余在 durable 队列 `todo` 原生排队等待；图谱同理受 `CONCURRENCY_GRAPH_MAX`（默认 3）；同一仓库不会并发两个索引（恒定同槽串行）
  2. `DurableTaskService.defer` / backends 门面支持 `lock` 透传，index/graph 入队带 `lock=index-slot-{hash(repo_id)%N}`，N 从 `SystemSetting` 实时读取、改值对新任务生效，且不与 KEDA `todo` 深度伸缩形成空转扩容反馈环
  3. 每个 `ProviderCredential` 可配 `max_concurrency`（默认 50、0=不限）；chat/深度分析/编码的 LLM 调用按凭证 id 限流（Redis 租约信号量 + 进程内 fallback），超过该凭证上限时排队等待、超时返回友好"系统繁忙"，不打到 provider 触发 429/异常
  4. 容器（深度分析/编码）并发仍受 `runner.concurrent` 约束并在设置/文档可见；MCP 工具调用不受任何并发限制
  5. 单 worker（compose）与多 worker（k8s KEDA）部署下分类并发上限均生效（跨进程，经 DB/队列原语而非进程内信号量）

**Plans**: TBD（plan-phase 拆分）

### Phase 68: 实时进度统一 + 进度条修复

**Goal**: 统一并修正索引/图谱/AI 描述的实时进度——索引进度条单调不回退、图谱实时进度、AI 描述状态在前端可见
**Depends on**: Phase 67（对齐并发与仓库状态字段）
**Requirements**: PROG-01, PROG-02
**Success Criteria** (what must be TRUE):

  1. 索引进度条单调递增不回退（消除"文件级 90%/100% → chunk 级 0%"跳变），重新触发索引不残留上一轮 100%
  2. 向量索引阶段前端实时展示百分比 + 阶段文案（解析中/生成向量中/写入向量库中）
  3. 图谱构建展示实时进度（百分比 + 当前文件），`graph_files_total` 在开始即写、`update_graph_progress` 持续推送（图谱作为独立轨展示，不把向量 100% 拉回）
  4. AI 描述生成在前端展示"排队中 / 生成中 / 完成 / 失败"状态

**Plans**: TBD（plan-phase 拆分）

**UI hint**: yes

### Phase 69: 批量加仓 + 全部更新索引（超管）

**Goal**: 支持经 CSV 批量导入数百个仓库，并给超级管理员一键"全部更新索引"，批量入队受 Phase 67 并发上限排队消费、不打爆资源
**Depends on**: Phase 67（并发上限约束批量并行度）
**Requirements**: BATCH-01, BATCH-02
**Success Criteria** (what must be TRUE):

  1. 超级管理员在仓库列表页可见并点击"全部更新索引"，把全部未删除仓库批量入队（普通用户不可见/不可调用，`IsSuperUser` fail-closed）
  2. 批量入队的数百个仓库受 `CONCURRENCY_INDEX_MAX` 排队消费，不一次性打爆 CPU/内存
  3. 提供批量建仓能力（接受数组的批量接口或明确可复用现有 create 接口循环），支持 CSV 导入数百仓库
  4. 触发后前端给出"已排队 N 个"反馈

**Plans**: TBD（plan-phase 拆分）

**UI hint**: yes

### Phase 70: access token / 密钥提供方重构（FK）

**Goal**: 把仓库 access token 重构为可选——仓库可显式选择"密钥提供方"（`GitInstanceCredential` FK）或填自有 token；建仓表单按 provider 拼接 URL 并失焦校验
**Depends on**: Nothing（相对独立；复用现有 `GitInstanceCredential` 实例池 + `aresolve_git_token` 解析器）
**Requirements**: TOKEN-01, TOKEN-02
**Success Criteria** (what must be TRUE):

  1. `Repository` 增加可空 `git_instance_credential` FK + migration；token 解析优先级 per-repo → FK 实例凭证 → host 自动匹配 → 无，老仓库（仅 per-repo token 或仅 host 匹配）行为零回归
  2. 建仓 `access_token` 改为可选；可选择"密钥提供方"(实例凭证) 或填自有 token；`has_credential` 反映"per-repo 或实例池可解析"
  3. `TestConnection`（含新建路径）在无 token 时按 FK/host fallback 实例池校验仓库存在性/权限
  4. 建仓表单选 provider 后 URL 拆段拼接（前缀 `https://{host}` 只读 + 中间 group/repo 输入框 + 固定 `.git`），失焦后自动校验仓库存在性/权限
  5. 全局凭证 admin 页（`git-credentials`）补"按 provider + host 生效"用途说明

**Plans**: TBD（plan-phase 拆分）

**UI hint**: yes

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

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 65. AI 对话串流隔离修复 | 1/1 | Complete | 2026-06-23 |
| 66. 默认禁用 LSP（仅 tree-sitter） | 1/1 | Complete | 2026-06-23 |
| 67. 并发治理（槽位锁池 / provider 限流 / 容器上限） | 3/3 | Complete | 2026-06-23 |
| 68. 实时进度统一 + 进度条修复 | 1/1 | Complete | 2026-06-23 |
| 69. 批量加仓 + 全部更新索引（超管） | 1/1 | Complete | 2026-06-23 |
| 70. access token / 密钥提供方重构（FK） | 1/1 | Complete | 2026-06-23 |

**Execution order:** 65 → 66 → 67 → 68 → 69 → 70。依赖链：65（串流隔离，前端为主、独立低风险，打头阵）、66（禁用 LSP，配置改动缓解图谱慢，独立）、67（并发治理核心基建）→ 68（进度统一，依赖 67 状态字段）、69（全部更新索引 + 批量建仓，依赖 67 并发上限排队消费）；70（token/密钥提供方重构，相对独立、工作量最大，排最后）。65/66/70 与主线相对独立可并行，67 是 68/69 的硬依赖。

**UI 触面（标 UI hint）:** Phase 65（chat 前端流式隔离）、Phase 68（仓库索引/图谱/AI 描述进度卡片）、Phase 69（仓库列表页"全部更新索引"按钮 + 反馈）、Phase 70（建仓/编辑/凭证弹窗 + provider URL 拼接与失焦校验）。`/gsd-ui-phase` 可介入 68/69/70。后端为主的 66/67 无 Web 前端重触面。

里程碑 v0.1.0–v0.12.0（Phases 1–64）均已交付。v0.13.0 并发治理与索引体验（Phases 65–70）planning 中。

---
*Previous milestones archived in .planning/milestones/*
