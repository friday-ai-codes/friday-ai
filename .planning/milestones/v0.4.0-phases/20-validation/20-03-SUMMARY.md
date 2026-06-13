---
phase: 20-validation
plan: 03
subsystem: api
tags: [workflow, validation, template, loader, code-review-pipeline, daily-summary, security]

# Dependency graph
requires:
  - phase: 20-validation
    provides: WorkflowGraphValidator 纯函数核心 + DAG.from_node_edge_dicts（20-01）
provides:
  - daily_summary 字段对齐真实输出（fetch_data.body / summarize.text），运行语义正确
  - code_review_pipeline 方案 A 结构性契约对齐（去 http 中转节点 + trigger→review[target_handle=coding_result]→notify + notify 引 review_report + payload 文档化 description）
  - 4 个内置模板经 WorkflowGraphValidator 均零 error
  - acreate/create_workflow_from_template 建库前同源图校验（TPL-03，非法模板 ValueError 拒绝、无半残 workflow，T-20-08）
  - test_template_loader 守护测试（TPL-01/02/03：每模板零 error + 5 类 schema 可判定断裂注入 + loader 拒绝 + 字段对齐回归）
affects: [模板创建路径（from_template API）]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "模板→validator 入参同源转换：type→node_type、模板节点 id 兼作 short_id+id、edge source/target→source_node_id/target_node_id 保留 handle（loader 与测试同口径）"
    - "建库前 fail-fast：load_template 后、acreate 前同源校验，error→ValueError（view 层已 ValueError→400）"
    - "断裂注入只用有 schema 的节点（ai_prompt/ghost），禁用 http 字段避免假绿（Pitfall 3）"

key-files:
  created: []
  modified:
    - server/workflows/templates/daily_summary.json
    - server/workflows/templates/code_review_pipeline.json
    - server/workflows/templates/loader.py
    - server/tests/workflows/test_template_loader.py

key-decisions:
  - "code_review_pipeline 采用 orchestrator 已定方案 A：去除产不出 coding_result.merge_requests 的 http_request 节点，trigger→review 边 target_handle=coding_result，description 文档化 webhook payload 前提（务实终态）"
  - "_validate_template_graph 同时接入 async 与 sync 两条 create 入口，两路径均不产生半残 workflow（Rule 2 一致性强化 T-20-08）"
  - "daily_summary 字段对齐为运行语义修复（output 字段虽在 ai_prompt schema 内，validator 无法判定语义错——Pitfall 3）；TPL-01 正确性靠字段对齐 + 守护测试断言不回退坏字段"

requirements-completed: [TPL-01, TPL-02, TPL-03]

# Metrics
duration: ~12min
completed: 2026-06-13
---

# Phase 20 Plan 03: 模板修复 + loader 建库前校验 + 模板守护测试 Summary

**修复两个断裂内置模板（daily_summary 字段对齐 body/text；code_review_pipeline 按方案 A 去 http 中转节点、trigger→review[target_handle=coding_result]→notify、引 review_report、文档化 webhook payload 前提），让 loader 在 acreate 前调用与保存同源的 WorkflowGraphValidator 拒绝非法模板（TPL-03，无半残 workflow），并扩展 test_template_loader 守护每模板零 error + 5 类 schema 可判定断裂注入 + loader 拒绝（TPL-01/02/03）。**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-06-13T11:53:00Z
- **Completed:** 2026-06-13T12:05:00Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- **daily_summary.json（Task 1）**：`{{nodes.fetch_data.output}}`→`{{nodes.fetch_data.body}}`（http 实际输出 body）、`{{nodes.summarize.output}}`→`{{nodes.summarize.text}}`（ai_prompt 主文本字段）。
- **code_review_pipeline.json（Task 1，方案 A）**：去除 `fetch_pr`（http_request）节点；边重构为 `trigger → review`（`target_handle="coding_result"`）+ `review → notify`；notify content `{{nodes.review.output}}`→`{{nodes.review.review_report}}`（真实输出字段，原 output 不在 ai_code_review 输出 schema 会触发 field_not_found）；description 文档化 webhook payload 前提（`coding_result: {merge_requests:[...]}` 形态 + repository_id 须为已注册仓库 UUID + 已配置凭证）。
- **loader.py（Task 2）**：新增模块级 `_validate_template_graph(template, template_id)`，把模板 nodes/edges 转 validator 入参（同 loader `template_to_short` 标识符空间）并调 `WorkflowGraphValidator().validate`，errors 非空 → `raise ValueError`；在 `acreate_workflow_from_template` 与 `create_workflow_from_template` 的 `load_template` 之后、`acreate`/`create` 之前调用。validator 纯 CPU 无 ORM，同步直调。
- **test_template_loader.py（Task 3）**：新增 4 个测试类——`TestTemplateGraphValidation`（参数化 4 模板零 error）、`TestTemplateBreakageInjection`（坏 node_type / 缺必填 config / `{{nodes.summarize.nonexistent_field}}` / `{{nodes.ghost.x}}` / 坏 source_handle 共 5 例，reason 命中）、`TestLoaderPreCreateValidation`（注入断裂 acreate → ValueError 且 DB 无新 workflow + 4 合法模板回归）、`TestTemplateFieldAlignmentRegression`（daily_summary body/text 不回退 + code_review_pipeline 方案 A 契约）。

## Task Commits

1. **Task 1: 模板修复（daily_summary 字段 + code_review_pipeline 方案 A）** - `c5ad9ec9f` (fix)
2. **Task 2: loader 建库前同源 validator 校验** - `5651f417d` (feat)
3. **Task 3: test_template_loader 扩展 TPL-01/02/03** - `d44e68d58` (test)

## Files Created/Modified
- `server/workflows/templates/daily_summary.json` - 变量引用对齐真实输出字段（body/text）
- `server/workflows/templates/code_review_pipeline.json` - 方案 A 结构性契约对齐 + payload 文档化 description
- `server/workflows/templates/loader.py` - `_validate_template_graph` 助手 + async/sync 两入口建库前校验
- `server/tests/workflows/test_template_loader.py` - TPL-01/02/03 守护测试（含修正 async 用例 node 数 4→3、移除既有未用 import）

## Decisions Made
- **方案 A 终态（orchestrator 已定）：** code_review_pipeline 的 http 中转节点结构性产不出 `coding_result.merge_requests`（Pitfall 4），故移除并让 webhook payload 直接经 `target_handle=coding_result` 进入 ai_code_review 输入端口；外部 PR 审查无法纯 config 自足，description 文档化"需预注册仓库 UUID + 凭证"前提为符合"开箱能跑"意图的务实终态。
- **断裂注入只用 schema 节点：** 注入路径用 ai_prompt（有输出 schema，命中 field_not_found）与 ghost（命中 node_not_found），**不用 http 节点字段**——http 无输出 schema 字段层会被跳过导致假绿（Pitfall 3）。
- **sync 入口一并接入校验（Rule 2）：** 计划仅点名 acreate，但 sync `create_workflow_from_template` 同样会从非法模板产生半残 workflow，故 `_validate_template_graph` 同时接入两入口，统一 T-20-08 防线（4 个合法模板的既有 sync 用例不破）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - 阻塞] code_review_pipeline 节点数变化导致既有 async 用例失败（4→3）**
- **Found during:** Task 2 验证
- **Issue:** Task 1 方案 A 去除 http 中转节点后，`test_async_create_workflow_from_template` 仍断言 `len(nodes) == 4`，与新 3 节点结构冲突。
- **Fix:** 更新断言为 `== 3` 并加中文注释说明方案 A 重构。
- **Files modified:** server/tests/workflows/test_template_loader.py
- **Commit:** d44e68d58

**2. [Rule 2 - 缺失关键功能] sync create_workflow_from_template 同源校验缺口**
- **Found during:** Task 2
- **Issue:** 计划仅要求 acreate 路径建库前校验，但 sync 入口同样可由非法模板产生半残 workflow（T-20-08 同类威胁）。
- **Fix:** `_validate_template_graph` 同时接入 async 与 sync 两条 create 入口。
- **Files modified:** server/workflows/templates/loader.py
- **Commit:** 5651f417d

**3. [Rule 1 - Bug] 既有未用 import（Path / WorkflowEdge / WorkflowNode）触发 ruff F401**
- **Found during:** Task 3 ruff check
- **Issue:** test_template_loader.py 既有未使用 import，编辑该文件后 ruff F401 阻断提交。
- **Fix:** 移除 `Path` / `WorkflowEdge` / `WorkflowNode` 三个未用 import（保留 `Workflow`）。
- **Files modified:** server/tests/workflows/test_template_loader.py
- **Commit:** d44e68d58

## Threat Surface
本计划对齐编辑态模板契约 + 强化建库前校验，与 STRIDE 注册表对齐：
- T-20-08（非法模板建库产生半残 workflow）：loader 在 acreate/create 前调同一 validator，error→ValueError→（view 层）400，建库前拒绝 ✅
- T-20-09（description 暴露真实仓库 UUID/凭证）：code_review_pipeline description 仅说明 payload 形态与"需预注册仓库 UUID + 凭证"前提，未写入任何真实 UUID/凭证值 ✅
- T-20-10（伪造 repository_id 越权拉 diff）：accept — repository_id 经 Friday 既有运行态凭证/权限校验（Phase 14 防线），本阶段仅对齐编辑态契约，未放宽运行态鉴权 ✅

## Verification
- `cd server && uv run pytest tests/workflows/test_template_loader.py -q` → 35 passed。
- `cd server && uv run pytest tests/workflows -q` → 466 passed（零回归）。
- 4 模板经 WorkflowGraphValidator 校验零 error（daily_summary/code_review_pipeline/feishu_full_pipeline/code_generation）。
- 注入 5 类 schema 可判定断裂 → validator errors 非空且 reason 命中；loader 注入断裂 → ValueError 且无 workflow 落库。
- `ruff check` loader.py + test_template_loader.py 通过；`server/uv.lock` 经 `git checkout` 还原无无关 diff。

## State Sync Note
按本次执行约束（sequential / 不改阶段级字段），未运行 STATE.md / ROADMAP.md 的 advance-plan / update-progress 等状态写入；仅交付代码、测试与本 SUMMARY。

## Self-Check: PASSED

- 修改文件全部存在：daily_summary.json / code_review_pipeline.json / loader.py / test_template_loader.py / 20-03-SUMMARY.md。
- 任务提交全部存在：c5ad9ec9f / 5651f417d / d44e68d58（git 校验通过）。
- 验证：模板守护测试 35 例绿；tests/workflows 466 例零回归；4 模板 validator 零 error；ruff 通过；uv.lock 无无关 diff。

---
*Phase: 20-validation*
*Completed: 2026-06-13*
