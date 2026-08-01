---
phase: 106-multi-signal-scoring
plan: 02
subsystem: codegraph-routing
tags: [repo-router, weight-config, system-setting, settings-service, validation, adrf]

# Dependency graph
requires:
  - phase: 106-multi-signal-scoring/106-01
    provides: DEFAULT_WEIGHT_CONFIG（唯一默认配置来源）、SIGNAL_* breakdown key 常量
provides:
  - SettingKeys 三键定版：repo_router.weight_config / nr_snapshot / alias_dict（106-04/05/06 只消费不再改 system/models.py）
  - repo_router_config.py loader/校验单点：WEIGHT_GRID、validate_weight_config、load_weight_config/aload_weight_config、load_nr_snapshot/aload_nr_snapshot
  - RepoRouterWeightConfigView（GET/PUT /api/settings/repo-router/weight-config/，superuser 写门禁）
  - 保存即生效链路（get_json_setting 60s 缓存 + post_save signal 失效）与非法值双层拦截（view 400 / loader 回退默认）
affects: [106-04, 106-05, 106-06, 106-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "配置 loader 单点 + 参数注入：纯函数模块零 I/O，router/replay 经 repo_router_config 读取后注入（RESEARCH Pattern 2）"
    - "单 JSON SystemSetting 键 + 专用端点强校验（CLAUDE_CODE_CONFIG 先例）；通用 settings PUT 不用于权重写入"
    - "视图层 sync_to_async 默认 thread_sensitive=True（与 Django async ORM 同线程语义）；thread_sensitive=False 的 aload_* 留给 router 热路径"

key-files:
  created:
    - server/codegraph/services/repo_router_config.py
    - server/tests/codegraph/test_repo_router_config.py
    - server/tests/system/test_repo_router_weight_config.py
  modified:
    - server/system/models.py
    - server/system/views.py
    - server/system/urls.py

key-decisions:
  - "不校验 Σw=1（CONTEXT ROUTE-04 的 C_crit 裁决取代 ROUTE-06 字面）：改为离散网格白名单 + INV-R2 相对形式 fsum(domain,stack,team) <= 0.5*fsum(全部5权重) + 常数逐项范围"
  - "视图 GET 用 sync_to_async(load_weight_config)（thread_sensitive=True）而非 aload_weight_config：与 async ORM 同线程语义一致；aload_*（thread_sensitive=False）保留给 106-06 router 热路径"
  - "is_default 严格按 SystemSetting 行存在性判定（行存在但非法时 loader 回退默认、is_default 仍为 false——运维可从 GET 值与默认对比察觉）"

patterns-established:
  - "权重配置写入唯一入口：RepoRouterWeightConfigView PUT（validate_weight_config 单点校验）；直写 DB 由 loader 二次校验兜底"
  - "settings_service 缓存测试纪律：locmem 不随测试事务回滚，用例前后清 _cache_key（两个测试文件同一 autouse fixture 形态）"

requirements-completed: [ROUTE-06]

coverage:
  - id: D1
    description: "权重配置 loader/校验单点：WEIGHT_GRID 网格白名单、INV-R2 相对形式、常数范围/跨键校验；load_weight_config 无行/坏 JSON/非法值回退 DEFAULT + warning（永不反噬路由）；load_nr_snapshot 形状契约；保存即生效（signal 失效缓存）"
    requirement: ROUTE-06
    verification:
      - kind: unit
        ref: "server/tests/codegraph/test_repo_router_config.py（33 条：校验矩阵/回退语义/保存即生效/异步一致性）"
        status: pass
    human_judgment: false
  - id: D2
    description: "专用端点 GET/PUT /api/settings/repo-router/weight-config/：GET 已认证返回生效配置 + is_default；PUT 仅 superuser、非法 400 + 逐条 errors、合法落库即生效；URL 排在 <str:key>/ 通配前，通用端点零回归"
    requirement: ROUTE-06
    verification:
      - kind: integration
        ref: "server/tests/system/test_repo_router_weight_config.py（13 条：GET 默认/存储、保存即生效链路、400 校验矩阵、403/401、resolve 回归）"
        status: pass
      - kind: unit
        ref: "server/tests/test_settings.py + tests/test_system_smoke.py（既有 settings 端点回归，58 passed 合并运行）"
        status: pass
    human_judgment: false

# Metrics
duration: ~50min（含前执行器中断接续）
completed: 2026-07-29
status: complete
---

# Phase 106 Plan 02: 权重外置与配置校验端点 Summary

**权重/常数外置为单 JSON SystemSetting 键 `repo_router.weight_config`：SettingKeys 三键定版 + `repo_router_config.py` loader/校验单点（网格白名单 + INV-R2 相对形式 + 常数范围，非法回退 DEFAULT）+ `RepoRouterWeightConfigView` 专用 GET/PUT 端点（superuser 写门禁，保存即生效）**

## Performance

- **Duration:** ~50 min（前执行器完成 RED + 大部分 loader 实现后中断，本执行器接续收尾）
- **Started:** 2026-07-29T07:47:00Z
- **Completed:** 2026-07-29T08:38:00Z
- **Tasks:** 2
- **Files modified:** 7（含 tests/system/__init__.py）

## Accomplishments

- SettingKeys 三键一次定版（weight_config / nr_snapshot / alias_dict，注释标注各键写方/读方 plan）——106-04/05/06 只消费不再动 `system/models.py`。
- `repo_router_config.py`（328 行）：`validate_weight_config` 为 view 与 loader 共用校验单点——权重键集合恰为 5 信号、离散网格 `WEIGHT_GRID`（1e-9 容差）、INV-R2 相对形式（`math.fsum`）、常数逐项范围 + `c_lo<c_hi` 跨键约束、锚点/版本/facet 列表结构校验；错误列表非空时返回可用的规范化尝试。
- 双层防御验证达成（T-106-03/04）：PUT 非法 400 + 逐条 errors 且不落库；直写 DB 非法值被 loader 拦截回退 `DEFAULT_WEIGHT_CONFIG` 深拷贝 + warning `repo_router_weight_config_invalid`（try/except 包裹，观测永不反噬路由）。
- 保存即生效链路经测试验证：预热 60s 缓存 → 写行触发 post_save signal 失效 → 下一次 `load_weight_config` 即新值（无需发版/重启）。
- 端点观测符合 LOGGING-SPEC：PUT 成功记 `repo_router_weight_config_updated`（info、category=caller、component=system，只记 weight_set_version 不记配置全文，T-106-05）。
- 46 条新测试全绿（33 loader + 13 端点）；既有 settings 端点零回归（合并回归运行 58 passed）。

## Task Commits

Each task was committed atomically:

1. **Task 1: SettingKeys 三键 + loader/校验单点（TDD RED）** - `4a5ef880` (test)（前执行器）
2. **Task 1: SettingKeys 三键 + loader/校验单点（TDD GREEN）** - `d5fe7acf` (feat)
3. **Task 2: RepoRouterWeightConfigView 专用端点 + URL + 测试** - `b979324d` (feat)

## Files Created/Modified

- `server/system/models.py` - SettingKeys 追加 REPO_ROUTER_WEIGHT_CONFIG / NR_SNAPSHOT / ALIAS_DICT 三常量（中文注释标注写方/读方）
- `server/codegraph/services/repo_router_config.py` - loader/校验单点：WEIGHT_GRID、validate_weight_config、load_weight_config、load_nr_snapshot、aload_*（sync_to_async thread_sensitive=False）
- `server/system/views.py` - RepoRouterWeightConfigView（GET 已认证 / PUT superuser，复用 validate_weight_config，aupdate_or_create 落库 + caller 观测事件）
- `server/system/urls.py` - `repo-router/weight-config/` path 插在 `<str:key>/` 通配之前（沿用文件内排序纪律注释）
- `server/tests/codegraph/test_repo_router_config.py` - 33 条：SettingKeys 定版 / 校验矩阵（含 11 参数化常数越界）/ 回退语义 / 保存即生效 / aload 一致性
- `server/tests/system/test_repo_router_weight_config.py` - 13 条：GET 默认与存储值 / PUT 合法落库即生效 / merge 语义 / 网格外·INV-R2·c_lo>=c_hi 400 / 403·401 / URL resolve 与通用端点回归
- `server/tests/system/__init__.py` - 新建 tests/system 包（本 plan 前不存在该目录）

## Decisions Made

- **INV-R2 测试构造修正**（RED 阶段即处理）：plan 字面样例 domain=0.30/stack=0.20/team=0.15 在默认 text=0.55/act=0.12 下相对和 0.65/1.32≈0.492 ≤ 0.5 并不违反相对形式，改用 0.40/0.30/0.20（均在网格内，0.90/1.57≈0.573 > 0.5）构造违反用例。
- **视图层线程语义**：GET 用 `sync_to_async(load_weight_config)()`（默认 thread_sensitive=True，与 Django async ORM 同线程）而非模块的 `aload_weight_config`（thread_sensitive=False 独立线程/独立 DB 连接）——后者留给 106-06 router 热路径；plan 文字「ORM/loader 调用走 sync_to_async」两种形态均满足，取与测试事务可见性和 ORM 语义一致者。
- **is_default 判定**：严格按行存在性（plan 原文），行存在但非法时 GET 返回默认值但 is_default=false。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - 门禁冲突] 验收 grep 与注释字面冲突**
- **Found during:** Task 1（acceptance criteria 自检）
- **Issue:** 模块 docstring/注释中「禁逐键 aget_setting」说明文字命中验收断言 `rg -c "aget_setting" == 0`（Pitfall 7 守护本意是禁调用）
- **Fix:** 改写为「禁逐键 aget」（plan action 原文用词），语义不变
- **Files modified:** server/codegraph/services/repo_router_config.py
- **Verification:** `rg -c "aget_setting"` 无匹配；33 条测试仍全绿
- **Committed in:** d5fe7acf

**2. [Rule 1 - Bug] GET 经 thread_sensitive=False 包装导致读不到未提交事务数据**
- **Found during:** Task 2（test_get_configured_returns_stored_values 首跑失败）
- **Issue:** 视图 GET 最初用 `aload_weight_config`（thread_sensitive=False）——独立线程持独立 DB 连接，测试事务内写入的行不可见（生产中亦意味着视图读与请求事务隔离，语义与 async ORM 不一致）
- **Fix:** 视图改用 `sync_to_async(load_weight_config)()`（默认 thread_sensitive=True），并加注释说明分工；`aload_*` 保留给 router 热路径
- **Files modified:** server/system/views.py
- **Verification:** 13 条端点测试全绿（含保存即生效链路）
- **Committed in:** b979324d

---

**Total deviations:** 2 auto-fixed（1 门禁冲突、1 线程语义 bug）
**Impact on plan:** 均为正确性/门禁一致性修正，无 scope creep；接口契约（exports/端点形态/校验口径）与 plan 完全一致。

## Issues Encountered

- **中断接续**：前执行器在 GREEN 实现中途中断（models.py + repo_router_config.py 未提交）。接续时先读现场——实现实际已完整，33 条 RED 测试直接全绿，按协议补 GREEN 提交后继续 Task 2，未重写任何已有代码。
- **pre-existing ruff E402**：plan verification 的 `ruff check system/views.py` 在 HEAD 版本即有 17 处 E402（既有中段 import 块，CI 将全量 ruff 视为 advisory baseline 不阻塞门禁）。本 plan 触碰的行零新增告警（其余 4 个文件 ruff 全绿）；已记入 deferred-items.md。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 106-04（nr_snapshot 写入）：`SettingKeys.REPO_ROUTER_NR_SNAPSHOT` 与 `load_nr_snapshot` 形状契约（`{"n_r_by_repo", "n_bar", "generated_at"}`，缺失/非法 → 空形状）已就位。
- 106-05（前端）：GET/PUT 契约定版——GET 返回配置全量 + `is_default`；PUT 400 返回 `{"detail", "errors": [...]}` 逐条中文错误可直接渲染。
- 106-06（router 消费）：`aload_weight_config` / `aload_nr_snapshot`（thread_sensitive=False）即取即用；`SettingKeys.REPO_ROUTER_ALIAS_DICT` 键已定版待消费。
- 校验口径纪律已固化在代码注释：不校验 Σw=1，网格 + INV-R2 相对形式 + 常数范围（CONTEXT 裁决字面依据）。

## Self-Check: PASSED

- FOUND: server/codegraph/services/repo_router_config.py
- FOUND: server/tests/codegraph/test_repo_router_config.py
- FOUND: server/tests/system/test_repo_router_weight_config.py
- FOUND: commit 4a5ef880（test，前执行器 RED）
- FOUND: commit d5fe7acf（feat，GREEN）
- FOUND: commit b979324d（feat，端点）

---
*Phase: 106-multi-signal-scoring*
*Completed: 2026-07-29*
