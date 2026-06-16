---
phase: 44-repocodingtask-execution-plan-dag-wave
reviewed: 2026-06-16T21:30:00Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - server/delivery/models/repo_coding_task.py
  - server/delivery/models/__init__.py
  - server/delivery/migrations/0017_repocodingtask.py
  - server/delivery/services/repo_coding_task_service.py
  - server/delivery/services/__init__.py
  - server/services/plan_orchestration/wave_layering.py
  - server/services/plan_orchestration/wave_progression.py
  - server/services/plan_orchestration/__init__.py
  - server/workflows/nodes/ai/coding.py
findings:
  critical: 0
  warning: 2
  info: 3
  total: 5
status: issues_found
---

# Phase 44: Code Review Report

**Reviewed:** 2026-06-16T21:30:00Z
**Depth:** standard
**Files Reviewed:** 9
**Status:** issues_found

## Summary

审查范围为 Phase 44「RepoCodingTask + execution_plan DAG wave 调度」的全部 source 文件（model / migration / service / 拓扑分层纯函数 / wave 推进 helper / AICodingNode 接线）。整体实现质量高，关键不变式守得很到位：

- **死锁/liveness（INV 重点）**：`aadvance_coding_waves` 严格按「① 回填 → ② 传递闭包阻断 → ③ 决策出口」执行，阻断在任何 early-return 之前完成。链式（A→B→C）与菱形传播均经 BFS+`seen` 去重正确收敛，`failed` 计入终态避免 gate 永挂——逐场景推演**未发现死锁**。
- **INV-6**：所有 `RepoCodingTask` 写入（建行 / 状态推进 / wave / depends_on 连边）确实只经 `RepoCodingTaskService`；`wave_progression.py` 与 `coding.py` 仅经 `service.mark_*` / `create_tasks_for_plan` 写，无旁路。grep 守护对当前代码无误报/漏报命中。
- **async ORM 安全**：回填/阻断/收尾均用 `*_id` 标量、`afirst` / `aexists` / `async for` / 反向 M2M `.filter()` async 迭代，未见 async 上下文裸访问 lazy-FK。
- **migration**：4 态枚举、索引、FK on_delete、M2M 与 model 逐字段一致；依赖 `delivery.0016` / `repositories.0036` / `subagent.0013` 均存在，无 0017 叶子冲突。
- **零回归命门**：空 `dependencies` → 全仓 wave=0、legacy 无 `plan_version_id` → 不建 RepoCodingTask 全并行，均保留。

两个 WARNING 集中在「半可信输入下 DAG 边与 wave 分层的一致性」与「回调并发下 dispatch 副作用的幂等性」——状态写本身幂等，但派发（建容器/SubAgentSession）这一副作用未受同等保护。

## Warnings

### WR-01: `build_repo_dep_edges` 不按 `id` 过滤任务，可生成「同 wave 跨仓依赖边」绕过首发派发的 wave 保证

**File:** `server/services/plan_orchestration/wave_layering.py:104-109`

**Issue:**
`build_repo_waves` 在构造任务级 DAG 时**只纳入有 `id` 的任务**（`for t in execution_plan if t.get("id")`，行 49-59），而 `build_repo_dep_edges` 的成边循环**不做同样过滤**：

```python
for t in execution_plan:              # 未过滤 t.get("id")
    ra = t.get("repository_id", "")
    for dep in (t.get("dependencies") or []):
        rb = task_repo.get(dep, "")
        if ra and rb and ra != rb:
            edges.setdefault(ra, set()).add(rb)
```

后果链（半可信 LLM 合成 plan）：一个**无 `id` 但有 `repository_id` + `dependencies`** 的任务会贡献一条仓级 `depends_on` 边，但因被分层排除而**不抬高该仓 wave**。若该仓同时还有一个 `id` 的 wave0 任务，则 `repo_waves[ra]==0`、`wave_mode` 仍为 True（`coding.py:376-380` 的 `all(rid in repo_waves ...)` 通过），而 `coding.py` 首发派发是：

```python
current_wave = min(repo_waves.values())            # 0
dispatch_repo_ids = [rid for rid in repo_groups if repo_waves.get(rid) == current_wave]
```

首发**不校验 `depends_on`**，依赖「min wave 仓无未满足依赖」这一由分层保证的不变式。该不变式被上面不一致打破后，会出现「`ra`（含 depends_on 边）与其依赖仓 `rb` 在 wave0 被同批并行 dispatch」，即依赖顺序被忽略。wave 推进段 `_collect_dispatchable_pending` 会校验 `depends_on`，但**首发段不会**，故 wave0 这一批是漏洞窗口。

**Fix:** 让 `build_repo_dep_edges` 与 `build_repo_waves` 采用同一过滤口径，仅对有 `id` 的任务成边：

```python
def build_repo_dep_edges(execution_plan: list[dict]) -> dict[str, list[str]]:
    task_repo = {
        t["id"]: t.get("repository_id", "")
        for t in execution_plan
        if t.get("id")
    }
    edges: dict[str, set[str]] = {}
    for t in execution_plan:
        if not t.get("id"):          # 与 build_repo_waves 一致：无 id 任务不参与建边
            continue
        ra = t.get("repository_id", "")
        for dep in (t.get("dependencies") or []):
            rb = task_repo.get(dep, "")
            if ra and rb and ra != rb:
                edges.setdefault(ra, set()).add(rb)
    return {rid: sorted(deps) for rid, deps in edges.items()}
```

（可选加固：`coding.py` 首发派发也对 `dispatch_repo_ids` 做一次「该仓所有 `depends_on` 是否同在本 wave」的断言/日志，避免未来再出现 wave 与边不一致时静默违序。）

### WR-02: 回调并发重入下，wave 派发副作用非幂等（可能重复建容器 / 重复 MR）

**File:** `server/services/plan_orchestration/wave_progression.py:116-120`, `server/workflows/nodes/ai/coding.py:826-836`, `server/delivery/services/repo_coding_task_service.py:86-94`

**Issue:**
状态写已做幂等（`mark_done` / `mark_blocked` 用条件更新 + 影响行数判定；`create_tasks_for_plan` 用 `get_or_create`），但**派发这一外部副作用未受同等保护**：

- `aadvance_coding_waves` 的 step 3b 选出 `dispatch` 批时，这些 task 在 DB 里仍是 `pending`，**返回到 mark_running 落库之间存在时间窗**。
- `mark_running`（`_mark_running_sync`）是**无条件** `task.status = RUNNING; save(...)`，没有 `pending→running` 的条件守门。
- 若同一 wave 多个容器近乎同时完成、`_schedule_workflow_resume` 触发**两次并发节点重入**，两次 `aadvance` 都可能在任一方 `mark_running` 落库前读到相同的 `pending` 可派发集合，于是**各自 dispatch 一次**→ 同一仓建两个 SubAgentSession / 两个容器，收尾阶段可能产出两个 MR。

`waiting` 判定 keys off `RUNNING`（step 3a），在严格串行的回调下能正确收敛；但本 phase 的设计明确依赖「复用 Phase 43 回调续驱」，其重入串行性是该幂等论证的隐含前提，源码层未自证。

**Fix（任一即可，建议都做）:**

1. 给 `mark_running` 加 `pending→running` 条件守门，使重复/并发 dispatch 的状态回填天然 no-op（与 `mark_done` 同范式），并让调用方据影响行数决定是否真正建容器：

```python
@sync_to_async
def _mark_running_sync(self, task, subagent_session) -> int:
    return RepoCodingTask.objects.filter(
        id=task.id, status=RepoCodingTaskStatus.PENDING
    ).update(
        status=RepoCodingTaskStatus.RUNNING,
        subagent_session=subagent_session,
        updated_at=timezone.now(),
    )
```

2. 在派发前以原子 `pending→running` 占位（claim）后再 dispatch，仅对 claim 成功（影响 1 行）的 task 真正建容器；或在 `_resume_wave` 入口对该 `plan_version` 加 `select_for_update` / 节点级串行锁，确认 Phase 43 续驱对同一 node 不会并发重入。请显式验证并在注释中记录该串行性保证。

## Info

### IN-01: INV-6 grep 守护正则无法拦截链式 `RepoCodingTask.objects.filter(...).update(...)`

**File:** `server/tests/delivery/test_repo_coding_task_inv6_guard.py:32-35`

**Issue:** `_RE_ORM_WRITE` 要求 `update` 紧跟 `.objects.`，故 `RepoCodingTask.objects.filter(...).update(...)` 这类链式写**不会被命中**。当前生产代码无此模式（service 内部的 `.filter().update()` 在 allowed writer 中，合规），故无实际违规；但守护存在盲点，未来若有人在非 allowed 文件用链式 `.filter().update()` 旁路写，守护会漏报。

**Fix:** 增补一个宽松正则覆盖链式写，例如 `re.compile(r"\bRepoCodingTask\.objects\b.*\.update\(")`（多行/同行均扫），或显式断言「除 allowed writer 外无 `RepoCodingTask.objects` 后跟 `.update(` 的行」。

### IN-02: migration 头注释为 "Django 6.0.1"，与 STACK 声明的 `django>=5.1` 不一致

**File:** `server/delivery/migrations/0017_repocodingtask.py:1`

**Issue:** 文件头 `# Generated by Django 6.0.1`，而项目栈文档（AGENTS.md/STACK）写 `django>=5.1`。migration 内容本身版本无关、可正常运行，但生成环境与部署声明版本的漂移会让团队在排查兼容性时困惑。

**Fix:** 确认本地/CI 实际 Django 版本与 `pyproject.toml` 约束一致；如确为 6.0.x，更新 STACK/约束文档使其与实际一致（仅文档对齐，非代码缺陷）。

### IN-03: `_dispatch_wave` 在 SubAgentSession 查不到时静默跳过 `mark_running`

**File:** `server/workflows/nodes/ai/coding.py:599-605`

**Issue:**
```python
sess = await SubAgentSession.objects.filter(session_id=s["session_id"]).afirst()
if sess is not None:
    await service.mark_running(task, sess)
```
若 `afirst()` 返回 `None`，则该仓虽已进入 `waiting_sessions`（容器视为已派发），但其 task 仍停留 `pending`，无 `subagent_session_id`。后续 resume 的回填只遍历 `running` task → 该 task 不被回填；`_collect_dispatchable_pending` 可能将其当作可派发再次 dispatch（重复建容器）。

实践中 `_run_repo_coding._create_session()` 在 dispatch 前已 `aupdate_or_create(session_id=...)` 且 `session_id` 唯一并被 await，故正常路径 `sess` 不会为 `None`，可达性极低；列为 INFO 以记录该隐含前提。

**Fix:** 当 `sess is None` 但该仓确已计入 `waiting_sessions` 时，记 warning 并将该 task 经 `service.mark_failed(task, {"reason": "session_missing"})` 标终态（避免悬挂 pending 致重复派发），而非静默跳过。

---

_Reviewed: 2026-06-16T21:30:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
