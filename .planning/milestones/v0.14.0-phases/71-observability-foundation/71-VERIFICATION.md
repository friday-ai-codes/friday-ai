---
phase: 71-observability-foundation
verified: 2026-06-24T13:06:00Z
status: passed
score: 8/8 must-haves verified
overrides_applied: 0
gap_closure: 2026-06-24T13:33:00Z
gap_closure_note: "两处 gap 已闭合（代码 + 测试，全部 green）：LOG-06 分组件级别/堆栈阈值经新增 filter_by_component_level / gate_stack_by_threshold processor 运行时生效（signal 失效缓存即时热更新）；LOG-07 WebhookTriggerView 派发前 await record_inbound_webhook(kind=workflow) 脱敏入库。详见文末「Gap closure（2026-06-24）」。"
gaps:
  - truth: "运行时改日志级别(全局/分组件)/堆栈阈值/采样初始·后续/保留天数·大小，实时生效无需重启"
    status: partial
    reason: "全局级别 + 采样初始/后续 + 保留天数/大小 三项确实运行时生效（signal 热更新 + 配置在判定/清理处实时读取，已被测试覆盖）；但「分组件级别」(LOG_COMPONENT_LEVELS) 与「堆栈阈值」(LOG_STACK_THRESHOLD) 仅落 SettingKeys 并触发 signal，apply_log_level() 只重设单一全局过滤级别，从不读取/应用这两项 → 改了不生效。"
    artifacts:
      - path: "server/common/logging.py"
        issue: "apply_log_level()/configure_structlog() 全程未引用 LOG_COMPONENT_LEVELS / LOG_STACK_THRESHOLD；无按 component 分级过滤的 processor，StackInfoRenderer 无阈值门控。"
      - path: "server/system/signals.py"
        issue: "_LOG_KEYS 含这两键并在写时调 apply_log_level()，但 apply_log_level 只解析全局 LOG_LEVEL，对这两键是空操作。"
    missing:
      - "在日志链路实现按 component 的级别过滤（读 LOG_COMPONENT_LEVELS，命中 component 时按其级别 drop/keep），使分组件级别运行时生效"
      - "实现堆栈阈值门控（按 LOG_STACK_THRESHOLD 决定是否走 StackInfoRenderer/format_exc_info），使堆栈阈值运行时生效"
  - truth: "飞书/通用 webhook/Git push/容器回调原始 payload 脱敏后入库可查看（统一 webhook 原始留痕）"
    status: partial
    reason: "feishu(3 入口)/git_push/container_callback 三类均已在入口 await record_inbound_webhook 脱敏入库，MCP 调用归因 + AI 对话会话下钻 API 齐备且可下钻原始数据。但「通用 workflow webhook」是真实可达的公开端点 POST /api/workflows/webhook/<path>/（WebhookTriggerView, AllowAny），未调用 record_inbound_webhook，kind=workflow 留痕从不写入 → 四类 webhook 缺一类。71-05-SUMMARY 称『本代码库无独立通用 workflow webhook 入口』与事实不符。"
    artifacts:
      - path: "server/workflows/api/views.py"
        issue: "WebhookTriggerView.post（约 1558 行起）接收通用 webhook，仅 logger.info(webhook_trigger_start) + 派发 TriggerDispatcher，未写 InboundWebhookEvent（无脱敏原始留痕）。"
      - path: "server/system/webhook_recorder.py"
        issue: "已定义 KIND_WORKFLOW='workflow' 枚举，但全仓无任何调用点使用它。"
    missing:
      - "在 WebhookTriggerView.post 验签/派发前 await record_inbound_webhook(kind=KIND_WORKFLOW, raw_body=..., headers=..., source_ip=..., correlation={webhook_path:...})，使通用 workflow webhook 原始 payload 脱敏入库可查看"
---

# Phase 71: 可观测性地基（用户上下文贯穿 + 系统日志治理）Verification Report

**Phase Goal:** 建立可观测性地基——让每次调用都能绑定到触发用户（无则 system），并把系统日志从"每进程 800 条内存环形缓冲"升级为"队列化落库、可搜索、可按条件清理、可运行时配置"的日志中心，统一 webhook 原始留痕与调用下钻。
**Verified:** 2026-06-24T13:06:00Z
**Status:** passed（gap closure 2026-06-24T13:33:00Z；初次 verify 为 gaps_found，两处 gap 已闭合）
**Re-verification:** No — initial verification + gap closure

## Goal Achievement

### Observable Truths（对应 ROADMAP Phase 71 八条 Success Criteria）

| # | Truth | Status | Evidence |
| - | ----- | ------ | -------- |
| 1 | 任意请求日志带 user_id(登录/system)+request_id+source；飞书/webhook/durable 后台任务显示来源，跨线程/durable worker 正确继承 | ✓ VERIFIED | `common/middleware.py` 入口绑 request_id/source/trace_id+user_id=system 占位、`finally` clear；`common/mixins.py` DRF `initial` 认证后 `rebind_user`；`common/log_context.py` `bind_task_context` 干净 Context 显式 bind；后台传播接线于 `durable/{tasks,tasks_impl,service}.py`、`services/background_runner.py`、`workflows/engine/scheduler.py`、`feishu/views.py`、`runapscheduler.py`；中间件挂 `settings.py` MIDDLEWARE 最外层。`test_log_context_propagation.py` 绿。 |
| 2 | SystemLogEntry 落库，最新时间倒序，按组件/级别/用户/来源/关键词/时间段筛选 + 全文搜索 | ✓ VERIFIED | `system/log_views.py::SystemLogQueryView` order_by("-ts") + `_apply_filters`（component/level/user_id/source/ts__gte·lte/message__icontains）；路由 `/api/system/logs/`。migration 0009 建表。`test_system_log_api.py` 绿（倒序/筛选/分页）。 |
| 3 | 队列(5000)+批量落库；四计数(队列/写入/丢弃/失败)暴露；满→丢弃+计数，失败→计数，不反噬业务 | ✓ VERIFIED | `system/log_sink.py` `deque(maxlen=5000)`、手动满判定 `_dropped++`、daemon `friday-log-sink` `bulk_create`、`_write_failed += len`、`snapshot_counters()`（queued/max/enqueued/written/dropped/write_failed/sampled_out）经 logs 查询 `counters` 暴露；enqueue/worker 全 `except: pass`。`test_system_log_sink.py` 绿。 |
| 4 | 每条日志带 category(caller/sampling)+component；LOGGING-SPEC 事件目录 | ✓ VERIFIED | `common/logging.py::annotate_category_component` processor（无 category→sampling，component 推断）挂 redact 后、enqueue 前；`LOGGING-SPEC.md §2/§10` caller/sampling 定义 + Phase 71 事件目录。`test_log_runtime_config.py` 分类用例绿。 |
| 5 | 运行时改级别(全局/分组件)/堆栈阈值/采样初始·后续/保留天数·大小，实时生效无需重启 | ⚠️ PARTIAL | 全局级别热更新 ✓（`apply_log_level` + signal，`test_log_level_hot_reload_via_signal` 绿）；采样初始/后续 ✓（`_should_record` 实时读）；保留天数/大小 ✓（`_retention_config` 实时读）。**但分组件级别 + 堆栈阈值仅落键/触发 signal，apply_log_level 从不读取/应用 → 改了不生效**（见 gaps）。 |
| 6 | 飞书/通用 webhook/Git push/容器回调原始 payload 脱敏入库可查看；MCP 见触发用户；AI 对话下钻会话全部请求+原始 | ⚠️ PARTIAL | feishu(3)/git_push/container_callback 已 `await record_inbound_webhook` 脱敏入库（`redact_for_ledger`/`redact_secrets_in_text`+截断），`/api/system/webhooks/` 可查看；MCP `/calls/drilldown/` 解析触发用户（绝不回 token）；AI `/conversations/<uuid>/drilldown/` 取全部 Message+关联留痕。`test_inbound_webhook_event.py`/`test_log_drilldown_api.py` 绿。**但通用 workflow webhook 端点未留痕**（见 gaps）。 |
| 7 | 日志按条件批量清理 + 保留策略定时自动清理 | ✓ VERIFIED | `system/log_views.py::SystemLogClearView`（同款筛选删除 + confirm_all 防误清 + 审计）；`system/log_retention.py::purge_system_logs/purge_webhook_events`（按天数+行数）；`runapscheduler.py` 注册 daily `purge_observability_logs` job。`test_system_log_api.py` purge 用例绿。 |
| 8 | 凭证脱敏不破（redact_credentials/redact_secrets_in_text/redact_for_ledger，CI 守护通过） | ✓ VERIFIED | 落库 processor 链 redact 在 enqueue/buffer 之前；webhook/下钻入库前 `redact_for_ledger`+`redact_secrets_in_text`+截断，只读直出不重拼明文。`test_credential_leak_protection.py` 绿。 |

**Score:** 6/8 truths verified（2 项 PARTIAL）

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/common/log_context.py` | contextvars bind/clear + LogSource 枚举 + bind_task_context | ✓ VERIFIED | 实质实现，被中间件/mixin/后台链路引用 |
| `server/common/middleware.py` | 请求级入口兜底中间件 | ✓ VERIFIED | 同步/异步双协议；挂 MIDDLEWARE 最外层 |
| `server/common/mixins.py` | DRF 认证后补绑 user | ✓ VERIFIED | `LogContextMixin.initial` rebind_user |
| `server/common/logging.py` | annotate + enqueue processor + apply_log_level | ⚠️ ORPHANED(部分) | processor 链就绪；但 component_levels/stack_threshold 未被消费 |
| `server/system/log_sink.py` | 队列 5000 + 批量 worker + 四计数 + 采样 | ✓ VERIFIED | 完整实现 |
| `server/system/log_views.py` | 查询/清理 API | ✓ VERIFIED | 路由 `/api/system/logs/`、`/logs/clear/` |
| `server/system/log_retention.py` | 保留清理 | ✓ VERIFIED | apscheduler daily job 注册 |
| `server/system/webhook_recorder.py` | 脱敏收口 | ⚠️ ORPHANED(部分) | KIND_WORKFLOW 定义但无调用点 |
| `server/system/webhook_views.py` | webhook 留痕查看 API | ✓ VERIFIED | 路由 `/api/system/webhooks/` |
| `server/system/drilldown_views.py` | MCP/对话下钻 API | ✓ VERIFIED | 路由 `/calls/drilldown/`、`/conversations/<uuid>/drilldown/` |
| `server/system/models.py` | SystemLogEntry/InboundWebhookEvent/SettingKeys.LOG_* | ✓ VERIFIED | migration 0009 建两表 |
| `server/system/migrations/0009_*` | 建表迁移 | ✓ VERIFIED | `0009_inboundwebhookevent_systemlogentry.py` |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| MIDDLEWARE | RequestLogContextMiddleware | settings.py 注册 | WIRED | 最外层（whitenoise 之后、session 之前） |
| structlog 链 | enqueue_system_log | configure_structlog processors | WIRED | 挂 redact 之后（脱敏入队） |
| SystemSetting 写 | apply_log_level | signals._LOG_KEYS post_save | WIRED(全局)/NOT_WIRED(分组件+堆栈) | 全局级别生效；component_levels/stack_threshold 触发但 apply 不消费 |
| 通用 workflow webhook | InboundWebhookEvent | WebhookTriggerView → record_inbound_webhook | NOT_WIRED | 端点存在，未调用 recorder |
| feishu/git/container webhook | InboundWebhookEvent | record_inbound_webhook | WIRED | 三入口 await 入库 |
| 后台任务入口 | bind_task_context | durable/bg/workflow/feishu/apscheduler | WIRED | 五处接线 + initiated_by_user_id 传播 |
| urls_system | log/webhook/drilldown views | friday/urls.py include system.urls_system | WIRED | `/api/system/` 挂载 |

### Behavioral Spot-Checks / Probe Execution

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Phase 71 全量验证测试套件 | `uv run pytest tests/test_log_context_propagation.py tests/test_system_log_sink.py tests/test_log_runtime_config.py tests/test_system_log_api.py tests/test_inbound_webhook_event.py tests/test_log_drilldown_api.py tests/test_credential_leak_protection.py tests/test_system_logs.py -q` | **104 passed** (11.85s, exit 0) | ✓ PASS |

> 说明：测试套件全绿，但绿测并未覆盖两处 PARTIAL（分组件级别/堆栈阈值的"实际生效"未被断言；通用 workflow webhook 留痕无对应用例）——测试只验证了已实现的子集，正是 goal-backward 校验补出缺口之处。

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| CTX-01 | 71-01 | 请求级上下文中间件 | ✓ SATISFIED | 真理 1 |
| CTX-02 | 71-01 | 后台任务用户传播 | ✓ SATISFIED | 真理 1（五处接线） |
| LOG-01 | 71-02/04 | SystemLogEntry 倒序+筛选+全文 | ✓ SATISFIED | 真理 2 |
| LOG-02 | 71-02 | 队列 5000+批量+丢弃/失败计数 | ✓ SATISFIED | 真理 3 |
| LOG-03 | 71-04 | 日志绑定触发用户可筛选 | ✓ SATISFIED | 真理 1+2 |
| LOG-04 | 71-05 | 调用下钻(MCP/对话) | ✓ SATISFIED | 真理 6（下钻部分） |
| LOG-05 | 71-03 | category/component + 事件目录 | ✓ SATISFIED | 真理 4 |
| LOG-06 | 71-03 | 运行时日志配置实时生效 | ⚠️ PARTIAL | 真理 5（分组件/堆栈阈值未生效） |
| LOG-07 | 71-05 | webhook 原始统一落库 | ⚠️ PARTIAL | 真理 6（通用 workflow webhook 未留痕） |
| LOG-08 | 71-04 | 按条件清理 + 保留定时清理 | ✓ SATISFIED | 真理 7 |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| `server/repositories/index_views.py` | 42/54-57/1389 | pre-existing ruff（模块导入/F841） | ℹ️ Info | 71-05-SUMMARY 已记 deferred，非本 phase 引入、在编辑区外 |

> 无 TBD/FIXME/XXX 未引用债务标记；观测代码 `except: pass` 为规范要求的 best-effort，非 stub。

### Human Verification Required

无。两处缺口均为可静态观测的代码级缺失（端点存在未接线 / 配置键定义未被消费），不需真机或外部系统确认。

### Gaps Summary

地基 8 条成功标准中 6 条完整达成、代码证据扎实且 104 条测试全绿；2 条为**部分达成**，须补全：

1. **运行时配置（标准 5 / LOG-06）**：全局级别、采样初始·后续、保留天数·大小三项确实运行时生效并有测试；但 `LOG_COMPONENT_LEVELS`（分组件级别）与 `LOG_STACK_THRESHOLD`（堆栈阈值）仅定义为 SettingKeys 并在写时触发 signal，`apply_log_level()` 只重设单一全局过滤级别、从不读取或应用这两项——改了**不生效**。需在日志链路实现按 component 的分级过滤与按阈值的堆栈门控。

2. **统一 webhook 原始留痕（标准 6 / LOG-07）**：feishu/git_push/container_callback 三类已脱敏入库且可下钻，MCP/AI 对话下钻齐备；但「通用 workflow webhook」是真实可达的公开端点 `POST /api/workflows/webhook/<path>/`（`WebhookTriggerView`），未调用 `record_inbound_webhook`，`kind=workflow` 留痕从不写入。`webhook_recorder.py` 已预留 `KIND_WORKFLOW` 但无调用点。71-05-SUMMARY 称"本代码库无独立通用 workflow webhook 入口"与事实不符。需在该端点验签/派发前补 `record_inbound_webhook(kind=KIND_WORKFLOW, ...)`。

两处缺口均不在 Phase 72–75 的后续 Success Criteria 中被覆盖（Phase 75 UI-04 仅提供运行时配置**表单**，不解决后端分组件/堆栈阈值的实际应用），故不作 deferred。

---

## Gap closure（2026-06-24T13:33:00Z）

两处 gap 已在代码层闭合并补测，目标命令全绿（`test_log_runtime_config` / `test_inbound_webhook_event` / `test_credential_leak_protection` / `test_system_log_sink` 共 58 passed），`ruff check` 干净，`makemigrations --check` 无变更（无模型改动）。

### Gap 1（LOG-06）：分组件级别 + 堆栈阈值运行时生效

- `server/common/logging.py` 新增两个 best-effort processor 并挂入链路：
  - `filter_by_component_level`（挂在 `annotate_category_component` 之后、`buffer_log`/`enqueue_system_log` 之前）：读 `SettingKeys.LOG_COMPONENT_LEVELS`（`settings_service.get_json_setting`，60s 缓存 + signal 失效），命中事件 `component` 且事件级别低于该 component 配置级别时 `raise structlog.DropEvent` 丢弃；未配置/推不出 component/解析失败一律放行。尽早丢弃以省后续缓冲/落库开销，高频路径廉价（未配置时命中缓存空值直接回退，不做 json 解析）。
  - `gate_stack_by_threshold`（挂在 `StackInfoRenderer`/`format_exc_info` 之前）：读 `SettingKeys.LOG_STACK_THRESHOLD`，事件级别低于阈值时剥除 `stack_info`/`exc_info`/`exception`/`stack` 键，使其后渲染器不再输出堆栈/traceback；未配置阈值则不门控。
- 运行时生效路径不变：`signals.py` 的 `_apply_log_config_if_needed` 已在写时失效缓存，processor 每条事件读已失效的缓存即得新值，无需重启/reconfigure。
- 测试（`server/tests/test_log_runtime_config.py`）：`test_component_level_filter_via_signal`（`LOG_COMPONENT_LEVELS={"noisy_component":"ERROR"}` → noisy 的 INFO 被丢、其它 component 的 INFO 放行、noisy 的 ERROR 仍放行）；`test_stack_threshold_gate_via_signal`（`LOG_STACK_THRESHOLD=ERROR` → WARNING 事件剥除异常、ERROR 事件保留 traceback），均经 signal 即时生效。

### Gap 2（LOG-07）：通用 workflow webhook 原始留痕

- `server/workflows/api/views.py` `WebhookTriggerView.post` 在读取 body 后、派发 `TriggerDispatcher` 前，`await record_inbound_webhook(kind=KIND_WORKFLOW, raw_body=<decoded body>, headers=dict(request.headers), source_ip=client_ip(request), verified=False, correlation={"webhook_path": path, "trace_id": trace_id})`，脱敏入库、best-effort、不影响 webhook 主流程（镜像 feishu/git_push 范式）。
- 测试（`server/tests/test_inbound_webhook_event.py::TestWorkflowWebhookRecording`）：POST `/api/webhook/<path>/`（无匹配 WebhookConfig 仍 200）→ 落 1 行 `InboundWebhookEvent(kind="workflow")`，`correlation.webhook_path` 正确，明文凭证不入库、出现 `***REDACTED***`。

### 附带修复（Rule 1：测试隔离 bug，由本次改动时序暴露）

- `server/system/log_sink.py`：`_ensure_worker` 原仅以 `PYTEST_CURRENT_TEST`（仅单用例执行期存在，导入/采集期为空）判定是否禁用 daemon 落库线程；该线程在 app 初始化首批日志事件里被误启动后常驻整轮测试，用后台连接 autocommit 落库绕过用例事务回滚、污染相邻用例（baseline 仅因 SQLite 锁竞争 `written=0` 侥幸通过，本次改动时序使后台写入落地从而暴露泄漏）。改为新增 `_is_under_pytest()` 同时检测 `sys.modules` 是否含 `pytest`，覆盖整轮会话，落实该函数 docstring 既定的"测试不起后台线程"契约。生产环境（无 pytest）行为不变。

---

_Verified: 2026-06-24T13:06:00Z_
_Verifier: Claude (gsd-verifier)_
_Gap closure: 2026-06-24T13:33:00Z (gsd-executor)_
