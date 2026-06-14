---
phase: 24-sensitive-ai-detect
plan: 04
subsystem: web
tags: [vue3, script-setup, tanstack-query, vue-i18n, reka-ui, sensitive-detection, exclusion, ai-suggested]

# Dependency graph
requires:
  - phase: 24-sensitive-ai-detect
    provides: "24-03 敏感建议 REST API：GET sensitive-suggestions/（severity 排序，?status 过滤）+ POST .../{sid}/action/（accept/dismiss → {suggestion, rule?, cleanup_available}）"
  - phase: 23-purge-reconcile
    provides: "ReconcilePanel（对账/清理面板）作为 accept 后显式清理引导目标"
  - phase: 22-fail-closed
    provides: "ExclusionRulesPanel + RepoExclusionRule(source=ai_suggested)；repository-exclusions query key"
provides:
  - "前端敏感建议面板 SensitiveSuggestionsPanel.vue（severity 排序列表 + real_secret 高优先级告警 + accept/dismiss）"
  - "类型化 client sensitiveSuggestionsApi（list/accept/dismiss）"
  - "zh-CN sensitive.* 命名空间（severity/detector 标签 + real_secret 告警 + 不自动删引导文案）"
  - "仓库详情页 #exclusions section 挂载（EXCL-03 用户可见闭环达成）"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "建议面板复用既有 useQuery/useMutation + useConfirmDialog/useToast/useErrorHandler 范式（对齐 ReconcilePanel/ExclusionRulesPanel）"
    - "accept 后 invalidate 自身建议 key + repository-exclusions key，使新建 ai_suggested 规则即时显现于排除规则面板"
    - "守护测试以真实 zh-CN.json 作 i18n messages（zhCN as any），断言真实文案防被改空"

key-files:
  created:
    - web/src/api/sensitiveSuggestions.ts
    - web/src/components/repository/SensitiveSuggestionsPanel.vue
    - web/src/components/repository/__tests__/SensitiveSuggestionsPanel.spec.ts
  modified:
    - web/src/locales/zh-CN.json
    - web/src/pages/repositories/[id]/index.vue

key-decisions:
  - "面板 prop 命名 repoId（依 PLAN 指定），区别于既有面板的 repositoryId；page 挂载用 :repo-id"
  - "real_secret 告警以列表顶部 destructive 横幅 + 行内 bg-destructive/5 双重突出（data-testid=real-secret-alert 供测试稳定定位），确保真实密钥不被普通建议淹没（T-24-15）"
  - "accept 走 useConfirmDialog 二次确认，description 明示「不会自动删除 / 需在清理面板显式执行」（T-24-14）；dismiss 无需确认（无破坏性）"
  - "前端保序渲染后端已排序结果，不在前端重排（severity 权重 + detected_at desc 由后端把控）"

requirements-completed: [EXCL-03]

# Metrics
duration: ~10min
completed: 2026-06-15
---

# Phase 24 Plan 04: 敏感文件 AI 识别前端建议面板 Summary

**兑现 EXCL-03 用户可见闭环：仓库详情页排除区新增「AI 敏感文件建议」面板——按 severity 排序展示建议、real_secret 高优先级告警、接受（幂等建 `ai_suggested` 排除规则）/忽略（dismiss）操作，接受后引导用户用既有「对账与清理」面板做显式删除（绝不静默删）。接通 24-03 REST 契约与 Phase 22/23 既有面板。**

## Performance

- **Duration:** ~10 min
- **Completed:** 2026-06-15
- **Tasks:** 2（API client + zh-CN 文案；面板组件 + 页面挂载 + 守护测试）
- **Files:** 3 created + 2 modified

## Accomplishments

- **`sensitiveSuggestionsApi`（Task 1）**：类型化 client，`list(repoId, status?)` → `GET sensitive-suggestions/?status=`；`accept/dismiss(repoId, id)` → `POST .../{id}/action/ {action}`。类型 `SensitiveSuggestion`（id/path/severity/detector/reason/status/detected_at/updated_at）与 24-03 序列化器逐字段对齐，`SensitiveActionResponse` 含可选 `rule` 与 `cleanup_available`。
- **zh-CN `sensitive.*` 命名空间（Task 1）**：全中文——面板标题/副标题、severity 标签（真实密钥/疑似敏感/建议复核）、detector 标签（启发式/内容扫描/AI 识别）、空态、real_secret 告警标题与说明、接受/忽略按钮、接受确认（明示建规则 + 不自动删 + 引导清理面板）、接受/忽略成功提示、错误文案。
- **`SensitiveSuggestionsPanel.vue`（Task 2）**：`<script setup lang="ts">`，prop `repoId`。`useQuery(['repository-sensitive-suggestions', repoId])` 拉 pending 建议；real_secret 列表顶部 destructive 横幅 + 行内危险底色高优先级突出；每行展示 severity badge（real_secret 危险 / likely_sensitive 警示 / config_review 中性）、detector 标签、脱敏 reason；accept 经 `useConfirmDialog`（明示不自动删/需显式清理）→ `useMutation` → toast + invalidate 建议与 `repository-exclusions` 列表；dismiss → mutation → toast + invalidate；空态/加载/错误齐备。
- **页面挂载（Task 2）**：仓库详情页 `#exclusions` section，于 `ExclusionRulesPanel` 与 `ReconcilePanel` 之间挂载 `<SensitiveSuggestionsPanel :repo-id="repository.id" />`。
- **守护测试（Task 2）**：4 例全绿——(a) real_secret + likely_sensitive 两行 + 告警真实文案断言；(b) 接受触发 `accept(repo-1, id)` 且确认弹窗含「不会自动删除/显式执行」措辞；(c) 忽略触发 `dismiss` + invalidate 后建议消失；(d) 空态渲染且无告警。

## Task Commits

1. **Task 1: API client + zh-CN 文案** — `f7fbf8434` (feat)
2. **Task 2: 面板组件 + 页面挂载 + 守护测试** — `3bd239566` (feat)

## Files Created/Modified

- `web/src/api/sensitiveSuggestions.ts` — 类型化 list/accept/dismiss client + 类型定义（含安全边界注释）
- `web/src/components/repository/SensitiveSuggestionsPanel.vue` — 建议面板组件
- `web/src/components/repository/__tests__/SensitiveSuggestionsPanel.spec.ts` — 4 例守护测试
- `web/src/locales/zh-CN.json` — 新增 `sensitive.*` 命名空间
- `web/src/pages/repositories/[id]/index.vue` — import + `#exclusions` section 挂载面板

## Decisions Made

见 frontmatter key-decisions。核心：prop `repoId`（依 PLAN）；real_secret 双重视觉突出 + 稳定 testid；accept 二次确认明示不自动删/引导清理（T-24-14）；前端保序渲染后端已排序结果。

## Deviations from Plan

None - plan executed exactly as written.

## Threat Surface Scan

无计划外新增威胁面（复用既有 client / TanStack Query / reka-ui / vue-i18n 栈，无新增 npm 依赖，T-24-SC accept）。计划内威胁缓解均落地：
- **T-24-13（信息泄漏）**：面板仅渲染后端脱敏 `reason`，不构造/回显原始文件内容或密钥本体。
- **T-24-14（接受语义篡改/误导）**：accept 确认弹窗明示「新增排除规则、不会自动删除已索引内容、需在清理面板显式执行」；测试 (b) 断言该措辞。
- **T-24-15（real_secret 可见性/抵赖）**：real_secret 高优先级 destructive 告警 + 行内危险底色，确保用户必然注意到真实密钥；测试 (a) 断真实告警文案。

## Known Stubs

None - 列表、accept/dismiss 均实接 24-03 REST API，无占位/空数据桩。

## Verification

- `cd web && pnpm vitest run src/components/repository/__tests__/SensitiveSuggestionsPanel.spec.ts` → **4 passed**。
- `cd web && pnpm exec vue-tsc --noEmit 2>&1 | grep -ci "sensitive"` → **0**（无 sensitive 相关类型错误）。
- `cd web && pnpm exec eslint src/api/sensitiveSuggestions.ts src/components/repository/SensitiveSuggestionsPanel.vue src/components/repository/__tests__/SensitiveSuggestionsPanel.spec.ts` → **0 错**。
- `grep -n "SensitiveSuggestionsPanel" web/src/pages/repositories/[id]/index.vue` → 命中 import + 挂载（行 16 / 612）。

## Self-Check: PASSED

---
*Phase: 24-sensitive-ai-detect*
*Completed: 2026-06-15*
