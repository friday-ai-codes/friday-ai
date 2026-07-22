---
phase: 101-completion-loop
plan: 03
status: complete
date: 2026-07-22
requirements: [LOOP-02, LOOP-03]
key-files:
  created:
    - server/tests/workflows/test_coding_writeback.py
    - server/tests/test_coding_graph_completion.py
  modified:
    - server/delivery/services/coding_completion.py
    - server/delivery/services/__init__.py
    - server/mcp_tools/learning_case_extraction.py
    - server/workflows/nodes/ai/coding.py
    - server/orchestration/coding_graph.py
    - server/mcp_tools/work_item_execution_service.py
    - server/tests/delivery/test_coding_completion.py
    - server/tests/mcp_tools/test_work_item_execution.py
    - web/src/types/workflow/schemas.ts
    - docs/guide/workflows.md
commits:
  - 317b48c6
  - 93f4be4b
  - 6adb1dff
  - 4ee87e38
  - c2749bb9
---

# Phase 101 Plan 03: 三链路完工闭环锚点接线 Summary

**一句话**：三元组反查器（workflow 链 `plan_version_id → ArtifactVersion → artifact.work_item`、chat 链 `content__chat_coding_plan_id` JSON 键 seam）+ 三链路（workflow / chat / MCP）在"MR 结果已知"锚点统一接公共回写与 learning case 后台提炼——workflow 侧 `write_back` 三态守门（模板默认开、**存量缺键 fallback 零行为变化**）、chat 侧无配置面能反查即回写、全部 best-effort fail-soft 不挂容器回调。

## What Was Built

### Task 1: 三元组反查器 + aextract_for_session 便捷入口（commit `317b48c6`）

- `server/delivery/services/coding_completion.py`
  - `@dataclass(frozen=True) WorkItemTriple`：`feishu_project_key/work_item_type/work_item_id/title/space_id`；`space_id` 供 `awrite_back` 免二次反查（`awrite_back` 新增可选 `space_id` 入参，`space=None` 时优先经 id 直取 Space，再退 `feishu_project_key` 反查——向后兼容）。
  - `aresolve_triple_from_plan_version`：镜像 `render_traceability_section` 的标量链路（`values() + afirst()`，async 安全）；任一跳空 → None 静默，异常 → None + `triple_resolve_failed`（warning/sampling）。
  - `aresolve_triple_for_coding_session`：hop 经 `ArtifactVersion.objects.filter(content__chat_coding_plan_id=str(coding_plan_id))`（JSONField key transform）；docstring 写明 seam 现状（该键当前无写入方 → 存量 chat 会话全部"反查不到自然跳过"，零行为变化）与点亮条件（未来编排/桥接写入该键后自动点亮；禁止重新引入 chat→delivery eager 投影）。
  - 私有 helper `_atriple_from_work_item_id` 两链共用。
- `server/mcp_tools/learning_case_extraction.py` 新增 `aextract_for_session(session_id, *, requirement_text, work_item_type, work_item_id, pr_url, initiated_by_user_id)`：标量取 `SubAgentSession`（status 做状态门入参）+ `TaskResult`（text_output/branch/pr_url/modified_files，无则空）后转调 `aextract_learning_case`；全程兜底 try/except（后台任务里跑，异常只记日志）。
- `__init__.py` re-export `WorkItemTriple` + 两个 resolver。
- 测试 +4：workflow 链正向（真实 WorkItem+Artifact+ArtifactVersion 命中三元组含 space_id）、断链（无 work_item / None / 非法 UUID → None）、chat 链正向（content 埋键命中）、现状路径（普通 coding_plan → None，未绑定不触 DB）。

### Task 2: workflow 锚点——守门 + 接线 + 前端同步 + 升级说明（commit `93f4be4b`）

- `server/workflows/nodes/ai/coding.py`
  - `config_schema` 新增 `write_back`（boolean，title"回写飞书工作项"，default True——仅影响新建节点；`required` 未加）。
  - `_finalize_and_notify` 在 INGEST-02 投递之后、`emit_sub_step("create_mr", COMPLETED)` 之前插完工闭环块，整块 try/except 吞为 `coding_completion_loop_failed`（warning），绝不影响 NodeResult；实现拆为私有方法 `_run_completion_loop`（Claude's Discretion）。
  - 三元组反查：主链 `plan_version_id` 反查优先；None 时 trigger fallback（`feishu_project_key`/`feishu_work_item_id`/`feishu_work_item_type` **三键齐备**才构造，work_item_id 转 int 失败视为无——T-101-03-02）。
  - **三态守门（P3）**：键在且 False → 全跳过；键在且 True → 有 triple 才回写、无 triple 记 `writeback_skipped`（reason=no_work_item，caller）；**键不在（存量）→ 有 triple 才回写、无 triple debug 级静默（零行为变化）**。
  - 回写执行：`mr_results` + `failed_repos` 映射 `RepoResult`（status completed/failed），`awrite_back(..., space_id=triple.space_id, initiated_by_user_id=triggered_by)`；`triggered_by` 经 `workflow_execution.triggered_by_id` 标量（None → service 记 system）；不传 doc 参数。
  - 提炼调度：逐 `completed_session_id` 经 `run_in_background`（不 await Future）调 `aextract_for_session`，pr_url 按 session→repo→mr_url 映射取（取不到空）；与回写互不依赖。
- `web/src/types/workflow/schemas.ts` `aiCodingConfigSchema` 追加 `write_back: z.boolean().default(true)`；`pnpm run type-check`（vue-tsc）通过。
- `docs/guide/workflows.md` ai_coding 小节：配置表新增 `write_back` 行 + 升级说明 warning 块（存量缺键语义 / 显式开关行为 / 失败只记事件不重试 / 与 `notify_feishu_im` 的"业务留痕 vs 即时通知"分工）。
- 新建 `server/tests/workflows/test_coding_writeback.py`（6 用例）：legacy 缺键+无 triple 零变化（无 writeback_skipped 噪音断言，capture_logs）、legacy 缺键+有 triple 回写入参正确、显式 False 不回写、显式 True+无 triple 记 writeback_skipped、提炼逐 session 调度、闭环抛异常 NodeResult 不受影响。

### Task 3: chat 锚点——create_pr_or_skip_node（commit `6adb1dff`）

- `server/orchestration/coding_graph.py` 新增模块级 `_run_completion_loop(coding_session, *, pr_url, write_back)`：
  - 归因：`Conversation.objects.filter(id=conversation_id).values_list("created_by_id", flat=True).afirst()` 标量（取不到 fail-soft None → system）。
  - 回写（仅 PR 成功分支 `write_back=True`）：`aresolve_triple_for_coding_session` 反查，None → debug 静默（无会话级开关——CONTEXT 锁定"避免新配置面"）；有 triple → 单元素 `RepoResult(repo.name, "completed", branch_name, mr_url)`，title 取 `coding_plan.title`（select_related 直取）空则"编码任务"。
  - 提炼：`subagent_session_id` 非空即调度（`session_id = str(coding_session.subagent_session.session_id)`，L630 同款访问先例）；requirement_text 取 plan title 或 tech_plan 前 500 字。
  - PR 成功分支在 `store_coding_complete_to_message` 之后、return 之前接 `write_back=True`；**skip-PR 分支不回写**（`write_back=False`）但提炼照常触发（代码注释注明 LOOP-03"任一链路编码成功完成"语义，pr_url 传 ""）；失败分支未动。两处均整块 try/except 吞 `coding_graph_completion_loop_failed`。
- 新建 `server/tests/test_coding_graph_completion.py`（4 用例）：PR 成功+triple → 回写一次（入参断言）+调度一次+返回值不变；PR 成功+triple None → 不回写、提炼仍调度、返回值不变；skip-PR → 不回写、提炼调度、branch_url 不变；反查器 raise → 返回值不变。既有 `test_coding_session_graph.py` 32 用例零回归。

### Task 4: MCP 锚点——execute_work_item_repo_tasks（commit `4ee87e38`）

- `server/mcp_tools/work_item_execution_service.py` 在 write_back 块之后、`status_values` 计算之前插提炼调度块（整块 try/except 吞 `learning_case_schedule_failed`）：逐 `COMPLETED` 且 `execution_trace_id` 非空的 task，标量取 `subagent_session__session_id`，非空即 `run_in_background` 调度 `aextract_for_session(sid, requirement_text=technical_plan.title, work_item_type/work_item_id=方案三元组, pr_url=task.mr_url, initiated_by_user_id=str(run.user_id) or None)`。锚点在 `_execute_one_task` 内 MR 创建之后——符合 STATE"不挂容器回调"。模块新增 structlog logger。
- 测试 +3：双仓 COMPLETED（含 subagent_session）/FAILED → 仅 COMPLETED 仓调度且 factory 执行后入参（session_id/三元组/pr_url/title）逐项断言；COMPLETED 无 execution_trace → 不调度；`run_in_background` raise → 返回值零影响。

### style（commit `c2749bb9`）

新增代码段对齐 `ruff format`（6 处单表达式收拢 + 新测试文件整体 format）；存量漂移行（改造前已存在）不动。

## Deviations from Plan

1. **[Rule 3 - 计划内缺口] `_finalize_and_notify` 无 session→repo 映射**：plan 要求提炼 pr_url 取"该 session 对应仓的 mr_url"，但该方法只收 `completed_session_ids` 列表。在两个调用点（单 wave `pending_sessions` 循环 / wave `RepoCodingTask` 循环）顺手构建 `session_repo_map` 并作为**可选参数**（默认 None）传入——两个调用方本就持有配对信息，零额外查询、签名向后兼容。
2. **[微调] chat 侧归因/标题取值内层 fail-soft**：`Conversation` 标量查询与 `coding_plan.title` 取值各自 try/except 兜底（归因取不到不应连带杀死提炼调度）——比 plan 的"整块吞"更细一层，语义仍是 best-effort。
3. **[Scope boundary] 存量腐坏测试**：`tests/test_sub_step_coding_node.py::test_plan_generation_node_still_works` 引用不存在的模块 `workflows.nodes.ai.plan_generation`（ModuleNotFoundError，与本次改动无关），已记 `deferred-items.md`，不修。
4. **[Scope boundary] 既有 format 漂移不动**：`coding_graph.py` / `work_item_execution_service.py` / `test_work_item_execution.py` 的 `ruff format --check` 报告中，非本次新增的旧行漂移一律保留原样，仅新增段对齐。
5. **[流程偏差自纠] 误用一次 `git stash`/`git stash pop`**：验证存量失败时误用了被禁的 stash（幸运无损——pop 成功、栈已清空、工作区改动经逐文件核对完好）。后续排查改用只读手段，不再触碰 stash。

## Known Stubs

- **chat 反查链 seam 待点亮**（有意为之，plan 锁定）：`ArtifactVersion.content.chat_coding_plan_id` 键当前无写入方，生产 chat 链回写恒走"反查不到自然跳过"（零行为变化）。点亮条件与禁止事项已写进 `aresolve_triple_for_coding_session` docstring；正向路径由测试构造 content 埋键驱动验证。

## Threat Flags

无新增未建模面：trigger fallback 三键齐备守门（T-101-03-02）、存量三态守门专项用例（T-101-03-01）、后台调度不 await（T-101-03-03）、三链归因逐链透传（T-101-03-04）均按 threat register 落地。

## Verification Evidence

- plan 验证命令全绿（四个测试文件 + 两大锚点宿主零回归，共 69 用例）：

  ```text
  ======================= 69 passed, 19 warnings in 41.33s =======================
  ```

- 补充回归：`test_coding_session_graph_e2e.py` + `test_coding_events.py` 12 passed；`test_coding_node.py`/`test_coding_wave.py`/`test_sub_step_coding_node.py` 29 passed + 1 存量失败（见 Deviation 3）+ 1 xfail。
- `rg -n "write_back" web/src/types/workflow/schemas.ts` → L296 命中 `aiCodingConfigSchema`。
- `rg -n "_handle_completed"` 对五个改动模块 → 零命中（锚点不挂容器回调）。
- `cd web && pnpm run type-check`（vue-tsc --noEmit）通过。
- `ruff check` 全部改动文件无告警；`ruff format --check` 我方新增段干净（存量漂移见 Deviation 4）。

## Self-Check: PASSED

- 5 个关键文件（service/两个新测试/SUMMARY/deferred-items）全部存在。
- 5 个 commit（317b48c6 / 93f4be4b / 6adb1dff / 4ee87e38 / c2749bb9）全部在 git log 可查。
