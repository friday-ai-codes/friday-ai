---
phase: 13-ingest
verified: 2026-06-11T14:40:00Z
reverified: 2026-06-11T14:52:00Z
status: passed
score: 23/23 must-haves verified
overrides_applied: 0
deferred:
  - truth: "INGEST-08 文本类型全集（需求/方案/PRD/diff）中 diff 类知识文本可摄取"
    addressed_in: "Phase 14"
    evidence: "Phase 14 success criteria 2/5：编码完成回调拉取全量 diff 归档落库并摄取 code_change 实体；万行级大 diff 分层切块。REQUIREMENTS.md 据此将 INGEST-08 标记 Pending 属预期"
human_verification: []
---

# Phase 13: 统一摄取与版本化 Verification Report

**Phase Goal:** 知识摄取成为业务流程的自动副产品——幂等、异步、版本化，检索面始终只见最新版；以 chat 与 MCP 两个形态最稳定的触发点验证管线
**Verified:** 2026-06-11T14:40:00Z
**Status:** passed（初验 human_needed；真实 Qdrant E2E 实跑闭环后复核通过）
**Re-verification:** Yes — orchestrator 以真实 Qdrant 实例（本机 dev 容器）+ 确定性 mock embedding 实跑端到端摄取脚本：
1. 首次摄取 → `delivery_knowledge` 出现 hybrid（dense+sparse named vectors）点位，payload 14 键完整携带（含 8 个 schema 索引字段）✓
2. 修改后重摄取 → 新版本 v2 入库、旧版本 is_latest 翻转 + invalid_at 置位、旧点物理删除，检索面只见最新版 ✓

**E2E 实跑发现并修复的真实缺陷（commit a010567e）：** `ensure_delivery_knowledge_collection` / `tombstone_points` / `delete_points` 在 async 上下文直接调用 `QdrantService.get_client()`，首次初始化经 `_get_config_sync` 读 SystemSetting（sync ORM）→ `SynchronousOnlyOperation` 崩溃。测试套件因 mock get_client 永远不会覆盖此路径——已改为 `await sync_to_async(QdrantService.get_client)()`，knowledge 套件 124 passed 复跑确认零回归。这正是 Manual-Only 项存在的价值。

**附带观察（非 gap）：** 同一实体两次摄取若 event_time 完全相同会触发 `kversion_valid_range` 约束并按既有"concurrent_conflict"路径吞为 warning（无新版本）——真实触发点用 now() 取时间，微秒精度下实际不可达；如未来需要可在 normalizer 层做单调时间保证。

## Goal Achievement

### Observable Truths — ROADMAP Success Criteria（合同级）

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | chat 产出 CodingPlan / 触发编码时自动入图入向量，对话原文不入图，零手动操作 | ✓ VERIFIED | `chat/models.py:281,298`、`coding_session_service.py:589` 三锚点接线在位（HEAD 实测）；`sources/coding_plan.py` content 仅 title+tech_plan，`rg "conversation\.messages|Message"` 零命中；`test_triggers.py` 特征串 `_SENTINEL` 断言（L31）+ chat 投递 7 用例通过 |
| 2 | MCP 工具链产出方案/执行编码时自动摄取 | ✓ VERIFIED | `technical_plan_service.py:528`（mcp_plan_created）、`work_item_execution_service.py:601`（mcp_tasks_executed）接线在位；`test_triggers.py -k mcp` 4 用例通过 |
| 3 | 修改后重摄取为新版本：新向量入库、旧向量下线（is_latest 翻转兜底 + 物理删除）、旧边失效、检索默认只命中最新版 | ✓ VERIFIED | `test_version_flip_on_content_change`（v2 supersedes v1、v1 invalid_at、upsert→tombstone→delete 调用序）+ 3 条 chaos 用例通过；OQ-1 定案：「旧边写 expired_at」按 Phase 12 bi-temporal 语义实现为 `graph_store.invalidate_edge`（置位 invalid_at），模块 docstring 已记录映射，功能等价 |
| 4 | 摄取一律 on_commit + background runner 异步，幂等（重复投递不重复实体/版本），reconcile 对账可验证 | ✓ VERIFIED | `ingestion.py:118-121` `sync_to_async(_register)` + `run_in_background(lambda...)`；A1 三用例（autocommit 投递/rollback 丢弃/异常全吞）+ `test_ingest_idempotent_triple_fire`（3 连发 1 实体 1 版本 upsert×1）通过；`reconcile_delivery_knowledge` 六检查项命令存在且 9 用例通过 |
| 5 | 确定性 chunk + EmbeddingService 向量化写入 delivery_knowledge（hybrid dense+sparse），payload 完整携带权限/版本字段 | ✓ VERIFIED | `chunking.py` 纯函数（uuid5 of KNOWLEDGE_NAMESPACE，格式 `point:{version_id}:{index}` 锁定）；`test_vector_ops.py:69` + `test_ingestion.py:242` 键集合 ⊇ `KNOWLEDGE_PAYLOAD_INDEXED_FIELDS ∪ REQUIRED_FIELDS`（import 常量断言）；hybrid dict + sparse 降级语义有用例 |

### Observable Truths — PLAN must_haves（18 条）

| # | Plan | Truth | Status | Evidence |
|---|------|-------|--------|----------|
| 1 | 13-01 | 同 content 两次 chunk 字节级一致、point id 一致 | ✓ VERIFIED | `test_chunking.py` 确定性用例（124 passed 套件内） |
| 2 | 13-01 | payload 键集合 ⊇ schema 常量并集 | ✓ VERIFIED | `test_vector_ops.py:69` import 常量断言；`build_knowledge_points` 写入处另有自检 raise（REVIEW 复核 ✓） |
| 3 | 13-01 | vector_ops 写失败必 raise 不静默 | ✓ VERIFIED | `vector_ops.py:126-131` False→KnowledgeError；`wait=True` ×4；失败注入用例通过 |
| 4 | 13-02 | 同 IngestionRequest 3 连发：单实体单版本 upsert×1 | ✓ VERIFIED | `test_ingest_idempotent_triple_fire`（L249）断言 acount==1 ×2 + call_count |
| 5 | 13-02 | hash 同 + vector_synced=False 重触发：零新版本，仅补向量 | ✓ VERIFIED | `test_crash_recovery_same_hash_unsynced_revectorizes`（L470，INGEST-07 铁律闭环） |
| 6 | 13-02 | 内容变更产生 v2（supersedes），v1 翻转 + tombstone + 物理删除 | ✓ VERIFIED | `test_version_flip_on_content_change`（L280） |
| 7 | 13-02 | 向量步骤失败不破坏 DB 翻转（第一道防线） | ✓ VERIFIED | 3 条 chaos 用例（L327/340/356：delete 失败/tombstone 失败/upsert 失败留 unsynced） |
| 8 | 13-02 | aschedule rollback 不投递、commit 投递、异常不上抛 | ✓ VERIFIED | L101/114/130 三用例（A1 首验） |
| 9 | 13-02 | embedding 含 None 整体 abort，DB/Qdrant 零写 | ✓ VERIFIED | `test_embedding_none_aborts_with_zero_writes`（L385，断言 acount==0） |
| 10 | 13-03 | chat 三动作各投递一次，零手动操作 | ✓ VERIFIED | `test_triggers.py -k chat` 7 用例（created=False 零投递、全失败零投递亦覆盖） |
| 11 | 13-03 | MCP 两服务成功时各投递 | ✓ VERIFIED | `-k mcp` 4 用例 |
| 12 | 13-03 | coding_plan content 仅 title+tech_plan，零对话原文 | ✓ VERIFIED | 特征串 `_SENTINEL` 断言 + grep 零命中（T-13-01 钉死） |
| 13 | 13-03 | mcp normalizer 产出 work_item 锚 + tech_plan + HAS_PLAN EdgeSpec | ✓ VERIFIED | `mcp_plan.py:94-95`（EdgeRelation.HAS_PLAN + generate_entity_id 唯一入口）；normalize 用例 4 条 |
| 14 | 13-03 | ingestion 抛异常时 5 触发点宿主主流程仍成功 | ✓ VERIFIED | `TestExceptionIsolation` 3 用例；宿主套件 65 passed 零回归 |
| 15 | 13-04 | reconcile 默认 dry-run 六检查项零写副作用 | ✓ VERIFIED | `test_dry_run_detect_zero_write`（L138）；Summary 行含 missing_edges 等 9 计数键 |
| 16 | 13-04 | --fix 四类修复（重嵌入/tombstone+删/孤儿删/补边） | ✓ VERIFIED | L237/284 调用参数级断言用例 |
| 17 | 13-04 | 单点异常 skip 不崩整命令 | ✓ VERIFIED | `test_item_exception_skips_without_crash`（L152） |
| 18 | 13-04 | rebuild --yes 删建后从 PG 全量重嵌入 latest | ✓ VERIFIED | L186/208 两用例；`rg TODO rebuild_delivery_knowledge.py` 零命中（锚点已消化） |

**Score:** 23/23（5 ROADMAP SC + 18 plan truths）全部 VERIFIED

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | INGEST-08 文本类型「diff」的摄取 | Phase 14 | Phase 14 SC2/SC5：diff 归档落库 + code_change 摄取 + 万行级大 diff 分层切块；REQUIREMENTS.md 将 INGEST-08 留 Pending 与此一致 |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `server/knowledge/chunking.py` | 确定性 chunker + point id 派生 | ✓ VERIFIED | 125 行；KnowledgeChunk/MAX_CHUNK_CHARS=3000/chunk_knowledge_text/derive_point_ids 全在；零 tree_sitter/CodeParser |
| `server/knowledge/vector_ops.py` | 失败响亮写薄层 | ✓ VERIFIED | 198 行；常量 import 自 collection.py；wait=True ×4；零 batch_set_payload/delete_vectors |
| `server/knowledge/migrations/0002_*.py` | vector_synced 字段 | ✓ VERIFIED | 迁移 + models.py:212 字段在位；`makemigrations --check --dry-run` 干净 |
| `server/knowledge/ingestion.py` | DTO + 调度 + 六步序核心 | ✓ VERIFIED | 503 行；全部导出符号在位；WR-01 修复（L365-379 dropped 差集 tombstone+删除）与 IN-03 修复（require_aware 公开 import）均在 HEAD |
| `server/knowledge/sources/__init__.py` | 惰性注册表 | ✓ VERIFIED | get_normalizer + 未知 kind KeyError 用例通过 |
| `server/knowledge/sources/coding_plan.py` | chat normalizer | ✓ VERIFIED | 66 行；OQ-3 拼法；源缺失返回空列表 |
| `server/knowledge/sources/mcp_plan.py` | mcp 双事件 normalizer | ✓ VERIFIED | 102 行；HAS_PLAN exclusive EdgeSpec |
| `server/knowledge/management/commands/reconcile_delivery_knowledge.py` | 六检查项对账命令 | ✓ VERIFIED | 472 行；dry-run 默认 + --fix + --limit；零 filter 删点 |
| `server/knowledge/management/commands/rebuild_delivery_knowledge.py` | 全量重嵌入扩展 | ✓ VERIFIED | TODO 锚点已消化；只过滤 is_latest=True |
| 测试文件 ×5（chunking/vector_ops/ingestion/triggers/reconcile） | 回归资产 | ✓ VERIFIED | 全部存在，124 passed |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| ingestion.py | background_runner | `sync_to_async(_register)` → on_commit → `run_in_background(lambda...)` | ✓ WIRED | L118-121，factory 形态正确 |
| ingestion.py | graph_store.py | add_edge/invalidate_edge/neighbors 唯一收口 | ✓ WIRED | L310/318/320；`KnowledgeEdge.objects` 零命中 |
| ingestion.py | vector_ops.py | upsert→tombstone→delete 三步序 | ✓ WIRED | L42 import；调用序测试钉死 |
| vector_ops.py | collection.py | schema 常量 import | ✓ WIRED | L26 单一事实源 |
| chunking.py | models.py | KNOWLEDGE_NAMESPACE 派生 | ✓ WIRED | L18/123 |
| vector_ops.py | qdrant_service.py | upsert_vectors_by_name False→raise | ✓ WIRED | L126-131 转译为 KnowledgeError |
| chat/models.py ×2 + coding_session_service ×1 | ingestion.py | lazy import + aschedule_ingestion | ✓ WIRED | 计数 2/1，HEAD 实测；views.py（HEAD）零命中（OQ-4：confirm 不挂） |
| mcp ×2 | ingestion.py | 同上 | ✓ WIRED | technical_plan_service:528、work_item_execution_service:601 |
| reconcile 命令 | ingestion.py / vector_ops.py | revectorize_version / apply_edge_specs / tombstone / delete | ✓ WIRED | --fix 用例调用参数级断言 |
| mcp_plan.py | models.py | generate_entity_id 派生 HAS_PLAN 目标 | ✓ WIRED | L95，无散落 uuid5 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| sources/coding_plan.py | event.content | `CodingPlan.objects.select_related(...).afirst()` 真实 ORM 重读 | Yes | ✓ FLOWING |
| sources/mcp_plan.py | 双事件 content/payload | `McpWorkItemTechnicalPlan.objects.select_related(...)` 真实 ORM | Yes | ✓ FLOWING |
| ingestion._persist_sync | 版本行/翻转 | select_for_update 锁内真实写库 | Yes | ✓ FLOWING |
| reconcile 命令 | 漂移计数 | 真实 ORM 迭代 + client.retrieve/scroll | Yes | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| knowledge 全量回归 | `cd server && uv run pytest tests/knowledge/ -q` | 124 passed, 1 deselected, 7.83s | ✓ PASS |
| 宿主零回归 | `uv run pytest tests/test_coding_tools.py tests/mcp_tools/ -q` | 65 passed | ✓ PASS |
| 迁移完整 | `uv run python manage.py makemigrations --check --dry-run` | No changes detected, exit 0 | ✓ PASS |
| VALIDATION 命令映射 | `-k chat`/`-k mcp`/`-k normalize`/`-k "detect or skip or rebuild"` collect | 7/4/4/7 非空选中 | ✓ PASS |
| 真实 Qdrant 端到端 | — | 测试全 mock（--disable-socket） | ? SKIP → human |

### Probe Execution

无 `scripts/*/tests/probe-*.sh` 约定探针，PLAN/SUMMARY 未声明 probe——SKIPPED（不适用）。

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| INGEST-03 | 13-03 | chat 自动摄取（对话原文不入图） | ✓ SATISFIED | SC1 证据链：3 锚点 + 特征串断言 |
| INGEST-05 | 13-03 | MCP 工具链自动摄取 | ✓ SATISFIED | SC2 证据链：2 锚点 + 投递断言 |
| INGEST-06 | 13-01/02/04 | 重摄取版本翻转 + 向量下线 + 旧边失效 | ✓ SATISFIED | SC3 证据链；OQ-1 expired_at→invalid_at 措辞映射已定案记录 |
| INGEST-07 | 13-02/04 | 异步 on_commit + 幂等 + reconcile 可验证 | ✓ SATISFIED | SC4 证据链：A1 + 三连发 + crash 恢复 + 对账命令 |
| INGEST-08 | 13-01/02 | 确定性 chunk + hybrid 写入 + payload 全字段 | ✓ SATISFIED（Phase 13 份额） | SC5 证据链；「diff」文本类型 DEFERRED → Phase 14（REQUIREMENTS.md Pending 与此一致） |

无 ORPHANED：REQUIREMENTS.md 映射 Phase 13 的 5 个 ID 全部被 4 个 plan 的 frontmatter 认领。

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | TBD/FIXME/XXX/HACK/PLACEHOLDER 扫描零命中（全部 9 个产物文件） | — | 无 |

REVIEW.md 4 项发现处置核验：WR-01 修复（73994e99）在 HEAD（`ingestion.py:365-379` dropped 差集下线 + 2 条收缩测试 L521/565）；IN-03 修复（90d354fc）在 HEAD（require_aware 公开 import）；IN-01/IN-02 为 acknowledged Info（有记录的有意保留，非未解决债务）。

### Human Verification Required

### 1. 真实 Qdrant 端到端摄取

**Test:** `docker compose` 启动 qdrant 后，在 dev 环境创建或修改一次 CodingPlan（chat 对话产出方案），等待后台摄取完成。
**Expected:** `delivery_knowledge` collection 出现对应点位（hybrid dense+sparse named vectors），payload 完整携带 entity_kind/entity_id/version/is_latest/project_id/event_time；再修改一次方案后，旧版本点 is_latest 翻转并被物理删除，检索面只见最新版。
**Why human:** 测试套件经 pytest-socket 全程禁网、Qdrant 全 mock；真实 named vectors 写入、set_payload/delete 的 wait=True 行为需真实实例验证（13-VALIDATION.md Manual-Only 项）。

### Gaps Summary

无 gaps。23/23 must-haves 全部经代码与测试证据验证；唯一非自动化项为 VALIDATION.md 预先声明的 Manual-Only「真实 Qdrant 端到端摄取」，已列入 human_verification。INGEST-08 的「diff」文本类型按 ROADMAP 属 Phase 14 范围，列为 deferred（非 gap）。

---

_Verified: 2026-06-11T14:40:00Z_
_Verifier: Claude (gsd-verifier)_
