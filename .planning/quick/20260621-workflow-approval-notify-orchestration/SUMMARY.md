---
type: quick
slug: workflow-approval-notify-orchestration
status: complete
created: 2026-06-21
blocks_done: [C2, D1, D2]
blocks_pending: []
---

# 工作流重写收尾：审批合并 + 推送解耦 + 编排路径切换 — SUMMARY

> 本 SUMMARY 覆盖整个 quick task。**C2 / D1 / D2 均已完成并提交**（main 分支，code-only），
> 故 `status: complete`。

## C2 — 完成（合并 ai_plan_approval → human_approval，mode=plan_feishu）

**提交：** `83a0c3494`（单原子提交，code-only，main 分支）

### 实现的挂起通道决策

按 PLAN 已定决策落地：**飞书卡片审批统一接入 `waiting_approval` 通道，淘汰
`waiting_event` 的审批分支**。`human_approval(mode=plan_feishu)` 的 `execute` 返回
`waiting_approval`（不再 `waiting_event`）。验证可行的依据：

- 调度器主循环对 `waiting_approval` 与 `waiting_event` **本就同构处理**（均进
  `waiting_nodes_mem`、不加回 pending），`_rebuild_state_from_db` / `_continue_after_node`
  对两态一视同仁，故切换零行为漂移。
- `approve_node` / `reject_node` 已同时接受 `WAITING_APPROVAL` 与 `WAITING_EVENT`；
  `feishu/callbacks/approval_callback.py` 的 `_do_approval` 也已 filter 两态并经
  `approve_node`/`reject_node` 恢复 —— 故飞书审批卡片回调链路无需改动即指向
  human_approval 的恢复入口（C2.4 天然满足）。`plan_callback.py` 属 ReAct 方案生成卡片
  （D1 范围），未触碰。
- HITL 等待类节点（wait_feishu / chat_question 等）继续使用 `waiting_event`，不受影响。

### 变更文件

**后端：**
- `server/workflows/nodes/control/approval.py` — `HumanApprovalNode` 新增 `mode`
  （`generic`|`plan_feishu`，默认 generic）+ `chat_id`；吸收原 `ai_plan_approval` 的
  `_create_plan_document` / `_build_document_content` / `_send_approval_card`；plan_feishu
  分支产出 `{title, plan, final_answer, usage, document_url, approval_status}` 并返回
  `waiting_approval`。
- `server/workflows/nodes/ai/plan_approval.py` — **删除**（节点能力已合并）。
- `server/workflows/nodes/ai/__init__.py` — 移除 `PlanApprovalNode` 导入/导出。
- `server/workflows/engine/scheduler.py` — `approve_node` 的 INGEST-01 钩子改判
  `node_type == "human_approval" and config.mode == "plan_feishu"`（取 node_type + config）。
- `server/knowledge/sources/workflow_plan.py` — 审批节点查找 `node__node_type` 改
  `human_approval`。
- `server/workflows/migrations/0029_merge_plan_approval_into_human_approval.py` — **新增**
  数据迁移：存量 `ai_plan_approval` → `human_approval`，注入 `config.mode=plan_feishu`
  （保留既有 chat_id 等 config；reverse=noop）。
- `server/workflows/templates/code_generation.json` /
  `server/workflows/templates/feishu_full_pipeline.json` — 方案审批节点 `ai_plan_approval`
  → `human_approval`，config `{mode: plan_feishu, chat_id: ""}`。
- `server/workflows/nodes/integrations/feishu_doc.py` — 注释指向更新。

**前端：**
- `web/src/components/execution/HumanApprovalPanel.vue` — 吸收 PlanApprovalPanel 的方案
  摘要/任务/风险/假设折叠展示 + 文档链接；数据源合并 `approval_data`+`output_data`，
  状态兼容 `waiting_approval`/`waiting_event`/`completed`。
- `web/src/components/execution/NodeDetailSheet.vue` — 删除 `showPlanApproval` 与
  PlanApprovalPanel，仅保留 human_approval 分支（兼容存量 waiting_event）。
- 删除 `web/src/components/execution/PlanApprovalPanel.vue`、
  `web/src/components/workflow/config/AIPlanApprovalConfig.vue`。
- `web/src/types/workflow/node-definitions/categories/control.ts` — humanApproval schema/
  uiSchema 新增 `mode` + `chat_id`。
- 清理 ai_plan_approval 引用：`nodeVisuals.ts`、`registry.ts`（CONFIG_COMPONENTS）、
  `schemas.ts`、`ActionNode.vue`、`NodePalette.vue`、`portConfig.ts`（APPROVAL_NODE_TYPES）、
  `components.d.ts`。
- 重生成 `node-definitions.json`（19 defs）与 `node-types.fixture.json`（35 nodes，
  含 human_approval approved/rejected 端口、移除 ai_plan_approval）。
- 测试更新到新契约：`node-sync.test.ts`、`workflow-data-table.test.ts`、
  `BaseWorkflowNode.test.ts`。

### 测试结果

- 后端 `cd server && uv run pytest tests/workflows/ tests/test_plan_approval_node.py
  tests/workflows/test_engine_waiting.py tests/test_notification_hook.py
  tests/knowledge/test_triggers.py tests/test_ai_node_chain.py -q`：
  **611 passed, 2 skipped, 1 failed**。唯一失败
  `TestCodingTriggers::test_coding_chat_pr_created_branch_delivers_once` 为
  **既有失败（out-of-scope）** —— 失败在 `orchestration/coding_graph.py:create_pr_or_skip_node`
  → `services/git_credentials.py:resolve_git_token_sync`（`repo` 为 `[]` 列表，UUID 校验
  报错），与 C2 改动文件完全无关（编码-PR/git 凭证域），记入 `deferred-items.md`。
- `cd server && uv run python manage.py makemigrations --check --dry-run`：**No changes detected**。
- 前端 `pnpm -C web vitest run`（node-sync / definitions / HumanApprovalPanel /
  workflow-data-table / BaseWorkflowNode）：**5 files, 42 passed**。
- `pnpm -C web type-check`：C2 触碰文件零类型错误；唯一报错在
  `workflow-edge-routing.test.ts`（`EdgeRouteResult.strategy`）属另一在途 edge-routing
  任务的未提交改动，非 C2。
- `pnpm -C web eslint <touched files>`：clean。

### 偏离 / 说明

- 工作区存在另一未提交的 edge-routing/bezier quick task（CustomConnectionLine /
  edgeRouting / GradientEdge / WorkflowCanvas 等）。C2 提交**仅** stage 自己的文件，未触碰
  这些改动；`components.d.ts` 移除了指向未提交 `CustomConnectionLine.vue` 的自动导入行
  以保证本提交 type-check 自洽（该行会在对方下次 dev 重生成）。
- `amark_waiting_approval` 仅写 `approval_data`（未同时写 output_data）——前端 Panel 改为
  合并 `approval_data`+`output_data` 取数，避免改动模型层影响通用审批行为。

## D1 — 完成（飞书推送从 plan_generation / coding 解耦为独立通知/文档节点）

**提交：** `adb1e3f27`（单原子提交，code-only，main 分支）

### 变更文件

**后端：**
- `server/workflows/nodes/ai/plan_generation.py` — `get_enabled_tools` 默认工具集
  移除 `send_plan_card` / `create_feishu_document`（自动推送职责），保留 `verify_plan` /
  `search_repository_code` / `ask_user_question`（澄清 HITL）/ `fetch_feishu_document`
  （只读取材）。同步重写 `_PLAN_GENERATION_BASE_PROMPT`（删除「第三阶段：飞书交互」段，
  改为「产出方案后由下游节点接管审批/推送」）+ 类 docstring。
- `server/workflows/nodes/ai/coding.py` — 结果通知 `_send_result_notification` 降级为
  **可选回退**（chat_id 留空 → `log.debug("result_notification_skipped_decoupled")`
  跳过，非错误）；`chat_id` config description 改述为「分支确认卡片用途 + 结果通知已解耦」；
  模块/类 docstring 标注解耦。**分支确认卡片 HITL（`_send_branch_confirmation`）逐字不动**。
- `server/workflows/templates/code_generation.json` /
  `server/workflows/templates/feishu_full_pipeline.json` — 在 `ai_coding` 后串联
  `feishu_doc_create`（生成交付文档）+ `notify_feishu_im`（通知编码结果），新增对应 edges。

**前端：**
- `web/src/components/workflow/config/AIPlanGenerationConfig.vue` — 第 5 步「飞书推送」
  改为「飞书澄清提问（可选）」，chat_id 文案改述为「仅用于 AI ask_user_question 澄清；
  方案文档/审批/推送由下游节点负责」；移除「飞书交互」能力标签。
- `web/src/components/workflow/config/AICodingConfig.vue` — chat_id 标「可选」+ 文案改述
  「分支确认卡片用途；结果通知已解耦到下游飞书通知(IM)节点」；流程图「通知结果」→「下游通知」。

**测试：**
- `server/tests/test_plan_generation_node.py` — `test_get_enabled_tools_includes_defaults`
  断言更新（移除 send_plan_card/create_feishu_document，新增 ask_user_question/
  fetch_feishu_document 存在 + 推送类工具不存在）；`test_plan_generation_tool_loop_with_fake_model`
  回放序列去掉 send_plan_card turn（改 verify_plan → final）。
- `server/tests/workflows/test_template_loader.py` — code_generation 节点数断言 4 → 6。

### 分支确认 HITL vs 结果通知 拆分实现

- **分支确认（HITL，保留挂起）**：`AICodingNode.execute` 在无法解析分支名时调
  `_send_branch_confirmation` 发飞书确认卡片并 `return waiting_event`，由飞书回调写回
  `_confirmed_branch_name` 重入 `_execute_with_branch` 恢复 —— 此链路**完全未改动**，
  挂起→恢复完整。
- **结果通知（解耦为可选回退）**：`_finalize_and_notify` / `_finalize_wave` /
  `_resume_legacy` 收尾段仍调 `_send_result_notification`，但该方法在 chat_id 为空时直接
  跳过（默认模板 chat_id=""）→ 不再是硬依赖；主推送路径改由模板里下游 `notify_feishu_im`
  节点承担。

### send_plan_card resume linkage 去向

- C2 已把方案+飞书卡片**审批**收口到 `human_approval(mode=plan_feishu)` 走
  `waiting_approval` 通道（approval_callback 恢复）。D1 据此把 `send_plan_card`
  （`requires_suspension=True`，原在 plan_generation agent loop 内触发 suspend、经
  plan_callback → schedule_resume_agent_session 恢复）从默认工具集移除——**plan_generation
  不再产生方案卡片 suspend**，节点正常 completed 后由下游 human_approval 接管审批挂起。
  故**无悬挂 resume / 无死锁**：方案多轮迭代改由模板边 `plan_approval --rejected-->
  generate_plan` 回流实现（C2 模板已就位）。`send_plan_card` 工具与 `plan_callback.py`
  保留（未删），供存量/手动启用，不属 D1 删除范围。
- `ask_user_question`（澄清 HITL，独立 resume 链路）保留在工具集，不受影响。

### 测试结果

- 后端 `uv run pytest tests/workflows/ tests/test_coding_node.py tests/test_coding_wave.py
  tests/test_ai_node_chain.py tests/test_notification_hook.py`：**582 passed, 2 skipped,
  1 xfailed, 1 error**。唯一 error =
  `tests/workflows/test_engine_trigger_data.py::TestTriggerDataReadSide::test_dispatcher_full_chain_resolves`
  —— 单独运行 **passed**，属测试隔离/顺序问题（dispatcher trigger data 域，非 D1 文件），
  **非 D1 引入的新失败**。
- 后端 `uv run pytest tests/test_plan_generation_node.py
  tests/workflows/test_plan_generation_tools_guard.py tests/workflows/test_template_loader.py`：
  **41 passed**。
- `uv run python manage.py makemigrations --check --dry-run`：**No changes detected**。
- 前端 `pnpm exec vitest run node-sync definitions`：**3 files, 39 passed**（fixture 与生成
  TS defs 仍一致——D1 未改端口/节点类型，fixture 零漂移）。
- `pnpm type-check`：**exit 0 干净**（无 D1 文件类型错误）。
- `CI=true pnpm exec eslint <两个 config 面板>`：**clean**。
- node-defs/fixture 重生成：**无语义 diff**（ai_coding/ai_plan_generation 不在前端 TS
  node-defs；fixture 仅含 node_type/category/ports）；node-definitions.json 仅 generated_at
  时间戳变动，已 `git checkout` 还原避免无意义 diff。
- 既知预存失败 `test_coding_chat_pr_created_branch_delivers_once`（git 凭证 `repo=[]`）
  未触碰、与 D1 无关。

### 偏离 / 说明

- **chat_id 未从 plan_generation 完全移除**：该字段（继承自 `AIAgentBaseNode`）仍被
  `ask_user_question` 澄清 HITL 使用（base_agent `_ensure_agent_session` 据其建会话写
  temp_data），故前端面板**重定位**为「飞书澄清提问」而非删除（符合 D1.4「或标注为
  可选回退」）。
- `_send_result_notification` 方法**保留**（未删）作为可选回退，仅默认（chat_id 空）不
  推送 —— 满足 D1.2「chat_id 配置可保留但默认不推送」。
- 工作区 `web/src/components.d.ts` 有 2 行 unplugin 自动导入新增（CustomConnectionLine /
  NodeInsertMenu，属另一在途 edge-routing/canvas 任务），**未纳入本提交**（仅 stage 自己
  的 8 个 D1 文件）。
- ⚠️ 过程记录：调试 ruff 时误用 `git stash`（main 直提，非 worktree），第一次 pop 静默失败
  致工作树一度显示无改动；经 `git stash pop` 二次恢复，全部改动完整无丢失（edge-routing
  任务其时已落 3 个提交 e5ddd5c5e/87ce25eba/f3cf6f50b，故未受影响）。后续避免 git stash。

## D2 — 完成（内置模板切换到 ai_plan_research 编排路径，多仓多agent）

**提交：** `c3d3b9dbc`（单原子提交，code-only，main 分支，6 文件 / +222 -28）

> ⚠️ 并发记录：提交期间另一在途 edge-routing/dify 任务在 main 并发提交（含一次
> `git add -A` 扫动），导致首次 `git commit` 因「索引被对方扫空」报 nothing-staged
> 失败；重新仅 `git add` 自己 6 个文件后提交成功（`c3d3b9dbc`）。全程未用 `git stash`，
> 未触碰对方文件（`web/src/components.d.ts` 始终保留对方的 CustomConnectionLine/
> NodeInsertMenu 自动导入新增，未 stage/未改/未还原）。

### 变更文件（6）

**后端：**
- `server/workflows/nodes/ai/plan_research.py` —
  - 输出 `default` 端口 schema 新增 `plan`（object）；`done` 终态 `_map_terminal`
    改 **async**，加载 `PlanVersion.content`（§7 MergedPlan）内联为 `plan` 并把
    `plan_version_id` 注入其中。
  - 新增 `_resolve_include_repos`（逐项 render_template）；`_resolve_work_item`
    支持 render_template（用户可用模板变量；模板默认空 → INV-2 允许无 work_item）。
  - 模块/`_resolve_session`/`_create_session`/`_map_terminal` docstring 固化点4 契约。
- `server/workflows/engine/scheduler.py` — `approve_node` 的 INGEST-01 知识摄取钩子
  生成节点查找改 `node__node_type__in=["ai_plan_generation", "ai_plan_research"]`
  （两路径均经 `output_data["plan"]` 摄取，normalizer 无需改）。
- `server/workflows/templates/code_generation.json` /
  `server/workflows/templates/feishu_full_pipeline.json` — `generate_plan` 由
  `ai_plan_generation` 改 `ai_plan_research`，config `{requirement_text, include_repos:[],
  work_item_id:""}`；保留 C2/D1 下游接线（human_approval(plan_feishu) → ai_coding →
  feishu_doc_create + notify_feishu_im + rejected 反馈环）；`create_doc.content` 由
  `{{nodes.generate_plan.final_answer}}` 改 `{{nodes.generate_plan.plan.summary}}`
  （适配新产物；`plan.title` 引用不变，因 schema 新增 `plan` 后字段校验通过）。

**测试：**
- `server/tests/workflows/test_plan_research_node.py` — 新增
  `test_done_inlines_merged_plan_content_for_downstream`（done 内联 §7 MergedPlan +
  注入 plan_version_id）与 `test_resume_via_session_id_ignores_conflicting_input`
  （点4：续推钥匙在场时忽略冲突的 requirement_text、不新建 session）。
- `server/tests/workflows/test_template_loader.py` — code_generation 节点数仍 6（仅
  类型变更），新增断言 `ai_plan_research in node_types` & `ai_plan_generation not in`。

### 点4「上游输入 vs 驳回回流」契约如何显式化

物理隔离两条通道，冻结于节点 docstring + routing 行为：
- **续推（resume）= 本节点自身 `NodeExecution.output_data["session_id"]`**：仅
  clarifying/researching 挂起时写入；`_resolve_session` 据此重取**同一** PlanSession，
  `execute` 内「resolve 先于 create」短路 → resume **绝不读取 `default` 输入端口需求**。
- **首建（first-run）= config `requirement_text` ∪ `default` 输入端口**：仅当续推通道
  为空才走 `_create_session`。
- **驳回（rejection）**：`human_approval(rejected)` 经 `reject_reason` 显式字段沿
  `rejected` 出边回流；模板 `plan_approval --rejected--> generate_plan` 是 DAG
  **back-edge**，引擎按 back-edge 处理（`routing._forward_edges` 过滤反馈环，已
  COMPLETED 的生成节点不自动重跑）→ 驳回是「干净止于审批、不进编码」的 HITL 终止
  （ai_coding 的 `approved` 支 skip_unselected，下游级联 skip，**无死锁**）。多轮方案
  修订由编排引擎自身 session 内澄清/融合重试回路（suspend/resume）承担，**不**借模板
  back-edge 把驳回反馈误当首次需求重新建 session——这正是点4 消解的二义性。
- 测试覆盖：首跑（`test_missing_requirement_fails_fast` / `test_drive_to_done_*` 等）
  + resume（`test_resume_via_session_id_ignores_conflicting_input` /
  `test_research_suspend_resume_reaches_done_via_node_execution` e2e）两路径。

### TechnicalPlan → PlanSession/MergedPlan 产物迁移如何处理 ai_coding 兼容

经典 `ai_plan_generation` 产顶层平铺 `TechnicalPlan` JSON；编排 `ai_plan_research` 产
canonical `PlanVersion`。迁移策略：**ai_plan_research done 终态在 `default` 端口同时
携带引用三元组（session_id/plan_version_id/status）与内联 `plan`（=PlanVersion.content，
§7 MergedPlan，含 execution_plan）并注入 plan_version_id**。链路：
`generate_plan.output["plan"]` → 经 `collect_inputs`/审批节点透传 →
`human_approval(plan_feishu).get_input("plan")`（落审批文档 summary/execution_plan）→
approved 输出再透传 → `ai_coding.get_input("plan")`。ai_coding `_extract_plan_data`
**无需改动**：读 `plan.execution_plan`/`plan.plan_version_id`，命中 `plan_version_id`
即解析 canonical `PlanVersion` 进 **wave 模式**（多仓多 agent fan-out）。

### 多仓 / 多 agent 端到端验证状态

`RepoRouterV2Adapter`（多仓路由）/ `ResearchDispatchAdapter`（high/medium 置信仓 per-repo
容器 fan-out）/ `wave_layering`（拓扑分层）在编排路径下端到端可跑，由
`tests/services/test_plan_research_e2e.py` 3 用例守护（IO 边界 mock）：
`test_e2e_requirement_to_merged_plan_with_cross_repo_deps`（两仓路由+并行调研+融合产
跨仓 MergedPlan，dispatch.await_count==2）、`test_research_suspend_resume_reaches_done_via_node_execution`
（researching waiting_event → 容器回调 → resume → done）、
`test_e2e_clarification_loop_reruns_only_affected`（澄清回路仅重跑受影响仓）。**全绿**。

### 测试结果

- `cd server && uv run pytest tests/workflows/ tests/test_ai_node_chain.py
  tests/services/test_plan_research_e2e.py -q`：**554 passed, 2 skipped**（含
  test_plan_research_node 9 例、test_plan_research_e2e 3 例、test_template_loader 30 例、
  test_api 模板用例）。无新失败；既知隔离 flaky `test_dispatcher_full_chain_resolves`
  本次未触发（通过）。
- `cd server && uv run python manage.py makemigrations --check --dry-run`：**No changes detected**。
- `cd server && uv run pytest tests/knowledge/test_triggers.py tests/test_coding_node.py
  tests/test_coding_wave.py -q`：**67 passed, 1 xfailed, 1 failed**——唯一失败即既知预存
  `test_coding_chat_pr_created_branch_delivers_once`（git 凭证 `repo=[]`，deferred-items.md
  已记，非 D2 引入）。
- 前端 `pnpm -C web exec vitest run node-sync definitions`：**3 files, 39 passed**。
  D2 未改节点类型/端口名/增删节点；fixture 仅记 node_type/category/port name（不记端口
  schema），故 `ai_plan_research` 输出新增 `plan` 属性对 fixture 零影响 → **无需重生成
  node-defs/fixture**，也未触碰任何前端文件。

### 偏离 / 说明

- **work_item_id 模板默认留空**：`fetch_work_item` 输出 schema 无 `work_item_id` 字段
  （其 id 为飞书整型 work item id，≠ delivery.WorkItem UUID），且二者无干净映射；INV-2
  允许无 work_item 锚，故两模板 `work_item_id=""`（字段已"wired"，用户可填 UUID/模板变量，
  节点已支持 render_template）。需求经 `requirement_text` 承载，路由经 `include_repos`
  （默认空 → 按全库/项目路由）。此为避免 graph validator `field_not_found` 的安全选择。
- **未删 ai_plan_generation 节点**：PLAN D2 仅要求「模板中替换」，节点保留供存量工作流/
  手动启用；INGEST 钩子双类型兼容。
- 既知预存失败 `test_coding_chat_pr_created_branch_delivers_once` 未在 D2 触碰/消化（git
  凭证域，独立修复范围），仍记于 deferred-items.md。
