---
phase: 11-rtool
plan: 02
subsystem: task
tags: [rtool, sdk-mcp, pat-injection, graceful-401, back-compat]
requires: [RTOOL-02, RTOOL-03, RTOOL-04]
provides:
  - "task/core/remote_tools.py：remote_tools schema → 进程内 SDK MCP server（build_remote_tools_mcp_server / _make_handler / remote_allowed_tools / REMOTE_MCP_SERVER_NAME）"
  - "TaskConfig 三字段 user_token / tools_endpoint / remote_tools（FRIDAY_TASK_ 前缀，pydantic v2 自动 JSON 解码 list[dict]）"
  - "executor._execute_claude 条件挂载 mcp_servers + allowed_tools（仅三字段俱全时；否则向后兼容）"
affects:
  - "11-03（runner Go env 透传 FRIDAY_TASK_REMOTE_TOOLS/USER_TOKEN/TOOLS_ENDPOINT）"
  - "11-04（server dispatch 注入 env_FRIDAY_TASK_* + 机会性 PAT）"
tech-stack:
  added: []
  patterns:
    - "直接构造 SdkMcpTool（非 @tool 装饰器），handler 为普通 async (dict)->dict（mirror server/agents/sdk/mcp_adapter.py）"
    - "工具 handler 不 raise_for_status：显式判 status_code，401/403/非200/传输错误一律 return is_error（RTOOL-04 graceful）"
    - "options_kwargs dict 条件加键 + ClaudeAgentOptions(**kwargs)（条件挂载向后兼容范式）"
    - "PAT 仅进 Authorization header；日志只记 has_user_token bool / tool 名（脱敏）"
key-files:
  created:
    - task/core/remote_tools.py
  modified:
    - task/core/config.py
    - task/core/executor.py
    - task/tests/test_claude_sdk_integration.py
decisions:
  - "[11-02] TaskConfig.remote_tools 采用 pydantic v2 复杂类型 env 自动 JSON 解码（A2 首选路径）——实测 FRIDAY_TASK_REMOTE_TOOLS='[{...}]' 直接解析为 list[dict]，无需 model_validator + json.loads 兜底"
  - "[11-02] handler 不 raise_for_status，显式 status_code 分支（401/403→令牌失效文本 / !=200→HTTP {code} / 传输错误→catch httpx.HTTPError），全部 return is_error 不抛（RTOOL-04）"
  - "[11-02] executor 装配先 build_remote_tools_mcp_server → None 守卫，仅非 None 时给 options 加 mcp_servers/allowed_tools，log 加 has_user_token bool + remote_tool_count（绝不记 PAT 明文）"
metrics:
  duration_min: 9
  tasks: 3
  files: 4
  completed: 2026-06-10
---

# Phase 11 Plan 02: task 容器侧 RemoteTool 机制 Summary

新建 `task/core/remote_tools.py` 把 `remote_tools` schema 列表动态注册为进程内 SDK MCP server，每个工具 handler 以直传 PAT 回调 Phase 10 的 `/api/tools/execute/`（401/403/非200/传输错误一律返回结构化工具错误不崩容器）；扩展 `TaskConfig` 三字段（FRIDAY_TASK_ 前缀）；在 `_execute_claude` 装配点条件挂载 `mcp_servers`/`allowed_tools`。使 11-01 task 侧 RED 用例全转 GREEN，PAT 全程仅进 Authorization header 不入日志，零新增依赖。

## What Was Built

### Task 1 — task/core/remote_tools.py（新建）— commit `df7f2208`
- `REMOTE_MCP_SERVER_NAME = "friday-remote-tools"` + `logger = structlog.get_logger(__name__)`。
- `_make_handler(tool_name, tools_endpoint, user_token)` → `async def handler(args) -> dict`：`httpx.AsyncClient` POST `tools_endpoint`，json=`{"name", "arguments"}`，headers 带 `Authorization: Bearer <PAT>` + `Content-Type`，timeout=60。**不** `raise_for_status`；`try/except httpx.HTTPError`→is_error；401/403→「工具不可用：令牌已失效或无权限」is_error；!=200→`HTTP {code}` is_error；==200 解析 body `ok`（ok→text(result)，否则 is_error text(error)）。日志仅 `logger.warning(tool=, status=)`，绝不入 token。
- `build_remote_tools_mcp_server(remote_tools, tools_endpoint, user_token) -> McpSdkServerConfig | None`：任一为空→None（向后兼容）；否则逐条 `SdkMcpTool(...)` + `logger.info("remote_mcp_server_created", tool_count=, tools=[names])`（不打印 token）+ `create_sdk_mcp_server(...)`。
- `remote_allowed_tools(remote_tools)` → `[f"mcp__{REMOTE_MCP_SERVER_NAME}__{name}"]`。
- 结果：`tests/test_remote_tools.py` 10 passed（11-01 importorskip 守卫从 skip 转硬断言全 GREEN）。

### Task 2 — task/core/config.py（TaskConfig 三字段）— commit `13255aff`
- 新增 `user_token: str = ""`、`tools_endpoint: str = ""`、`remote_tools: list[dict] = []`（FRIDAY_TASK_ 前缀经 env_prefix 自动映射）。
- 实测确认 pydantic v2 自动 JSON 解码：`FRIDAY_TASK_REMOTE_TOOLS='[{"name":"a","input_schema":{}}]'` → `config.remote_tools` 解析为含 1 dict 的 list（无需手动 json.loads）。
- 默认空保证不设 env 时行为与现状完全一致（clean-env 验证 + `tests/test_config.py` 5 既有用例不退）。

### Task 3 — task/core/executor.py 条件装配 + 扩展测试 — commit `257f41be`
- 顶部 `from .remote_tools import REMOTE_MCP_SERVER_NAME, build_remote_tools_mcp_server, remote_allowed_tools`。
- `_execute_claude` 构造前 `mcp_server = build_remote_tools_mcp_server(...)`；`ClaudeAgentOptions(...)` 改为先组 `options_kwargs`（保持全部现有键不变），`if mcp_server is not None:` 加 `mcp_servers={REMOTE_MCP_SERVER_NAME: mcp_server}` + `allowed_tools=remote_allowed_tools(...)`，末 `ClaudeAgentOptions(**options_kwargs)`。
- `log.info("Executing Claude Agent SDK", ...)` 加 `has_user_token=bool(...)` + `remote_tool_count=len(...)`，**不**记 token 值。
- 扩展 `tests/test_claude_sdk_integration.py`：`test_options_include_mcp_when_remote_tools_present`（有 token+tools→options 含 mcp_servers 键 + allowed_tools == `mcp__friday-remote-tools__a`）、`test_options_omit_mcp_when_no_remote_tools`（无→options 不含 server 键，向后兼容）、`test_executor_logs_no_pat_plaintext`（捕获 structlog 无 PAT 明文）；monkeypatch `core.executor.query` 为空 async generator 捕获 options，不触网。

## Verification Results

| 命令 | 结果 |
|------|------|
| `cd task && uv run pytest tests/test_remote_tools.py -q` | 10 passed |
| `cd task && uv run pytest tests/test_config.py tests/test_remote_tools.py -q` | 15 passed |
| `cd task && uv run pytest tests/test_claude_sdk_integration.py tests/test_remote_tools.py -q` | 18 passed, 3 skipped |
| `cd task && uv run pytest tests/test_remote_tools.py tests/test_callback.py tests/test_claude_sdk_integration.py -q` | 35 passed, 3 skipped（回归不退） |
| `rg "user_token" task/core/remote_tools.py task/core/executor.py` | 仅出现于 header 注入 / None 守卫 / 签名 / docstring，无 logger/print 打印 token 值 |

3 skipped 为需真实 API Key 的集成测试（既有 skipif 守卫，非回退）。1 个 callback.py datetime.utcnow DeprecationWarning 为既有、本 plan 范围外。

## Deviations from Plan

None — plan 按写执行。Task 2 沿 A2 首选路径（pydantic v2 自动 JSON 解码）落地，实测通过，未触发 `model_validator + json.loads` 兜底分支。

## Known Stubs

无。三字段默认空属设计内的向后兼容路径（不挂 MCP server），非未完成 stub。

## Threat Flags

无新增计划外安全面。本 plan 落地 threat register 中 T-11-04（PAT 不入日志/返回文本，由 `test_token_not_in_logs_or_result` + `test_executor_logs_no_pat_plaintext` 守卫）、T-11-05（401/403/非200/传输错误 graceful，由 `test_handler_401/transport/non200` 守卫）、T-11-06（返回文本不含 token）三项 mitigate。

## Self-Check: PASSED

- 创建文件存在：`task/core/remote_tools.py`、`.planning/phases/11-rtool/11-02-SUMMARY.md`。
- 修改文件存在：`task/core/config.py`、`task/core/executor.py`、`task/tests/test_claude_sdk_integration.py`。
- 提交存在：`df7f2208`（Task 1）、`13255aff`（Task 2）、`257f41be`（Task 3）。
