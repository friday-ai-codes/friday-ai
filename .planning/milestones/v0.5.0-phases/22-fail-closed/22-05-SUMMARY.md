---
phase: 22-fail-closed
plan: 05
subsystem: api
tags: [exclusion, fail-closed, security, rest-api, adrf, vue, tanstack-query, i18n]

# Dependency graph
requires:
  - phase: 22-fail-closed
    provides: "22-01 RepoExclusionRule 模型、services.exclusion 单一匹配器、invalidate_matcher_cache、serialize_rules_for_repo、BUILTIN_GLOBAL_DEFAULTS"
provides:
  - "排除规则 REST API：GET/POST /api/repositories/<id>/exclusions/、DELETE .../<rule_id>/"
  - "RepoExclusionRuleSerializer（regex fail-loud 校验 + pattern 非空/长度上限）"
  - "services.exclusion.get_global_default_specs() 全局默认单一读取入口"
  - "前端类型化 API client web/src/api/exclusions.ts + ExclusionRulesPanel 编辑面板"
  - "仓库详情页排除规则配置入口（EXCL-01 用户可配置闭环）"
affects: [22-fail-closed Wave 2 enforcement 面（规则变更即时生效）, 23-purge 对账 UI]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "全局默认单一读取入口 get_global_default_specs：视图与匹配器合并共用，不在视图层硬编码默认"
    - "构造期 fail-loud（serializer re.compile 非法 regex → 400 不写库）/ 运行期 fail-closed（matcher）"
    - "写操作后 invalidate_matcher_cache(repository_id) 使各读取面即时读新规则（T-22-18）"
    - "关闭全局默认 = source=global+enabled=False override 行；删除该行 = 再次启用"
    - "前端 TanStack Query 查询 + mutation + invalidate 刷新；DRF 字段级错误提取展示"

key-files:
  created:
    - server/tests/repositories/test_exclusion_api.py
    - web/src/api/exclusions.ts
    - web/src/components/repository/ExclusionRulesPanel.vue
  modified:
    - server/repositories/serializers.py
    - server/repositories/views.py
    - server/repositories/urls.py
    - server/services/exclusion.py
    - web/src/pages/repositories/[id]/index.vue
    - web/src/locales/zh-CN.json
    - web/src/components.d.ts

key-decisions:
  - "采用独立 APIView（RepositoryExclusionRulesView / RepositoryExclusionRuleDetailView）而非 ViewSet @action，与既有 <uuid:repository_id>/... 显式路由 + adrf APIView idiom 一致（RepositorySpacesView/IndexedFilesListView）"
  - "GET 返回 global_defaults 每条带 enabled + override_id，前端据此渲染只读默认的关闭开关与再次启用"
  - "exclusion.py 抽出 get_global_default_specs() 复用于视图与 _resolve_effective_specs，避免默认/JSON 解析双份真相"
  - "rule_type 用原生 <select>（最小面板，规避 reka-ui Select 组件多子组件接线复杂度与类型风险）"

requirements-completed: [EXCL-01]

# Metrics
duration: 8min
completed: 2026-06-14
---

# Phase 22 Plan 05: 排除规则 REST API + 最小前端编辑入口 Summary

**为排除配置提供 REST API（CRUD + regex fail-loud 校验 + 缓存失效）与仓库详情页最小编辑面板：列出全局默认（只读可关闭）+ per-repo 增删，保存即时生效，措辞如实（仅承诺 Friday 不可见，不承诺 git 物理删除），完成 EXCL-01「用户可配置」闭环。**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-06-14T09:16:32Z
- **Completed:** 2026-06-14T09:24:07Z
- **Tasks:** 2 自动任务（+ 1 人工 checkpoint，自动模式下延后至 UAT）
- **Files:** 3 created + 7 modified

## Accomplishments

- **排除规则 REST API（Task 1, TDD）**
  - `RepoExclusionRuleSerializer`：`rule_type=regex` 时 `re.compile` 校验，非法 → 400 ValidationError（fail-loud，不写库，对齐 D-02 / T-22-17）；pattern 非空 + 长度上限（≤500，防 ReDoS 超长 pattern）。
  - `RepositoryExclusionRulesView`：`GET` 返回 `{global_defaults:[{pattern, rule_type, source, enabled, override_id}], rules:[per-repo]}`，global_defaults 来自 `services.exclusion.get_global_default_specs()`（builtin ∪ 全局设置，**不在视图硬编码**）；`POST` 新增 per-repo 规则 / 关闭全局默认 override，成功后 `invalidate_matcher_cache`（T-22-18）。
  - `RepositoryExclusionRuleDetailView`：`DELETE` per-repo 规则，越仓删除 → 404（T-22-19），写后失效缓存。
  - 路由：`<id>/exclusions/`、`<id>/exclusions/<rule_id>/`。
  - `services/exclusion.py` 抽出 `get_global_default_specs()` 作全局默认单一读取入口，`_resolve_effective_specs` 复用之（合并逻辑不漂移）。
  - 12 个 API 测试全绿；既有 18 个匹配器测试不回归（重构等价）。

- **前端排除规则编辑入口（Task 2）**
  - `web/src/api/exclusions.ts`：`ExclusionRule` / `GlobalDefaultRule` 类型 + `list/create/remove`。
  - `ExclusionRulesPanel.vue`：全局默认只读列表 + 关闭/启用 `Switch`（override）、per-repo 规则列表 + 删除、新增表单（dir/glob/regex + pattern）；TanStack Query 查询 + mutation + invalidate；非法 regex 后端 400 经字段级错误提取展示具体原因。
  - 安全措辞如实（DOMAIN §9.1）：`securityNote` 仅承诺「对 Friday 的索引/检索/agent/容器不可见」，明确「不会从 Git 历史物理删除」。
  - 面板挂载到仓库详情页（`[id]/index.vue`）新增「排除规则」分区 + 锚点导航；i18n key 加入 `zh-CN.json` 的 `exclusion` 命名空间（默认中文）。

## Task Commits

1. **Task 1: 排除规则 REST API（TDD）** - `36112b4f6` (test, RED) → `22dd76679` (feat, GREEN)
2. **Task 2: 前端排除规则编辑面板** - `b8c2adc38` (feat)

_TDD: Task 1 走 RED（test 提交，端点缺失 → 404 失败）→ GREEN（feat 提交，30 passed）。无 refactor 提交（GREEN 一次到位）。_

## Files Created/Modified

- `server/tests/repositories/test_exclusion_api.py` - 12 个 API 测试（CRUD / fail-loud / override / 缓存失效 / 权限）
- `server/repositories/serializers.py` - 新增 `RepoExclusionRuleSerializer`
- `server/repositories/views.py` - 新增两个 APIView + 导入 `get_global_default_specs`/`invalidate_matcher_cache`
- `server/repositories/urls.py` - 注册 exclusions 路由（顺带 ruff 组织 import）
- `server/services/exclusion.py` - 抽出 `get_global_default_specs()`，`_resolve_effective_specs` 复用
- `web/src/api/exclusions.ts` - 类型化 API client
- `web/src/components/repository/ExclusionRulesPanel.vue` - 编辑面板
- `web/src/pages/repositories/[id]/index.vue` - 挂载面板 + 导航分区
- `web/src/locales/zh-CN.json` - `exclusion` i18n 文案（含安全边界如实措辞）
- `web/src/components.d.ts` - unplugin 自动注册新组件（生成文件）

## Decisions Made

- **独立 APIView vs ViewSet @action**：选独立 APIView，与既有 `<uuid:repository_id>/...` 显式路由 + adrf APIView idiom 一致（参考 `RepositorySpacesView` / `IndexedFilesListView`），权限沿用 `IsAuthenticated`。
- **GET 契约**：global_defaults 每条带 `enabled` + `override_id`，让前端只读默认也能渲染「关闭/再次启用」开关；rules 仅列 per-repo 实际规则（user/ai_suggested），global override 标记不混入。
- **单一真相**：`get_global_default_specs()` 同时服务视图展示与匹配器合并，杜绝默认硬编码/JSON 解析双份。
- **前端 rule_type 控件**：用原生 `<select>` 而非 reka-ui Select（最小面板、降低类型/接线风险）。
- **DRF 字段错误展示**：`ApiError.detail` 对字段级错误（`{pattern:[...]}`）为兜底默认值，面板内增 `fieldError()` 从 `ApiError.body` 提取首个字段错误，使非法 regex 原因可见。

## Deviations from Plan

None - plan executed exactly as written.

（说明：`server/repositories/urls.py` 的一处既有 import 排序由 ruff 在格式化时一并组织，属落地清理，非行为偏离。）

## Checkpoint (Task 3 — human-verify)

本 plan 标记 `autonomous:false`（含 Task 3 人工验收 checkpoint）。本次在 **AUTONOMOUS 模式**下执行：Task 3（浏览器层人工核对面板展示/增删/regex 报错/安全措辞）**自动批准并延后至 UAT**，不阻塞完成。建议后续手动验收：
1. 仓库详情页 `/repositories/<id>` 打开「排除规则」面板，确认内置全局默认（.env / *.pem / node_modules/ 等）展示。
2. 新增 glob `*.secret` → 列表出现；新增非法 regex `[` → 明确报错且未入库。
3. 关闭一条全局默认（override）→ 状态变化；删除自建规则 → 移除。
4. 阅读说明文案：确认仅承诺「Friday 不可见」，无「git 历史物理删除」措辞。

## Known Stubs

None - 面板数据均由 `/api/repositories/<id>/exclusions/` 实接，无占位/空数据桩。

## Verification

- `server/.venv/bin/python -m pytest tests/repositories/test_exclusion_api.py tests/services/test_exclusion_matcher.py` → **30 passed**。
- `cd web && pnpm vue-tsc --noEmit` → 无类型错误。
- `cd web && pnpm vitest run src/components/repository` → **69 passed**（无回归）。
- `ruff format` + `ruff check` changed 后端文件 → clean。
- ESLint `--fix` changed 前端文件 → clean。

## Next Phase Readiness

- EXCL-01 用户可配置闭环达成：API + 前端入口齐备，规则变更经缓存失效即时对 Wave 2 各 enforcement 面（索引扫描、MCP、RAG、编码容器）生效。
- Phase 23（存量派生数据清理/对账）可复用 `RepoExclusionRule` 可枚举规则与本 API 契约。

## Self-Check: PASSED

---
*Phase: 22-fail-closed*
*Completed: 2026-06-14*
