---
phase: 11-rtool
plan: 01
subsystem: testing
tags: [rtool, tdd-red, sdk-mcp, pat-injection, dispatch-contract, cross-component]
requires: [RTOOL-02, RTOOL-03, RTOOL-04]
provides:
  - "task/server/runner 三组件 Wave 0 RED 测试，钉死 RemoteTool 闭环可验证契约"
  - "跨进程契约字段名三侧一致：FRIDAY_TASK_USER_TOKEN / FRIDAY_TASK_REMOTE_TOOLS / FRIDAY_TASK_TOOLS_ENDPOINT"
  - "WR-3 机制钉定：机会性 PAT 经可选 user_pat 形参（_resolve_user_pat 解析器）注入"
affects:
  - task/core/remote_tools.py（Wave 1 11-02 落地转 GREEN）
  - server/workflows/nodes/ai/coding.py（Wave 2 11-04 落地转 GREEN）
  - runner/internal/docker/executor.go（Wave 2 11-03 落地转 GREEN）
tech-stack:
  added: []
  patterns:
    - "importorskip 守卫：impl 未落地优雅 skip，无 collection error（mirror Phase 10 10-01）"
    - "SDK MCP server handler 直接单测（monkeypatch httpx.AsyncClient.post，无 live Claude/query）"
    - "dispatch metadata 捕获范式（mock_dispatcher 复刻 test_coding_anthropic_base_url_passthrough.py）"
    - "metadata env_ 前缀 TrimPrefix 透传（runner Go）"
key-files:
  created:
    - task/tests/test_remote_tools.py
    - server/tests/test_remote_tool_dispatch.py
  modified:
    - task/tests/conftest.py
    - runner/internal/docker/executor_test.go
decisions:
  - "[11-01] WR-3 fix：机会性 PAT 经 _run_repo_coding 可选 user_pat 形参下传（mirror anthropic_api_key），_execute_with_branch 经 AICodingNode._resolve_user_pat 解析实时明文；server 测试 monkeypatch 该解析器钉死 11-04 实现形态"
  - "[11-01] test_builds_n_tools 经 McpSdkServerConfig instance 的 ListToolsRequest 处理器读工具名（SDK 返回 {type:sdk,name,instance}，instance 为 mcp lowlevel Server）"
  - "[11-01] omit-PAT 与 never-reads-DB 为安全负向不变量，Wave 0 即 GREEN 且须保持（非 RED）"
metrics:
  duration_min: 14
  tasks: 3
  files: 4
  completed: 2026-06-09
---

# Phase 11 Plan 01: Wave 0 RED 脚手架（RemoteTool 闭环跨三组件） Summary

在 task / server / runner 三组件各落一套自动化测试，用 RED-first 钉死 RemoteTool 闭环的可验证行为契约（RTOOL-02 SDK MCP 构建与调用、RTOOL-03 三跳注入与脱敏、RTOOL-04 吊销 graceful），并跨进程统一契约字段名；本 plan 不写任何生产代码，测试预期 RED 直至 Wave 1/2（11-02/11-03/11-04）落地转 GREEN。

## What Was Built

### Task 1 — task/tests/test_remote_tools.py（新建）+ conftest 扩展 — commit `ab4a57c6`
- `task/tests/test_remote_tools.py`：模块顶部 `pytest.importorskip("core.remote_tools")` 守卫，impl 未落地时整模块优雅 skip（0 collection error）。覆盖：
  - RTOOL-02：`test_builds_n_tools`（2 schema → 含 2 工具 a/b 的 MCP server，经 instance 的 ListToolsRequest 处理器断言工具名）、`test_no_remote_tools_returns_none` / `test_no_token_returns_none` / `test_no_endpoint_returns_none`（向后兼容不挂 server）、`test_remote_allowed_tools_naming`（`mcp__{server}__{name}`）、`test_handler_success_returns_content`。
  - RTOOL-04：`test_handler_401_returns_tool_error_not_raise`、`test_handler_transport_error_graceful`、`test_handler_non200_returns_tool_error`（401/传输错误/500 一律 `is_error` 结构化错误，绝不抛）。
  - RTOOL-03 脱敏：`test_token_not_in_logs_or_result`（成功 + 401 两路，捕获 structlog 日志与返回文本均无 `friday_pat_SECRET123`，T-11-01）。
  - 测试用 monkeypatch `httpx.AsyncClient.post` 返回伪响应，**不** import `claude_agent_sdk.query`、不触网。
- `task/tests/conftest.py`：`mock_config` 补 `user_token` / `remote_tools` / `tools_endpoint` 三字段（默认空 = 向后兼容）。

### Task 2 — server/tests/test_remote_tool_dispatch.py（新建）— commit `69617194`
- 复刻 `test_coding_anthropic_base_url_passthrough.py` 的 dispatch 捕获 fixture 套（就地复制，独立可单跑）。
- `test_dispatch_metadata_includes_tools_endpoint`（RED）：`settings.FRIDAY_BASE_URL` override → 断言 `metadata["env_FRIDAY_TASK_TOOLS_ENDPOINT"] == "https://friday.example.com/api/tools/execute/"`（由 base 推导，非 callback_url，Pitfall 1）。
- `test_dispatch_opportunistic_pat_injected_when_present`（RED，**WR-3 钉定**）：monkeypatch `AICodingNode._resolve_user_pat` 返回 `friday_pat_REALTIME` 模拟实时明文来源 → 断言 `metadata["env_FRIDAY_TASK_USER_TOKEN"] == "friday_pat_REALTIME"`。钉死 11-04 须实现：`_resolve_user_pat` 解析器 + 可选 `user_pat` 形参（mirror `anthropic_api_key`）+ metadata 注入。
- `test_dispatch_omits_pat_when_no_realtime_source`（GREEN 不变量）：无明文来源 → metadata 不含 `env_FRIDAY_TASK_USER_TOKEN`（PAT-02）。
- `test_dispatch_never_reads_access_token_plaintext`（GREEN 不变量，T-11-02）：spy `AccessToken.objects.{filter,get,aget,all,afirst}` → 断言 dispatch 路径零调用 + metadata 无 `friday_pat_`。

### Task 3 — runner/internal/docker/executor_test.go 扩展 — commit `6d68ea96`
- `TestBuildContainerEnv_RemoteTools`（RED）：断言 `FRIDAY_TASK_REMOTE_TOOLS` 非空且含工具名 `a`（Pitfall 2 前缀修复——现状仅注 `FRIDAY_REMOTE_TOOLS`，11-03 落地前 RED）+ metadata env_ 透传 `FRIDAY_TASK_USER_TOKEN` / `FRIDAY_TASK_TOOLS_ENDPOINT`（已 GREEN）。
- `TestBuildContainerEnv_RemoteTools_NoPATNoEmptyKey`（GREEN）：无 PAT 键不注入空键（既有 `s != ""` 守卫，向后兼容）。

## Expected-RED Status（impl 落地前）

| 组件 | 命令 | 结果 | 说明 |
|------|------|------|------|
| task | `cd task && uv run pytest tests/test_remote_tools.py -q` | 1 skipped, 0 errors | importorskip 守卫，`core.remote_tools` 未落地 → 整模块优雅 skip（无 collection error）。11-02 落地后转硬断言 |
| server | `cd server && uv run pytest tests/test_remote_tool_dispatch.py -q` | 2 failed, 2 passed | RED：tools_endpoint / opportunistic-PAT（KeyError，预期）；GREEN：omit-PAT / never-reads-DB（安全不变量）。11-04 落地后 4/4 GREEN |
| runner | `cd runner && go test ./internal/docker/ -run TestBuildContainerEnv_RemoteTools` | FAIL（RemoteTools）/ PASS（NoPAT） | RED：`FRIDAY_TASK_REMOTE_TOOLS` 缺失（前缀错位），11-03 落地后转 PASS |

**回归不退**：server `test_coding_anthropic_base_url_passthrough.py` 12 passed；task `test_callback.py`+`test_claude_sdk_integration.py` 22 passed/3 skipped；runner 既有 `TestBuildContainerEnvSeparatesTaskModeAndTaskType` 通过。gofmt 干净。

## Deviations from Plan

None — plan 按写执行。WR-3 plan-checker fix 已按指示应用：机会性 PAT 注入机制钉定为可选 `user_pat` 形参（经 `_resolve_user_pat` 解析器），server dispatch 测试 monkeypatch 该解析器以钉死 11-04 实现形态。`test_builds_n_tools` 经 SDK 返回 config 的 `instance`（mcp lowlevel Server）的 `ListToolsRequest` 处理器读工具名——SDK 0.1.58 实测返回 `{type:"sdk", name, instance}`，instance 无简单 tools 列表属性，故走请求处理器内省（属计划内"按返回结构取名称"的具体实现选择，非偏离）。

## Known Stubs

无生产代码改动（纯测试文件）。三组件测试以 RED 形态等待 Wave 1/2 生产实现：
- task：`core/remote_tools.py`（11-02）—— `build_remote_tools_mcp_server` / `_make_handler` / `remote_allowed_tools` / `REMOTE_MCP_SERVER_NAME`。
- runner：`executor.go buildContainerEnv` 注入 `FRIDAY_TASK_REMOTE_TOOLS`（11-03）。
- server：`coding.py` 的 `_resolve_user_pat` + `user_pat` 形参 + `env_FRIDAY_TASK_TOOLS_ENDPOINT`/`env_FRIDAY_TASK_USER_TOKEN` metadata 注入（11-04）。
这些 RED 是 Nyquist「先测后实现」的预期状态，非未完成 stub。

## Threat Flags

无新增安全面（纯测试文件）。测试本身是 T-11-01（PAT 不进日志/返回文本）、T-11-02（不读 AccessToken 明文）、T-11-03（401 graceful）三项安全不变量的可执行守卫。

## Self-Check: PASSED

- 创建文件全部存在：`task/tests/test_remote_tools.py`、`server/tests/test_remote_tool_dispatch.py`、`task/tests/conftest.py`、`runner/internal/docker/executor_test.go`、`.planning/phases/11-rtool/11-01-SUMMARY.md`。
- 提交全部存在：`ab4a57c6`（task）、`69617194`（server）、`6d68ea96`（runner）。
