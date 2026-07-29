---
phase: 106-multi-signal-scoring
plan: 03
subsystem: codegraph-routing
tags: [repo-router, metadata-resolver, alias-dict, t2-calibrated-cosine, embedding-cache, facet-scores]

# Dependency graph
requires:
  - phase: 106-multi-signal-scoring/106-01
    provides: SIGNAL_DOMAIN/STACK/TEAM 常量、repo_meta.facet_scores 键契约（docstring 权威定义）、DEFAULT_WEIGHT_CONFIG（t2_c_lo/c_hi 初值与 t2_disabled_facets 位）
provides:
  - 元数据 resolver 模块 repo_router_metadata.py：T1 别名词典纯函数 + T2 校准余弦（async）+ facet_scores 组装
  - DEFAULT_ALIAS_DICT 双轨词典骨架（代码常量起步；SystemSetting repo_router.alias_dict 覆盖经 merge_alias_dict 合并，106-06 接线）
  - match_t1 / merge_alias_dict / alias_dict_hash 纯函数——golden harness（106-08）可无 Django 环境离线 import（已验证）
  - FacetT2Matcher（facet 值向量 Django cache + 进程内二级缓存，key repo_router:facet_vec:{model_id}:{sha256(value)}，TTL 7d）+ warm_facet_vectors 批量预热
  - resolve_facet_scores 输出契约 == repo_meta.facet_scores（{domain|stack|team: {score, layer}}），来源层 t1/t2/None 随分数进快照
affects: [106-04, 106-06, 106-07, 106-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Django 依赖局部 import 隔离：模块顶层 stdlib-only，T2 的 cache/EmbeddingService/CallSource 全部在方法体内 import——纯函数部分可离线确定性复用"
    - "T1 匹配 ASCII 短 token 词边界护栏：纯 ASCII token 用 (?<![a-z0-9])token(?![a-z0-9])，中文短语直接 in（零依赖）"
    - "T2 静默降级：任何失败 → None + repo_router_t2_degraded 采样 warning，绝不阻塞路由"

key-files:
  created:
    - server/codegraph/services/repo_router_metadata.py
    - server/tests/codegraph/test_repo_router_metadata.py
  modified: []

key-decisions:
  - "ASCII 短 token 加字母数字词边界（否则 django 误命中 Go、tests 误命中别名 ts）；中文短语保持直接 in——plan 字面为纯子串匹配，误报会以 1.0 确定性分数污染排序，按 Rule 2 补齐"
  - "stack 聚合 second_max 只在已匹配值上取（仅 1 值命中时 second_max=0 → 0.8·max）；全部值未命中 → 信号不可用（None），不给 0"
  - "warm_facet_vectors 返回「调用后向量可用」条数（先前已缓存 + 本次成功写入），整体 best-effort 绝不抛"
  - "resolver 复用 scoring 的 SIGNAL_* 常量作输出键（stdlib-only 跨模块 import），契约一致性由代码而非约定保证"

patterns-established:
  - "别名词典双轨：DEFAULT_ALIAS_DICT 代码常量起步 + SystemSetting 覆盖合并；生效词典 alias_dict_hash 进快照保回放确定性（T-106-08）"
  - "facet 值长度 200 字符 DoS 护栏在 resolver 与 matcher 双侧生效（T-106-06）"

requirements-completed: [ROUTE-04]

coverage:
  - id: D1
    description: "T1 确定性别名词典匹配 + facet 解析语义：canonical/alias 1.0、parent 0.6、未命中 None；技术栈多值 0.8·max+0.2·second_max；未分类/空/缺失/超长 → 不可用；团队条件信号不给 0.5；merge/hash 纯函数；零 Django import 可离线复用"
    requirement: ROUTE-04
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_metadata.py#TestMatchT1/TestResolveFacetScores/TestMergeAliasDict（32 条）"
        status: pass
      - kind: other
        ref: "uv run python -c \"sys.modules['django']=None; import codegraph.services.repo_router_metadata\"（无 Django 环境 import 验证）"
        status: pass
    human_judgment: false
  - id: D2
    description: "T2 校准余弦通道：clip((cos-c_lo)/(c_hi-c_lo),0,1) 三点校准；facet 值向量两级缓存（命中零 embedding 调用）；EmbeddingService 失败/未配置/facet 被 t2_disabled_facets 禁用 → 静默降级 T1-only + repo_router_t2_degraded 采样 warning；团队绝不走 T2；warm_facet_vectors 批量预热"
    requirement: ROUTE-04
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_metadata.py#TestFacetT2Matcher/TestWarmFacetVectors（11 条）"
        status: pass
      - kind: integration
        ref: "resolver→aggregate_and_score 端到端契约检查（facet_scores 直接作 repo_meta 注入，六信号 breakdown + INV-R3 成立；tests/codegraph 全量 351 passed 零回归）"
        status: pass
    human_judgment: false

# Metrics
duration: 13min
completed: 2026-07-29
status: complete
---

# Phase 106 Plan 03: 元数据 resolver（T1 别名词典 + T2 校准余弦） Summary

**`repo_router_metadata.py` 落地 ROUTE-04 三层匹配的信号生产层：T1 别名词典纯函数（canonical/alias 1.0、parent 0.6，零 Django 可离线 import）+ T2 校准余弦（facet 向量两级缓存、失败静默降级）+ facet_scores 组装（多值 0.8·max+0.2·second_max、"未分类"→缺失、团队条件信号），输出契约与 106-01 scorer 的 repo_meta.facet_scores 严格一致**

## Performance

- **Duration:** ~13 min
- **Started:** 2026-07-29T08:46:43Z
- **Completed:** 2026-07-29T08:59:06Z
- **Tasks:** 2（均 TDD：RED→GREEN 四提交）
- **Files modified:** 2（均新建）

## Accomplishments

- **T1 确定性层**（纯函数，golden harness 可离线复用）：`match_t1` casefold 匹配（中文短语直接 in、纯 ASCII token 加词边界防误报），canonical/alias 命中 1.0、仅上位类目 0.6、未命中 None；`DEFAULT_ALIAS_DICT` 技术栈维度照抄 `_EXT_LANGUAGE_MAP` 18 语言 + 常见别名，活跃度/关键程度枚举骨架（关键程度四档全保留，Pitfall 1），语义分面/团队空骨架待 SystemSetting 覆盖（生产词表 deferred，同 O-2 纪律）。
- **facet 解析语义全部测试锁定**：`技术栈` split("/") 逐值匹配后 `0.8·max + 0.2·second_max`（绝不 sum/mean——验收 grep 零命中）；"未分类"/空串/缺失/超长（>200 字符 DoS 护栏，T-106-06）→ `{score: None, layer: None}` 进重归一化；`团队归属` 只走 T1 且需求未提团队 → None（不给 0.5）；criticality/activity 原值不经 resolver（分工注释就位，106-06 直接放 repo_meta）。
- **T2 校准余弦通道**：`FacetT2Matcher` 用调用方已算好的 query dense 向量（零额外 query embedding），facet 值向量走 Django cache（key `repo_router:facet_vec:{model_id}:{sha256(value)}`，TTL 7d）+ 进程内 dict 二级缓存；miss 时经 `use_call_source(CallSource.EMBEDDING)` 调 `EmbeddingService`；余弦 stdlib 显式循环（禁 numpy，验收 grep 零命中）；任何失败 → None + `repo_router_t2_degraded`（sampling，facet_value 截断 32 字符，T-106-07）。
- **双轨词典设施**：`merge_alias_dict` 覆盖合并（override 非 dict 结构条目跳过，T-106-08 容错；default 不被原地修改）+ `alias_dict_hash`（canonical JSON sha256，键序不变）供 106-06 快照审计。
- **43 条测试全绿**（Task 1 32 条 + Task 2 11 条，验收要求 ≥18）；`tests/codegraph` 全量 351 passed / 20 skipped 零回归；resolver→scorer 端到端契约验证：facet_scores 直接注入 repo_meta 后六信号 breakdown 齐备、INV-R3（Σbreakdown==score）成立、条件信号缺失重归一化行为正确。

## Task Commits

Each task was committed atomically (TDD: RED → GREEN):

1. **Task 1: T1 别名词典 + facet 解析纯函数** - `828a54b1` (test, RED) → `7a192392` (feat, GREEN)
2. **Task 2: FacetT2Matcher 校准余弦 + 缓存 + 静默降级** - `68a5e512` (test, RED) → `9951fd21` (feat, GREEN)

## Files Created/Modified

- `server/codegraph/services/repo_router_metadata.py`（644 行）- 元数据 resolver：facet 键名/层级/未分类常量、DEFAULT_ALIAS_DICT、match_t1/merge_alias_dict/alias_dict_hash 纯函数、resolve_facet_scores 主入口、FacetT2Matcher、warm_facet_vectors
- `server/tests/codegraph/test_repo_router_metadata.py`（513 行）- 43 条：T1 三层语义/词边界防误报/多值聚合/未分类/条件信号/超长护栏/合并容错/hash 不变性/T2 校准三点/缓存命中与回写/降级 warning/T2 禁用清单/预热计数

## Decisions Made

- **ASCII 短 token 词边界**：plan 字面为「casefold 子串包含匹配」，但 DEFAULT 词典自带大量 2 字符 ASCII 别名（py/ts/js/kt），纯子串会让 "django" 误命中 "Go"、"tests" 误命中 "ts"——T1 是确定性层，误报直接产出 1.0 分数污染排序。纯 ASCII token 改用 `(?<![a-z0-9])token(?![a-z0-9])` 词边界（re 为 stdlib，零依赖约束不破），中文短语保持直接 `in`（plan 原文语义）。测试 `test_short_ascii_alias_no_false_positive` 锁定。
- **stack second_max 口径**：second_max 只在已匹配（非 None）值上取；仅一值命中时 second_max=0 → 0.8·max（plan 注释要求已写入代码）；全部未命中 → 信号不可用（未知 ≠ 确认不匹配，重归一化锁定语义）。
- **词典 canonical 键查找大小写不敏感**（exact 优先，casefold 扫描兜底）——facet 值与词典键来自同一闭集，此容错防运维覆盖时大小写笔误。
- **warm_facet_vectors 计数语义**：返回调用后向量可用的值条数（含先前已缓存），best-effort 全包裹（预热失败不阻塞冷启动，T2 自然降级）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] T1 匹配 ASCII 短 token 词边界护栏**
- **Found during:** Task 1（DEFAULT_ALIAS_DICT 别名表设计时）
- **Issue:** plan 指定纯 casefold 子串匹配，但同一 plan 要求的短别名（py/ts/js/golang 等）在纯子串下大规模误报（"django"→Go、"tests"→ts），确定性层误报=错误的 1.0 信号分
- **Fix:** `_contains_token` 对纯 ASCII token 用字母数字词边界 regex，含 CJK token 保持直接 `in`；零新增依赖
- **Files modified:** server/codegraph/services/repo_router_metadata.py
- **Verification:** test_short_ascii_alias_no_false_positive + 全部行为用例仍按 plan 字面通过
- **Committed in:** 7a192392（Task 1 GREEN 提交）

---

**Total deviations:** 1 auto-fixed（1 missing critical correctness guard）
**Impact on plan:** 匹配语义收紧仅消除误报路径，plan 全部 behavior 样例不受影响；无 scope creep。

## Issues Encountered

None——除上述 deviation 外按计划执行；两轮 TDD 均 RED（collection error）→ GREEN 一次通过。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 106-06（router 组装 repo_meta）：`resolve_facet_scores` 即取即用——传 query_text/facets/合并词典/constants（含 t2_disabled_facets）/query_embedding/FacetT2Matcher；`SettingKeys.REPO_ROUTER_ALIAS_DICT` 读取后 `merge_alias_dict(DEFAULT_ALIAS_DICT, override)` 合并，`alias_dict_hash` 进快照。
- 106-04（校准 command）：`warm_facet_vectors` 可直接用于闭集向量预热；t2_c_lo/c_hi 生产校准回填后经 FacetT2Matcher 构造参数生效。
- 106-08（golden harness）：`match_t1`/`DEFAULT_ALIAS_DICT`/`merge_alias_dict`/`alias_dict_hash` 已验证可无 Django 环境 import（T1-only 确定性离线路径）。
- T2 校准初值（0.25/0.55）沿用 DEFAULT_WEIGHT_CONFIG，生产 O-2 实测回填 deferred（构造函数带非法值回退护栏）。

## Self-Check: PASSED

- FOUND: server/codegraph/services/repo_router_metadata.py
- FOUND: server/tests/codegraph/test_repo_router_metadata.py
- FOUND: commit 828a54b1（test, Task 1 RED）
- FOUND: commit 7a192392（feat, Task 1 GREEN）
- FOUND: commit 68a5e512（test, Task 2 RED）
- FOUND: commit 9951fd21（feat, Task 2 GREEN）
- 验证命令复核：43 passed（本文件）；tests/codegraph 351 passed / 20 skipped；ruff check/format 双绿；numpy/sum(/mean( grep 零命中；use_call_source ≥1；无 Django import 验证通过

---
*Phase: 106-multi-signal-scoring*
*Completed: 2026-07-29*
