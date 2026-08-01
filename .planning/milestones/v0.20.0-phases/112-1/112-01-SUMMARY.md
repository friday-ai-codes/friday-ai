---
phase: 112-1
plan: 01
requirements: [FLOW-01, CHARTER-02]
provides:
  - "blueprint_schema.py：feature_points[].intent 必填枚举（greenfield / brownfield / fix），schema 层强制"
  - "SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG = \"blueprint.spec_gate.config\"（JSON {threshold, weights{goal,boundary,constraint,acceptance}}，默认阈值 0.20 + 0.30/0.25/0.20/0.25）"
  - "SettingKeys.BLUEPRINT_ROUTE_WEIGHTS = \"blueprint.route.weights\"（JSON {<intent>: {router_base, charter_match, history_match}}，默认 greenfield 0.40/0.35/0.25、brownfield 0.60/0.20/0.20、fix 0.70/0.15/0.15）"
  - "settings_service.aget_float_setting / aget_json_setting（async 版，语义镜像同步版，不走 60s 缓存）"
  - "event_taxonomy：112 的 11 个 blueprint_* 阶段事件常量（spec_gate 3 / route 1 / repo_research 3 / reroute 1 / confirmation 3），全部在 BLUEPRINT_EVENTS 内"
  - "tests/helpers/blueprint_samples.py：make_blueprint 产物带 intent（fp_01 greenfield / fp_02 brownfield）"
  - "tests/fixtures/blueprint_golden/gaokao_boost.json：三条 fp intent = brownfield / greenfield / greenfield（112-03/04 路由加权断言的期望依据）"
affects:
  - "112-02（spec_gate）消费 BLUEPRINT_SPEC_GATE_CONFIG + aget_json_setting + spec_gate 三事件常量"
  - "112-03（route）消费 feature_points[].intent + BLUEPRINT_ROUTE_WEIGHTS + blueprint.route.scored"
  - "112-04（repo_research / reroute）与 112-05（确认门）消费对应事件常量，无需再改 event_taxonomy.py"
  - "既有 6 个蓝图消费测试与 evaluate_blueprint_golden command（schema 破坏性演进后零改动通过）"
key-files:
  created:
    - server/tests/test_blueprint_settings.py
    - server/tests/delivery/test_blueprint_event_taxonomy_112.py
  modified:
    - server/services/process_runtime/blueprint_schema.py
    - server/tests/helpers/blueprint_samples.py
    - server/tests/fixtures/blueprint_golden/gaokao_boost.json
    - server/tests/services/test_blueprint_schema.py
    - server/system/models.py
    - server/system/settings_service.py
    - server/delivery/services/event_taxonomy.py
completed: 2026-07-30
---

# Phase 112-1 Plan 01: 地基改动（intent 枚举 + 运行时配置键 + 事件常量）Summary

**一行结论**：`feature_points[].intent` 成为 schema 层必填枚举（缺失与非法值均被 `validate_blueprint` 拒绝，三合法值正向覆盖），两份字面数据同步后 6 个既有蓝图消费测试与 golden command 零改动全绿；`blueprint.spec_gate.config` / `blueprint.route.weights` 两个点分键注册完成并补齐 `aget_float_setting` / `aget_json_setting`（既有 8 个 getter 逐字未动）；112 的 11 个阶段事件常量一次注册进 `BLUEPRINT_EVENTS`（与 `ALL_EVENTS` 互斥）——wave 2 的 spec_gate 与 route 可并行开工且不再写同一文件。

## Accomplishments

- **FLOW-01 前置（intent 强制）**：`feature_points.items.required` 加 `intent`，`properties` 内 `title` 之后插入 `enum: [greenfield, brownfield, fix]`（白名单在 schema 内，非手写判断 → T-112-01 mitigate）。`requirement_spec.required`、`additionalProperties` 默认策略、id 唯一性后置检查、`items[].feature_point_id` 解析检查、`iter_blocks` 全部零改动。三条行为断言锁死演进：缺 intent 被拒 / `"refactor"` 被拒 / 三合法值通过（参数化）。
- **数据同步 2 文件**：`blueprint_samples.py` 两条 fp 取 `greenfield`（后端接口净新增）/ `brownfield`（前端入口改造）——工厂天然覆盖两个枚举分支；`gaokao_boost.json` 三条 fp 取 `brownfield`（`:42` 自述改造）/ `greenfield`（`:55` 自述净新增）/ `greenfield`（新增组卷能力），即 112-03/04 路由加权断言的期望依据。
- **6 文件回归零改动**：`test_blueprint_execution` / `test_blueprint_quality` / `test_blueprint_artifact_wiring` / `test_evaluate_blueprint_golden` / `test_blueprint_integration` / `test_blueprint_schema` 全绿，且前 5 个文件 `git diff --stat` 为空（未靠改断言"适配"）；`evaluate_blueprint_golden` 退出码 0，`target_repo_hit_rate=1.0`、`citation_coverage=1.0`。
- **CHARTER-02 前置（配置外置）**：`SettingKeys` 尾部按既有三段式注释（JSON 形状 / 默认值 / 消费方）追加两键，无 migration（`makemigrations --check` 退出码 0）。`settings_service` **只新增** `aget_float_setting` / `aget_json_setting`——`git diff` 无任何删除行，既有 8 个 getter 行为与签名逐字未变。畸形配置逐项回默认（非 JSON / 顶层 list / 空字符串三例，同步与 async 各一组，绝不抛 → T-112-02 mitigate）。
- **事件常量前置**：11 个 `Final[str]` 点分三段常量 + 每个上方一行中文注释写清 emit 点所属 plan 与 payload 关键键，且显式注明「payload 只记标量与关联键，澄清/需求正文不进 payload」（T-112-04 mitigate）。既有 4 个常量、`ALL_EVENTS`、其它事件段一字不动；`test_event_taxonomy_alignment` 的覆盖性反查未被打破（`-k taxonomy` 8 passed）。

## Task Commits

| Task | Commit | 内容 |
| ---- | ------ | ---- |
| 1 | `5d4c25c0` | feature_points 补必填枚举 intent + blueprint_samples / gaokao_boost 字面数据同步 + 3 条正负向 schema 断言 |
| 2 | `b72fb286` | 6 文件回归 + golden command 门通过；SettingKeys 两个点分键 + aget_float/json_setting + 17 例设置测试 |
| 3 | `1ad212b4` | event_taxonomy 追加 11 个 112 阶段事件常量（进 BLUEPRINT_EVENTS 与 `__all__`）+ 5 例常量守护测试 |

## Files

- `server/services/process_runtime/blueprint_schema.py`（修改：只动 `feature_points.items.required` 数组与 `properties` 字典，其余 schema 段与三处后置检查零改动）
- `server/tests/helpers/blueprint_samples.py`（修改：两条 fp 各补 intent + docstring 字段说明同步；`make_blueprint` 签名与 deepcopy 语义未变）
- `server/tests/fixtures/blueprint_golden/gaokao_boost.json`（修改：三条 fp 各补 intent，缩进沿用原文件）
- `server/tests/services/test_blueprint_schema.py`（修改：+3 个测试函数 → 43 passed）
- `server/system/models.py`（修改：`SettingKeys` 尾部追加两个常量 + 三段式注释；既有键一个未改）
- `server/system/settings_service.py`（修改：`aget_int_setting` 之后新增两个 async getter，纯追加）
- `server/delivery/services/event_taxonomy.py`（修改：blueprint 区段追加 11 常量 + `BLUEPRINT_EVENTS` / `__all__` 同步；`ALL_EVENTS` 与既有 4 常量未动）
- `server/tests/test_blueprint_settings.py`（新建，17 例：缺键回默认 / 合法值生效 / 畸形三例降级 / aget_float 三例 / 两键互不干扰，同步 + async 双路径）
- `server/tests/delivery/test_blueprint_event_taxonomy_112.py`（新建，5 例：字面值契约 / 入 BLUEPRINT_EVENTS / 与 ALL_EVENTS 互斥 / 既有 4 常量冻结 / 集合恰 15 且全 `blueprint.` 前缀无重复）

## Decisions

- `blueprint_samples.py` 的 fp_02 取 `brownfield` 而非 RESEARCH 3.4 第 2 步给的 `greenfield`：按 PLAN Task 1 指令，让工厂天然覆盖两个枚举分支（RESEARCH 已核查无断言依赖 fp_02 字段集，实测 6 文件回归全绿）。
- 新键不加 `signal`：阈值/权重读取频率低，同步路径 60s 缓存足够，async 路径按 `aget_*` 既有约定每次打 DB（写入即生效，无缓存滞后）。
- `test_blueprint_settings.py` 的默认值形状（`_DEFAULT_SPEC_GATE` / `_DEFAULT_ROUTE_WEIGHTS`）只作测试内"传入默认"快照，**不**在本 plan 建立生产默认常量——默认常量归 112-02 / 112-03 的 loader 模块（PATTERNS 第 8 类：配置对象与纯函数判定分离）。
- 事件常量未加进 `delivery/services/__init__.py` 的再导出面：既有 4 个 blueprint 常量同样只从 `event_taxonomy` 模块直接导入，保持一致（`__init__.py` 仅导出 `ALL_EVENTS` / `RESERVED_EVENTS` / `build_envelope`）。

## Deviations from Plan

共 2 处，均为按现实修正的断言口径，无功能偏差。

**1. [Rule 1 - 事实修正] `validate_blueprint` 返回签名是 `(bool, str | None)`，非 plan 写的 `(bool, errors列表)`**

- **Found during:** Task 1
- **Issue:** PLAN Task 1 ④ 描述断言为「返回 `(False, errors)` 且 errors 非空」「三个合法值均返回 `(True, [])`」，但 `blueprint_schema.validate_blueprint` 实际返回 `tuple[bool, str | None]`（成功 `(True, None)`，失败为单条已脱敏截断的字符串）。
- **Fix:** 断言改为与既有 40 条测试同口径——负向 `assert ok is False` + `assert "intent" in (err or "")` / `assert err`；正向 `assert (ok, err) == (True, None)`。行为验收（缺失被拒 / 非法被拒 / 三合法通过）与 PLAN 意图完全一致。
- **Files modified:** `server/tests/services/test_blueprint_schema.py`
- **Commit:** `5d4c25c0`

**2. [Rule 3 - 前提不成立] `blueprint_schema.py` 模块 docstring 未逐字列 feature_point 字段形状，故未改**

- **Found during:** Task 1
- **Issue:** PLAN Task 1 ①第三条要求「模块 docstring 若逐字列了 feature_point 字段形状，同步补 intent」。实读 docstring（`:1-20`）只描述六段骨架与五项后置检查，未列 feature_point 字段集。
- **Fix:** 该条为条件式指令，条件不成立 → 不改（避免无意义扰动冻结度高的模块头）。`blueprint_samples.py:3-12` docstring 确实逐字列了字段说明，已按 PLAN ② 同步补 intent 说明。
- **Files modified:** 无
- **Commit:** —

## 测试与验证

- `tests/services/test_blueprint_schema.py`：43 passed（+3 新增）
- `tests/test_blueprint_settings.py`：17 passed（新建）
- `tests/delivery/test_blueprint_event_taxonomy_112.py`：5 passed（新建）
- **6 个消费测试回归全绿且零改动**：`test_blueprint_execution` / `test_blueprint_quality` / `test_blueprint_artifact_wiring` / `test_evaluate_blueprint_golden` / `test_blueprint_integration` / `test_blueprint_schema` 合计 86 passed；`git diff --stat` 对前 5 个文件输出为空
- PLAN verification 全套 8 文件：**108 passed**
- `uv run python manage.py evaluate_blueprint_golden`：退出码 0（gaokao_boost 过 validate_blueprint 门，passed=1 / failed=0）
- `uv run python manage.py makemigrations --check --dry-run`：退出码 0（SettingKeys 纯常量无 migration）
- `uv run pytest tests/delivery/ -q -k taxonomy`：8 passed（既有覆盖性反查未被新常量打破）
- 冻结面自检：三 commit 触及 9 文件 = PLAN `files_modified` 全集；`repo_router_v2 / decompose_segments / research_adapter / architect_merge_adapter / merged_plan / clarify_adapter / render / resume / builtin_processes` 零命中
- `git diff HEAD~3 HEAD -- server/system/settings_service.py` 无任何删除行（既有 getter 逐字未动）
- 观测面：本 plan 产出为 schema 常量、纯常量事件表、settings getter（getter 已 fail-safe 吞异常，按 LOGGING-SPEC 不在高频读取路径打日志，与既有 8 个 getter 同范式）；11 个事件常量的 emit 点与 `category`/`component` 埋点归 112-02–05 落地，注释已前置约束 payload 只记标量与关联键
- 代码风格：改动文件全部经 `uv run ruff format` + `uv run ruff check --fix`，All checks passed

## Self-Check: PASSED

- 文件存在：9 个 `files_modified` 全部命中（2 新建 + 7 修改）
- commit 存在：`5d4c25c0` / `b72fb286` / `1ad212b4` 均在 `git log`
- artifacts contains 断言：`"greenfield"` ∈ blueprint_schema.py ✓；`blueprint.spec_gate.config` ∈ models.py ✓；`async def aget_json_setting` ∈ settings_service.py ✓；`blueprint.route.scored` ∈ event_taxonomy.py ✓；`"intent"` ×3 ∈ gaokao_boost.json ✓
- key_links 断言：`"intent"` ×2 ∈ blueprint_samples.py ✓；`aget_float_setting|aget_json_setting` ∈ settings_service.py ✓

## Next Phase Readiness

- **112-02（spec_gate）**：`SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG` + `aget_json_setting` 就位，默认值形状见本 SUMMARY provides；三个 spec_gate 事件常量可直接 import。loader 需按 PATTERNS 第 8 类做逐字段 `float()` 强转与 clamp（本 plan 只保证「非 dict / 解析失败回默认」这一层）。
- **112-03（route）**：`feature_point["intent"]` 现为 schema 保证存在的枚举值（无需 `None` 分支）；`BLUEPRINT_ROUTE_WEIGHTS` 默认三档权重已在 models.py 注释固化；`blueprint.route.scored` 常量就位。
- **112-04 / 112-05**：repo_research 3 事件 + reroute 1 + confirmation 3 全部注册完毕，两个 plan 均无需再改 `event_taxonomy.py`（消除 wave 2/3 写冲突）。
- **golden fixture**：`gaokao_boost.json` 三条 intent 分布（brownfield / greenfield / greenfield）是 112-03/04 路由加权断言的期望依据——greenfield 功能点重章程，`onion-learning` 应凭 `owned_domains(status=planned)` 进候选。
