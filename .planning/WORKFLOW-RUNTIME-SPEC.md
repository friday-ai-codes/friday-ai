# 工作流运行时合同（WORKFLOW-RUNTIME-SPEC）

> Chassis v2 的运行时语义合同。配合 `.planning/AI-WORKFLOW-SIGNAL-MODEL-SPEC.md`
> （设计动机）与 `.cursor/plans/工作流底盘重构_*.plan.md`（分阶段路线）阅读。
> 本文件钉死"节点/边类型、信号投影、反应语义、artifact 关系、durability"等运行时
> 不变量，避免各 phase 实现漂移。
>
> 语言：正文中文；代码标识 / 路径 / 信号名保留英文。

---

## 1. 节点类型（node kind）

每个节点声明一个 `kind`（`BaseNode.kind` ClassVar，P2 起补齐）：

- `deterministic`：纯函数式工序（http_request / code / condition / 数据节点）。
- `ai_process`：驱动一个可恢复的 `ConvergenceSession`（收敛回路）的 AI 节点。
- `human_task`：产生人类待办并挂起（审批 / 澄清回答 / 接管）。
- `external_wait`：等待外部事件唤醒（wait_feishu_field 等），落 `WorkflowEventSubscription`。
- `reaction`：横切副作用（通知 / 文档 / 回写 / 告警），默认不进主 DAG（见 §4）。
- `gate`：会改变"主交付是否继续"的闸门（human_approval）。

注意：`kind` 是运行时语义标签，**不**等于 UI `category`（trigger/action/control/integration/ai）。

## 2. 边类型（edge kind）

- `delivery`：实线主交付流（artifact 往前推进），现 gradient 边。
- `data`：纯数据依赖（模板引用 `{{nodes.x.y}}` 也属此类语义）。
- `signal_subscription`：虚线信号订阅边，**派生自 `WorkflowReaction` 配置**，
  不是独立事实源（P4/P6）。
- `artifact_dependency`：节点对某 `ArtifactVersion` 的读写依赖（P2/P7）。

## 3. Signal 投影（不建第三套事件表）

Signal 是对既有事实源的**即时投影**，是稳定、对用户可见的语义值对象，不持久化。

来源（投影函数见 `server/workflows/reactions/signal.py`）：

- `workflow_hook`：`project_from_hook(event, execution, node_execution)` —— P0 已实现。
- `process_event`：来自 `ConvergenceSessionEvent`（P2）。
- `artifact_transition`：来自 `ArtifactVersion` 产出/废弃/审批（P1/P2）。

`Signal` 形状：`name / scope / subject_id / source / payload / occurred_at`。
- `scope ∈ {workflow_execution, node_execution, process_session, artifact}`。
- node 类信号 `subject_id` = 宿主 `WorkflowNode.id`（便于按 host_node 匹配反应）。
- `payload` 仅受控、脱敏字段（execution_id / node_status / error_code），
  **禁止**放 LLM 原文 / 飞书原始 payload / 异常全文。

稳定信号词表（`SIGNAL_NAMES`）：

- 节点：`node.started` / `node.completed` / `node.failed` / `node.waiting`
- 流程：`process.stage_changed` / `process.failed` / `clarification.asked` / `clarification.answered`
- artifact：`artifact.produced` / `artifact.superseded` / `artifact.approved`
- 审批：`approval.requested` / `approval.granted` / `approval.rejected`

hook 事件 → 信号映射（P0）：`node_started→node.started`、`node_completed→node.completed`、
`node_failed→node.failed`、`node_waiting_approval→{node.waiting, approval.requested}`、
`node_waiting_event→node.waiting`、`node_approved→approval.granted`、`node_rejected→approval.rejected`。
`node_skipped` 不产生信号。

## 4. Reaction 语义

`WorkflowReaction`（配置）+ `ReactionExecution`（执行留痕）见
`server/workflows/models/reaction.py`；运行时见 `server/workflows/reactions/runtime.py`。

不变量：

- **幂等**：幂等键 = `execution_id : signal.subject_id : signal_name : reaction_id`
  （`subject_id` 为信号发出主体即发出节点；工作流级反应被多个节点触发时各自独立
  去重，绑定 host_node 的反应 subject 恒等于 host_node）。唯一约束
  `uniq_reaction_execution_idempotency`。同一信号重放命中已有记录即短路，绝不重复
  副作用（修复现状 notify/doc 每跑必副作用）。
- **永不反噬主流程**：non_blocking 反应失败仅记 `ReactionExecution.failed` 可查，
  不抛回主交付链路。`ReactionDispatchHook` 用 `create_task` 后台分发。
- **blocking_mode**：
  - `non_blocking`：通知/文档/回写/webhook（默认）。
  - `gate`：人工审批等，由 DAG 节点承载，runtime **跳过**不当订阅触发。
  - `compensation`：失败补偿（后续）。
- **可扩展 target**：`runtime.register_executor(target_type)` 注册执行器；
  P0 内置 `webhook` / `notify_feishu_im` / `alert`，P4 接 UI 后扩 `feishu_doc_create` / `writeback`。
- **重试**：`retry_policy = {max_attempts, backoff_seconds}`，runtime 内有界重试。

匹配规则：`workflow_id` + `signal_name` + `enabled`，且 node 类信号需
`host_node == subject` 或 `host_node 为空`（工作流级反应）。

`AlertRule`/`AlertRuleExecution`（既有）是本运行时的设计原型；P0 暂保留独立，
后续可收编为 `target_type=alert` 的反应。

## 5. Artifact 关系链（P1/P2）

`WorkItem → ArtifactVersion(technical_plan vN) → RepoCodingTask → PR/MR → writeback/document`。
`Artifact`/`ArtifactVersion` 为事实源，单一写入入口 `ArtifactService`；
`ConvergenceSession.current_artifact_version` 指向当前产物版本。

## 6. Durability（重启/超时恢复）

- **事件订阅超时**：`check_timeouts` 命令按 `timeout_action` 处理
  （`fail`/`skip`/`retry`）；`retry` 经引擎 `_continue_after_node` 重跑等待节点
  （重新挂起并刷新 timeout），以 `execution.context._timeout_retries` 有界（默认 3）。
  已接入 APScheduler（`check_workflow_event_timeouts`，~60s）。
- **挂起执行恢复**：SUSPENDED 执行的状态全持久化在 DB（execution/node/subscription），
  由外部事件回调（飞书/容器/审批）经 `_continue_after_node` 续推；超时由上面的
  扫描兜底。
- **观测**：所有反应/超时事件结构化 started/completed/failed + duration_ms，
  设 `category`（caller/sampling）+ `component`；best-effort，绝不反噬业务。

## 7. 红线（实施必守）

- 不新增第三套 `WorkflowSignalEvent` 事实表；signal 走投影。
- reaction 必须有幂等 DB 记录，不靠前端隐藏边触发。
- 不把 `NodeExecutionStatus` 扩成庞大 AI 内部状态枚举；AI 内部态从
  `ConvergenceSession` / 子任务 / trace 投影。
- 通知/文档/回写失败默认不升级为 workflow failed（除非声明为 gate/blocking）。
- artifact timeline 不做画布伪节点；在执行详情/工作台呈现。
- 不旁路单一写入入口（`ArtifactService` / `ClarificationService` / `ConvergenceSessionService`）。

---

*创建：2026-06-28 · Chassis v2 P0。后续 phase 落地新增章节，不回改已钉不变量。*
