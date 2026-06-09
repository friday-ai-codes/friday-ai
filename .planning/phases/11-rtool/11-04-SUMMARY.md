---
phase: 11-rtool
plan: 04
subsystem: server
tags: [rtool, dispatch, pat-injection, tools-endpoint, sdk-mcp, security]
requires: [RTOOL-03]
provides:
  - "server dispatch 注入 RemoteTool 链路：env_FRIDAY_TASK_TOOLS_ENDPOINT（FRIDAY_BASE_URL 推导）+ 机会性 env_FRIDAY_TASK_USER_TOKEN"
  - "AICodingNode._resolve_user_pat 机会性 PAT 解析器（实时请求线程明文，绝不读 DB）"
  - "11-01 server RED 用例全部转 GREEN（4/4）"
affects:
  - server/workflows/nodes/ai/coding.py
tech-stack:
  added: []
  patterns:
    - "tools_env dict-then-merge（仅非空才注入键），mirror 既有 anthropic_env 范式"
    - "可选 user_pat 形参透传（mirror anthropic_api_key 先例）+ _resolve_user_pat 解析器"
    - "日志只记 has_tools_endpoint / has_user_token bool，敏感明文绝不入 log"
key-files:
  created: []
  modified:
    - server/workflows/nodes/ai/coding.py
decisions:
  - "[11-04] tools endpoint 强制由 settings.FRIDAY_BASE_URL 拼 /api/tools/execute/ 推导，绝不用 runner callback_url（Pitfall 1 / T-11-13）"
  - "[11-04] 机会性 PAT 经 _resolve_user_pat 解析器 + 可选 user_pat 形参注入；无实时明文来源返回 ''，省略 env_FRIDAY_TASK_USER_TOKEN（PAT-02，绝不读 AccessToken/DB）"
  - "[11-04] _resolve_user_pat 当前实现返回 ''（机制就绪），实时请求线程明文 PAT 通道接入留 follow-up（per Open Q1 Option C + 机会性 B）"
metrics:
  duration_min: 6
  tasks: 2
  files: 1
  completed: 2026-06-10
---

# Phase 11 Plan 04: server dispatch 注入（tools endpoint + 机会性 PAT） Summary

在 `server/workflows/nodes/ai/coding.py` 的 dispatch 装配处注入 RemoteTool 闭环的 server 这一跳：`env_FRIDAY_TASK_TOOLS_ENDPOINT` 由 `settings.FRIDAY_BASE_URL` 推导（拼 `/api/tools/execute/`，绝不用 callback_url），并以**机会性** `env_FRIDAY_TASK_USER_TOKEN`（仅实时请求线程明文可用时，绝不读 AccessToken/DB）注入；使 11-01 server RED 用例全部转 GREEN，遵守 PAT-02（明文绝不落盘/不可从 DB 取）与 Open Q1 裁决（机制完整 + 脱敏，自动解析存量 PAT 留 follow-up）。

## What Was Built

### Task 1 — coding.py tools_endpoint 注入（FRIDAY_BASE_URL 推导）— commit `399a233c`
- 在 `_run_repo_coding` 构造 `anthropic_env` 之后、`DispatchTask(...)` 之前，新增 `tools_env: dict[str, str] = {}`。
- `from django.conf import settings`；`base = getattr(settings, "FRIDAY_BASE_URL", "").rstrip("/")`。
- `if base: tools_env["env_FRIDAY_TASK_TOOLS_ENDPOINT"] = f"{base}/api/tools/execute/"`（契约：空 base 不注入该键 → 向后兼容降级，task 侧无 endpoint 不挂 MCP server）。
- 在 `DispatchTask(...).metadata` 末尾展开 `**tools_env`（与 `**anthropic_env` 并列）。
- `task_dispatched_to_runner` 日志加 `has_tools_endpoint=bool(base)`，绝不记端点明文值。

### Task 2 — coding.py 机会性 PAT 注入（实时请求线程，绝不读 DB）— commit `5a07924f`
- 新增 `AICodingNode._resolve_user_pat(context) -> str` 解析器：唯一合法明文来源为「带 PAT 的实时认证请求线程」；**绝不**从 AccessToken/ToolTokenBinding/任何 DB 表读明文（PAT-02）；当前实现返回 `""`（无现成实时线程明文通道，背景/飞书触发 triggered_by/AgentSession.user 可能为 None，均非明文来源），机制就绪，实时通道接入留 TODO follow-up。
- `_run_repo_coding` 按 `anthropic_api_key` 先例新增可选形参 `user_pat: str = ""`。
- `tools_env` 装配处追加 `if user_pat: tools_env["env_FRIDAY_TASK_USER_TOKEN"] = user_pat`（无明文 → 不注入该键，不阻塞 dispatch）。
- `_execute_with_branch` 在分发循环前 `user_pat = await self._resolve_user_pat(context)`，以 `user_pat=` 透传每个 `_run_repo_coding`。
- `task_dispatched_to_runner` 日志加 `has_user_token=bool(user_pat)`，PAT 明文绝不入 log。

注：`remote_tools` 的 `FRIDAY_TASK_` 前缀注入由 11-03 runner 侧从既有 payload 负责（payload 单一真源），本 plan 不重复 fetch/不双注入。

## Verification Results

| 命令 | 结果 |
|------|------|
| `uv run pytest tests/test_remote_tool_dispatch.py -q` | **4 passed**（endpoint / opportunistic-PAT / omit-PAT / never-reads-DB 全 GREEN） |
| `uv run pytest tests/test_coding_anthropic_base_url_passthrough.py -q` | **12 passed**（anthropic_env 行为未回退） |
| `uv run pytest .../test_remote_tool_dispatch.py + ...base_url_passthrough.py + test_remote_tool_execute.py -q` | **23 passed**（含 Phase 10 执行端点回归） |
| `rg "AccessToken.objects" server/workflows/nodes/ai/coding.py` | 无匹配（确认 dispatch 路径不读令牌明文，T-11-02） |
| `rg "FRIDAY_BASE_URL" server/workflows/nodes/ai/coding.py` | 命中端点推导 |

具体 GREEN 用例：`test_dispatch_metadata_includes_tools_endpoint`（值 == `https://friday.example.com/api/tools/execute/`）、`test_dispatch_opportunistic_pat_injected_when_present`（monkeypatch `_resolve_user_pat` → 注入 `friday_pat_REALTIME`）、`test_dispatch_omits_pat_when_no_realtime_source`（无来源不注入）、`test_dispatch_never_reads_access_token_plaintext`（AccessToken.objects 零调用 + metadata 无 `friday_pat_`）。

## Deviations from Plan

None — plan 按写执行。`_resolve_user_pat` 默认返回 `""` 是计划内决策（Open Q1 Option C + 机会性 B：机制完整就绪，实时请求线程明文 PAT 通道接入作为已知 follow-up，不违反 PAT-02、不阻塞里程碑）。

## Known Stubs

- `AICodingNode._resolve_user_pat` 当前返回 `""`（机制就绪 stub）：实时请求线程明文 PAT 通道（如 contextvar）接入留 follow-up。此为 Open Q1 裁决明确的「机制完整 + 自动解析存量 PAT 不在本期」范围，**非**未完成 stub——server 注入链已打通（test_dispatch_opportunistic_pat_injected_when_present 经 monkeypatch 该解析器证明注入路径就绪），且不引入空 token 注入（无明文 → 省略键）。

## Threat Flags

无新增安全面。本 plan 强化既有信任边界：tools endpoint 强制 FRIDAY_BASE_URL 推导（T-11-13）、PAT 明文零 DB 读取（T-11-02/T-11-11）、PAT 明文不入日志（T-11-12）、无明文来源 fail-closed 降级（T-11-14）——均有对应 GREEN 守卫用例。零新增依赖（仅用既有 `django.conf.settings`，T-11-SC）。

## Self-Check: PASSED

- 修改文件存在：`server/workflows/nodes/ai/coding.py`。
- 提交存在：`399a233c`（Task 1 tools endpoint）、`5a07924f`（Task 2 机会性 PAT）。
- 验证命令全 GREEN（23 passed），rg 守卫确认零 AccessToken 明文读取。
