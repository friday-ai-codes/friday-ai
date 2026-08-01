---
phase: 111-schema
plan: 01
requirements: [SCHEMA-01, SCHEMA-06, SCHEMA-07]
provides:
  - "blueprint_schema.py：BLUEPRINT_SCHEMA_VERSION / BLUEPRINT_JSON_SCHEMA / validate_blueprint / iter_blocks / diff_blueprint_blocks"
  - "blueprint_execution.py：derive_execution_plan / derive_technical_plan_document / DEFAULT_BRANCH_STRATEGY"
  - "tests/helpers/blueprint_samples.py：make_blueprint 合法样例工厂（111-04 与 112/113 测试复用）"
affects:
  - "server/delivery/artifacts/builtin_types.py（blueprint/v1 判别分支——蓝图 content 落 ArtifactVersion 的唯一接线点）"
  - "Phase 112/113 装配流水线与 111-04 集成测试以本模块为契约源"
key-files:
  created:
    - server/services/process_runtime/blueprint_schema.py
    - server/services/process_runtime/blueprint_execution.py
    - server/tests/helpers/blueprint_samples.py
    - server/tests/services/test_blueprint_schema.py
    - server/tests/services/test_blueprint_execution.py
    - server/tests/delivery/test_blueprint_artifact_wiring.py
  modified:
    - server/delivery/artifacts/builtin_types.py
completed: 2026-07-29
---

# Phase 111 Plan 01: blueprint/v1 schema + block diff + execution_plan 派生器 Summary

**一行结论**：blueprint/v1 六段 jsonschema（Draft 2020-12 预编译 + 引用完整性后置检查 + v0 直通）、block 级三分类 diff、execution_plan 确定性派生器（remove→delete 映射、复用 validate_technical_plan 验收）全部落地，并经 builtin_types 判别分支接进 ArtifactService 强制入库门——蓝图 content 能且只能以合法形状落库，下游 coding dispatcher 零改动。

## Accomplishments

- **SCHEMA-01**：`BLUEPRINT_JSON_SCHEMA`（六段 + meta + requirement_spec + must_haves + citations 池，Block/Citation `$defs` 基元）+ `validate_blueprint`（jsonschema 结构 + 两项后置检查：块 citations id ∈ 文档级引用池、items[].feature_point_id ∈ feature_points[].id）。缺段/缺必填/坏枚举/坏引用全部拒绝并给出可读错误（`json_path: message`）；接进 `builtin_types._validate_technical_plan` 判别分支后成为 `ArtifactService.create/add_version` 的强制门（缺段 content 抛 `ArtifactContentInvalid`）。
- **SCHEMA-06**：`derive_execution_plan` 按 repository_id 聚合 items、跨仓 depends_on 投影仓级 dependencies、`(min wave, repository_id)` 确定性排序、五必填字段补齐（branch_strategy 默认 `feature`、repository_name 从 repo_associations 快照查表缺失回退 id）、files_touched **remove→delete 映射**；`derive_technical_plan_document` 输出经既有 `validate_technical_plan` 验收，同输入重复调用逐字节一致。
- **SCHEMA-07**：`iter_blocks` 确定性走查全部已知 Block[] 落位（section_path 点分 + `[id]` 索引，对齐 DESIGN §6.1 anchor 约定），`diff_blueprint_blocks` 按 block_id 对齐产出 added/removed/modified 三分类（sorted 确定性）；端到端测试覆盖「ArtifactVersion 版本链（v2 supersedes v1）+ diff 恰好命中被改 block」。
- **v0 零回归**：无 `schema_version` 的旧 MergedPlan 形状在 validate_blueprint 直通、在 builtin_types 走原 `validate_technical_plan` 路径；`test_artifact_service.py` 回归全绿，另补 v0 合法/非法双向断言。

## Task Commits

| Task | Commit | 内容 |
| ---- | ------ | ---- |
| 1 | `e0c4b7dd` | blueprint/v1 六段 jsonschema + 引用完整性校验 + iter_blocks + block 级 diff + 样例工厂 + 28 例测试 |
| 2 | `0f58b6eb` | execution_plan 确定性派生器（按仓聚合 + remove→delete + validate_technical_plan 验收）+ 10 例测试 |
| 3 | `449f1a5e` | builtin_types blueprint/v1 判别分支 + 落库接线测试 5 例（含 v0 回归） |

## Files

- `server/services/process_runtime/blueprint_schema.py`（新建，纯函数，stdlib + jsonschema，无 django/delivery import；模块级预编译 `Draft202012Validator`）
- `server/services/process_runtime/blueprint_execution.py`（新建，纯函数，顶层仅 import `validate_technical_plan`；无 `dict_to_technical_plan` 引用）
- `server/delivery/artifacts/builtin_types.py`（修改：`_validate_technical_plan` 加 schema_version 判别分支，函数内懒 import，只加分支不动注册逻辑）
- `server/tests/helpers/blueprint_samples.py`（新建：`make_blueprint` 工厂——2 direct + 1 indirect 仓、2 feature_points、2 items 含跨仓 depends_on/wave/remove 动作、citations 池 3 条）
- `server/tests/services/test_blueprint_schema.py`（28 例）/ `test_blueprint_execution.py`（10 例）/ `server/tests/delivery/test_blueprint_artifact_wiring.py`（5 例）

## Decisions

- iter_blocks 列表项 section_path 索引取标识字段（items→id、repo_associations/current_state_analysis→repository_id、affected_features→feature、steps→seq），缺失回退位置下标——保证任意半可信输入下路径仍可产出。
- diff 的 modified 判定用 `json.dumps(sort_keys=True, ensure_ascii=False)` canonical 序列化比对（与 ArtifactService content_hash 同一 canonical 思路）。
- `validate_blueprint` 对 `schema_version != "blueprint/v1"`（含缺失与未来版本号）一律 pass-through，判别收敛在 builtin_types 分支——未来 blueprint/v2 扩展时只改判别点。

## Deviations from Plan

None——plan 执行与书面一致。两处按 plan 内嵌指令完成的现场核实：

1. **v0 最小样例真实行为核实**（Task 3 指令③）：实测 `validate_technical_plan({"title":"t","summary":"s","execution_plan":[]})` 返回 `(True, None)`（schema 对 execution_plan 无 minItems），据此固化「v0 最小样例创建成功」断言，并补一条 v0 非法样例（缺 execution_plan）仍被拒的反向断言。
2. **空 items 派生行为**（Task 2 测试⑦）：空 execution_plan 数组过 validate_technical_plan（无 minItems 约束），断言 `derive_technical_plan_document` 返回 `(doc, None)` 且 `doc["execution_plan"] == []`。

## 测试与验证

- `tests/services/test_blueprint_schema.py`：28 passed
- `tests/services/test_blueprint_execution.py`：10 passed
- `tests/delivery/test_blueprint_artifact_wiring.py` + `test_artifact_service.py`（回归）：12 passed
- 三文件组合 verification 套件：43 passed（见 Self-Check）
- 冻结面自检：三个 commit 触及文件 = plan files_modified 七文件，`repo_router_v2 / decompose_segments / research_adapter / architect_merge_adapter / merged_plan / clarify_adapter / render / technical_plan` 零命中
- 观测面：本 plan 全部为纯函数模块与校验分支，无 IO/生命周期事件，按 LOGGING-SPEC「高频循环禁 INFO」不加日志（与 merged_plan.py / wave_layering.py 同范式）；落库观测沿用 ArtifactService 既有 `artifact_created`（caller）事件

> 环境备注：同 worktree 有并行 executor 同时跑 pytest，本计划测试墙钟时间被 CPU 竞争拉长（单跑 <60s），结果不受影响。

## Next Phase Readiness

- 111-04 集成测试可直接复用 `make_blueprint` 与 `validate_blueprint`/`diff_blueprint_blocks` 导出面。
- Phase 112/113 装配流水线的契约源就位：装配产物过 `validate_blueprint` 即可经 ArtifactService 落库；confirmed 后调 `derive_technical_plan_document` 得到 dispatcher 可消费文档。
- 114 重锚定与 115 渲染消费 `iter_blocks` 的 section_path 约定（点分 + `[id]`），已有测试锁形状。
