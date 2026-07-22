---
phase: 103-container-integration
plan: 01
subsystem: access-tokens / chat / mcp-tools / workflows / subagent / runners
tags: [agent-01, agent-02, task-token, short-ttl, revocation, pat-02]
requires: []
provides:
  - "access_tokens/services.py：mint_task_token / arevoke_task_tokens 统一铸造与吊销入口"
  - "AccessToken.kind（personal/task）+ session_id 字段（迁移 0003）"
  - "三链派发（chat/MCP/workflow）统一铸造短 TTL token 注入 env_FRIDAY_TASK_USER_TOKEN"
  - "两条派发路径注入 env_FRIDAY_TASK_KNOWLEDGE_ENDPOINT（103-02 task 侧消费面）"
  - "五点终态幂等吊销（callbacks×2 + consumers WS×2 + 断连收敛）"
affects:
  - "103-02（token + endpoint 双要素就位后容器知识 MCP 链路激活）"
tech-stack:
  added: []
  patterns:
    - "任务级凭证复用既有 AccessToken 模型 + 认证类零改动（kind 字段仅归类，不参与认证裁决）"
    - "吊销 best-effort 双保险：service 内 try/except 吞异常 + WS 调用点再套一层"
    - "落库副本剔除敏感键（last_output.dispatch.metadata 去 env_FRIDAY_TASK_USER_TOKEN）"
decisions:
  - "token 过期余量取 10 分钟（CONTEXT Claude's Discretion 建议值采纳）"
  - "chat 链 last_output.dispatch 落库副本剔除 token 明文——runner 断连重建 dispatch 时该键缺失，容器降级不挂知识工具（fail-soft，与 user 不可解析降级语义一致）"
  - "T-11-02 spy 断言收窄为 AccessToken 读取类 manager 方法（mint 会 acreate 新行，写入合法）"
  - "amark_cancelled 实际有一个调用方（cancel_repo_summary，REPO_SUMMARY 专属），不 mint token 故不挂吊销钩子；假想终态路径由 expires_at 自过期兜底"
metrics:
  duration: ~35min
  completed: 2026-07-22
  tasks: 3/3
  tests: "targeted 155 passed（lifecycle 14 + remote_tool_dispatch 4 + access_tokens 8 + trigger_dispatcher 14 + coding_wave 7 + subagent + chat）"
---

# Phase 103 Plan 01: 任务级短 TTL token（AGENT-01）Summary

**One-liner:** 三条派发链路（chat / MCP / workflow）统一经 `mint_task_token` 为发起用户新签发 kind=task 短 TTL token（明文仅内存直进容器 env，DB 只存 sha256，expires=timeout+10min），MCP 桥接会话经 `initiating_user` 透传 created_by 不静默失效，五个真实终态写入点幂等吊销，机会性 PAT ContextVar 死通道整体移除，PAT-02 底线不破。

## Tasks

| # | Task | Commit | 关键文件 |
|---|------|--------|----------|
| 1 | AccessToken kind/session_id 迁移 + mint/revoke service + 生命周期测试 | a8e9a49c | access_tokens/models.py, migrations/0003, access_tokens/services.py, tests/test_task_token_lifecycle.py |
| 2 | 三链接线（chat mint + MCP created_by 透传 + workflow 替换透传）+ 知识端点注入 | 48f98efd | chat/coding_session_service.py, mcp_tools/execution_service.py, mcp_tools/views.py, mcp_tools/work_item_execution_service.py, workflows/nodes/ai/coding.py, tests/test_coding_wave.py |
| 3 | 死通道清理 + 五点终态吊销 + 泄漏防线/MCP 覆盖测试 + 存量测试迁移 | af02b945 | workflows/{api/views,triggers/dispatcher,engine/scheduler,nodes/base}.py, subagent/api/callbacks.py, runners/consumers.py, tests/test_remote_tool_dispatch.py, tests/test_trigger_dispatcher.py |

## 实现要点

### Task 1 — 模型扩展 + services
- `AccessToken` 加 `kind`（choices personal/task，default personal，db_index）与 `session_id`（nullable indexed）；认证类 `AccessTokenAuthentication` 零改动（前缀闸门 + sha256 查表逻辑不读这两个字段）。迁移 0003 手写，`makemigrations --check` 无缺失。
- `mint_task_token(user, session_id, timeout_seconds)`：`generate_pat()` 内存生成明文，`acreate` 只落 `hash_token(明文)` + 前后缀指纹，`expires_at = now + timeout + 10min`；事件 `task_token_minted`（session_id/user_id/expires_in_seconds，category=caller，component=access_tokens，绝不含明文）。
- `arevoke_task_tokens(session_id)`：`filter(kind=task, session_id, revoked_at__isnull=True).aupdate(revoked_at=now)` 幂等；整体 try/except 吞异常返回 0（best-effort）；事件 `task_token_revoked`（含 count + initiated_by_user_id="system"）。
- 模块 docstring 写明 PAT-02 语义：mint 是新签发，与"从 DB 反取明文"本质不同。

### Task 2 — 三链接线
- **chat 链**（`dispatch_coding_task`，MCP 复用同函数）：`create_sub_session` 之后、构造 `DispatchTask` 之前，`task_type != "coding_commit"` 时按 `conversation.created_by_id` 解析用户 → mint（timeout 对齐硬编码 3600）→ `env_metadata["env_FRIDAY_TASK_USER_TOKEN"]`；user 不可解析降级不注入；日志只记 `has_user_token=bool`。同点注入 `env_FRIDAY_TASK_KNOWLEDGE_ENDPOINT`（`FRIDAY_BASE_URL.rstrip("/")` 非空才注入，不带路径）。
- **泄漏面加固（超出计划确认项的必要修复，见 Deviations）**：`sub_session.last_output["dispatch"]` 现状会整份落库 `metadata`——token 注入后即成落盘泄漏点，落库副本显式剔除 `env_FRIDAY_TASK_USER_TOKEN` 键。
- **MCP 链**：`dispatch_execution` 加 keyword `initiating_user=None` 透传 `_create_bridge_session(created_by=...)`；`ExecuteCodingPlanView` 与 `ExecuteWorkItemRepoTasksView`→`execute_work_item_repo_tasks`→`_execute_one_task` 链补传 `request.user`（ORM 实例，与 Phase 101 的 `initiated_by_user_id` 字符串归因并行不混用）。
- **workflow 链**：`_resolve_user_pat` 替换为 `_resolve_dispatch_user`（读 `workflow_execution.triggered_by_id`，fields_cache 命中直用否则 afirst）；`_dispatch_wave` / `_run_repo_coding` 形参 `user_pat` 改 `dispatch_user`；env 装配处 mint（session_id 即 execution id，timeout 取 `config.get("timeout_seconds", 1800)`）+ 注入 KNOWLEDGE_ENDPOINT；既有 TOOLS_ENDPOINT 不动。

### Task 3 — 死通道 + 吊销 + 测试
- 删除 `access_tokens/context.py` 及全链管道：`workflows/api/views.py` capture 块、`triggers/dispatcher.py` get_request_pat、`engine/scheduler.py` `_user_pat_plaintext` 写入/下传与 `start_execution` 的 `user_pat` 形参、`nodes/base.py` `user_pat_plaintext` 字段；`common/log_context.py` docstring 中对已删模块的引用一并清理。
- 五点吊销：callbacks `_handle_completed`/`_handle_failed`（service 自吞异常）；consumers WS `_handle_completed`/`_handle_failed` + `_handle_disconnect_timeout`（额外 try/except 兜底，绝不阻塞 WS 处理）。
- 测试：lifecycle 追加 chat 链集成（metadata 注入 + AccessToken 新签发断言 + last_output/CodingSession 落库泄漏扫描）、MCP 链覆盖（`dispatch_execution(initiating_user=user)` → 桥接 Conversation.created_by==user + kind=task token 存在）、终态吊销双路径（HTTP handler + WS handler 直调，幂等）、user 不可解析降级；`test_remote_tool_dispatch.py` 机制换代（mint 注入测试替换 ContextVar 套件，T-11-02 收窄为读取类 spy）；`test_trigger_dispatcher.py` 移除 `user_pat` kwarg。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - 安全] chat 链 last_output.dispatch 落库副本剔除 token 明文**
- **Found during:** Task 2
- **Issue:** 计划第 3 步只要求"确认泄漏面（现状即不含，保持）"，但现状 `sub_session.last_output["dispatch"]` 会把**整份 `metadata`** 落库（规划期坐标为 Phase 100 基线，metadata 键当时不含 token）；本 plan 把 token 写进 `env_metadata` 后，不剔除即直接违反 SC "SubAgentSession.last_output 无 friday_pat_ 明文"。
- **Fix:** 落库副本 dict comprehension 剔除 `env_FRIDAY_TASK_USER_TOKEN`；注释说明 runner 断连重建 dispatch（`_rebuild_dispatch_task`）时该键缺失 → 容器降级不挂知识工具（fail-soft）。
- **Files modified:** server/chat/coding_session_service.py
- **Commit:** 48f98efd

**2. [Rule 1 - 测试 bug] lifecycle 测试遍历字段用 attname 而非 name**
- **Found during:** Task 1
- **Issue:** 泄漏扫描遍历 `concrete_fields` 用 `field.name` 会触发 FK 关系对象同步查询（async 上下文 SynchronousOnlyOperation）。
- **Fix:** 改用 `field.attname`（FK 取 `*_id` 本地列，语义等价且异步安全）。
- **Commit:** a8e9a49c

### 计划疑点核实（plan-checker 非阻塞警告）

**`amark_cancelled` 调用方核实**：计划声称"`SubAgentSession.amark_timeout/amark_cancelled` 无调用方"——执行期 `rg` 核实为**部分不准确**：
- `amark_cancelled` 有一个调用方：`repositories/summary_service.py::cancel_repo_summary`（用户终止"建立知识"任务）。但该路径仅作用于 `task_type=REPO_SUMMARY` 的 session，此类任务**从不铸造 task token**（mint 只挂在三条 coding 派发链），故无需挂吊销钩子。
- `amark_timeout` 确无调用方；`summary_service` 另有两处直接 `aupdate(status=TIMEOUT)` 的收敛路径，同样 REPO_SUMMARY 专属。
- 结论：五点吊销（callbacks×2 + WS×2 + 断连收敛）已覆盖 coding 任务全部真实终态写入点；REPO_SUMMARY 取消/超时路径无 token 可吊，假想残余由 `expires_at` 自过期兜底。callbacks 处注释已按实情修正表述。

## Known Stubs

无。

## Threat Flags

无新增计划外安全面（threat_model 内 T-103-01/02/04 缓解全部落地：明文只内存、短 TTL + 五点幂等吊销、minted/revoked 结构化事件 + created_by 落库归因）。

## 验证结果

- `pytest tests/test_task_token_lifecycle.py tests/test_remote_tool_dispatch.py tests/test_access_tokens.py tests/test_trigger_dispatcher.py tests/test_coding_wave.py tests/subagent tests/chat -q` → **155 passed**。
- 死通道守门：`! rg -q "user_pat_plaintext|_resolve_user_pat|set_request_pat|get_request_pat" server/` → 全仓零命中（含测试）。
- 明文泄漏面：`rg "friday_pat_" server/`（排除 tests/access_tokens）命中均为存量脱敏规则（redaction.py/logging.py 正则）、settings 认证顺序注释与本 plan 泄漏防线注释——无新增明文拼接点。
- `makemigrations --check --dry-run` → No changes detected。
- 本次改动文件 `ruff check` 全净。

## Self-Check: PASSED

- server/access_tokens/services.py — FOUND
- server/access_tokens/migrations/0003_accesstoken_kind_session_id.py — FOUND
- server/tests/test_task_token_lifecycle.py — FOUND（>80 行）
- server/access_tokens/context.py — DELETED（预期）
- commits a8e9a49c / 48f98efd / af02b945 — FOUND
