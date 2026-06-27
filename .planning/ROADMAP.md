# Roadmap: Friday AI

## Milestones

- 🚧 **v0.16.1 统一 AI 技术方案生成（图编排归一 + 插槽式澄清拼接 + 能力完善）** — Phases 90–95 (in progress) — patch 级优化/统一：4 套分散方案生成归一到 `plan_orchestration`、废弃 LangChain `ai_plan_generation`、完善澄清/拆分能力 + 插槽式编辑范式（18 v1 需求 UNIFY/CLARIFY/SLOT/DECOMP）
- ✅ **v0.16.0 项目工作区（飞书文档双向同步 + IDE 上下文闭环 + feature list 交付流水线）** — Phases 82–89 (shipped 2026-06-26) — 里程碑审计 tech_debt（37/37 需求满足 / integration_ok；遗留真机/live-platform 验收 + 既有并发测试欠债）见 [audit](./milestones/v0.16.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.16.0-ROADMAP.md)
- ✅ **v0.15.0 项目（交付上下文聚合根）** — Phases 76–81 (shipped 2026-06-26) — 里程碑审计 passed（38/38 需求满足 / integration_ok）见 [audit](./milestones/v0.15.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.15.0-ROADMAP.md)
- ✅ **v0.14.0 可观测性与日志治理** — Phases 71–75 (shipped 2026-06-24) — 里程碑审计 passed（34/34 需求满足 / integration_ok）见 [audit](./milestones/v0.14.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.14.0-ROADMAP.md)
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

> 历史里程碑详情归档在 `.planning/milestones/`，要点见 `MILESTONES.md`。

## Phases

### 🚧 v0.16.1 统一 AI 技术方案生成（图编排归一 + 插槽式澄清拼接 + 能力完善）(Phases 90–95) — IN PROGRESS

> patch 级优化/统一里程碑（非新功能）。把工作流 / 对话 / MCP 三入口的 4 套分散「AI 技术方案生成」归一到唯一图编排底座 `plan_orchestration`，废弃旧 LangChain 单 agent `ai_plan_generation`，并完善能力——结构化交互式澄清（多轮 resume）、LLM 跨仓拆分、方案推群干净渲染、插槽式（形状端口磁吸）编辑范式。**依赖顺序**：澄清能力/数据（90）→ 出口面 + resume（91）→ 插槽后端（92）→ 插槽前端（93）；入口统一（94）依赖澄清单一来源（90/91）；拆分完善（95）相对独立可收尾。

- [x] **Phase 90: 澄清能力层** — 结构化 `Clarification` 数据模型 + LLM 多问题生成 + 入口无关统一提问能力（CLARIFY-01/02/03） (completed 2026-06-27)
- [x] **Phase 91: 澄清出口面 + 回流 resume** — 会话内联卡 / 群飞书交互卡双出口 + 答复统一回流续推 + 多轮（CLARIFY-04/05/06/07）(5/5 plans) (completed 2026-06-27)
- [x] **Phase 92: 插槽系统（后端）** — 端口 shape 语义 + Validator 形状校验 + `ai_plan_research` 澄清插槽 + 澄清卡节点（SLOT-01/02）— 3 plans
- [ ] **Phase 93: 插槽编辑器（前端）** — @vue-flow 形状磁吸 + 澄清节点附着子节点可视编组 + 下接发群（SLOT-03/04）
- [ ] **Phase 94: 入口统一** — 工作流/对话/MCP 三入口归一到 plan_orchestration + 废弃 ai_plan_generation + done 推群干净渲染（UNIFY-01~06）
- [ ] **Phase 95: 拆分完善** — `decompose` 升级为 LLM 跨仓业务线/模块/前后端拆分（DECOMP-01）

#### Phase Details

### Phase 90: 澄清能力层

**Goal**: 把「澄清」做成编排的一等能力——结构化数据模型 + LLM 多问题生成 + 入口无关的统一提问能力，为出口面与插槽铺底。
**Depends on**: Phase 89（v0.16.0 已交付的 plan_orchestration 底座）
**Requirements**: CLARIFY-01, CLARIFY-02, CLARIFY-03
**Success Criteria** (what must be TRUE):

  1. `Clarification` 可存储多个问题（单选/多选 + 选项 + 推荐项）与多答案，所有写入经单一入口（INV-6），并自带向后兼容迁移。
  2. 编排过程能基于需求 + 路由候选 + 召回上下文由 LLM 产出多问题结构化澄清（每题带选项 + 推荐 / 关键词加重），`call_source=plan_clarification` 上报请求/token/TTFT/上游错误码。
  3. 编排任意点（架构师融合 / 调研容器卡住）可经统一 `ask_clarification` 能力产出结构化澄清请求，入口无关、可携带 origin_repo。

**Plans**: 4 plans（3 waves）

- [x] 90-01-PLAN.md — 结构化数据模型：Clarification 容器扩展 + ClarificationQuestion 子表 + 迁移 0026 + barrel（Wave 1）
- [x] 90-02-PLAN.md — ClarificationService 扩展：create_round/answer_round + recommendation_adopted 定格 + ahas_pending + INV-6 子模型守护（Wave 2）
- [x] 90-03-PLAN.md — ClarifyAdapter 接 LLM 多题 + fail-soft 回退 + 三处 pending 判定升级（resume/e2e helper）（Wave 3）
- [x] 90-04-PLAN.md — 入口无关统一 ask_clarification helper（写 delivery、origin_repo、与 chat tool 同名防撞）（Wave 3）

### Phase 91: 澄清出口面 + 回流 resume

**Goal**: 澄清请求能在「AI 会话」与「工作流/群」两个出口面发出，用户作答能统一回流并续推编排，且支持多轮且不无限挂起。
**Depends on**: Phase 90
**Requirements**: CLARIFY-04, CLARIFY-05, CLARIFY-06, CLARIFY-07
**Success Criteria** (what must be TRUE):

  1. AI 会话中澄清请求内联渲染为单/多选提问卡（前端组件），用户作答经 endpoint 回流。
  2. 工作流/群场景澄清请求经飞书交互卡（单/多选 + ⭐推荐 + 其他）由机器人发到群（复用已建 `build_clarification_card`）。
  3. 回写结构化答案后经 `answer_clarification` → `adrive_plan_session_to_pause_or_terminal` 续推，工作流 + 会话同源（不造两套）。
  4. 答后引擎/Agent 重判：信息不足再发一轮、足够则继续编排出方案，且有防无限挂起的上界。

**Plans**: 5 plans（3 waves）

- [x] 91-01-PLAN.md — 共享回流 helper aanswer_round_and_resume + 多轮放开（移除 CR-01 + round_no 上界 6 + 带答案重判）（Wave 1，CLARIFY-06/07）✅
- [x] 91-02-PLAN.md — 工作流节点发卡 + WorkflowEventSubscription + build_clarification_card 携 clarification_id/新 action + WR-03 三处 pending 收口（Wave 1，CLARIFY-05/WR-03）✅
- [x] 91-03-PLAN.md — 飞书澄清回调 plan_clarify_（form_value→answers→answer_round→续推→approve_node）（Wave 2，CLARIFY-05/06）✅
- [x] 91-04-PLAN.md — 会话端专路由 endpoint 收 answers[] + owner gate + runtime 暴露 plan 结构化轮 + 续推（Wave 2，CLARIFY-04/06）✅
- [x] 91-05-PLAN.md — 前端 ClarificationCard 多题多选扩展 + 类型/api/store + i18n 守护（Wave 3，CLARIFY-04）✅

### Phase 92: 插槽系统（后端）

**Goal**: 端口具备「形状（shape）」语义并被后端校验，`ai_plan_research` 暴露澄清插槽端口 + 新增可编排的「澄清卡」节点。
**Depends on**: Phase 90, Phase 91
**Requirements**: SLOT-01, SLOT-02
**Success Criteria** (what must be TRUE):

  1. 节点定义可声明端口 shape（technical_plan / clarification_request / clarification_answer / feishu_message 等），`WorkflowGraphValidator` 保存即按 shape 兼容性校验连接合法性。
  2. `ai_plan_research` 暴露 `clarify`（clarification_request 凹槽）/ `resume`（clarification_answer 凸点）插槽端口。
  3. 新增「澄清卡」节点（入 clarification_request、出 clarification_answer + feishu_message）可被注册与编排。

**Plans**: 3 plans（3 waves）

- [x] 92-01-PLAN.md — NodePort.shape 能力契约字段 + KNOWN_PORT_SHAPES 常量 + get_schema 输出 + WorkflowGraphValidator 契约兼容校验（Wave 1，SLOT-01）
- [x] 92-02-PLAN.md — ai_plan_research 暴露 clarify/resume 插槽端口 + build_clarification_card action 前缀参数化（Wave 2，SLOT-02）
- [x] 92-03-PLAN.md — clarification_card 节点 + clarify_card_ 独立回调（answer_round 落库 + approve 本节点）+ fixture 重生成（Wave 3，SLOT-02）

### Phase 93: 插槽编辑器（前端）

**Goal**: 工作流编辑器支持形状磁吸拼接，澄清节点可视附着到方案节点并可下接发飞书群。
**Depends on**: Phase 92
**Requirements**: SLOT-03, SLOT-04
**Success Criteria** (what must be TRUE):

  1. @vue-flow 编辑器按 shape 兼容判定 `isValidConnection`，拖拽时兼容插槽高亮 + 磁吸吸附，不兼容形状不可连。
  2. 澄清节点作为方案节点的「附着子节点」可视编组（生命周期绑定的视觉表达）。
  3. 澄清节点可下接「发送飞书群聊」等吃 feishu_message 形状的节点。

**Plans**: 7 plans（4 waves）
**UI hint**: yes

- [x] 93-00-PLAN.md — 后端地基（BLOCKER 修复）：NodePortSerializer 补 shape 字段 + GET /api/node-types/ shape 暴露集成断言（Wave 1，SLOT-03）✅
- [ ] 93-01-PLAN.md — 契约判定地基：NodePort.shape? + portShapes 兼容纯函数 + useConnectionValidator 第 4 条 + i18n 全量键（Wave 2，依赖 93-00，SLOT-03）
- [ ] 93-02-PLAN.md — 磁吸支撑：useConnectionDragState 拖拽态 holder + usePortSnap 吸附几何（28px/zoom 换算/仅兼容）（Wave 3，SLOT-03）
- [x] 93-03-PLAN.md — SLOT-04 数据：store metadata.parentNodeId 持久化 + attach/detach + 删父级联删子 + transform parentNode/extent（top-level 与 data.metadata 同源）+ autoLayout 编组整体（Wave 1，SLOT-04）✅
- [ ] 93-04-PLAN.md — palette 收录 clarification_card + nodeVisuals 琥珀视觉 + node-sync 守护绿（Wave 1，SLOT-03/04）
- [ ] 93-05-PLAN.md — BaseWorkflowNode 端口方形/圆形 + shape 着色 + 拖拽兼容/禁止态 + IM 门控 + 附着徽标 + useImCapability（Wave 4，SLOT-03/04）
- [ ] 93-06-PLAN.md — 画布磁吸交互（connect-start/end + 吸附 + 不兼容 Toast）+ 附着编组渲染（.slot-attach-group/.slot-attach-connector）/删父级联确认/解除确认 + 人工验收（Wave 4，SLOT-03/04）

### Phase 94: 入口统一

**Goal**: 工作流 / 对话 / MCP 三入口的方案生成全部归一到 `plan_orchestration`，废弃旧 LangChain `ai_plan_generation`，done 出口用干净结构化 markdown 推送方案到群。
**Depends on**: Phase 90, Phase 91
**Requirements**: UNIFY-01, UNIFY-02, UNIFY-03, UNIFY-04, UNIFY-05, UNIFY-06
**Success Criteria** (what must be TRUE):

  1. `technical_plan_generation` 模板从 `ai_plan_generation` 切换到 `ai_plan_research`，既有已实例化工作流不破坏。
  2. 旧 `ai_plan_generation`（LangChain 单 agent）标记 deprecated + 迁移指引并从默认模板/新建路径移除，向后兼容不回退。
  3. MCP `create_feishu_technical_plan` delegate 到 plan_orchestration、`create_coding_plan` 产物口径收口，三入口产同一 canonical `MergedPlan`/`PlanVersion`。
  4. 对话方案生成的澄清挂起收敛为单一来源（消除 `ToolResult` marker vs `PlanSession.Clarification` 双挂起二义）。
  5. `ai_plan_research` 的 done 出口用干净结构化 markdown 推送方案到群（复用本轮渲染修复，不 dump LLM 原始文本）。

**Plans**: TBD

### Phase 95: 拆分完善

**Goal**: `decompose` 阶段从「按行切」升级为 LLM 跨仓拆分，提升路由/调研精度。
**Depends on**: Phase 90（沿用统一 LLM call_source/观测约定；功能上相对独立）
**Requirements**: DECOMP-01
**Success Criteria** (what must be TRUE):

  1. `decompose` 阶段由「按非空行切分」升级为 LLM 跨仓业务线/模块/前后端拆分。
  2. 新增 LLM 调用赋 `call_source` 并上报指标，失败 fail-soft 降级回退到现状按行切分。

**Plans**: TBD

#### Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 90. 澄清能力层 | 4/4 | Complete    | 2026-06-27 |
| 91. 澄清出口面 + 回流 resume | 5/5 | Complete    | 2026-06-27 |
| 92. 插槽系统（后端） | 3/3 | Complete    | 2026-06-27 |
| 93. 插槽编辑器（前端） | 2/7 | 🚧 In progress | - |
| 94. 入口统一 | 0/TBD | Not started | - |
| 95. 拆分完善 | 0/TBD | Not started | - |

<details>
<summary>✅ v0.16.0 项目工作区（飞书文档双向同步 + IDE 上下文闭环 + feature list 交付流水线）(Phases 82–89) — SHIPPED 2026-06-26 — 审计 tech_debt</summary>

- [x] Phase 82: 项目工作区实体 + 权限翻转 + 飞书文件夹 + 5 文件 (5/5 plans) — WS-01~04, DOC-01~06 — completed 2026-06-26
- [x] Phase 83: 飞书文档双向同步引擎 (6/6 plans) — SYNC-01~06 — completed 2026-06-26
- [x] Phase 84: 项目工作台前端 2.0 (5/5 plans) — WB-01~05 — completed 2026-06-26
- [x] Phase 85: 项目上下文可读 + 分支绑定 (4/4 plans) — CTX-01/02, BIND-01/02 — completed 2026-06-27
- [x] Phase 86: IDE 上下文闭环（hooks） (5/5 plans) — HOOK-01~04 — completed 2026-06-27
- [x] Phase 87: 看板拆分节点 + 群 + 流式卡片 (4/4 plans) — BOARD-01/02 — completed 2026-06-27
- [x] Phase 88: 智能业务关联仓库 (5/5 plans) — REPO-01/02 — completed 2026-06-27
- [x] Phase 89: 技术方案深化 + 建分支绑项目 (4/4 plans) — PLAN-01~04 — completed 2026-06-27

完整阶段详情见 [milestones/v0.16.0-ROADMAP.md](./milestones/v0.16.0-ROADMAP.md)；里程碑审计 tech_debt（37/37 需求、integration_ok；遗留真机/live-platform 验收 + 既有并发测试欠债）见 [milestones/v0.16.0-MILESTONE-AUDIT.md](./milestones/v0.16.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.15.0 项目（交付上下文聚合根）(Phases 76–81) — SHIPPED 2026-06-26 — 审计 passed</summary>

- [x] Phase 76: 命名腾挪（Project→Space 重构前置） (1/1 plans) — RENAME-01/02 — completed 2026-06-25
- [x] Phase 77: 项目聚合根 + 身份映射 + 成员协作 (1/1 plans) — PROJ-01~05, IDENT-01, MEMBER-01~03 — completed 2026-06-25
- [x] Phase 78: 飞书触发建项目 + 看板枚举 + 工作项组合 (1/1 plans) — FSPROJ-01~03, COMPOSE-01/02 — completed 2026-06-25
- [x] Phase 79: 工件/依赖项（可配置类型 + 实例 + RAG）+ 知识关联 (1/1 plans) — ARTIFACT-01~05, KLINK-01/02 — completed 2026-06-26
- [x] Phase 80: 项目记忆 + MR 实体 + 上下文召回接入 Web 会话 (1/1 plans) — MEM-01~04, RECALL-01~03, MR-01/02 — completed 2026-06-26
- [x] Phase 81: Cursor 回流 + 前端项目工作台 (1/1 plans) — CURSOR-01~03, UI-01~03 — completed 2026-06-26

完整阶段详情见 [milestones/v0.15.0-ROADMAP.md](./milestones/v0.15.0-ROADMAP.md)；里程碑审计 passed（38/38 需求、integration_ok）见 [milestones/v0.15.0-MILESTONE-AUDIT.md](./milestones/v0.15.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.14.0 可观测性与日志治理 (Phases 71–75) — SHIPPED 2026-06-24 — 审计 passed</summary>

- [x] Phase 71: 可观测性地基（用户上下文贯穿 + 系统日志治理） (5/5 plans) — CTX-01/02, LOG-01~08 — completed 2026-06-24
- [x] Phase 72: 调用数据采集（AI/LLM + 召回 + 请求入口） (4/4 plans) — RATE-01/02, RAG-01/02, SLA-02/03/04 — completed 2026-06-24
- [x] Phase 73: 快照·趋势·查询 API (3/3 plans) — SNAP-01~05, RATE-03, SLA-01, QUERY-01/02 — completed 2026-06-24
- [x] Phase 74: 告警引擎与通知（阈值 + 告警事件 + 邮件） (3/3 plans) — ALERT-01/02/03 — completed 2026-06-24
- [x] Phase 75: 运维大盘前端 + 规范固化 (5/5 plans) — UI-01~04, SPEC-01 — completed 2026-06-24

完整阶段详情见 [milestones/v0.14.0-ROADMAP.md](./milestones/v0.14.0-ROADMAP.md)；里程碑审计 passed（34/34 需求、integration_ok）见 [milestones/v0.14.0-MILESTONE-AUDIT.md](./milestones/v0.14.0-MILESTONE-AUDIT.md)。

</details>

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

**🚧 当前在建：v0.16.1 统一 AI 技术方案生成（图编排归一 + 插槽式澄清拼接 + 能力完善）（Phases 90–95，6 阶段 / 18 v1 需求 UNIFY/CLARIFY/SLOT/DECOMP）** — planning。patch 级优化/统一里程碑：4 套分散方案生成归一到 `plan_orchestration`、废弃 LangChain `ai_plan_generation`、完善澄清（多轮 resume）/拆分能力 + 插槽式编辑范式。下一步 `$gsd-plan-phase 90`（澄清能力层）。

里程碑 v0.1.0–v0.16.0（Phases 1–89）均已交付。**✅ v0.16.0 项目工作区（飞书文档双向同步 + IDE 上下文闭环 + feature list 交付流水线）（Phases 82–89，8 阶段 / 37 需求）已 shipped（2026-06-26，里程碑审计 tech_debt — 37/37 需求满足 / integration_ok，遗留真机/live-platform 验收 + 既有并发测试欠债）**，完整阶段详情见 [milestones/v0.16.0-ROADMAP.md](./milestones/v0.16.0-ROADMAP.md)、审计见 [milestones/v0.16.0-MILESTONE-AUDIT.md](./milestones/v0.16.0-MILESTONE-AUDIT.md)。

各历史里程碑详情归档在 `.planning/milestones/`，要点见 `MILESTONES.md`。

---
*Previous milestones archived in .planning/milestones/*
