---
phase: 48-sdd-facets
reviewed: 2026-06-17T01:40:20Z
depth: deep
files_reviewed: 11
files_reviewed_list:
  - server/services/sdd_detect.py
  - server/services/indexer.py
  - server/repositories/serializers.py
  - web/src/components/repository/SddMethodologyBadge.vue
  - web/src/pages/repositories/tree.vue
  - web/src/pages/repositories/index.vue
  - web/src/pages/repositories/[id]/index.vue
  - web/src/types/index.ts
  - web/src/locales/zh-CN.json
  - web/src/components.d.ts
  - web/src/components/repository/__tests__/SddMethodologyBadge.spec.ts
findings:
  critical: 0
  warning: 1
  info: 2
  total: 3
status: issues_found
---

# Phase 48: Code Review Report

**Reviewed:** 2026-06-17T01:40:20Z
**Depth:** deep
**Files Reviewed:** 11
**Status:** issues_found

## Summary

Phase 48（SDD 仓库检测 + facets 打标 + 前端徽标）整体实现稳健，对照本次审查的全部重点逐项核实通过：

- **fail-safe 绝不阻断 index success** ✅ — `_run_sdd_detect` 整段 `try/except` 吞异常仅记 `sdd_detect_dispatch_failed` warning，绝不重抛；位于 `clone_and_index_repository` 的 `if not branch:` base-only 守护内、`finally` 的 `shutil.rmtree(temp_dir)` 之前被 `await`。`test_dispatch_swallows_detector_exception` / `test_dispatch_hook_runs_before_rmtree_in_clone_and_index` 守护成立。
- **幂等 + `_pinned` 尊重** ✅ — `if facets == (repo.facets or {}): return False` 幂等 no-op 守护避免 `updated_at` 漂移；`_pinned` 含 `methodology` 时早退不读不写。两条均有守护测试（`test_idempotent_no_save_when_already_sdd`、`test_pinned_methodology_skips_detection`）。
- **openspec 消失只清自动 SDD、不误删他值** ✅ — 仅当 `facets["methodology"] == "SDD"` 时 `del`，他值（如 `自研流程`）原样保留（`test_openspec_absent_keeps_other_methodology_value`）。`openspec` 为普通文件而非目录时 `os.path.isdir` 为假，不打标（`test_openspec_as_file_is_not_tagged`）。
- **serializer 不泄漏敏感字段** ✅ — `RepositorySerializer.Meta.fields` 不含 `facets`，只透出从 `facets["methodology"]` 派生的只读 `methodology`，`_pinned` 等内部键不外泄；`tree_views.py` 透出 facets 时也过滤 `_` 前缀键。`methodology` 为 `SerializerMethodField`，写入被忽略（`test_methodology_is_read_only`）。
- **前端徽标守护与 i18n** ✅ — `SddMethodologyBadge` 以 `v-if="isSdd"`（严格 `=== 'SDD'`）守护，非 SDD / `null` / `undefined` 均不渲染（4 条 spec）。`zh-CN.json` 仅存在单个 `repositories` 顶级键（无重复键覆盖风险），文案以真实 JSON 断言；`tree.vue` 过滤 `methodology===SDD` 的通用 chip，避免与徽标双重渲染。
- **回归** ✅ — `tree.vue` chip 渲染由 `v-for span` 改为 `template v-for + v-if` 过滤，仅排除已由徽标承载的 `methodology:SDD`，其余分面 chip 行为不变。后端 9 条 SDD 检测测试、3 条 serializer 测试、前端 4 条 spec 全部本地实跑通过。

仅发现 1 个 WARNING（共享 `facets` JSON 字段的并发丢更新窗口，沿用既有模式）与 2 个 INFO。无 BLOCKER。

## Warnings

### WR-01: `facets` JSON 字段的并发读-改-写丢更新窗口

**File:** `server/services/sdd_detect.py:62-73`
**Issue:** `detect_and_tag_sdd` 以「`dict(repo.facets)` → 改 `methodology` → `repo.asave(update_fields=["facets","updated_at"])`」整段 read-modify-write 写回整个 JSON blob。`FacetService.refresh_fact_facets`（`server/repositories/facet_service.py:56-65`）使用**完全相同**的模式写同一字段，且它可被独立流程触发（除索引内 `indexer.py:1310` 外，还有 `server/subagent/api/callbacks.py:1177` 的 AI summary 回调）。若两者交错执行（各自读到旧 facets 后分别写回），后写者会用不含对方新键的快照覆盖整字段，导致 `methodology` 或事实分面被瞬时丢弃，需待下一轮索引/刷新才自愈。`update_fields=["facets"]` 写的是整段 JSON，无法做到键级隔离，因此「methodology 与 FacetService 键不冲突」只保证逻辑不重叠，并不能避免整 blob 丢更新。

属低概率、最终一致、且**沿用本仓库既有写入范式**（FacetService 自身亦如此），非 Phase 48 独有缺陷；但本 phase 确实新增了一个对该 JSON 字段的独立并发写入者，故记录在案。

**Fix:** 若要彻底消除窗口，可对 facets 写回收敛到带行锁的原子读-改-写（在 `sync_to_async` 内用 `transaction.atomic()` + `select_for_update()` 重新取最新 `repo.facets` 再 merge），或将 `methodology` 升为独立列。鉴于 best-effort/最终一致语义，亦可仅在文档中明确接受该窗口、不改代码。示例（最小化窗口）：

```python
from asgiref.sync import sync_to_async
from django.db import transaction

@sync_to_async
def _atomic_tag(repository_id: str, present: bool) -> bool:
    with transaction.atomic():
        repo = Repository.objects.select_for_update().filter(id=repository_id).first()
        if repo is None:
            return False
        facets = dict(repo.facets or {})
        if _METHODOLOGY_KEY in set(facets.get(_PINNED_KEY, [])):
            return False
        if present:
            facets[_METHODOLOGY_KEY] = _SDD_VALUE
        elif facets.get(_METHODOLOGY_KEY) == _SDD_VALUE:
            del facets[_METHODOLOGY_KEY]
        if facets == (repo.facets or {}):
            return False
        repo.facets = facets
        repo.save(update_fields=["facets", "updated_at"])
        return True
```

## Info

### IN-01: `methodology` 同时显式声明并列入 `read_only_fields`（冗余）

**File:** `server/repositories/serializers.py:57,121`
**Issue:** `methodology` 既被显式声明为 `serializers.SerializerMethodField()`（本身永远只读），又被加入 `Meta.read_only_fields`。`SerializerMethodField` 天然只读，重复声明属冗余（同序列化器内另两个 method field `has_credential` / `linked_spaces_count` 即未列入 `read_only_fields`）。当前 DRF 版本未对此报错（3 条 serializer 测试实跑通过），但与同文件惯例不一致，易误导后续维护者以为该项有实际作用。
**Fix:** 从 `Meta.read_only_fields` 中移除 `methodology`，仅保留显式 `SerializerMethodField()` 声明即可。

### IN-02: `_pinned` 非 list 时 pin 守护静默失效（沿用既有模式，非本 phase 新引入）

**File:** `server/services/sdd_detect.py:58-60`
**Issue:** `pinned = set(facets.get(_PINNED_KEY, []))`。若 `_pinned` 被写成字符串（如 `"methodology"`）而非 list，`set("methodology")` 会按字符拆分，`"methodology" in pinned` 恒为 False，pin 守护静默失效、人工 pin 被自动检测覆盖。`FacetService`（`facet_service.py:57`）使用**完全相同**的 `set(facets.get("_pinned", []))`，故此为既有约定（`_pinned` 始终为 list），非本 phase 新引入的缺陷。
**Fix:** 可选硬化：`pinned = set(facets.get(_PINNED_KEY) or [])` 并在取用前做 `isinstance(..., (list, tuple, set))` 类型校验；若维持现状则依赖 `_pinned` 写入端契约。

---

## Verification Notes（本地实跑）

- `server/tests/test_sdd_detect.py` — 9 passed
- `server/tests/repositories/test_repository_methodology_field.py` — 3 passed
- `web/src/components/repository/__tests__/SddMethodologyBadge.spec.ts` — 4 passed

---

_Reviewed: 2026-06-17T01:40:20Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
