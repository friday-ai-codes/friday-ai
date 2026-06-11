---
phase: 13-ingest
plan: 13-01
status: complete
subsystem: knowledge
requirements_addressed: [INGEST-08, INGEST-06]
tags: [chunking, vector-ops, qdrant, idempotency]
dependency_graph:
  requires:
    - server/knowledge/models.py (KNOWLEDGE_NAMESPACE, KnowledgeEntityVersion)
    - server/knowledge/collection.py (payload schema 常量, DELIVERY_KNOWLEDGE_COLLECTION)
    - server/services/qdrant_service.py (QdrantService.get_client / upsert_vectors_by_name)
  provides:
    - "KnowledgeEntityVersion.vector_synced（布尔字段，0002 迁移）：向量 upsert 成功后置 True；13-02 短路条件 = content_hash 相同 AND vector_synced"
    - "get_embedding_model_name()（knowledge/collection.py，入 __all__）：公开 embedding 模型名读取"
    - "KnowledgeChunk / MAX_CHUNK_CHARS=3000 / chunk_knowledge_text(title, content) / derive_point_ids(version_id, chunk_count)（knowledge/chunking.py，纯函数）"
    - "build_knowledge_points(...) / upsert_knowledge_points(points) / tombstone_points(point_ids) / delete_points(point_ids)（knowledge/vector_ops.py）"
    - "mock_embedding fixture（tests/knowledge/conftest.py，dense AsyncMock 1024 维 + sparse sync）"
  affects:
    - 13-02（摄取核心消费全部上述符号）
    - 13-04（reconcile 消费 vector_ops 与 vector_synced）
tech_stack:
  added: []
  patterns:
    - "知识路径 Qdrant 写语义与 indexer 刻意相反：wait=True + 失败 raise（删点除外：吞但 structlog error）"
    - "point id 锁定格式 point:{version_id}:{index}（uuid5 of KNOWLEDGE_NAMESPACE）"
key_files:
  created:
    - server/knowledge/chunking.py
    - server/knowledge/vector_ops.py
    - server/knowledge/migrations/0002_knowledgeentityversion_vector_synced.py
    - server/tests/knowledge/test_chunking.py
    - server/tests/knowledge/test_vector_ops.py
  modified:
    - server/knowledge/models.py
    - server/knowledge/collection.py
    - server/tests/knowledge/conftest.py
    - server/tests/knowledge/test_models.py
decisions:
  - "upsert 失败直接 raise KnowledgeError（基类 message+details 语义足够，未新增 KnowledgeVectorWriteError 子类）"
  - "build_knowledge_points 写入处内置 schema 键集合自检（缺字段即 raise，T-13-02 双保险）"
  - "summary chunk 为 title 预留空间：首段硬切剩余回流 section，超长内容零丢失"
metrics:
  duration: ~9min
  tasks: 3
  files: 9
  completed: 2026-06-11
---

# Phase 13 Plan 01: 向量化基建三件套 Summary

确定性知识文本 chunker（同输入同 point id）+ delivery_knowledge 失败响亮写薄层（wait=True / False→raise / 按 id 删点）+ vector_synced 幂等凭据字段，为 13-02 摄取核心提供无状态可独立测试的底层件。

## 任务执行情况

| Task | 内容 | Commits |
|------|------|---------|
| 1 | vector_synced 迁移 + get_embedding_model_name 公开 + mock_embedding fixture | 4f673819 (RED), 2050b052 (GREEN) |
| 2 | 确定性 chunker（chunking.py） | de6f14dd (RED), 9430670f (GREEN) |
| 3 | Qdrant 写操作薄层（vector_ops.py，失败响亮） | 2e33ea86 (RED), 6367e2ba (GREEN) |

## 验收对照（must_haves truths）

- ✅ 同一 content 两次 chunk 字节级一致、同 version_id 两次 derive_point_ids 完全一致（test_chunking.py 确定性组）
- ✅ 每个 point payload 键集合 ⊇ INDEXED ∪ REQUIRED（test_vector_ops.py import 常量断言 + 写入处运行时自检）
- ✅ 任一写操作失败响亮：upsert False → raise KnowledgeError；tombstone 异常重抛 + error 日志；delete 吞但 `knowledge_vector_delete_failed` error 日志

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - 缺失自检] build_knowledge_points 写入处 schema 键集合自检**
- **Found during:** Task 3
- **Issue:** 计划仅要求 import 常量；纯 import 不被使用会触发 ruff F401，且写入处无运行时防线
- **Fix:** 模块级 `_SCHEMA_KEYS` 集合 + 构造时缺字段 raise（T-13-02 mitigate 落到写入处）
- **Files modified:** server/knowledge/vector_ops.py
- **Commit:** 6367e2ba

**2. [Rule 3 - 格式] 自动生成的 0002 迁移未过 ruff format**
- **Found during:** Task 3 验收
- **Fix:** `ruff format` 后随 Task 3 提交
- **Commit:** 6367e2ba

其余按计划逐字执行。

## 实现要点

- `raise KnowledgeError(...)` 直接复用基类（计划允许"基类语义不合适才新增子类"，message + details 已足够表达）。
- summary chunk 预留 title 空间（budget = MAX − len(title) − 2），首段硬切剩余回流 section——超长内容硬切零丢失（test_oversize 锁定字符计数守恒）。
- `derive_point_ids` 拼接格式 `point:{version_id}:{index}` docstring 带 generate_entity_id 同款锁定警告。
- mock_embedding 非 autouse：dense `AsyncMock(side_effect=...)` 1024 维（对齐 get_expected_dimension 默认），sparse classmethod 同步 monkeypatch。

## Known Stubs

None — 本 plan 全部符号有真实实现与测试，无占位数据流。

## Threat Flags

None — 未新增计划 threat_model 之外的安全面（无新端点/认证路径/文件访问；schema 字段写入即 T-13-02 缓解本体）。

## 验证结果

- `uv run pytest tests/knowledge/` → 80 passed（既有 61 用例零回归）
- `manage.py makemigrations --check --dry-run` → 退出码 0
- `ruff check knowledge/ tests/knowledge/` → All checks passed
- 验收 grep：`_embedding_model_name` 私有名零残留；`tree_sitter|CodeParser` 零命中；`batch_set_payload|delete_vectors` 零命中；`wait=True` 4 处；测试 import schema 常量断言命中
