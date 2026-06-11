# Phase 14 Deferred Items

执行期间发现的范围外问题（scope boundary：不在本 phase 修复，仅登记）。

## 14-04 执行中发现

- **`server/workflows/` 既有 ruff lint 错误（非本 plan 引入）**：
  `engine/scheduler.py` 顶部 import 块 I001（`rest_framework` 排序）、
  `api/analytics.py` F401 ×2、`api/permissions.py` / `api/views.py` /
  `hooks/builtin.py` / `nodes/ai/code_review.py` / `migrations/0025_alert_rules.py` I001、
  `nodes/control/loop.py` F841。在 HEAD~ 基线上已存在（已用 `git show | ruff check --stdin-filename` 验证 scheduler.py），14-04 计划 verification 中
  `ruff check workflows/` 全目录通过需要范围外清理，本 plan 按"只验改动文件"执行。
- **`server/workflows/nodes/ai/plan_generation.py` 既有 ruff format 漂移（非本 plan 引入）**：
  模块级 `Final[str]` 注解与若干 `json.dumps(...)` 折行不符合当前 ruff format 输出；
  本 plan 插入块本身符合 format（`--diff` 输出全部位于未触碰区段）。

## 14-05 执行中发现

- **`server/feishu/bot/service.py` 既有 ruff I001（非本 plan 引入）**：
  顶部 import 块排序不符合当前 ruff 规则；该文件最后一次改动为
  `c3047129 chore: prepare open source release`，本 plan 未触碰。14-05 计划
  verification 中 `ruff check feishu/` 全目录通过需要范围外清理，本 plan
  按"只验改动文件"执行（`feishu/views.py` check/format 全部通过）。
