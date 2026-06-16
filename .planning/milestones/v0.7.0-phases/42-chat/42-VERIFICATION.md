---
phase: 42-chat
status: passed
verified: 2026-06-16
requirements: [ENTRY-02]
plans: [42-01]
deferred: ["真实 LLM/容器端到端 chat 编排 resume 验收（IO 边界 mock；沿用 39/40/41 deferred 决策）"]
---

# Phase 42 Verification: Chat 入口薄封装（ENTRY-02）

**方法**：goal-backward——从 ROADMAP Phase 42 的三条 Success Criteria 反查代码与测试是否真正交付「同一 engine、同一状态机的薄 chat 入口」，而非仅核对任务完成。

## Success Criteria 核验

### SC-1 — Chat 入口薄封装复用同一底层 orchestration engine（不并行造两套编排），从对话即可发起方案编排（ENTRY-02）

**结论：PASS**

证据链：
- 薄共享 helper `server/services/plan_orchestration/entrypoint.py`：
  - `start_orchestration(entrypoint, requirement_text, *, work_item, created_by, include_repos)` 薄包 `PlanSessionService.create_session`（按统一 decomposition 形态建 session，entrypoint 合法性仍由 create_session 既有校验）。
  - `build_orchestration_engine(*, session_service, node_execution_id)` 注入与 Phase 41 **完全相同**的 5 个真实 adapters（RepoRouterV2/DeliveryKnowledgeRecall/ResearchDispatch/ArchitectMerge/Clarify）构造 `PlanOrchestrationEngine`。
  - 经 `plan_orchestration/__init__.py` curated re-export（`start_orchestration` / `build_orchestration_engine` 进 `__all__`）。
- **两入口共用同一 helper（grep 守护）**：
  - workflow：`server/workflows/nodes/ai/plan_research.py` `_create_session`→`start_orchestration(entrypoint="workflow")`、`_build_engine`→`build_orchestration_engine(node_execution_id=...)`。
  - chat：`server/agents/tools/plan_research_tools.py` `start_plan_research`→`start_orchestration(entrypoint="chat", work_item=None)` + `build_orchestration_engine()`。
  - 二者引用同一 `start_orchestration` / `build_orchestration_engine`——证明「底层 engine 复用、不造两套」。
- `start_plan_research` 为 `@tool`（category=PROJECT，space_id/conversation_id 由 MCP 适配层 `_adapt_tool` 从 schema 移除 + 自动注入，LLM 不可见）；自动注册进 registry + 接线进 chat 工具白名单 `_INDEXED_TOOL_NAMES`（有已索引仓库即可在对话中发起编排）。
- Phase 41 工作流节点重构为复用 helper 后**行为零变更**：`tests/workflows/test_plan_research_node.py`（5）+ `tests/services/test_plan_research_e2e.py`（3）全绿。
- 测试：`tests/agents/test_start_plan_research_tool.py::test_start_plan_research_drives_to_done_merged_plan`（chat 工具经共享 helper 驱动同一 engine 到 done，产 canonical MergedPlan 引用、session.entrypoint==chat、status==DONE）；`::test_start_plan_research_registered`（注册 + category=PROJECT + schema 含 requirement_text/include_repos + 在 `_INDEXED_TOOL_NAMES`）。

### SC-2 — Chat 发起的编排与工作流入口产出一致的 MergedPlan 与 §15 trace 事件（同一 engine、同一状态机）

**结论：PASS（IO 边界 mock；真实 LLM/容器 deferred）**

证据链：
- `tests/services/test_orchestration_entry_consistency.py::test_chat_and_workflow_entries_yield_equivalent_merged_plan`：同一 requirement + 同一 include_repos，分别经 `start_orchestration(entrypoint="workflow")` 与 `start_orchestration(entrypoint="chat", work_item=None)` 建两 session，用**结构相同的**注入 engine（同 mock router/recall + 真实 `ResearchDispatchAdapter` + `ArchitectMergeAdapter(_FakeSynth)` + `ClarifyAdapter`、容器回调用 e2e 范式 `_complete_running_tasks`）分别驱动到 done。断言：
  - 两 session 各自 `current_plan_version` 对应 `PlanVersion.content` **dict 相等**（同一融合产物，content 无 id/时间类字段）；跨仓拓扑一致（`dependency_dag={repoB:[repoA]}`、`execution_plan[t2].dependencies==["t1"]`）。
  - 两 session 的 §15 事件 taxonomy **序列相同**（按 `created_at` 取 `PlanSessionEvent.event` 列表，`seq_wf == seq_chat`），覆盖 `repo.routing / knowledge.recalling / plan.merge.completed` 等同序。
- 这证明「同一 engine、同一状态机 → 入口无关一致产物」——chat 与 workflow 仅入口运行时不同（工作流 waiting_event / chat interrupt + fire-and-forget），驱动的是同一 engine 状态机。

### SC-3 — Chat 自然语言需求允许 TechnicalPlan.work_item 为 null 但显式标记（INV-2）

**结论：PASS**

证据链：
- `start_plan_research` 建 session 时显式传 `work_item=None`（自然语言需求）；`entrypoint=chat` 落 `PlanSession.entrypoint`（显式可追溯）。融合落 canonical 时 `ArchitectMergeAdapter._handle_pass` 取 `WorkItem.objects.filter(id=session.work_item_id).afirst()` → None（chat 入口 work_item_id 为 None）→ `TechnicalPlanService.create_from("orchestration", {...}, work_item=None)`：canonical `TechnicalPlan.work_item=None`（DOMAIN §5.1：null + 来源标记即「自然语言需求」，不另设 bool）。
- `created_by` 从 `Conversation.created_by` 标量解析为 recall actor（async 安全，不裸 lazy-FK）；为空时召回 fail-closed 返回空（文档化降级，T-42-01）。
- 测试：`tests/agents/test_start_plan_research_tool.py::test_start_plan_research_inv2_null_work_item`：chat 自然语言需求（不传 work_item）驱动到 done → `PlanSession.work_item_id is None` 且 `entrypoint=="chat"`；canonical 经 `session.current_plan_version`→`PlanVersion`→`TechnicalPlan.work_item_id is None`（origin=orchestration）。
- SC-2 测试同时断言两入口 `work_item_id is None`。

## 守护与回归

- `makemigrations --check --dry-run` 干净（**无模型变更，无 migration**——薄封装复用既有 engine/adapters/模型）。
- 共用 grep 守护：`start_orchestration` / `build_orchestration_engine` 同时被 `plan_research.py`（workflow）与 `plan_research_tools.py`（chat）引用，证明「底层 engine 复用、不造两套」。
- engine 纯度守护（engine 只经 transition 推进，不直接写 status）+ INV-6 守护（PlanSession/Clarification/ArchitectMerge/TechnicalPlan 写入唯一入口）回归全绿。
- 回归：plan_orchestration + workflows + delivery（INV-6 守护）+ agents 工具套件——本 phase 直接相关 16 测全绿；engine 纯度 + INV-6 + orchestration 回归 107 passed；Phase 41 节点/e2e 8 passed（helper 重构后零回归）。
- `ruff`（line 100）+ zh-CN docstring 通过（含已编辑文件 `agents/tools/__init__.py` 导入排序顺手收口）。

## 偏差（已自动修复，详见 SUMMARY）

- [Rule 3] `agents/tools/__init__.py` 导入块 I001 预先存在；新增 `start_plan_research` 导入触发 lint，对本就在编辑的导入块跑 `ruff --fix`（纯排序，无语义变更）使 Task 2 verify ruff 干净。

## Deferred（非本 phase SC）

- 真实 LLM / 真实调研容器 / 真实网络的 chat 编排端到端 resume 验收（本 phase 一律 IO 边界 mock，沿用 Phase 39/40/41 deferred 决策）。
- chat 编排的富前端可视化 / trace 可视化（chat 已有对话/澄清 UI；非 SC 必需）。
- 对外 OpenAI/Anthropic API adapter 透出编排事件（v0.11）。

## 范围外（pre-existing，不在本 phase 修复）

- `tests/agents/test_tool_contracts.py::test_search_repository_code_input_schema_snapshot` 预先存在的快照文本漂移（`search_repository_code` description，与 ENTRY-02 无关）——见 `deferred-items.md`。

## 里程碑过渡

**未执行**（autonomous 模式约束）：v0.7.0 里程碑过渡由 orchestrator 管理，不在本次范围。Phase 42 为 v0.7.0 末 phase；本 plan 完成后里程碑全部 7 phases 编排能力交付完毕。

---
*Phase 42 verified PASS — 2026-06-16*
