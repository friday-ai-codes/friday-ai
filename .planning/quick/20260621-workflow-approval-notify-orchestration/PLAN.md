---
type: quick
slug: workflow-approval-notify-orchestration
status: in-progress
created: 2026-06-21
---

# 工作流重写收尾：审批合并 + 推送解耦 + 编排路径切换

> 接续已完成并推送的工作流重写（A1 飞书文档节点 / A2 飞书IM通知节点 / B1 去容器镜像 / C1 删除 ai_code_review）。
> 本任务覆盖剩余三块深度耦合的架构改动 C2 / D1 / D2。每块完成即跑测试验证再进下一块，保持仓库始终可编译可运行。

## 背景（探索结论，避免重复摸排）

方案侧存在**两条并行路径**：
- 经典路径（内置模板在用）：`ai_plan_generation`（ReAct，`LangChainAgentRunner`）+ `ai_plan_approval`。
- 编排路径（较新、未进公开模板）：`ai_plan_research` → `PlanOrchestrationEngine.advance()`（多仓路由 + 拆分 + 多 agent 并行）。

关键耦合点（改动必经）：
- 调度器挂起态分两套：`ai_plan_approval` 用 `waiting_event`；`human_approval` 用 `waiting_approval`
  （`server/workflows/engine/scheduler.py`）。
- 飞书审批/卡片回调：`server/feishu/callbacks/plan_callback.py`、`approval_callback.py`；
  agent resume 经 `server/tasks/agent_tasks.py` + `schedule_resume_agent_session`。
- 方案审批通过会触发 knowledge ingestion 钩子（`scheduler.py` 约 1372-1404）。
- 前端面板：`web/src/components/execution/PlanApprovalPanel.vue`（waiting_event）、`HumanApprovalPanel.vue`（waiting_approval）；
  `NodeDetailSheet.vue` 按 nodeType + status 决定展示哪个面板。
- `send_plan_card` / 分支确认卡片与 `waiting_event` + resume 强绑定（`plan_generation.py` 默认工具集、`coding.py:1407-1473 / 1913-1975`）。
- 节点注册自动发现 + 前端 `node-definitions.json`/fixture 需同步（删/改节点后跑
  `pnpm -C web generate:node-defs` 与 `pnpm -C web gen:node-fixture`）。
- 已存工作流 `WorkflowNode.node_type` 无降级：删/改节点类型必须配数据迁移
  （参考 `server/workflows/migrations/0028_remove_ai_code_review_nodes.py` 与 `0009/0010`）。

## 方案

### C2 — 合并 ai_plan_approval → human_approval（点6）

目标：统一为单一审批节点 `human_approval`，通过 `mode` 区分「通用控制台审批」与「方案+飞书卡片审批」。

1. `human_approval` 节点 config 增加 `mode`（`generic` | `plan_feishu`，默认 `generic`）+ 复用 `ai_plan_approval`
   的 `chat_id` / 飞书文档生成能力（`_create_plan_document`）。
2. 调度器挂起态统一：让 `mode=plan_feishu` 也走 `waiting_approval`，或在 `human_approval` 内桥接飞书卡片回调；
   决策点——优先把飞书卡片审批接入 `waiting_approval` 通道，淘汰 `waiting_event` 的审批分支（HITL 仍保留给等待类节点）。
3. 迁移 ingestion 钩子：审批通过（plan_feishu 模式）仍触发 knowledge ingestion。
4. 飞书回调 `approval_callback.py` / `plan_callback.py` 统一指向 human_approval 的恢复入口。
5. 前端：`HumanApprovalPanel.vue` 吸收 `PlanApprovalPanel.vue` 的方案展示/文档链接；`NodeDetailSheet.vue`
   只保留 human_approval 分支；删除 `ai_plan_approval` 的 def/visuals/palette/registry/schema/panel。
6. 数据迁移：把存量 `ai_plan_approval` 节点 `node_type` 改名为 `human_approval` 并写入 `config.mode=plan_feishu`
   （rename + config 注入，参考 `0010_rename_node_types.py` / `0011`）。
7. 内置模板 `code_generation.json` / `feishu_full_pipeline.json` 的 `plan_approval` 改为 `human_approval(mode=plan_feishu)`。

### D1 — 飞书推送从 plan_generation / coding 解耦（点8/10）

目标：生成/编码节点专注产出，推送交给独立通知节点（已备好 `notify_feishu_im` + `feishu_doc_create`）。

1. `ai_plan_generation`：默认工具集移除 `send_plan_card`/`create_feishu_document` 的「自动推送」职责，
   仅产出 `TechnicalPlan` + markdown；HITL 审批交给下游 `human_approval(mode=plan_feishu)`。
   - 注意：`send_plan_card` 与 agent resume 的挂起链路要么迁到 human_approval，要么由独立通知节点承担。
2. `ai_coding`：分支确认卡片（`coding.py:1407-1473`）与结果通知（`1913-1975`）抽离——
   分支确认作为 HITL 仍需挂起，可保留在 coding 或下沉到 control 节点；纯「结果通知」改由下游 `notify_feishu_im` 承担，
   移除 coding 内的 `_send_result_notification` 强依赖（`chat_id` 配置可保留但默认不推送）。
3. 模板串联：在 `human_approval`/`ai_coding` 后接 `feishu_doc_create` + `notify_feishu_im`，让「文档生成」「通知人/群」可视可配。
4. 前端配置面板同步去掉已解耦的 `chat_id` 推送项（或标注为可选回退）。

### D2 — 切换内置模板到 ai_plan_research 编排路径（点4/7/路径）

目标：内置模板默认走多仓路由 + 多 agent 并行的编排路径，并消解「上游输入 vs 驳回回流」二义性。

1. 用 `ai_plan_research` 替换模板中的 `ai_plan_generation`（`feishu_full_pipeline.json` / `code_generation.json`），
   接入 `include_repos`（UUID）、`requirement_text`、`work_item_id`。
2. 点4 二义性统一：`ai_plan_research` resume 从 `NodeExecution.output_data.session_id` 取 `PlanSession`，
   驳回信息经审批节点回流时以显式端口/字段携带（不再与首次上游输入混淆）；在节点文档与 routing 注释中固化该契约。
3. 处理两套方案产物迁移：`ai_plan_generation`→`TechnicalPlan` JSON vs `ai_plan_research`→`PlanSession`/`plan_version_id`；
   下游 `ai_coding` 的 `plan` 输入需兼容 MergedPlan（`execution_plan` 形态）。
4. 多仓多 agent：确认 `RepoRouterV2Adapter` / `research_adapter`（high/medium 置信仓 per-repo 容器 fan-out）
   / `wave_layering` 在模板路径下端到端可跑。
5. 重写/更新模板 + 模板加载测试（`test_template_loader.py` / `test_api.py` 的模板计数与节点数断言）。

## 验收

- 后端：`uv run pytest`（至少 `tests/workflows/` + `tests/test_ai_node_chain.py` + 审批/编排相关）全绿；
  `python manage.py makemigrations --check --dry-run` 无遗漏。
- 前端：`pnpm vitest run`（节点同步/定义/面板）+ `pnpm type-check` + `pnpm lint` 干净。
- 每次删/改节点后重生成 `node-definitions.json` 与 `node-types.fixture.json` 并对账（node-sync 测试）。
- 端到端：从内置模板创建工作流可保存可执行（编排路径多仓需求能路由+并行调研+合并方案）。

## 原子提交边界（建议）

- `refactor(workflow): 合并 ai_plan_approval 进 human_approval(mode=plan_feishu) + 迁移`
- `refactor(workflow): 飞书推送从 plan_generation/coding 解耦为独立通知/文档节点`
- `feat(workflow): 内置模板切换到 ai_plan_research 编排路径（多仓多agent）`

## 风险

- 审批/HITL 挂起-恢复链路改动若不完整会直接让工作流执行卡死——务必每步跑执行相关测试。
- 飞书回调路由改动需前后端契约同步（`server/feishu/callbacks/` ↔ 前端面板动作）。
- 两套方案产物迁移：存量执行记录/工作流引用旧节点，迁移需覆盖 rename + config + 端口。
