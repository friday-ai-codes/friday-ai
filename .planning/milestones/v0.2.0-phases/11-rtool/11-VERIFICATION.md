---
phase: 11-rtool
verified: 2026-06-10T02:55:00Z
status: human_needed
score: 4/4 must-haves verified (mechanism)
overrides_applied: 0
re_verification:
  previous_status: none
  note: initial verification
accepted_followups:

  - item: "自动解析存量/背景任务的 PAT 明文（实时请求线程明文通道，如 contextvar）"
    rationale: "Open Q1 裁决 Option C + 机会性 B；PAT-02 禁止从 DB 读明文。_resolve_user_pat 现返回 \"\"（机制就绪、休眠），自动注入留 follow-up。此为 by-design，非 gap。"
    location: "server/workflows/nodes/ai/coding.py:812-829 (TODO(RTOOL follow-up))"
human_verification:

  - test: "真实容器 + 真实 Claude SDK loop：注入 remote_tools + 有效 PAT + tools_endpoint，确认 agent 经 create_sdk_mcp_server 真正加载并调用远程工具完成端到端闭环，且 builtin Bash/Edit/Write 仍可用（execute 模式）"
    expected: "agent 实际调用 mcp__friday-remote-tools__* 工具并经 /api/tools/execute/ 以 owner 身份执行；编码内建工具不被排他白名单禁掉"
    why_human: "需真实 claude-agent-sdk query() 循环 + 运行容器；单测以 monkeypatch httpx/query 验证装配契约，无法验证真实 SDK 加载/调用行为"

  - test: "docker inspect <task 容器> 与 runner/task 运行日志检查"
    expected: "环境变量与日志中不出现明文 friday_pat_* 令牌（仅在 Authorization header 与 env 注入，日志只记 has_user_token/remote_tool_count 等 bool/计数）"
    why_human: "需运行中的真实容器与真实日志输出；静态审查已确认无 PAT 落入任何 log 语句，但 docker inspect 时点的运行态需人工确认"

  - test: "在途任务运行中吊销该用户 PAT（实时注入 PAT 场景），观察任务行为"
    expected: "已在途的工具调用收到 401/403 → 结构化工具错误回传 agent，容器不崩、任务 graceful 跑完其余工作；仅后续新调用被阻断"
    why_human: "需真实运行任务 + 实时吊销时序；单测验证 handler 对 401/403 的 graceful 返回，但完整在途时序需 E2E"
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: human_needed
---

# Phase 11: task 容器接通（RemoteTool 链路闭环）Verification Report

**Phase Goal:** task 容器消费 `remote_tools` 并经 SDK MCP server 真正加载调用工具，用户令牌以直传 PAT 安全注入（脱敏），令牌吊销时在途任务 graceful 跑完仅阻断新调用
**Verified:** 2026-06-10T02:55:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | task 容器消费 `remote_tools`，agent 经 `create_sdk_mcp_server` proxy 真正加载并调用工具（含 builtin/mcp/skill） | ✓ VERIFIED (mechanism) | `task/core/remote_tools.py:130-188` `build_remote_tools_mcp_server` 逐条 schema→`SdkMcpTool`→`create_sdk_mcp_server`；`task/core/executor.py:307-331` 条件挂载 `mcp_servers` + `allowed_tools`，且 `_BUILTIN_CODING_TOOLS`(Bash/Edit/Write/Read/Glob/Grep) 与远程工具一并列入（WR-02 已修，排他白名单不禁内建）。真实 SDK 加载/调用→人工 E2E。 |
| 2 | 用户令牌以直传 PAT 经 server→runner→task 注入容器，agent 以用户身份回调执行端点完成闭环 | ✓ VERIFIED (mechanism) | 三跳贯通：server `coding.py:885-911` 注入 `env_FRIDAY_TASK_TOOLS_ENDPOINT`(+机会性 `env_FRIDAY_TASK_USER_TOKEN`) → runner `executor.go:117` 新增 `FRIDAY_TASK_REMOTE_TOOLS` + `env_` TrimPrefix 透传(`:124-133`) → task `config.py:86-97` 三字段 + handler `Authorization: Bearer <PAT>` POST `/api/tools/execute/`(`remote_tools.py:62-74`)。端到端真实闭环→人工 E2E。 |
| 3 | `docker inspect` 与 runner/task 日志中不出现明文令牌（注入与脱敏同阶段交付） | ✓ VERIFIED (static) | 全仓 grep 无任何 log 语句打印 token 值；task 仅记 `tool`/`status`，executor 记 `has_user_token=bool`/`remote_tool_count`(`executor.py:340-341`)，server 记 `has_user_token=bool`/`has_tools_endpoint`(`coding.py:960-961`)，runner zerolog 仅记 task_id/container_id(`executor.go:86`)。运行态 docker inspect→人工。 |
| 4 | 令牌吊销时在途任务 graceful 跑完仅阻断新调用，鉴权失效为不可重试终止态回传结构化错误 | ✓ VERIFIED | `remote_tools.py:62-125` handler 不 `raise_for_status`：传输错误/401-403/非200/非JSON 一律 `return {is_error: True}`，绝不抛。测试 `test_handler_401_returns_tool_error_not_raise` 等钉死。完整在途吊销时序→人工 E2E。 |

**Score:** 4/4 truths verified (机制层面完整且正确)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `task/core/remote_tools.py` | SDK MCP 构建 + PAT 回调 handler + graceful | ✓ VERIFIED | 204 行，含 `build_remote_tools_mcp_server`/`_make_handler`/`remote_allowed_tools`/`REMOTE_MCP_SERVER_NAME` + `_is_valid_tools_endpoint`(WR-03) + name 容错(WR-04) |
| `task/core/config.py` | TaskConfig 三字段 | ✓ VERIFIED | `user_token`/`tools_endpoint`/`remote_tools` 默认空（向后兼容），`FRIDAY_TASK_` 前缀映射 |
| `task/core/executor.py` | 条件装配 mcp_servers/allowed_tools | ✓ VERIFIED | `:307-332` 仅 `mcp_server is not None` 才加键；内建工具保留 |
| `runner/internal/docker/executor.go` | FRIDAY_TASK_REMOTE_TOOLS + env_ 透传 | ✓ VERIFIED | `:117` 前缀修复（与旧 FRIDAY_REMOTE_TOOLS 同源同值）；`:128` `s != ""` 守卫不注入空键 |
| `server/workflows/nodes/ai/coding.py` | tools_endpoint(FRIDAY_BASE_URL 推导) + 机会性 PAT | ✓ VERIFIED | `:886-891` base 推导 `/api/tools/execute/`；`if user_pat` 才注入；`_resolve_user_pat` 返回 ""（休眠 follow-up） |

### Key Link Verification

| From | To | Via | Status |
|------|-----|-----|--------|
| executor._execute_claude | remote_tools.build_remote_tools_mcp_server | `build_remote_tools_mcp_server(remote_tools, tools_endpoint, user_token)` | ✓ WIRED (`executor.py:307`) |
| _make_handler | `/api/tools/execute/` | httpx POST + `Authorization: Bearer <PAT>` | ✓ WIRED (`remote_tools.py:62-74`) |
| coding._run_repo_coding | DispatchTask.metadata | `env_FRIDAY_TASK_TOOLS_ENDPOINT = {FRIDAY_BASE_URL}/api/tools/execute/` | ✓ WIRED (`coding.py:888,911`) |
| 实时请求线程 PAT(可选) | env_FRIDAY_TASK_USER_TOKEN | `_execute_with_branch → _resolve_user_pat → user_pat` 透传 | ⚠️ WIRED but DORMANT (`_resolve_user_pat` 返回 ""，by-design follow-up) |
| payload.metadata env_* | 容器 env FRIDAY_TASK_* | runner `TrimPrefix("env_")` 循环 | ✓ WIRED (`executor.go:124-133`) |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| RTOOL-02 | 11-01/02 | task 经 SDK MCP server 真正加载调用 remote_tools | ✓ SATISFIED (mechanism) | build/mount/handler 全贯通 + builtin 保留；真实 SDK 加载→人工 |
| RTOOL-03 | 11-01/03/04 | 直传 PAT server→runner→task 注入 + 脱敏 | ✓ SATISFIED (mechanism) | 三跳 env 名一致；endpoint 由 FRIDAY_BASE_URL；机会性 PAT 绝不读 DB；各层脱敏。自动解析存量 PAT = 已接受 follow-up |
| RTOOL-04 | 11-01/02 | 吊销 graceful 仅阻断新调用 | ✓ SATISFIED | handler 401/403/非200/传输/非JSON 全 graceful 不抛 |

### Behavioral Spot-Checks / Test Execution

| Suite | Command | Result | Status |
|-------|---------|--------|--------|
| task | `cd task && uv run pytest tests/test_remote_tools.py tests/test_callback.py tests/test_claude_sdk_integration.py -q` | **46 passed, 3 skipped** (3 skip = `FRIDAY_RUN_INTEGRATION_TESTS` 门控的 live-API) | ✓ PASS |
| server | `cd server && uv run pytest tests/test_remote_tool_dispatch.py tests/test_remote_tool_execute.py -q` | **11 passed** | ✓ PASS |
| runner | `cd runner && go test ./internal/docker/...` | **ok** (TestBuildContainerEnv_RemoteTools / _NoPATNoEmptyKey / Separates 全 PASS) | ✓ PASS |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `coding.py` | 812-829 | `_resolve_user_pat` 硬编码 `return ""` | ℹ️ Info (by-design) | 链路休眠：无实时明文通道前 MCP server 永不挂载。Open Q1 Option C 决策，非 gap；`TODO(RTOOL follow-up)` 已标注 |
| `executor.go` | 91 | `json.Marshal(...)` 忽略 err（`_`） | ℹ️ Info | nil→""(安全向后兼容值)；REVIEW IN-02 已接受 |

无 BLOCKER / WARNING 级反模式。无未引用的 TBD/FIXME/XXX 调试标记。

### Human / E2E Verification Required

详见 frontmatter `human_verification`。三项均需真实容器 + 真实 Claude SDK loop，单测（monkeypatch httpx/query）无法覆盖：

1. **真实 SDK 加载并调用远程工具**（端到端「需求→agent→调用用户授权工具」闭环 + builtin 工具在 execute 模式可用）。
2. **`docker inspect` + 运行日志无明文 PAT**（静态已证无 log 泄漏，运行态需人工确认）。
3. **在途吊销 graceful**（实时注入 PAT 场景下吊销，任务跑完仅阻断新调用）。

### Accepted Follow-up（非 gap，供里程碑审计可见）

**自动 PAT 明文解析休眠**：`_resolve_user_pat` 当前返回 `""`，因此当前任何 dispatch 路径都不会注入 `FRIDAY_TASK_USER_TOKEN`，task 侧 `build_remote_tools_mcp_server` 恒返回 None——**RemoteTool 链路端到端处于休眠态**，直到接入「实时请求线程明文 PAT 通道（如 contextvar）」的 follow-up 落地。这是 CONTEXT Open Q1 裁决（Option C + 机会性 B）的**有意设计**：PAT-02 禁止从 DB 读明文，故背景/飞书触发任务的自动注入留作已知 follow-up，**不阻塞里程碑**。下游消费者在该 follow-up 落地前不得假设远程工具已上线。

### Summary

机制（mechanism）层面 RTOOL-02 / RTOOL-03 / RTOOL-04 **完整且正确**：三组件契约字段名一致、endpoint 由 FRIDAY_BASE_URL 派生、PAT 仅进 header 且各层脱敏、绝不从 AccessToken/DB 读明文、handler 对所有失败路径 graceful 不抛、builtin 编码工具在挂载远程工具时被保留。全部自动化测试通过（task 46、server 11、runner 全绿）。状态判定为 **human_needed**：机制已验证，但「真实 Claude SDK 加载调用 / docker inspect 无明文 / 实时吊销 graceful」三项需真实容器 E2E 人工确认。自动解析存量 PAT 为**已接受的 by-design follow-up**，非 gap。

---

_Verified: 2026-06-10T02:55:00Z_
_Verifier: Claude (gsd-verifier)_
