---
phase: 101-completion-loop
plan: 02
status: complete
date: 2026-07-22
subsystem: mcp_tools / knowledge / observability
requirements: [LOOP-03]
provides:
  - "aextract_learning_case 自动提炼公共入口（锚点接线归 101-03）"
  - "call_source: learning_case_extraction / pr_review_capture（LOGGING-SPEC §4.1 已登记）"
  - "SettingKeys.LEARNING_CASE_AUTO_EXTRACT / PR_REVIEW_CAPTURE 系统开关"
  - "McpLearningCase.run 可空 + source_session_id 幂等键（migration 0011）"
key-files:
  created:
    - server/mcp_tools/learning_case_extraction.py
    - server/tests/mcp_tools/test_learning_case_extraction.py
    - server/mcp_tools/migrations/0011_learningcase_auto_extract.py
  modified:
    - server/agents/call_source.py
    - server/system/models.py
    - server/mcp_tools/models.py
    - server/tests/test_model_usage_call_source.py
    - .planning/observability/LOGGING-SPEC.md
commits:
  - "32ef4eec feat(101-02): 观测登记先行——新增 learning_case_extraction/pr_review_capture call_source"
  - "0ad5c01d feat(101-02): McpLearningCase 支持自动提炼——run FK 放松 + source_session_id 幂等键"
  - "51c7152c feat(101-02): aextract_learning_case 自动提炼管线——质量门+REJECT+幂等+脱敏+入图"
---

# Phase 101 Plan 02: 自动提炼 learning case 管线 Summary

**一句话**：`aextract_learning_case` 提炼管线落地（开关→状态门→幂等→LLM→质量门→脱敏→入库→入图，全程 fail-soft），LLM 侧完整镜像 memory_distill 范式（`use_call_source("learning_case_extraction")` + `arecord_llm_usage` 两路上报），质量门与功能同 plan 落地（P2 mem0 前车之鉴）——REJECT 走显式 `learning_case_rejected` 事件不入库；观测登记先行（两个新 call_source + feature_list_parse 补登在任何提炼代码之前 commit）。本 plan 不接锚点（101-03 的事）。

## What Was Built

### Task 1（32ef4eec）：观测登记先行

- `server/agents/call_source.py`：`CallSource` 追加 `LEARNING_CASE_EXTRACTION` / `PR_REVIEW_CAPTURE`，枚举计数 33→35，docstring 版本履历补 v0.17.0 Phase 101。
- `.planning/observability/LOGGING-SPEC.md` §4.1 追加三行：补登已漂移的 `feature_list_parse` + 两个 Phase 101 新值。
- `server/system/models.py` `SettingKeys`：`LEARNING_CASE_AUTO_EXTRACT = "learning_case.auto_extract_enabled"`（默认开可秒关）/ `PR_REVIEW_CAPTURE = "learning_case.pr_review_enabled"`（默认关，LOOP-05）。
- 同步更新枚举计数守卫测试 `tests/test_model_usage_call_source.py`。

### Task 2（0ad5c01d）：McpLearningCase 数据模型放松

- `run` FK 改 `null=True, blank=True`（自动提炼无 InteractionRun；on_delete/related_name 不变，人工路径零回归）。
- 新增 `source_session_id`（`max_length=80`，unique，null）幂等键——取 80 为 LOOP-05 `{session_id}:pr_review` 变体留余量；人工 `create_learning_case` 路径不写此字段，多条 NULL 不参与 unique 冲突（SQLite/Postgres 语义一致）。
- migration `0011_learningcase_auto_extract` 仅含 AlterField(run) + AddField(source_session_id)；`makemigrations --check` 干净。
- 已核实 Phase 100 normalizer `knowledge/sources/learning_case.py` 不依赖 `case.run`。

### Task 3（51c7152c）：aextract_learning_case 提炼管线 + 五路测试

- `server/mcp_tools/learning_case_extraction.py`（431 行）：
  - **管线顺序**：kill switch（`aget_bool_setting(LEARNING_CASE_AUTO_EXTRACT, default=True)`）→ 状态门（仅 `completed`）→ 幂等（`source_session_id = session_id + idempotency_suffix` aexists 查重）→ LLM 提炼 → JSON 解析（剥 ```json 围栏，解析失败进 REJECT）→ 质量门 → 脱敏 → 入库 → 入图 → `learning_case_extraction_completed`（caller + duration_ms）。
  - **LLM**（`_acall_llm`，测试 mock 点）：`aresolve_or_error` 缺凭证 fail-soft；`use_call_source(CallSource.LEARNING_CASE_EXTRACTION.value)` + `build_chat_model(max_output_tokens=1024, streaming=False)`；`arecord_llm_usage(source="mcp_tools")` 成功/异常两路都记；异常 `parse_upstream_status` 留痕。幂等检查在 LLM 之前——重入不烧 token（T-101-02-02）。
  - **质量门**（`_admission_gate`）：problem/solution 去空白后 ≥30 字符、problem≠solution、去模板断言（暂无/无/N-A/TODO/待补充/略 开头）；不过门 `logger.warning("learning_case_rejected", reason=..., category="caller", initiated_by_user_id=...)` 不入库。
  - **脱敏**：title/problem/root_cause/solution 全过 `redact_secrets_in_text`（T-101-02-01）。
  - **入库**：`acreate(run=None, source_session_id=key, ...)`；`IntegrityError` 捕获视为并发 duplicate skip。
  - **入图**：lazy import `knowledge.ingestion` → `aschedule_ingestion(IngestionRequest("learning_case", case.id, "learning_case_auto_extracted"), initiated_by_user_id=... or "system")`（Phase 100 通路，INV-6）。
  - 跳过事件（disabled/status_gate/duplicate/llm_unavailable）用 `category="sampling"`；外层兜底 try/except 记 `learning_case_extraction_failed`，绝不上抛。
- `server/tests/mcp_tools/test_learning_case_extraction.py` 五路：开关关（LLM 未调用）/ failed 状态门 no-op / 幂等重入单条（且 LLM 只调一次）/ REJECT 路径（capture_logs 断言 `learning_case_rejected` 事件 + reason + category + initiated_by_user_id）/ 成功路径（run=None、幂等键、脱敏断言埋 `sk-ant-*` 明文、`aschedule_ingestion` 以 ("learning_case", case_id) + initiated_by_user_id 被调）。

## Verification

- `uv run pytest tests/mcp_tools/test_learning_case_extraction.py tests/mcp_tools/test_learning_cases.py -q` → **11 passed**（5 新 + 6 既有，人工路径零回归）。
- `uv run ruff check` + `ruff format --check` 通过。
- `makemigrations --check --dry-run mcp_tools` 无未生成变更。
- `rg "LEARNING_CASE_EXTRACTION|PR_REVIEW_CAPTURE" server/agents/call_source.py` = 2 命中；`rg -c "feature_list_parse" LOGGING-SPEC.md` = 1。
- Commit 顺序：32ef4eec（登记）在 51c7152c（提炼代码）之前——"先登记再写代码"证据成立。

## Deviations from Plan

**1. [Rule 1 - 调整] 脱敏测试明文样例改用 `sk-ant-*` 格式**
- **Found during:** Task 3 测试编写
- **Issue:** 计划原文写"输入里埋 `token=abc123secret`"，但 `redact_secrets_in_text` 的 `SENSITIVE_VALUE_PATTERN` 不匹配该格式（只认 sk-ant-/sk-/AIza/Bearer/PEM），断言会假绿。
- **Fix:** 明文样例改为 `sk-ant-abcd1234secretvalue9876543210`（与 `test_memory_distill.py` 同款），真实验证脱敏生效。
- **Commit:** 51c7152c

**2. [说明] 执行者中断续接**
- Task 1/2 由前一执行者完成并提交（32ef4eec / 0ad5c01d），本次续接核实两者落地无误后仅执行 Task 3 + SUMMARY。

其余按计划执行。

## Known Stubs

无——管线完整可用；锚点接线（workflow/chat/MCP 完成点调用 `aextract_learning_case`）按设计归 101-03，非 stub。

## Threat Flags

无新增计划外安全面。`<threat_model>` 四项 mitigate 全部落实：T-101-02-01（四字段脱敏 + 明文断言测试）、T-101-02-02（幂等前置于 LLM + usage 按 call_source 聚合）、T-101-02-03（状态门 + 质量门 + REJECT 事件 + 开关秒关）、T-101-02-04（事件带 initiated_by_user_id 或 system + source_links.session_id 可回溯）。

## Self-Check: PASSED

- `server/mcp_tools/learning_case_extraction.py` 存在（431 行 ≥ min_lines 150）
- `server/mcp_tools/migrations/0011_learningcase_auto_extract.py` 存在
- `server/tests/mcp_tools/test_learning_case_extraction.py` 存在
- Commits 32ef4eec / 0ad5c01d / 51c7152c 均在 git log
