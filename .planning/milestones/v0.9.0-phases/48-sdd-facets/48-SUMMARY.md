---
phase: 48-sdd-facets
plans: [48-01, 48-02]
subsystem: [server/services, server/repositories, web/repositories]
tags: [sdd, facets, methodology, indexing, i18n]
requires:
  - 索引完成钩子（FINALIZING base-only 派发范式，Phase 24/25）
  - tree_views.py facets 透出面（知识树）
provides:
  - server/services/sdd_detect.py（detect_and_tag_sdd 单一写入入口）
  - indexer FINALIZING best-effort SDD 派发钩子（_run_sdd_detect）
  - RepositorySerializer.methodology 只读派生字段
  - SddMethodologyBadge.vue + i18n（repositories.tree.sddBadge/sddBadgeTitle）
affects:
  - 后续 Phase 49–52 spec 生命周期治理（methodology 入口信号）
tech-stack:
  added: []
  patterns: [best-effort fail-safe 钩子, facets 单一写入入口, vue-i18n 守护组件]
key-files:
  created:
    - server/services/sdd_detect.py
    - server/tests/test_sdd_detect.py
    - server/tests/repositories/test_repository_methodology_field.py
    - web/src/components/repository/SddMethodologyBadge.vue
    - web/src/components/repository/__tests__/SddMethodologyBadge.spec.ts
  modified:
    - server/services/indexer.py
    - server/repositories/serializers.py
    - web/src/pages/repositories/tree.vue
    - web/src/pages/repositories/index.vue
    - web/src/pages/repositories/[id]/index.vue
    - web/src/types/index.ts
    - web/src/locales/zh-CN.json
metrics:
  completed: 2026-06-17
---

# Phase 48 Plan 01+02: SDD 仓库检测 + facets 打标 + 前端标签 Summary

索引完成后纯 `os.path.isdir` 探测仓库根 `openspec/`，best-effort 写 `facets["methodology"]="SDD"`（绝不阻断索引 success），并在知识树、标准 `/repositories` 列表/详情页透出显式 SDD 方法论徽标。

## What Was Built

### 48-01 后端检测链路（SDD-01）

- **`server/services/sdd_detect.py`** — `async def detect_and_tag_sdd(repository_id, repo_path) -> bool` 单一写入入口。纯文件系统探测（仅 import `os` + `structlog`，`Repository` 函数内惰性 import，零重依赖 D-48-5）：
  - openspec/ 存在 → `facets["methodology"]="SDD"`。
  - openspec/ 不存在且当前为自动写入的 `"SDD"` → 删除该键（防漂移）；他值不动。
  - `methodology` 在 `_pinned` → 跳过（尊重人工 pin）。
  - facets 未变 → 不 `asave`（幂等，避免 `updated_at` 漂移）。
  - repo 缺失 / openspec 为文件而非目录 → 返回 False，不抛。
- **`server/services/indexer.py`** — 新增模块级 `_run_sdd_detect` 钩子（复刻 `_run_commit_index` / `_run_sensitive_detection` fail-safe 范式：整段 try/except → `sdd_detect_dispatch_failed` warning，绝不重抛），并在 `clone_and_index_repository` FINALIZING `if not branch:` 段、rmtree 之前 `await`（仅 base 路径）。

### 48-02 前端标签（SDD-02）+ orchestrator 范围扩展

- **`SddMethodologyBadge.vue`** — 镜像 `EntityKindBadge.vue` 形状，`methodology === 'SDD'` 守护 + vue-i18n，emerald 高亮，非 SDD 不渲染任何节点。
- **i18n** — `repositories.tree.sddBadge`="SDD" / `sddBadgeTitle`="Spec-Driven（openspec）仓库"（zh-CN，专有名词保留英文）。
- **知识树 `tree.vue`** — 卡片 + 能力树详情接入徽标；详情通用 chip 循环过滤 `methodology==='SDD'`，避免与显式徽标重复渲染。
- **范围扩展（orchestrator 决策，覆盖 48-02 plan D-48-4 开放点）**：
  - `RepositorySerializer.methodology` 只读 `SerializerMethodField`，从 `facets.get("methodology")` 派生（无 facets → null），让标准 `/repositories` 列表/详情不依赖知识树即可透出 SDD。
  - `Repository` TS 类型新增 `methodology?: string | null`。
  - 主 `/repositories` 列表卡片（`index.vue`）+ 仓库详情页头部（`[id]/index.vue`）渲染 `SddMethodologyBadge`。

## Tests

- 后端 `tests/test_sdd_detect.py`（9 例）：含/不含 openspec、删除取消标记、他值不清、`_pinned` 跳过、幂等不漂移（`updated_at` 不变）、repo 缺失不抛、openspec 为文件不打标；挂接守护：rmtree 前 await 时序 + 检测异常不冒泡（best-effort）。
- 后端 `tests/repositories/test_repository_methodology_field.py`（3 例）：facets→"SDD" 派生、缺省 null、字段只读。
- 前端 `SddMethodologyBadge.spec.ts`（4 例）：SDD 渲染（文案/标题取自真实 `zh-CN.json`）、他值/undefined/null 不渲染。

验证结果：
- `uv run pytest tests/test_sdd_detect.py tests/repositories/test_repository_methodology_field.py` 全绿（含既有 auto_build_graph 回归 → 17 passed）。
- `uv run ruff check`（sdd_detect / indexer / serializers / 测试）全部 `All checks passed!`。
- `pnpm vitest run`（4 passed）、`pnpm vue-tsc --noEmit`（无错）、`pnpm eslint`（5 文件干净）、`zh-CN.json` JSON 合法。
- 接入计数：`tree.vue` SddMethodologyBadge=3（1 import + 2 usage）、`index.vue`=2、`[id]/index.vue`=2；`grep _run_sdd_detect(repository_id, temp_dir)` 去注释后=1。

## Deviations from Plan

**范围扩展（orchestrator 决策，非偏差）**：48-02 plan D-48-4 原边界为「仅复用知识树 facets 透出面，不新增后端 serializer 字段」。本次执行按 orchestrator 明确指示扩展：为满足 SDD-02「仓库列表与详情页可见」，新增只读 `RepositorySerializer.methodology` 字段并在标准 `/repositories` 列表/详情渲染徽标。保持最小 diff、只读派生、零回归（既有 serializer 字段与测试不受影响）。

其余按 plan 实现，无其它偏差。

## Self-Check: PASSED

- created files 存在：`sdd_detect.py` / `SddMethodologyBadge.vue` / 两份测试 / `test_repository_methodology_field.py` ✅
- 提交均存在（test→feat TDD 边界 + 后端 serializer + 前端 feat/test）✅
- 全部测试 + lint + 类型检查通过 ✅
