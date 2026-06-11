---
phase: 13-ingest
plan: 13-02
status: complete
subsystem: knowledge
requirements_addressed: [INGEST-06, INGEST-07, INGEST-08]
tags: [ingestion, versioning, idempotency, on-commit, graph-edges]
dependency_graph:
  requires:
    - server/knowledge/models.py (generate_entity_id, 三约束语义, vector_synced)
    - server/knowledge/graph_store.py (add_edge / invalidate_edge / neighbors, _require_aware)
    - server/knowledge/chunking.py + vector_ops.py (13-01 产物全部公开符号)
    - server/knowledge/collection.py (ensure_delivery_knowledge_collection, get_embedding_model_name)
    - server/services/background_runner.py (run_in_background factory 契约)
  provides:
    - "IngestionRequest(source_kind, source_id, trigger)：触发点唯一构造的最小定位 DTO（frozen）"
    - "EdgeSpec(relation, target_entity_id, exclusive=False)：出边规格（exclusive=同 relation 单 target 语义）"
    - "IngestionEvent(kind, origin, source_kind, source_id, title, content, payload, project_id, repository_id, event_time, edges=())：normalizer 统一事件 DTO"
    - "aschedule_ingestion(request)：触发点唯一入口——sync_to_async 包裹 on_commit 注册 + run_in_background factory 投递，顶层异常全吞（A1 已测试钉死）"
    - "ingest(request)：后台执行体（get_normalizer → normalize → ingest_events；空事件 warning no-op）"
    - "ingest_events(events, *, trigger='')：六步序核心（阶段 A 持久化 → 阶段 B 边 → 阶段 C 向量序）"
    - "apply_edge_specs(entity_id, edges, *, event_time)：边阶段公开函数（幂等可重入，13-04 reconcile 检查项 6 --fix 复用）"
    - "revectorize_version(version)：单版本补写向量（needs_revector / reconcile --fix / rebuild 复用；point ids 为空时确定性派生回写）"
    - "get_normalizer(source_kind)（knowledge/sources/__init__.py）：惰性注册表，未知 kind raise KeyError"
  affects:
    - 13-03（触发点接线 + coding_plan/mcp_plan normalizer 模块——注册表路径已登记）
    - 13-04（reconcile 复用 apply_edge_specs / revectorize_version / vector_synced 语义）
tech_stack:
  added: []
  patterns:
    - "async 触发点注册 on_commit 的唯一正确写法：await sync_to_async(_register)()（thread_sensitive 与 ORM 同线程；autocommit 立即投递 / atomic 延迟 / rollback 丢弃）"
    - "_persist_sync 三态判定（skipped / needs_revector / 翻转）互斥，权威判定在 select_for_update 锁内；embed 前另有无锁预短路"
key_files:
  created:
    - server/knowledge/ingestion.py
    - server/knowledge/sources/__init__.py
    - server/tests/knowledge/test_ingestion.py
  modified: []
decisions:
  - "OQ-1 措辞映射（规划定案）：REQUIREMENTS'旧边写 expired_at'实现为 graph_store.invalidate_edge 置位 invalid_at（业务时间线失效）——版本替代是业务失效而非记录纠错；模块 docstring 已记录供 verify-work 对照"
  - "边非严格同事务（规划定案）：边操作在 _persist_sync 之后经 graph_store 原语异步执行；恢复三层保障 = uniq_kedge_active 幂等可重入 + skipped/needs_revector 仍执行边阶段（自愈，已测试）+ 13-04 reconcile 兜底"
  - "INGEST-07 铁律落地：hash 相等绝不产生新版本——needs_revector 分支不建版本行、不置 invalid_at，仅 revectorize_version 补写向量（crash 恢复用例钉死）"
  - "tombstone 失败 catch + knowledge_ingest_tombstone_failed error 不再上抛：DB is_latest 翻转已是第一道防线（chaos 用例钉死）"
metrics:
  duration: ~12min
  tasks: 2
  files: 3
  completed: 2026-06-11
---

# Phase 13 Plan 02: 统一摄取核心 Summary

交付 Phase 13 状态机心脏：`aschedule_ingestion` 触发点唯一入口（async on_commit + background runner，A1 首验闭环）+ `ingest_events` 六步版本翻转事务序（三态幂等判定 + 边精细置位 + upsert→tombstone→delete 向量序），13-03 触发点与 13-04 对账只消费本层。

## 任务执行情况

| Task | 内容 | Commits |
|------|------|---------|
| 1 | DTO + 调度层（aschedule_ingestion）+ sources 惰性注册表 | dbbdf0a0 (RED), 31060679 (GREEN) |
| 2 | ingest 执行体六步序 + 三态幂等 + 边精细置位 | a3110586 (RED), 8d000f2e (GREEN) |

## 验收对照（must_haves truths）

- ✅ 幂等三连发：3 次 `ingest_events` → 1 实体 1 版本，Qdrant upsert 仅 1 次（`test_ingest_idempotent_triple_fire`；预短路另有 `generate_embeddings_batch` 零新增调用断言）
- ✅ hash 相同 + vector_synced=False 重摄：零新版本行、无 invalid_at 置位、revectorize 被调、vector_synced 回 True（`test_crash_recovery_same_hash_unsynced_revectorizes`）
- ✅ 内容变更重摄：v2 latest supersedes=v1，v1 is_latest=False + invalid_at 置位，旧 point ids 按 upsert→tombstone→delete 序处理（`test_version_flip_on_content_change` 调用序断言）
- ✅ 向量步任一失败不破坏 DB：delete 失败不崩 / tombstone 失败 error 响亮且翻转生效 / upsert 失败 v2 落库 vector_synced=False（三个 chaos 用例）
- ✅ aschedule_ingestion：rollback 不投递、autocommit 立即投递、异常全吞 warning（A1 首验三用例）
- ✅ embedding 含 None：整体 raise，DB / Qdrant 零写入（`test_embedding_none_aborts_with_zero_writes`）

验收 grep：`sync_to_async(_register)` 命中、`run_in_background(lambda` 命中；`invalidate_entity_version` 与 `KnowledgeEdge.objects` 在 ingestion.py 零命中（边写只走 graph_store 收口）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - 格式] on_commit 投递行重排为单行以满足验收 grep**
- **Found during:** Task 1 验收
- **Issue:** ruff format 将 `run_in_background(` 折行后 `rg "run_in_background\(lambda"` 不命中
- **Fix:** task_name 预先取值，投递 lambda 收为单行
- **Commit:** 31060679

**2. [Rule 3 - 验收冲突] 模块 docstring 避开 `invalidate_entity_version` 字面量**
- **Found during:** Task 2 验收
- **Issue:** 规划定案 3 的 docstring 提及该原语名，与"零命中"grep 验收冲突
- **Fix:** 改述为"实体作废级联原语"，语义不变
- **Commit:** 8d000f2e

其余按计划逐字执行（含 Task 1 为调度层 factory 预留的 `ingest` 签名占位，Task 2 替换为真实实现）。

## 实现要点

- **三态互斥**：`_PersistResult(entity, version, point_ids, old_point_ids, skipped, needs_revector)` frozen dataclass；`version` 仅在并发 IntegrityError 病理路径可能为 None。
- **预短路 vs 权威判定**：embed 前无锁预读（省远程 embedding 费用），`_persist_sync` 锁内重新判定为权威——两层判定条件一致（hash 相同 AND vector_synced）。
- **多事件批两阶段**：阶段 A 先持久化全部实体/版本，阶段 B 统一处理边（保证 EdgeSpec 两端实体已存在，规划定案 4）。
- **exclusive 边语义**：先 `neighbors(direction="out")` 查活跃出边——同 target 复用跳过；exclusive 时其他 target 逐条 `invalidate_edge`；`add_edge` 撞 `uniq_kedge_active` 视为并发已建幂等放弃。
- **revectorize_version** 复用 `version.qdrant_point_ids`，数量与 chunks 不符时按 `derive_point_ids` 派生回写——同时覆盖 13-04 rebuild 全量重嵌入场景。

## Known Stubs

- `knowledge/sources/__init__.py` 注册表登记的 `knowledge.sources.coding_plan` / `knowledge.sources.mcp_plan` 模块尚不存在——**有意为之**，由 Plan 13-03 落地（本 plan 测试用 monkeypatch 注入 fake normalizer）；在模块落地前调用 `get_normalizer` 会 ImportError 响亮失败，不会静默。

## Threat Flags

None — 未新增计划 threat_model 之外的安全面：T-13-03（向量序防线）/ T-13-02（payload 键集合）/ T-13-04（graph_store 收口）均按计划 mitigate 并有对应测试；无新端点 / 认证路径 / 文件访问。

## 验证结果

- `uv run pytest tests/knowledge/` → 100 passed（既有 80 用例零回归 + 新增 20）
- `manage.py makemigrations --check --dry-run` → 无变更（退出码 0）
- `ruff check knowledge/ tests/knowledge/` → All checks passed；`ruff format --check` 通过
- 验收 grep 全部按预期（命中 2 项 / 零命中 2 项）

## Self-Check: PASSED

- 4 个产物文件全部存在（ingestion.py / sources/__init__.py / test_ingestion.py / SUMMARY）
- 4 个 commit（dbbdf0a0, 31060679, a3110586, 8d000f2e）全部在 git log 中
- tests/knowledge/ 100 passed；makemigrations --check 退出码 0
