---
phase: 260818-pt8-agent-friday-mcp-repo-summary-json
plan: 01
subsystem: api
tags: [mcp, claude-agent-sdk, structured-output, blueprint, repo-summary, callbacks, resume]

# Dependency graph
requires:
  - phase: 260817-xb9-readable-repo-research-detail
    provides: blueprint repo research 派发/事件/可读过程明细基座
provides:
  - "共享 Agent→Friday MCP 结构化提交工厂 agent_submit_mcp（场景注册 + schema 隔离 + apply_capture_to_result 唯一收口）"
  - "三场景（repo_summary / blueprint_research_fitness / blueprint_repo_plan）统一走 MCP tool 提交，删除自由文本 JSON 解析与 fallback"
  - "服务端 callback 硬切：只认 output.mcp_result，纯 text/围栏 JSON 明确拒绝"
  - "resume 污染会话过滤：仅 last_output.mcp_submit_ok=True 可续跑"
  - "blueprint 派发 repository_name 空名回退 Repository.name（started 事件 + last_output 非空）"
affects: [blueprint-research, repo-summary, subagent-callbacks, dispatch]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Agent→Friday 结构化通信统一走 MCP tool（friday-submit server + 场景专用 tool），不再靠正文文本 JSON"
    - "apply_capture_to_result 单点收口：有捕获→success + mcp_result；未调用→success=False + mcp_tool_not_called"
    - "AST 精确定位函数体的 scoped grep 门禁（不误伤 docstring 与 repo_verify 链）"

key-files:
  created:
    - task/core/agent_submit_mcp.py
    - task/tests/test_agent_submit_mcp.py
    - task/tests/test_explore_structured_submit.py
    - server/tests/subagent/test_mcp_submit_channel_gate.py
  modified:
    - task/core/executor.py
    - task/core/runner.py
    - task/core/config.py
    - server/subagent/api/callbacks.py
    - server/services/process_runtime/blueprint_research_adapter.py
    - server/services/process_runtime/blueprint_route.py

key-decisions:
  - "D-01/D-04 硬切 MCP：不保留任何旧结果渠道（repo_summary 私有 submit_summary server / blueprint 文本 JSON 全删）"
  - "D-03 未调用 MCP 提交工具 → 任务明确失败（mcp_tool_not_called），不静默用自由文本兜底"
  - "D-07 已捕获结构化结果后，即使 SDK 普通文本为空也判定成功"
  - "D-08 失败重试不 resume 未按协议提交的污染会话（mcp_submit_ok 缺失/False 不可续）"
  - "D-09 dispatch/route 的 repository_name 空名回退 Repository.name"

patterns-established:
  - "共享 MCP 提交工厂：一处注册场景 schema/tool/prompt 契约，各 mode 只调用不复制"
  - "结构化提交契约测有 schema 漂移守卫（task 侧 required/enum 与 server 契约对照）"

requirements-completed: [MCP-SUBMIT-01, MCP-SUBMIT-02, MCP-SUBMIT-03, MCP-SUBMIT-04, MCP-SUBMIT-05, MCP-SUBMIT-06]

# Metrics
duration: 跨会话（含前序模型执行 Task 1/2 主体）
completed: 2026-08-19
---

# Phase 260818-pt8: Agent→Friday MCP 结构化提交统一化 Summary

**抽离共享 Agent→Friday MCP 提交工厂并把 repo_summary / blueprint fitness / blueprint repo_plan 三场景硬切到 MCP tool 结果，彻底删除自由文本 JSON 解析、污染会话续跑与空仓库名派发。**

## Performance

- **Tasks:** 3 (全部完成)
- **Files created:** 4
- **Files modified:** 6
- **Plan-internal 测试:** task 46 passed / 3 skipped；server 85 passed

## Accomplishments
- 新建 `task/core/agent_submit_mcp.py`：`register_scenario` / `get_scenario` / `build_submit_mcp` / `apply_capture_to_result` 单点收口，三场景 schema 隔离、prompt 契约内建。
- `executor.py` / `runner.py`：repo_summary 与 explore(submit_scenario) 均走工厂 + `apply_capture_to_result`，删除 `_extract_summary_json`/`_is_valid_json`/`_sanitize_summary` 与旧私有 submit server。
- `callbacks.py`：`_update_repository_on_summary_complete` / `_parse_blueprint_fitness` / `_parse_blueprint_repo_plan` 只认 `output.mcp_result`，纯 text/围栏 JSON 拒绝；新增 `mcp_submit_ok` 落痕。
- `blueprint_research_adapter.py`：按 mode 注入 `env_FRIDAY_TASK_SUBMIT_SCENARIO`；prompt 去掉「只输出 JSON」改指向工厂契约；`_aresume_env` 过滤 `mcp_submit_ok=True`；`repository_name` 空名回退。
- `blueprint_route.py`：placement 候选批量补 `repository_name`（`_ahydrate_candidate_names`）。
- scoped AST 门禁测（`test_mcp_submit_channel_gate.py`）：task/core 无旧私有 server、三场景 parser 不走文本 JSON、repo_verify 链不被误伤。

## Files Created/Modified
- `task/core/agent_submit_mcp.py` - 共享 MCP 提交工厂 + apply_capture_to_result 唯一收口
- `task/core/executor.py` - repo_summary/explore 挂载工厂 MCP、统一收口；删旧私有 server 常量
- `task/core/runner.py` - completed 帧上报 mcp_result/submit_scenario；删自由文本解析 helper
- `task/core/config.py` - 新增 `submit_scenario`（env FRIDAY_TASK_SUBMIT_SCENARIO）
- `server/subagent/api/callbacks.py` - 三场景只认 mcp_result；mcp_submit_ok 落痕；拒旧文本
- `server/services/process_runtime/blueprint_research_adapter.py` - 注入 SUBMIT_SCENARIO、resume 过滤、name 回退、prompt 契约
- `server/services/process_runtime/blueprint_route.py` - placement 候选批量补名
- 测试：`test_agent_submit_mcp.py` / `test_explore_structured_submit.py` / `test_mcp_submit_channel_gate.py`（新增）；`test_216_02_repo_summary.py` / `test_claude_sdk_integration.py` / `test_repo_summary_callback.py` / `test_summary_callback_charter_enqueue.py` / `test_blueprint_research_callback.py` / `test_blueprint_repo_plan_callback.py` / `test_blueprint_research_stage.py` / `test_blueprint_repo_resume.py`（更新为 mcp_result 契约）

## Decisions Made
None - 按计划 D-01..D-10 执行；测试基础设施临时用本地 Postgres 见 Issues。

## Deviations from Plan
None - plan executed as written（未 git commit / stage，符合 git 纪律）。

## Issues Encountered
- **远端测试库不可用**：`server/.env` 的 `DATABASE_URL` 指向 `10.8.8.153:15432`，本次运行期间该 socat 代理后端 Postgres 关闭连接（`postgres`/`friday`/`test_friday` 均 "server closed the connection unexpectedly"）。为跑 `transaction=True` 的 server DB 测试，临时起本地 `postgres:17-alpine`（容器 `friday-test-pg`，端口 15499），以 `DATABASE_URL=…127.0.0.1:15499` + `QDRANT_URL=""` + `REDIS_URL=""`（cache 回退 locmem 避免 pytest-socket 拦截）运行，全部通过。**未修改仓库 .env**；远端恢复后按原配置即可。
- **1 个既有失败（out of scope）**：`task/tests/test_callback.py::TestClaudeExecuteModeKeepsBash::test_execute_mode_does_not_disable_bash` 失败于 `_detect_changes_guidance` 对 MagicMock `repository_id` 调 `re.fullmatch` 抛 TypeError。经 `git stash` 本文件改动后在 HEAD 上复现同样失败 → 确认为既有缺陷，且 `test_callback.py` 与 `_detect_changes_guidance` 均不在本计划 files_modified 内，未处理。

## Next Phase Readiness
- 三场景结构化提交链路 MCP-only 就绪；可重跑「高三」蓝图验证真实容器提交路径。
- 建议后续独立修复 `_detect_changes_guidance` 对非字符串 `repository_id` 的健壮性（既有缺陷）。

---
*Phase: 260818-pt8-agent-friday-mcp-repo-summary-json*
*Completed: 2026-08-19*
