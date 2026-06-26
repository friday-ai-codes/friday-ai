# Phase 89 PLAN-03 — 容器 5min 挂起 / resume（SUMMARY）

**Status:** ✅ Complete | **Wave:** 2 | **Depends:** 89-01

## 交付

单仓编码容器遇阻等待用户 → 5min 无回复挂起/暂存容器；用户卡片回复 → 经 Phase 86
`SessionStore` + `build_resume_dispatch_env` resume 续跑到终态；session miss → 应用态重灌新
session。复用 86 SessionStore→Redis + v0.8 callback resume + dispatcher.cancel + apscheduler
（已在栈），**绝不重造 session 持久化**。全段 fail-soft + INV-6 写收口 + 脱敏 + 归因。

## 承载模型确认（A1）

**`CodingSession`** 承载单仓容器 SDK session（`sdk_session_id` / `sdk_transcript`，
`SessionStore` / `build_resume_dispatch_env` / `_persist_sdk_session` 均以其为对象）。挂起态
`SUSPENDED` + `parked_at` 落 `CodingSession`——**非** `RepoCodingTask`（v0.8 多仓 wave 执行
实体，不持单仓容器 SDK session）。read_first 已在代码确认。

## Files

### Added
- `server/chat/container_suspend_service.py` — `ContainerSuspendService`（INV-6 写收口）：
  - `arm_timeout` — apscheduler `DateTrigger` 一次性 job（`suspend-{cs_id}` 幂等 replace_existing）
  - `cancel_timeout` — 用户回复取消未触发 job（不存在 no-op）
  - `suspend` — CAS `RUNNING/AWAITING→SUSPENDED` + `dispatcher.cancel` + `parked_at` + 事件，fail-soft
  - `resume` — CAS `SUSPENDED/AWAITING→RUNNING` → `build_resume_dispatch_env` 命中 re-dispatch
    （`container_resumed`）/ 空走应用态重灌（`container_resume_reloaded`），fail-soft
  - `schedule_container_resume` / `_do_resume_async` — 飞书回复网关（`_run_in_thread` +
    `bind_task_context`；仅 `SUSPENDED` 才 resume，绝不重起活容器）
  - `_run_suspend_job` — apscheduler job 入口（顶层函数 + bind_task_context 重绑发起用户）
- `server/chat/migrations/0029_codingsession_parked_at_alter_codingsession_status.py` — 纯
  `AddField(parked_at)` + `AlterField(status choices)`，无 RunPython
- `server/tests/chat/test_container_suspend.py` — 15 用例（suspend/resume/miss/竞态/fail-soft/
  arm-cancel seam/网关）

### Modified
- `server/chat/models.py` — `CodingSession.Status.SUSPENDED` + `parked_at` 字段
- `server/subagent/api/callbacks.py` — `_handle_question` 发卡后接线 `arm_timeout`（仅 coding 容器，
  best-effort try/except 不反噬回调）
- `server/feishu/callbacks/container_callback.py` — `handle_container_answer` 接线
  `schedule_container_resume`（cancel_timeout + 仅挂起态 resume，best-effort）

## Observability
- 结构化事件：`container_suspended` / `container_resumed` / `container_resume_reloaded` /
  `container_suspend_*` / `container_resume_*`（`category=caller`, `component=chat`, `duration_ms`）；
  scheduler 起停 `category=sampling`。
- 归因：`initiated_by_user_id`（发卡取 `_resolve_initiated_user`，回复取 `callback.user_open_id`，
  后台 `_run_in_thread` / `_run_suspend_job` re-bind）；无触发用户 `system`。
- 脱敏：`user_reply` 经 `redact_secrets_in_text` 后并进 prompt 受控块；日志仅 `has_user_reply` 布尔。
- 未触碰 `call_source.py`（89-01 baseline=30）。

## 竞态 / fail-soft
- CAS 状态机：挂起 `RUNNING/AWAITING→SUSPENDED`、resume `SUSPENDED/AWAITING→RUNNING`，已非该态
  幂等短路（计时到点与回复并发安全）。
- 停容器 / 计时 / resume 任一失败吞掉记 warning，绝不反噬容器回调 / 飞书回调主流程（不回灌 5xx）。
- session miss / cwd 漂移 → `build_resume_dispatch_env` 返回 `{}` → 应用态重灌新 session
  （绝不静默错配他容器 transcript）。

## Tests
- `cd server && uv run pytest tests/chat/test_container_suspend.py -q` → **15 passed**
- `cd server && uv run pytest tests/chat tests/subagent -q` → **107 passed**（无回归）
- `makemigrations --check --dry-run` 干净；ruff + mypy（新文件）通过

## Deferred → `89-UAT.md`
真机延迟挂起触发 / 真实容器 resume 续到终态 / 冷启动重灌 / apscheduler 多副本去重 + web 进程内
scheduler 生命周期 —— 需 runner + Docker 真实容器，记 `89-UAT.md`（[ASSUMED] container-live）。
