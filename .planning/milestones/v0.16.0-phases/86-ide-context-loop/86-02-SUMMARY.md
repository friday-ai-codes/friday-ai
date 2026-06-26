# 86-02 SUMMARY — SessionStore→Redis 跨容器 resume + dispatch 带项目上下文（HOOK-04）

**Status:** ✅ Done | **Wave:** 1 | **Requirements:** HOOK-04

## 交付内容

### Task 1 — SessionStore（Redis 镜像 + DB fallback + cwd 一致校验）
- 新模块 `server/chat/session_store.py`：`class SessionStore`
  - `async mirror(coding_session, cwd=WORKSPACE_CWD)`：把 `sdk_session_id` + `sdk_transcript`(+cwd, saved_at) 写 Redis（Django `CACHES`，key `sdk_session:{id}`，TTL 7 天与「7 天内 resume」一致）。Redis/序列化异常吞掉（best-effort，DB 真相源）。
  - `load(coding_session)`：**Redis read-through → DB fallback**（实例已载字段，无额外查询）；两者皆空 → `None`（调用方走应用态重灌新 session 兜底）。Redis 故障静默降级直读 DB。
  - `assert_cwd_consistent(stored_cwd, dispatch_cwd)`：cwd 漂移 → `False`（放弃 transcript resume）；`stored_cwd` 空（DB fallback/旧数据）→ 放行不回退（保 v0.8 既有 DB resume）。
  - 常量 `WORKSPACE_CWD="/app/workspace"`（容器约定 cwd，dispatch 固定下发 + resume 校验）。
- 接线（复用 v0.8/v0.12，不重造主链）：
  - `chat/sdk_resume.py::build_resume_dispatch_env`：改为经 `SessionStore.load`（Redis→DB）取 transcript + `assert_cwd_consistent` 校验；命中且 cwd 一致才注入 resume env，否则 `{}`。新增 kw-only `dispatch_cwd=WORKSPACE_CWD`，**返回 env 键不变**，原有调用与 `test_sdk_resume.py` 不破。
  - `subagent/api/callbacks.py::_persist_sdk_session`：落库成功后追加 `await SessionStore().mirror(...)`（fail-soft，镜像失败不影响回调）。

### Task 2 — dispatch 携带项目上下文 + workspace cwd 固定
- `chat/coding_session_service.py`：
  - 新增 `_resolve_project_context_for_dispatch(coding_session) -> str`：定位项目（优先 `conversation.bound_project`，否则 `(repository, branch)` 反查 `ProjectBranch`），经 `pack_project_context`（内置 visibility fail-closed + 写 `RetrievalTrace(source=chat_project_context)`，不绕过）召回，`redact_secrets_in_text` 脱敏后返回；无绑定/空召回/异常 → `""`（fail-soft）。
  - 新增 `_lookup_project_by_branch`（sync_to_async 显式绑定反查）+ `_prepend_project_context`。
  - `build_dispatch_metadata`：注入 `env_FRIDAY_TASK_WORKSPACE_CWD=WORKSPACE_CWD`（供 resume cwd 一致校验）。
  - `dispatch_coding_task`：仅 `coding` 任务（非 `coding_commit`）召回非空时注入 `env_FRIDAY_TASK_PROJECT_CONTEXT` + 拼入 prompt 头部；召回空 → 不注入，派发与现状逐字一致。

## Files modified
- `server/chat/session_store.py`（新）
- `server/chat/sdk_resume.py`
- `server/chat/coding_session_service.py`
- `server/subagent/api/callbacks.py`
- `server/tests/chat/test_session_store.py`（新）
- `server/tests/chat/test_coding_dispatch_context.py`（新）

## Tests
- `tests/chat/test_session_store.py`（13）+ `tests/chat/test_coding_dispatch_context.py`（6）+ `tests/test_sdk_resume.py`（5）→ **24 passed**。
- 回归不破：`tests/test_coding_session.py` + `tests/test_runner_recovery.py` + `tests/test_coding_session_service.py` → **61 passed**。
- ruff check 全绿（4 源文件 + 2 测试）。
- 覆盖：mirror→load 命中 Redis、redis-down→DB fallback、mirror 吞异常、cwd 一致/不一致/空放行、build_resume Redis 命中+cwd 一致→非空 / cwd 漂移→{} / DB fallback resume、dispatch bound_project 召回+RetrievalTrace、ProjectBranch 反查、无绑定→""、members_only 非成员 fail-closed、脱敏、workspace cwd 注入。

## Observability
- `sdk_session_mirrored`/`sdk_session_mirror_failed`/`sdk_session_load_cache_degraded`/`resume_cwd_mismatch_skip`/`dispatch_project_context_failed`（category=sampling, component=chat）。
- dispatch 召回经触发用户（`conversation.created_by`，匿名 None）；RetrievalTrace 由 packer 写（含 redact_for_ledger）。全链 best-effort，绝不反噬派发/回调。

## Deferred / Notes
- **真·跨容器 resume = 线上联验**：Redis 镜像 + cwd 校验逻辑已落地并单测覆盖；实际多容器/冷启动命中需运行时（容器侧 transcript 还原 + SDK resume）联验。
- `WORKSPACE_CWD` 为容器约定常量；容器侧实际 cwd 由 `task/` 决定（本计划范围不改 `task/`），dispatch 与镜像统一用约定 cwd 即可保证 `assert_cwd_consistent` 语义；若未来容器改用 tempdir，需把真实 cwd 经回调回传到镜像 cwd 字段。
- **轻微偏离（已记）**：`SessionStore.load` 实现为同步方法（计划描述为 `async def`），因唯一调用方 `build_resume_dispatch_env` 须保持同步签名（`test_sdk_resume.py` 既有契约 + 在 async dispatch 中直接调用）；`load` 仅读 Redis（sync cache）+ 实例已载字段，无 DB 查询，同步安全。`mirror` 仍为 `async`（callbacks await 调用）。
