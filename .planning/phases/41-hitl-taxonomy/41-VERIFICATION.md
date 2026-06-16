---
phase: 41-hitl-taxonomy
status: passed
verified: 2026-06-16
requirements: [CLARIFY-01, ENTRY-01, EVENT-01]
plans: [41-01, 41-02, 41-03]
deferred: ["真实 LLM/容器端到端验收（IO 边界 mock；沿用 39/40 deferred 决策）"]
---

# Phase 41 Verification: HITL 澄清 + 事件 taxonomy + 工作流入口

**方法**：goal-backward——从 ROADMAP Phase 41 的三条 Success Criteria 反查代码与测试是否真正交付，而非仅核对任务完成。

## Success Criteria 核验

### SC-1 — HITL 澄清：不清晰挂起，回答后仅 affected_partials 重跑、其余复用（CLARIFY-01，§14）

**结论：PASS**

证据链：
- `Clarification` 模型（`server/delivery/models/clarification.py`）+ migration 0016：question/answer/answered_at + `affected_partials` M2M（回答后重跑面）。
- `ClarificationService`（`server/delivery/services/clarification_service.py`，INV-6 单一写入入口）：
  - `create_clarification` 建 pending（answered_at=None）+ 设 affected M2M。
  - `answer_clarification` 幂等条件更新（`answered_at IS NULL`）→ 仅 affected_partials 经 `ResearchService.mark_stale` 置 stale（其 valid PartialPlan invalidated_reason="clarification"），**非 affected task/partial 不动**；无 affected → 纯解除挂起。
  - INV-6 grep 守护：`Clarification.objects.create` 仅出现在 service。
- `engine._clarify` 接真实 `ClarifyAdapter`：needs → `needs_clarification`（clarifying 自挂起，不进 researching）；否则 `clarified`（→researching）。
- 测试：
  - `tests/delivery/test_clarification_service.py`（5）：仅 affected stale、非 affected 复用、无 affected 纯解除、重复答幂等 no-op、INV-6 守护。
  - `tests/services/test_engine_clarify.py`（6）：pending 挂起不转移 + emit clarification.asked、已答/无澄清 →researching、resume 不重复建、默认 policy（无 high/medium 或 ambiguous）。
  - `tests/services/test_plan_research_e2e.py::test_e2e_clarification_loop_reruns_only_affected`：端到端 merge 失败→澄清(affected=taskA)→answer→**仅 taskA 重跑、taskB 复用**→done（taskA 旧 partial invalidated + 新 valid；taskB 始终单一 valid，零失效）。

### SC-2 — 工作流入口端到端：需求经 拆分→路由→召回→澄清→并行调研→融合 产出带跨仓依赖的 MergedPlan（ENTRY-01）

**结论：PASS（IO 边界 mock；真实 LLM/容器 deferred）**

证据链：
- `AIPlanResearchNode`（`server/workflows/nodes/ai/plan_research.py`，auto-registered `ai_plan_research`）：建/恢复 `PlanSession(entrypoint=workflow)` → 注入真实 adapters（RepoRouterV2/DeliveryKnowledgeRecall/ResearchDispatch/ArchitectMerge/Clarify）构造 `PlanOrchestrationEngine` → 驱动 `engine.advance` → clarifying/researching 处 `waiting_event` 挂起（复用既有 ask_user_question/callback resume，无新 HITL infra）→ done 输出 canonical `current_plan_version`、failed 输出 NodeResult failed。
- 节点 config_schema（requirement_text/include_repos/work_item_id）+ ports（default plan_version_id/session_id/status + error）即 SSOT 经 `/api/node-types/` 自动渲染（UI reuse-first，无新 Vue 组件）；node fixture 已含 `ai_plan_research`，前后端漂移守护 `node-sync.test.ts` 绿。
- 测试：
  - `tests/workflows/test_plan_research_node.py`（5）：drive-to-done（plan_version_id 非空）、clarifying 挂起 waiting_event、failed 映射、missing requirement 快失败、schema/注册。
  - `tests/services/test_plan_research_e2e.py::test_e2e_requirement_to_merged_plan_with_cross_repo_deps`：真实 engine+全部真实 service，仅 IO 边界 mock（router/recall LLM、容器 dispatch/online、容器回调、merge synth）→ 终态 done + canonical `PlanVersion`，其 content 为 §7 MergedPlan，**跨仓依赖显式存在**（`dependency_dag={repoB:[repoA]}`、`execution_plan[t2].dependencies=["t1"]`、`dependencies_on_other_repos=["ContractX"]`）。无真实容器/网络（dispatch mock 调用 2 次）。

### SC-3 — §15 统一信封 trace 事件全程持久化，覆盖全 taxonomy + 38/39/40 对齐（EVENT-01，§15，INV-5）

**结论：PASS**

证据链：
- `PlanSessionEvent` append-only 模型 + migration 0015（§15 信封列 event/work_item/payload/ts）；`PlanSessionService._emit_event` 升级为 best-effort 持久化（DB 失败只 log，绝不抛影响转移）。
- `event_taxonomy`：§15 稳定常量集 + `build_envelope` 统一信封 helper；`ALL_EVENTS`（本 phase 编排产出 11 事件）+ `RESERVED_EVENTS`（work_item.syncing / coding.wave.* 预留）。
- 全 emit 点引用 `EVENT_*` 常量（engine/research_adapter/architect_merge_adapter/callbacks/plan_session_service/clarify_adapter/clarification_service），消除 38/39/40 字符串漂移。
- 测试：
  - `tests/delivery/test_plan_session_event.py`（4）：信封持久化（含/无 work_item）+ best-effort 吞错 + ALL_EVENTS 对账。
  - `tests/services/test_event_taxonomy_alignment.py`（3）：emit 点无裸字面量 + 引用值 ∈ ALL_EVENTS + 覆盖性反查（每事件至少一个 producer emit）。
  - e2e 断言 `PlanSessionEvent` 行覆盖 `repo.routing / knowledge.recalling / repo.research.started / repo.research.completed / plan.merge.started / plan.merge.completed`（实跑持久化）。

## 守护与回归

- `makemigrations --check --dry-run` 干净（0015 + 0016 已落，无遗漏）。
- engine 纯度守护（不直接写 `.status=`，只经 transition）绿；INV-6 守护（PlanSession / Clarification 写入唯一入口）绿。
- 全量回归无破坏：`tests/workflows` 504 passed、`tests/delivery` 298 passed（INV-6 plan_session 守护修复后）、Phase 41 编排套件 63 passed。
- 前后端节点漂移守护 `node-sync.test.ts` 绿。
- `ruff`（line 100）+ zh-CN docstring 通过。

## 偏差（已自动修复，详见各 SUMMARY）

- [Rule 1] `research_adapter` dispatch `session_id` 附 uuid 后缀——修 stale 重派 `AgentSession` UNIQUE 冲突（SC-1 affected 重跑必要修复）。
- [Rule 1] 节点 `suspend.output` 误下标 + docstring 触发 INV-6 源码守护误报——已修。
- [Rule 3] 41-01 alignment 覆盖性反查按 producer 文件存在性容错（子计划顺序安全；41-02 落地后自动强制 clarification 覆盖）。

## Deferred（非本 phase SC）

- 真实 LLM / 真实调研容器 / 真实网络的端到端验收（本 phase 一律 IO 边界 mock，沿用 Phase 39/40 deferred 决策）。
- WS 实时 trace 推送、plan-session/trace 可视化视图（EVENT-01 仅要求产出+持久化事件）。
- Chat 入口（Phase 42）。

## 里程碑过渡

**未执行**（autonomous 模式约束）：v0.7.0 里程碑过渡（Phase 42 仍 pending）不在本次范围。

---
*Phase 41 verified PASS — 2026-06-16*
