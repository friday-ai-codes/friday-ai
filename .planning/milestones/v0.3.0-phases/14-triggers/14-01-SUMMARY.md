---
phase: 14-triggers
plan: 01
subsystem: knowledge
tags: [kmod-05, enh-01, diff-archive, modifies-chunk, chunking, unidiff]
requires:
  - 13-02 统一摄取管线（EdgeSpec / apply_edge_specs / ingest_events 契约）
  - 12 KnowledgeEdge target_chunk_id XOR 约束 + MODIFIES_CHUNK 枚举占位
provides:
  - CodeChangeArchive 模型 + migration 0003（KMOD-05 持久层，zlib 压缩 + 幂等锚）
  - KnowledgeEdge uniq_kedge_chunk_active partial unique（Pitfall 4 DB 防线）
  - EdgeSpec(target_chunk_id, metadata) + apply_edge_specs chunk 边幂等分支
  - graph_store.chunk_in_edges(chunk_id) 反查收口（ENH-01）
  - chunk_knowledge_text diff-aware 分层切块（chunk_kind="diff"）
  - sources 注册表 workflow_plan / task_result / feishu_work_item 三行登记
affects:
  - 14-03 DiffArchiver（消费 CodeChangeArchive + EdgeSpec chunk 通路）
  - 14-04/05/06 三个 normalizer（消费注册表登记 + chunker diff 分支）
tech-stack:
  added: ["unidiff>=0.7.5,<0.8"]
  patterns:
    - chunk 边写入唯一通路 = EdgeSpec → apply_edge_specs（RESEARCH 选项 A）
    - diff chunks 只从 version.content 重派生（Pitfall 8，content 即真理）
key-files:
  created:
    - server/knowledge/migrations/0003_codechangearchive_and_more.py
    - server/tests/knowledge/test_diff_archive.py
    - server/tests/knowledge/test_modifies_chunk.py
  modified:
    - server/pyproject.toml
    - server/uv.lock
    - server/knowledge/models.py
    - server/knowledge/ingestion.py
    - server/knowledge/graph_store.py
    - server/knowledge/chunking.py
    - server/knowledge/sources/__init__.py
    - server/tests/knowledge/test_chunking.py
decisions:
  - uniq_kedge_chunk_active 条件取 invalid_at/expired_at 双 NULL（照 uniq_kedge_active 同款形态）
  - EdgeSpec XOR 违例 warning 跳过单 spec 不 raise 整批；chunk 边忽略 exclusive
  - 实体边 exclusive 置位时跳过 target_id 为 None 的 chunk 边（混合批互不干扰）
  - diff 区段超长文件按 hunk 再切时，文件头随首个 hunk 保留、后续 hunk 拼回文件头两行上下文
metrics:
  duration: ~10min
  tasks: 3
  files: 11
completed: 2026-06-11
---

# Phase 14 Plan 01: 地基件（归档模型 + chunk 边通路 + diff 切块）Summary

CodeChangeArchive 归档表（zlib 压缩 + (source_kind, source_id, commit_sha) 幂等锚）、chunk 边幂等通路（EdgeSpec 扩展 + apply_edge_specs + DB partial unique 双防线）与 chunk_knowledge_text 的 diff-aware 文件→hunk→硬切分层切块全部落地，后续 plan 不再触碰 knowledge 核心模块。

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | unidiff 依赖 + CodeChangeArchive + chunk partial unique + migration | 3fb1031b | models.py, 0003 migration, test_diff_archive.py |
| 2 | EdgeSpec 扩展 + apply_edge_specs chunk 幂等 + chunk_in_edges + 注册表三行 | 56f04a58 | ingestion.py, graph_store.py, sources/__init__.py, test_modifies_chunk.py |
| 3 | chunk_knowledge_text diff-aware 分支 | 8268e6fb | chunking.py, test_chunking.py |

## 交付物对照（must_haves）

- ✅ CodeChangeArchive 可落库：zlib 往返逐字节一致、Git 元数据/仓库 FK（SET_NULL）/文件级 JSON 全部持久化（test_compression_roundtrip / test_full_field_persistence）
- ✅ 同 (source_kind, source_id, commit_sha) 重复归档被 uniq_codechange_source_commit 拒绝（test_duplicate_source_commit_rejected）
- ✅ apply_edge_specs chunk 边三连发幂等：恰 1 条活跃边，metadata 持久化（test_chunk_edge_triple_fire_idempotent）
- ✅ uniq_kedge_chunk_active DB 级 partial unique（Pitfall 4 封堵，test_chunk_edge_partial_unique 双向断言）
- ✅ chunk_knowledge_text diff 分层切块：chunk_kind="diff"、逐 chunk ≤ MAX_CHUNK_CHARS、确定性不变、非 diff 路径零回归（test_diff_* 四用例）
- ✅ graph_store.chunk_in_edges 反查收口（含 metadata；invalidate 后不可见）
- ✅ sources/__init__.py 三行登记（模块由 14-04/05/06 落地，落地前 get_normalizer 触发 ImportError 响亮失败）

## Deviations from Plan

**1. [Rule 3 - Blocking] migration 文件名与 frontmatter 预估不同**
- **Found during:** Task 1
- **Issue:** makemigrations 实际生成 `0003_codechangearchive_and_more.py`（plan frontmatter 预估为 `0003_codechangearchive_kedge_chunk_unique.py`）
- **Fix:** 按 plan 注记"生成文件名以实际为准"采用实际文件名，未手写改名
- **Commit:** 3fb1031b

**2. [Rule 1 - Bug] 生成的 migration 不符合 ruff 规范**
- **Found during:** Task 1
- **Issue:** Django 生成的 migration import 排序与格式不过 ruff check/format
- **Fix:** `ruff check --fix` + `ruff format` 处理后提交
- **Commit:** 3fb1031b

其余按计划逐字执行。

## Known Stubs

| Stub | File | Reason |
|------|------|--------|
| `workflow_plan` / `task_result` / `feishu_work_item` 注册行指向尚不存在的模块 | `server/knowledge/sources/__init__.py` | 规划定案（13-02 先例）：先登记，模块由 14-04/05/06 落地；落地前 get_normalizer 触发 ImportError 响亮失败，不静默 |

## Verification

- `uv run pytest tests/knowledge/` → 136 passed（既有用例零回归 + 本 plan 新增 12 用例）
- `uv run python manage.py makemigrations --check --dry-run` → 退出码 0
- `uv run ruff check knowledge/ tests/knowledge/` + `ruff format --check` → 全部通过
- 验收锚点：`rg "KnowledgeEdge.objects" knowledge/ingestion.py` 零命中；注册表三行计数 == 3；`-k chunk` 非空选中；unidiff 版本约束 `>=0.7.5,<0.8` 落 pyproject + uv.lock

## Self-Check: PASSED

- FOUND: server/knowledge/migrations/0003_codechangearchive_and_more.py
- FOUND: server/tests/knowledge/test_diff_archive.py
- FOUND: server/tests/knowledge/test_modifies_chunk.py
- FOUND: commit 3fb1031b / 56f04a58 / 8268e6fb
- tests green (136 passed) / makemigrations check clean
