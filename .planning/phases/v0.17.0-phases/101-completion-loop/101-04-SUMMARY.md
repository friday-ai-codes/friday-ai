---
phase: 101-completion-loop
plan: 04
status: complete
date: 2026-07-22
requirements: [LOOP-04, LOOP-05]
key-files:
  created:
    - server/tools/handlers/__init__.py
    - server/tools/handlers/skill_steps.py
    - server/tools/migrations/0005_seed_platform_skills.py
    - server/mcp_tools/pr_review_capture.py
    - server/tests/tools/__init__.py
    - server/tests/tools/test_platform_skills.py
    - server/tests/mcp_tools/test_pr_review_capture.py
  modified:
    - server/tools/sources/skill.py
    - server/tools/executor.py
    - server/tools/views.py
    - server/mcp_tools/learning_case_extraction.py
    - server/workflows/nodes/ai/coding.py
    - server/orchestration/coding_graph.py
    - server/mcp_tools/work_item_execution_service.py
    - .planning/phases/100-learning-case-mcp/100-REVIEW.md
commits:
  - f8f61e7c
  - 170f8172
  - dbc457ac
  - 8046ec07
key-decisions:
  - "LOOP-05 沉淀复用采用 plan 推荐做法：learning_case_extraction 拆出 apersist_extracted_case（质量门→脱敏→入库→入图可复用序列），review 模块 LLM 后直调——不重复 LLM 调用"
  - "PR review 锚点调度前置开关检查：开关关时零后台任务零 LLM 调用，且 101-03 既有 bg 调度精确断言测试零回归"
  - "需要权限主体的步骤工具（delivery_knowledge / learning_cases / report_project_knowledge）经可选 user_id 入参解析 user，缺失 fail-closed 返回 error JSON——绝不以特权身份兜底"
---

# Phase 101 Plan 04: 平台 Skill 种子 + 步级 trace + PR review 可选沉淀 Summary

**一句话**：`pre_coding_research` / `post_coding_capture` 两个多步 Skill 种子（7 个步骤 builtin 薄封装全部委托既有 service）+ skill 执行步级 trace（started/completed/failed 三态事件 + run 可用时逐步 `ToolCallRecord`，`{skill}#{i}:{step}` 命名）+ LOOP-05 PR 创建成功锚点的可选轻量 review 沉淀（`SettingKeys.PR_REVIEW_CAPTURE` 默认关、`call_source=pr_review_capture`、结论经 `apersist_extracted_case` 走 LOOP-03 幂等/质量门/脱敏/入库/入图路径）。

## What Was Built

### Task 1: 步骤工具薄封装 + 两个平台 Skill 种子 migration（commit `f8f61e7c`）

- `server/tools/handlers/skill_steps.py`：7 个 async handler，只做参数适配 + 结果 JSON 化（统一返回 `json.dumps(..., ensure_ascii=False)` 字符串），逻辑全部委托：
  - `route_repositories` → `RepoRouterV2.route`；`search_rag_chunks` → `services.retrieval.rag_search.search_rag`（`repo_ids` 形态）；`search_delivery_knowledge` → `DeliveryKnowledgeSearchService.search_similar`；`search_learning_cases` → `learning_case_service.search_learning_cases`；`summarize_branch` → `merge_request_service.summarize_branch`（target 缺省 `repo.default_branch`）；`create_learning_case` → `create_learning_case_from_technical_plan`（新建 `source="skill"` 的 `InteractionRun` 作审计锚，service 要求 run FK + 输出 run_id）；`report_project_knowledge` → `MemoryService.create_draft`（draft 路径，绝不直写 active，`MemoryPermissionError` → error JSON）。
  - 缺必需参数 / 无法解析权限主体 → 含 `error` 键的 JSON（不抛裸异常）；全部 `**kwargs` 容忍透传多余键。
- `migrations/0005_seed_platform_skills.py`（范本照抄 0002，get_or_create + reverse 按名删 9 行）：7 个 builtin 步骤工具（检索类 timeout 30、summarize/create 类 60）+ 两个 SKILL（`pre_coding_research` timeout 120、`post_coding_capture` timeout 180）；docstring 写明步骤参数语义（顶层透传合并、步内静态优先）。

### Task 2: Skill 步级 trace + 顶层输入透传 + 端到端测试（commit `170f8172`）

- `tools/sources/skill.py`：`execute_skill(tool, arguments, run=None)`——每步 `effective_args = {**arguments, **step_args}`（静态优先）；三态结构化事件（`skill_step_started/completed/failed`，kv 含 skill/step/step_tool/ok/duration_ms，`category="caller"`、`component="tools"`）；run 非 None 时逐步 `arecord_tool_call`（tool_name=`{skill}#{i}:{step}`，整段 try/except 吞，ledger 自带 redact_for_ledger）。首败中断与 `list[dict]` 返回形状零回归。
- `tools/executor.py`：`execute_tool` / `_dispatch` 追加 keyword `run=None` 仅透传 skill 分支（builtin/mcp 签名不动，既有调用方零改动）。
- `tools/views.py`：执行端点把顶层审计 run 传入 `execute_tool`（其余审计逻辑一字不动）。
- `tests/tools/test_platform_skills.py`（5 用例全绿）：步级 ToolCallRecord + 前缀命名 + 透传、静态参数优先、首败中断只留 1 条记录、run=None 不写 ledger 不抛、PAT 端到端调 `pre_coding_research`（4 步 handler 全 patch）→ 200 + 4 步结果 + 顶层 run 下 4 条步级记录。

### Task 3: LOOP-05 pr_review_capture 模块 + 双锚点触发（commit `dbc457ac`）

- `server/mcp_tools/pr_review_capture.py`（~330 行）`acapture_pr_review(...)`：开关（默认关，`aget_bool_setting(SettingKeys.PR_REVIEW_CAPTURE, default=False)`）→ 幂等前置（`{sid}:pr_review` 查重，重入不烧 token）→ `summarize_branch` diff 摘要（仓库缺失/异常 skip）→ LLM review（完整镜像 memory_distill 范式：`use_call_source(pr_review_capture)` + `build_chat_model(max_output_tokens=1024, streaming=False)` + `arecord_llm_usage` 成功/异常双路；system = `REVIEW_SYSTEM_PROMPT`（**只 import 不修改**，git diff 为空）+ 追加中文沉淀指令；user = requirement + files/risks/test_suggestions 截断 6000 字符）→ 组装 problem（需求/变更上下文）+ solution（review 结论）+ outcome="review" 经 `apersist_extracted_case` 入库。全程 fail-soft，外层兜底记 `pr_review_capture_failed`；事件带 `category`/`component`/`initiated_by_user_id`。
- `learning_case_extraction.py` 拆分（plan 推荐做法，注释写明决策）：`_aextract` 的"质量门→脱敏→入库→入图→收尾事件"拆为公开 `apersist_extracted_case(parsed, *, session_key, ...)`（幂等检查在 persist 前做）；`_aextract` 后半直接委托，行为零变化（101-02 的 5 个守护测试原样全绿）。
- 双锚点接线（同款 `run_in_background` 调度、不 await）：
  - workflow `coding.py` `_run_completion_loop`（新增 `base_branch` 入参）：对每个 successful_mr 反查该仓对应 completed_session_id（`session_repo_map` 反转），取不到 session 的仓跳过。
  - chat `coding_graph.py` `_run_completion_loop`（新增 `target_branch` 入参，PR 分支传 `mr_request.target_branch`）：`write_back=True` 即 PR 创建成功分支才触发；skip-PR 分支不触发。
  - 两处均在调度前先读开关：默认关时**零后台任务零 LLM 调用**（模块内开关/幂等仍有兜底）。
- `tests/mcp_tools/test_pr_review_capture.py`（5 用例全绿）：开关关零成本（summarize/LLM 均未调用）、开关开全链 mock 落库（`:pr_review` 后缀、outcome="review"、source_links 含 pr_url、入图带归因）、summarize 异常 fail-soft、同 session 重入 skip 不烧 token、仓库缺失 skip。

### EXTRA: LO-02 收尾（orchestrator 附加任务，commit `8046ec07`）

- `work_item_execution_service.py` 2 处摄取投递（`_ensure_coding_plan` 的 `mcp_coding_plan`、`_execute_one_task` 的 `mcp_execution_trace`）按 views.py（`e8df0951`）同款模式补传 `initiated_by_user_id=str(run.user_id) if getattr(run, "user_id", None) else None` + 同款注释；100-REVIEW.md 追加"LO-02 收尾"完结注记（同 commit）。LO-02 至此全部修复。

## Deviations from Plan

### Auto-fixed / 设计适配

**1. [参数适配] 权限主体步骤工具增加可选 `user_id` 入参（fail-closed）**
- **Found during:** Task 1
- **Issue:** `search_delivery_knowledge` / `search_learning_cases` / `report_project_knowledge` 底层 service 以 `user` 为权限主体（fail-closed），而 `execute_tool` 链路无 user 上下文（Phase 11 已知 gap，views.py 注释存档）。
- **Fix:** handler 经可选 `user_id` 解析 User（skill 顶层 arguments 透传即可注入每步）；解析不到返回 error JSON，绝不以特权身份兜底。schema 声明该键。
- **Commit:** f8f61e7c

**2. [Rule 3] `create_learning_case` handler 新建 `source="skill"` 审计 run**
- **Found during:** Task 1
- **Issue:** `create_learning_case_from_technical_plan` 要求非空 `InteractionRun`（FK + 输出 run_id），skill 步骤链路无既有 run。
- **Fix:** handler 内 `InteractionRun.objects.acreate(source="skill")` 作审计锚（不伪造 token 指纹），docstring 写明。
- **Commit:** f8f61e7c

**3. [Rule 1 - 测试隔离] e2e 用例补 `_reseed_platform_skills` fixture**
- **Found during:** Task 2
- **Issue:** `django_db(transaction=True)` 用例间 flush 会清掉 migration 种子数据，端到端用例在全量运行时找不到 `pre_coding_research`（单跑通过、合跑失败）。
- **Fix:** fixture 幂等重播 0005 种子函数（get_or_create 天然幂等）。
- **Commit:** 170f8172

**4. [Rule 2 - 零回归守护] 锚点调度前置开关检查（非字面"一行调度"）**
- **Found during:** Task 3
- **Issue:** 若无条件调度后台任务再在模块内判开关，默认关时仍产生后台任务，且 101-03 `test_extraction_scheduled_per_completed_session` 对 `run_in_background` 调用名单做精确断言会被打破。
- **Fix:** 双锚点在调度前先 `aget_bool_setting(PR_REVIEW_CAPTURE, default=False)`（读失败视为关），开关开才调度；模块内开关/幂等仍为兜底。"默认关零 LLM 调用"被更强满足（零后台任务），101-03 测试零回归。
- **Commit:** dbc457ac

**5. [计划勘误确认] 触碰 `learning_case_extraction.py`（frontmatter files_modified 漏列，plan-checker 已预警）**
- 按 plan 正文推荐做法拆出 `apersist_extracted_case`，改动最小（`_aextract` 后半委托 + `__all__` 追加），101-02 既有 5 个守护测试原样全绿。
- **Commit:** dbc457ac

### 其他说明

- `orchestration/coding_graph.py` / `mcp_tools/work_item_execution_service.py` 存在与本次改动无关的存量 ruff format 漂移（L56/L78/L145、L379/L511 等），沿用 101-03"存量漂移不动"惯例未格式化；新增代码段均 format 干净。
- 发现第三处摄取投递（Phase 13 旧点 `mcp_tasks_executed`）同样缺 `initiated_by_user_id`，LO-02 未点名故不越权修改——已记 `deferred-items.md`。

## Verification

- `uv run pytest tests/tools/test_platform_skills.py tests/mcp_tools/test_pr_review_capture.py -q` → 10 passed。
- 综合套件（+ 101-02/03 回归宿主）`tests/mcp_tools/test_learning_case_extraction.py tests/workflows/test_coding_writeback.py tests/test_coding_graph_completion.py tests/mcp_tools/test_work_item_execution.py` → **35 passed**。
- `manage.py migrate tools` OK + 9 个种子在表 + handler dotted-path 全部可 import；`makemigrations --check --dry-run tools` 无未生成变更。
- `git diff server/workflows/nodes/ai/code_review.py` 为空（`REVIEW_SYSTEM_PROMPT` 常量原文件未动）。
- `tests/mcp_tools/test_execution_tools.py` + `test_work_item_execution.py`（LO-02 修复宿主）→ 13 passed。
- 已知存量失败（未触碰，与本 plan 无关）：`tests/knowledge/test_triggers.py` 3 个 rotten + `test_sub_step_coding_node.py::test_plan_generation_node_still_works`（deferred-items 在案）。

## Threat Model 落实

| Threat | Disposition | 落实 |
|--------|-------------|------|
| T-101-04-01 EoP（skill steps 扇出） | mitigate | views.py 权限逻辑未动（PAT-only fail-closed）；步骤工具均委托既有只读检索/同能力 service，权限主体经 user_id fail-closed |
| T-101-04-02 信息泄露（步级 ledger / review 沉淀） | mitigate | 步级留痕走 `arecord_tool_call`（ledger 内建 redact_for_ledger）；review 产物经 `apersist_extracted_case` 的 `redact_secrets_in_text` 四字段脱敏 |
| T-101-04-03 DoS（review LLM 成本） | mitigate | 开关默认关 + 锚点前置开关守门（零后台任务）+ `{sid}:pr_review` 幂等前置（重入不烧 token）+ `call_source=pr_review_capture` 可聚合告警 |
| T-101-04-04 Tampering（handler stale target） | mitigate | Task 1 verify 脚本断言 7 个 handler dotted-path 全部可 import |

## Known Stubs

无——两个 Skill 步骤全部接真实 service；review 沉淀走真实入库路径。（`pre_coding_research` 第 2-4 步在未透传 `repository_ids`/`user_id` 时按设计返回显式 error JSON 并继续，属 fail-closed 行为而非 stub，migration/skill description 已写明透传语义。）

## Self-Check: PASSED

- FOUND: server/tools/handlers/skill_steps.py
- FOUND: server/tools/migrations/0005_seed_platform_skills.py
- FOUND: server/mcp_tools/pr_review_capture.py（>80 行）
- FOUND: server/tests/tools/test_platform_skills.py / server/tests/mcp_tools/test_pr_review_capture.py
- FOUND commits: f8f61e7c / 170f8172 / dbc457ac / 8046ec07
- key_links：`skill.py → arecord_tool_call`（步级 ledger）✓；`pr_review_capture.py → apersist_extracted_case`（LOOP-03 入库路径）✓；`pr_review_capture.py → REVIEW_SYSTEM_PROMPT`（只 import）✓
