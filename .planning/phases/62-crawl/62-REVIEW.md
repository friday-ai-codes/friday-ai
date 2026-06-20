---
phase: 62-crawl
reviewed: 2026-06-20T17:10:26Z
depth: standard
files_reviewed: 15
files_reviewed_list:
  - server/durable/tasks_impl.py
  - server/durable/handlers.py
  - server/durable/tasks.py
  - server/delivery/models/ingest_run.py
  - server/delivery/migrations/0024_ingestrun_durable_queue.py
  - server/delivery/api/views.py
  - server/delivery/api/serializers.py
  - server/delivery/urls.py
  - server/repositories/models.py
  - server/repositories/migrations/0038_corpustreesnapshot_source_hash.py
  - server/repositories/tree_views.py
  - server/codegraph/services/corpus_tree.py
  - web/src/api/ingest.ts
  - web/src/components/knowledge/BatchIngestPanel.vue
  - web/src/locales/zh-CN.json
findings:
  critical: 1
  warning: 1
  info: 2
  total: 4
status: clean
fixes_applied: 2026-06-21
---

# Phase 62: Code Review Report

**Reviewed:** 2026-06-20T17:10:26Z
**Depth:** standard
**Files Reviewed:** 15
**Status:** issues_found

## Summary

Phase 62 接入了「爬取入库」与「PageIndex/知识树生成」两条 durable 队列。后端 `run_crawl_ingest` 薄封装契约干净（DB 真相源、排除 COMPLETED、单行隔离、有界并发），队列动作端点（enqueue 202 / list / detail / start / stop / retry）权限、路由顺序、`idempotency_key` 派生均符合契约且不直接 import procrastinate；前端面板正确从后端 `listQueue` 恢复队列（无内存 `batchId` 作为列表来源）、轮询 running/queued→2s、stop 破坏性确认、feishu 引导保留、zh-CN 文案纯增量。迁移 0024/0038 均为带 default 的加列，兼容存量。

但 **PageIndex（PAGEIDX-01）分支存在一个 BLOCKER 级逻辑错误**：`KnowledgeTreeRebuildView` 把「入队时刻的当前指纹」作为 `target_hash` 传入，而 `run_page_index` 又用「执行时刻的当前指纹」与之比对——二者来自同一 `compute_source_hash()`，在仓库数据未变的常态下恒等，导致 `run_page_index` **永远返回 skipped、`build_full` 永不被调用**，重建端点实际上是死路（首次构建也建不出树）。该缺陷被现有测试遗漏（测试手工传 `target_hash`，未端到端模拟 rebuild view 传当前指纹）。

另有一处 list 端点全表加载与威胁模型声明的「N=50 上限避免大查询」不符（WARNING），以及两处低风险 INFO。

关于预存失败用例 `test_plan_session_inv6_guard`（`chat/conversation_service.py:1922` 中文注释处）：`chat/conversation_service.py` **不在** Phase 62 变更文件清单内（本阶段未触及 chat app），其失败与 Phase 62 无关，确认为 **PRE-EXISTING / 非本阶段回归**。

## Critical Issues

### CR-01: 知识树重建端点永远跳过、`build_full` 永不执行（hash 比对参照错误）

**File:** `server/repositories/tree_views.py:182-196`（配合 `server/durable/tasks_impl.py:146-153`）
**Issue:**
`KnowledgeTreeRebuildView.post` 计算并传入的 `target_hash` 是**入队时刻的当前全仓指纹**：

```183:194:server/repositories/tree_views.py
        # 入队点算 target hash：run_page_index 据此 hash 跳过（未变不重建重 LLM 聚类，T-62-05 DoS）。
        target_hash = await CorpusTreeService.compute_source_hash()
        key = "page_index:corpus_tree"
        job_id = await DurableTaskService.defer(
            "durable_page_index",
            {"target_id": "corpus_tree", "target_hash": target_hash},
            queue=QUEUE_PAGE_INDEX,
            idempotency_key=key,
        )
```

而 `run_page_index` 的跳过判定又用**执行时刻的当前全仓指纹** `current` 与之比对：

```146:153:server/durable/tasks_impl.py
    current = await CorpusTreeService.compute_source_hash()
    if target_hash and target_hash == current:
        logger.info(
            "durable_page_index_skipped", target_id=target_id, reason="hash_unchanged"
        )
        return {"status": "skipped", "reason": "hash_unchanged", "target_id": target_id}

    result = await CorpusTreeService.build_full()
```

`compute_source_hash()` 是确定性纯函数（见 `test_compute_source_hash_deterministic_and_sensitive`）。在「入队 → worker 领取执行」之间仓库数据未变的常态下，`target_hash == current` 恒成立 → **每次都返回 `skipped`，`build_full` 永不被调用**。后果：
- 管理员点击「重建」实际什么都不做（包括**首次**构建——空系统也建不出 active snapshot）。
- 这是 `durable_page_index` 在生产代码中的**唯一**入队点（grep 确认仅 `tree_views.py` 派发），所以该队列在常态下形同虚设，PAGEIDX-01「hash 变则真实重建」的核心目标未达成。

跳过逻辑的正确参照应是**上一次已构建 snapshot 的 `source_hash`**（「自上次构建以来输入是否变化」），而非入队时刻的当前指纹（「入队到执行之间是否变化」，几乎恒为否）。现有测试用 `target_hash=""`（强制构建）和手工 `target_hash=stored_hash`（强制跳过）分别验证两路，**未模拟 rebuild view 实际传入的「当前指纹==执行指纹」场景**，故漏掉此集成缺陷。

**Fix:** 让 rebuild view 传入「当前 active snapshot 的 source_hash」而非当前指纹，使比对语义变为「自上次构建以来是否变化」。例如在 `tree_views.py`：

```python
from repositories.models import CorpusTreeSnapshot

last_hash = await sync_to_async(
    lambda: CorpusTreeSnapshot.objects.filter(is_active=True)
    .values_list("source_hash", flat=True)
    .first()
)() or ""
job_id = await DurableTaskService.defer(
    "durable_page_index",
    {"target_id": "corpus_tree", "target_hash": last_hash},
    queue=QUEUE_PAGE_INDEX,
    idempotency_key=key,
)
```

这样 `run_page_index` 内 `current != last_hash`（有变化）→ 重建；`current == last_hash`（无变化）→ 跳过。等价替代方案：在 `run_page_index` 内部直接读 active snapshot 的 `source_hash` 作为比对基线，忽略入队传入的 `target_hash`。同时补一个端到端守护测试：通过 rebuild view 派发后断言首次/变化时 `build_full` 被调用、无变化时跳过。

## Warnings

### WR-01: 队列 list 端点全表加载，与威胁模型「N=50 上限避免大查询」声明不符

**File:** `server/delivery/api/views.py:537-545`
**Issue:**
`IngestQueueView.get` 先无上限地遍历**所有**带 `batch_id` 的 `IngestRun` 行，在 Python 内分组后才 `[:50]` 切片：

```537:545:server/delivery/api/views.py
            groups: "OrderedDict[object, list[IngestRun]]" = OrderedDict()
            for run in IngestRun.objects.filter(batch_id__isnull=False).order_by(
                "-started_at"
            ):
                groups.setdefault(run.batch_id, []).append(run)

            items: list[dict] = []
            for batch_id, batch_runs in list(groups.items())[:_QUEUE_LIST_LIMIT]:
```

`_QUEUE_LIST_LIMIT = 50` 只截断了**输出批数**，并未限制 DB 查询行数。62-01 威胁模型 T-62-04 明确声称「list N=50 上限避免大查询」、序列化器 docstring 也称按「最近 N 批」——但实现会随着历史 `IngestRun`（含旧 JSON 批量与未来所有 crawl 批次）累积而把整张表读进内存，构成与文档声明不一致的可用性/DoS 隐患。注意旧 `JsonIngestBatchView` 派发的批次也带 `batch_id`，会一并被全量加载并出现在 crawl 队列里。

**Fix:** 在 DB 层先限定行数再分组，例如按 `batch_id` 取最近 N 个分组键后再拉取这些批次的行；或至少对 `started_at` 设一个时间/行数硬上限，使查询真正有界：

```python
recent_batch_ids = [
    bid async for bid in IngestRun.objects.filter(batch_id__isnull=False)
    .order_by("-started_at").values_list("batch_id", flat=True).distinct()[:_QUEUE_LIST_LIMIT]
]
# 再仅查询这些 batch_id 的行
```

## Info

### IN-01: `run_page_index` 返回的 `source_hash` 与 `build_full` 落库的 hash 可能不一致

**File:** `server/durable/tasks_impl.py:146,153-159`
**Issue:** `run_page_index` 用 `current`（任务体内第一次 `compute_source_hash()`）作为返回的 `source_hash`，而 `build_full` 内部又**重新** `compute_source_hash()` 一次并以后者落 snapshot（`corpus_tree.py:172-176`）。若两次计算之间仓库数据发生变化，返回值与实际落库值会不同，可能误导下游消费者/日志。影响很低（仅观测一致性）。
**Fix:** 让 `build_full` 返回其落库所用的 `source_hash`（已返回 `source_hash`），`run_page_index` 直接采用 `result.get("source_hash")` 作为返回值，避免重复计算与潜在分叉。

### IN-02: 对已全部 COMPLETED 的批次执行 start/retry 会派发一个空操作 durable job

**File:** `server/delivery/api/views.py:733-756`（`_redefer_batch`）
**Issue:** `_redefer_batch` 仅把 QUEUED/STOPPED/FAILED 行置回 QUEUED；若该批全部 COMPLETED，则 `redefer_ids` 为空（无行被重置），但仍会 `DurableTaskService.defer(...)` 创建一个新 job——`run_crawl_ingest` 随后查不到 active 行返回 `count: 0`。功能正确（幂等、无副作用），仅产生一次无意义的入队。前端 `canRetry` 对 completed 也开放重试入口，会触发此空操作。
**Fix:**（可选）当 `redefer_ids` 为空时短路返回，不再 defer，并在响应里标注 `dispatched: False`；或在前端对 completed 批次不展示「重试」。

---

## Fixes applied (2026-06-21)

全部在 scope 内问题已修复并各自原子提交（Conventional Commits，中文 subject）；
另含 62-UI-REVIEW 的 advisory UI 偏离。

| ID | 状态 | 提交 | 修复要点 |
|----|------|------|----------|
| CR-01 | fixed: requires human verification | `fix(repositories): 修复知识树重建恒跳过、build_full 永不执行` | run_page_index 改以「上次构建 active 快照 source_hash」为基线自判（首次/有变则建、未变则跳过）；rebuild view 不再传自我否定的 target_hash；新增 `CorpusTreeService.get_active_source_hash`。补端到端守护测试（rebuild view payload 驱动：首次建/未变跳/变化重建）。⚠️ 逻辑修复，建议人工复核 build/skip 判定语义。 |
| IN-01 | fixed | （并入 CR-01 提交） | run_page_index 返回值改用 build_full 落库的 `source_hash`，消除返回值与落库值分叉。 |
| WR-01 | fixed | `fix(delivery): 队列 list 在 DB 层限制最近 N 批避免全表加载` | IngestQueueView.get 先 GROUP BY batch_id 取各批最新 started_at 倒序前 N 个 batch_id（DB LIMIT），再仅拉这些批次行分组，查询有界、顺序稳定。 |
| IN-02 | fixed | `fix(delivery): 全 COMPLETED 批次 retry 跳过空 defer` | `_redefer_batch` 无可重投行时短路返回空串、不 defer，动作端点回 `dispatched=False`；补守护测试。 |
| UI 偏离 (62-UI-REVIEW) | fixed | `fix(web): 队列面板对齐 UI 契约（轮询/标题/loading）` | 轮询条件收紧为仅 `running`（合契约，避免 queued 永久空转）；移除误导性 `:title="item.batch_id"`；骨架区以 sr-only + role=status 消费此前死键 `crawlQueue.loading`（zh-CN.json 未改动，保持 additive）。 |

CR-01 配套测试语义同步另提交：`test(durable): 同步 page_index 幂等守护至基线比对语义`。

**验证结果：**
- `cd server && uv run pytest tests/durable tests/delivery tests/repositories -q`：本阶段相关用例全绿。
  剩余失败均为**预存且与本阶段无关**（已在 base commit 复现确认）：`test_plan_session_inv6_guard`
  （评审已声明，chat app 非本阶段文件）、`test_index_retry_resume`、`test_index_history_changed_files`
  （索引轨环境性失败）；`test_rebuild_repo_summaries` 为预存测试顺序污染（单独执行通过，base 亦然）。
- `cd web && pnpm vitest run src/components/knowledge`：8 passed。
- `manage.py check`：no issues；`makemigrations --check`：no changes detected。

约束遵守：业务代码无直接 `import procrastinate`；async ORM 经 `sync_to_async` / async manager；
rebuild view 保留 `IsAdminUser`；deterministic idempotency key 不变。未改动 STATE.md / ROADMAP.md。

---

_Reviewed: 2026-06-20T17:10:26Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
_Fixes: 2026-06-21 (Claude, gsd-code-fixer)_
