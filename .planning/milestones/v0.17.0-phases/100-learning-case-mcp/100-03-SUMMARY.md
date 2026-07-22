---
phase: 100-learning-case-mcp
plan: 03
status: complete
date: 2026-07-15
---

# Phase 100 Plan 03: MCP 三类产物入图（normalizer + 写入点钩子 + E2E 边可达性） Summary

**一句话**：McpCodingPlan/McpRepositoryAnalysis/McpCodingExecutionTrace 三 normalizer（kind 复用 tech_plan/document/code_change）+ 5 写入点 `aschedule_ingestion` 钩子 + plan→execution（IMPLEMENTED_BY）/work_item 锚（RELATES_TO 双事件）/chat plan（RELATES_TO 可反查）边关系 + 端到端边可达性与幂等自动化断言。

## What Was Built

### Task 1: mcp_repository_analysis + mcp_coding_plan normalizer

- `server/knowledge/sources/mcp_repository_analysis.py`
  - 单事件：`kind=document`、`origin=mcp`、`source_kind="mcp_repository_analysis"`；content 为 summary JSON markdown 组装（str/list 值逐段 + evidence file_path+reason 列表）；payload 只放摘要（repository_id/branch/focus/status/evidence_count），不复制 summary 全文；源缺失 warning + `[]`。
- `server/knowledge/sources/mcp_coding_plan.py`
  - 公开 `build_plan_event(plan, version, *, edges=())` 纯构造（mcp_execution_trace 锚事件复用，同源拼法纪律）；content 取**最新** `McpCodingPlanVersion`（`# title / ## 需求 / ## 步骤 / ## 测试计划 / ## 风险`，dict 项走 `json.dumps(sort_keys=True)` 确定性序列化）。
  - 主事件出边：`plan.analysis_id` 非空 → `REFERENCES` → mcp_repository_analysis 实体；work_item 三元组可反查（经 `McpWorkItemRepoTask.coding_plan` 反查）时，查与同一 work_item 锚有活跃边（任意方向、任意 relation）的 chat `coding_plan` 实体，逐个挂 `RELATES_TO`——缺料静默跳过（常态，不 warning 刷屏）。
  - work_item 锚双事件：三元组齐备时照抄 mcp_plan.py 锚构造（`feishu_work_item` + 三元组 source_id + `name\n\ndescription` 轻量锚 content——与 mcp_plan.py 逐字节同源拼法）；**锚出边强制 RELATES_TO（非排他），禁用 HAS_PLAN**——exclusive 语义会打失效 work_item 既有 HAS_PLAN→mcp_technical_plan 活跃边（决策存档模块 docstring，T-100-07）。version 缺失 → warning + `[]`（`knowledge_normalize_plan_version_missing`）。

### Task 2: mcp_execution_trace normalizer（[plan 锚, code_change] 双事件）

- `server/knowledge/sources/mcp_execution_trace.py`
  - code_change 主事件：`source_kind="mcp_execution_trace"`、title=`{repo.name} MCP 执行 @ {commit_sha[:8] or status}`；content 为执行摘要 markdown（执行概要 + branch_summary str 值段落 + file_changes 路径列表 + test_results 概要 + error 截断 500）；**last_diff / runner_logs 全程零接触**（T-100-06，task_result.py T-14-24 同款）。
  - payload 带 PR 信息（locked decision）：plan_id/plan_version_id/status/branch_name/target_branch/commit_sha/mr_url（`mr_result` 的 `mr_url`/`url` 键，缺为 ""）/file_change_count/retry_count。
  - plan 锚事件复用 `build_plan_event`，`IMPLEMENTED_BY`（方案→代码变更）EdgeSpec 挂锚事件，方向与 task_result.py L219-225 一致；plan 无自有最新版本 → 降级 code_change 单事件 + warning。event_time = `completed_at or created_at`（aware 化照 task_result.py）。

### Task 3: 5 处写入点投递钩子（6 个 aschedule 调用）

- `server/mcp_tools/views.py`（lazy import + 中文注释，不改响应外形）
  - AnalyzeRepositoryView acreate 后：`("mcp_repository_analysis", analysis_id, "mcp_analysis_created")`
  - CreateCodingPlanView plan+version acreate 后：`("mcp_coding_plan", plan_id, "mcp_coding_plan_created")`
  - ImproveCodingPlanView 新版本 acreate + current_version 翻转后：`("mcp_coding_plan", plan_id, "mcp_coding_plan_improved")`（重摄天然幂等：content 变更翻版本、未变 hash 短路）
  - ExecuteCodingPlanView `refresh_execution_trace` 之后（摄取时刻 trace 更完整）：`("mcp_execution_trace", trace_id, "mcp_execution_created")`
- `server/mcp_tools/work_item_execution_service.py`
  - `_ensure_coding_plan` acreate 分支 return 前：`("mcp_coding_plan", plan_id, "mcp_work_item_plan_created")`
  - `_execute_one_task` trace acreate 分支 refresh 后：`("mcp_execution_trace", trace_id, "mcp_work_item_execution_created")`
- grep 确认 `McpCodingPlanVersion.objects.acreate` 等写入点全覆盖（views 1894/1903/1998 + service 247，无遗漏）；既有 `mcp_technical_plan` 投递点未动。

### Task 4: 四组测试（server/tests/knowledge/test_mcp_artifact_sources.py，17 用例）

- **TestNormalizers**（8）：三 normalizer 字段/kind/source_kind/payload；REFERENCES/RELATES_TO/锚 RELATES_TO 边断言；execution_trace 锚 content 与 `mcp_coding_plan.normalize` 主事件 **逐字节相等**（同源拼法回归防线）；diff 哨兵串（塞进 last_diff + runner_logs）零泄漏；源缺失/版本缺失降级。
- **TestTriggers**（6）：4 个 views 写入点走 HTTP（make_access_token Bearer + monkeypatch delegate/dispatch）+ 2 个 service 写入点直调，source_kind/source_id/trigger 三元逐点断言。
- **TestEdgeReachability**（1，ROADMAP criterion 3 端到端）：真跑 `ingest()`（mock 向量全套）依次摄取 technical_plan→analysis→plan→trace，断言活跃边 plan—IMPLEMENTED_BY→trace、锚—RELATES_TO→plan、plan—RELATES_TO→chat plan、plan—REFERENCES→analysis；**既有 HAS_PLAN→mcp_technical_plan 边未被打失效**（T-100-07 回归项）；`graph_store.traverse` 从锚 2 跳可达 execution；trace latest payload mr_url/commit_sha 与 fixture 一致；natural key 隔离断言（同 source_id 串不同 source_kind → 不同 uuid5）。
- **TestIdempotentReingest**（1，criterion 4 MCP 面）：三类产物各 ingest 两次 → 实体/版本数不变（4/4）、全部 current_version==1、第二轮 5 事件全走 skipped 短路。

## Deviations from Plan

1. **[实现细节] trace 降级分支的测试构造**：`McpCodingExecutionTrace.plan_version` 是非空 FK，「plan 最新 version 缺失」正常数据形态下不可达；用例以病理形态构造（trace.plan_version 指向他 plan 的版本、trace.plan 自身无版本）覆盖降级分支。防御代码保留。
2. **[编排口径] 不传 initiated_by_user_id**：orchestrator 提示"pass initiated_by_user_id where available"，但 plan Task 3 锁定「不传——MCP 链口径与 technical_plan_service.py L499 一致」（MCP 走 access token 认证，无 Django 用户；run 维度归因已由 InteractionRun 承担）。按 locked plan 执行。
3. **[格式] views.py / work_item_execution_service.py 预存 format 漂移**：`ruff format --check` 报的 reformat 全部位于本 plan 未触及的既有段落（`--diff` 核对），为避免与并行 executor（100-02 同文件邻域）产生无关大 diff，不做全文件 format；本 plan 新增代码段符合 format 规范，`ruff check` 全绿。

## Verification Evidence

- Task 1 验证（`-k "analysis or coding_plan"`）：

  ```text
  ================ 10 passed, 7 deselected, 8 warnings in 22.36s =================
  ```

- 全文件（Task 2/4 验证含 `-k execution_trace` / trigger / E2E / 幂等）：

  ```text
  ======================= 17 passed, 14 warnings in 28.47s =======================
  ```

- 整体验证（plan `<verification>`：新测试 + tests/mcp_tools/ 全量零回归）：

  ```text
  ================= 169 passed, 154 warnings in 63.33s (0:01:03) =================
  ```

- `uv run ruff check` 全部触及文件通过；新建 3 个 normalizer 模块与测试文件 `ruff format` 干净（既有 views/service 文件的预存漂移见 Deviation 3）。
- E2E 断言含「work_item 既有 HAS_PLAN→mcp_technical_plan 边未被 RELATES_TO 锚边打失效」回归项（plan `<verification>` 指定）。

## Commits

| Commit | 说明 |
| --- | --- |
| `112c248f` | feat(100-03): mcp_repository_analysis 与 mcp_coding_plan normalizer |
| `0532b4da` | feat(100-03): mcp_execution_trace normalizer（[plan 锚, code_change] 双事件） |
| `d56cc9dc` | feat(100-03): MCP 产物 5 处写入点挂 aschedule_ingestion 投递钩子 |
| `0b835b6a` | test(100-03): MCP 三类产物 normalizer/触发/E2E/幂等四组测试 |

## Known Stubs

无。`_NORMALIZERS` 预注册的 3 个 MCP 条目（100-01 登记）本 plan 全部落地；`learning_case` 条目由并行 plan 100-02 落地。

## Threat Flags

无新增安全面：T-100-06（diff 泄漏）已 mitigate——last_diff/runner_logs 零接触 + 哨兵串测试兜底；T-100-07（HAS_PLAN exclusive 误用）已 mitigate——锚边强制 RELATES_TO + docstring 存档 + E2E 既有边活跃回归断言；T-100-08（写入点 DoS）——aschedule_ingestion 异常自吞，投递失败不反噬 MCP 响应（既有机制，钩子未包新 try/except）；零新依赖。

## Self-Check: PASSED

- `server/knowledge/sources/mcp_repository_analysis.py` — FOUND
- `server/knowledge/sources/mcp_coding_plan.py`（build_plan_event 导出） — FOUND
- `server/knowledge/sources/mcp_execution_trace.py` — FOUND
- `server/tests/knowledge/test_mcp_artifact_sources.py` — FOUND
- Commit `112c248f` / `0532b4da` / `d56cc9dc` / `0b835b6a` — FOUND
