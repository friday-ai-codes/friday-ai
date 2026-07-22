---
phase: 103-container-integration
plan: 02
subsystem: task-container / mcp-tools
tags: [agent-02, knowledge-mcp, allowed-tools, exclusion, session-id]
requires: []
provides:
  - "task/core/knowledge_tools.py：7 工具白名单 + build_knowledge_mcp_server + knowledge_allowed_tools"
  - "TaskConfig.knowledge_endpoint / knowledge_quota（FRIDAY_TASK_ env 自动映射）"
  - "executor._build_tool_mounts：allowed_tools 合并唯一收口点（builtin+remote+knowledge+extra）"
  - "InteractionRun.raw_request.task_session_id 关联键（X-Friday-Session-Id）"
affects:
  - "103-01（服务端 env 注入 FRIDAY_TASK_KNOWLEDGE_ENDPOINT/USER_TOKEN 后本链路激活）"
  - "103-03（task 容器构建，文件不相交）"
tech-stack:
  added: []
  patterns:
    - "闭包共享计数器实现 per-task 配额（quota_counter=[0]，7 工具共用预算）"
    - "三源工具挂载合并收口单一构造函数（_build_tool_mounts）"
key-files:
  created:
    - task/core/knowledge_tools.py
    - task/tests/test_knowledge_tools.py
    - server/tests/mcp_tools/test_container_knowledge_chain.py
  modified:
    - task/core/config.py
    - task/core/executor.py
    - task/tests/test_claude_sdk_integration.py
    - server/interactions/entry.py
decisions:
  - "配额文案不带 is_error：预算终点非错误，避免模型把它当失败反复重试"
  - "builtin 规则收口后 repo_summary 的 allowed_tools 也含全量 builtin（Write/Edit 仍被 disallowed_tools 拦截，优先级更高）——plan 明文规则，行为差异见 Deviations"
  - "第七面 search_rag_chunks 回归测试用 settings.ENABLE_GRAPHRAG_ENRICHMENT=False 强制 rag-only 路径，让 search_rag 内真实内置匹配器执行 fail-closed 过滤"
metrics:
  duration: ~25min
  completed: 2026-07-22
  tasks: 3/3
  tests: "task 233 passed / server mcp_tools 181 passed"
---

# Phase 103 Plan 02: 容器知识 MCP（AGENT-02）Summary

**One-liner:** 容器编码代理经进程内 SDK MCP server（friday-knowledge，7 工具白名单硬编码）HTTP 转调服务端 /api/mcp/tools/*，三要素守门降级零回归，allowed_tools 三源合并收口单一构造函数（WR-02），per-task 配额 200 守门，X-Friday-Session-Id 入 InteractionRun 关联键，第七面排除回归钉全绿。

## Tasks

| # | Task | Commit | 关键文件 |
|---|------|--------|----------|
| 1 | knowledge_tools.py（7 工具白名单 + handler + 配额 + 脱敏）+ TaskConfig 字段 + 单元测试 | 17813002 | task/core/knowledge_tools.py, task/core/config.py, task/tests/test_knowledge_tools.py |
| 2 | executor 挂载 + allowed_tools 合并收口单一构造函数 + WR-02 专项测试 | 9c815b2e | task/core/executor.py, task/tests/test_claude_sdk_integration.py |
| 3 | 服务端 X-Friday-Session-Id 关联键 + 第七面排除回归测试 | dcf073eb | server/interactions/entry.py, server/tests/mcp_tools/test_container_knowledge_chain.py |

## 实现要点

### Task 1 — knowledge_tools.py
- `KNOWLEDGE_TOOL_SCHEMAS` 硬编码 7 条（search_rag_chunks / grep_repository / get_repository_file / search_delivery_knowledge / search_learning_cases / search_project_context / lookup_project_by_branch），input_schema 逐一对照 `server/mcp_tools/serializers.py`（required 字段测试钉死）。
- `build_knowledge_mcp_server(endpoint_base, user_token, session_id, quota)`：三要素守门（endpoint/token 任一空 → None）；端点校验镜像 `_is_valid_tools_endpoint`（失败只记 scheme 不记完整 URL）；配额闭包计数器 7 工具共享。
- handler 响应外形按 MCP 工具视图（非 remote_tools 的 {ok} 信封）：body 直接业务参数 dict；200 → `json.dumps(body, ensure_ascii=False)`；401/403 → 固定文案；其余非 200 → 只回显 HTTP code **不回显响应体**（T-103-05，测试构造含 secret 的 500 body 断言不出现）；非 JSON 200 兜底；传输错误 return-not-raise。
- 日志只记 tool/status/duration_ms/quota_used（token/endpoint URL/入参明文零泄漏，structlog capture 断言）。
- TaskConfig 新增 `knowledge_endpoint`（默认空）/`knowledge_quota`（默认 200），env_prefix 自动映射，默认值零回归（test_config.py 不红）。

### Task 2 — executor 收口
- 新增模块级 `_build_tool_mounts(config, task_id, extra_mcp_servers, extra_allowed_tools) -> (mcp_servers, allowed_tools)`：remote + knowledge + extra 三源与 builtin 合并的**唯一收口点**；任一 server 挂载即全量并入 `_BUILTIN_CODING_TOOLS`（排他白名单缺列即禁用，WR-02 前科注释保留）；无挂载返回 `({}, [])` 与现状逐字一致。
- `_execute_claude` 散装 merge（原 L610-623）替换为构造函数调用；session_id 用 `config.task_id`；启动日志追加 `has_knowledge_endpoint`（仅 bool）。
- WR-02 专项测试：knowledge 单挂不丢 builtin（全量 11 项断言）；remote+knowledge+extra(ask_user) 三源并集无重复；全空配置零回归钉。

### Task 3 — 服务端关联键 + 第七面
- `begin_interaction_run` 在 raw_request 组装后读 `HTTP_X_FRIDAY_SESSION_ID`，非空写 `raw_request["task_session_id"]`（经 acreate_interaction_run 统一脱敏落库），`InteractionRun.objects.filter(raw_request__task_session_id=...)` 可关联查询；观测面复用注释（McpToolView._record → RequestMetric source=mcp，零新建）。
- `test_container_knowledge_chain.py`：(a) get_repository_file 读 .env → 404 file_excluded 无明文；(b) grep_repository 命中集剔除 .env；(c) search_rag_chunks mock 底层 provider（embedding/sparse/BranchAwareSearchService）返回含 .env 候选、真实内置匹配器 fail-closed 滤除；关联键带头/不带头双向断言。

## Deviations from Plan

### 行为说明（plan 明文规则的副作用，非偏差修复）

**1. builtin 规则对 repo_summary 路径的影响**
- Plan 规则"任一 MCP server 挂载（含 extra）即全量并入 builtin"使 repo_summary 模式（仅挂 extra 的 submit 工具）的 allowed_tools 从「只读分析集」变为「全量 builtin ∪ submit」。
- Write/Edit/MultiEdit/NotebookEdit 仍被该路径的 `disallowed_tools` 拦截（SDK 优先级高于 allowed_tools），只读语义的核心防线不变；WebFetch/WebSearch 由 prompt 约束禁用（与收口前的防线等级一致）。
- 既有 `test_216_02_repo_summary.py` mock 整个 `_execute_claude`，断言不受影响，233 项 task 测试全绿。

### Auto-fixed Issues

**1. [Rule 1 - Bug] 修正配额共享测试的 MCP CallToolRequest 入参**
- **Found during:** Task 1
- **Issue:** 测试经 MCP server 请求处理器调 `grep_repository` 时传 `{"query": "q"}`，被 SDK schema 校验拒绝（缺 required `pattern`），未到达配额守门。
- **Fix:** 按各工具 required 字段传参（`search_rag_chunks` 传 query、`grep_repository` 传 pattern）。
- **Files modified:** task/tests/test_knowledge_tools.py
- **Commit:** 17813002

## 验证结果

- `cd task && uv run pytest tests/ -q` → **233 passed, 3 skipped**（含存量 remote_tools/exclusion_prune/216_02 零回归）。
- `cd server && uv run pytest tests/mcp_tools/ -q` → **181 passed**（含新增 test_container_knowledge_chain.py 5 项与存量六面排除测试）。
- `cd server && uv run pytest tests/test_interactions_ledger.py ...` → 12 passed（entry.py 改动零回归）。
- `rg "user_token|Authorization" task/core/knowledge_tools.py | rg -v "header|Bearer|绝不|docstring|#"` → 仅剩 docstring/形参名，token 无日志/返回文本路径。
- ruff check + format 全部通过。

## 依赖说明

服务端 env 注入（`env_FRIDAY_TASK_KNOWLEDGE_ENDPOINT` + `env_FRIDAY_TASK_USER_TOKEN`）在 103-01 落地；本 plan 三要素守门保证单独合入零回归（env 未注入 → build 返回 None 降级不挂）。

## Threat Flags

无新增计划外安全面：出站 HTTP（携带 PAT）已在 plan threat_model T-103-05/06 中登记并落地 mitigation（端点校验 + 响应体不回显 + 日志脱敏 + 配额）。

## Known Stubs

无。

## Self-Check: PASSED

- 创建文件全部存在（knowledge_tools.py / test_knowledge_tools.py / test_container_knowledge_chain.py / SUMMARY.md）。
- 三个任务提交均在 git log（17813002 / 9c815b2e / dcf073eb）。
