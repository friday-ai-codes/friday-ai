# Requirements: Friday AI

**Defined:** 2026-06-27
**Core Value:** 把当前分散的多套「AI 技术方案生成」统一到唯一的图编排底座 `plan_orchestration`（工作流 / 对话 / MCP 三入口归一、废弃旧 LangChain 单 agent 路径），并完善该能力——LLM 拆分、结构化交互式澄清 + 多轮 resume 续推、方案推送渲染，并引入「插槽式（形状端口磁吸）」工作流编辑范式让澄清等子环节可拖拽拼接。本里程碑 v0.16.1 为**优化/统一现有能力**（非新功能），Phases 90+ 续号。

> 设计基线见本轮会话设计稿（统一底座能力对账 + 澄清能力/出口面模型 + 插槽式编辑器设计）。统一底座 `plan_orchestration` 已具备 resume / 多 claude code 容器并行调研 / 架构师融合汇总，下游 `human_approval`/`ai_coding` 已兼容 `MergedPlan`+wave。本里程碑核心是把「澄清」做成一等公民 + 插槽式编辑器 + 三入口归一。

## v1 Requirements

里程碑 v0.16.1。每条映射到一个 Phase（见 Traceability）。

### 入口归一（UNIFY）

- [ ] **UNIFY-01**: 工作流方案生成统一到 `ai_plan_research`（plan_orchestration）；`technical_plan_generation` 模板从 `ai_plan_generation` 切换到 `ai_plan_research`，既有已实例化工作流不破坏
- [ ] **UNIFY-02**: 旧 `ai_plan_generation`（LangChain 单 agent）标记 deprecated + 迁移指引，最终从默认模板/新建路径移除，保留向后兼容不回退
- [ ] **UNIFY-03**: MCP `create_feishu_technical_plan` 改为 delegate 到 `plan_orchestration`，产 canonical `MergedPlan`/`PlanVersion`（与工作流/对话同一产物口径）
- [ ] **UNIFY-04**: MCP `create_coding_plan` 产物口径收口（并入或对齐 plan_orchestration，不再走独立确定性 seam 产分叉结构）
- [ ] **UNIFY-05**: 对话方案生成的澄清挂起收敛为单一来源（消除 `ToolResult` marker vs `PlanSession.Clarification` 双挂起二义）
- [ ] **UNIFY-06**: `ai_plan_research` 的 `done` 出口接「推送方案到群」，用干净结构化 markdown 渲染（复用本轮渲染修复，不 dump LLM 原始文本）

### 澄清能力 + 出口面（CLARIFY）

- [ ] **CLARIFY-01**: 结构化澄清数据模型——`Clarification` 扩展支持多问题（单选/多选 + 选项 + 推荐项）+ 多答案的结构化存储（单一写入入口 INV-6）
- [ ] **CLARIFY-02**: LLM 结构化澄清问题生成——基于需求 + 路由候选 + 召回上下文产出多问题（关键词加重 / 每题选项 + 推荐），`call_source=plan_clarification`
- [ ] **CLARIFY-03**: 统一「提问能力」——编排过程任意点（架构师融合 / 某调研容器卡住）经一个 `ask_clarification` 能力产出结构化澄清请求，入口无关、可携带 origin_repo
- [ ] **CLARIFY-04**: 出口面·AI 会话——澄清请求在对话前端内联渲染为单/多选提问卡（前端组件），用户作答经 endpoint 回流
- [ ] **CLARIFY-05**: 出口面·工作流 / 群——澄清请求经飞书交互卡（单/多选 + ⭐推荐 + 其他）由机器人发到群（复用已建 `build_clarification_card`）
- [ ] **CLARIFY-06**: 答复回流统一——回调/endpoint 回写结构化答案 → `answer_clarification` → `adrive_plan_session_to_pause_or_terminal` 续推（工作流 + 会话同源，不造两套）
- [ ] **CLARIFY-07**: 多轮澄清——答后引擎/Agent 重判，信息仍不足再发一轮、足够则继续编排出方案；防无限挂起

### 插槽式编辑器（SLOT）

- [ ] **SLOT-01**: 端口「形状（shape）」语义——节点定义声明端口 shape（`technical_plan` / `clarification_request` / `clarification_answer` / `feishu_message` 等）；后端 `WorkflowGraphValidator` 按 shape 兼容性校验连接合法性（保存即校验）
- [ ] **SLOT-02**: `ai_plan_research` 暴露 `clarify`（`clarification_request` 凹槽）/ `resume`（`clarification_answer` 凸点）插槽端口；新增「澄清卡」节点（入 `clarification_request`、出 `clarification_answer` + `feishu_message`）
- [ ] **SLOT-03**: 前端编辑器（@vue-flow）形状磁吸——`isValidConnection` 按 shape 兼容判定，拖拽时兼容插槽高亮 + 磁吸吸附，不兼容形状不可连
- [ ] **SLOT-04**: 澄清节点作为方案节点的「附着子节点」可视编组（生命周期绑定的视觉表达），并可下接「发送飞书群聊」等吃 `feishu_message` 形状的节点

### 拆分完善（DECOMP）

- [ ] **DECOMP-01**: `decompose` 阶段从「按非空行切分」升级为 LLM 跨仓业务线/模块/前后端拆分，提升路由/调研精度（`call_source` 赋值、fail-soft 降级回退现状）

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### 流式方案卡片（STREAM）

- **STREAM-01**: 方案文本边生成边流式刷新到群/会话（cardkit/v1 打字机效果）——锦上添花，非统一/优化核心
- **STREAM-02**: 流式与交互互斥的状态切换（流式期关交互、交互期关流式）封装

### 插槽推广（SLOTX）

- **SLOTX-01**: 形状插槽系统推广到更多节点类型（不止澄清）——通用「带槽节点 + 适配拼图」生态

## Out of Scope

| Feature | Reason |
|---------|--------|
| 把 `plan_orchestration` 重写为 langgraph StateGraph | 已确认能力等价（自研状态机已具备编排/澄清/汇总/resume），不为「形式上是 langgraph」做大重写；收益仅统一 checkpoint/可视化，留后续评估 |
| 用 langgraph 替换自研工作流 DAG 引擎 | 工作流是用户可视编辑 + DB 持久化的宏观业务编排，与 agent 微观推理编排是两层，不替换 |
| 飞书网页版渲染交互表单卡片 | 平台限制：2.0 表单组件仅飞书 App 渲染，网页版显示升级占位；交互澄清卡定位飞书 App / 会话前端 |
| 编码中全自动 replan | 沿用既有「抛 question 给人」HITL 过渡，全自动留 backlog（v0.8 已定） |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| CLARIFY-01 | TBD | Pending |
| CLARIFY-02 | TBD | Pending |
| CLARIFY-03 | TBD | Pending |
| CLARIFY-04 | TBD | Pending |
| CLARIFY-05 | TBD | Pending |
| CLARIFY-06 | TBD | Pending |
| CLARIFY-07 | TBD | Pending |
| SLOT-01 | TBD | Pending |
| SLOT-02 | TBD | Pending |
| SLOT-03 | TBD | Pending |
| SLOT-04 | TBD | Pending |
| UNIFY-01 | TBD | Pending |
| UNIFY-02 | TBD | Pending |
| UNIFY-03 | TBD | Pending |
| UNIFY-04 | TBD | Pending |
| UNIFY-05 | TBD | Pending |
| UNIFY-06 | TBD | Pending |
| DECOMP-01 | TBD | Pending |

**Coverage:**
- v1 requirements: 18 total
- Mapped to phases: 0（待 roadmapper 填充）
- Unmapped: 18 ⚠️（roadmap 创建后归零）

---
*Requirements defined: 2026-06-27*
*Last updated: 2026-06-27 after start milestone v0.16.1 统一 AI 技术方案生成*
