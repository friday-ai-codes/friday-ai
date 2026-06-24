---
phase: 72-data-collection
plan: "72-03"
subsystem: observability / container-token-chain
tags: [RATE-02, token-usage, container, model-usage-record, tps, redaction]
requires:
  - "72-02: interactions.ledger.arecord_llm_usage(run 可选) + agents.call_source.CallSource + ModelUsageRecord(nullable run / call_source / ttft_ms / upstream_status_code / user_id / source)"
  - "71-05: 容器回调原始留痕脱敏（record_inbound_webhook）"
provides:
  - "task: CallbackClient.report_token_usage —— 容器主动 emit token_usage 回调（补全 task→回调断点）"
  - "task: ClaudeRunner._execute_claude 在 _write_usage_data 后主动 emit + usage 富化（真实 model / ttft_ms / provider）"
  - "server: _handle_token_usage 桥接落 ModelUsageRecord（统一 TPS 源），call_source/user 服务端权威派生"
  - "server: TokenUsagePayloadSerializer 可选字段 ttft_ms/provider/call_source/upstream_status_code/failure_type（向后兼容）"
affects:
  - "TPS 统计（Phase 73 SQL 聚合）现纳入四类容器 LLM token"
tech-stack:
  added: []
  patterns:
    - "best-effort 桥接/emit（独立 try/except swallow，绝不反噬回调/任务主流程）"
    - "服务端权威派生 call_source/user（不信任 runner 可篡改 payload，对齐 cross_repo_relevance 范式）"
    - "单一执行 chokepoint（_execute_claude）覆盖四类容器"
key-files:
  created:
    - server/tests/test_container_token_chain.py
    - task/tests/test_usage_emit.py
  modified:
    - server/subagent/api/serializers.py
    - server/subagent/api/callbacks.py
    - task/integrations/callback.py
    - task/core/executor.py
decisions:
  - "call_source 始终服务端权威派生（忽略 payload.call_source），优先于 plan 行文的 `p.get('call_source') or 派生` —— 遵从 plan 自身 threat T-72-03-TAMPER + 用户 MANDATORY 约束（防 runner 跨类误归因）"
  - "无 model 字段变更 → 仅序列化器可选字段 → 无 migration"
metrics:
  duration: "~25min"
  completed: "2026-06-24"
  tasks: 2
  files: 6
---

# Phase 72 Plan 03: 容器侧 token 链路闭合（task→回调→ModelUsageRecord）Summary

端到端闭合此前断裂的容器 token 链路：task 侧新增 `CallbackClient.report_token_usage` 并由 `_execute_claude` 在写完 `usage.json` 后主动 emit（四类容器经同一 chokepoint 全覆盖），server 侧在既有 `_handle_token_usage` 写 `TokenUsage` 之外**桥接**落一行 `ModelUsageRecord` 纳入统一 TPS 源，`call_source` 与发起用户由 `SubAgentSession` 服务端权威派生，复用 72-02 的 `arecord_llm_usage(run=None)` + `CallSource`。

## PASS/FAIL per task

| Task | 内容 | 结果 |
|------|------|------|
| Task 1 | server 桥接容器 token → ModelUsageRecord（call_source 服务端派生）+ 序列化器可选字段 + 守护测试 | **PASS** |
| Task 2 | task 主动 emit token_usage（补全断点）+ usage 富化 + 四类容器全覆盖 + 守护测试 | **PASS** |

## 端到端确认：容器 token 现已到达 ModelUsageRecord

链路闭合后路径：
1. **task**（`ClaudeRunner._execute_claude`）：执行结束 → 写 `usage.json`（保留，向后兼容兜底）→ 紧随 `await self.callback.report_token_usage(usage_data)`（best-effort），usage_data 富化真实 `model`（SDK/config 解析，失败回退硬编码）、`ttft_ms`（首 AssistantMessage 时延）、`provider`（缺则不放）。四类容器（plan/execute/explore/repo_summary）均经 `_execute_claude` 这一唯一 emit 发送点（funnel 测试断言）。
2. **callback client**：POST `type=token_usage` 到统一回调端点 `/api/containers/callback/`（镜像 `report_completed`/`report_failed`；standalone 返 True 不发；HTTP 失败返 False 不抛）。
3. **server**（`_handle_token_usage`）：写 `TokenUsage`（成本归因既有消费方，零回归）→ 桥接 `arecord_llm_usage(run=None, source="container_callback", ...)` 落 `ModelUsageRecord`，`call_source` 由 `_derive_container_call_source(session)` 服务端派生四类（`workflow_coding_container`/`repo_summary_container`/`deep_analysis_container`/`sdk_agent_task`），`user_id` 由 `_resolve_initiated_user(session)` 从 `main_session.user` / `node_execution→workflow_execution.triggered_by` 派生（无则 `system`）。

测试 `test_coding_token_usage_bridges_to_model_usage_record` 直接断言一次 coding token_usage 回调后 `TokenUsage` 与 `ModelUsageRecord` 各落一行、`call_source=workflow_coding_container`、`run=None`、`user_id` 来自权威来源、tokens 正确 —— **容器 token 确已端到端进入 ModelUsageRecord/TPS**。

## 验证结果

- `cd server && uv run pytest tests/test_container_token_chain.py -x -q` → **9 passed**
- `cd server && uv run pytest tests/test_credential_leak_protection.py -x -q` → **24 passed**（脱敏契约零回归）
- `cd task && uv run pytest tests/test_usage_emit.py -x -q` → **14 passed**
- `cd task && uv run pytest tests/test_callback.py -q` → **17 passed**（既有回调零回归）
- `ruff check`（server: callbacks.py / serializers.py / test_container_token_chain.py；task: callback.py / executor.py / test_usage_emit.py）→ **All checks passed**
- **makemigrations**：无需 —— 仅 `TokenUsagePayloadSerializer` 新增可选字段，无 model 字段变更。

## 安全 / 威胁缓解落实

- **T-72-03-TAMPER**：`call_source` 始终由 `_derive_container_call_source(session)` 服务端权威派生（依据 dispatch 时写入、runner 不可改的 `task_type`/`last_output.source`）；`user_id` 取 `main_session.user`/`workflow_execution.triggered_by`，**绝不**取 runner 可篡改的 `last_output` 任意键。测试 `test_explicit_..._call_source_server_authoritative` 断言：即使 payload 伪造 `call_source=workflow_coding_container`，repo_summary session 仍被服务端覆盖为 `repo_summary_container`。
- **T-72-03-01（脱敏）**：`report_token_usage` 与桥接只承载 token 计数 + provider/model/ttft/call_source/status 元数据，无 prompt/completion 文本；standalone 日志仅记 model。`test_credential_leak_protection.py` 复跑保持绿。
- **T-72-03-03（DoS/反噬）**：emit best-effort（httpx 异常吞 + return False）；executor 整段 try/except swallow；server 桥接独立 try/except，失败仅 `warning("container_token_bridge_failed")`、回调仍返回 `{"status":"ok"}`。测试 `test_bridge_failure_does_not_break_callback` / `test_execute_claude_emit_failure_does_not_break_task` 断言。

## Deviations from Plan

### 1. [Rule 2 - 安全正确性] call_source 始终服务端权威派生（忽略 payload.call_source）

- **背景**：plan Task 1 step 3 行文写 `call_source = p.get("call_source") or _derive_container_call_source(session)`，但 plan 自身 `<threat_model>` T-72-03-TAMPER 与用户 MANDATORY 约束均要求「server-authoritative call_source derivation，don't trust runner-mutable payload」。两者冲突。
- **处置**：桥接采用 `call_source = _derive_container_call_source(session)`（永不采信 payload），且 task 容器侧**不上报** `call_source`（仅作前向兼容占位保留在序列化器）。`CallSource.normalize` 仅能挡非法值，挡不住「合法枚举内的跨类误归因」，故服务端派生是唯一正确缓解。
- **影响**：序列化器仍接受 `call_source`（前向兼容），但桥接不读取；守护测试 `(c)` 改为断言 tamper resistance（更强）。
- **文件**：`server/subagent/api/callbacks.py`、`server/subagent/api/serializers.py`、`server/tests/test_container_token_chain.py`。

### 2. [实现对齐] executor 属性名 `self.callback`（非 plan 行文的 `self.callback_client`）

- plan 伪代码用 `self.callback_client.report_token_usage`，但 `ClaudeRunner` 实际属性是 `self.callback`（`core/runner.py` 以 `callback=self.callback` 注入）。按真实属性名实现，并对 `callback is None`（向后兼容路径）短路不 emit。

### 3. [实现对齐] provider 派生不取不存在的 `session.provider_type`

- plan 提到 `session.provider_type`，但 `SubAgentSession` 无此字段（`provider_type` 在 `TokenUsage`/`WorkflowExecution`）。桥接改用 `p.get("provider") or last_output.get("provider") or ""`；task 侧用 `getattr(config, "claude_provider"/"provider_type", "")`，缺则不放（交 server 兜底）。

## 四类容器全覆盖确认

四类容器执行入口（`run_plan_mode`/`run_execute_mode`/`run_explore_mode`/`run_repo_summary_mode`）**均调用 `_execute_claude`**，emit 发送点位于 `_execute_claude` 内 `_write_usage_data` 之后，故单一 chokepoint 即覆盖四类，无需在各 `run_*` 重复埋点。`test_all_container_modes_funnel_through_execute_claude`（参数化 4 mode）断言四类都到达 `_execute_claude`。

## Self-Check: PASSED

- created `server/tests/test_container_token_chain.py` — FOUND
- created `task/tests/test_usage_emit.py` — FOUND
- modified `server/subagent/api/serializers.py`、`server/subagent/api/callbacks.py`、`task/integrations/callback.py`、`task/core/executor.py` — FOUND
- 全部 verify 命令（server chain 9 / credential 24 / task emit 14 / callback 17）通过，ruff 干净，无 migration 需求。
