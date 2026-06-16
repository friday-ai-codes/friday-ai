---
phase: 41-hitl-taxonomy
reviewed: 2026-06-16T13:10:00Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - server/delivery/models/plan_session_event.py
  - server/delivery/models/clarification.py
  - server/delivery/migrations/0015_plansessionevent.py
  - server/delivery/migrations/0016_clarification.py
  - server/delivery/services/event_taxonomy.py
  - server/delivery/services/clarification_service.py
  - server/delivery/services/plan_session_service.py
  - server/delivery/services/research_service.py
  - server/services/plan_orchestration/engine.py
  - server/services/plan_orchestration/protocols.py
  - server/services/plan_orchestration/clarify_adapter.py
  - server/services/plan_orchestration/research_adapter.py
  - server/services/plan_orchestration/architect_merge_adapter.py
  - server/services/plan_orchestration/__init__.py
  - server/subagent/api/callbacks.py
  - server/workflows/nodes/ai/plan_research.py
findings:
  critical: 2
  warning: 2
  info: 2
  total: 6
status: resolved
resolved_at: 2026-06-16T14:40:00Z
resolution:
  CR-01: fixed
  CR-02: fixed
  WR-01: fixed
  WR-02: fixed
  IN-01: fixed
  IN-02: acknowledged  # v0.7 默认 affected 为空的限制（HITL 答复关联候选仓后置），见 SUMMARY
---

# Phase 41: Code Review Report

**Reviewed:** 2026-06-16T13:10:00Z
**Depth:** standard
**Files Reviewed:** 16
**Status:** resolved

> **Resolution (2026-06-16):** CR-01/CR-02（BLOCKER）+ WR-01/WR-02 + IN-01 已修复并补测；
> 默认（非注入 policy）真实路径下工作流入口现可走到 `done`：
> - 无澄清分支（routing 有 high/medium）：researching 派 deep 容器 → 容器完成回调经
>   `node_execution` 关联触发 `_schedule_workflow_resume` 重新驱动挂起节点 → merging → done（CR-02）。
> - 有澄清分支（routing 无 high/medium）：建一轮 Clarification 挂起；答复后单轮 guard
>   放行 researching → … → done，不再无限追问（CR-01）。
> 详见各 finding 下的 _Resolution_ 注记与对应 `fix(41): ...` 提交。

## Summary

审查 Phase 41（HITL 澄清 + 事件 taxonomy + 工作流入口）变更源文件，对照 DOMAIN §6/§14/§15 与 INV-5/INV-6、engine 纯度、async lazy-FK bug 类、best-effort 事件语义、suspend/resume 正确性逐条核验。

EVENT-01（事件 taxonomy 持久化）质量高：`PlanSessionEvent` append-only 信封、`_emit_event` best-effort（try/except 吞错不阻断转移）、§15 常量集中定义 + 各 emit 点引用常量、`build_envelope`/`_persist_event` 全程用 `work_item_id` 标量规避 lazy-FK，均正确落地。INV-6 单一写入、engine 仅经 `transition` 改 status 的纯度约束保持良好。`mark_stale` 的影响面**精确**限定在传入 `task_ids`（仅 affected_partials），未误伤其他 task——SC-1 的「仅 affected 重跑」在 service 层是对的。stale 重派 `session_id` 附 uuid 后缀修 `AgentSession` UNIQUE 冲突的自动修复**正确**。

但发现 **2 个 BLOCKER**，二者叠加导致 **默认 policy 下工作流入口（ENTRY-01/SC-2）在真实（非 mock）路径几乎无法走到 `done`**：

1. **CLARIFY-01 澄清回路存在无限挂起**：默认 policy 对「已答」无感知，回答后重入 `_clarify` 会因 routing 信号未变而**再次创建新 Clarification**，违反 §14「全部已答 → researching」。
2. **researching 段 `waiting_event` 无 resume 通路**：调研容器的 `SubAgentSession` 未关联 `node_execution`，且 `plan_research` 回调分支显式跳过 resume——任一 deep 仓被派发后工作流节点将永久挂起。

测试之所以全绿，是因为 `test_engine_clarify` 用注入 policy 绕开了「答后重入」的真实路径，节点/e2e 测试用全 light 仓或直接驱动 barrier 绕开了真实 research-resume 往返。

## Critical Issues

### CR-01: 默认澄清 policy 答后重入造成无限挂起（违反 DOMAIN §14「全部已答 → researching」）

**File:** `server/services/plan_orchestration/clarify_adapter.py:81-101`（配合 `default_needs_clarification` 37-64）

**Issue:**
`ClarifyAdapter.clarify` 仅以「存在 pending（`answered_at IS NULL`）」短路；无 pending 时**无条件重跑 policy**。但 `default_needs_clarification` 的两个判定条件都**与用户答复无关、答后不变**：

- 条件 1：`(session.routing).candidates` 无 high/medium → 需澄清；
- 条件 2：`session.decomposition.ambiguous` 为真 → 需澄清。

用户答复经 `answer_clarification` 只写 `answer`/`answered_at`（+ 可选 affected stale），**绝不修改 `session.routing` / `session.decomposition`**，且 clarifying 不回环到 routing/decomposing 重算。因此答后重入 `_clarify`：pending 已清空 → 重跑 policy → 条件仍成立 → **创建第二条 Clarification（新 pending）→ 节点再次挂起**。这与 §14「clarifying | 无待澄清 **或全部已答** → researching」直接冲突，也违反 41-02 must_have「回答后 engine 重入 _clarify：pending 清空 → clarified → researching」。

由于这是触发澄清的**最常见原因**（低路由置信），默认 policy 下编排在该分支**永远无法离开 clarifying**（每次答复都被再问）。`test_engine_clarify::test_already_answered_advances_to_researching` 用 `policy=lambda s: (False, ...)` 注入了「不需澄清」的 policy，因此没有覆盖真实的「答后 policy 仍判需澄清」路径，掩盖了该缺陷。

**Fix:**
落实 §14「全部已答 → researching」：无 pending 但**已存在已答 Clarification**时应判定澄清已满足、直接放行（而非盲目重跑 policy）。最小修复：

```python
async def clarify(self, session: PlanSession) -> dict:
    from delivery.models import Clarification

    has_pending = await Clarification.objects.filter(
        session_id=session.id, answered_at__isnull=True
    ).aexists()
    if has_pending:
        return {"needs_clarification": True, "pending": True}

    # §14「全部已答」：已问过且全部已答 → 视为澄清满足，直通 researching，
    # 不因 routing/decomposition 信号未变而重复追问（否则无限挂起）。
    has_answered = await Clarification.objects.filter(
        session_id=session.id, answered_at__isnull=False
    ).aexists()
    if has_answered:
        return {"needs_clarification": False}

    needs, question, affected_task_ids = self.policy(session)
    ...
```

更稳健的做法是把「已答 Clarification + 答复文本」作为入参传给 policy，让 policy 自行判断答复是否已消解歧义（支持「答复仍不充分 → 追问」的合法多轮），但 v0.7 至少须保证默认路径满足 §14 不死循环。

**Resolution（fixed）**：`ClarifyAdapter.clarify` 实现单轮 HITL 语义——无 pending 但本 session
已存在「已答」Clarification 时直接返回 `needs_clarification=False`（直通 researching），不再重跑
静态 policy；仅首轮（本 session 无任何 Clarification）跑 policy。新增真实-adapter-path 回归测试
`test_engine_clarify::test_real_policy_answered_round_advances_no_second_clarification`（routing 无
high/medium → 答后不再追问、不建第二条 Clarification）。提交 `fix(41): CR-01 ...`。

---

### CR-02: researching 段 `waiting_event` 缺少 resume 通路——节点永久挂起（SC-2 truth #3 未真正接通）

**File:** `server/services/plan_orchestration/research_adapter.py:169-205`（`node_execution_id=""` + `SubAgentSession.acreate` 未设 `node_execution`）；`server/subagent/api/callbacks.py:122-128`；`server/workflows/nodes/ai/plan_research.py:292-302`

**Issue:**
`AIPlanResearchNode` 在 `researching` 且有在途调研任务时返回 `NodeResult(status="waiting_event", output={... "_resume_from_callback": True})`（`plan_research.py:292-302`），声称「复用既有 callback resume 范式」。但调研容器的 resume 通路实际**断开**：

1. `ResearchDispatchAdapter._dispatch_deep_task` 创建 `SubAgentSession` 时**未设置 `node_execution`**，且 `DispatchTask(..., node_execution_id="")` 硬编码为空（`research_adapter.py:175-187, 202`）。对比 `coding.py:1005-1033`，AICodingNode 显式把 `node_execution_id` 写入 `SubAgentSession`，正是工作流 resume 的关键钥匙。
2. 容器完成回调 `_schedule_workflow_resume` 以 `session.node_execution_id` 为前置（`callbacks.py:193`：`if not session.node_execution_id: return`）——plan_research 容器无此 id，**直接跳过工作流恢复**。
3. 另一条 `_schedule_agent_session_resume` 对 `last_output.source == "plan_research"` **显式 return 跳过**（`callbacks.py:122-128`，CR-01 注释为防幽灵 agent）。

结果：deep 调研容器完成后，`_handle_research_completion` 经 barrier 把 **PlanSession DB** 推进到 merging/done，但**挂起的工作流 `NodeExecution` 永不被重新驱动**——节点停在 `WAITING_EVENT`，永不产出 `output`（plan_version_id），也永不走完 merging→done。

注意触发条件与 CR-01 互补：routing 有 high/medium → 不触发澄清 → 进 researching → 派 deep 容器 → **挂死**；routing 无 high/medium → 触发 CR-01 无限澄清。两者叠加使默认 policy 下**没有**一条真实路径能到达 `done`。`node_execution` 注入由 engine 纯度（adapter 入口无关、不持有 node_execution）天然缺位，是真实的架构接缝缺陷，而非仅「真实容器 E2E deferred」可掩盖（mock 回调即可暴露，但现有测试用全 light 仓 / 直接驱动 barrier 绕过了该往返）。

**Fix:**
为 plan_research 调研容器建立到工作流节点的 resume 桥接，二选一：

- **(推荐) 透传 node_execution**：节点把 `node_execution_id` 经 session 注入到调研 dispatch（如 `ResearchDispatchAdapter` 增可选 `node_execution_id` 注入位，或 engine 入口把它放进 `PlanSession` 元数据），`SubAgentSession.acreate(..., node_execution_id=node_execution_id)`，使既有 `_schedule_workflow_resume` 自然触发；
- **或** 在 `_handle_research_completion` 的 barrier 推进后，按 `plan_session_id → 关联工作流 NodeExecution` 反查并调 `WorkflowEngine._continue_after_node`，补一条「plan_session → workflow」专用 resume 通路。

并补一条 mock 回调的 research-suspend→resume 往返测试（不依赖真实容器）证明节点最终走到 `completed`。

**Resolution（fixed，推荐方案：透传 node_execution）**：`AIPlanResearchNode._build_engine` 把本
节点 `node_execution.id` 透传给 `ResearchDispatchAdapter(node_execution_id=...)`；`_dispatch_deep_task`
据此设置 `SubAgentSession.node_execution`（+ `DispatchTask.node_execution_id`），使容器完成回调经
既有 `_schedule_workflow_resume` 自然重新驱动挂起的 WAITING_EVENT 节点（researching→merging→done）。
`callbacks.py` 中 `_schedule_agent_session_resume` 的 plan_research 短路保留（Phase 39 幽灵 agent 修复）——
工作流路径现由顶部 `if session.node_execution_id: return` 提前短路并改走 workflow resume，Chat 入口
（无 node_execution）仍走 plan_research 短路。新增 suspend(researching)→resume→done 往返测试
`test_plan_research_e2e::test_research_suspend_resume_reaches_done_via_node_execution`（IO 边界 mock
dispatch/容器/LLM，断言调研 SubAgentSession 关联 node_execution + 节点 resume 后产出 MergedPlan）。
提交 `fix(41): CR-02 ...`。

## Warnings

### WR-01: `mark_stale` 对 running 的 affected 任务无状态前置——晚到回调被静默丢弃 + 可能重复派容器

**File:** `server/delivery/services/research_service.py:183-194`

**Issue:**
`_mark_stale_sync` 把 `task_ids` 中**所有非 stale 任务**置 stale（含 `pending`/`running`），不像 `retry_task` 那样有 session 状态/任务状态前置校验。若某 affected 任务正 `running`（容器在途）时澄清被回答置 stale，随后 researching 重派会对同仓再起一个容器；而原 running 容器的晚到完成回调进入 `_aload_research_task` 时，因 `task.status == STALE ∈ (DONE, FAILED, STALE)` 被判「终态」→ 返回 None → **静默丢弃**（`callbacks.py:1242-1247`）。可能出现同仓双容器 + 丢弃一份结果。默认 policy 下 `affected_task_ids` 恒为 `[]`，实际触发面窄（多见于 merge-reclarify / e2e 注入 affected 的场景），故列为 WARNING。

**Fix:**
`mark_stale` 仅对「已 done 的 affected 任务」置 stale 重跑更安全（running 任务让其自然完成后再按需失效），或对正在 running 的 affected 任务先取消其在途容器再 stale，避免重复派发与结果丢弃。

**Resolution（fixed）**：`ResearchService._mark_stale_sync` 加状态前置——仅把**已终态**（done/failed）
的 affected 任务置 stale 重跑，running/pending 在途任务跳过（让其自然完成）。避免同仓双容器派发 +
晚到回调结果被静默丢弃（晚到回调对已 stale 任务经 `_aload_research_task` 终态判定安全 no-op，不损坏
状态）。新增测试 `test_research_service::test_mark_stale_skips_running_affected_task` /
`test_mark_stale_running_only_is_noop`。提交 `fix(41): WR-01 ...`。

### WR-02: merge 校验失败 `validation_failed_reclarify` 回退在默认 policy 下退化为空操作

**File:** `server/services/plan_orchestration/engine.py:268-281`（配合 `architect_merge_adapter.py:238-254`）

**Issue:**
§14「PlanValidator 失败 → clarifying 或 researching 按报告回退重跑」。当 `back_target="clarifying"`（有 valid partial、无 stale 时的默认）→ `transition("validation_failed_reclarify")` 回 clarifying。但下一步 `_clarify` 在默认 policy 下：无 pending、routing 有 high/medium、无 ambiguous → 判**不需澄清** → 直接 `clarified` → researching；此时所有 task 已 done（无 affected 被 stale）→ barrier 立即满足 → 再次 merging → 同样的合成失败 → `attempt >= MAX_MERGE_RETRIES` → `fail`。即 reclarify 分支**既不真正发起澄清、也不重跑任何 partial**，仅空转一圈后失败。行为有界（不死循环），但 §14「按报告回退重跑」的语义未被实质实现——验证失败无法借澄清/重研究带来新信息再融合。

**Fix:**
让 merge 失败回退携带「为何失败」驱动澄清/重研究：失败 report 写入 session 上下文，由澄清 policy 据 report 触发针对性澄清（含 affected_partials），或当 `back_target=researching` 时对相关 partial 主动 `mark_stale` 以真正重跑，否则 reclarify/reresearch 退化为「再失败一次」。

**Resolution（fixed）**：`ArchitectMergeAdapter._handle_fail` 在 `back_target == "clarifying"` 且
`attempt < MAX_MERGE_RETRIES` 时，经 `ClarificationService` 主动建一条「描述校验失败原因」的 pending
Clarification + emit `clarification.asked`。结合 CR-01 单轮 guard，回退真正落到一次 HITL 澄清（节点
挂起等用户），而非默认 policy 下被静默吞没空转。**有界**：仅在仍可重试时建（attempt 达上限时 engine
直接落 `failed` 终态，不留孤儿 pending）；重 merge 仍非法 → `attempt>=MAX` → `failed` 终态，不无限循环。
未主动 stale partial（避免对正确 partial 误失效；选择「确定性有界」而非全量重研究——见决策注记）。
新增测试 `test_architect_merge_adapter::test_merge_fail_reclarify_creates_clarification` /
`test_merge_fail_reclarify_bounded_when_attempt_exhausted` /
`test_merge_reclarify_meaningful_with_one_round_guard`。提交 `fix(41): WR-02 ...`。

## Info

### IN-01: `plan.session.failed` 不在 DOMAIN §15 taxonomy 表内（additive）

**File:** `server/delivery/services/event_taxonomy.py:58, 77`

**Issue:** `ALL_EVENTS` 含 `plan.session.failed`，但 DOMAIN §15 事件表未列该名（§15 仅到 `coding.wave.*`）。属合理的失败终态 trace 扩展、且 plan-01 明确要求，但与 §15 文档存在轻微不一致。

**Fix:** 在 DOMAIN §15 表补 `plan.session.failed` 行（payload `{error}`），保持代码常量集与文档词表逐字对齐，避免后续 v0.11 对外 adapter 漏映射。

**Resolution（fixed）**：DOMAIN §15 事件表已补 `| \`plan.session.failed\` | \`{error}\` |` 行（紧随
`plan.validation.failed`）。提交 `docs(41): IN-01 ...`。

### IN-02: 纯 HITL 澄清路径下用户答复永不触发 affected 重跑

**File:** `server/services/plan_orchestration/clarify_adapter.py:55, 62, 64`

**Issue:** `default_needs_clarification` 恒返回 `affected_task_ids=[]`，故 `answer_clarification` 走「无 affected → 纯解除挂起」，§14「仅 affected_partials 重跑」在真实 HITL 答复中从不发生（仅在 merge-reclarify / e2e 显式注入 affected 时被覆盖）。结合 CR-01，当前 HITL 答复对调研结果无任何影响。可能为「affected 决定权后置」的有意决策，但与 SC-1 的「答后仅 affected 重跑」叙述存在落差。

**Fix:** 明确 affected 来源（如：澄清答复关联到被质疑的候选仓 → 对应 task 入 affected），使「答后增量重跑」在 HITL 主路径真实可达；或在文档/SUMMARY 注明 v0.7 默认 affected 为空的限制与后续补齐计划。

**Resolution（acknowledged，deferred）**：保留 v0.7 默认 affected 为空的有意决策（HITL 答复关联候选仓
为后置能力）。注入 policy / merge-reclarify / e2e 显式注入 affected 的路径仍按 §14「仅 affected 重跑」
工作（见 `test_e2e_clarification_loop_reruns_only_affected`）。后续补齐「答复→affected」映射规划归入
v0.7+ 待办，不阻断本里程碑 SC。

---

_Reviewed: 2026-06-16T13:10:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
