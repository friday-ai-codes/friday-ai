---
phase: 13-ingest
plan: 13-04
status: complete
subsystem: knowledge
requirements_addressed: [INGEST-07, INGEST-06]
tags: [reconcile, rebuild, drift-detection, idempotency, ops-command]
dependency_graph:
  requires:
    - server/knowledge/ingestion.py (revectorize_version / apply_edge_specs / IngestionRequest——13-02 产物)
    - server/knowledge/vector_ops.py (tombstone_points / delete_points——13-02 产物)
    - server/knowledge/graph_store.py (neighbors——检查项 6 边检测)
    - server/knowledge/sources/ (get_normalizer 惰性注册表——检查项 6 --fix 补边)
    - server/code_relations/management/commands/verify_payload_consistency.py (命令范式 exact analog)
  provides:
    - "manage.py reconcile_delivery_knowledge：六检查项对账（5 类 DB↔Qdrant 漂移 + HAS_PLAN 边一致性；dry-run 默认 + --fix + --limit）"
    - "rebuild_delivery_knowledge --yes 扩展：删建后从 PG latest 全量重嵌入，返回 (dimension, reembedded, failed)"
    - "tests/knowledge/test_reconcile.py：漂移注入 → 检测/修复 9 用例回归资产"
  affects:
    - Phase 15（检索面正确性由本命令兜底保障）
    - 运维 runbook（漂移修复 / 灾备重建 / 维度变更统一入口）
tech_stack:
  added: []
  patterns:
    - "修复动作经模块属性调用（ingestion.revectorize_version / vector_ops.tombstone_points）——monkeypatch 模块属性即可拦截全部写路径，测试零真实 Qdrant"
    - "两级异常隔离：单 entity/version 检查 try/except + 检查项级 try/except，skip 计数 + knowledge_reconcile_item_skipped warning，残缺数据下命令完整跑完"
key_files:
  created:
    - server/knowledge/management/commands/reconcile_delivery_knowledge.py
  modified:
    - server/knowledge/management/commands/rebuild_delivery_knowledge.py
    - server/tests/knowledge/test_reconcile.py
decisions:
  - "Summary 行键集合锁定为 checked/missing/stale_latest/multi_latest/orphans/db_anomalies/missing_edges/skipped/fixed——test_reconcile 以解析断言钉死，后续改动即测试失败"
  - "检查项 6 --fix 经 entity.source_kind 泛化取 normalizer（非硬编码 mcp_technical_plan）：未来新增带边 source 自动获得兜底，KeyError 时 skip+warning"
  - "检查项 3 多 latest 修复按 DB 真值 tombstone 非 latest 点；DB 无 latest 真值（孤儿族）时 skip 交检查项 4 处理，禁止反向按 Qdrant 改 DB"
  - "--limit 只作用于 DB 侧迭代检查（1/2/6）；scroll 类检查（3/4）按召回面全量遍历"
metrics:
  duration: ~12min
  tasks: 3
  files: 3
  completed: 2026-06-11
---

# Phase 13 Plan 04: reconcile 对账命令与 rebuild 全量重嵌入 Summary

`reconcile_delivery_knowledge` 六检查项对账命令（dry-run 默认 + --fix opt-in）闭环六步摄取序步 3–5 的全部失败后果（含 Pitfall 2 短路掩盖向量缺失与 tombstone 失败残留），`rebuild_delivery_knowledge` 消化 Phase 12 TODO 锚点实现从 PG latest 全量重嵌入——INGEST-07"幂等可验证的运维闭环"收口。

## 任务执行情况

| Task | 内容 | Commits |
|------|------|---------|
| 1 | reconcile 命令（六检查项）+ 检测/dry-run/skip 三用例（TDD） | 116188d7 (RED), b6730f84 (GREEN) |
| 2 | rebuild 全量重嵌入扩展（消化 TODO 锚点）+ 2 个 rebuild 用例 | 998c9e3b |
| 3 | --fix 修复路径调用参数级断言补全（4 用例） | 5bb4112d |

## 验收对照（must_haves truths）

- ✅ 默认 dry-run：六检查项输出每项一行计数 + `Summary: checked=N missing=N stale_latest=N multi_latest=N orphans=N db_anomalies=N missing_edges=N skipped=N fixed=N`；漂移注入下四类修复 mock 零调用、Qdrant 零写副作用
- ✅ --fix：missing → `revectorize_version` 重嵌入（不重走版本翻转）；stale → `tombstone_points` + `delete_points`；orphan → `delete_points`；missing_edges → `get_normalizer` 重建事件取 EdgeSpec 后 `apply_edge_specs` 补建（全部调用参数级断言，point id 列表逐项比对）
- ✅ 单点异常 skip 不崩：retrieve 抛错 → skipped ≥ 1，命令完整跑完退出码 0；检查项级失败（scroll 整体挂）同样隔离
- ✅ `rebuild --yes`：删建后 `filter(is_latest=True)` 逐版本 `revectorize_version`（2 latest → 2 次调用，非 latest 不进入）；单版本失败 error 记录后继续，`reembedded=N failed=N` 出现在输出

验收 grep：`rg "delete\(.*Filter|FilterSelector" reconcile_delivery_knowledge.py` 零命中（修复删点只按 point id 列表，P1）；`rg "TODO" rebuild_delivery_knowledge.py` 零命中（锚点已消化）。

## Deviations from Plan

### 说明

**1. [流程] Task 3 按 test-only 任务执行（无独立 RED/GREEN 循环）**
- **原因：** Task 1 GREEN 已按计划完整实现 --fix 分支（计划 Task 1 action 明示六检查项含 --fix 动作），Task 3 的交付物本身就是回归断言——测试对既有实现直接通过是预期行为，非"RED 意外通过"信号
- **Commit:** 5bb4112d（`test(13-04)` 单 commit）

**2. [Rule 3 - lint] RED 测试文件一处未用 import 与 ruff format 漂移**
- **Found during:** Task 1 GREEN 验证
- **Fix:** 移除提前引入的 `timezone` import（Task 3 需要时再加回）+ `ruff format`，与命令实现同 commit（b6730f84）

其余按计划逐字执行。

## 实现要点

- **六检查项序**：1 latest 向量完整性（含空 point_ids 残骸）→ 2 非 latest 残留 → 3 召回面多 latest（scroll filter is_latest=true 按 entity 聚合）→ 4 孤儿点（payload version_id 不在 PG，含非法/空 version_id）→ 5 DB 不变量 report-only（多 latest / invalid_at<=valid_at / unsynced latest 三分项输出）→ 6 HAS_PLAN 入边对账（`graph_store.neighbors(direction="in")`）。
- **修复单向性**：对账以 DB 为真值，全部修复动作只写 Qdrant / 补边，零反向改 DB 路径；检查项 5 恒不 fix。
- **rebuild 失败提示**：failed > 0 时输出 WARNING 指引 `reconcile_delivery_knowledge --fix` 补救（两命令形成闭环）。
- **structlog 始末事件**：`knowledge_reconcile_started/finished`（finished 带全部计数）、`rebuild_delivery_knowledge_started/finished`（finished 带 reembedded/failed）。

## Known Stubs

None — 命令、扩展、9 个测试用例全部真实实现，无占位数据流。

## Threat Flags

None — 未新增计划 threat_model 之外的安全面：T-13-03（dry-run 默认 + 检查项 2/6 检出修复测试）、T-13-02（--fix 重嵌入复用 revectorize_version → build_knowledge_points schema 收口）、T-13-04（命令只读 ORM + 调公开函数，零 raw SQL，grep 验收通过）均按计划 mitigate。

## 验证结果

- `uv run pytest tests/knowledge/test_reconcile.py -x` → 9 passed
- `uv run pytest tests/knowledge/ -x` → 122 passed（含 test_collection.py rebuild 用例零回归）
- `uv run python manage.py makemigrations --check --dry-run` → No changes detected
- `ruff check` / `ruff format --check` 全部通过

## Self-Check: PASSED

- 3 个产物文件全部存在（reconcile_delivery_knowledge.py / rebuild_delivery_knowledge.py / tests/knowledge/test_reconcile.py）
- 4 个 commit（116188d7, b6730f84, 998c9e3b, 5bb4112d）全部在 git log 中
- tests/knowledge/ → 122 passed；makemigrations --check 干净
