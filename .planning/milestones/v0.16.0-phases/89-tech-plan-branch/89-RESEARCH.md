# Phase 89: 技术方案深化 + 建分支绑项目（Tech Plan + Branch）- Research

**Researched:** 2026-06-27
**Domain:** 复用 v0.7 PlanOrchestration / v0.8 git·branch·resume / 85 ProjectBranch / 86 SessionStore / 83 RESEARCH 同步 / v0.11 CardKit / v0.12 durable，编排「消费 88 确认仓 → per-repo+overall 方案深化（canonical + RESEARCH 镜像）→ 修订回路卡片 → 容器 5min 挂起/resume → 按方案建分支推送绑项目」交付收尾（PLAN-01~04）
**Confidence:** HIGH（全部基于真实代码勘察，无新外部依赖）

<user_constraints>
## User Constraints (from 89-CONTEXT.md，LOCKED — 研究只围绕这些)

1. **PLAN-01 方案载体**：复用 v0.7 `TechnicalPlan`/`PlanVersion`（canonical 唯一事实源）+ 镜像一份进项目 RESEARCH（经 Phase 83 同步引擎双向镜像飞书）。per-repo（负责事项/代码预改动/影响业务模块/预计 e2e·单测+覆盖项/风险/feature list 不清处/与现功能冲突）+ overall 整体方案 + 跨仓上下文；卡片多轮校验/澄清；消费 Phase 88 `get_verified_associations`。
2. **PLAN-02 修订回路**：执行中发现要改/增/删仓库 → 「调研问题发现」卡片 → 更新方案 / 创建补充修订（新 PlanVersion supersedes）+ 同步改仓库关联（多轮，优雅处理）。
3. **PLAN-03 容器 5min 挂起/resume**：单仓任务遇阻等待用户 → 5min 无回复 → 挂起/暂存容器；用户卡片回复 → resume（session 持久化复用 Phase 86 `SessionStore`→Redis + v0.8 callback resume + v0.12 durable）续到终态。session 找不到 → 用应用态（方案+用户回复）重灌新 session（官方推荐兜底）。
4. **PLAN-04 建分支绑项目**：方案确认后逐仓建分支并推送 + 绑 仓库↔分支↔项目（写 `ProjectBranch`，经 `ProjectBranchService.bind(source=plan)`，Phase 85 seam）。分支名 **固定格式**：`{type}/{yymmdd}.m-{项目跟踪id}.{项目名}[-{版本号}]`（type=conventional commits，yymmdd 日期，项目跟踪 id=飞书 work_item id，项目名=项目跟踪看板名一致，版本号有则填）。示例 `feat/260610.m-123456770019.高三提分专项-v1.0`。AI 生成分支名 + 用户卡片确认，回接 IDE 闭环。
5. **观测强制**：新 LLM（方案）赋 `call_source`（登记 LOGGING-SPEC §4.1）；脱敏；`initiated_by_user_id`；写入经 service（INV-6）。
6. **不重造**：复用 v0.7 PlanOrchestration + v0.8 git/branch + 85 ProjectBranch + 86 SessionStore + v0.11 CardKit + v0.12 durable。

### Claude's Discretion
- per-repo 方案七要素 schema 字段名 / overall 段落组织；
- 「调研问题发现」LLM 是否新增 vs 复用 clarify；
- 容器挂起的 5min 计时载体（durable scheduled vs apscheduler）、挂起状态枚举命名；
- 分支名生成 LLM prompt 结构、本地 git 建分支推送实现（复用 `CreateBranchNode` 逻辑 vs 抽 service）。

### Deferred Ideas (OUT OF SCOPE)
- None — 讨论保持在 phase scope 内。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PLAN-01 | per-repo + overall 技术方案——七要素 + 跨仓上下文 + 卡片多轮校验澄清 | 复用 v0.7 `PlanOrchestrationEngine`（`start_orchestration` + `build_orchestration_engine` + `adrive_plan_session_to_pause_or_terminal`）：route→recall→research(per-repo explore 容器产 `PartialPlan`)→merge(`ArchitectMergeAdapter`→`MergedPlan`→canonical `TechnicalPlan`/`PlanVersion`)。Phase 89 把 `include_repos` 锚定为 88 `get_verified_associations` 输出；扩 per-repo 深化 prompt/merge schema 产七要素；卡片多轮 = 复用既有 `ClarifyAdapter` clarification HITL + Phase 87/88 CardKit 流式卡范式。RESEARCH 镜像 = `ProjectDocService.append_research_note`（触发 83 push 飞书）。 |
| PLAN-02 | 方案修订回路——「调研问题发现」卡片 → 更新方案/补充修订 + 同步改仓库关联 | 补充修订 = `TechnicalPlanService` 加新 `PlanVersion`（`supersedes` self FK 已建）；改仓库关联 = `RepoAssociationService`（88，写收口 INV-6）；卡片状态机逐字镜像 Phase 87/88 `@register_card_callback` + `_run_in_thread` + `bind_task_context` + 保持/恢复 waiting。 |
| PLAN-03 | 容器 5min 无回复挂起/resume | 容器问答经 `subagent/api/callbacks.py` question → 飞书卡片；resume env 经 `chat/sdk_resume.py::build_resume_dispatch_env`（取 `SessionStore` Redis 镜像→DB fallback + cwd 一致校验）+ v0.8 callback resume + v0.12 durable 定时挂起。session 找不到 → 应用态重灌（`SessionStore.load` 返回 None 即走兜底）。 |
| PLAN-04 | 方案确认后逐仓建分支推送 + 绑项目（固定格式分支名 + AI 生成 + 卡片确认） | 建分支推送 = 复用 `CreateBranchNode` 的 server-local git（`DATA_DIR/repos/{repo_id}` fetch/checkout/create/push）+ `aresolve_git_token` 注入；绑定 = `ProjectBranchService.bind(source=BranchSource.PLAN)`（85 seam 已就绪）；分支名 = 新 LLM 生成 + 固定格式校验 + 卡片确认。 |
</phase_requirements>

## Summary

Phase 89 是 v0.16.0 交付流水线的**收尾编排阶段**，与 Phase 88 同构——90% 是把已交付子系统串起来，净新增极少：

1. **方案深化（PLAN-01）**：v0.7 编排引擎**已实现** route→recall→per-repo research(explore 容器)→merge→canonical `TechnicalPlan`/`PlanVersion` 全链路（`server/services/plan_orchestration/`）。Phase 89 只需：① `include_repos` 喂入 88 `get_verified_associations`（已是约定契约，输出 `repository_id` 对齐 `RepoRouterV2Adapter` include 优先级）；② 把 per-repo research prompt + `ArchitectMergeAdapter` merge schema 扩成七要素（负责事项/代码预改动/影响业务模块/e2e·单测+覆盖/风险/feature 不清处/与现功能冲突）；③ 终态 canonical 方案文本镜像进项目 RESEARCH（`ProjectDocService.append_research_note` → 触发 83 双向同步）。卡片多轮校验复用既有 `ClarifyAdapter` clarification HITL。

2. **修订回路（PLAN-02）**：`PlanVersion.supersedes` self FK + `TechnicalPlanService` 加版本能力**已存在**；改仓库关联走 88 `RepoAssociationService`（写收口）。净新增 = 「调研问题发现」卡片 + 回调 FSM（镜像 Phase 87/88）。

3. **容器挂起/resume（PLAN-03）**：跨容器 resume 地基**全部就绪**——`SessionStore`（86，Redis 镜像 + DB fallback + cwd 一致校验）+ `build_resume_dispatch_env`（分片下发 transcript）+ v0.8 callback resume + v0.12 durable。净新增 = ① 容器问答触发 5min 定时（durable scheduled task / apscheduler）；② 超时 → 停容器（`dispatcher.cancel`）+ 标挂起态；③ 用户回复 → re-dispatch 携 resume env 续驱；④ session miss → 应用态重灌（`SessionStore.load`→None 即走兜底）。

4. **建分支绑项目（PLAN-04）**：`CreateBranchNode` server-local git 建分支推送逻辑**已存在**（`DATA_DIR/repos/{repo_id}`）；`ProjectBranchService.bind(source=plan)` seam **已就绪**（85，幂等 get_or_create + 审计 + 写仅成员）。净新增 = ① 分支名 AI 生成（新 `call_source=branch_naming`）+ 固定格式校验/兜底；② 卡片确认 HITL；③ 建+推+绑编排（fail-soft 单仓隔离）。

**Primary recommendation:** 新建一个 `PlanDeepenService`（`server/initiatives/services/` 或 `delivery/services/`，编排 88 输出→v0.7 引擎→七要素深化→RESEARCH 镜像，INV-6 收口）+ 一个 `PlanDeepenNode`（workflow，consume 88 + waiting_event 多轮校验卡）+ 修订回路卡片/回调 + 容器挂起 5min 计时/resume helper（复用 SessionStore/sdk_resume/dispatcher）+ 分支编排 `BranchProvisionService`（建+推+绑，复用 CreateBranchNode 逻辑 + ProjectBranchService）+ 分支名生成 + 卡片确认。**严格复用既有引擎/服务/卡片范式，不另起。**

## Standard Stack（全部既有，无新外部依赖）

| 资产 | 路径 / 符号 | 用途 |
|------|------------|------|
| 方案编排引擎 | `server/services/plan_orchestration/entrypoint.py::{start_orchestration, build_orchestration_engine}` + `resume.py::adrive_plan_session_to_pause_or_terminal` | route→recall→research→merge 全链路（PLAN-01 核心，入口无关续驱） |
| canonical 方案脊柱 | `server/delivery/models/technical_plan.py::{TechnicalPlan, PlanVersion(supersedes self FK), PlanExternalRef}` | 方案唯一事实源 + 版本链（PLAN-01/02，复用不新建） |
| 方案写收口 | `server/delivery/services/technical_plan_service.py::TechnicalPlanService`（INV-6） | 加版本 / 关联 / 状态（PLAN-02 补充修订） |
| 方案会话 | `server/delivery/models/plan_session.py::{PlanSession, PlanSessionStatus}` + `plan_session_service.py` | 编排会话态 + decomposition.include_repos |
| per-repo 方案产物 | `server/delivery/models/research_task.py::{RepoResearchTask, PartialPlan}` | 每仓研究/部分方案（七要素扩展位） |
| 整体方案合成 | `server/services/plan_orchestration/architect_merge_adapter.py::ArchitectMergeAdapter` → `merged_plan.py` | overall 方案 + 跨仓上下文（schema 扩七要素，call_source=plan_merge 已埋） |
| per-repo explore 容器 | `server/services/plan_orchestration/research_adapter.py::ResearchDispatchAdapter`（explore + node_execution_id 续驱 + fail-soft） | per-repo 深化容器（call_source=deep_analysis_container 已埋） |
| 澄清 HITL | `server/services/plan_orchestration/clarify_adapter.py::ClarifyAdapter` + `delivery.models.Clarification` | 卡片多轮校验/澄清（PLAN-01 复用） |
| **88 输入契约** | `server/initiatives/services/repo_association_service.py::RepoAssociationService.get_verified_associations(project, work_item=None)` → `[{repository_id, repo_name, verdict, matched_node_paths, routed_reason, score}]`（仅 verified） | PLAN-01 喂 `include_repos` |
| 仓库关联写收口 | `RepoAssociationService.{confirm_repos, reopen_candidates, ...}`（88，INV-6） | PLAN-02 改仓库关联 |
| 分支绑定写收口 | `server/initiatives/services/project_branch_service.py::ProjectBranchService.bind(*, project_id, repository_id, branch_name, source=BranchSource.PLAN, actor, initiated_by_user_id, feishu_board_id, _skip_member_check)`（幂等 + 审计 + 写仅成员，**source=plan seam 已就绪**） | PLAN-04 绑 仓库↔分支↔项目 |
| 分支来源枚举 | `server/initiatives/models/project_branch.py::BranchSource.{MANUAL, PLAN, CODING}` + `ProjectBranch`（unique (project,repository,branch_name)） | PLAN-04 |
| server-local 建分支推送 | `server/workflows/nodes/git/branch.py::CreateBranchNode._create_branch_for_repository`（`DATA_DIR/repos/{repo_id}` fetch/checkout/create/push，并行 + 单仓 fail-soft） | PLAN-04 建分支推送逻辑（抽 service 复用） |
| git token 注入 | `server/services/git_credentials.py::aresolve_git_token(repo)`（per-repo→host fallback） | PLAN-04 push 鉴权 / PLAN-03 容器 dispatch |
| SDK session 跨容器持久化 | `server/chat/session_store.py::SessionStore.{mirror, load, assert_cwd_consistent}`（86，Redis→DB fallback + cwd 一致） | PLAN-03 resume / miss 兜底 |
| SDK resume dispatch env | `server/chat/sdk_resume.py::build_resume_dispatch_env(coding_session, dispatch_cwd)`（分片 transcript，超限/cwd 漂移回退新 session） | PLAN-03 resume 续跑 |
| 容器回调（question/heartbeat/completed/failed） | `server/subagent/api/callbacks.py`（question→飞书卡片；node_execution_id→`_schedule_workflow_resume`；chat 入口→`adrive_plan_session_to_pause_or_terminal`） | PLAN-03 挂起触发 + resume 续驱 |
| 容器 dispatch / 取消 | `server/runners/dispatcher.py::{get_dispatcher().dispatch(DispatchTask), cancel(task_id)}` | PLAN-03 派发 / 停容器 |
| 编码会话态 | `server/chat/models.py::CodingSession`（`Status.{DRAFT,CONFIRMED,RUNNING,AWAITING_CONFIRMATION,COMPLETED,FAILED}` + `sdk_session_id`/`sdk_transcript`/`revision_count`） | PLAN-03 挂起态承载（新增 SUSPENDED + parked_at） |
| durable 任务 | `server/resumable/service.py::{submit_resumable, wrap_resumable, register_running, heartbeat}` + `server/durable/`（queues/tasks/handlers） | PLAN-03 5min 定时挂起 + resume 编排（多副本 exactly-once） |
| RESEARCH 文档写收口 | `server/initiatives/services/project_doc_service.py::ProjectDocService.append_research_note(project_id, ...)`（INV-6 + 触发 83 push + 写时材料化 CTX-01/02） | PLAN-01 方案镜像进 RESEARCH（→ 83 同步飞书） |
| 飞书文档双向同步 | Phase 83 `DocSyncService` + `ProjectDocService.advance_sync_revision`（block 级增量 push，never-clobber） | PLAN-01 RESEARCH 镜像下行飞书 |
| CardKit 流式卡 | `server/services/feishu_im.py::FeishuIMClient.{create_card_entity, send_card_entity, stream_card_content, settle_card_stream, send_card}` + `FeishuIMService` | PLAN-01/02/04 卡片 |
| 卡片回调注册 | `server/feishu/callbacks/`（`@register_card_callback(prefix)` + `_run_in_thread` + `bind_task_context`，前缀须唯一） | PLAN-02/04 卡片 FSM |
| 群解析/建群 | `server/initiatives/services/project_service.py::ProjectService.resolve_or_create_group` | 卡片落群 |
| call_source | `server/agents/call_source.py::{CallSource(27 值), use_call_source, normalize}`；已含 `PLAN_MERGE`/`PLAN_SPEC_GENERATION`/`DEEP_ANALYSIS_CONTAINER`/`WORKFLOW_CODING_CONTAINER` | 观测（新增 plan_deepen/plan_revision/branch_naming） |
| 召回/LLM 留痕 | `server/interactions/ledger.py::{arecord_retrieval_trace, arecord_llm_usage}`（脱敏 + best-effort） | 观测强制 |
| 脱敏 | `server/common/logging.py::{redact_secrets_in_text}` + `redact_for_ledger` | 凭证/正文/分支名脱敏 |
| 触发用户归因 | `server/common/log_context.py::bind_task_context(user_id, source, component)` + `initiated_by_user_id` | 后台 worker re-bind |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 新建 verify/coding 容器栈 | 复用 v0.7 `ResearchDispatchAdapter` explore 容器 | per-repo 深化是「读代码产七要素方案」语义，正是 explore 只读，直接复用 |
| 复用 `CreateBranchNode` 节点 | 抽 `BranchProvisionService` 共享建分支推送逻辑 | 推荐抽 service（节点 + 方案流水线两入口复用，INV-6 收口绑定写），避免在节点里塞 ProjectBranch 写 |
| 新 `PlanRevision` 模型 | 复用 `PlanVersion.supersedes` 补充修订 | 复用版本链（铁律不重造），修订即新版本 |
| 自写容器挂起态 | 复用 v0.12 durable + `SessionStore` resume | 全套已就绪，仅加 SUSPENDED 态 + 5min 计时 |

**Installation:** 无新外部依赖（纯复用 + 新 Django service/node/card/callback + 小幅 schema 扩展）。

## Package Legitimacy Audit

> 本阶段**不安装任何外部包**——全部基于既有 server/ 代码与已锁定技术栈。审计 N/A。

| Package | Registry | Disposition |
|---------|----------|-------------|
| （无新增） | — | N/A — 纯内部复用 |

## Architecture Patterns

### Flow（PLAN-01~04 串联）

```text
Phase 88 get_verified_associations(project) ─┐ [{repository_id, verdict, score, ...} 仅 verified]
                                             ▼
 PlanDeepenService.deepen (INV-6 收口)
   1) include_repos = [a.repository_id]  → start_orchestration(workflow, requirement_text, include_repos)
   2) engine = build_orchestration_engine(node_execution_id=...)  [v0.7 同一引擎工厂]
   3) adrive_plan_session_to_pause_or_terminal(engine, session)
        route → recall → research(per-repo explore 容器 → PartialPlan 七要素)
        → merge(ArchitectMergeAdapter → overall MergedPlan + 跨仓上下文)
        → canonical TechnicalPlan/PlanVersion (TechnicalPlanService 写收口)
   4) 卡片多轮校验澄清 (ClarifyAdapter clarification HITL + CardKit 流式卡)
   5) 终态方案文本 → ProjectDocService.append_research_note → 83 双向镜像飞书   [PLAN-01 ✓]
                                             │ 方案确认
            ┌────────────────────────────────┼────────────────────────────────┐
            ▼                                ▼                                ▼
 [PLAN-02 修订回路]              [PLAN-03 容器挂起/resume]          [PLAN-04 建分支绑项目]
 执行中发现改/增/删仓            单仓容器问答 question 卡            逐仓 AI 生成分支名(固定格式)
  → 「调研问题发现」卡片          5min 无回复 → dispatcher.cancel     → 卡片确认
  → TechnicalPlanService 加      停容器 + CodingSession=SUSPENDED   → CreateBranch 逻辑 fetch/checkout/push
    PlanVersion(supersedes)      用户卡片回复 → build_resume_         (DATA_DIR/repos/{id} + aresolve_git_token)
  → RepoAssociationService       dispatch_env(SessionStore) re-      → ProjectBranchService.bind(source=plan)
    同步改仓库关联(多轮)          dispatch → 续到终态                 → 绑 仓库↔分支↔项目 → 回接 IDE 闭环
                                 session miss → 应用态重灌新 session
```

### Pattern 1: v0.7 引擎复用（入口无关续驱）
`include_repos` 喂 88 输出 → `start_orchestration` 建 `PlanSession` → `build_orchestration_engine(node_execution_id=...)` → `adrive_plan_session_to_pause_or_terminal` 续驱到「重挂起短路（researching 在途 / clarifying 未答）或终态」。**绝不新建第二个 engine 工厂**（CONTEXT「不造两套」），节点/服务复用同一 helper。

### Pattern 2: 卡片 HITL 状态机（镜像 87/88）
`@register_card_callback("plan_revise_" / "branch_confirm_")`（前缀唯一）+ 同步轻 ack + `_run_in_thread` + `bind_task_context(user_id=callback.user_open_id)` 后台处理；澄清/重算类**保持 waiting**，确认/终态类 `approve_node`。action_value 仅携路由 ID（不携方案正文/分支名正文，脱敏）。

### Pattern 3: 容器挂起/resume（PLAN-03 核心，复用 86/v0.8/v0.12）
- **挂起触发**：容器 question 回调发卡后注册 5min durable scheduled task（或 apscheduler 一次性 job，key=session_id）；到点未答 → `dispatcher.cancel(task_id)` 停容器 + `CodingSession.status=SUSPENDED` + `parked_at`。
- **resume**：用户卡片回复 → `build_resume_dispatch_env(coding_session)`（`SessionStore.load` Redis→DB + cwd 一致校验 + 分片 transcript）→ re-dispatch `DispatchTask`（携 resume env + 用户答复并进 prompt）→ 容器 `ClaudeAgentOptions(resume=...)` 续跑到终态。
- **session miss 兜底**：`SessionStore.load` 返回 None（Redis 失效 + DB 无 transcript）→ 不带 resume env，用应用态（canonical 方案 + 用户回复）重灌新 session 全新执行（`build_resume_dispatch_env` 已对此 fail-safe 返回 `{}`）。

### Pattern 4: 分支名固定格式生成 + 校验
- AI 生成（`use_call_source(CallSource.BRANCH_NAMING)`）：prompt 注入 type 取值规则（conventional commits）、yymmdd、work_item id（项目跟踪 id）、看板项目名、版本号（描述含则填）。
- **服务端权威校验/兜底**：正则 `^(feat|fix|chore|refactor|docs|style|test|perf|build|ci)/\d{6}\.m-\w+\.[^/]+(-v[\d.]+)?$`；id/项目名/日期由 server 权威字段拼装（不信 LLM 自由拼），LLM 仅定 type + 是否带版本号；非法 → server 兜底用默认 type=feat 拼标准名。卡片展示供用户确认/改 type。

### Anti-Patterns to Avoid
- **新建第二个 plan engine 工厂**：必用 `build_orchestration_engine` + `adrive_plan_session_to_pause_or_terminal`（CONTEXT 锁定）。
- **新建 PlanRevision 模型**：补充修订即 `PlanVersion.supersedes` 新版本。
- **分支名信 LLM 自由拼**：id/项目名/日期 server 权威拼装，LLM 仅定 type/版本号开关；正则兜底。
- **RESEARCH 镜像整篇覆盖飞书**：经 `append_research_note`/83 block 级增量（never-clobber）。
- **容器挂起后丢 transcript**：resume 前必经 `SessionStore` + cwd 一致校验，漂移即回退新 session（绝不静默错配他容器）。
- **同步 ORM 裸用 async**：一律 `sync_to_async`。
- **观测反噬主流程 / 旁路写表**：`arecord_*`/发卡/git/绑定 best-effort try/except；ProjectBranch/TechnicalPlan/RepoAssociation 写一律经各自 service（INV-6）。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| 方案 route→research→merge | 自写编排 | `build_orchestration_engine` + `adrive_plan_session_to_pause_or_terminal` |
| per-repo 深化容器 | 自写 dispatch | `ResearchDispatchAdapter` explore + node_execution_id 续驱 |
| 方案版本/补充修订 | 新模型 | `PlanVersion.supersedes` + `TechnicalPlanService` |
| 跨容器 resume | 自写 transcript 同步 | `SessionStore` + `build_resume_dispatch_env`（86） |
| 5min 挂起定时 | 自写轮询 | v0.12 durable scheduled / apscheduler 一次性 job |
| 停容器 | 自写 docker | `dispatcher.cancel(task_id)` |
| 建分支推送 | 自写 git | `CreateBranchNode._create_branch_for_repository` 逻辑（抽 service）+ `aresolve_git_token` |
| 绑 仓库↔分支↔项目 | 直写 ProjectBranch | `ProjectBranchService.bind(source=plan)`（85 seam） |
| RESEARCH 镜像飞书 | 自写飞书 API | `append_research_note` → 83 双向同步 |
| 卡片流式/回调 | 自拼 httpx | CardKit + `@register_card_callback` |
| 召回/LLM 留痕 | 自写表 | `arecord_retrieval_trace`/`arecord_llm_usage` |

**Key insight:** 净新增仅 ①per-repo/overall 七要素 schema 扩展 ②「调研问题发现」卡片+回调 ③5min 挂起计时+停容器（resume 链已通） ④分支名生成+固定格式校验+卡片确认+建推绑编排。其余全是已交付模板拼装。

## New Persistence / Schema（plan-phase 细化）

> 复用 canonical `TechnicalPlan`/`PlanVersion`（PLAN-01/02 无新模型）、`ProjectBranch`（PLAN-04 无新模型）、`RepoAssociation`（PLAN-02 复用）。仅 **PLAN-03** 需小幅 schema 扩展：

- `CodingSession.Status` 新增 `SUSPENDED = "suspended", "已挂起"`（容器 5min 无回复停容器后的态）+ 新增 `parked_at` `DateTimeField(null, blank)`（挂起时间戳，便于审计/恢复诊断）。纯 `AddField`/`AlterField`（choices 变更）migration，无回填。
  - 备注（A1，**plan-phase 后 live 验证**）：「单仓任务」的容器实例承载——若多仓编码用 `RepoCodingTask` 而非 `CodingSession`，挂起态字段落在实际承载 SDK session 的模型上（read_first 确认 `RepoCodingTask` 与 `CodingSession` 关系）。
- 写入只经 service（INV-6）。

## Observability Plan（强制，LOGGING-SPEC §4.1/§5/§7）

| 项 | 动作 |
|----|------|
| **新 call_source** | `server/agents/call_source.py::CallSource` 末尾新增（登记 §4.1，27→30）：`PLAN_DEEPEN = "plan_deepen"`（per-repo/overall 方案七要素深化 LLM，Phase 89）、`PLAN_REVISION = "plan_revision"`（「调研问题发现」修订检测 LLM）、`BRANCH_NAMING = "branch_naming"`（分支名生成 LLM）。既有 `PLAN_MERGE`/`DEEP_ANALYSIS_CONTAINER`/`WORKFLOW_CODING_CONTAINER` 沿用不动。 |
| **LLM 用量** | 每次 `ainvoke`（深化/修订检测/分支名）经 `arecord_llm_usage(call_source=..., ttft_ms, prompt/completion_tokens, upstream_status_code)`。 |
| **RetrievalTrace** | 方案深化若触发召回（recall adapter 已埋）/ 跨仓上下文检索 → `arecord_retrieval_trace(kind="recall", payload=...)`（AI 对话 + MCP 两链）。 |
| **initiated_by_user_id** | 节点取 `WorkflowExecution.triggered_by_id`（缺 `system`）；卡片回调取 `callback.user_open_id`；durable `submit_resumable` payload 带 `initiated_by_user_id`，worker 入口 `bind_task_context`；容器 dispatch 透传。 |
| **结构化事件** | `plan_deepen_started/_completed/_failed`、`plan_revision_proposed/_applied`、`container_suspended/_resumed/_resume_reloaded`、`branch_provision_started/_branch_pushed/_branch_bound/_failed`（`category="caller"`, `component` ∈ {`plan_deepen`/`initiatives`/`chat`}, 带 `duration_ms`）；per-repo/容器步骤 `category="sampling"`。 |
| **脱敏** | 方案正文/verdict/分支名/git 异常/上游响应经 `redact_secrets_in_text`；入库 payload 经 `redact_for_ledger`；git token 仅记 `has_git_token` 布尔，绝不入日志。 |
| **component 登记** | 新增 `component="plan_deepen"` 到 LOGGING-SPEC §5（或复用 `initiatives`）。 |

## Common Pitfalls

1. **容器挂起竞态**：5min 计时到点 与 用户刚好回复并发 → 双触发（停容器 + resume）。**避免**：CAS 状态机（RUNNING→SUSPENDED 条件更新；resume 仅在 SUSPENDED/AWAITING 时执行），定时器到点先读态幂等短路。
2. **resume cwd 漂移错配他容器 transcript**：必经 `SessionStore.assert_cwd_consistent`；dispatch 固定下发 `WORKSPACE_CWD`，漂移即回退新 session。
3. **分支已存在重复推送报错**：建分支前 `branch_exists`/`git` 幂等处理（已存在则跳过 create 仅 bind）；`ProjectBranchService.bind` 本身幂等（get_or_create）。
4. **单仓建分支失败拖垮全部**：逐仓 try/except 隔离（mirror CreateBranchNode 并行 + 收集 succeeded/failed），绝不上抛。
5. **RESEARCH 镜像整篇覆盖用户飞书编辑**：经 `append_research_note`/83 block 级增量 never-clobber，不整篇 diff。
6. **补充修订内容相等仍翻版本**：`PlanVersion` content_hash 相等不翻版本（v0.3/v0.6 铁律，service 已处理），修订回路复用。
7. **私有仓 push 无凭证**：push URL 须注入 `aresolve_git_token`（per-repo→host fallback）；SSH→HTTPS 改写（mirror v0.8 `_run_repo_coding` dispatch env 范式）。

## Assumptions Log

| # | Claim | Risk if Wrong |
|---|-------|---------------|
| A1 | 单仓编码容器 SDK session 承载于 `CodingSession`（含 sdk_session_id/transcript）；挂起态字段落此 | 若多仓走 `RepoCodingTask` 承载，挂起字段落点改；plan-phase 后 read_first 确认 |
| A2 | 88 `get_verified_associations` 输出 `repository_id` 可直接喂 `start_orchestration(include_repos=[...])` | 已为 88-05 明确约定契约，风险低 |
| A3 | `CreateBranchNode` 依赖 `DATA_DIR/repos/{repo_id}` 本地克隆存在（否则「请先克隆仓库」） | 方案确认仓未克隆 → 建分支前需确保克隆/或经容器建分支；plan-phase 注记 fallback |
| A4 | 5min 计时用 v0.12 durable scheduled / apscheduler 一次性 job | 若 durable 不支持延迟调度，用 apscheduler date trigger（已在栈，repo sync 轮询用） |
| A5 | per-repo explore 容器深化产七要素可经 prompt + merge schema 扩展承载，无需新容器模式 | 风险低（explore 只读读代码产文本正是所需） |
| A6 | 分支名「项目名」取自飞书项目跟踪看板名（work_item / project 跟踪字段可得） | 看板名字段缺失 → 用 project.name 兜底；plan-phase 注记 |

## Open Questions

1. **「单仓任务」承载模型**（A1）：`CodingSession` vs `RepoCodingTask`——挂起态字段落点。**推荐**：落实际持有 SDK session 的模型；execute 阶段 read_first 确认。
2. **5min 计时器载体**：durable scheduled vs apscheduler 一次性 job。**推荐**：apscheduler date trigger（已在栈，简单，best-effort；多副本由 django-apscheduler jobstore 去重）。
3. **建分支用 server-local git vs 容器**：本地需克隆（A3）。**推荐**：复用 `CreateBranchNode` server-local（已实现 + 快），未克隆仓 fail-soft 标失败并提示，不阻断其余。

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest>=9.0.2` + `pytest-asyncio` + `pytest-django` + `respx` + `pytest-socket` + `factory-boy` |
| Quick run | `cd server && uv run pytest tests/initiatives/test_plan_deepen_service.py -x` |
| Full suite | `cd server && uv run pytest` |

### Phase Requirements → Test Map
| Req | Behavior | Type | Command | Exists? |
|-----|----------|------|---------|---------|
| PLAN-01 | 消费 88 verified → include_repos → 引擎深化 → canonical TechnicalPlan/PlanVersion 七要素 | unit | `pytest tests/initiatives/test_plan_deepen_service.py::test_deepen_from_verified -x` | ❌ |
| PLAN-01 | 终态方案镜像 RESEARCH（append_research_note 被调） | unit | `...::test_mirror_research -x` | ❌ |
| PLAN-01 | 卡片多轮校验澄清保持 waiting | unit | `pytest tests/workflows/test_plan_deepen_node.py::test_clarify_waiting -x` | ❌ |
| PLAN-02 | 「调研问题发现」→ 加 PlanVersion(supersedes) + 改仓库关联 | unit | `pytest tests/feishu/test_plan_revision_callback.py::test_revise_creates_supplement -x` | ❌ |
| PLAN-03 | 5min 无回复 → cancel 容器 + status=SUSPENDED | unit | `pytest tests/chat/test_container_suspend.py::test_timeout_suspends -x` | ❌ |
| PLAN-03 | 用户回复 → build_resume_dispatch_env re-dispatch 续驱 | unit | `...::test_reply_resumes -x` | ❌ |
| PLAN-03 | session miss → 应用态重灌新 session（resume env 空） | unit | `...::test_session_miss_reload -x` | ❌ |
| PLAN-04 | AI 生成 + 固定格式正则校验/兜底 | unit | `pytest tests/initiatives/test_branch_naming.py::test_format -x` | ❌ |
| PLAN-04 | 逐仓建分支推送 + ProjectBranchService.bind(source=plan) + 单仓 fail-soft | unit | `pytest tests/initiatives/test_branch_provision.py::test_provision_and_bind -x` | ❌ |
| PLAN-04 | 卡片确认 → 建推绑；INV-6（仅 service 写 ProjectBranch） | guard/unit | `pytest tests/initiatives/test_project_branch_inv6_guard.py -x` | 已存在(85) |

### Sampling Rate
- **Per task commit:** 相关 `pytest tests/.../test_*.py -x`
- **Per wave merge:** `cd server && uv run pytest tests/initiatives tests/feishu tests/chat tests/workflows`
- **Phase gate:** `cd server && uv run pytest` 全绿
- **真机 E2E**（runner+Docker 真实 explore 深化 / 真实 git push / 真实飞书卡片+resume）→ deferred 记 89-UAT.md（autonomous 链路以 respx/seam 覆盖，对齐 87/88）。

## Security Domain

| ASVS | Applies | Control |
|------|---------|---------|
| V4 Access Control | yes | 写仅成员（ProjectBranchService 写恒守成员闸）；方案/RESEARCH 写经成员/visibility fail-closed |
| V5 Input Validation | yes | 用户卡片输入（修订要求/分支 type）不裸拼进容器 prompt/分支名；分支名 server 权威拼装 + 正则；action_value 不携正文 |
| V6 Secrets | yes | git token 经 `aresolve_git_token` 注入 push URL/容器 env，绝不入日志（仅 has_git_token 布尔）；Fernet 复用不新增 |
| V7 Logging | yes | 方案/分支名/verdict/异常脱敏（redact_secrets_in_text / redact_for_ledger） |
| V2/V3 Auth/Session | no | 复用既有 JWT/PAT/SubAgentSession |

| Threat | STRIDE | Mitigation |
|--------|--------|------------|
| 用户输入注入容器/分支名执行 | Tampering | prompt 来自 server 权威态；分支名正则 + 权威拼装 |
| 容器深化意外写远端仓 | Tampering | explore 只读双层拦截 + workspace clean 兜底 |
| resume 错配他容器 transcript | Tampering/Info | SessionStore cwd 一致校验，漂移回退新 session |
| token/方案明文落日志 | Info Disclosure | 脱敏不可绕过；token 不入 dispatch 日志 |
| 旁路写 ProjectBranch/TechnicalPlan | Tampering | INV-6 service 收口 + grep 守护 |

## Sources

### Primary (HIGH) — 真实代码勘察
- `server/services/plan_orchestration/{entrypoint,engine,resume,research_adapter,architect_merge_adapter,clarify_adapter}.py`
- `server/delivery/models/{technical_plan,plan_session,research_task}.py` + `delivery/services/{technical_plan_service,plan_session_service}.py`
- `server/initiatives/services/{repo_association_service(get_verified_associations),project_branch_service,project_doc_service,project_service}.py`
- `server/initiatives/models/project_branch.py`（BranchSource/ProjectBranch）
- `server/chat/{session_store,sdk_resume,coding_session_service,models(CodingSession)}.py`
- `server/subagent/api/callbacks.py`（question/resume）+ `server/runners/dispatcher.py`（dispatch/cancel）
- `server/workflows/nodes/git/branch.py`（CreateBranchNode）+ `server/services/git_credentials.py`
- `server/agents/call_source.py` + `server/interactions/ledger.py` + `.planning/observability/LOGGING-SPEC.md`
- `.planning/phases/89-tech-plan-branch/89-CONTEXT.md`、`88-05-SUMMARY.md`、`REQUIREMENTS.md`、`ROADMAP.md`、`project-workspace/MILESTONE-PROPOSAL.md`（§8/§9/§10）

### Secondary (MEDIUM)
- `.planning/phases/{83,85,86,87,88}-*/*-SUMMARY.md` — 上游交付决策
- `.planning/milestones/v0.8.0-*` — git/branch/resume 范式

## Metadata
- **Confidence:** Standard stack HIGH（一手代码签名核对）；架构 HIGH（v0.7/87/88 可复刻模板）；新持久化 MEDIUM（仅 CodingSession 挂起态扩展，承载模型 A1 待 live）；分支建推 MEDIUM（CreateBranchNode 依赖本地克隆 A3）。
- **Research date:** 2026-06-27 | **Valid until:** 2026-07-27（内部代码稳定）
