# 85-01 Summary — 项目上下文物化进交付知识图谱

**Plan:** 85-01（CTX-01 写半 / CTX-02 图谱沉淀）
**Status:** ✅ Done
**Commit:** `73f4f1ce` — `feat(85): 项目上下文物化进交付知识图谱（写时增量+兜底重建+visibility 隔离）[85-01]`

## 交付内容

把项目上下文（DOC-01~05 五文件正文 + active 项目记忆）物化进既有 `delivery_knowledge`
向量库与交付知识图谱（复用 `KnowledgeEntity`/`KnowledgeEdge`），经新 `source_kind`
（`project_doc` / `project_memory`）+ 复用 `EntityKind.DOCUMENT` 做逻辑隔离（A1 锁定口径，
**不**新建第二个物理 collection）。写时增量钩子 + 兜底定时全量重建 + content_hash 幂等短路
三者合成跨重启安全网。

### 新增文件
- `server/knowledge/sources/project_doc.py` — `async def normalize`：5 文件 `last_synced_snapshot`
  → DOCUMENT 实体 + REFERENCES→项目节点边；正文 `redact_secrets_in_text` 脱敏；fail-soft（缺正文不缺实体）。
- `server/knowledge/sources/project_memory.py` — `async def normalize`：active 记忆 → DOCUMENT 实体
  + REFERENCES→项目节点边；非 active / 不存在 → `[]`（不摄取已废弃）。
- `server/knowledge/management/commands/rebuild_project_context.py` — `class Command` +
  `_rebuild_project_context()`：按 source 重 `aschedule_ingestion`（幂等，**绝不删库**）。
- `server/tests/knowledge/test_project_doc_source.py`、`test_project_memory_source.py`、
  `test_rebuild_project_context.py` — source/重建守护测试。
- `server/tests/initiatives/test_memory_materialize_hook.py` — 三处写收口钩子 + best-effort 守护测试。

### 改动文件
- `server/knowledge/ingestion.py` — `aschedule_ingestion(request, *, initiated_by_user_id=None)`
  归因透传给 `run_in_background`（默认 None 保既有 5 调用点零回归）。
- `server/knowledge/sources/__init__.py` — `_NORMALIZERS` 注册 `project_doc` / `project_memory`。
- `server/initiatives/services/memory_service.py` — 新 `_schedule_materialization` 私有方法
  + `append`/`edit`/`sync_edit`(applied)/`supersede`/`confirm_draft` 5 处写后挂钩子（best-effort + 归因）。
- `server/initiatives/services/project_doc_service.py` — `write_human_block` 写后挂 project_doc 钩子
  + `_schedule_materialization` helper。
- `server/initiatives/services/doc_sync_service.py` — `pull` 回写正文后挂 project_doc 钩子（透传 `initiated_by_user_id`）。
- `server/agents/management/commands/runapscheduler.py` — 注册 `rebuild_project_context` CronTrigger job
  （daily 06:00，`max_instances=1`、`replace_existing=True`）。

## 迁移
**无新增 migration**（复用既有 `delivery_knowledge` + `KnowledgeEntity`/`KnowledgeEdge`，无 schema 变更）。
0008 留给并行的 85-03（ProjectBranch）独占。

## 观测
- normalizer：`project_doc_rag_normalize_started/completed`、`project_memory_rag_normalize_*`
  （`component=knowledge`、`category=sampling`、`duration_ms`、`content_length`、`event_count`）。
- 重建：`rebuild_project_context_started/completed`（`category=caller`、`scheduled`、`duration_ms`）。
- 归因：写时增量经 `aschedule_ingestion` 透传 `initiated_by_user_id`（无则 system，定时重建为 system）。
- 脱敏：正文入图前 `redact_secrets_in_text`；日志只记 id/计数/长度，绝不记正文（T-85-01-01）。
- best-effort：钩子 `except Exception: pass`（`# noqa: BLE001`）+ ingestion content_hash 幂等，绝不反噬业务写（T-85-01-02）。

## 测试结果
- 计划指定 + 新增：`tests/knowledge/test_project_doc_source.py test_project_memory_source.py
  test_rebuild_project_context.py tests/initiatives/test_memory_materialize_hook.py` → **14 passed**。
- 回归（确认 ingestion 签名变更 + 钩子无回归）：`tests/knowledge tests/initiatives`
  （-k ingestion/artifact/source/memory/doc/sync/trigger/rebuild/materialize）→ **450 passed**。
- ruff：我的新文件全 clean。`ingestion.py` 报 1 条 import-order 错误为**HEAD 上已存在的 pre-existing lint**
  （我的 diff 仅改函数签名未动 imports），未引入新 lint，按规范不在本 plan 修复。

## A1 架构口径决策（已显式记录于 85-01-PLAN.md）
复用 `delivery_knowledge` 作项目上下文专属、逻辑独立于代码 RAG（per-repo `code_index_*`）的承载；
被否决备选「另起第三个物理 collection」理由：与 CTX-02 双重向量化 + 重写整套 collection 生命周期，
收益仅物理隔离而 visibility 隔离已由 `delivery_knowledge` 的 `access_scope` 具备。

## Deferred / 交接
- visibility 召回过滤口径对称验证（OQ2 / A3）由 **85-02** 作安全前置门（零泄漏 PASS 测试）承担——
  本 plan 仅写入侧正确填充 `space_id`（项目维度）。
- 读侧召回端点（RAG/grep/file-read MCP 工具）属 **85-02**。
- 分支绑定（ProjectBranch 模型 / 迁移 0008 / lookup 扩展）属并行 **85-03 / 85-04**。

## Blockers
无。
