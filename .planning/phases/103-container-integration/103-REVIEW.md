---
phase: 103-container-integration
reviewed: 2026-07-22T06:55:00Z
depth: standard
files_reviewed: 24
files_reviewed_list:
  - server/access_tokens/migrations/0003_accesstoken_kind_session_id.py
  - server/access_tokens/models.py
  - server/access_tokens/services.py
  - server/access_tokens/context.py (deleted)
  - server/chat/coding_session_service.py
  - server/common/log_context.py
  - server/interactions/entry.py
  - server/mcp_tools/execution_service.py
  - server/mcp_tools/views.py
  - server/mcp_tools/work_item_execution_service.py
  - server/runners/consumers.py
  - server/services/project_context_packer.py
  - server/subagent/api/callbacks.py
  - server/workflows/api/views.py
  - server/workflows/engine/scheduler.py
  - server/workflows/nodes/ai/coding.py
  - server/workflows/nodes/base.py
  - server/workflows/triggers/dispatcher.py
  - task/Dockerfile
  - task/core/config.py
  - task/core/executor.py
  - task/core/knowledge_tools.py
  - task/core/runner.py
  - task/scripts/sync_skills.py
findings:
  critical: 0
  warning: 3
  info: 6
  total: 9
status: resolved
resolution:
  fixed: 7
  accepted: 2
  fixed_at: 2026-07-22T07:40:00Z
---

# Phase 103: Code Review Report

**Reviewed:** 2026-07-22T06:55:00Z（UTC）
**Depth:** standard
**Files Reviewed:** 24 个源文件（10 个提交的并集，测试文件按可靠性抽查，`.planning/` 排除）
**Status:** findings（0 Critical / 3 Warning / 6 Info）

## Summary

对 Phase 103 十个已合并提交做了对抗式审查，重点核查 token 生命周期、容器知识 MCP handler、allowed_tools 合并收口、skills 注入与上下文对齐。

**总体判断：核心安全承诺（PAT-02）成立。** 逐点核实：

- **明文不落盘**：`mint_task_token` 明文只经返回值进内存 env；DB 仅存 `hash_token(明文)`；`task_token_minted` / `task_token_revoked` / `coding_dispatch_task_token` 等事件均无明文；chat 链 `last_output.dispatch` 落库副本剔除 `env_FRIDAY_TASK_USER_TOKEN`（`coding_session_service.py:479-481`）；workflow 链不持久化 dispatch metadata；`_rebuild_dispatch_task` 重派后缺 token 键 → 容器降级不挂知识工具（fail-soft，符合注释声明）。
- **不从 DB 反取**：ContextVar 死通道（`access_tokens/context.py` + views/dispatcher/scheduler/base 四处管道）删除干净，无残留引用。
- **吊销幂等 + 五点覆盖**：`arevoke_task_tokens` 用 `filter(revoked_at__isnull=True).aupdate(...)` 单语句更新，幂等且保留首次时间戳；callbacks HTTP 双终态 + consumers WS 双终态 + 断连收敛五点齐备，全部 best-effort 不反噬主流程。
- **过期余量算术正确**：chat 链 mint 3600s 与 `DispatchTask(timeout=3600)` 一致；workflow 链 mint 与 dispatch 同用 `config.get("timeout_seconds", 1800)`；余量恒 +10 分钟，token 生存期 ≥ 任务 timeout。
- **认证类零改动正确**：`AccessTokenAuthentication` 不读 `kind`，前缀闸门 + sha256 查表 + `is_valid`（过期/吊销）对 kind=task 天然生效；迁移为纯增列（default + nullable），存量行安全。
- **知识 MCP handler**：配额 check-then-increment 之间无 await，单事件循环下原子，并发安全；7 个 handler 共享闭包计数器符合"per-task 共享预算"设计；timeout 60s、401/403 graceful、非 200 不回显响应体、非 JSON 兜底，全路径 return-not-raise；端点校验拒绝非 http(s)/无 host，且失败日志只记 scheme。
- **skills 注入**：同名跳过逐目录判断正确；`iterdir` 跳过非目录（README.md 不会被当技能拷入）；hash 一致性测试逐文件 sha256 + 文件集合双断言，当前 `task/assets/skills/` 与 `skills/skills/` 实测 diff 为空；Dockerfile COPY 层带 `--chown` 且位于 entrypoint 层之前，组织合理。
- **上下文对齐**：wave 层按 `str(project.id)` 去重召回一次逐仓复用，branch 在 wave 内恒定，语义达成；全路径 fail-soft 空串。

发现 3 个 Warning（1 个 repo_summary 工具白名单回归、1 个 chat 匿名会话行为漂移、1 个落库脱敏不完整的既有残留）与 6 个 Info，见下。

## Warnings

### WR-01: `_build_tool_mounts` 把全量 builtin 并入 repo_summary 白名单，WebFetch/WebSearch 意外解禁

**File:** `task/core/executor.py:147-155`（合并逻辑）、`task/core/executor.py:539-546`（受影响调用点）
**Issue:** 收口后的规则是"任一 MCP server 挂载（含 extra）即全量并入 `_BUILTIN_CODING_TOOLS`"。repo_summary 模式恒挂 extra 的结构化提交 server，改造前它的 allowed_tools 仅为 `[*_READONLY_ANALYSIS_TOOLS, submit_tool]`（明确注释"不含 WebFetch/WebSearch——prompt 约束禁止网络请求"）；改造后全量 builtin 被并入，`disallowed_tools` 只拦了 `Write/Edit/MultiEdit/NotebookEdit`，**WebFetch/WebSearch 从白名单排除降级为仅 prompt 约束**。这是只读分析容器的网络出口策略回归（commit 声称"全空配置零回归钉"，但零回归测试只钉了"无任何挂载"的场景，未覆盖 extra-only 挂载）。
**Fix:** 二选一：
```python
# 方案 A（最小改动）：repo_summary 调用点补禁网络工具
disallowed_tools=["Write", "Edit", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch"],

# 方案 B（收口更准）：builtin 并入仅在 remote/knowledge 挂载时触发，
# extra-only 挂载沿用调用方自带的白名单
if remote_server is not None or knowledge_server is not None:
    allowed_tools = [*_BUILTIN_CODING_TOOLS]
```
并补一条 extra-only（repo_summary 形态）的白名单守护测试。

### WR-02: `apack_dispatch_context` 的 `user is None → ""` 守门改变 chat 匿名会话行为，与"纯重构零行为变化"声明不符

**File:** `server/services/project_context_packer.py:263-264`（新守门）、`server/chat/coding_session_service.py`（`_resolve_project_context_for_dispatch` 调用点）
**Issue:** 上提前，chat 私有实现把 `user=None`（匿名会话，注释明确"匿名会话可为 None"）直接传入 `pack_project_context`——后者对 None user 是可容忍的（`_is_member` 对 `uid is None` 返回 False，但 `PUBLIC_ORG` 项目非成员放行；`_layer_rag` 内部自兜底异常）。即：**匿名会话 + PUBLIC_ORG 项目此前能召回项目上下文，上提后一律返回空串**。81956173 提交说明声称"纯重构零行为变化"，该边缘不成立；phase 关注项"no chat behavior drift"在此有一处收紧型漂移（fail-closed 方向，泄漏风险为零，但派发上下文缺失会影响该场景的编码质量）。
**Fix:** 若收紧是有意的，修正提交说明预期并在 docstring 记录"匿名会话不召回"；若无意，去掉 `user is None` 短路，让 `pack_project_context` 自身的 visibility 闸门（成员/public_org）继续做权威判定：
```python
if project is None:
    return ""
```

### WR-03: `last_output.dispatch` 落库脱敏只剔任务 token，`env_FRIDAY_TASK_GIT_ACCESS_TOKEN` / `env_FRIDAY_TASK_CLAUDE_API_KEY` 明文仍持久化

**File:** `server/chat/coding_session_service.py:479-481`
**Issue:** 新增的 `persisted_metadata` 只过滤 `env_FRIDAY_TASK_USER_TOKEN` 一个键，而 chat 链 `build_dispatch_metadata` 产出的 metadata 同时含 Git 访问 token（`coding_session_service.py:178`）与 Claude API key（`:162`），二者随 `last_output.dispatch.metadata` 明文进 DB。该持久化行为先于 Phase 103 存在（非本 phase 引入），且 `_rebuild_dispatch_task` 断连重派依赖这些键（一刀切剔除会破坏重派 clone），故不算本次回归；但本 phase 恰好以"泄漏防线"为名改造了这段代码，只堵一类凭证会造成"已脱敏"的错觉。
**Fix:** 至少在 `persisted_metadata` 处的注释显式声明"Git token / API key 因重派依赖仍落库"并登记为已知债务；中期方案是重派时从 `aresolve_git_token` / provider 配置重解析凭证，落库副本统一剔除 `env_*_TOKEN|API_KEY` 类键（可复用 `redact_for_ledger` 的键名单思路）。

## Info

### IN-01: dispatch 失败时已铸 token 不吊销，存活至自然过期

**File:** `server/chat/coding_session_service.py:429-432`、`server/workflows/nodes/ai/coding.py:1918-1921`
**Issue:** mint 在 dispatch 之前；`get_dispatcher().dispatch(...)` 或后续步骤抛异常时无终态回调触发吊销，token 带全量权限存活至 `timeout + 10min` 自过期。窗口有限且明文未离开服务端内存，风险低。
**Fix:** dispatch 异常路径 best-effort 调 `arevoke_task_tokens(session_id)`。

### IN-02: `arevoke_task_tokens` 吞异常后零日志

**File:** `server/access_tokens/services.py:91-92`
**Issue:** `except Exception: return 0` 连 debug 级日志都没有，吊销持续失败（如 DB 抖动）时不可观测，只能靠 TTL 兜底且无人知晓。
**Fix:** except 分支加 `logger.debug("task_token_revoke_failed", session_id=..., error_type=type(e).__name__)`（保持 best-effort 不 raise）。

### IN-03: chat 链 mint 超时 `3600` 与 `DispatchTask(timeout=3600)` 魔数双写

**File:** `server/chat/coding_session_service.py:430` 与 `:468`
**Issue:** 两处硬编码靠注释"对齐下方"维系，改其一漏其一会造成 token 早于任务过期（余量 10 分钟可部分吸收但不保证）。
**Fix:** 提取 `dispatch_timeout = 3600` 局部变量两处共用。

### IN-04: 配额用尽后每次调用都打 warning，存在容器日志刷屏面

**File:** `task/core/knowledge_tools.py:272-278`
**Issue:** agent 在配额用尽后反复调工具时，`knowledge_tool_quota_exhausted` 每次都以 warning 输出（高频循环 INFO/WARNING 刷屏纪律）。
**Fix:** 首次用尽时打一条，后续降为 debug 或直接静默（返回文案本身已足够让 agent 停手）。

### IN-05: `X-Friday-Session-Id` 未限长/未校验即入库

**File:** `server/interactions/entry.py:109-111`
**Issue:** 客户端可控 header 原样写入 `raw_request["task_session_id"]`（JSONField），无长度上限与格式校验；合法值恒 ≤64 字符（`SubAgentSession.session_id` max_length=64），恶意/异常调用方可塞入 KB 级串污染留痕。
**Fix:** `task_session_id = task_session_id[:64]` 截断（或不匹配 `^[\w.-]{1,64}$` 时丢弃）。

### IN-06: kind=task 行无清理策略，且出现在用户 PAT 管理列表

**File:** `server/access_tokens/models.py`、`server/access_tokens/views.py:42-44`
**Issue:** 每次编码派发逐仓铸一行（wave 多仓、高频工作流下增长可观），软吊销永不物理删除，无过期 task token 的保留/清理任务；同时列表 API 不区分 kind，`task:sub-xxx` 行会淹没用户的个人 token 管理页。"API 不区分 kind"是 CONTEXT 锁定决策，此条仅登记运维债务。
**Fix:** 后续 phase 加定期清理（如删除 `kind="task"` 且过期/吊销超 N 天的行），列表 API 可选 `kind` 过滤参数。

---

## Resolution Notes（2026-07-22 code review fixes）

7 项已修复（3 Warning + 4 Info），2 项 Info 登记为接受/递延。每项一个原子提交，
定向测试全绿（task 全量 235 passed / server 定向 76 passed，含新增守护测试）。

### 已修复

- **WR-01**（`81afe45b`）：采纳方案 B——`_build_tool_mounts` 的 builtin 并入仅在
  remote / knowledge（编码链 MCP server）挂载时触发，extra-only 挂载沿用调用方
  自带白名单；同时 repo_summary 调用点 `disallowed_tools` 显式追加
  WebFetch/WebSearch（双保险：即使 knowledge 同挂导致 builtin 并入，disallowed
  优先级更高仍兜底）。新增守护测试 `test_extra_only_mount_keeps_caller_allowlist_no_builtin`。
- **WR-02**（`a3759080`）：收紧属无意漂移，去掉 `apack_dispatch_context` 的
  `user is None` 短路，恢复"匿名会话 + PUBLIC_ORG 召回"的 chat 既有语义——权限
  判定权威回归 `pack_project_context` visibility 闸门（members_only 对匿名依旧
  fail-closed）。workflow 链调用点自带 `dispatch_user is not None` 守门，行为不变。
  新增匿名 PUBLIC_ORG 召回 + 匿名 members_only fail-closed 两条回归测试。
- **WR-03**（`ab5a23f0`）：采纳中期方案——落库副本统一剔除 `CREDENTIAL_ENV_KEYS`
  三键（USER_TOKEN / GIT_ACCESS_TOKEN / CLAUDE_API_KEY），剔除清单记
  `_redacted_env_keys` 标记；`_rebuild_dispatch_task` 断连重派按标记从权威源重解析
  补回 Git token（`aresolve_git_token`）与 API key（provider 配置），重派 clone/SDK
  行为与首派一致；USER_TOKEN 不重铸（重派容器降级不挂知识工具，与既有声明一致）。
  内存 dispatch 保持完整，首派零变化。新增落库泄漏守护 + 重解析成功/失败降级三条测试。
- **IN-01**（`bb50af81`）：chat 链 dispatch 抛异常时 best-effort
  `arevoke_task_tokens(session_id)` 后原样上抛；workflow 链 `task_dispatch_failed`
  分支同样吊销（`dispatch_user is not None` 守门）。新增吊销回归测试。
- **IN-02**（`7d8e2d86`）：吞异常分支加结构化 `task_token_revoke_failed` warning
  （session_id / error_type kv，category=caller / component=access_tokens），仍不 raise。
- **IN-04**（`fba260dc`）：配额用尽 warning 只打首次一条（计数器越界一格作已告警
  哨兵，7 handler 共享闭包全局恰一次），后续静默返回文案。新增只打一条守护测试。
- **IN-05**（`495ff80f`）：`X-Friday-Session-Id` 入库前截断 64 字符（对齐
  `SubAgentSession.session_id` max_length）。新增超长头截断测试。

### 接受 / 递延

- **IN-03**（chat 链 mint 3600 与 DispatchTask timeout 魔数双写）：接受现状。两处
  相邻且有注释互指，余量 10 分钟可吸收漂移；单独提变量收益有限，留待下次触碰该
  函数时顺手收敛。
- **IN-06**（kind=task 行无清理策略 + 出现在 PAT 管理列表）："API 不区分 kind"为
  CONTEXT 锁定决策，登记为运维债务递延后续 phase（定期清理任务 + 列表 kind 过滤参数）。

_Fixed: 2026-07-22T07:40:00Z_
_Fixer: Claude (gsd-code-fixer)_

_Reviewed: 2026-07-22T06:55:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
