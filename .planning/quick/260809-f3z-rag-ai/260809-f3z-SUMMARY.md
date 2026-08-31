---
quick_id: 260809-f3z
slug: rag-ai
subsystem: repositories
tags: [durable, index, repo-summary, charter, enqueue]

requires:

  - phase: durable-index-summary
    provides: DurableTaskService / QUEUE_INDEX / QUEUE_REPO_SUMMARY / adraft_charter
provides:

  - 建仓后自动入队 full index + AI summary（含创建者归因）
  - summary 成功回写后 durable_charter_draft 串联
  - QUEUE_CHARTER + charter-slot 并发槽位

affects: [repository-create, repo-summary-callback, charter-draft]

tech-stack:
  added: []
  patterns:

    - enqueue_* 薄 helper（幂等键 + slot lock + best-effort swallow）
    - summary → charter 归因仅信任 AgentSession.user

key-files:
  created:

    - server/repositories/index_enqueue.py
    - server/repositories/charter_enqueue.py
    - server/tests/repositories/test_create_auto_enqueue.py
    - server/tests/durable/test_charter_draft_task.py
    - server/tests/subagent/test_summary_callback_charter_enqueue.py
  modified:

    - server/repositories/views.py
    - server/repositories/summary_service.py
    - server/durable/queues.py
    - server/durable/concurrency.py
    - server/durable/handlers.py
    - server/durable/tasks.py
    - server/durable/tasks_impl.py
    - server/system/models.py
    - server/subagent/api/callbacks.py
    - server/tests/repositories/test_batch_and_reindex.py
    - server/tests/repositories/test_token_provider_fk.py
    - server/tests/durable/test_business_tasks.py

key-decisions:

  - "建仓只入队 durable_index + durable_repo_summary，从不单独入队 durable_graph"
  - "index defer 失败回滚 INDEXING/RUNNING，恢复先前 index_status"
  - "charter job：LLM 不可用/仓库不存在 → skipped 完成；persist/未预期异常 re-raise 供重试"
  - "CONCURRENCY_CHARTER_MAX 仅 SettingKeys 常量，无迁移种子，缺省回退 4"
  - "本 quick 按用户要求不 commit、不更新 STATE.md"

patterns-established:

  - "enqueue_repo_index / enqueue_charter_draft 镜像 enqueue_repo_summary"
  - "dispatch_repo_summary 写入 AgentSession.user_id 供回调归因"

requirements-completed: [CREATE-ENQUEUE-01, CREATE-ENQUEUE-02, CREATE-ENQUEUE-03]

duration: ~20min
completed: 2026-08-09
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: unknown
---

# Quick 260809-f3z：建仓自动入队索引 / AI 描述 / 章程 — 摘要

**新建仓库后 durable 同时入队 full index（RAG，图谱仍走 indexer `auto_after_index`）与 AI summary；summary 成功落库后再 best-effort 入队 `durable_charter_draft`，全程带创建者归因且不阻塞 HTTP 201。**

## 成果

- 建仓 `_acreate_repository_core`：并行语义入队 index + summary，观测事件 `repo_create_pipeline_enqueued`；外层 try 保证入队异常不破坏已创建仓库。
- `enqueue_repo_index`：`IndexHistory` RUNNING + `INDEXING` → `defer("durable_index")`；defer 失败回滚 history→FAILED、repo 恢复先前状态。
- `enqueue_repo_summary` / `dispatch_repo_summary` / `run_repo_summary`：透传 `initiated_by_user_id`；合法 User 写入 `AgentSession.user`。
- 新队列 `QUEUE_CHARTER` + `durable_charter_draft` + `enqueue_charter_draft`（幂等键 `charter:{id}`）。
- summary 成功 `asave` 后 `_resolve_initiated_user` → `enqueue_charter_draft`；失败回调不入队。
- `run_charter_draft`：`not_found` / `llm_unavailable` → skipped；`CharterPersistError` 与其它异常脱敏日志后 **re-raise**。
- 未触碰 `charter_service` 蒸馏/release-link 与 `RepoCharterSection` UI；既有未提交改动保留。

## 任务完成情况

| Task | 内容 | 提交 |
|------|------|------|
| 1 | 建仓入队 index + summary + 归因 | 未提交（按用户要求） |
| 2 | durable_charter_draft + summary 回调串联 | 未提交 |
| 3 | 聚焦测试 | 未提交 |

## 验证结果

```text
uv run ruff check <changed files>
→ All checks passed!

uv run pytest \
  tests/repositories/test_create_auto_enqueue.py \
  tests/durable/test_charter_draft_task.py \
  tests/subagent/test_summary_callback_charter_enqueue.py \
  tests/repositories/test_batch_and_reindex.py \
  tests/repositories/test_token_provider_fk.py \
  tests/durable/test_business_tasks.py \
  tests/repositories/test_charter_service.py \
  tests/test_repositories.py \
  -q --tb=line
→ 98 passed, 2 deselected, 50 warnings in 246.96s
```

（2 deselected = `postgres_queue` 标记用例，默认套件排除。）

## 偏差

### 自动修复

1. **[Rule 2]** 建仓入队外层再包 try/except，防止 helper 回归时已建仓却返回 500。
2. **[Rule 3]** index defer 失败回滚 INDEXING/RUNNING（对齐 reindex-all）。
3. **[Rule 3]** Postgres `DURABLE_TASK_BACKEND=auto` 下既有 in-process 契约测会误走 procrastinate；为 `test_business_tasks` / charter adapter 强制 `use_procrastinate_backend=False`。

### 未做（按用户约束）

- 未 git commit
- 未更新 `.planning/STATE.md` / ROADMAP

## 残留风险

- Procrastinate worker 需消费新队列名 `charter`（部署/KEDA 队列列表若硬编码需补齐，否则 charter 任务会积压）。
- `CONCURRENCY_CHARTER_MAX` 无 UI/种子，运维需手动写 SystemSetting 才能调并发；缺省 4。
- 建仓 index 幂等键 `index:{id}`：若用户几乎同时再点「触发索引」，在途去重可能吞掉第二次（既有 index 语义，非本 quick 引入）。
- summary 归因依赖 `AgentSession.user`；历史已派发、未写 user 的会话回调仍记 `system`。

## Self-Check: PASSED

- [x] `server/repositories/index_enqueue.py` 存在
- [x] `server/repositories/charter_enqueue.py` 存在
- [x] 三份新测试文件存在
- [x] 聚焦 pytest 98 passed
- [x] Ruff 通过
- [x] 无新 commit；既有 charter UI / release-link 未提交文件仍在工作区
