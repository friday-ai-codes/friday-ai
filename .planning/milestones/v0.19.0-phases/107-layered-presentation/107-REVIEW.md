---
phase: 107-layered-presentation
reviewed: 2026-07-30T01:05:00Z
depth: deep
diff_base: 2bbcce09
branch: milestone/v0.19.0-plan-trust
status: fixed
fixed_at: 2026-07-30T01:50:00Z
findings:
  blocker: 2
  major: 2
  minor: 9
  info: 4
  total: 17
resolution:
  fixed: 16
  deferred: 1
tests_after_fix:
  backend: "2764 passed, 21 skipped（tests/codegraph + tests/delivery + tests/services + tests/agents + tests/workflows）"
  frontend: "328 passed（web vitest src/components/chat + src/stores）+ vue-tsc --noEmit 通过"
tests_executed:
  backend: "334 passed（tests/codegraph/{ranking,group_scope,v2_degraded,v2_meta,golden,measure_stage1_latency} + tests/delivery/test_expire_pending_clarifications + tests/workflows/test_plan_research_node + tests/services/{repo_router_adapter,engine_clarify,event_taxonomy_alignment} + tests/test_metric_sampling + tests/agents/{repository_relevance_tool,runapscheduler_backfill} + tests/chat/{trace_model,manual_override_view}）"
  frontend: "49 passed（RoutingDecisionPanel.test.ts + stores/routing.test.ts）"
  property_probe: "clamp_llm_permutation 穷举 9460 组（n<=6, k=0..3, 全部子集×全排列）后置条件 0 违规"
files_reviewed_list:
  - server/agents/management/commands/runapscheduler.py
  - server/agents/tools/repository_relevance.py
  - server/agents/tools/schemas/repository_relevance.py
  - server/chat/migrations/0032_repositoryroutingtrace_degrade_reason.py
  - server/chat/models.py
  - server/chat/views.py
  - server/codegraph/management/commands/measure_stage1_latency.py
  - server/codegraph/services/repo_group_scope.py
  - server/codegraph/services/repo_router_ranking.py
  - server/codegraph/services/repo_router_v2.py
  - server/delivery/management/commands/expire_pending_clarifications.py
  - server/delivery/models/clarification.py
  - server/delivery/services/clarification_service.py
  - server/delivery/services/event_taxonomy.py
  - server/friday/settings.py
  - server/services/process_runtime/clarify_adapter.py
  - server/services/process_runtime/repo_router_adapter.py
  - server/system/metric_sampling.py
  - server/workflows/nodes/ai/plan_research.py
  - web/src/components/chat/RoutingDecisionPanel.vue
  - web/src/stores/chat.ts
  - web/src/stores/routing.ts
  - web/src/types/routing.ts
findings_index:
  - id: BL-01
    severity: BLOCKER
    file: server/delivery/management/commands/expire_pending_clarifications.py:373
    summary: 超时出口只改状态不重驱引擎，会话由 waiting_clarification 停成 research/running，仍无产出
    status: fixed
    commit: e5c80c87
  - id: BL-02
    severity: BLOCKER
    file: server/agents/tools/schemas/repository_relevance.py:56
    summary: 工具输出无 degraded/degrade_reason/block_order/router_version，实时对话链路降级提示与分组呈现恒不生效
    status: fixed
    commit: 5f587a00
  - id: MJ-01
    severity: MAJOR
    file: server/codegraph/services/repo_router_ranking.py:56
    summary: 重试/降级分类按具体异常类名子串匹配，漏掉 429/5xx（不重试且显示「未知原因」），却把 400 判为可重试
    status: fixed
    commit: 0d92a841
  - id: MJ-02
    severity: MAJOR
    file: server/codegraph/services/repo_router_v2.py:634
    summary: auto_selected 现由 score_ranked 排序后的首位决定，α 可改变编排是否自动推进，与同处注释声明的不变量矛盾且无测试锁定
    status: fixed
    commit: c084039a
  - id: MN-01
    severity: MINOR
    file: web/src/components/chat/RoutingDecisionPanel.vue:82
    summary: group 空串兜底未实现（?? 对 "" 无效），该候选在分组启用时从两个分区同时消失
    status: fixed
    commit: 9d6e485d
  - id: MN-02
    severity: MINOR
    file: server/codegraph/services/repo_router_v2.py:412
    summary: 无分组上下文时候选列表不按 score_ranked 排序，与有上下文路径「首位=最佳」语义不一致
    status: fixed
    commit: bf96dfa9
  - id: MN-03
    severity: MINOR
    file: server/agents/tools/repository_relevance.py:293
    summary: v2_candidates[:top_k] 可能把 in_project 组整组截空，而 block_order 仍报长度 2
    status: fixed
    commit: 37874e69
  - id: MN-04
    severity: MINOR
    file: server/system/metric_sampling.py:184
    summary: 新增 gauge 块的 error=str(exc) 未过 redact_secrets_in_text，违反脱敏强制规范
    status: fixed
    commit: 8012d0d1
  - id: MN-05
    severity: MINOR
    file: server/delivery/management/commands/expire_pending_clarifications.py:338
    summary: initiated_by_user_id 只 logger.bind 未进 contextvars，transition/_emit_event 等下游日志拿不到归因
    status: fixed
    commit: 311f514a
  - id: MN-06
    severity: MINOR
    file: server/friday/settings.py:399
    summary: D-4 仍留约 10 分钟矛盾态窗口，且出口会在已 TIMEOUT 的工作流上「继续推进」
    status: fixed
    commit: 1404db2e
  - id: MN-07
    severity: MINOR
    file: server/codegraph/services/repo_router_v2.py:1373
    summary: timeout/max_candidates/hits_per_repo/cache_ttl 未走 _stage1_seconds 的 fail-safe，非数值配置直接抛
    status: fixed
    commit: 257cf05f
  - id: MN-08
    severity: MINOR
    file: server/chat/views.py:2760
    summary: manual override 未对 original.block_order 做 isinstance 校验（detail 视图做了），脏数据会写出错值
    status: fixed
    commit: fd456919
  - id: MN-09
    severity: MINOR
    file: server/services/process_runtime/repo_router_adapter.py:86
    summary: D-1 放开硬过滤后 evidence 含跨空间能力树节点路径与 LLM reasoning，超出「仓名不敏感」的论证范围
    status: fixed
    commit: 813e6f32
  - id: IN-01
    severity: INFO
    file: server/delivery/management/commands/expire_pending_clarifications.py:298
    summary: _pending_round 每轮 2 次 exists 查询，单次扫描 N+1
    status: fixed
    commit: c7c415da
  - id: IN-02
    severity: INFO
    file: server/chat/migrations/0032_repositoryroutingtrace_degrade_reason.py:1
    summary: 迁移文件名只提 degrade_reason，实际含两个 AddField
    status: deferred
  - id: IN-03
    severity: INFO
    file: server/codegraph/services/repo_router_ranking.py:194
    summary: blend_ranked_scores 的 N 含不在 stage0_scores 内的 id（防御分支会让 S_llm 偏小）
    status: fixed
    commit: 72dbce52
  - id: IN-04
    severity: INFO
    file: web/src/components/chat/RoutingDecisionPanel.vue:154
    summary: in_project 组为空时仍展示置顶因果句，无对比对象
    status: fixed
    commit: 41a01ce9
---

# Phase 107: 代码评审报告

**评审范围:** `2bbcce09..HEAD` 中 `server/` 与 `web/` 的全部源码改动（43 个文件，7198 行新增）
**深度:** deep（跨文件调用链 + 消费方追踪 + 穷举性质探测 + 实跑既有测试）
**结论:** `findings` —— 2 个 BLOCKER、2 个 MAJOR、9 个 MINOR、4 个 INFO

**修复状态（2026-07-30）:** 16 条 fixed、1 条 deferred（IN-02，迁移已 applied 不宜改名）。每条 finding 正文下方有「处置」块记录方案与 commit；BLOCKER/MAJOR 四条均带「复现 → 修复」的守护测试。修复后回归：后端 `tests/codegraph + tests/delivery + tests/services + tests/agents + tests/workflows` 2764 passed / 21 skipped；前端 `vitest src/components/chat + src/stores` 328 passed 且 `vue-tsc --noEmit` 通过。

## 摘要

**先说通过的部分（这些是本 phase 最容易做坏而实际做对了的地方）：**

- **D-3 硬约束成立。** `score_ranked` 是独立字段，全模块只有 `repo_router_v2.py:1686` 一处写入；`breakdown` 无任何 α 项（grep 确认 `alpha` 只出现在配置读取、`blend_ranked_scores` 调用与快照留痕）；三处 `Σbreakdown == score` 断言全部在位且通过——`test_repo_router_v2_meta.py:248` / `:462`（1e-9）与 `RoutingDecisionPanel.vue:328`（1e-6）。徽标与「合计」行也确实仍读 `score`。
- **有界重排的后置条件真的成立。** 对 `clamp_llm_permutation` 做了穷举探测（n≤6、k=0..3、全部子集 × 全排列，共 9460 组）：返回集合恒等于输入子集，且 `|order.index(rid) - base_order.index(rid)| <= k` **零违规**。base rank 确实取「被 LLM 返回子集内的相对位次」（`repo_router_ranking.py:152`），不是全量窗口下标——这条修得对。
- **总延迟是硬上界。** 重试写在自己的 `for attempt in range(2)` 里，per-attempt 超时取 `min(timeout_seconds, remaining)`（`repo_router_v2.py:1526`），退避睡眠也受剩余预算封顶（`:1553`），且 langchain 内部重试被 `max_retries=0` 关掉。循环结构上不存在「跑完不 break 也不 raise」的路径，`response` 不可能为 None。
- **K 预算在生产主路径生效。** `candidates = [by_rid[rid] for rid in clamped_order ...]`（`:1677`）把裁剪产物写回返回顺序。这处计划外改动我逐一核对了副作用面：`confidence` 仍由 Stage 0 位次推导（`sorted_scores` 取自 `stage0_candidates`，`:1610`），不受重排影响；`breakdown`/`criticality`/`matched_node_paths` 均来自 `base`，与顺序无关；候选集合不变（`candidates ⊆ clamped_order` 且两者同集）。**唯一实际外溢是 `auto_selected`**，见 MJ-02。
- **`_fail` 的 CAS 未命中不再静默。** `_fail_sync` 命中时会把 `session.status` 同步为 `FAILED`（`convergence_session_service.py:288`），未命中时 `_refresh_status_sync` 重读 DB，所以命令侧 `if session.status != FAILED` 的终态核对（`expire_pending_clarifications.py:367`）是有效判据，闭合了「CAS 未命中却记成已出口」的缺口。
- **幂等复用 CAS、扫描两段式。** 出口只经 `transition`，无自建锁；`_collect` 的 `atomic + select_for_update(skip_locked=True)` 块内确实只做同步读与收集，`asyncio.run` 在事务外。
- **降级原因 6 值闭集封闭。** `classify_degrade_reason` 只吃 `skipped_reason` 与**异常类型名**两个字符串，结构上收不到异常实例/消息；返回值恒 ∈ 闭集 ∪ `""`；DB 列 `max_length=32` 是第二道形状约束；前端未命中一律回「未知原因」且 DOM 不出现原始串（`RoutingDecisionPanel.vue:230`）。两处 `str(exc)[:200]` 都已改为 `redact_secrets_in_text(str(exc))[:200]`（`repo_router_v2.py:496` / `:594` / `:1545`）。
- **前端尊重后端 `block_order`。** 全局重排已删，`groupedBlocks` 按 `blockOrder` 产出分区、区内才排序（`:124-147`）；override 兜底用 `??`（`routing.ts:81-84`）；零新色板（`teal`/`amber` 本来就在 `components/ui/badge/index.ts:18-21` 的 variant 里）；历史 trace（`block_order` 缺失）走平铺兼容分支。
- **迁移 additive、无 RunPython、可逆**（两个 `AddField` 均带默认值）。

**问题集中在两处，都不是「代码写错」而是「链路没接通」：**

1. 澄清超时出口把会话推到 `research`/`running` 之后**没有人再驱动引擎**——会话不再停在 `waiting_clarification`，但同样永远不会产出任何东西（BL-01）。
2. 降级提示与分组呈现所依赖的四个结果级字段**不在工具输出契约里**——用户在对话当场看不到降级横幅与分组分区，只有刷新页面或改一次勾选后才出现（BL-02）。前端测试用手写 payload 伪造了这四键，正好掩盖了这个缺口。

---

## BLOCKER

### BL-01：澄清超时出口只改状态、不重驱引擎 → 会话停成 `research`/`running`，RELY-02 的「继续推进」未达成

> **处置：fixed**（commit `e5c80c87`）
>
> resume 出口在事务外经 `build_orchestration_engine` + `adrive_convergence_session_to_pause_or_terminal` 真实续驱（与 `answer_resume` 同源，不新造 engine 工厂）；续驱失败只记 exception、不回退状态。模块 docstring 补写「出口必须真的推进」一节，出口日志加 `final_status`/`final_stage`。守护测试：`test_resume_exit_redrives_engine_out_of_intermediate_state`（断言引擎被续驱且会话落终态，修复前停在 research/running 即失败）、`test_redrive_failure_does_not_roll_back_exit`、`test_fail_exit_does_not_redrive`、`test_exit_log_reports_post_redrive_landing`。

**文件:** `server/delivery/management/commands/expire_pending_clarifications.py:373`（`_aexit_one` 的 resume 分支）

**问题:**

resume 出口只做了一次状态转移：

```373:373:server/delivery/management/commands/expire_pending_clarifications.py
                await service.transition(session, "clarified", stage_state=stage_state)
```

`transition("clarified")` 按 stage graph 把会话推到 `current_stage="research"` / `status="running"`（`builtin_processes.py:294`），**之后没有任何东西调用 `engine.advance` 或 `adrive_convergence_session_to_pause_or_terminal`**：

- 命令自身不构造 engine、不调续驱 helper（全文无 `adrive_` 引用）。
- 全仓 `adrive_convergence_session_to_pause_or_terminal` 的调用方只有 `answer_resume.py` / `plan_research.py` / `subagent/api/callbacks.py` / `orchestration_delegate.py` / `feature_solution_service.py` / `plan_deepen_service.py` —— 全部是**用户/回调触发**的入口，没有周期任务。
- `runapscheduler.py` 的 20 个 job 里没有任何一个扫 `status=running` 的 `ConvergenceSession`。

结果：会话从「停在 `waiting_clarification`」变成「停在 `research`/`running`」。核心红线的字面要求（不得再停在 `waiting_clarification`）满足了，但 RELY-02 的实质要求「带未澄清假设**继续推进**」没有满足——生产事故的成因是「会话等不到产出，agent 绕道徒手编方案」，换个 status 卡住并不能断掉这条绕行。而且新状态更难发现：`running` 在看板上与正常运行不可区分（107-06-SUMMARY 自己也记了这条局限）。

叠加因素：本命令声称「逐字镜像 `check_timeouts.py`」，而**被镜像的那个命令恰恰做了重驱**（`check_timeouts.py:62` `asyncio.run(self._redrive_retry(...))` → `:176` `engine._continue_after_node(...)`）。本命令的模块 docstring 第 16–17 行也写着「异步引擎重驱在事务外 `asyncio.run`」——这句描述与实现不符，只有 `asyncio.run(self._aexit_one(...))`，里面没有引擎。

另外 `_workflow_timed_out` 分支会在**工作流已被标 TIMEOUT** 之后才出口（D-4 纵深条件），此时把会话推到 `running` 更没有承接方：那条工作流已经终态，`WorkflowEventSubscription` 也已 inactive。

**修复建议:**

在 `_aexit_one` 的 resume 分支里接上既有续驱 helper（与 `answer_resume.py` 同源，不新造 engine 工厂）：

```python
# resume 分支：transition 之后必须真的推一步，否则会话停在 research/running 无人驱动
else:
    await service.transition(session, "clarified", stage_state=stage_state)
    try:
        from services.process_runtime import (
            adrive_convergence_session_to_pause_or_terminal,
            build_orchestration_engine,
        )
        engine = build_orchestration_engine()
        session = await adrive_convergence_session_to_pause_or_terminal(engine, session)
    except Exception:
        # 续驱失败不回退状态（transition 已幂等落地），记 exception 后按已出口计
        log.exception("clarification_timeout_exit_redrive_failed")
```

注意两点：(1) 续驱必须在事务外（已满足，`_aexit_one` 本就在事务外）；(2) `adrive_` 自带 `waiting_clarification` / `waiting_event` 短路与 `max_steps` 保护，不会死循环。若判断本 phase 不做重驱，则必须把「resume 后会话无人驱动」写成显式已知缺陷并同步修正命令 docstring 第 16–17 行的描述，不能让 `research/running` 冒充「已继续推进」。

---

### BL-02：工具输出契约缺四个结果级字段 → 降级提示与分组呈现在实时对话链路恒不生效

> **处置：fixed**（commit `5f587a00`）
>
> (a) `RepositoryRelevanceOutput` 补 `router_version`/`degraded`/`degrade_reason`/`block_order` 四个带默认值字段；`_analyze_relevance_core` 改回 `RepositoryRelevanceAnalysis` dataclass 把结果级事实带出来；`degraded` 走与 detail/override 同一派生点（`_derive_degraded` 下沉为 `chat.models.derive_routing_degraded`）。(b) 前端 `groupingEnabled` 改为只看 `block_order?.length === 2`，删掉 `some(c => c.group === 'in_project')` 这条在「正确仓全在跨组」时恰好失效的兜底。(c) 新增后端输出 schema 快照 `tests/agents/fixtures/repository_relevance_output_schema.json`，前端 `routing.test.ts` 从**同一份 schema** 构造 tool-output payload（schema 里没有的键构造不出来），两端契约缺口会同时打红。

**文件:** `server/agents/tools/schemas/repository_relevance.py:56-60`（`RepositoryRelevanceOutput`）、`web/src/stores/chat.ts:1275-1298`

**问题:**

前端在 SSE `part_completed` 时从工具输出解析四个结果级事实：

```1289:1298:web/src/stores/chat.ts
        const traceId = data?.trace_id
        if (data && typeof traceId === 'string') {
          const trace: RoutingDecisionData = {
            ...
            router_version: typeof data.router_version === 'string' ? data.router_version : undefined,
            degraded: typeof data.degraded === 'boolean' ? data.degraded : undefined,
            degrade_reason: data.degrade_reason,
            block_order: Array.isArray(data.block_order) ? data.block_order : undefined,
          }
```

但 `data` 就是 `RepositoryRelevanceOutput.model_dump()`（`repository_relevance.py:458-468`），而该模型只有四个字段：

```56:60:server/agents/tools/schemas/repository_relevance.py
class RepositoryRelevanceOutput(BaseModel):
    candidates: list[RepositoryRelevanceCandidate]
    threshold: float
    total_candidates: int
    trace_id: str
```

即 `router_version` / `degraded` / `degrade_reason` / `block_order` **在生产恒为 undefined**。后果是本 phase 两个用户可见的头条能力在**主路径（对话进行中那一刻）完全不出现**：

- `degraded` undefined → `RoutingDecisionPanel.vue:209` 的 `degraded` 恒 false → 无降级横幅、无 `muted` 徽标灰化、无降级版 tooltip。RELY-03「降级用户可见」不成立。
- `block_order` undefined → `groupingEnabled` 落到兜底 `allCandidates.some(c => c.group === 'in_project')`（`:109`）。**这恰好在最需要分组的场景失效**：当正确仓在跨组、in_project 组为空时（gk-008/gk-009 那类样本），没有任何候选的 `group === 'in_project'` → 分组关闭 → 平铺、无「跨组」徽标、无「更匹配的仓不在本项目关联范围内」置顶提示。ROUTE-01/02 在最有信息量的那一类查询上恰好不生效。
- 用户要看到这些，必须**刷新页面**（`ConversationDetailView` 的 payload 有这四键，`chat/views.py:560-570`）或**改一次勾选**（override 响应回传四键）。

`degrade_reason`/`block_order` 已经正确落库（`repository_relevance.py:304-306`），所以这是纯粹的「出参没带出来」——一行 schema + 一行构造的缺口。

覆盖为什么没抓住：`web/src/stores/__tests__/routing.test.ts:319-339` 手写了一个含四键的 tool-output payload 来断言解析逻辑，而后端从不产生这个形状的 payload。这个用例只验证了前端 parser，没有验证契约两端一致，属于**假阳性守护**。

**修复建议:**

1. 给输出模型补四个带默认值的可选字段（additive，不破 schema snapshot 的 input 半边）：

```python
class RepositoryRelevanceOutput(BaseModel):
    candidates: list[RepositoryRelevanceCandidate]
    threshold: float
    total_candidates: int
    trace_id: str
    # 结果级事实（RELY-03 / ROUTE-01）：与 trace 落库的同一组值，供实时链路直接渲染
    router_version: str = ""
    degraded: bool = False
    degrade_reason: str = ""
    block_order: list[str] = Field(default_factory=list)
```

2. `_analyze_relevance_core` 目前只回 `(candidates, trace_id)`，需要把这四个值一并返回（或返回一个小 dataclass），再由 `analyze_repository_relevance` 填进 `RepositoryRelevanceOutput`。`degraded` 用与后端同一个派生点（`chat/views.py:_derive_degraded`），不要在工具侧另写一遍版本字面判定。
3. 加一条**契约一致性**测试：从真实的 `analyze_repository_relevance` 输出里断言这四键存在，而不是在前端手写 payload。

---

## MAJOR

### MJ-01：重试与降级分类按具体异常类名子串匹配 → 漏掉 429/5xx，却把 400 判为可重试

> **处置：fixed**（commit `0d92a841`）
>
> 分类与重试判定改为**状态码优先、类名子串兜底**：新增纯函数 `is_retryable_upstream_failure`，429/5xx（含 529）/408/425 与无状态码的连接、超时类可重试；4xx 客户端错误（400/401/403/404/422）归 `upstream_error` 但不重试。`classify_degrade_reason` 增 `status_code` 参数，408/504 归 `timeout`。用**真实 openai SDK 异常实例**（带真实 `status_code`）参数化钉住上表，另有纯函数层 17 组参数化用例；`settings.py` 的重试语义注释同步订正。

**文件:** `server/codegraph/services/repo_router_ranking.py:55-56`、`server/codegraph/services/repo_router_v2.py:294-297`

**问题:**

分类只看 `type(exc).__name__` 的子串：

```55:56:server/codegraph/services/repo_router_ranking.py
_TIMEOUT_TOKENS = ("Timeout",)
_UPSTREAM_TOKENS = ("Connect", "APIStatus", "APIError", "HTTPStatus", "BadRequest")
```

`APIStatusError` 是 openai/anthropic SDK 的**基类**，具体抛出的永远是子类，子类名里不含 "APIStatus"。实测（在本仓 venv 里直接调 `classify_degrade_reason`）：

| 异常类名 | 分类结果 | 是否重试 | 用户看到的原因 |
|---|---|---|---|
| `APITimeoutError` | `timeout` | ✅ | 上游超时 |
| `APIConnectionError` | `upstream_error` | ✅ | 网关错误 |
| `RateLimitError`（429） | **`unknown`** | ❌ | **未知原因** |
| `InternalServerError`（500） | **`unknown`** | ❌ | **未知原因** |
| `OverloadedError`（529） | **`unknown`** | ❌ | **未知原因** |
| `BadRequestError`（400） | `upstream_error` | **✅（无意义）** | 网关错误 |

两个后果：

1. **RELY-05 的「1 次重试」在最该重试的场景不生效。** 429/500/502/503/529 是上游抖动的主要形态，恰好都不重试；而 `settings.py:377-383` 的注释还写着「重试只在快速失败（网关错误 / 连接失败）场景生效」——按当前分类，"网关错误" 这一类实际只覆盖了连接失败。
2. **400 被重试**，与 `_is_retryable_stage1_error` 的 docstring 明确写的「不可重试类（解析错误、**参数错误**等确定性失败）直接上抛：重试一次结果一样，只会白白吃掉总预算」直接矛盾——多烧一次上游调用、多一行 `ModelUsageRecord`、把用户可见降级推迟一个 RTT。

**修复建议:**

按异常**继承链**判定而不是类名子串，并显式把 429/5xx 归入可重试：

```python
_TIMEOUT_TOKENS = ("Timeout",)
# 5xx / 429 / 连接类：值得重试且应显示「网关错误」
_UPSTREAM_TOKENS = (
    "Connect", "APIStatus", "APIError", "HTTPStatus",
    "RateLimit", "InternalServer", "ServiceUnavailable", "Unavailable",
    "Overloaded", "BadGateway", "Timeout429",
)
# 确定性失败：分类为 upstream_error 但**不重试**（4xx 客户端错误）
_NON_RETRYABLE_TOKENS = ("BadRequest", "Authentication", "PermissionDenied", "NotFound", "Unprocessable")
```

并让 `_is_retryable_stage1_error` 先排除 `_NON_RETRYABLE_TOKENS`。补一条参数化单测把上表六个类名钉住——这是纯字符串映射，穷举成本极低。

---

### MJ-02：`auto_selected` 现由 `score_ranked` 排序后的首位决定，α 可改变编排是否自动推进

> **处置：fixed**（commit `c084039a`）
>
> 取「保留现状 + 订正文档 + 补护栏 + 加观测」方案：注释改写为如实描述（α 确实参与 auto_selected 判定，这是凸组合的设计后果；不变的是**组别**不进决策路径），并说明方向单调安全的理由；新增 `RepoRouteResultV2.auto_selected_suppressed_by_alpha` 且进 `repo_router_v2_scored` 事件；护栏测试锁定「α 只抑制不误开」（α ∈ {0, 0.35, 0.9, 1.0} 参数化）、抑制可观测、无 high 时不误报抑制。

**文件:** `server/codegraph/services/repo_router_v2.py:626-634`

**问题:**

同一处的注释宣称了一个不成立的不变量：

```632:634:server/codegraph/services/repo_router_v2.py
        # auto_selected 读**扁平列表首位**（即全局最高分候选）：block ranking 是
        # 呈现层置顶，不得改变编排是否自动推进——否则组别就间接进了决策路径。
        auto_selected = bool(final) and final[0].confidence == "high"
```

`final` 来自 `_apply_presentation`，有分组上下文时按 `_rank_sort_key` → `_rank_value` → **`score_ranked`** 排序（`:417-425`）。`score_ranked = (1-α)·S_final + α·S_llm`，所以「扁平列表首位」不再是「Stage 0 最高分候选」，而是「凸组合后最高分候选」。由于 `confidence` 只在 Stage 0 位次 0 上才可能是 `high`（`_deterministic_confidence`，`:1023-1041`），α 把某个 Stage 0 第二名顶到首位时，`final[0].confidence` 变成 `medium`/`low` → `auto_selected` 由 `True` 翻成 `False`。

即：**LLM 经 α 重新获得了对「编排是否自动推进」的影响力**，这正是 RELY-04（Phase 105 修完的编排死锁根因）要切断的那条路径。`_stage1_llm_reasoning:1607-1609` 还专门写了「confidence 的输入恒为 Stage 0 分数列表，绝不换成凸组合后的旁路分」——confidence 本身确实没换，但**消费 confidence 的那个下标换了**，等效地把决策权还了回去。

缓解事实（值得记录）：方向是单调安全的——α 只能把 `auto_selected` 从 `True` 变 `False`（更多人工确认），不可能凭空造出 `high`。所以这不是「错误自动推进」的风险，而是「本该自动推进的场景被 α 静默拦下」的行为回归。

**当前无任何护栏**：既无断言锁定这个单调性，也无观测能区分「α 抑制了自动推进」与「本来就不该自动推进」。

**修复建议:**

二选一，但必须显式：

- **（推荐）让 `auto_selected` 读 Stage 0 首位而非呈现层首位**，把决策与呈现彻底解耦：

```python
# auto_selected 只看确定性 confidence == high 的那个候选是否存在（它只可能是 Stage 0 首位），
# 与 score_ranked 排序结果无关——呈现层置顶与凸组合都不得进决策路径。
auto_selected = any(c.confidence == "high" for c in final)
```

- 或保留现状但补一条测试锁定单调性（`α > 0` 只能让 `auto_selected` 由 True→False，绝不 False→True），并在 `repo_router_v2_scored` 事件里加一个 `auto_selected_suppressed_by_alpha` 布尔，让抑制可观测。同时修正 `:632-634` 的注释——它现在描述的是一个不成立的保证。

---

## MINOR

### MN-01：前端 `group` 空串兜底未实现（`??` 对 `""` 无效）→ 分组启用时该候选从两个分区同时消失

> **处置：fixed**（commit `9d6e485d`）
>
> `c.group || 'global'`，类型改 `group?: RoutingGroup | ''` 与运行时形状对齐；补空串候选不得从两个分区同时消失的用例。

**文件:** `web/src/components/chat/RoutingDecisionPanel.vue:81-83`

后端契约明确写着「缺省（空串）由前端视为 global」（`schemas/repository_relevance.py:43`、`types/routing.ts:41`），但实现用的是 `??`：

```81:83:web/src/components/chat/RoutingDecisionPanel.vue
function groupOf(c: RoutingCandidate): RoutingGroup {
  return c.group ?? 'global'
}
```

`"" ?? 'global'` 返回 `""`。分组启用时 `members = sorted.filter(c => groupOf(c) === group)` 对 `'in_project'` 与 `'global'` 都不匹配 → 该候选**在两个分区里都不渲染**，而表头「路由决策（N 个仓库相关）」仍把它计入 `allCandidates.length`，用户看到「说有 5 个，只列出 4 个」。

同时 TS 类型 `group?: RoutingGroup` 与运行时实际值 `""` 不一致——类型系统在这里给不出保护。

当前生产不可达（`_apply_presentation` 总会标注 group；legacy 路径的 `block_order` 为 `[]` 走平铺分支），但这条兜底路径正是为「后端没标注」准备的，坏在了它唯一要处理的输入上。

**修复:** `return c.group || 'global'`，并把类型改成 `group?: RoutingGroup | ''` 让运行时形状与类型对齐。

### MN-02：无分组上下文时候选列表不按 `score_ranked` 排序，与有上下文路径语义不一致

> **处置：fixed**（commit `bf96dfa9`）
>
> 早退分支改 `sorted(candidates, key=_rank_sort_key)[:top_k]`，两条路径「首位 = 最佳」同口径；补无上下文路径按 rank key 排序的用例。

**文件:** `server/codegraph/services/repo_router_v2.py:412-415`

```412:415:server/codegraph/services/repo_router_v2.py
    if project_repo_ids is None:
        return candidates[:top_k], decide_block_order(
            None, None, delta=delta, has_project_context=False
        )
```

这条早退只截断不排序，但此时 `score_ranked` **已经写好了**（`:1686` 在 `_apply_presentation` 之前执行）。于是同一个 API 出现两种排序口径：有项目上下文 → 列表按 `_rank_value` 降序；无项目上下文（MCP / REST / `session.work_item_id is None` 的编排）→ 列表按裁剪后的 LLM 排列。`_rank_value` 的 docstring 自称是「排序比较值的唯一所有者」，但它在这条路径上根本没被用来排序。

后果是「首位 = 最佳」这个消费方普遍依赖的隐式契约在两条路径上不同；前端又会按 `rankKey` 重排，与后端扁平顺序不一致。

**修复:** 早退分支同样用 `sorted(candidates, key=_rank_sort_key)[:top_k]`。若确实要保留「LLM 排列原样透出」的语义，就不要在这条路径上写 `score_ranked`（保持 `None`），让两件事至少自洽。

### MN-03：`v2_candidates[:top_k]` 可能把 in_project 组整组截空，而 `block_order` 仍报长度 2

> **处置：fixed**（commit `37874e69`）
>
> 新增 `_truncate_by_group_quota`：每个非空组先各占 1 个名额、其余按全局顺序补齐，输出仍保持全局 `score_ranked` 降序；返回上限仍是 `top_k`（工具契约不变）。补纯函数三条 + 真实工具路径一条用例。

**文件:** `server/agents/tools/repository_relevance.py:293`

router 现在按组各取 `top_k` 后并集（≤ 2·top_k），并按全局 `score_ranked` 排序；工具侧再 `[:top_k]` 截断。当全局组分数整体占优时，截断后可能**一个 in_project 候选都不剩**，而落库的 `block_order` 来自 router 结果、仍是长度 2 → 前端启用分组、`in_project` 块因 `total === 0` 被 `filter` 掉。ROUTE-01「组内各展示 Top-3」在 `top_k` 较小时无法保证。

`:287-292` 的注释已经承认这个取舍（不改工具契约），但没有保护「每组至少保留 1 条」这个更重要的产品语义。

**修复:** 截断改为按组配额而非全局前 N，例如每组各留 `max(1, top_k // 2)` 后再按 `score_ranked` 补齐到 `top_k`；或在 `total_candidates` 之外补一个 `truncated_groups` 字段让丢失可见。

### MN-04：新增 gauge 块的 `error=str(exc)` 未脱敏

> **处置：fixed**（commit `8012d0d1`）
>
> `metric_sampling` 的 gauge 块与 `expire_pending_clarifications` 的 unsupported_stage 告警都改走 `redact_secrets_in_text`。

**文件:** `server/system/metric_sampling.py:180-186`

```180:186:server/system/metric_sampling.py
        except Exception as exc:  # noqa: BLE001 — 单块失败只丢该行，绝不吞掉整帧
            logger.warning(
                "gauge_backlog_clarifications_failed",
                category="sampling",
                component="metric_sampling",
                error=str(exc),
            )
```

强制规范要求异常文本一律过 `redact_secrets_in_text`（`.cursor/rules/observability-logging.mdc`「脱敏不可绕过」）。这里是 DB 异常，`OperationalError` 在部分驱动下会回显连接串（含口令）。本 phase 在 `repo_router_v2` 里刚把两处 `str(exc)[:200]` 改成源头脱敏，同一条纪律不该在新代码里退回去。

**修复:** `error=redact_secrets_in_text(str(exc))`（`from common.logging import redact_secrets_in_text`，与 `repo_group_scope.py:92` 同款函数级 import）。`expire_pending_clarifications.py:380` 的 `error=str(exc)`（stage graph 的 `ValueError`）风险低但同理，建议一并统一。

### MN-05：`initiated_by_user_id` 只 `logger.bind` 未进 contextvars

> **处置：fixed**（commit `311f514a`）
>
> `_aexit_one` 用 `structlog.contextvars.bound_contextvars(initiated_by_user_id, user_id, source="scheduler")` 包住整个出口动作，出口本体拆到 `_aexit_one_bound`；补「下游模块内部读得到归因」与「绑定不泄漏到 scheduler 主循环」两条用例。

**文件:** `server/delivery/management/commands/expire_pending_clarifications.py:338-346`

规范要求后台任务「显式携带 `initiated_by_user_id` 并**在 worker 入口重新 bind**」。这里用的是 `logger.bind(...)` 返回的**本地** logger，只影响本命令自己打的日志；`ConvergenceSessionService.transition` / `_fail` / `_emit_event` 以及被它们触发的其他模块日志拿不到该字段（它们各自 `structlog.get_logger(__name__)`）。而 `_record_stage1_usage` 那类消费方读的正是 `structlog.contextvars.get_contextvars()`。

**修复:** 在 `_aexit_one` 入口用 `structlog.contextvars.bound_contextvars(initiated_by_user_id=initiated_by, source="scheduler")` 包住整个出口动作，本地 `logger.bind` 可保留用于事件专属 kv。

### MN-06：D-4 仍留约 10 分钟矛盾态窗口，且出口会在已 TIMEOUT 的工作流上「继续推进」

> **处置：fixed**（commit `1404db2e`）
>
> `CLARIFICATION_EXPIRY_CHECK_INTERVAL_SECONDS` 默认 600 → 60，与 `check_timeouts` 对齐，矛盾态窗口压到 1/10；`.env.example` 与 runapscheduler 注释同步（注释保留「改过 trigger 间隔需清 django_apscheduler_djangojob 旧行」的运维提示）。未采用「让 check_timeouts 反向触发澄清出口」的方案：会在工作流侧引入对 delivery 的依赖，改动面大于收益。

**文件:** `server/friday/settings.py:399-403`、`server/workflows/nodes/ai/plan_research.py:412-418`

订阅超时与澄清超时现在读同一个 `CLARIFICATION_TIMEOUT_HOURS`（D-4 的核心要求达成），但两侧扫描频率差一个数量级：`check_timeouts` 每 60s、澄清扫描每 600s。到期瞬间 `check_timeouts` 几乎必然先跑，把 `NodeExecution` 标 TIMEOUT、`WorkflowExecution` 标 TIMEOUT 并写 `error_message`，随后最多 10 分钟内澄清扫描才出口。CONTEXT 的原话是「**任何时刻**都不得存在『工作流已判超时而会话仍在等』的窗口」——窗口从 23 小时压到 ≤10 分钟是巨大改进，但不是零。

更实际的问题：出口发生时工作流已经终态，此时把会话推到 `research`/`running`（叠加 BL-01 的无重驱）产出的是一个挂在死工作流上的孤儿会话。

**修复:** 把 `CLARIFICATION_EXPIRY_CHECK_INTERVAL_SECONDS` 默认降到 60s（扫描本身是两条索引查询，成本可忽略；注释里担心的 SQLite 写锁争用只在真有出口目标时才写库），或让 `check_timeouts` 在 `action="fail"` 且存在关联 `ConvergenceSession` 时先触发澄清出口再标工作流超时。

### MN-07：Stage 1 四个配置读取未走 fail-safe

> **处置：fixed**（commit `257cf05f`）
>
> 新增 `_stage1_int(key, minimum=1)`；`timeout_seconds` 改走 `_stage1_seconds`，三个整数项改走 `_stage1_int`。补四个键各写成空串时仍正常跑 Stage 1 的参数化用例。

**文件:** `server/codegraph/services/repo_router_v2.py:1373-1379`

`total_budget_seconds` / `backoff_base_seconds` 走了 `_stage1_seconds`（非数值/非有限/非正回退默认，绝不抛），但同一段里：

```1373:1379:server/codegraph/services/repo_router_v2.py
        timeout_seconds = float(_stage1_conf("REPO_ROUTER_STAGE1_TIMEOUT_SECONDS"))
        ...
        max_candidates = int(_stage1_conf("REPO_ROUTER_STAGE1_MAX_CANDIDATES"))
        hits_per_repo = int(_stage1_conf("REPO_ROUTER_STAGE1_HITS_PER_REPO"))
        cache_ttl = int(_stage1_conf("REPO_ROUTER_STAGE1_CACHE_TTL_SECONDS"))
```

四处裸 `float()`/`int()`。运维把任一项写成 `""` 或非数值 → `ValueError` → 被 `route()` 的兜底 except 吃掉 → 每次路由都静默降级 Stage 0，且降级原因是 `unknown`（`ValueError` 不命中任何 token），排查方向被彻底带偏。`clamp_ranking_params` / `_stage1_seconds` 建立的 fail-safe 纪律在这里断了。

**修复:** `timeout_seconds` 改用 `_stage1_seconds`；三个整数项加一个同款 `_stage1_int(key, minimum=1)`。

### MN-08：manual override 未校验 `original.block_order` 类型

> **处置：fixed**（commit `fd456919`）
>
> 抽 `_safe_block_order(value)` 供 detail / override 写入 / override 响应三处共用；补 dict/str/int 三种脏值都落 `[]` 的参数化用例（NULL 由 DB NOT NULL 约束挡住）。

**文件:** `server/chat/views.py:2758` / `:2784`

`ConversationDetailView` 对脏数据做了防御（`:566-570` 的 `isinstance(..., list)`），但 override 路径没有：

```2758:2758:server/chat/views.py
            block_order=list(original.block_order or []),
```

历史/脏行里 `block_order` 是 dict 时 `list(dict)` 得到键名列表、是 str 时得到字符列表，被原样写进新 trace 并在 `:2784` 直接回给前端（也未过 isinstance）。前端 `blockOrder` 只检查 `length === 2`，两元素的脏值会让 `GROUP_LABELS[block.group]` 渲染空标题、两个分区都 `total === 0` 被过滤 → **一个候选都不显示**。

**修复:** 复用 detail 视图同款守卫，抽一个 `_safe_block_order(value)` 供两处调用。

### MN-09：D-1 放开硬过滤后透出的不只是仓名

> **处置：fixed**（commit `813e6f32`）
>
> 采纳建议 (1)：`repo_router_adapter._resolve_repository_ids` 与工具侧两处注释订正为「不绕过任何现存权限检查，但透出面不止仓名——还含跨组仓的能力树节点路径、sub_project 与 LLM reasoning，是一个新的元数据面」，并记下收窄时的现成判据（`group == global`）与改动落点。建议 (2)（跨组 evidence 降级为仅仓名）**未采纳**：它会削掉分组呈现的核心信息量（用户正是靠 evidence 判断该不该跨组协作），属产品取舍而非缺陷修复，留待有明确合规要求时再议。

**文件:** `server/services/process_runtime/repo_router_adapter.py:86-90`、`server/agents/tools/repository_relevance.py:221-225`

两处的论证是「沿用 `mcp_tools/views.py` 的 `RouteRepositoriesView` 与 `repositories/route_views.py` 两个已上线全库入口的既有判断（**仓名不敏感**）→ 不新增可见性面」。我核实了前提：这两个入口确实只有 `permission_classes = [IsAuthenticated]`（`repositories/route_views.py:28`、`mcp_tools/views.py:239`），无 per-user/per-space 过滤——**所以这不是绕过任何现存权限检查**，结论方向正确。

但论证的范围不够：实际透出的 `evidence` 是「命中能力节点: `<node_path>` / `<node_path>` / `<node_path>`」+ LLM 的 `reasoning` + `sub_project`（`repository_relevance.py:249-257`），也就是**其他空间仓库的能力树节点路径、子应用名与模型对其结构的推理**，不止仓名。chat 入口从「空间内仓」放宽到「全库」，对空间成员而言这是一个新的元数据面。

**修复:** 不必回退 D-1（分组呈现依赖它），但建议：(1) 把「跨组候选透出 node_path/reasoning」写进 CONTEXT 的安全裁决段，别让后续评审只看到「仓名不敏感」；(2) 考虑跨组候选的 evidence 降级为仅仓名 + 「跨组，详情需申请访问」——`group == global` 已是现成判据，改动面只在这一处映射。

---

## INFO

### IN-01：`_pending_round` 每轮 2 次 `exists()` 查询

> **处置：fixed**（commit `c7c415da`）
>
> `_pending_round` 改一次 `annotate(Count(...), Count(..., filter=Q(...)))` 聚合，去掉每轮两条 `exists()`。

**文件:** `server/delivery/management/commands/expire_pending_clarifications.py:298-309`

外层遍历未答轮，内层每轮两条 `exists()`。默认 `CLARIFICATION_EXPIRY_SCAN_LIMIT=200` 且这些查询在 `atomic + select_for_update` 事务内 → 最坏 400+ 次往返都在持锁事务里。10 分钟一次的任务量级可接受，但持锁时长与 limit 线性相关。可用一次 `annotate(Count(...))`/`values` 聚合替掉内层循环。

### IN-02：迁移文件名与内容不符

> **处置：deferred**
>
> 迁移已 applied，改名会让已部署实例的 `django_migrations` 与文件名不一致，风险大于可读性收益（评审自身也标注「不宜改名」）。内容本身 additive、可逆，无需处理。

**文件:** `server/chat/migrations/0032_repositoryroutingtrace_degrade_reason.py`

文件名只提 `degrade_reason`，实际含 `degrade_reason` 与 `block_order` 两个 `AddField`。纯可读性问题（迁移已 applied 后不宜改名）。内容本身 additive、无 `RunPython`、可逆，符合要求。

### IN-03：`blend_ranked_scores` 的 N 含无效 id

> **处置：fixed**（commit `72dbce52`）
>
> `blend_ranked_scores` 先过滤不在 `stage0_scores` 的 id 再算 `n` 与 `idx`；补「含无效 id 的输入与等价纯净输入结果完全一致」的用例。

**文件:** `server/codegraph/services/repo_router_ranking.py:193-201`

`n = len(llm_order)` 包含不在 `stage0_scores` 里的 id，那些 id 被 `continue` 跳过但仍占据 `idx` 与 `n` → 有效候选的 `S_llm` 被系统性压低。生产路径不可达（调用侧 `clamped_order` 与 `candidates` 同集，实测确认），但这是防御分支自己引入的偏差。改成先过滤再算 `n` 即可。

### IN-04：in_project 组为空时仍展示置顶因果句

> **处置：fixed**（commit `41a01ce9`）
>
> 本项目组无候选时置顶提示换成陈述句「本项目关联范围内没有匹配的仓库」；补对应用例。

**文件:** `web/src/components/chat/RoutingDecisionPanel.vue:153-156`

`decide_block_order` 在 `in_project_top is None`（本项目组无候选）时返回 `["global", "in_project"]`，前端据 `blockOrder[0] === 'global'` 展示「更匹配的仓不在本项目关联范围内」。此时并没有发生 delta 迟滞比较，也没有被压下去的对比对象。文案在语义上仍成立（本项目确实没有匹配仓），但「更匹配」暗示了一次比较。若要精确，可在 in_project 块 `total === 0` 时换成「本项目关联范围内没有匹配的仓库」。

---

## 逐项回应评审重点

| # | 重点 | 结论 |
|---|---|---|
| 1 | D-3 硬约束 | **通过。** `score_ranked` 唯一写入点 `repo_router_v2.py:1686`，不触碰 `score`/`breakdown`；三处 `Σbreakdown == score` 断言在位且通过（后端 1e-9 ×2、前端 1e-6） |
| 2 | 有界重排正确性 | **后置条件与 base 语义通过**（穷举 9460 组零违规）；**K 预算在主路径生效**（裁剪产物写回顺序），副作用逐项核对后只外溢到 `auto_selected`（MJ-02）；**总延迟为硬上界**（per-attempt `min(timeout, remaining)` + 退避受剩余预算封顶 + langchain 重试关闭）。重试**分类**有缺陷（MJ-01） |
| 3 | D-1 回归面 | **无越权/无绕过现存检查**（两个既有全库入口确认只有 `IsAuthenticated`）；6 个未改消费方零影响成立（`repository_ids` 语义逐字未动，新字段全带默认值）；`auto_selected` 可被 α 改变**属实且无护栏**（MJ-02，方向单调安全）；透出内容超出「仓名」论证范围（MN-09） |
| 4 | 澄清出口幂等与并发 | **复用 CAS、未自建锁，通过**；`_fail` CAS 未命中的静默返回**已闭合**（终态核对基于 `_fail_sync` 会同步内存 status，判据有效）；扫描确实事务内只收集、事务外执行——**但事务外只做了 transition，没有重驱引擎（BL-01）** |
| 5 | 必达留痕 | **4 个静默 return 全部补齐**（`no_questions`/`no_space`/`no_project`/`no_chat_id`）+ 第 5 条 `send_failed`，整体 best-effort 不反噬；`_maybe_advance_container` 幂等锚改 `answered_at__isnull` **未引入新问题**（全仓无 `container_status="skipped"` 写入方，唯一其他取值 `delivery_failed` 正是要放行的场景） |
| 6 | 安全/脱敏 | **降级原因闭集封闭**（函数签名结构上收不到异常实例；DB 列长 32；前端未命中回「未知原因」，DOM 无原始串）；**两处 `str(exc)[:200]` 都已改为源头脱敏**；trace 两列与 detail payload 无敏感信息。新代码引入一处未脱敏 `str(exc)`（MN-04） |
| 7 | 可观测性规范 | 事件均带 `category`/`component`；定时任务 wrapper 固定 `user_id="system"`、命令逐条携带 `initiated_by_user_id`（但只 `logger.bind`，未进 contextvars，MN-05）；`backlog.pending_clarifications` gauge 已入 `_GAUGE_NAMES` 且零值也落；Stage 1 `ModelUsageRecord` 埋点口径正确（一次上游调用一行、缓存命中零行、不伪造 TTFT） |
| 8 | 前端 | 分区渲染尊重 `block_order`、全局重排已删；override 兜底用 `??` 正确；未知降级原因回退「未知原因」且 DOM 无原始串；零新色板零新依赖；历史 trace 兼容。`group` 空串兜底用错了运算符（MN-01）；**四个结果级字段在实时链路拿不到（BL-02）** |
| 9 | 迁移 | **通过。** 两个 `AddField` 均带默认值，additive、无 `RunPython`、可逆；文件名与内容轻微不符（IN-02） |

---

_Reviewed: 2026-07-30T01:05:00Z_
_Reviewer: gsd-code-reviewer_
_Depth: deep_
