# Roadmap: Friday AI

## Milestones

- 🚧 **v0.4.0 工作流系统契约重构** — Phases 17–21 (in progress)
- ✅ **v0.3.0 交付知识图谱** — Phases 12–16 (shipped 2026-06-12) — [archive](./milestones/v0.3.0-ROADMAP.md)
- ✅ **v0.2.0 用户身份令牌与 Agent 工具打通** — Phases 6–11 (shipped 2026-06-10) — [archive](./milestones/v0.2.0-ROADMAP.md)
- ✅ **v0.1.0 首启初始化向导** — Phases 1–5 (shipped 2026-06-09) — [archive](./milestones/v0.1.0-ROADMAP.md)

## v0.4.0 工作流系统契约重构 (IN PROGRESS)

**Milestone:** v0.4.0 工作流系统契约重构 — 保存即合法、模板开箱能跑、执行真实可见
**Created:** 2026-06-12
**Phases:** 5（Phase 17–21，接续 v0.3.0 的 Phase 16）
**Requirements:** 24 条 v1 需求（VAR×4 / TPL×3 / SSOT×3 / VAL×3 / ENG×5 / TRIG×3 / OBS×3）

## Overview

收敛工作流系统的「编辑态契约」与「运行态契约」。构建顺序按依赖排列：先把运行态语义修对——变量引用解析（Phase 17）与引擎状态机（Phase 18）是其余一切的语义地基；随后前端节点定义收敛到后端 registry 单一事实源（Phase 19），为校验层提供权威的端口/schema 依据；接着把校验前移到保存与模板创建（Phase 20，`WorkflowGraphValidator` 统一 bulk-update / 导入 / 模板 loader，并以定稿的解析语义修复 4 个内置模板）；最后清理触发模型断裂并补齐执行可观测（Phase 21），让"触发了没跑 / 跑了像卡住"的黑箱体验消失。核心引擎骨架（DAG/Engine/BaseNode）保留，重点是契约收敛与校验前移，不是推倒重写。

## Phases

- [x] **Phase 17: 变量引用链路修复** - 自建流水线 short_id 保存同步/重写，解析失败显式报错，前端引用入口统一格式，嵌套路径与解析器测试 (completed 2026-06-12)
- [x] **Phase 18: 执行引擎状态机修复** - waiting_event 完成判定、next_handle 分支路由、trigger_data 注入、死锁诊断、target_handle 语义收敛与引擎回归测试 (completed 2026-06-13)
- [x] **Phase 19: 节点定义单一事实源** - 前端面板/端口/表单 schema 收敛到 `GET /api/node-types/`，删除硬编码 registry 与 portConfig，CI 一致性守护 (completed 2026-06-13)
- [ ] **Phase 20: 保存即合法与模板修复** - `WorkflowGraphValidator` 统一校验（保存/导入/模板共用），IssuesPanel 接真实结果，4 个内置模板修复 + 可执行性校验测试
- [ ] **Phase 21: 触发模型与执行可观测** - 飞书 event_type 断裂修复、schedule 假功能处理、dispatch 失败可查，执行详情错误展示 + WS 断线轮询兜底 + 状态枚举对齐

## Phase Details

### Phase 17: 变量引用链路修复

**Goal**: 用户在变量选择器里选中的引用，保存后执行时所选即所得——可解析则取到值，不可解析则显式报错指明原因
**Depends on**: Nothing（本里程碑首个阶段）
**Requirements**: VAR-01, VAR-02, VAR-03, VAR-04
**Success Criteria** (what must be TRUE):

  1. 用户在自建流水线中通过变量选择器选择上游节点输出引用并保存（bulk-update），执行时该引用保证可解析——客户端 short_id 被同步落库或服务端重写 config 引用，不再因 short_id 漂移抛 ValueError
  2. 变量引用解析失败（节点 ID 不存在、字段不存在、未知前缀）时，对应节点显式失败，错误信息指明是哪个引用、哪个节点/字段缺失；不再静默替换为空串或原样保留 `{{...}}` 字面量
  3. 变量选择器、端口复制、SmartInput 三个入口生成的引用格式统一（统一用 short_id），与后端解析器支持的语法完全一致
  4. `{{nodes.x.data.name}}` 形式的嵌套字段路径能取到 `output["data"]["name"]`，且 `render_template`/`get_template_value` 对错误 ID、未知前缀、UUID vs short_id、嵌套路径均有专项单元测试覆盖

**Plans**: 4 plans

Plans:
**Wave 1**

- [x] 17-01-PLAN.md — 解析核心 template_resolver.py（四分类报错 + 嵌套下钻）+ base.py 两 API 委托 + scheduler 结构化 error_message + 专项单测（VAR-02, VAR-04）
- [x] 17-02-PLAN.md — bulk-update 落库客户端 short_id：唯一性校验、冲突重生成、同事务全 config 重写 + 不变式测试（VAR-01）
- [x] 17-03-PLAN.md — 前端统一引用构造 util 三入口收口 + toBackendNodes 上送 short_id（VAR-03, VAR-01）

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 17-04-PLAN.md — 调用面渲染时机/吞错逐节点核查 + 后端/前端全链路回归（wave 2，VAR-01..04）

**UI hint**: yes

### Phase 18: 执行引擎状态机修复

**Goal**: 执行引擎的运行态语义真实可信——等待就是 suspended、分支按 handle 路由、触发数据可引用、死锁有诊断，不再出现"显示完成实际没跑完 / 永远 running"
**Depends on**: Phase 17（解析失败语义定稿，trigger_data 引用复用同一解析路径）
**Requirements**: ENG-01, ENG-02, ENG-03, ENG-04, ENG-05
**Success Criteria** (what must be TRUE):

  1. 含 waiting_event（审批/事件等待）节点的执行不会被误判为 completed，挂起（suspended）状态经 API/WS 对前端真实可见
  2. 条件分支在调度主循环与回调续跑两条路径下行为一致：均按节点结果 `next_handle` 与边 `source_handle` 路由，未选中分支的节点正确标记 skipped
  3. 任意触发方式（飞书事件、手动、API）发起的执行中，`{{trigger.*}}` 引用都能解析出触发数据
  4. DAG 死锁（有 pending 但无 ready 且无等待节点）时执行明确转 failed，错误信息列出哪些节点在等待哪些未满足的依赖，不留无限 running
  5. 节点输入收集尊重 `target_handle` 语义（或该字段被明确移除并统一文档/前端展示），且调度、分支、死锁、等待四类引擎核心路径有自动化回归测试

**Plans**: 5 plans

Plans:
**Wave 1**

- [x] 18-01-PLAN.md — routing.py 纯函数路由核心（就绪/级联/死锁/归集）+ DAGNode 入边明细 + 零 DB 单测

**Wave 2**

- [x] 18-02-PLAN.md — conftest 测试基建 + 主循环就绪/级联/输入接入 routing + target_handle 端到端测试

**Wave 3**

- [x] 18-03-PLAN.md — 完成/挂起/死锁收口（waiting ⇒ suspended、删轮询、热循环修复、死锁结构化转 failed）

**Wave 4**

- [x] 18-04-PLAN.md — 回调续跑重入主循环 + 执行级互斥 + 容器回调断裂修复 + coding_callback 迷你调度器删除

**Wave 5**

- [x] 18-05-PLAN.md — trigger_data 写入 source 键 + resume_from_node 继承 + _execute_node 注入 + {{trigger.*}} 端到端测试

### Phase 19: 节点定义单一事实源

**Goal**: 后端节点 registry 成为唯一事实源——前端面板、表单、画布端口全部由 `GET /api/node-types/` 驱动，前后端节点定义不再漂移
**Depends on**: Nothing（可与 Phase 17/18 并行；建议序贯执行排在 18 后）
**Requirements**: SSOT-01, SSOT-02, SSOT-03
**Success Criteria** (what must be TRUE):

  1. 前端节点面板（palette）、配置表单 schema、默认 config 全部以 `GET /api/node-types/` 返回为准，硬编码 `NODE_REGISTRY` 删除后画布编辑功能不回退，幽灵节点 `fetch_project_info` 不再出现（指向真实的 `fetch_space_info`）
  2. 画布节点的输入/输出 Handle 按后端 NodePort 定义渲染：`ai_coding` 显示 `plan` 输入、`ai_code_review` 显示 `coding_result` 输入、审批节点显示 `approved`/`rejected` 输出，`portConfig.ts` 硬编码被替换
  3. 前后端节点定义一致性有 CI 自动化守护：前端消费的节点 type/端口与后端 registry 漂移时 CI 失败（或前端定义完全由后端生成、无需对账）

**Plans**: 5 plans

Plans:
**Wave 1**

- [x] 19-01-PLAN.md — 后端 get_schema 派生 default_config + NodeTypeSerializer 暴露 ui_schema/default_config + dump_node_fixture 离线快照 + 后端字段断言（SSOT-01, SSOT-03）
- [x] 19-02-PLAN.md — 幽灵节点存量数据幂等迁移 fetch_project_info → fetch_space_info（SSOT-01）

**Wave 2** *(depends on 19-01)*

- [x] 19-03-PLAN.md — store 接口扩字段 + registry helper 改 store 适配器 + 删 NODE_REGISTRY legacy + 消费方收敛 + validateNodeConfig 降级（SSOT-01）
- [x] 19-04-PLAN.md — BaseWorkflowNode Handle 由 store inputs/outputs 渲染 + 最小回退 + portConfig 降级保留 migratePortId + [id].vue 顺序化（SSOT-02）

**Wave 3** *(depends on 19-01, 19-03)*

- [x] 19-05-PLAN.md — 幽灵前端全量改名 + 死代码清理 + node-sync fixture 驱动漂移守护 + validate-node-definitions URL 修正（SSOT-03, SSOT-01）

**UI hint**: yes

### Phase 20: 保存即合法与模板修复

**Goal**: 非法工作流在保存/导入/模板创建时就被结构化拒绝，而不是执行时才失败；4 个内置模板开箱即可跑通
**Depends on**: Phase 17（变量引用解析语义定稿）、Phase 18（模板端到端执行依赖引擎路由正确）、Phase 19（端口/schema 校验以收敛后的 registry 为权威依据）
**Requirements**: VAL-01, VAL-02, VAL-03, TPL-01, TPL-02, TPL-03
**Success Criteria** (what must be TRUE):

  1. 保存非法工作流（DAG 环/无入口/孤立节点、edge 归属或 handle 非法、节点 config 不合 schema、变量引用不可解析）时，bulk-update / 单节点边 CRUD / 导入返回结构化错误（节点 id + 字段路径 + 原因）；合法工作流保存不受影响
  2. 前端保存前可调用 dry-run 校验接口，IssuesPanel 真实展示后端校验的警告/错误（不再是永不出现的死代码）
  3. 用户从任一内置模板（含 `daily_summary`、`code_review_pipeline`）创建工作流后，不修改任何配置即可成功执行到业务预期结果
  4. 模板自动化校验测试覆盖：节点 type 存在于 registry、config 必填字段齐全、`{{ }}` 变量引用的节点 ID 与字段在上游输出 schema 中存在、edge handle 与节点端口定义一致——人为注入断裂的模板会让测试失败
  5. 模板创建（loader）在实例化前执行与保存相同的图校验（同一 `WorkflowGraphValidator`），非法模板拒绝创建并返回结构化错误

**Plans**: TBD
**UI hint**: yes

### Phase 21: 触发模型与执行可观测

**Goal**: 触发链路真实可用、失败可查；执行状态与节点错误在前端如实呈现，用户不再把"失败"误感知为"卡住"、把"没触发"误感知为"没反应"
**Depends on**: Phase 17（失败变量引用的错误信息）、Phase 18（suspended 状态与死锁诊断对前端可见）
**Requirements**: TRIG-01, TRIG-02, TRIG-03, OBS-01, OBS-02, OBS-03
**Success Criteria** (what must be TRUE):

  1. 画布保存 `feishu_event_trigger` 节点后 `WorkflowTrigger` 表正确生成（`event_type`/`event_types` 字段统一），对应飞书事件能匹配并触发工作流执行
  2. `schedule` 触发类型不再是假功能：定时调度按配置真正注册并 dispatch（django-apscheduler），或该选项从模型/UI 中移除、用户无法再配置出不生效的触发器
  3. 触发分发失败不再被静默吞掉：dispatch 异常记录到可查询的位置（执行记录或事件日志），用户能看到"触发了但没跑起来"的原因
  4. 执行详情页节点失败时清晰展示 error_message、失败的变量引用与重试情况；WebSocket 断线时自动降级 REST 轮询（与列表页一致），长时执行 UI 不冻结，进度以服务端权威值为准
  5. 执行整体状态（running/suspended/failed 等）在列表与详情页如实展示，前端状态枚举与后端 `ExecutionStatus` 对齐，前端引用的不存在状态值（如 `waiting_approval`）被清除或后端补齐

**Plans**: TBD
**UI hint**: yes

## Progress

**Execution Order:** 17 → 18 → 19 → 20 → 21（19 可与 17/18 并行；20 必须在 17/18/19 之后；21 必须在 17/18 之后）

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 17. 变量引用链路修复 | 4/4 | Complete    | 2026-06-12 |
| 18. 执行引擎状态机修复 | 5/5 | Complete    | 2026-06-13 |
| 19. 节点定义单一事实源 | 5/5 | Complete    | 2026-06-13 |
| 20. 保存即合法与模板修复 | 0/? | Not started | - |
| 21. 触发模型与执行可观测 | 0/? | Not started | - |

## Coverage Map

| Phase | Requirements | Count |
|-------|--------------|-------|
| 17 | VAR-01, VAR-02, VAR-03, VAR-04 | 4 |
| 18 | ENG-01, ENG-02, ENG-03, ENG-04, ENG-05 | 5 |
| 19 | SSOT-01, SSOT-02, SSOT-03 | 3 |
| 20 | VAL-01, VAL-02, VAL-03, TPL-01, TPL-02, TPL-03 | 6 |
| 21 | TRIG-01, TRIG-02, TRIG-03, OBS-01, OBS-02, OBS-03 | 6 |

**Total:** 24/24 v1 requirements mapped ✓（无孤儿、无重复）

## Notes

- **Phase 编号接续**：v0.3.0 止于 Phase 16，本里程碑从 Phase 17 起连续编号。
- **VAL 与 TPL 合并为 Phase 20**：两者共享同一 `WorkflowGraphValidator`——TPL-03 要求模板 loader 走与保存相同的校验，TPL-02 的模板校验测试本质是 validator 在模板夹具上的应用；拆开会导致校验器被两个阶段反复改动。修模板（TPL-01）需要 VAR 解析语义（Phase 17）定稿，且"开箱能跑到业务预期结果"依赖引擎路由（Phase 18）正确，故压在两者之后。
- **TRIG 与 OBS 合并为 Phase 21**：两者共同回答"触发/执行到底发生了什么、用户能不能看到"——TRIG-03（dispatch 失败可查）与 OBS-01（节点错误可见）是同一条可观测叙事；且 OBS-03 状态对齐依赖 Phase 18 修复后的真实状态机语义。
- **Phase 19 的并行性**：SSOT 收敛纯属编辑态、不依赖引擎修复，技术上可与 17/18 并行；序贯执行时排在 18 后、20 前（VAL-03 IssuesPanel 与端口 handle 校验需要收敛后的端口定义作为权威依据）。
- **审计映射（2026-06-12 三路代码审计）**：审计发现 1（变量引用断裂）→ Phase 17；发现 5（引擎状态机）→ Phase 18；发现 3（节点定义三套源）→ Phase 19；发现 2+4（模板断裂、保存零校验）→ Phase 20；发现 6+7（触发模型、可观测）→ Phase 21。
- **关键防线**：解析失败行为（VAR-02）的语义定稿是 Phase 20 变量引用校验与 Phase 21 错误展示的共同上游，必须在 Phase 17 一次定对；`WorkflowGraphValidator` 的校验规则与 registry 端口定义（Phase 19 产物）保持单源，避免校验器内再长出第四套节点定义。

---
*Created: 2026-06-12*
*Milestone: v0.4.0 工作流系统契约重构*
*Previous milestones archived in .planning/milestones/*
