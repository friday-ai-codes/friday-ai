---
phase: 71-observability-foundation
plan: "71-03"
subsystem: observability / logging
tags: [logging, runtime-config, sampling, structlog, LOG-05, LOG-06]
requires:
  - "71-02: SystemLogEntry + log_sink 队列/计数 + enqueue_system_log processor"
  - "Wave 1: common/log_context.py (LogSource) + common/logging.py 脱敏链"
provides:
  - "SettingKeys.LOG_* 运行时日志配置键（级别/分组件/堆栈阈值/采样/保留）"
  - "settings_service.get_json_setting / get_float_setting"
  - "common.logging.apply_log_level() 热更新过滤级别 + _resolve_structlog_level 读 DB 优先"
  - "common.logging.bound_logger() + annotate_category_component processor（category/component 地基）"
  - "log_sink 采样过滤（caller 全记 / sampling 首 N + 比例）+ sampled_out 计数"
  - "LOGGING-SPEC §10 事件目录（Phase 71 已知事件）"
affects:
  - "全仓 structlog 事件：每条兜底 category=sampling；component 经 bound_logger / contextvars 显式带"
  - "system/signals.py：SystemSetting 写 LOG_* → 即时重设过滤级别"
tech-stack:
  added: []
  patterns:
    - "复用 SystemSetting + settings_service(60s 缓存) + signals(写时失效) 承载运行时配置"
    - "structlog.configure(wrapper_class=...) 运行时重设过滤级别（幂等，保留 processor 链）"
    - "观测代码 best-effort：读配置/调级别失败静默回退，绝不反噬业务"
key-files:
  created:
    - server/tests/test_log_runtime_config.py
  modified:
    - server/system/models.py
    - server/system/settings_service.py
    - server/system/signals.py
    - server/common/logging.py
    - server/system/log_sink.py
    - .planning/observability/LOGGING-SPEC.md
decisions:
  - "组件自动推断从 logger name 首段映射 §5 清单；但默认 PrintLogger factory 不把 logger name 放进 event_dict，故 processor 自动推断仅在 logger 名已在 dict 时生效——component 的保证路径是 bound_logger() 显式 bind / contextvars，存量渐进迁移（符合 plan「不强制重写全仓」）"
  - "stack_threshold / retention_days / retention_max_rows 本 plan 仅落配置键 + 可读（经缓存失效热更新），enforcement 在 71-04 消费（与 plan 一致）"
  - "采样丢弃用独立 sampled_out 计数，与队列满 dropped 语义区分（背压 vs 主动抽样）"
metrics:
  duration: ~25min
  completed: 2026-06-24
---

# Phase 71 Plan 03: 运行时日志配置 + 分类/采样（LOG-05/06）Summary

给日志中心装上"运行时旋钮"（级别/采样/保留经 `SystemSetting` 热改、级别即时生效无需重启）与"分类骨架"（caller 全记 / sampling 采样 + component 地基 helper），并补全 `LOGGING-SPEC.md` 事件目录。

## Tasks

### PASS — Task 1: SettingKeys.LOG_* + settings_service 读取 + signals 热更新级别（LOG-06）
- `system/models.py`：`SettingKeys` 新增 7 个 `LOG_*` 点分命名常量（`log.level` / `log.component_levels` / `log.stack_threshold` / `log.sampling_initial` / `log.sampling_rate` / `log.retention_days` / `log.retention_max_rows`）。纯字符串常量，**无 migration**（`makemigrations --check` = No changes detected）。
- `system/settings_service.py`：新增 `get_float_setting`（沿用 `_get_raw` 缓存 + try/except 回默认）、`get_json_setting`（json.loads，失败/非 dict 回默认）；顺手移除 pre-existing 未用 import `SettingKeys`（满足 plan ruff-clean 验收，见 Deviations）。
- `common/logging.py`：`_resolve_structlog_level()` 改为 **DB（`LOG_LEVEL`）优先 → env 回退 → INFO**（局部 import + try/except 防加载期 app/DB 未就绪）；新增 `apply_log_level()` 即时 `logging.setLevel()` + `structlog.configure(wrapper_class=make_filtering_bound_logger(level))`（best-effort、幂等、保留 processor 链）；`configure_structlog()` 末尾调用 `apply_log_level()`。
- `system/signals.py`：`_LOG_KEYS` + `_apply_log_config_if_needed()`，在 `on_system_setting_saved` / `on_system_setting_deleted` 命中 `LOG_*` 即调 `apply_log_level()`（缓存先失效，apply 读到新值），best-effort try/except，不动既有 cache 失效 + qdrant reset。

### PASS — Task 2: category/component helper + 采样过滤 + LOGGING-SPEC 事件目录补全（LOG-05）
- `common/logging.py`：新增 `_KNOWN_COMPONENTS`（§5 组件清单）+ `_infer_component()`（logger name 首段映射，推不出留空）+ `bound_logger(name, *, component=None)`（薄包 `get_logger` 并 `bind(component=...)`，地基 helper）+ processor `annotate_category_component`（无 `component` 推断、无 `category` 默认 `sampling`），挂在 `redact_credentials` 之后、`buffer_log`/`enqueue_system_log` 之前；`enqueue_system_log` 改用注入的 `component` 并把 `component` 加入 `_reserved`。
- `system/log_sink.py`：`_should_record()` 采样判定（`caller` 全记不采样；`sampling`/缺省按 `(component,event)` 首 `LOG_SAMPLING_INITIAL` 全记 + 之后 `random()<LOG_SAMPLING_RATE`；读配置失败保守全记）；新增 `_sampled_out` 计数（与队列满 `dropped` 区分）+ `_sample_counts`；`snapshot_counters` 增 `sampled_out`；`_reset_for_tests` 清采样状态。配置经 `settings_service`（60s 缓存，不每条打库）。
- `.planning/observability/LOGGING-SPEC.md`：新增「§10 事件目录（Phase 71 已知事件）」，登记 CTX / 落库 / webhook / 观测 API / 后台任务事件的 category+component + `SettingKeys.LOG_*` 配置表，注明 72+ 增量补全。

## Test Results

`tests/test_log_runtime_config.py`（13 用例，全绿）：
- 热更新：`log.level=DEBUG` 经 signal → debug 进 stdout；改 WARNING → debug 不出（无需重启，capfd 断言）。
- `_resolve_structlog_level` DB 优先 / env 回退；`get_json_setting` 解析 + 非法/非 dict 回默认；`get_float_setting` 解析 + 回默认；缓存写时失效。
- `annotate_category_component` 默认 sampling + 推断 component / 保留显式 caller+component / 未知 logger 留空；`bound_logger` 推断 + 显式覆盖。
- 采样：`INITIAL=2`+`RATE=0` → 同 (component,event) 前 2 入队、第 3 条 `sampled_out`（`dropped==0`）；`caller` 全记不采样；落库行带 category/component。

回归（无破坏，54 全绿）：`test_credential_leak_protection.py`（脱敏链路含落库对称守护）、`test_system_log_sink.py`（71-02 队列/计数）、`test_log_context_propagation.py`（CTX 贯穿）、`test_system_logs.py`。

验收命令：
- `uv run pytest tests/test_log_runtime_config.py -x -q` → 13 passed
- `uv run pytest tests/test_credential_leak_protection.py tests/test_system_log_sink.py tests/test_log_context_propagation.py tests/test_system_logs.py -q` → 54 passed
- `uv run ruff check common/logging.py system/settings_service.py system/signals.py system/log_sink.py system/models.py tests/test_log_runtime_config.py` → All checks passed
- `uv run python manage.py makemigrations --check --dry-run` → No changes detected

## Files Changed
- `server/system/models.py` — `SettingKeys.LOG_*` 7 常量
- `server/system/settings_service.py` — `get_json_setting` / `get_float_setting`（+ 移除未用 import）
- `server/system/signals.py` — `LOG_*` 写时即时重设过滤级别
- `server/common/logging.py` — DB 优先级别解析 + `apply_log_level` + `bound_logger` + `annotate_category_component` + enqueue component 修正
- `server/system/log_sink.py` — 采样过滤 + `sampled_out` 计数
- `.planning/observability/LOGGING-SPEC.md` — §10 事件目录
- `server/tests/test_log_runtime_config.py` — 新增（13 用例）

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 移除 settings_service.py pre-existing 未用 import `SettingKeys`**
- **Found during:** Task 1（ruff check）
- **Issue:** `from .models import SettingKeys, SystemSetting` 中 `SettingKeys` 在原文件即未使用（pre-existing F401）；plan `<verification>` 要求 `ruff check ... settings_service.py` 干净。
- **Fix:** 改为 `from .models import SystemSetting`。
- **Files modified:** server/system/settings_service.py
- **Commit:** （未提交，per 执行指令"Do NOT git commit"）

### 设计取舍（非缺陷，记录以便后续）

**component 自动推断的现实边界**：默认 `PrintLogger` logger factory **不把 logger name 放进 event_dict**（实测 `add_logger_name` 因 `PrintLogger` 无 `.name` 而失败）。因此 `annotate_category_component` 的"从 logger name 推 component"仅在 event_dict 已含 `logger`/`logger_name` 时生效（已单测覆盖）。**component 的保证交付路径是 `bound_logger()` 显式 bind / contextvars**（如 workflow/scheduler 经 `bind_task_context` 带 component）；存量 `structlog.get_logger(__name__)` 调用在迁移到 `bound_logger` 前 component 可能为空——符合 plan「不强制重写全仓事件、地基 helper + 存量渐进迁移」。`category` 则对所有事件兜底为 `sampling`（无此限制）。

**stack_threshold / retention 仅落配置**：`log.stack_threshold` / `log.retention_days` / `log.retention_max_rows` 本 plan 落配置键 + 经缓存失效可热改读取，enforcement（堆栈条件渲染 / 保留清理）按 plan 在 71-04 消费。

## Known Stubs
None —— 所有新增能力均有数据源与测试覆盖；retention/stack_threshold 配置键为 71-04 预留消费（plan 明确），非悬空 stub。

## Threat Flags
None —— 未引入新网络入口/认证路径/schema 变更；`annotate_category_component` 仅加 category/component 元字段，不引入用户输入原文，脱敏链路顺序（`redact_credentials` 在 renderer 前）不变。

## Self-Check: PASSED
- FOUND: server/tests/test_log_runtime_config.py
- FOUND: server/system/models.py (SettingKeys.LOG_*)
- FOUND: server/common/logging.py (apply_log_level / bound_logger / annotate_category_component)
- FOUND: server/system/log_sink.py (_should_record / sampled_out)
- FOUND: .planning/observability/LOGGING-SPEC.md (§10 事件目录)
- 13 + 54 tests passed; ruff clean; no migration needed.
