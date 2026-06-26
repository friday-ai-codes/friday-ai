# 83-01 Summary — block_id 结构化 diff + 三方合并 + schema 地基

**Plan:** 83-01（Wave 1）
**Status:** ✅ 完成
**Requirements:** SYNC-03, SYNC-04

## 交付物

### 纯算法层（无 IO/ORM/httpx，可无 DB 单测）
- NEW `server/initiatives/services/doc_sync_diff.py`
  - `block_content_hash(text)` — 归一化（折叠空白）后 sha256 hexdigest，幂等；落 `ProjectDocBlockMap.content_hash`（max_length=128）。
  - `diff_blocks(*, base_snapshot, theirs_blocks, block_map)` — block_id 结构化 diff：
    不在 map→`added`、在 map 且 hash 变→`edited`、在 map 但飞书已无→`deleted`、hash 未变→no-op。
    缺 block_id/脏块跳过不抛；`block_map` 空→全 `added`；兼容 dict 与裸 hash 字符串映射条目。
  - `three_way_merge(*, base, theirs, ours)` — 真值表合并，飞书侧（theirs）优先为 `merged`，
    相交冲突 `has_conflict=True` 且落败方 `ours` 进 `loser`（capture-never-clobber，绝不静默丢）。
  - dataclass `BlockDiff` / `MergeResult`（均 `frozen`）。

### schema 扩展（migration 0007）
- `ProjectDoc` 新增 `subscribed`(BooleanField default=False) + `last_feishu_edit_at`(DateTimeField null=True)（OQ-4）。
- NEW 模型 `ProjectDocBlockRevision`（doc + feishu_block_id + db_ref + content + source + reason + captured_at；
  db_table `initiative_project_doc_block_revisions`；Index(["doc","feishu_block_id"])）——
  STATE/MILESTONES/RESEARCH/PREFLIGHT 的 capture-never-clobber 落点（OQ-2）。
- `server/initiatives/migrations/0007_doc_sync_engine.py` — 纯 AddField + CreateModel，无回填。
- `models/__init__.py` re-export 加 `ProjectDocBlockRevision`。

### 写入收口 + 守护（INV-6）
- `ProjectDocService.capture_block_revision`（+ `_capture_block_revision_locked`）——最小写入收口占位，
  编排由 83-04 填充；新模型落库只经此 service。
- `test_project_doc_inv6_guard.py` 的 `_MODELS` 扩 `ProjectDocBlockRevision`（grep 守护 + writer 有效性断言）。

### 测试脚手架（Wave 0）
- NEW `tests/initiatives/test_doc_sync_diff.py` — 16 用例（content_hash 幂等/归一化、diff 四类 + 防御性、merge 真值表）。
- NEW `tests/initiatives/conftest.py` — `project_doc_factory`/`block_map_factory`/`project_memory_factory`（经 service，INV-6）+ `respx_feishu` fixture，供 Wave 2+ 复用。

## 验证
- `makemigrations --check --dry-run initiatives` → No changes detected（干净）。
- `pytest tests/initiatives/test_doc_sync_diff.py tests/initiatives/test_project_doc_inv6_guard.py` → 18 passed。
- `pytest tests/initiatives/test_project_doc_service.py` → 12 passed（service 改动未回退既有）。
- `ruff check`（全部 touched 文件）→ All checks passed；`doc_sync_diff.py` 无 httpx/.objects/structlog（仅 docstring 提及）。

## 偏差 / 备注
- migration 自动名重命名为 `0007_doc_sync_engine.py`（无下游迁移引用，安全）。
- `diff_blocks` 的 `base_snapshot` 入参保留供下游 rebase 上下文；结构化 diff 本身以 block_id + content_hash 判定，不依赖其文本内容。
- 新增 block 缺映射时区段默认 `"system"`（字面量，避免引入 ORM `DocSection` 依赖以保持纯函数）。
