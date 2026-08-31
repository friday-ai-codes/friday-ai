---
phase: 48-sdd-facets
verified: 2026-06-17T01:38:00Z
status: human_needed
score: 10/10 must-haves verified
overrides_applied: 0
human_verification:

  - test: "在真实索引环境（容器/runner + 真实 clone）对一个仓库根含 openspec/ 的真实仓库跑一次 base 索引，索引完成后查 Repository.facets"
    expected: "FINALIZING 钩子在 rmtree 之前命中真实 clone 路径，facets[\"methodology\"]==\"SDD\"；索引 success 终态不受影响"
    why_human: "单测直接以 tmp_path 调 detect_and_tag_sdd，挂接测试为源码顺序断言 + monkeypatch fail-safe，未真实跑完整 clone→index→FINALIZING 链路；端到端需真实容器/索引环境"

  - test: "对一个不含 openspec/ 的真实仓库跑索引，再对一个曾打标的仓库删除 openspec/ 后重索引"
    expected: "不含的不被误标；删除后自动 SDD 标记被清除；重复索引 updated_at/facets 不漂移"
    why_human: "幂等与防漂移在单测层已证，但真实多次索引（含增量/分支 overlay 不触发）需真实索引环境端到端确认"

  - test: "在浏览器打开标准 /repositories 列表、仓库详情页、知识树页，查看一个已打标 SDD 的真实仓库"
    expected: "列表卡片、详情页头部、知识树卡片+能力树详情均显示 emerald 高亮的 \"SDD\" 徽标（hover title 为 zh-CN 文案），非 SDD 仓库不显示；详情 facets 通用 chip 不重复渲染 methodology=SDD"
    why_human: "视觉呈现/高亮样式/真实数据流（serializer methodology 透出 + tree_views facets 透出）端到端需人工目检"
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: human_needed
---

# Phase 48: SDD 仓库检测 + facets 打标 + 前端标签 Verification Report

**Phase Goal:** 索引完成后自动识别 spec-driven 仓库并打标，用户在前端可识别 SDD 仓库
**Verified:** 2026-06-17T01:38:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | 含 `openspec/` 的仓库索引后写 `facets["methodology"]="SDD"` | ✓ VERIFIED | `sdd_detect.py:63-65` `os.path.isdir`→`facets[methodology]=SDD`；测试 `test_openspec_present_tags_sdd` 绿 |
| 2 | 不含 `openspec/` 不被误标 | ✓ VERIFIED | `sdd_detect.py:66` 仅当原值为自动 SDD 才清除；`test_openspec_absent_keeps_other_methodology_value` 绿（他值 "自研流程" 不动） |
| 3 | 删除 `openspec/` 后取消自动 SDD 标记，他值不动 | ✓ VERIFIED | `sdd_detect.py:66-68` `del facets[methodology]` 仅针对 `=="SDD"`；`test_openspec_absent_clears_auto_sdd_tag` 绿 |
| 4 | `_pinned` 含 methodology 时跳过，不覆盖人工 pin | ✓ VERIFIED | `sdd_detect.py:59-61` pin 守护；`test_pinned_methodology_skips_detection` 绿 |
| 5 | 重复检测幂等：facets 未变不 asave，updated_at 不漂移 | ✓ VERIFIED | `sdd_detect.py:71-72` no-op 守护；`test_idempotent_no_save_when_already_sdd` 断 `updated_at` 不变，绿 |
| 6 | 检测/打标 best-effort，绝不阻断索引 success | ✓ VERIFIED | `indexer.py:3481-3490` 整段 try/except→`sdd_detect_dispatch_failed` warning 不重抛；`test_dispatch_swallows_detector_exception` 绿 |
| 7 | `facets.methodology==="SDD"` 时列表卡片渲染 SDD 徽标 | ✓ VERIFIED | `tree.vue:368` + `index.vue:159`（标准列表）；`SddMethodologyBadge.vue:11,16` `isSdd` 守护；组件测试绿 |
| 8 | 详情渲染 SDD 徽标，区别于普通 chip | ✓ VERIFIED | `tree.vue:399` + `[id]/index.vue:355`；`tree.vue:402` chip 循环过滤 `methodology==='SDD'` 防重复 |
| 9 | 非 SDD（缺失/他值）不渲染徽标 | ✓ VERIFIED | `SddMethodologyBadge.vue:16` `v-if="isSdd"`；测试覆盖 他值/undefined/null 三例不渲染，绿 |
| 10 | 徽标文案来自既有 vue-i18n（zh-CN），默认中文 | ✓ VERIFIED | `SddMethodologyBadge.vue:9,18,21` `useI18n` + `t(...)`；`zh-CN.json:155-156` `sddBadge`/`sddBadgeTitle`；测试以真实 json 断言文案，绿 |

**Score:** 10/10 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `server/services/sdd_detect.py` | `detect_and_tag_sdd` 单一写入入口 | ✓ VERIFIED | 纯 `os`+`structlog`，`Repository` 惰性 import；零重依赖（无 indexer/tree-sitter/LLM/FacetService） |
| `server/services/indexer.py` | `_run_sdd_detect` 钩子 + base-only 调用 | ✓ VERIFIED | 钩子 `3469-3490`；FINALIZING `if not branch:` 段 `3894` `await _run_sdd_detect(...)`，rmtree `3945` 在其后 |
| `server/tests/test_sdd_detect.py` | 检测器 + fail-safe 守护测试 | ✓ VERIFIED | 9 例全绿（含/不含/清除/他值/pin/幂等/缺失/文件/挂接顺序+异常吞噬） |
| `server/repositories/serializers.py` | `methodology` 只读派生字段 | ✓ VERIFIED | `get_methodology` 从 `facets.get("methodology")` 派生；`read_only_fields` 含 methodology |
| `server/tests/repositories/test_repository_methodology_field.py` | serializer 派生守护 | ✓ VERIFIED | 3 例全绿（SDD 派生/缺省 null/只读） |
| `web/src/components/repository/SddMethodologyBadge.vue` | i18n + SDD 守护徽标组件 | ✓ VERIFIED | `useI18n`、`isSdd` 守护、emerald 高亮、非 SDD 不渲染节点 |
| `web/src/pages/repositories/tree.vue` | 卡片 + 详情接入徽标 | ✓ VERIFIED | import + 2 usage（卡片 `368` / 详情 `399`）+ chip 去重过滤 `402` |
| `web/src/locales/zh-CN.json` | sddBadge/sddBadgeTitle 文案 | ✓ VERIFIED | `155-156` 键存在，JSON 合法 |
| `web/src/components/repository/__tests__/SddMethodologyBadge.spec.ts` | 渲染/非渲染 + 真实 json 文案 | ✓ VERIFIED | 4 例全绿，文案取自真实 `zhCN.repositories.tree.*` |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `indexer.clone_and_index_repository` FINALIZING (`if not branch:`) | `_run_sdd_detect → detect_and_tag_sdd` | best-effort dispatch before rmtree | ✓ WIRED | `3894` await，`detect_idx < rmtree_idx` 经 `test_dispatch_hook_runs_before_rmtree_in_clone_and_index` 断言 |
| `sdd_detect.detect_and_tag_sdd` | `Repository.asave` | 仅 facets 变更时写回 | ✓ WIRED | `75` `asave(update_fields=["facets","updated_at"])`，前置 no-op 守护 |
| `tree.vue` 卡片/详情 | `SddMethodologyBadge` | `:methodology="...facets?.methodology"` | ✓ WIRED | `368`/`399` |
| `index.vue` / `[id]/index.vue` | `SddMethodologyBadge` | `:methodology="repository.methodology"` | ✓ WIRED | `159`/`355`，依赖 serializer 派生字段 + TS 类型 `methodology?` |
| `SddMethodologyBadge.vue` | `zh-CN.json repositories.tree.sddBadge` | `t('repositories.tree.sddBadge')` | ✓ WIRED | `18`/`21` |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `index.vue` / `[id]/index.vue` 徽标 | `repository.methodology` | `RepositorySerializer.get_methodology` ← `obj.facets["methodology"]`（DB） | 是（真实 facets 派生，无 facets→null） | ✓ FLOWING |
| `tree.vue` 卡片/详情徽标 | `card.facets?.methodology` / `repoTree.facets?.methodology` | `repositories/tree_views.py` facets 透出 ← DB facets | 是（既有透出面） | ✓ FLOWING |
| `facets["methodology"]` 写入 | — | `detect_and_tag_sdd` `asave` ← FINALIZING 钩子真实 clone 路径 | 单测层真实写；真实索引链路端到端待人工确认 | ⚠️ 见 human_verification |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| 后端检测器 + 挂接守护测试 | `uv run pytest tests/test_sdd_detect.py` | 9 passed | ✓ PASS |
| serializer methodology 派生测试 | `uv run pytest tests/repositories/test_repository_methodology_field.py` | 3 passed | ✓ PASS |
| 前端徽标渲染/文案测试 | `pnpm vitest run .../SddMethodologyBadge.spec.ts` | 4 passed | ✓ PASS |
| 端到端真实索引打标 | 需真实容器/索引环境 | — | ? SKIP → human |

### Probe Execution

不适用：本 phase 未声明 probe，且非 migration/probe 驱动 phase。

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| SDD-01 | 48-01 | 索引完成后检测 `openspec/` → `facets["methodology"]="SDD"`，best-effort 不阻断 | ✓ SATISFIED | 检测器 + 钩子 + fail-safe，truths 1–6 全绿；端到端真实索引待人工 |
| SDD-02 | 48-02 | 用户在仓库列表/详情看到 SDD 标签 | ✓ SATISFIED | 徽标组件 + serializer 派生 + tree/list/detail 接入，truths 7–10 全绿；视觉呈现待人工 |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | 无 TBD/FIXME/XXX/PLACEHOLDER；无空实现 stub；无悬空 fetch | — | 检测器/钩子/组件均为实质实现，无 debt marker |

### Human Verification Required

所有可程序化验证的 truth 均已通过单测/源码核查（10/10）。以下端到端项需真实容器/真实索引环境或人工目检确认：

#### 1. 真实索引链路打标（SDD-01 端到端）

**Test:** 在真实索引环境对一个仓库根含 `openspec/` 的真实仓库跑一次 base 索引，索引完成后查 `Repository.facets`。
**Expected:** FINALIZING 钩子在 rmtree 之前命中真实 clone 路径，`facets["methodology"]=="SDD"`；索引 success 终态不受影响。
**Why human:** 单测以 `tmp_path` 直接调检测器，挂接测试为源码顺序断言 + monkeypatch fail-safe，未真实跑完整 clone→index→FINALIZING 链路。

#### 2. 不误标 / 防漂移 / 幂等（SDD-01 端到端）

**Test:** 对不含 `openspec/` 的真实仓库索引；对曾打标仓库删除 `openspec/` 后重索引；同仓库重复索引。
**Expected:** 不含的不误标；删除后自动 SDD 标记被清除；重复索引 `updated_at`/facets 不漂移。
**Why human:** 真实多次索引（含增量、功能分支 overlay 不触发）需真实索引环境端到端确认。

#### 3. 前端徽标视觉呈现（SDD-02 端到端）

**Test:** 浏览器打开标准 `/repositories` 列表、仓库详情页、知识树页，查看一个已打标 SDD 的真实仓库。
**Expected:** 列表卡片、详情页头部、知识树卡片 + 能力树详情均显示 emerald 高亮的 "SDD" 徽标（hover title 为 zh-CN 文案）；非 SDD 不显示；详情 facets 通用 chip 不重复渲染 `methodology=SDD`。
**Why human:** 视觉高亮样式与真实数据流（serializer methodology 透出 + tree_views facets 透出）端到端需人工目检。

### Gaps Summary

无阻断性 gap。后端检测链路（SDD-01）与前端方法论徽标（SDD-02）的全部可程序化 truth 均已交付并经单测/源码核查证实：检测器单一写入入口、幂等防漂移、尊重 `_pinned`、不误标、清除自动标记、best-effort fail-safe 挂接（rmtree 之前 await）、serializer 只读派生、徽标组件守护与 i18n、tree/list/detail 三处接入与 chip 去重，均落实且测试全绿（后端 12 passed、前端 4 passed）。

唯余需真实容器/真实索引环境才能端到端确认的项（真实索引打标链路、防漂移多次索引、前端徽标视觉呈现）已列入 human_verification。因存在人工验证项，按决策树状态判定为 `human_needed`（非 gaps_found）。

---

_Verified: 2026-06-17T01:38:00Z_
_Verifier: Claude (gsd-verifier)_
