# 83-05 SUMMARY — ProjectDoc 渲染 read-through 缓存（SYNC-05）

**Status:** ✅ Done
**Wave:** 1（与 83-01 零文件重叠，可并行）
**Requirements:** SYNC-05

## 交付物

| 文件 | 变更 | 说明 |
|---|---|---|
| `server/initiatives/services/doc_sync_cache.py` | NEW | read-through 缓存薄层：`doc_render_cache_key` / `get_doc_render` / `set_doc_render` / `invalidate_doc_render` |
| `server/friday/settings.py` | 改 | 新增 `DOC_RENDER_CACHE_TTL = env.int("DOC_RENDER_CACHE_TTL", default=300)`（IGNORE_EXCEPTIONS 已在 redis CACHES OPTIONS，未改 backend / LocMem 回退） |
| `server/tests/initiatives/test_doc_sync_cache.py` | NEW | 命中/未命中/失效/redis 故障降级 + delete 守护 + 日志无正文守护（8 用例） |

## 关键不变量

- **read-through**：`get_doc_render` 命中返回缓存值（不查 DB）；未命中返回 None，调用方读 DB 渲染后 `set_doc_render` 回填。
- **失效用 delete 而非 set 空**（Pitfall 7）：写时 / 收飞书事件调 `invalidate_doc_render(doc_id)` → `cache.delete(key)`，下次读 miss 回填。
- **TTL 兜底**：`set` 默认 `settings.DOC_RENDER_CACHE_TTL`（300s），作"漏失效"过期保险。
- **降级直读 DB**：redis 不可用时 `IGNORE_EXCEPTIONS`（settings）+ 模块内整段 try/except 双层兜底，`get` 静默返回 None / `set`·`invalidate` no-op，**绝不反噬渲染主流程**。
- **观测**：缓存故障记 `doc_render_cache_degraded`（category=sampling / component=doc_sync / debug），只记 `doc_id` / `op` / `error_type`，**不记渲染正文**（T-83-05-INFO）。

## 验证

- `cd server && uv run pytest tests/initiatives/test_doc_sync_cache.py -q` → **8 passed**。
- settings 自检（redis 配置下）：`IGNORE_EXCEPTIONS in CACHES = True`、`DOC_RENDER_CACHE_TTL = 300`。

## 接线指引（Wave 2+ 消费）

- 渲染读路径：`val = get_doc_render(doc_id)`；miss → 读 DB 渲染 → `set_doc_render(doc_id, val)`。
- pull/push 写完 / 收 `drive.file.edit_v1` 事件：调一行 `invalidate_doc_render(doc_id)` 失效。

## Migration

**无新增 migration**（纯缓存薄层，不碰 ORM）。与 83-01（owns 0007）零冲突。

## 偏差 / 阻塞

- 无阻塞。`IGNORE_EXCEPTIONS` 已于既有提交存在于 redis CACHES OPTIONS（Task 1 仅需补 `DOC_RENDER_CACHE_TTL` 常量，最小 diff，零 backend 回归）。
- 模块按 plan 落为独立函数式薄层，未注册进 `services/__init__.py`（plan 明确不绑定 DocSyncService、自包含）。
