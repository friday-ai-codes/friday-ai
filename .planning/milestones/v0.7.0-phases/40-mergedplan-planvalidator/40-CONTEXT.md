# Phase 40: 架构师融合 + MergedPlan + PlanValidator + 跨仓依赖 - Context

**Gathered:** 2026-06-16
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — grey areas resolved at Claude's discretion per DOMAIN §6/§7/§14/§15)

<domain>
## Phase Boundary

实现编排的 **reduce 段**：替换 Phase 36 引擎 `_merge` 的 `SkeletonMerge`，起「架构师」融合产结构化 `MergedPlan` + `PlanValidator` 拦截低质量方案 + 跨仓依赖显式建模，落 canonical（经 Phase 37 `TechnicalPlanService`，INV-6）。

1. **MERGE-01**：架构师融合收齐 valid `PartialPlan`（Phase 39）→ 结构化 `MergedPlan`（§7：title/summary/api_contracts/dependency_dag/data_migrations/compat_risks/release_order/rollback_plan/execution_plan）→ 经 `TechnicalPlanService.create_from(origin="orchestration")` 落 `PlanVersion` + 置 `PlanSession.current_plan_version`。
2. **MERGE-02**：`PlanValidator` 拦截契约不一致（暴露↔依赖不匹配）/ 依赖成环 / 迁移顺序不合理 / 发布顺序与依赖不一致 / 缺回滚 → `ArchitectMerge.validation_status=failed` + report，按 §14 回退（merging→clarifying 或 researching）。
3. **MERGE-03**：跨仓依赖显式建模（`dependency_dag` + `execution_plan[].dependencies`），为 v0.8 wave 编码提供拓扑。
4. **EVENT（部分）**：`plan.merge.started` / `plan.merge.completed` / `plan.validation.failed` §15 事件。

**不在本 phase**：Clarification 真实回路（41，本 phase 验证失败可 transition 到 clarifying 但澄清交互在 41）、事件 sink 完整化（41）、工作流/Chat 入口（41/42）、v0.8 wave 编码消费 dependency_dag。

</domain>

<decisions>
## Implementation Decisions

### ArchitectMerge 模型（delivery，DOMAIN §6/§12 邻域）
- `ArchitectMerge`：`id UUIDField(pk, uuid4)`、`session FK(delivery.PlanSession, CASCADE, related_name="architect_merges")`、`merged_plan_version` 软引用 `UUIDField(null=True, blank=True)`（存 PlanVersion.id，与 Phase 36/37 软引用范式一致避免硬循环）、`validation_status CharField(choices: passed|failed, default=failed)`、`validation_report JSONField(default=dict)`、`attempt IntegerField(default=0)`、`created_at`。migration delivery 0014。curated re-export。INV-6：只经 service/融合 service 写。

### MergedPlan content schema（§7）
- canonical `PlanVersion.content` 的 MergedPlan 形状（§7）：`{title, summary, api_contracts[], dependency_dag, data_migrations[], compat_risks[], release_order[], rollback_plan, execution_plan[]}`。`execution_plan[]` 复用 Phase 36/PF-02 已对齐的 `execution_plan` 形状（repository_id + coding_instruction + dependencies）。
- 定义 MergedPlan schema/validator 落 `server/services/plan_orchestration/merged_plan.py`（或复用/扩展 `workflows/schemas/technical_plan.py`——倾向新建 merged_plan schema，因 MergedPlan 比既有 TechnicalPlan 多 api_contracts/dependency_dag/compat_risks/release_order/rollback_plan 跨仓字段；execution_plan 子结构复用 technical_plan 校验）。

### 架构师融合（MERGE-01）
- **架构师 = server 端 LLM 合成（可注入），非容器**：调研（Phase 39）用容器做 per-repo 隔离（map）；融合（reduce）是单点收敛，server 端 LLM 合成更合适且省资源/可测。融合 adapter `ArchitectMergeAdapter(MergeProtocol)` 落 `server/services/plan_orchestration/`，`merge(session)`：① 收集 session 的 valid `PartialPlan`（跳过 stale/invalid）；② 调可注入的 LLM 合成器（复用既有 provider_config / LLM 客户端解析）把 partials 合成 MergedPlan JSON（prompt 含各仓 api_contracts_exposed / dependencies_on_other_repos / candidate_files / proposed_changes，要求产 §7 结构）；③ 跑 `PlanValidator`；④ 通过 → `TechnicalPlanService.create_from(origin="orchestration", payload=merged, work_item=session.work_item)` 落 PlanVersion + 置 `PlanSession.current_plan_version` + `ArchitectMerge(validation_status=passed, merged_plan_version=...)`；⑤ 失败 → `ArchitectMerge(validation_status=failed, report)` + 不落 canonical + 按 §14 回退。
- LLM 合成器可注入（协议）→ 单测 mock 产出固定 MergedPlan，不依赖真实 LLM。真实 LLM 失败 → 降级（记 failed + report，不崩编排）。

### PlanValidator（MERGE-02，「不只是更贵的总结器」）
- 落 `server/services/plan_orchestration/plan_validator.py`，纯函数校验 MergedPlan，返回结构化 report `{valid: bool, errors: [...], warnings: [...]}`。校验项（DOMAIN §7）：
  1. **契约一致性**：每个仓 `dependencies_on_other_repos` 引用的契约能在其他仓 `api_contracts[]`/`api_contracts_exposed` 找到匹配（暴露↔依赖匹配）。
  2. **依赖 DAG 无环**：`dependency_dag` + `execution_plan[].dependencies` 拓扑排序检测环。
  3. **迁移顺序合理**：`data_migrations[]` 顺序与依赖一致（被依赖方迁移先行）。
  4. **发布顺序与依赖一致**：`release_order[]` 不违反 dependency_dag。
  5. **回滚完整**：`rollback_plan` 非空/覆盖各仓。
- 复用 PF-02 已对齐的 `verify_plan`（execution_plan 校验）作 execution_plan 子结构基础，PlanValidator 在其上扩展跨仓校验（不重复 execution_plan 项校验）。
- 失败 → report 写 `ArchitectMerge.validation_report`，engine 按 §14 回退（默认 merging→clarifying；planner 可定 researching 重跑触发条件）。

### engine `_merge` 接线 + §14 回退
- engine `_merge` 调注入 merge adapter；通过 → transition `merged`（merging→done）；失败 → 按 report transition 回退（`validation_failed` → clarifying 或 researching，§14「merging PlanValidator 失败 → clarifying 或 researching 按报告回退重跑」）。engine 不直写 status（transition only）。
- 回退重融合限次（防无限循环，对齐 §6 可靠恢复精神 + 自主工作流 gap closure 限 1 次思路）：`ArchitectMerge.attempt` 计数，超限则落 failed 终态。

### 事件 taxonomy（部分）
- `plan.merge.started` {partials:[repo_id...]}、`plan.merge.completed` {plan_version_id}、`plan.validation.failed` {reasons:[...]}，经 `_emit_event` §15 信封。

### Claude's Discretion
- MergedPlan schema 落新文件 vs 扩展 technical_plan.py（倾向新建 merged_plan.py，execution_plan 子校验复用）。
- LLM 合成器的精确接口与 prompt 结构（可注入 + mock 可测）。
- 验证失败回退到 clarifying vs researching 的判定规则（倾向默认 clarifying，partial stale/缺料才 researching）。
- 回退重融合最大次数（默认 1，超限 failed）。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- Phase 39 `PartialPlan`（valid 字段 + §7 content）/ `RepoResearchTask`（session 关联）—— 融合输入。
- Phase 37 `TechnicalPlanService.create_from(origin, payload, *, work_item)` —— canonical 落库唯一入口（INV-6），融合产物经它落 PlanVersion。
- Phase 36 `PlanSession.current_plan_version`（UUID 软引用）—— 融合后写入。
- `server/agents/tools/verify_plan.py`（PF-02 已对齐 execution_plan）—— execution_plan 子结构校验复用。
- `server/workflows/schemas/technical_plan.py`（execution_plan schema + validate）—— execution_plan 校验。
- `server/services/plan_orchestration/engine.py` `_merge` + `MergeProtocol/SkeletonMerge`（待替换）。
- provider_config / LLM 客户端解析（架构师 LLM 合成复用，aresolve 范式）。
- delivery service 单一写入入口 + grep 守护（INV-6）。

### Established Patterns
- 可注入协议 + 骨架默认（engine stage 依赖，38/39 已示范替换 Skeleton*）。
- LLM 调用经 provider_config 解析 + 失败 graceful 降级。
- 编排状态/产物只经 service 写（INV-6）；engine 不旁路 status（transition only，纯度守护）。
- 限次回退防无限循环（自主 gap closure / §6 恢复规则）。

### Integration Points
- ArchitectMergeAdapter(MergeProtocol) 注入 engine（替换 SkeletonMerge），工作流入口（41）注入。
- MergedPlan 落 canonical PlanVersion；PlanSession.current_plan_version 指向它。
- dependency_dag + execution_plan[].dependencies 被 v0.8 wave 编码消费。
- 事件经 _emit_event，Phase 41 接真实 sink。
- 验证失败回退衔接 Phase 41 Clarification 回路。

</code_context>

<specifics>
## Specific Ideas

- 严格按 DOMAIN §7（MergedPlan schema + PlanValidator 校验项「让架构师不只是更贵的总结器」）、§6（ArchitectMerge 字段）、§14（merging→done / PlanValidator 失败回退 clarifying|researching）、§15（plan.merge.* / plan.validation.failed 事件）。
- INV-6：MergedPlan 落 canonical 只经 TechnicalPlanService.create_from。
- INV-2：融合产物挂 session.work_item（chat null 允许）。
- 架构师 server 端 LLM 合成（reduce 单点），区别于 Phase 39 容器（map 隔离）——已确认 architect_subagent 决策的合理落地形态（专门架构师角色 + 结构化产物 + validator）。

</specifics>

<deferred>
## Deferred Ideas

- Clarification 真实交互回路（41，本 phase 仅 transition 到 clarifying）。
- 事件 sink / 订阅基础设施（41）。
- 工作流入口端到端跑通（41）+ Chat 入口（42）。
- v0.8 wave 编码消费 dependency_dag/execution_plan 拓扑。
- 架构师改容器形态（若未来需要更强隔离/工具，可选；本 phase server 端 LLM 合成足够）。

</deferred>
