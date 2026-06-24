---
phase: 71-observability-foundation
plan: "71-01"
subsystem: observability / user-context-propagation
tags: [structlog, contextvars, middleware, drf, durable, background, workflow, scheduler, feishu]
requires: [common.logging.configure_structlog (merge_contextvars 已在链首位)]
provides:
  - common.log_context (LogSource 枚举 + bind/rebind/clear/bind_task_context/resolve_user_id)
  - common.middleware.RequestLogContextMiddleware (请求入口绑定 + 结束清理)
  - common.mixins.LogContextMixin (DRF 认证后补绑 user_id / 声明 source)
  - durable/background_runner/workflow/scheduler/feishu 五条后台链路的发起用户传播
affects: [server/friday/settings.py MIDDLEWARE, durable defer 契约, run_in_background 契约]
tech-stack:
  added: []   # 仅用标准库 contextvars/uuid + 既有 structlog/asgiref
  patterns: [structlog.contextvars bind/clear, Django 同步+异步双协议中间件, contextmanager worker 入口 bind]
key-files:
  created:
    - server/common/log_context.py
    - server/common/middleware.py
    - server/common/mixins.py
    - server/tests/test_log_context_propagation.py
  modified:
    - server/friday/settings.py
    - server/durable/service.py
    - server/durable/tasks_impl.py
    - server/durable/tasks.py        # 计划外（见 Deviations）：procrastinate 包壳转发新形参
    - server/services/background_runner.py
    - server/workflows/engine/scheduler.py
    - server/feishu/views.py
    - server/agents/management/commands/runapscheduler.py
decisions:
  - "中间件外层只绑 request_id/source/trace_id + user_id=system 占位；真实 user_id 由 DRF mixin 认证后 rebind（解 DRF user 时序坑）"
  - "source 经 LogSource.normalize 受控枚举兜底，非法值回退 system（防基数污染）"
  - "后台任务跨线程/进程不自动传播 contextvars，入队携带 initiated_by_user_id，worker 入口 bind_task_context 重新绑定（无则 system）"
  - "所有新增形参均有默认值（None / 不传），既有调用方零回归"
metrics:
  duration: ~35min
  completed: 2026-06-24
---

# Phase 71 Plan 01: 用户上下文贯穿地基（CTX-01/02）Summary

为每个请求入口与每个后台任务 worker 把 `user_id`（无则 `system`）、`request_id`、`source`、`trace_id` 绑定到 `structlog.contextvars`，使全仓 `structlog.get_logger(__name__)` 事件自动可回答"谁触发的"——纯标准库实现，零新增依赖，全链路向后兼容。

## 交付内容

### Task 1 — `common/log_context.py`（上下文绑定单一收口）
- `LogSource(str, Enum)`：受控来源枚举（rest/mcp/chat_sse/compat_*/ws/webhook_*/container_callback/durable/background/workflow/scheduler/system）+ `normalize()` 非法值兜底 `system`。
- `bind_request_context` / `rebind_user` / `bind_source` / `clear_request_context`：请求级 bind/补绑/清理。`rebind_user(None)` 不覆盖既有占位。
- `@contextmanager bind_task_context(*, user_id, source, trace_id=None, **extra)`：后台 worker 入口 bind、退出 clear。
- `resolve_user_id(request)`：DRF 认证后取 `request.user.id`，未认证/异常回退 `system`，绝不读写明文凭证。

### Task 2 — 请求级中间件 + DRF mixin + settings
- `RequestLogContextMiddleware`：Django 同步+异步双协议中间件（`iscoroutinefunction`/`markcoroutinefunction` 分派），入口绑 `request_id`(X-Request-ID)/`trace_id`(X-Trace-ID)/`source=rest`/`user_id=system`，`finally` clear。**不**访问 `request.user`（避免过早触发认证）。
- `LogContextMixin`：重写 `initial`，`super().initial` 后 `rebind_user(resolve_user_id(request))` + 可选 `log_source` 声明来源。
- `settings.MIDDLEWARE`：`common.middleware.RequestLogContextMiddleware` 注册在 whitenoise 之后（靠最外层）。

### Task 3 — 后台任务用户传播（CTX-02）
- **durable**：`DurableTaskService.defer(..., initiated_by_user_id=None)` 非空写入 `payload["initiated_by_user_id"]`（不覆盖已传值）；`tasks_impl.run_index/run_graph/run_page_index/run_crawl_ingest/run_repo_summary` 各加形参并用 `bind_task_context(source="durable")` 包裹任务体。
- **background_runner**：`run_in_background(..., initiated_by_user_id=None)`，非空时 worker 干净 context 内 `bind_task_context(source="background")`；不传不绑定（零回归）。
- **workflow**：`_run_in_thread(coro, *, triggered_by_id=None, trace_id=None)` 在新线程/loop 入口 `bind_task_context(source="workflow", component="workflow")`，三处调用点传 `execution.triggered_by_id`。
- **apscheduler**：新增 `_with_scheduler_log_context` 装饰器（system + source/component=scheduler），应用到全部 `*_job` wrapper；仅保护 bind 构造、func 恰好执行一次、异常正常上抛。
- **feishu webhook**：`FeishuWebhookView.post` 入口 `bind_request_context(source=webhook_feishu, user_id=system)`；`_schedule_delivery_upsert`/`_schedule_comment_append` 的 `run_in_background` 传 `initiated_by_user_id="system"`。

## Deviations from Plan

### 计划外修改（Rule 3 — 使新形参在生产后端真正生效）

**1. [Rule 3 - 阻塞修复] `server/durable/tasks.py` procrastinate 包壳转发 `initiated_by_user_id`**
- **Found during:** Task 3
- **Issue:** `durable_index`/`durable_graph`/`durable_repo_summary` 三个 procrastinate `@app.task` 包壳用**显式 keyword-only 形参**并显式转发给 `run_*`，而非 `**payload` 展开。若仅改 `tasks_impl` 而不动包壳，procrastinate（生产 Postgres）后端执行时 `durable_index(**payload)` 会因 `initiated_by_user_id` 报 `TypeError: unexpected keyword argument`，且即便不报错也不会把该键转发给任务体——CTX-02 在生产 index/graph/repo_summary 路径失效。（in-process/SQLite 路径走 `durable.handlers` 的 `**payload` adapter，本身已兼容。）
- **Fix:** 三个包壳各加 `initiated_by_user_id: str | None = None` 形参并转发给对应 `run_*`。`durable_page_index`/`durable_crawl_ingest` 走 `**payload`，无需改动。
- **Files modified:** `server/durable/tasks.py`
- **Zero-regression:** 形参默认 None，既有 payload 不含该键时行为不变。

**2. [清理] `server/durable/tasks_impl.run_repo_summary` 移除未使用的 `from asgiref.sync import sync_to_async`**
- 原函数体从未使用该 import（dead import）；改写时一并移除，保持 ruff 干净。无行为变化。

> 其余文件均按计划 `files_modified` 实施，未触碰范围外文件。

## 测试结果

| 命令 | 结果 |
|------|------|
| `uv run pytest tests/test_log_context_propagation.py -x -q` | **17 passed** |
| `uv run pytest tests/test_credential_leak_protection.py -x -q` | **22 passed**（脱敏守护不破） |
| `uv run pytest tests/durable -q` | **76 passed, 13 deselected**（无回归） |
| `uv run pytest -k "background_runner or run_in_thread or feishu_webhook or scheduler or middleware"` | **45 passed**（无回归） |
| `uv run ruff check <12 changed files>` | **All checks passed!** |

守护测试覆盖：`LogSource.normalize` 兜底；请求 bind/rebind/clear；mixin 已认证/未认证两路；中间件请求结束清理；durable defer 写 payload + run_index bind（传值/None→system）；background_runner bind（传值/不传零回归）；workflow `_run_in_thread` bind source=workflow；scheduler 装饰器 system；feishu webhook source=webhook_feishu。

## Known Stubs

无。本 plan 为地基绑定，无 stub/占位数据流向 UI。

## Threat Flags

无新增信任边界外的网络入口/认证路径/落库链路。本 plan 仅绑定非敏感字段（`user_id`/`request_id`/`source`/`trace_id`），明文凭证绝不进 contextvars；`request_id`/`trace_id` 取自客户端 header 仅作关联键、`user_id` 由服务端 DRF 认证后权威写入（T-71-01-01）；`source` 受控枚举兜底（T-71-01-03）；中间件/`bind_task_context` 退出清理防泄漏（T-71-01-04）。

## Follow-ups（非本 plan 范围）

- 各业务 `defer` 调用方（手动索引/图谱/repo_summary 入口）逐步补传 `request.user.id` 作 `initiated_by_user_id`——本 plan 已把形参+payload 传播+worker bind 全部就位，调用方补传即生效（难定位的留默认 system，不阻塞）。
- MCP/compat/chat 视图按需挂 `LogContextMixin` 并设 `log_source` 声明来源（基础设施已就绪）。
- 日志落库（71-02/04）、webhook 原始留痕与下钻（71-05）将消费本 plan 绑定的字段。

## Self-Check: PASSED
- 创建文件均存在：`common/log_context.py`、`common/middleware.py`、`common/mixins.py`、`tests/test_log_context_propagation.py`。
- 修改文件均落地并通过 ruff + pytest。
- 提交由 orchestrator 负责（本执行未 git commit）。
