# 技术方案：AI 协作工作流 —— 信号 / 插槽 / 生命周期模型

> **用途**：本文件是一份**自包含的设计 + 实施手册**。新开会话时 `@` 引用它即可带上完整上下文，
> 无需回看原始对话。目标是把当前「线性管道式」工作流编辑器，演进为「**带人监督、围绕演进中
> 交付物、由 AI 反复收敛**」的协作工作流，借鉴缺氧（ONI）信号系统 + UE 蓝图 + 反思 Dify/n8n 的不足。
>
> **语言约定**：正文中文；代码标识 / 文件路径 / 端口名保留英文。
> **状态**：设计已与产品负责人对齐（2026-06-28），待分阶段实施。

---

## 0. 一句话定义

> 这套系统**不是数据管道，而是一台「协作收敛引擎」**：宏观图把一份**交付物**（技术方案 / PR）
> 路由过若干阶段；每个 AI 阶段是一个**有界收敛回路**（agent 提议 → 人/agent 澄清确认 → agent 修订）；
> 横切能力（澄清 / 通知 / 文档 / 审批）作为**类型化插槽 / 信号反应器**挂在节点的**生命周期信号**上；
> 产出是一份**带版本、人愿意签字**的交付物。

它要解决的真问题：**让一个不可靠的 agent，在人的监督下，通过「问—答—改」的有界往返，收敛出可信交付物。**
传统工作流把「往返 / 不确定 / 可监督」当边角料，而这里它们是主干。

### 0.1 完整工作流系统的定义（Friday 版本）

Friday 要做的不是「能拖很多节点的自动化工具」，而是一个面向 AI 交付的 **workflow OS**：

> 以 `WorkItem` 为脊柱，以版本化 artifact 为事实源，以状态机驱动 AI 收敛，以事件流解释过程，
> 以 human gate 控制风险，以 reaction 执行横切副作用的交付编排系统。

完整性不等于把所有能力塞进一张 DAG。完整性 = 下列能力都有清晰归属：

| 能力 | 归属层 | 解决的问题 |
|---|---|---|
| 主交付路径 | Delivery Graph | 需求如何从「同步」走到「PR / 回写」 |
| 演进对象 | Artifact Spine | 哪个版本的方案 / PR / 文档才是事实源 |
| AI 反复收敛 | AI Process Runtime | AI 不可靠时如何问、答、改、验证、回退 |
| 人类介入 | Human Task | 谁该确认、审批、接管、回答，超时怎么办 |
| 横切副作用 | Signal / Reaction | 通知、建文档、回写字段、告警何时触发 |
| 恢复与审计 | Runtime Guarantees | 重启、重试、幂等、补偿、可观察性 |

因此，目标不是替代 n8n/Dify 做通用集成平台，而是把「需求 → 可信方案 → 多仓代码 → PR」
这条 Friday 核心链路做成可配置、可恢复、可监督的工作流系统。

---

## 1. 第一性原理：工作流的最小元素

任何工作流剥到底只有四样：**被加工物（artifact）/ 加工者（actor）/ 流转规则（control）/ 触达（signal）**。
各范式的差别 = 对这四样的不同假设：

| 范式 | 加工者 | 流转 | artifact | 触达 |
|---|---|---|---|---|
| 传统 / Airflow / BPMN | 确定性函数 | 静态 DAG 一次向前 | 透明流过（无版本） | 完成即下一步 |
| n8n / Dify | 确定性集成节点 | 近线性、弱循环 | 数据载荷流过即弃 | 节点串节点 |
| UE 蓝图 | 函数 + latent（异步/耗时）节点 | **执行针 vs 数据针分离** | 运行时态 | 事件 + 强类型 pin |
| **缺氧信号系统** | **持续反应的设备** | **无「下一步」——靠信号状态反应** | 无 | **信号=可见的持续状态；自动化层与物理层两层分离** |
| **本系统（目标）** | **AI/人/确定性 三类，AI 是有态进程** | **交付 DAG + 收敛回路 + 信号订阅 三层** | **PlanVersion 一等、带版本** | **节点生命周期信号广播** |

**Dify/n8n「差的那点东西」**：用「无状态管道」思维解「有状态协商」问题——被迫把澄清/审批/通知
塞成线性管道上的节点，越塞越别扭，因为它们本质是**横切的、对状态做反应的能力**，不是交付主线工序。

**缺氧的两点启示**（必须吸收）：
1. **两层分离**：物理建造 与 自动化信号 是两张图，互不污染。
2. **信号是状态不是「下一步」**：设备广播自己的状态，谁关心谁订阅 + 反应，行为从状态涌现。

**UE 蓝图启示**：强类型 pin（=插槽）、执行流/数据流分离、**latent 节点（会等的节点 = 正在等澄清的 AI 节点）**。

---

## 2. 目标模型：五个一等公民

### 2.1 三种关系，绝不混成一根连线
| 关系 | 视觉 | 含义 | 例 |
|---|---|---|---|
| **交付流 delivery flow** | 实线（现有 gradient 边） | 宏观 DAG，artifact 往前推进 | 需求→方案→审批→编码→PR |
| **信号订阅 signal subscription** | 虚线 / 异色（**新增层**） | 节点状态信号被谁订阅反应 | 「通知」订阅方案节点的 `done`/`failed` |
| **能力插槽 capability slot** | 卡内嵌缺口（已建雏形） | 节点**内部不确定性**的补全位 | 澄清、审批挂在节点内部 |

### 2.2 节点 = 有生命周期的「工序」，状态可见（ONI 信号态 + 蓝图 latent）
AI 节点是**进程不是函数**，有态机：
`idle → running → waiting_clarification ⇄ revising → produced → (gate: waiting_approval) → done | failed`
- 卡片**显示当前态 + 收敛轮次**（如「修订中 · 第 2/6 轮」）。
- **当前态本身就是对外广播的信号**（供信号订阅层消费）。
- 人能「看见」agent 的反复 → 才谈得上监督。

### 2.3 收敛回路内建（非手画反馈边）
每个 AI 节点内禀属性：`max_rounds`（默认 6）、`confirm_by`（human/auto）、澄清插槽=回路的提问通道。
`问→答→改→重判` 是节点内部循环，画布上**不画回头线**。

### 2.4 插槽升级为「信号反应器」（缺氧精髓 —— 最关键的一跳）
每个可插入插件声明它**在宿主的哪个信号上触发**：
| 插件 | 触发信号 | 形态 |
|---|---|---|
| 澄清卡 clarification_card | `needs_clarification` | 槽（内部回路通道） |
| 飞书通知 notify_feishu(_im) | `done` / `failed`（**用户勾选订阅哪个**） | 信号反应器 |
| 飞书文档 feishu_doc_create | `produced`（产出了 technical_plan 等） | 信号反应器 |
| 审批 human_approval | 卡在 `produced → 下一步` 之间 | **闸门 gate**（非订阅） |

这样通知/文档/审批从「线性管道上的尴尬节点」变成「挂在信号上的反应器」——和缺氧同一心智。

### 2.5 artifact（PlanVersion）作为一等对象
画布上可见、被节点读写、带版本的中心物（像 git/build 而非水管）。交付主线 = 对这一演进物的若干次操作。

### 2.6 六层架构：完整但不混层

| 层 | 一等对象 | 说明 |
|---|---|---|
| **Artifact Spine** | `WorkItem` / `PlanVersion` / `RepoResearchTask` / `RepoCodingTask` / PR / 文档 | 事实源。工作流推进的是这些对象的状态与版本，不是临时 JSON 水流。 |
| **Delivery Graph** | `Workflow` / `WorkflowNode` / delivery edge | 用户画的主交付路径，保持可读、宏观、少分叉。 |
| **AI Process Runtime** | `PlanSession` / `RepoResearchTask` / `PartialPlan` / `NodeSubStep` | AI 节点内部的可恢复状态机，处理澄清、调研、融合、验证、回退。 |
| **Human Task** | `Clarification` / approval / takeover task | 人类待办层，承载谁来答、谁来批、超时/转派/跳过规则。 |
| **Signal / Reaction** | lifecycle signal + reaction instance | 通知、建文档、写回飞书、告警等横切行为；默认不阻塞主链路，除非声明为 gate。 |
| **Observability / Audit** | `PlanSessionEvent` / workflow hook / `RequestMetric` / audit event | 解释过程、排障、成本归因、审计追责。 |

这六层都要有，但 UI 不应把六层同时摊平。默认看 Delivery Graph；需要排障时展开信号层；
需要理解交付物演进时看 artifact timeline。

### 2.7 Signal 的工程定义：投影，不新造第三套事件

本仓当前已有两类事件底座：

- **Workflow lifecycle hook / WS**：`execution_started`、`node_completed`、`node_failed`、`node_waiting_event` 等，
  适合表达「工作流执行态」。
- **PlanSessionEvent taxonomy**：`repo.routing`、`repo.research.*`、`clarification.*`、`plan.merge.*`、
  `plan.validation.failed`、`coding.wave.*` 等，适合表达「AI 编排 trace / progress」。

目标模型里的 signal **不是第三套事件表**。它是对上述事实源的稳定投影：

```text
raw event / state transition
  → normalized lifecycle signal
  → reaction matcher
  → idempotent reaction execution
```

最小 signal 形状：

```text
Signal {
  name: "node.done" | "node.failed" | "artifact.produced" | "clarification.asked" | ...
  scope: workflow_execution | node_execution | plan_session | artifact
  subject_id: UUID/string
  source_event: workflow_hook | plan_session_event | artifact_transition
  payload: safe JSON
  occurred_at: datetime
}
```

最小 reaction 形状：

```text
Reaction {
  id
  owner_node_id / host_node_id
  signal_name
  target_node_type        # notify_feishu / feishu_doc_create / writeback / alert ...
  blocking_mode           # non_blocking | gate | compensation
  idempotency_key         # execution_id + host_node_id + signal_name + reaction_id
  retry_policy
  last_status / last_error
}
```

核心约束：

- `notification` / `document` / `writeback` 默认是 **non_blocking reaction**，失败可见、可重试，但不应误杀主交付。
- `human_approval` 是 **gate**，它改变主交付是否继续，不能当普通订阅。
- 所有 reaction 必须幂等；服务重启后能从 DB 重放「未完成 reaction」，不能只靠前端边。
- signal payload 走脱敏与受控字段；不要把 LLM 原始输出、飞书原始 payload、异常全文直接作为 reaction 输入。

---

## 3. 现状盘点（已建成 / 可复用 / 待改）

### 3.1 已建成（v0.16.1 里程碑，已 shipped）
- **后端能力契约端口**：`server/workflows/nodes/base.py` `NodePort.shape` 字段（与 `port_type` 正交，空=通配）；
  `server/workflows/nodes/shapes.py` `KNOWN_PORT_SHAPES`（clarification_request/clarification_answer/feishu_message/
  technical_plan/coding_assignment/feishu_document/approval_result）；
  `server/workflows/validation/graph_validator.py` `_validate_port_shapes`（保存即校验，双端非空且不等才报 `incompatible_port_shape`）。
- `ai_plan_research` 已暴露 `clarify`(out, clarification_request)/`resume`(in, clarification_answer) 端口（execute 未驱动）。
- **澄清卡节点** `clarification_card`（in clarification_request、out clarification_answer + feishu_message）+ 独立回调
  `server/feishu/callbacks/clarify_card_callback.py`。
- **结构化澄清数据模型**：`server/delivery/models/clarification.py`（Clarification 轮次容器 + ClarificationQuestion 子表，
  多问题/单多选/选项/推荐/按题答案 + `recommendation_adopted` 采纳信号）；唯一写入入口
  `server/delivery/services/clarification_service.py`（`create_round`/`answer_round`/`ahas_pending`，INV-6）。
- **澄清出口面 + 回流**：会话多题多选卡 `web/src/components/chat/ClarificationCard.vue` + 专路由
  `PlanClarificationAnswerView`（`server/chat/views.py`）+ 飞书群卡（`server/feishu/cards/chat_question_card.py:build_clarification_card`）+
  同源续推 helper `server/services/plan_orchestration/answer_resume.py:aanswer_round_and_resume`；多轮上界 `_MAX_CLARIFY_ROUNDS=6`。
- **三入口归一**：工作流 / 对话 / MCP 方案生成统一到 `server/services/plan_orchestration/`；旧 `ai_plan_generation` 标 deprecated
  + 节点库移除（向后兼容既有实例）。
- **decompose** 升级为 LLM 跨仓拆分（`server/services/plan_orchestration/decompose_segments.py`，fail-soft 回退按行切）。

### 3.2 拼积木插槽（本轮新增，已提交）—— 正确方向的第一步，但只到「类型匹配拼图」，未到「信号反应器」
- **分类配置（单一来源）**：`web/src/components/workflow/editor/slotTaxonomy.ts`
  - `SlotCapability = 'clarification' | 'notification' | 'document'`
  - `NODE_PROVIDES`：插件 → 提供能力（clarification_card→clarification；notify_feishu(_im)→notification；feishu_doc_create→document）
  - `NODE_SLOTS`：宿主 → 暴露能力槽（ai_plan_research=澄清+文档+通知；ai_coding_dispatcher/ai_coding=文档+通知；
    human_approval=文档+通知；create_pr/merge_pr/create_branch/mcp_deploy/create_group_chat/create_work_item_chat/board_split=通知）
  - `resolveSlotEdges`：拖入后自动接线（澄清=双向 clarify↔resume；通知/文档=宿主主成功出口→插件 default）
- **拖拽落入**：`web/src/components/workflow/editor/composables/usePaletteDragState.ts`（拖拽能力态）+
  `NodePaletteItem.vue`（dragstart/dragend 记录能力）+ `BaseWorkflowNode.vue`（卡内能力槽渲染 + drop 落入 + 类型匹配高亮/降亮）。
- **附着插件作为卡内 chip 不在画布单独渲染**：`web/src/components/workflow/editor/composables/useWorkflowTransform.ts`
  过滤带 `metadata.parentNodeId` 的子节点 + 其内部边；store 仍保留供后端执行（store 为 SSOT，`toVueFlowNodes` 单向渲染）。
- typed 端口（clarify/resume 等）改为内部接线、不渲染为可见 handle；plain 端口（default/error）保持。
- store 父子 API：`attachChild`/`detachChild`/`getChildNodes`/`removeNode`（级联删子）。

### 3.3 本质差距（现状 vs 目标）
1. 插槽只做「类型匹配拼图」，**未做「信号反应器」**——通知现在恒接 `default`，不能选「成功/失败」信号。
2. 节点**无可见生命周期态**——看不到 agent 的反复（running/waiting/revising）。
3. **信号订阅层不存在**——交付流与横切反应混在一根实线/或挤进插槽。
4. 收敛回路在后端有（`_MAX_CLARIFY_ROUNDS`），但**前端不可视**。
5. artifact（PlanVersion）**非画布一等对象**。
6. **reaction 运行时不存在**——还没有幂等键、重试、失败可见性、重启恢复、阻塞/非阻塞语义。
7. **Human Task 层不完整**——澄清和审批已有点状实现，但缺统一待办、转派、超时、跳过、接管模型。
8. **事件体系边界未固化**——workflow hook 与 `PlanSessionEvent` 都存在，signal 必须是投影层，不能再造第三套事实源。
9. **交付物链条不止 PlanVersion**——完整链路还需把 `WorkItem`、`PartialPlan`、`RepoCodingTask`、PR/MR、文档、writeback 纳入 timeline。

### 3.4 必须沿用的现有事实源

实施时以这些现状作为硬边界：

| 事实源 | 用途 | 约束 |
|---|---|---|
| `WorkflowExecution` / `NodeExecution` | 工作流执行与节点调度态 | 只表达调度态，不塞过多 AI 内部阶段。 |
| `PlanSession` | 方案编排状态机 | AI 方案收敛的主状态源；可从任意阶段恢复。 |
| `PlanSessionEvent` + `event_taxonomy` | progress / trace 事件 | 对外 adapter、UI trace、reaction signal 投影都应复用。 |
| `TechnicalPlan` / `PlanVersion` | canonical 技术方案 | 方案内容事实源；版本化、hash 去重、不可旁路写表。 |
| `Clarification` / `ClarificationQuestion` | HITL 澄清 | 人类回答唯一写入入口；多题、多选、采纳信号已具备。 |
| `WorkflowEventSubscription` | 等外部事件唤醒 | 这是「等待外部事件」机制，不等同于 reaction 订阅。不要混名。 |

---

## 4. 分阶段实施路线（每阶段可独立交付）

> 推荐顺序：先补运行时合同 → 再让 AI 生命周期可见 → 再做 reaction → 最后双层视图 / artifact 轨。
> 起步建议优先级：**Phase S0 → S3 → S2 → S1 → S4 → S5**。
> S1 扩槽很快，但不是架构核心；若先做 S2 而没有 S0，容易把 signal 做成「换皮边」。
> 也可按用户当时选择调整。

### Phase S0 — Workflow Runtime Contract（先钉死语义）
**目标**：把「完整工作流系统」的运行时合同写清楚并落最小后端骨架，避免 UI 先行后返工。
- 文档：补一份 `WORKFLOW-RUNTIME-SPEC.md`（或把本文件拆出 §runtime），定义：
  - 节点类型：`deterministic` / `ai_process` / `human_task` / `external_wait` / `reaction` / `gate`。
  - 边类型：`delivery` / `data` / `signal_subscription` / `artifact_dependency`。
  - signal 来源：workflow hook、`PlanSessionEvent`、artifact transition 的投影规则。
  - reaction 语义：幂等键、阻塞模式、重试、失败可见、恢复扫描。
  - artifact 关系：`WorkItem → PlanVersion → RepoCodingTask → PR/MR → writeback/document`。
- 后端最小骨架：
  - `WorkflowSignal` 不一定需要新表；优先做纯函数投影 + reaction 表。
  - 新增 `WorkflowReaction` / `ReactionExecution`（命名可议）承载配置与执行状态。
  - 事件消费必须 best-effort，默认不阻塞主 workflow；gate 例外。
- 前端最小骨架：
  - 数据模型支持 edge/reaction metadata，但 UI 仍可先只展示 chip。
- 验收：
  - 能从一次 `node_completed` 或 `plan.merge.completed` 事件投影出 normalized signal。
  - 同一 signal 重放不会重复发通知（idempotency test）。
  - 反应失败有状态可查，主流程默认不失败。

### Phase S1 — 扩澄清能力到更多 AI 节点（最快见效）
**目标**：让带不确定性的 AI 节点（如 `ai_coding_dispatcher`）也能用澄清能力槽。
- 后端：给 `ai_coding_dispatcher`（必要时 `ai_coding`）补 `clarify`(out, clarification_request)/`resume`(in, clarification_answer)
  端口（参照 `server/workflows/nodes/ai/plan_research.py` 端口声明）；接通其澄清挂起→`build_clarification_card`→
  `clarify_card_callback`/`aanswer_round_and_resume` 续推（复用既有，不造两套）。
- 前端：`slotTaxonomy.ts` `NODE_SLOTS.ai_coding_dispatcher` 加 `'clarification'`（一行）。
- 验收：编码指派节点出现澄清槽，拖入澄清卡可附着接线 + 续推；既有零回归。

### Phase S2 — 插槽升级为「信号反应器」（缺氧心智落地，最关键一跳）
**目标**：通知/文档插件可声明**订阅宿主哪个信号**（成功/失败/产出），而非恒接 default。
- 配置：`slotTaxonomy.ts` 扩展能力定义，增加「可订阅信号集合」+ 每个插件实例存储「已选信号」
  （存 `child.metadata.subscribeSignals: ['node.done'|'node.failed'|'artifact.produced']`）。
- 接线：前端仍可保留 store 内部边作兼容/可视化，但运行时语义应以 reaction 配置为准，而非仅靠
  `default/error` 端口触发。`resolveSlotEdges` 最多是 UI/迁移辅助，不是 signal 的事实源。
- 后端：保存 workflow 时把附着插件转换为 reaction 配置；执行时由 signal 投影触发 reaction。
- 前端：已填 chip 上提供「订阅信号」切换（成功/失败/两者）；空槽提示标注「（默认订阅完成）」。
- 后端契约：确认哪些 reaction 是 non-blocking，哪些是 gate；失败记录可见并可重试。
- 验收：把「飞书通知」拖入通知槽，可勾选「失败时通知」；同一失败 signal 重放不重复通知；
  通知发送失败不把主 workflow 标 failed。

### Phase S3 — 节点生命周期态 + 收敛轮次可视（体现「AI 反复收敛」本质）
**目标**：卡片显示 `running / waiting_clarification / revising / produced / waiting_approval / done / failed` + 轮次。
- 后端：`NodeExecution` / `PlanSession` 状态已有（`server/delivery/models/plan_session.py` PlanSessionStatus；
  `server/workflows/...` NodeExecution）；经既有 WS 实时通道（`server/workflows/consumers.py`）把节点运行态 + 澄清轮次推给前端。
- 语义：不要把所有 AI 子状态都塞进 `NodeExecutionStatus`。推荐做 projection：
  - `NodeExecution.status=running` + `PlanSession.status=clarifying` → UI 显示 `waiting_clarification`。
  - `PlanSessionEvent(plan.validation.failed)` → UI 显示「校验失败，回到澄清/调研」。
  - `Clarification.round_no` → UI 显示轮次。
- 前端：`BaseWorkflowNode.vue` 增「生命周期态徽章 + 轮次」（运行时态，复用既有执行监控 store / WS）；
  态色板与语义色一致（running 蓝 / waiting 琥珀 / revising 紫 / done 绿 / failed 红）。
- 验收：跑一次方案研究，卡片实时显示「等澄清 → 修订中 第 N 轮 → 已产出」。

### Phase S4 — 画布双层视图（缺氧式两张图叠加）
**目标**：实线交付流 + 虚线信号订阅，分色分层，可切换/叠加显示。
- 前端：`WorkflowCanvas.vue` 增「信号层」开关；信号订阅边用虚线 + 能力色渲染（区别于交付实线）；
  能力插件 chip 上引出到通知/文档目标的「信号线」可视。
- 数据：信号订阅关系以 reaction metadata 为准；store 内部边可作为兼容和布局辅助，渲染时按
  `metadata.subscribeSignals` / reaction 配置分类。
- 验收：可一键切换「只看交付流 / 叠加信号层」，两层不互相干扰。

### Phase S5 —（更远）artifact 版本轨
**目标**：交付物作为画布/详情页可见的中心对象，交付主线呈现为「对一组演进物的操作序列」。
- 轨道不只 `PlanVersion`，至少包含：
  - `WorkItem`：需求/缺陷身份、状态、评论、字段镜像。
  - `PlanVersion`：方案版本、hash、supersedes、审批态。
  - `RepoResearchTask` / `PartialPlan`：每仓调研状态与 stale/invalidation。
  - `RepoCodingTask`：wave、depends_on、produced_artifacts、运行结果。
  - PR/MR：分支、target、状态、回写结果。
  - 文档/writeback：飞书文档、群消息、字段回填。
- UI：可在 workflow execution detail 上新增 artifact timeline，而不是把所有 artifact 节点都塞进画布。
- 验收：用户能回答三个问题：
  1. 当前交付物最新版本是什么？
  2. 为什么变成这个版本（由哪些事件/人/agent 推动）？
  3. 哪些下游产物引用了这个版本？

### Phase S6 — Human Task Center（完整工作流系统必备）
**目标**：把澄清、审批、接管、跳过、重试变成统一人类待办，而不是散落在节点配置和卡片回调里。
- 模型：`HumanTask`（或复用现有模型加统一 projection），字段包含 `type`、`assignee`、`scope`、
  `due_at`、`status`、`resolution`、`source_signal`、`artifact_ref`。
- 类型：
  - clarification answer
  - plan approval
  - risk acknowledgement
  - takeover / manual resume
  - failed reaction retry/ignore
- UI：项目工作台/工作流执行页都能看到「我需要处理什么」。
- 语义：human task 可以是 gate，也可以是 non-blocking decision；必须明确。

---

## 5. 关键决策（已定）

- **三种关系分离**：交付流（实线 DAG）/ 信号订阅（虚线层）/ 能力插槽（卡内嵌）——不再「什么都连一根线」。
- **节点是有态进程**，态即广播信号；收敛回路是节点内禀属性（max_rounds=6），不画反馈边。
- **插槽 = 类型化 reaction 配置入口**：按能力类型匹配（非钉死单节点）；插件声明订阅哪个 signal。
- **附着插件 = 卡内 chip**（不在画布单独渲染），但仍是真实 store 节点 + 内部边，供后端执行（store SSOT，transform 过滤渲染）。
- **不造两套**：澄清续推统一走 `aanswer_round_and_resume` + `plan_orchestration`；新增 AI 澄清节点复用既有发卡/回调/续推。
- **向后兼容不回退**：deprecated 节点保留注册可运行；新端口空契约通配，既有工作流零回归。
- **taxonomy 单一来源**：哪个节点带哪些槽、能力定义，全在 `web/src/components/workflow/editor/slotTaxonomy.ts`，一处可调。
- **signal 不做第三套事实源**：从 workflow hook / `PlanSessionEvent` / artifact transition 投影，reaction 消费投影后的 signal。
- **主 DAG 不承载横切副作用**：通知/文档/writeback/告警默认 reaction 化；只有会改变交付是否继续的能力才进入 gate。
- **artifact 优先于 transient output**：节点 output 可供兼容和模板引用，但事实源应回落到 `WorkItem` / `PlanVersion` / task / PR 等模型。
- **Human Task 是一等层**：澄清、审批、接管、跳过、风险确认必须能进入统一待办/权限/超时模型。

---

## 5.5 完整工作流的验收标准

实现到位后，用户应该能完成并理解一条真实链路：

```text
飞书需求触发
 → WorkItem upsert
 → AI 方案编排（路由 / 召回 / 澄清 / 多仓调研 / 融合）
 → PlanVersion vN 产出
 → 人审批 / 风险确认
 → 多仓 wave 编码
 → PR/MR 创建
 → 飞书文档 / 群通知 / 字段回写
```

必须能回答：

1. **当前走到哪一步？**
   Delivery Graph 上能看到宏观阶段，节点态能区分 running / waiting / failed / done。
2. **AI 为什么卡住或改了方案？**
   `PlanSessionEvent` / clarification / validation failure 可解释，而不是只显示“节点失败”。
3. **当前最新交付物是什么？**
   artifact timeline 能看到 `PlanVersion`、coding tasks、PR/MR、文档/writeback。
4. **现在需要谁做什么？**
   Human Task Center 能显示待答澄清、待审批、可接管项、失败 reaction 处理。
5. **副作用有没有执行？失败怎么办？**
   reaction 状态可见、可重试、幂等，不会偷偷重复通知或误杀主流程。
6. **系统重启后能否继续？**
   主执行、AI 编排、human wait、reaction retry 都能从 DB 状态恢复。
7. **对外暴露是否复用同一事件词表？**
   OpenAI/Anthropic/飞书卡片 progress 只做 adapter，不另建事件语义。

非目标：

- 不追求成为任意 SaaS 自动化平台。
- 不把所有内部事件都暴露给用户配置；普通用户只看到「成功/失败/产出/需要我处理」这类稳定语义。
- 不让用户手画 AI 内部循环；复杂度留在可恢复状态机里。

---

## 6. 约束与注意事项（实施前必读）

- **项目强制规范**（见 `AGENTS.md` / `.cursor/rules/observability-logging.mdc`）：
  - 新增 LLM 调用赋 `call_source`（枚举见 `server/agents/call_source.py` + LOGGING-SPEC §4.1），上报请求/token/TTFT/上游错误码。
  - 结构化日志 started/completed/failed + `duration_ms`，设 `category`(caller/sampling) + `component`；观测 best-effort 不反噬业务。
  - INV-6 单一写入；async ORM 走 `sync_to_async`，禁裸 lazy-FK；飞书 payload/上游响应/异常文本脱敏（`redact_secrets_in_text`）。
  - i18n 默认中文。
- **工作树有大量无关 WIP**（chat/initiatives/`.planning/project-war-room/`/project-galaxy/`components.d.ts` 等，约 40+ 文件未提交）：
  **实施时绝不 `git stash`、绝不 `git add -A/.`，只 `git add <显式路径>`**；存在 `codex-fastapi-migration` stash 勿动。
- **i18n 提交坑**：`web/src/locales/zh-CN.json` 同时含他人 WIP，**不可整文件提交**；新增键要么内联在配置（如 slotTaxonomy 用内联中文），
  要么用 `git add -p` 仅提交自己的 hunk。本轮能力槽文案已内联在 `slotTaxonomy.ts` 规避此坑。
- **测试**：前端 `cd web && pnpm vitest run <path>` + `pnpm vue-tsc --noEmit`；后端 `cd server && uv run pytest <path>` + `ruff` + `mypy`。
  fixture 守护：新增/改端口或节点需重跑 `pnpm -C web gen:node-fixture`，保 `node-sync.test.ts` 绿。
- **Vue Flow 注意**：节点类型需在 `web/src/components/workflow/editor/nodes/nodeVisuals.ts` 注册（`allNodeTypeKeys`），
  否则 Vue Flow 报 `Node type is missing` 并回退默认节点（不渲染插槽）——见 `nodes/index.ts` 的 Proxy `has` trap 兜底。
- **GSD 工作流**：本仓用 GSD（`.planning/`）。建议把本方案转为新里程碑：`$gsd-new-milestone` → 按 Phase S0–S6 排 roadmap →
  逐 phase `discuss → plan → execute → review → verify`。新的推荐 milestone 应按 **S0 → S3 → S2 → S1 → S4 → S5/S6**
  排序，避免 UI 先行导致 signal 语义返工。

### 6.1 实施红线

- 不新增第三套「WorkflowSignalEvent」事实表，除非先证明 workflow hook + `PlanSessionEvent` + artifact transition
  无法投影满足需求。
- 不让 reaction 只靠前端隐藏边触发；隐藏边可作为兼容表达，但运行时必须有幂等 reaction 记录。
- 不把 `NodeExecutionStatus` 扩成庞大的 AI 内部状态枚举；AI 内部状态从 `PlanSession` / 子任务 / trace 投影。
- 不把通知/文档失败默认升级成 workflow failed；除非该 reaction 明确声明为 gate/blocking。
- 不把 artifact timeline 做成画布上大量“伪节点”；优先在 execution detail / project workbench 呈现。
- 不绕过 `TechnicalPlanService`、`ClarificationService`、`PlanSessionService` 等单一写入入口。

---

## 7. 新会话起步指引

1. 先读本文件 + `AGENTS.md` + `web/src/components/workflow/editor/slotTaxonomy.ts` + `BaseWorkflowNode.vue` +
   `server/workflows/nodes/base.py`（NodePort）+ `graph_validator.py`（_validate_port_shapes）。
2. 若要做完整工作流系统，先选 **S0**；若只做可见效果，选 **S3**；若只扩能力面，才选 **S1**。
3. 走 GSD：`$gsd-plan-phase`（或直接实现），严守第 6 节约束。
4. 每步：实现 → 前后端测试 → vue-tsc/ruff/mypy → 只提交显式路径。

---

## 附：四个参照系一句话对照（帮助保持设计定力）

- **缺氧信号系统**：两层分离 + 信号是可见状态 + 行为从状态涌现 → **我们要的「信号订阅层」+「节点态可见」**。
- **UE 蓝图**：强类型 pin + 执行/数据分离 + latent 节点 → **我们要的「类型化插槽」+「AI 节点是会等的 latent 进程」**。
- **Dify / n8n**：无状态管道、HITL 是 bolt-on → **我们要避免的反面：别把澄清/审批/通知塞进线性主线**。
- **传统 DAG**：确定性、无收敛回路 → **我们超越点：收敛回路 + 人监督 + 演进 artifact 是一等公民**。

*文档创建：2026-06-28 · 设计对齐自首启「第一性原理」讨论。*
