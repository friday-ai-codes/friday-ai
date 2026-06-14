---
phase: 24-sensitive-ai-detect
plan: 03
subsystem: api
tags: [django, adrf, rest-api, sensitive-detection, exclusion, ai-suggested, idempotent]

# Dependency graph
requires:
  - phase: 24-sensitive-ai-detect
    provides: "24-01 SensitiveFileSuggestion 模型（repo FK + path + severity/detector/status + 脱敏 reason）"
  - phase: 22-fail-closed
    provides: "RepoExclusionRule.Source.AI_SUGGESTED、services.exclusion.invalidate_matcher_cache、RepoExclusionRuleSerializer 规则创建路径"
provides:
  - "敏感建议 REST API：GET /api/repositories/<id>/sensitive-suggestions/（severity 排序，?status 过滤）"
  - "POST /api/repositories/<id>/sensitive-suggestions/<sid>/action/（accept/dismiss）"
  - "SensitiveFileSuggestionSerializer（全字段只读，reason 脱敏）"
  - "accept 接通 Phase 22 RepoExclusionRule(source=ai_suggested) 创建 + 缓存失效（幂等，NEVER silent-delete）"
affects: [24-04 前端建议面板]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "建议为只读视图（serializer 全 read_only），状态仅经专用 accept/dismiss action 变更（不允许直接 PATCH）"
    - "accept 复用 Phase 22 规则创建路径：aget_or_create(source=ai_suggested) 幂等 + invalidate_matcher_cache"
    - "severity 排序权重映射 _SENSITIVE_SEVERITY_ORDER（real_secret > likely_sensitive > config_review），Python 侧稳定排序 + detected_at desc"

key-files:
  created:
    - server/tests/repositories/test_sensitive_suggestions_api.py
  modified:
    - server/repositories/serializers.py
    - server/repositories/views.py
    - server/repositories/urls.py

key-decisions:
  - "独立 APIView（RepositorySensitiveSuggestionsView / RepositorySensitiveSuggestionActionView）+ 显式 <uuid:repository_id>/... 路由，与 Phase 22 exclusions 面 idiom 一致"
  - "accept 用 aget_or_create 而非 IntegrityError 捕获实现幂等（唯一约束含 source，二次 accept 命中既有行不重复创建、不报 500，T-24-12）"
  - "severity 排序走 Python 侧映射（建议规模有限），避免 DB Case/When 注解复杂度；同级 detected_at desc"
  - "accept response 附 cleanup_available: true 仅作前端引导提示，绝不在 accept 路径自动派发任何 reconcile/cleanup（NEVER silent-delete，删除仍由 Phase 23 用户显式触发）"

requirements-completed: [EXCL-03]

# Metrics
duration: ~12min
completed: 2026-06-15
---

# Phase 24 Plan 03: 敏感文件建议 REST API（list / accept / dismiss）Summary

**为 EXCL-03「建议 + 确认」面提供 REST 工作流：列出某仓 AI 敏感文件建议（severity 排序、real_secret 优先、`?status` 过滤），接受（→ 幂等创建 `RepoExclusionRule(source=ai_suggested, rule_type=glob)` + 标 accepted + `invalidate_matcher_cache`），忽略（标 dismissed）。全程绝不静默删除已索引/派生数据——删除仍由既有 Phase 23 reconcile/cleanup 用户显式触发。**

## Performance

- **Duration:** ~12 min
- **Completed:** 2026-06-15
- **Tasks:** 2（serializer；views + urls + guard 测试）
- **Files:** 1 created + 3 modified

## Accomplishments

- **`SensitiveFileSuggestionSerializer`（Task 1）**：`ModelSerializer` over `SensitiveFileSuggestion`，暴露 `id/path/severity/detector/reason/status/detected_at/updated_at` 且**全部 read_only**（建议由检测器产出，API 只读 + 仅经专用 action 改 status，T-24-09/10）；reason 仍为脱敏文本（T-24-11）。
- **list 端点 `RepositorySensitiveSuggestionsView.get`（Task 2）**：以 `repository_id` 限定查询（越仓不可见，T-24-09），默认仅 `pending`，支持 `?status=pending|accepted|dismissed|all`；按 severity 优先级（real_secret > likely_sensitive > config_review）+ `detected_at desc` 排序；返回 `{"suggestions": [...]}`。
- **action 端点 `RepositorySensitiveSuggestionActionView.post`（Task 2）**：
  - `accept` → `RepoExclusionRule.objects.aget_or_create(source=ai_suggested, rule_type=glob, pattern=path, defaults={enabled:True})` 幂等创建（T-24-12）+ 建议标 `accepted` + `invalidate_matcher_cache`（T-22-18）；返回 `{suggestion, rule, cleanup_available}`。
  - `dismiss` → 仅置 `status=dismissed`，不建规则、不删数据。
  - 越仓 / 不存在 `suggestion_id` → 404；非法 action → 400。
  - **绝不**在 accept 路径触发删除/清理（守护测试断言无 `CleanupRun` 创建、无 `run_cleanup` 调用）。
- **路由**：`<uuid:repository_id>/sensitive-suggestions/`（list）+ `.../{suggestion_id}/action/`（action）。
- **守护测试**：`test_sensitive_suggestions_api.py` 12 例全绿——severity 排序、`?status=all`、reason 字段集脱敏、accept 建规则/标 accepted、accept 无删除副作用、accept 幂等、dismiss 无规则、越仓 404、非法 action 400、缺仓 404、未认证 401/403。

## Task Commits

1. **Task 1: `SensitiveFileSuggestionSerializer`** — `e89ab30e0` (feat)
2. **Task 2: list/accept/dismiss 视图 + 路由 + guard 测试** — `7aace8cd4` (feat)

## Files Created/Modified

- `server/repositories/serializers.py` — 新增 `SensitiveFileSuggestionSerializer`（全字段 read_only）+ import `SensitiveFileSuggestion`
- `server/repositories/views.py` — 新增两个 APIView + `_SENSITIVE_SEVERITY_ORDER` 排序映射 + import `SensitiveFileSuggestion` / `SensitiveFileSuggestionSerializer`
- `server/repositories/urls.py` — 注册 `sensitive-suggestions` list / action 两路由
- `server/tests/repositories/test_sensitive_suggestions_api.py` — 12 例 API guard 测试

## Decisions Made

见 frontmatter key-decisions。核心：独立 APIView + 显式路由（对齐 Phase 22）；`aget_or_create` 实现 accept 幂等（唯一约束含 source）；severity Python 侧排序映射；accept 仅引导不自动清理（NEVER silent-delete）。

## Deviations from Plan

None - plan executed exactly as written.

（PLAN action 提到 accept 幂等可用 `aget_or_create` 或捕获 `IntegrityError`，本实现选 `aget_or_create`，属 PLAN 给定选项内，非偏离。）

## Threat Surface Scan

新增两个认证端点，威胁缓解均落地且有测试覆盖：
- **T-24-09（越权/越仓）**：`IsAuthenticated` + 以 `repository_id` 限定查询；越仓 `suggestion_id` → 404（不泄漏存在性）。测试 `test_cross_repo_suggestion_404`。
- **T-24-10（篡改/静默删除）**：accept 只建 `ai_suggested` 规则 + 标 accepted，绝不删数据；测试 `test_accept_never_deletes_data_no_cleanup_run` 断言无 `CleanupRun` 创建、`run_cleanup` 未调用。
- **T-24-11（信息泄漏）**：serializer 仅暴露既定字段，reason 脱敏；测试 `test_list_reason_is_redacted_no_secret_body` 断言字段集封闭。
- **T-24-12（重复 accept DoS）**：`aget_or_create` 幂等；测试 `test_accept_is_idempotent` 断言二次 accept 不 500 且规则不重复。
无计划外新增威胁面（复用 DRF + 既有 serializer/exclusion 面，无新增依赖）。

## Known Stubs

None - 所有端点数据均由 DB 实接，无占位/空数据桩。

## Verification

- `cd server && uv run pytest tests/repositories/test_sensitive_suggestions_api.py -q` → **12 passed**。
- `cd server && uv run pytest tests/repositories/test_exclusion_api.py -q` → **14 passed**（无回归）。
- `grep -n "ai_suggested\|AI_SUGGESTED" repositories/views.py` 命中 accept 路径（`Source.AI_SUGGESTED`）。
- `grep -n "invalidate_matcher_cache" repositories/views.py` 在 accept 建规则后调用。
- `uv run ruff check repositories/{views,serializers,urls}.py tests/repositories/test_sensitive_suggestions_api.py` → 0 错。

## Next Phase Readiness

- list/accept/dismiss API 契约稳定，24-04 前端建议面板可直接消费：`{suggestions:[...]}` + action 返回 `{suggestion, rule, cleanup_available}`。
- accept 已接通 Phase 22 `RepoExclusionRule(source=ai_suggested)`，规则即时经缓存失效对 Wave 2 各 enforcement 面生效。

## Self-Check: PASSED

---
*Phase: 24-sensitive-ai-detect*
*Completed: 2026-06-15*
