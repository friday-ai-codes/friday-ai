# Phase 88: 智能业务关联仓库（Repo Association）- Research

**Researched:** 2026-06-27
**Domain:** 复用既有 v0.7/v0.8/v0.11/v0.12/v0.15/v0.16 地基，编排「知识库+RAG 选仓 → 卡片 HITL 多轮确认 → 逐仓容器深验 → 最终确认」交互回路（REPO-01/02）
**Confidence:** HIGH（全部基于真实代码勘察，无新外部依赖）

<user_constraints>
## User Constraints (from 88-CONTEXT.md)

### Locked Decisions（锁定决策，研究只围绕这些，不探索替代方案）

1. **候选仓库排序依据 = 语义相关度 + 仓库活跃度 综合打分（COMBINED）**
   - 结合知识库（活跃度/功能梳理）+ RAG 多轮检索，对候选仓库综合打分排序。
   - Agent 自处理 + 发卡片引导式多轮澄清/确认涉及仓库（含用户自校验）。

2. **确认后逐仓自校验深度 = 开 claude code task（容器化 agent）深入验证**
   - 用户确认仓库后，对每个仓库**派 claude code task**（容器内运行编码 agent）深入仓库**代码**验证业务适配性，而非仅元数据/README 匹配。
   - 自校验发现不符 → 可回退重确认。
   - 校验完成 → 最终卡片确认。
   - 容器任务复用 **v0.12 durable + v0.8 dispatch**；带 `initiated_by_user_id`；新增 LLM/召回埋点（`call_source` + `RetrievalTrace`）。

3. **交互回路（REPO-01/02）**
   - 卡片引导式多轮澄清（CardKit）；用户确认仓库 → 逐仓 claude code task 自校验 → 最终卡片确认。
   - 全程 **fail-soft，单仓校验失败不阻断其余**。

### Claude's Discretion（可自行决策并给出推荐）

- COMBINED 打分的归一化方式、权重系数；
- 容器深验的 task_mode（推荐 `explore` 只读）、prompt 结构、verdict schema；
- 新增持久化模型的字段细节（在复用既有模型基础上）；
- 卡片交互状态机的状态枚举命名与超时时长。

### Deferred Ideas（OUT OF SCOPE）

- None — 讨论保持在 phase scope 内。
- （里程碑级 v2 项 PROJX-01~06 与本期无关，不碰。）
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REPO-01 | 智能仓库关联——基于 feature list + 拆分看板，结合知识库（活跃度/功能梳理）+ RAG 多轮 + Agent 自处理，发卡片引导式多轮澄清/确认涉及仓库 | COMBINED 选仓 = `RepoRouterV2.route`（节点级 hybrid + LLM 树推理 + 活跃度 facet 降权，`server/codegraph/services/repo_router_v2.py`）+ 卡片 HITL 复用 Phase 87 模式（workflow node `waiting_event` + CardKit + card callback，见 §Architecture）。消费 Phase 87 `BoardSplitService.propose_split` 输出 `{modules, features_flat}` 作选仓 query 语料。 |
| REPO-02 | 用户确认仓库后逐仓自校验（基于确认仓库再验证业务适配性，发现不符可回退重确认）+ 最终卡片确认 | 逐仓容器深验 = 复刻 `ResearchDispatchAdapter`（`server/services/plan_orchestration/research_adapter.py`）的 per-repo explore 容器 fan-out + `node_execution_id` → `_schedule_workflow_resume` 回调续驱 + 单仓 fail-soft 隔离。verdict 持久化镜像 `RepoResearchTask`/`PartialPlan`（`server/delivery/models/research_task.py`）。 |
</phase_requirements>

## Summary

Phase 88 是一个**纯编排/复用阶段**——几乎不引入新机制，而是把六个已交付的子系统串成一条「选仓 → 卡片确认 → 逐仓容器深验 → 最终确认」的人机协同回路。所有需要的底座都已存在且经勘察确认：

1. **COMBINED 选仓**：`RepoRouterV2`（`server/codegraph/services/repo_router_v2.py`）**已经**实现「语义相关度（节点级 dense+sparse hybrid 检索 RRF）+ 仓库活跃度（facet `活跃度` 降权）+ LLM 树推理」三合一打分，正是锁定决策要的 COMBINED ranking。活跃度由 `FacetService`（`server/repositories/facet_service.py`）从 `FileIndex.last_commit_authored_at` 计算四档（`活跃开发/维护中/低频/疑似废弃`）写进 `Repository.facets`。**唯一缺口**：RepoRouterV2 当前**未**埋 `call_source`（枚举里 `AUX_REPO_ROUTER` 已预留但未用）和 `RetrievalTrace`——Phase 88 必须补齐（观测强制）。

2. **卡片 HITL 多轮回路**：Phase 87（`board_split_review.py` 节点 + `board_split_card.py` 卡片 + `board_split_callback.py` 回调）是**逐字可照搬的模板**——workflow 节点返回 `waiting_event` + 持久化 `output_data`（轮次/提案/来源）+ 建 `WorkflowEventSubscription`（超时兜底）；CardKit schema 2.0 流式卡 + 按钮/输入框；回调走 `_run_in_thread` + `bind_task_context` 后台处理，多轮重拆保持 `waiting`、确认走 `approve_node` 恢复。

3. **逐仓容器深验**：`ResearchDispatchAdapter`（`server/services/plan_orchestration/research_adapter.py`）**已经**实现「per-repo fan-out 独立 claude code 容器（`explore` 只读模式）+ `node_execution_id` → 容器回调 `_schedule_workflow_resume` 续驱挂起节点 + 单仓 `mark_failed` fail-soft 隔离 + INV-6 经 service 写库」。task 容器侧 `explore` 模式（`task/core/runner.py::_run_explore_mode`）做只读深度代码分析、产文本、强制 workspace clean——正是「深入仓库代码验证业务适配性，不写 git」的现成能力。

4. **durable + 归因**：`resumable/service.py::submit_resumable/wrap_resumable` 提供 durable 登记/心跳/续跑；`common.log_context.bind_task_context` 在 worker 入口 re-bind `initiated_by_user_id`。

**Primary recommendation:** 新建一个 `RepoAssociationService`（`server/initiatives/services/`，INV-6 单一编排收口）+ 一个 workflow 节点 `RepoAssociationNode`（`server/workflows/nodes/integrations/`）+ 一个 AI 会话工具 `associate_repos`（`server/agents/tools/`）+ 一组 CardKit 卡片（`server/feishu/cards/repo_association_card.py`）+ 卡片回调（`server/feishu/callbacks/repo_association_callback.py`）+ 复用 `RepoRouterV2`（补埋点）+ 复刻 `ResearchDispatchAdapter` 的 per-repo explore 容器 dispatch（verify 语义）+ 新持久化模型 `RepoAssociation`/`RepoVerifyTask`。**严格照 Phase 87 + ResearchDispatchAdapter 两个模板拼装，不重造任何机制。**

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 候选仓库 COMBINED 打分（语义+活跃度+LLM） | API/Backend（`RepoRouterV2`，Qdrant + LLM） | Database（`Repository.facets`/`repo_index_nodes` Qdrant collection） | 选仓是后端检索+推理，前端只展示候选 |
| feature list 语料归一（Phase 87 输出消费） | API/Backend（`BoardSplitService.propose_split`/`FeatureListExtractor`） | — | 已是后端 service，本期只读其输出 |
| 卡片引导多轮澄清/确认（HITL） | Feishu（CardKit）+ Workflow 引擎（`waiting_event`/回调） | API/Backend（service 编排） | 交互面在飞书卡片；状态机在 workflow node + callback |
| 逐仓容器深验（claude code explore） | Runner + Task 容器（claude-agent-sdk） | API/Backend（dispatch + 回调续驱 + 持久化） | 深入代码验证须容器内 agent 跑；server 只 dispatch/收口 |
| 业务↔仓库关联 + 校验 verdict 持久化 | Database（新模型，INV-6 经 service） | API/Backend（service 写收口） | 真相源是 DB；写入收口单一 service |
| 观测（call_source / RetrievalTrace / 归因） | API/Backend（`interactions.ledger` + `structlog`） | — | 横切，best-effort 不反噬 |

## Standard Stack

### Core（全部既有，无新外部依赖）

| 资产 | 路径 / 符号 | 用途 | 为何是标准 |
|------|------------|------|-----------|
| COMBINED 选仓 | `server/codegraph/services/repo_router_v2.py::RepoRouterV2.route(query, *, top_k, repository_ids, use_llm)` → `RepoRouteResultV2{candidates: list[RepoRouteCandidateV2], router_version, auto_selected}` | 语义相关度（Stage0 节点级 dense+sparse hybrid RRF）+ 活跃度 facet 降权（`DEPRECATED_PENALTY=0.5`）+ Stage1 LLM 树推理（high/medium/low confidence） | 已是 v0.7/v0.8 唯一选仓器；锁定决策的 COMBINED ranking 已内置 |
| v1 选仓降级 | `server/codegraph/services/repo_router.py::RepoRouter.route` | `repo_index_nodes` 无命中时回落（repo_summaries 单点检索） | RepoRouterV2 自带降级链，不另写 |
| 路由编排 adapter 范式 | `server/services/plan_orchestration/repo_router_adapter.py::RepoRouterV2Adapter` | 取数 + 候选范围解析（include → space.repositories → 全库）+ 结果映射的薄编排示例 | 候选范围解析逻辑可直接复用 |
| 活跃度/技术栈/关键程度 facet | `server/repositories/facet_service.py::FacetService.refresh_fact_facets` + `DIM_ACTIVITY="活跃度"`（`活跃开发/维护中/低频/疑似废弃`） | 「仓库活跃度」事实分面，随索引刷新写 `Repository.facets`，零 LLM | RepoRouterV2 Stage0 已读 facets["活跃度"] |
| 「功能梳理」能力树 | Qdrant collection `repo_index_nodes`（`codegraph/services/repo_index_tree.py::COLLECTION_NAME`），payload 含 `node_path/summary/sub_project/facets` | RepoRouterV2 Stage0 检索面 = 模块/能力节点级 | 「功能梳理」即能力树节点摘要 |
| feature list 结构化（Phase 87 上游） | `server/initiatives/services/feature_list_extractor.py::FeatureListExtractor.{normalize_sources, extract_structure}`；`server/initiatives/services/board_split_service.py::BoardSplitService.propose_split` → `{modules, features_flat, degraded, chunk_count}` | Phase 88 选仓 query 语料来源（feature 名/描述/模块） | 单一编排收口，已埋 `call_source="board_split"` |
| 卡片 HITL 节点模板 | `server/workflows/nodes/integrations/board_split_review.py::BoardSplitReviewNode`（`is_blocking=True`, `waiting_event`, `WorkflowEventSubscription`） | 拉群 + 流式发卡 + 挂起等回调的逐字模板 | Phase 87 已验证的 HITL 范式 |
| CardKit 卡片构建 | `server/feishu/cards/board_split_card.py::{build_board_split_card, build_board_split_done_card, render_proposal_markdown}` | schema 2.0 流式卡 + 按钮 + 表单输入框 + action_value 仅携路由 ID（不携正文，脱敏） | Phase 87 模板 |
| 卡片回调状态机 | `server/feishu/callbacks/board_split_callback.py::handle_board_split_action`（`@register_card_callback("board_split_")` + `_run_in_thread` + `bind_task_context` + `approve_node`/保持 waiting） | 多分支动作（确认/重拆）后台处理 + 工作流恢复/续等 | Phase 87 模板 |
| CardKit 客户端 | `server/services/feishu_im.py::FeishuIMClient.{create_card_entity, send_card_entity, stream_card_content, settle_card_stream, send_card}`；`FeishuIMService.create(space)` / `create_feishu_im_client_for_project(space)` | 流式卡建实体/发卡/灌内容/封口（sequence 严格递增） | v0.11 Phase 58 CardKit 封装 |
| 群解析/建群 | `server/initiatives/services/project_service.py::ProjectService.resolve_or_create_group(*, project, member_ids, initiated_by_user_id)` → `chat_id` | 复用/建项目群 + bot 入群（INV-6） | v0.15/87 已用 |
| AI 会话工具范式 | `server/agents/tools/board_split_tools.py::split_feature_list_to_boards`（`@tool` + `ToolResult`） | Agent 自处理入口模板（与 workflow 节点共用 service） | Phase 87 范式 |
| 逐仓容器 explore 深验 | `server/services/plan_orchestration/research_adapter.py::ResearchDispatchAdapter`（per-repo SubAgentSession + `env_FRIDAY_TASK_MODE="explore"` + `node_execution_id` 回调续驱 + 单仓 fail-soft + runner offline 降级） | 「逐仓 claude code task 深入代码验证、只读、续驱、隔离」的现成实现 | v0.7 Phase 39 已交付 |
| 容器只读 explore 模式 | `task/core/runner.py::TaskRunner._run_explore_mode`（`ClaudeRunner.run_explore_mode` + `_check_workspace_clean` 强制无改动） | 容器侧只读深度代码分析、产文本、不写 git | v0.x 已有 task_mode |
| 容器 dispatch | `server/runners/dispatcher.py::DispatchTask` + `get_dispatcher().dispatch(task)`；`SubAgentSession`（`server/subagent/models.py`，`TaskType.{CODING, REPO_SUMMARY}`） | 派发容器任务 | v0.8 多仓 dispatch |
| 容器回调 → 节点续驱 | `server/subagent/api/callbacks.py`（completed/failed/question/heartbeat）→ `node_execution_id` 关联 → `_schedule_workflow_resume` 重入挂起 `WAITING_EVENT` 节点 | 容器完成后自动续驱工作流 | v0.8/v0.12 已接通 |
| durable 任务 | `server/resumable/service.py::{submit_resumable, wrap_resumable, register_running, heartbeat}`；`ResumableTask` | 后台编排登记/心跳/续跑（多副本 exactly-once） | v0.12 durable 底座 |
| 后台任务归因 | `server/common/log_context.py::bind_task_context(user_id, source, component)`；`initiated_by_user_id` 透传 | worker 入口 re-bind 触发用户（CTX-02 强制） | v0.14 可观测地基 |
| 召回留痕 | `server/interactions/ledger.py::arecord_retrieval_trace(run=None, *, kind, payload, user_id, conversation_id, source)`（payload 经 `redact_for_ledger`） | 新增召回写 `RetrievalTrace`（MCP+对话两链） | v0.14 强制 |
| LLM 用量留痕 | `server/interactions/ledger.py::arecord_llm_usage(call_source=..., ...)` + `parse_upstream_status` | 新增 LLM 调用上报 token/TTFT/上游错误码 | v0.14 强制 |
| call_source 声明 | `server/agents/call_source.py::{CallSource, use_call_source, CallSource.normalize}` | LLM 调用来源枚举（受控）+ contextvar 声明 | v0.14 强制 |
| 脱敏 | `server/common/logging.py::{redact_secrets_in_text}`（异常/上游文本）；`redact_for_ledger`（入库） | 凭证/正文脱敏不可绕过 | v0.14 强制 |
| 项目上下文召回（可选增强） | `server/services/project_context_packer.py::pack_project_context(project, user, *, query, conversation_id)` → `PackedContext`（fail-closed by visibility，已写 RetrievalTrace） | 给容器/LLM 注入项目上下文 | v0.15 RECALL |
| 持久化镜像模型 | `server/delivery/models/research_task.py::{RepoResearchTask, RepoResearchTaskStatus(pending/running/done/failed/stale), PartialPlan}` | per-repo 任务 + 产物的字段/状态机/INV-6 范式可镜像为 verify 任务 + verdict | v0.7 Phase 39 范式 |
| 项目↔仓库链候选 | `server/initiatives/models/project_branch.py::ProjectBranch`（project↔repository↔branch，INV-6 经 `ProjectBranchService`）；`projects.Space.repositories`（候选范围） | 现有项目↔仓库关系（分支级）；**无**业务级「项目↔仓库关联」模型 → 本期新增 | 见 §New Persistence |

### Supporting

| 资产 | 路径 / 符号 | 何时用 |
|------|------------|--------|
| WorkItem 关联 | `server/initiatives/services/project_service.py::ProjectService.attach_work_item(*, project_id, work_item, provenance, actor, initiated_by_user_id)` | 若需把确认仓库挂到 work_item/project 跟踪 |
| Provenance 枚举 | `server/initiatives/models::LinkProvenance`（含 `BOARD_DERIVED` 等） | 关联来源标注 |
| 节点注册 | `server/workflows/nodes/registry.py::register_node`（放 `workflows/nodes/integrations/` 自动发现） | 新节点注册 |
| 节点基类 | `server/workflows/nodes/base.py::{BaseNode, NodeResult, NodePort, NodeCategory, PortType, ExecutionContext}` | 新节点契约 |
| id list 解析 | `server/workflows/nodes/integrations/feishu_chat.py::_parse_id_list` | member_ids 三形态解析 |
| git 凭证 | `server/services/git_credentials.py::aresolve_git_token(repo)` | 容器 dispatch token 注入（per-repo→host fallback） |
| claude code 运行时 | `server/services/provider_config.py::aget_claude_code_runtime_config()` | 容器 api_key/base_url/模型档 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 新建 verify 容器 dispatch | 直接复用 `ResearchDispatchAdapter` | 语义不同（research 产 PartialPlan vs verify 产 verdict），prompt/verdict schema 需改；建议**复刻其结构**而非直接调用，避免污染 v0.7 编排状态机 |
| `RepoRouterV2`（COMBINED 内置） | 自写打分公式 | 违反「不重造」；RepoRouterV2 已含语义+活跃度+LLM，直接用 + 补埋点即可 |
| 新 `SubAgentSession.TaskType.REPO_VERIFY` | 复用 `TaskType.REPO_SUMMARY`/`PLAN` + last_output 标 source | 建议新增枚举值（清晰、便于 `observability_views` 按 task_type 区分），代价是一个 migration + task 容器侧无需改（explore 模式与 task_type 正交） |

**Installation:** 无新外部依赖（纯复用 + 新 Django 模型/服务/节点/卡片）。

## Package Legitimacy Audit

> 本阶段**不安装任何外部包**——全部基于既有 server/ 代码与已锁定的技术栈（Django/adrf/channels/structlog/qdrant-client/claude-agent-sdk 等均已在 `server/pyproject.toml`）。无 npm/PyPI 新增。审计 N/A。

| Package | Registry | Disposition |
|---------|----------|-------------|
| （无新增） | — | N/A — 纯内部复用 |

## Architecture Patterns

### System Architecture Diagram

```text
                  ┌─────────────────────────────────────────────────────────┐
 Phase 87 输出 ──▶ │ RepoAssociationService.propose (INV-6 单一编排收口)        │
 {modules,         │  1) 取 feature 语料 (features_flat → query 文本)           │
  features_flat}   │  2) RepoRouterV2.route(query, repository_ids=space仓)      │
                  │     = 语义hybrid + 活跃度facet降权 + LLM树推理 (COMBINED)  │
                  │     [补埋点: use_call_source(AUX_REPO_ROUTER)+RetrievalTrace]│
                  │  3) (可选多轮) Agent 自处理 / RAG 多轮细化候选             │
                  └───────────────┬─────────────────────────────────────────┘
                                  │ candidates[{repo_id,confidence,score,reason}]
                                  ▼
        ┌──────────────────────────────────────────────────────────────┐
        │ RepoAssociationNode (workflow, is_blocking, waiting_event)     │
        │  resolve_or_create_group → CardKit 流式候选卡 → 订阅超时兜底    │
        └───────────────┬──────────────────────────────────────────────┘
                        │  飞书群卡片 (CardKit schema 2.0)
                        ▼
        ┌──────────────────────────────────────────────────────────────┐
        │ 用户在群里多轮交互 (card callback, _run_in_thread+bind_ctx)     │
        │  ├─ "补充/澄清" → 带 extra_instruction 重算候选 → 重发卡(保持waiting)│
        │  └─ "确认这些仓库" → 进入逐仓深验阶段                            │
        └───────────────┬──────────────────────────────────────────────┘
                        │ 确认仓库列表 (持久化 RepoAssociation: status=confirmed)
                        ▼
        ┌──────────────────────────────────────────────────────────────┐
        │ 逐仓 fan-out claude code 容器 (复刻 ResearchDispatchAdapter)    │
        │  per repo: SubAgentSession(REPO_VERIFY) + env_FRIDAY_TASK_MODE  │
        │            ="explore" (只读) + node_execution_id 关联           │
        │  durable 登记(submit_resumable) + initiated_by_user_id 透传     │
        │  单仓 try/except 隔离 (mark_failed + 不波及其他仓 = fail-soft)   │
        └───────────────┬──────────────────────────────────────────────┘
                        │ 容器内 explore: 读代码验证业务适配 → 产 verdict 文本
                        ▼
        ┌──────────────────────────────────────────────────────────────┐
        │ 容器回调 subagent/api/callbacks → node_execution_id            │
        │   → _schedule_workflow_resume 重入挂起节点                     │
        │   → 聚合各仓 verdict (fit / mismatch / unknown) 落 RepoVerifyTask│
        └───────────────┬──────────────────────────────────────────────┘
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
   有 mismatch (回退)        全部 fit / 用户接受
   → 发"发现不符"卡片        → 最终确认卡 (build_done_card)
   → 回到确认阶段(waiting)    → RepoAssociation status=verified
                              → 输出确认仓库 → Phase 89 输入
```

### Component Responsibilities

| 组件 | 职责 | 落点（新建/复用） |
|------|------|------------------|
| `RepoAssociationService` | 单一编排收口（INV-6）：选仓提案 / 重算 / 确认落库 / 派验 / 聚合 verdict / 终态 | 新建 `server/initiatives/services/repo_association_service.py` |
| `RepoAssociationNode` | workflow 节点：拉群 + 发候选卡 + `waiting_event` + 订阅超时 | 新建 `server/workflows/nodes/integrations/repo_association.py` |
| `associate_repos` 工具 | AI 会话入口（与节点共用 service） | 新建 `server/agents/tools/repo_association_tools.py` |
| 卡片构建 | 候选卡 / 验证进行中卡 / 不符回退卡 / 最终确认卡 | 新建 `server/feishu/cards/repo_association_card.py` |
| 卡片回调 | 确认 / 澄清重算 / 接受 mismatch / 重确认（状态机） | 新建 `server/feishu/callbacks/repo_association_callback.py` |
| verify dispatch | per-repo explore 容器 fan-out + 续驱 + 隔离 | 新建 `server/initiatives/services/repo_verify_dispatch.py`（复刻 `ResearchDispatchAdapter` 结构） |
| 持久化 | `RepoAssociation` + `RepoVerifyTask` | 新建 `server/initiatives/models/`（INV-6 经 service） |

### Pattern 1: 卡片 HITL 多轮状态机（waiting_event + callback）

**What:** workflow 节点首发返回 `waiting_event` 并把交互状态持久化进 `NodeExecution.output_data`（轮次/候选/来源/chat_id）；用户卡片动作经 `@register_card_callback(prefix)` 路由到回调，回调 `_run_in_thread` + `bind_task_context` 后台处理，按动作分支：澄清类**保持 waiting**（更新 output_data + 重发卡），确认/终态类调 `WorkflowEngine().approve_node` 恢复。

**When to use:** Phase 88 的 clarify→confirm→verify→rollback→final-confirm 全程。

**Example（照搬 Phase 87，`server/feishu/callbacks/board_split_callback.py`）:**

```python
# Source: server/feishu/callbacks/board_split_callback.py
@register_card_callback("repo_assoc_")  # Phase 88 改前缀
def handle_repo_assoc_action(callback: CardCallback) -> dict[str, Any] | None:
    data = _extract_callback_data(callback)
    action = data.get("action", "")
    execution_id, node_id = data.get("execution_id", ""), data.get("node_id", "")
    if action == "repo_assoc_confirm":
        _run_in_thread(_do_confirm_and_verify_async(...))   # 派逐仓深验，保持 waiting
        return _ack_card("已收到，正在逐仓深入校验…")
    if action == "repo_assoc_refine":
        _run_in_thread(_do_refine_async(...))               # 重算候选，保持 waiting
        return _ack_card("已收到，正在按你的要求重新评估候选仓库…")
    ...
```

### Pattern 2: per-repo explore 容器 fan-out + 续驱 + fail-soft（REPO-02 核心）

**What:** 对每个确认仓库建独立 `SubAgentSession`，dispatch `DispatchTask`（`env_FRIDAY_TASK_MODE="explore"` 只读），关联 `node_execution_id` 使容器回调经 `_schedule_workflow_resume` 重入挂起节点；单仓异常 `try/except` 隔离（`mark_failed` + 不上抛）。

**Example（复刻 `server/services/plan_orchestration/research_adapter.py::_dispatch_deep_task` + `_build_dispatch_metadata`）:**

```python
# Source: server/services/plan_orchestration/research_adapter.py (复刻为 verify 语义)
metadata = {
    "repository_id": str(repo.id),
    "env_FRIDAY_TASK_MODE": "explore",          # 双层 git 写拦截 (Shell wrapper)
    "env_FRIDAY_TASK_TASK_MODE": "explore",     # pydantic-settings → TaskConfig.task_mode
}
cc = await aget_claude_code_runtime_config()
metadata["env_FRIDAY_TASK_CLAUDE_API_KEY"] = cc["api_key"]; ...
token = await aresolve_git_token(repo)          # per-repo → host fallback
if token:
    metadata["env_FRIDAY_TASK_GIT_ACCESS_TOKEN"] = token; ...
dispatch_task = DispatchTask(
    task_id=session_id, task_type="repo_verify", tags=[], image="",
    repo_url=repo_url, branch=repo.default_branch or "main", target_branch="",
    prompt=verify_prompt,                        # 注入 feature 适配性校验要求 + JSON verdict schema
    timeout=30 * 60, node_execution_id=self.node_execution_id or "",
    session_id=session_id, metadata=metadata,
)
await get_dispatcher().dispatch(dispatch_task)
# 单仓失败隔离：try/except → research_service.mark_failed(task, {...}) → 继续其他仓
```

### Pattern 3: COMBINED 选仓（复用 RepoRouterV2，补埋点）

**What:** `RepoRouterV2.route(query, top_k, repository_ids, use_llm=True)` 直接给出语义+活跃度+LLM 的综合候选；Phase 88 用 feature list（`features_flat` 的 name/description/module 拼成 query），`repository_ids` 限定为项目/空间仓（复用 `RepoRouterV2Adapter._resolve_repository_ids` 思路）。**多轮 RAG** = 用户澄清后把 `extra_instruction` 并进 query 重 route。

**补埋点（必做，当前缺失）:**

```python
# 当前 repo_router_v2.py 未埋点。Phase 88 在调用处包裹：
from agents.call_source import CallSource, use_call_source
with use_call_source(CallSource.AUX_REPO_ROUTER):   # 枚举已存在，未被使用
    result = await RepoRouterV2.route(query, repository_ids=repo_ids)
# 召回留痕（routing 链）:
await arecord_retrieval_trace(
    kind="routing",
    payload={"query": query, "candidates": [c.to_dict() for c in result.candidates]},
    user_id=initiated_by_user_id, conversation_id=str(...), source="repo_association",
)  # payload 入库经 redact_for_ledger（ledger 内部已做）
```

### Recommended Project Structure（新增文件）

```text
server/initiatives/
├── models/
│   ├── repo_association.py        # 新：RepoAssociation (业务↔仓库关联 + 状态)
│   └── repo_verify_task.py        # 新：RepoVerifyTask (per-repo 校验任务 + verdict)
├── services/
│   ├── repo_association_service.py # 新：单一编排收口 (INV-6)
│   └── repo_verify_dispatch.py     # 新：per-repo explore 容器 fan-out (复刻 ResearchDispatchAdapter)
├── migrations/00XX_repo_association.py  # 新模型 migration (纯 CreateModel)
server/workflows/nodes/integrations/
└── repo_association.py            # 新：RepoAssociationNode (waiting_event HITL)
server/agents/tools/
└── repo_association_tools.py      # 新：associate_repos (@tool, 与节点共用 service)
server/feishu/cards/
└── repo_association_card.py       # 新：候选/进行中/回退/最终 卡片
server/feishu/callbacks/
└── repo_association_callback.py   # 新：@register_card_callback("repo_assoc_")
```

### Anti-Patterns to Avoid

- **重写打分公式**：RepoRouterV2 已含 COMBINED（语义+活跃度+LLM），勿另起。
- **直接复用 v0.7 ResearchDispatchAdapter 实例**：会污染 `PlanSession` 编排状态机；应**复刻其结构**到 initiatives，verdict 语义独立。
- **容器深验用 coding/execute 模式**：会建分支/写 git；必须 `explore` 只读（`_check_workspace_clean` 兜底）。
- **整篇 diff / 大 payload 进卡片 action_value**：照 Phase 87，action_value 只携 `execution_id/node_id/round/action`，正文走 `output_data`/流式灌入。
- **同步 ORM 在 async 上下文裸用**：一律 `sync_to_async`（见 `_aresolve_project` 等范式）。
- **观测反噬主流程**：所有 `arecord_*` / 发卡 / emit 都 `try/except` best-effort。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 语义+活跃度综合选仓 | 自写 embedding+打分 | `RepoRouterV2.route` | 已含 Stage0 hybrid + 活跃度降权 + Stage1 LLM + 降级链 |
| 仓库活跃度判定 | 自查 git log | `FacetService` / `Repository.facets["活跃度"]` | 随索引刷新，四档已定义 |
| 卡片流式下发 | 自拼 httpx | `FeishuIMClient.{create_card_entity,...,settle_card_stream}` | v0.11 CardKit 封装，sequence/降级已处理 |
| HITL 挂起/恢复 | 自写轮询/状态 | workflow `waiting_event` + `WorkflowEventSubscription` + `approve_node` | Phase 87 验证范式 |
| per-repo 容器派发+续驱 | 自写 dispatch+poll | 复刻 `ResearchDispatchAdapter` + `node_execution_id` → `_schedule_workflow_resume` | v0.7/v0.8/v0.12 已接通回调续驱 |
| 容器只读深度分析 | 自定义 task 模式 | `env_FRIDAY_TASK_MODE="explore"`（`task/core/runner.py::_run_explore_mode`） | 已有只读模式 + workspace clean 兜底 |
| durable 后台编排 | 自写心跳/租约 | `resumable.service.submit_resumable` | v0.12 多副本 exactly-once |
| 召回/LLM 留痕 | 自写表 | `interactions.ledger.arecord_retrieval_trace / arecord_llm_usage` | 已脱敏 + best-effort |
| 触发用户归因 | 手动透参 | `bind_task_context(user_id=..., source=...)` + `initiated_by_user_id` | CTX-02 标准 |
| 群解析/建群 | 自调飞书 | `ProjectService.resolve_or_create_group` | INV-6 收口 |

**Key insight:** 本阶段 90% 是「拼装两个现成模板」（Phase 87 的卡片 HITL + ResearchDispatchAdapter 的 per-repo explore 容器），真正的净新增只有：① RepoRouterV2 补埋点；② 两个持久化模型；③ verify 语义的 prompt/verdict 解析。

## New Persistence（建议模型，plan-phase 细化字段）

> 现状缺口：**无业务级「项目↔仓库关联」模型**。`ProjectBranch` 是分支级、`ProjectRelation` 是项目↔项目、`Space.repositories` 是空间级仓库池。Phase 88 需要记录「某业务/项目 经本轮关联确认了哪些仓库 + 各仓校验 verdict」。

**`RepoAssociation`**（业务↔仓库关联 + 状态机，镜像 `RepoResearchTask` 的 INV-6 范式）：
- `project` FK（`initiatives.Project`）/ 可选 `work_item` FK（`delivery.WorkItem`）锚定业务；
- `repository` FK（`repositories.Repository`）；
- `status`：`proposed`（选仓提案）→ `confirmed`（用户确认）→ `verifying` → `verified` / `rejected`（mismatch 回退）；
- `score` float / `confidence` str / `routed_reason` text（来自 RepoRouterV2 候选）；
- `source` str（`router_v2` / `manual_added` / `manual_removed`）；
- `initiated_by_user_id` / 时间戳；
- 唯一约束 `(project, repository)`（或 `(work_item, repository)`）。

**`RepoVerifyTask`**（per-repo 容器校验任务 + verdict，**逐字镜像** `RepoResearchTask`/`PartialPlan`）：
- `association` FK（`RepoAssociation`）；`repository` FK；`subagent_session` FK（`SET_NULL`，dispatch 后回填）；
- `status`：`pending/running/done/failed/stale`（照 `RepoResearchTaskStatus`）；
- `attempt` int（单仓重试）；`error` JSON（结构化失败诊断）；
- `verdict` JSON：建议 schema `{fit: "fit"|"mismatch"|"unknown", confidence, summary, evidence_files[], mismatch_reasons[]}`（容器 explore 产出，server 解析）；
- 写入**只经** `RepoAssociationService`（INV-6，配 grep 守护 `test_repo_association_inv6_guard.py`，镜像 `test_research_inv6_guard.py`）。

**复用而非新建**：若 Phase 89 需把确认仓库转成分支绑定，走既有 `ProjectBranchService`（不在本期）。

## Observability Plan（强制，LOGGING-SPEC §4.1/§7）

| 项 | 动作 |
|----|------|
| **新 call_source** | 在 `server/agents/call_source.py::CallSource` 新增 `REPO_ASSOCIATION = "repo_association"`（Agent 自处理/候选细化的 LLM 调用）+ 在 LOGGING-SPEC §4.1 表登记；**并补用既有 `AUX_REPO_ROUTER`** 包裹 `RepoRouterV2.route` 调用（当前未用）。容器深验若走 SDK，沿用 `deep_analysis_container` 或新增 `repo_verify_container`（建议新增，便于 `observability_views` 区分）。 |
| **RetrievalTrace** | 选仓 route 后写 `arecord_retrieval_trace(kind="routing", payload={query, candidates})`；多轮 RAG 细化每轮各写一条。覆盖 AI 对话链；若经 MCP 工具入口亦写（两链）。 |
| **LLM 用量** | 候选细化/Agent 自处理的每次 `ainvoke` 经 `arecord_llm_usage(call_source=..., ttft_ms, prompt/completion_tokens, upstream_status_code)`（镜像 `FeatureListExtractor._record_usage`）。 |
| **initiated_by_user_id 透传** | 节点取 `WorkflowExecution.triggered_by_id`（缺 `system`）；回调取 `callback.user_open_id`；durable `submit_resumable` 的 payload 带 `initiated_by_user_id`；worker 入口 `bind_task_context`。容器 `SubAgentSession.last_output` 带触发用户。 |
| **结构化事件** | `repo_association_proposed`/`_confirmed`/`_verify_started`/`_verify_completed`/`_verify_failed`/`_rollback`（`category="caller"`, `component="initiatives"` 或新 `repo_association`, 带 `duration_ms`）；per-repo 容器步骤用 `category="sampling"`。 |
| **脱敏** | 容器 verdict 文本 / 异常 / 上游响应经 `redact_secrets_in_text`；入库 payload 经 `redact_for_ledger`。日志只记长度/计数/repo_id，不回显 feature 正文/token。 |
| **component 登记** | 建议新增 `component="repo_association"` 到 LOGGING-SPEC §5 组件清单（或复用 `initiatives`）。 |

## Common Pitfalls

### Pitfall 1: 容器深验用错模式导致写 git
**What goes wrong:** 用 `coding`/`execute` 模式跑「验证」→ 容器建工作分支、可能 commit/push。
**How to avoid:** 必须 `env_FRIDAY_TASK_MODE="explore"` + `env_FRIDAY_TASK_TASK_MODE="explore"`（双层拦截，见 `research_adapter._build_dispatch_metadata`）；容器侧 `_run_explore_mode` 有 `_check_workspace_clean` 兜底。
**Warning signs:** 验证后仓库出现新分支/提交。

### Pitfall 2: 容器回调不续驱挂起节点
**What goes wrong:** dispatch 的 `SubAgentSession` 未设 `node_execution_id` → 容器完成回调无法 `_schedule_workflow_resume`，节点永久 `waiting_event`。
**How to avoid:** 照 `ResearchDispatchAdapter`：`SubAgentSession.objects.acreate(node_execution_id=self.node_execution_id or None, ...)` 且 `DispatchTask(node_execution_id=...)`；节点 execute 时从 `context.node_execution.id` 取并透传给 dispatch service（mirror `AICodingNode`）。
**Warning signs:** 容器完成但卡片/工作流不前进。

### Pitfall 3: 单仓失败拖垮全部（违反 fail-soft）
**What goes wrong:** 某仓 clone 失败/容器异常上抛 → engine advance 通用 except 把整个流程标 fail。
**How to avoid:** 每仓 dispatch + 聚合 `try/except` 隔离（`mark_failed(task, {...})` + emit + continue），绝不上抛（见 `research_adapter` WR-02）；聚合时缺失仓 verdict 记 `unknown` 不阻断终态。

### Pitfall 4: 容器回调重入异常导致 5xx 风暴
**What goes wrong:** `_resume` 路径内异常上抛 → 容器回调 5xx → runner 重试 → 重复续驱。
**How to avoid:** resume/聚合段整体 fail-soft（mirror `AICodingNode._resume_wave`：`aadvance` 异常 swallow+warning，不回灌容器回调 5xx）。

### Pitfall 5: 跨轮 CardKit sequence 状态丢失
**What goes wrong:** 多轮重算复用同一 card_id 续灌，sequence 跨轮错乱。
**How to avoid:** 照 Phase 87 `board_split_callback._resend_streaming_card`——**每轮新建 card 实体**（create→send→stream→settle），流式失败降级普通 `send_card`。

### Pitfall 6: RepoRouterV2 候选范围未限定 → 全库噪声
**What goes wrong:** `repository_ids=None` 在全库检索，跨项目仓污染候选。
**How to avoid:** 复用 `RepoRouterV2Adapter._resolve_repository_ids` 思路——限定为 `Space.repositories` / 项目仓库范围。

### Pitfall 7: 观测未覆盖（RepoRouterV2 历史缺埋点）
**What goes wrong:** 沿用 RepoRouterV2 而不补 `call_source`/`RetrievalTrace` → 违反强制规范，code review 必拦。
**How to avoid:** 在调用处包 `use_call_source(AUX_REPO_ROUTER)` + 写 `RetrievalTrace`（见 Pattern 3）。

## Runtime State Inventory

> 非 rename/refactor 阶段，但涉及容器与 durable 任务，列关键运行态：

| Category | Items | Action |
|----------|-------|--------|
| Stored data | 新 `RepoAssociation`/`RepoVerifyTask` 表（DB canonical） | CreateModel migration（纯新增，无回填） |
| Live service config | 飞书卡片回调路由（`@register_card_callback("repo_assoc_")`） | 新增前缀，不与既有 `board_split_`/`chat_question` 冲突（前缀须唯一） |
| OS-registered state | 无 | None |
| Secrets/env vars | 容器 dispatch 注入 `env_FRIDAY_TASK_GIT_ACCESS_TOKEN`（经 `aresolve_git_token`，绝不入日志） | 复用既有解析器，token 不留痕 |
| Build artifacts | task 容器侧无需改（explore 模式已存在；若新增 `task_type="repo_verify"` 仅 server 端 SubAgentSession 枚举，容器按 task_mode 分流不读 task_type） | 确认 task 容器对未知 task_type 不报错（按 task_mode 走 explore） |

## Code Examples

### 节点 execute：拉群 + 发候选卡 + waiting_event（照 BoardSplitReviewNode）

```python
# Source: server/workflows/nodes/integrations/board_split_review.py (镜像)
async def execute(self, context: ExecutionContext) -> NodeResult:
    space = await _resolve_space(context)
    project = await _aresolve_project(space)
    initiated_by = self._resolve_initiator(context)          # triggered_by_id 或 "system"
    chat_id = await ProjectService().resolve_or_create_group(
        project=project, member_ids=member_ids, initiated_by_user_id=initiated_by)
    proposal = await RepoAssociationService().propose(
        space=space, feature_list=..., initiated_by_user_id=initiated_by)  # 内部 RepoRouterV2 + 埋点
    card = build_repo_assoc_card(proposal, execution_id=context.execution_id,
                                 node_id=context.node_id, round=1)
    await self._send_streaming_card(im_service, chat_id, card, proposal)
    await WorkflowEventSubscription.objects.acreate(
        workflow_execution=context.workflow_execution,
        node_execution=context.node_execution, event_type="RepoAssocCallback",
        timeout_at=timezone.now() + timedelta(minutes=60), timeout_action="fail")
    return NodeResult(status="waiting_event", output={
        "proposal": proposal, "chat_id": chat_id, "round": 1, "stage": "clarify"})
```

### 容器回调续驱（已接通，无需新写）

```text
容器 explore 完成 → POST /api/containers/callback/ (subagent/api/callbacks.py)
  → SubAgentSession.node_execution_id 非空
  → _schedule_workflow_resume → 节点重入 (status 仍 waiting_event)
  → RepoAssociationService.collect_verdicts() 聚合各 RepoVerifyTask.verdict
  → 有 mismatch → 发回退卡 (保持 waiting, stage="reconfirm")
  → 全 fit → 发最终确认卡 + RepoAssociation.status=verified → approve_node
```

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| v1 `RepoRouter`（repo_summaries 单点） | v2 `RepoRouterV2`（节点级 hybrid + LLM + 活跃度 facet） | 用 v2，v1 仅降级链 |
| 容器结果靠轮询 | `node_execution_id` → `_schedule_workflow_resume` 回调续驱 | 用回调续驱，勿轮询 |
| 后台任务无归因 | `bind_task_context` + `initiated_by_user_id`（v0.14 CTX-02） | 强制透传 |

**Deprecated/outdated:** 直接 patch `repo_router_v2` 调 LLM 而不经 `use_call_source` —— 现规范要求声明 call_source。

## Project Constraints (from .cursor/rules + AGENTS.md)

- **观测强制**（`.cursor/rules/observability-logging.mdc`）：新增 LLM 赋 `call_source`（§4.1 登记）+ 上报请求/token/TTFT/上游错误码；新增召回写 `RetrievalTrace`（MCP+对话两链）；事件 snake_case + `started/completed/failed` + `duration_ms` + `category`(caller/sampling) + `component`；后台任务带 `initiated_by_user_id`，worker 入口 re-bind；脱敏不可绕过（`redact_secrets_in_text`/`redact_for_ledger`）；观测 best-effort 不反噬。
- **INV-6 写入收口单一 service** + grep 守护（镜像 `test_research_inv6_guard.py`/`test_project_inv6_guard.py`）。
- **async ORM 走 `sync_to_async`**（adrf 异步，禁裸 lazy-FK）。
- **i18n 默认中文**：卡片/错误文案全中文。
- **复用 v0.15 地基，严禁重造**（initiatives/ProjectService/ProjectMember/context packer/feishu_im/CardKit/RepoRouterV2/resumable/dispatch）。
- **fail-soft 不阻断**：单仓校验失败不阻断其余；发卡/召回/容器任一失败不反噬主流程。
- **GSD 工作流**：直接改仓须走 GSD 命令（plan-phase/execute-phase）。

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest>=9.0.2` + `pytest-asyncio` + `pytest-django` + `respx`（httpx mock）+ `pytest-socket`（网络隔离）+ `factory-boy` |
| Config | `server/pyproject.toml`（`[tool.pytest]`），`server/tests/conftest.py`（adrf monkeypatch） |
| Quick run | `cd server && uv run pytest tests/initiatives/test_repo_association_service.py -x` |
| Full suite | `cd server && uv run pytest` |

### Phase Requirements → Test Map
| Req | Behavior | Type | Command | Exists? |
|-----|----------|------|---------|---------|
| REPO-01 | COMBINED 候选（语义+活跃度+LLM）+ 范围限定 + 埋点 | unit | `pytest tests/initiatives/test_repo_association_service.py::test_propose_combined -x` | ❌ Wave 0 |
| REPO-01 | 卡片多轮澄清重算保持 waiting | unit | `pytest tests/feishu/test_repo_association_callback.py::test_refine_keeps_waiting -x` | ❌ Wave 0 |
| REPO-01 | RepoRouterV2 调用包 `use_call_source(AUX_REPO_ROUTER)` + 写 RetrievalTrace | unit | `pytest tests/initiatives/test_repo_association_service.py::test_router_observability -x` | ❌ Wave 0 |
| REPO-02 | per-repo explore 容器 dispatch（mode=explore + node_execution_id + token 注入） | unit | `pytest tests/initiatives/test_repo_verify_dispatch.py::test_dispatch_explore -x` | ❌ Wave 0 |
| REPO-02 | 单仓失败 fail-soft 隔离不阻断其余 | unit | `pytest tests/initiatives/test_repo_verify_dispatch.py::test_per_repo_isolation -x` | ❌ Wave 0 |
| REPO-02 | mismatch → 回退重确认卡；全 fit → 最终确认 + approve_node | unit | `pytest tests/feishu/test_repo_association_callback.py::test_mismatch_rollback -x` | ❌ Wave 0 |
| REPO-01/02 | INV-6 写入收口守护（仅 service 写新模型） | guard | `pytest tests/initiatives/test_repo_association_inv6_guard.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** 该 plan 相关测试文件 `pytest tests/.../test_*.py -x`
- **Per wave merge:** `cd server && uv run pytest tests/initiatives tests/feishu tests/workflows`
- **Phase gate:** `cd server && uv run pytest` 全绿

### Wave 0 Gaps
- [ ] `tests/initiatives/test_repo_association_service.py` — REPO-01 选仓+埋点
- [ ] `tests/initiatives/test_repo_verify_dispatch.py` — REPO-02 容器派发+隔离
- [ ] `tests/feishu/test_repo_association_callback.py` — 卡片状态机（confirm/refine/mismatch/final）
- [ ] `tests/initiatives/test_repo_association_inv6_guard.py` — INV-6 grep 守护（镜像既有 guard）
- [ ] `tests/workflows/test_repo_association_node.py` — 节点 waiting_event + 订阅
- [ ] 真机容器 E2E（runner+Docker+真实 explore 校验）→ deferred 记 88-UAT.md（autonomous 链路以 respx/seam 覆盖，对齐 Phase 87/83）

## Security Domain

### Applicable ASVS Categories（security_enforcement=true, level 1）

| ASVS | Applies | Standard Control |
|------|---------|------------------|
| V4 Access Control | yes | 写仅成员（`ProjectMember`）；选仓召回经 `pack_project_context` visibility fail-closed；卡片回调归因 `resolve_feishu_user`/`user_open_id` |
| V5 Input Validation | yes | feature list 正文 / 用户卡片输入（refine_input）不作为执行指令裸拼进容器 prompt——经 server 权威 session 状态组织（mirror `_build_research_prompt`）；action_value 不携正文 |
| V6 Cryptography / Secrets | yes | git token 经 `aresolve_git_token` 注入容器 env，绝不入日志；凭证用既有 Fernet（不新增） |
| V7 Logging | yes | verdict/正文/异常脱敏（`redact_secrets_in_text`/`redact_for_ledger`）；payload label 不放用户原文 |
| V2 Auth / V3 Session | no | 复用既有 JWT/PAT/SubAgentSession，不新增认证面 |

### Known Threat Patterns

| Pattern | STRIDE | Mitigation |
|---------|--------|------------|
| 用户卡片输入注入容器执行指令 | Tampering | prompt 来自 server 权威 session 状态；用户输入仅作「拆分/筛选要求」附加约束，不构造执行命令（mirror `extract_structure` extra_instruction） |
| 非成员越权读项目仓库上下文 | Info Disclosure | `pack_project_context` 成员/visibility fail-closed；选仓候选范围限定 `Space.repositories` |
| 容器深验意外写远端仓库 | Tampering | `explore` 只读双层拦截 + workspace clean 兜底 |
| token / verdict 明文落日志 | Info Disclosure | 脱敏不可绕过；token 不入 dispatch 日志（仅 `has_git_token` 布尔） |
| 容器回调伪造续驱 | Spoofing | 沿用既有 `subagent/api/callbacks` 鉴权 + `node_execution_id`/`session_id` 服务端权威字段校验 |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | task 容器对未知 `DispatchTask.task_type`（如 `repo_verify`）不报错——按 `env_FRIDAY_TASK_MODE`/`task_mode` 分流到 explore，`task_type` 仅 server 端 SubAgentSession 语义 | New Persistence / Runtime State | 若容器按 task_type 强校验 → 需复用既有 task_type（如 `repo_summary`/`plan`）+ last_output 标 source。**plan-phase 前 live 验证**（已知 `task/core/config.py::normalize_legacy_task_mode` 仅特判 coding/coding_commit，其余走 task_mode，风险低） |
| A2 | RepoRouterV2 的 `repo_index_nodes`（功能梳理能力树）已对目标空间仓库建好索引；否则回落 v1 `repo_summaries` | Standard Stack / Pitfall 6 | 未索引则候选质量降级（仍可用 v1 fallback）；plan-phase 确认目标仓已索引 |
| A3 | 建议新增 `RepoAssociation`/`RepoVerifyTask` 模型而非复用现有——现状确无业务级项目↔仓库关联模型（仅 `ProjectBranch` 分支级 / `ProjectRelation` 项目级 / `Space.repositories` 空间级） | New Persistence | 若 plan-phase 决定复用 `ProjectBranch`（关联即建占位分支绑定）则 schema 不同；推荐独立模型（职责清晰） |
| A4 | 容器深验走 SDK，需新 `call_source`（建议 `repo_verify_container`）或复用 `deep_analysis_container` | Observability | 复用现值不报错但下钻区分度差；推荐新增并登记 §4.1 |
| A5 | COMBINED 权重/归一化沿用 RepoRouterV2 内置（score 已 `min(.,1.0)` 归一 + 活跃度 `*0.5` 降权），无需 Phase 88 额外加权 | Summary / Pattern 3 | 若产品要自定义权重，需在 service 层二次加权（Claude's Discretion，低风险） |

## Open Questions

1. **逐仓深验是否需要把 feature 子集精准映射到单仓？**
   - 已知：候选含 `matched_node_paths`/`sub_project`；verify prompt 可注入「本仓应承接的 feature 列表」。
   - 不清：feature→repo 的精确分配是 Phase 88 还是 Phase 89（方案深化）职责。
   - 推荐：Phase 88 只产「该仓是否适配 + 适配哪些 feature（粗）」verdict，精确分配留 Phase 89。

2. **关联确认输出给 Phase 89 的契约形态？**
   - 推荐：`RepoAssociation`（status=verified）列表 + 每仓 verdict，Phase 89 `PlanSession.decomposition.include_repos` 直接消费（对齐 `RepoRouterV2Adapter._resolve_repository_ids` 的 `include` 优先级）。

3. **多轮澄清的「Agent 自处理」深度？**
   - 已知：可在 service 内跑一轮 LLM 把用户澄清 + 候选合成更优候选（新 `call_source="repo_association"`）。
   - 推荐：首版 = RepoRouterV2 重 route（query 并入 extra_instruction）；Agent 自处理作可选增强（Claude's Discretion）。

## Environment Availability

| Dependency | Required By | Available | Fallback |
|------------|------------|-----------|----------|
| 在线 Runner + Docker | REPO-02 容器深验 | 运行期需 | 无 runner → 降级（mirror `research_adapter` runner_offline：跳过容器深验，仓库标 `unknown` 仍可最终确认），不阻断 |
| Qdrant（`repo_index_nodes`/`repo_summaries`） | REPO-01 选仓 | 索引完成需 | 无命中 → RepoRouterV2 回落 v1 |
| Provider 凭证（LLM） | Stage1 LLM 推理 / Agent 自处理 | 需 | 无 → RepoRouterV2 降级 Stage0 纯检索（`v2_stage0_only`） |
| 飞书应用（群/CardKit） | 卡片 HITL | 需真实租户 | 流式失败降级普通 send_card；真机 UAT deferred |

> 单元/集成测试经 respx + seam（`build_chat_model`/dispatcher/feishu client mock）覆盖，无需真实外部系统（对齐 Phase 83/87）。

## Sources

### Primary (HIGH confidence) — 真实代码勘察
- `server/codegraph/services/repo_router_v2.py` / `repo_router.py` — COMBINED 选仓
- `server/services/plan_orchestration/research_adapter.py` / `repo_router_adapter.py` — per-repo explore 容器 fan-out + 候选范围
- `server/workflows/nodes/integrations/board_split_review.py` / `board_split.py` — HITL 节点模板
- `server/feishu/cards/board_split_card.py` / `server/feishu/callbacks/board_split_callback.py` — CardKit + 回调状态机
- `server/initiatives/services/board_split_service.py` / `feature_list_extractor.py` — Phase 87 上游输出 + LLM 埋点范式
- `server/agents/call_source.py` — call_source 枚举（`AUX_REPO_ROUTER` 已存在未用）
- `server/interactions/ledger.py` — `arecord_retrieval_trace` / `arecord_llm_usage`
- `server/repositories/facet_service.py` — 活跃度 facet
- `server/chat/coding_session_service.py` — v0.8 dispatch metadata（token/cwd/上下文注入）
- `server/resumable/service.py` — durable
- `server/subagent/api/callbacks.py` / `models.py` — 容器回调续驱 + SubAgentSession TaskType
- `task/core/runner.py` / `config.py` — explore 只读模式
- `server/delivery/models/research_task.py` — RepoResearchTask/PartialPlan 持久化镜像
- `server/initiatives/models/{project,project_branch,relation}.py` — 现有模型缺口分析
- `.cursor/rules/observability-logging.mdc` / `.planning/observability/LOGGING-SPEC.md` — 观测强制
- `.planning/phases/88-repo-association/88-CONTEXT.md`、`REQUIREMENTS.md`、`ROADMAP.md`、`project-workspace/MILESTONE-PROPOSAL.md`、`STATE.md`

### Secondary (MEDIUM)
- `.planning/phases/87-board-split-card/*-SUMMARY.md` — Phase 87 落地决策（间接）

### Tertiary (LOW)
- 无（全部一手代码）

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 全部一手代码确认存在且签名核对
- Architecture (HITL + per-repo explore 容器): HIGH — Phase 87 + ResearchDispatchAdapter 是逐字可复刻模板
- Pitfalls: HIGH — 来自既有代码注释中的真实踩坑（fail-soft/5xx/sequence/explore 拦截）
- New persistence: MEDIUM — 缺口确认，字段建议待 plan-phase 细化
- 容器 task_type 行为(A1): MEDIUM — 建议 plan-phase live 验证

**Research date:** 2026-06-27
**Valid until:** 2026-07-27（内部代码稳定，30 天）
