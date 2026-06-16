# Phase 45: 上游产物提取 + 注入下游 wave - Pattern Map

**Mapped:** 2026-06-16
**Files analyzed:** 12 (3 new source + 3 modified source + 6 new/extended tests)
**Analogs found:** 12 / 12

所有新文件均在 `server/services/plan_orchestration/` 纯函数包、`RepoCodingTaskService` 单一写入入口、`AICodingNode` 既有 dispatch 链内有直接同包/同类 analog。无「无 analog」文件。

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `server/services/plan_orchestration/artifact_extraction.py` (NEW) | utility (纯函数) | transform | `server/services/plan_orchestration/wave_layering.py` | exact (同包纯函数 transform) |
| `server/services/plan_orchestration/artifact_injection.py` (NEW) | utility (async collect + 纯渲染) | transform / request-response | `server/services/plan_orchestration/wave_progression.py` (async collect) + `wave_layering.py` (纯渲染) | exact |
| `server/services/plan_orchestration/wave_progression.py` (MODIFY) | service helper (推进) | event-driven | self — `_backfill_running_terminal` (line 126) | self-extension |
| `server/delivery/services/repo_coding_task_service.py` (MODIFY) | service | CRUD | self — `mark_done`/`_mark_done_sync` (line 106-115) | self-extension |
| `server/workflows/nodes/ai/coding.py` (MODIFY) | workflow node | event-driven / request-response | self — `_dispatch_next_wave`/`_dispatch_wave`/`_run_repo_coding`/`_build_coding_prompt` | self-extension |
| `server/services/plan_orchestration/__init__.py` (MODIFY) | config (barrel) | — | self — `build_repo_waves`/`aadvance_coding_waves` exports | self-extension |
| `server/tests/services/plan_orchestration/test_artifact_extraction.py` (NEW) | test (unit, DB-free) | transform | `server/tests/services/plan_orchestration/test_wave_layering.py` | exact |
| `server/tests/services/plan_orchestration/test_artifact_injection.py` (NEW) | test (unit, DB-free) | transform | `test_wave_layering.py` | exact |
| `server/tests/delivery/test_repo_coding_task_service.py` (EXTEND) | test (unit, django_db) | CRUD | self — `test_mark_done_idempotent` (line 80) | self-extension |
| `server/tests/delivery/test_repo_coding_task_inv6_guard.py` (EXTEND) | test (源码扫描守护) | batch | self — `_RE_ORM_WRITE` 守护 (line 31-41) | self-extension |
| `server/tests/test_coding_node.py` (EXTEND) | test (unit) | request-response | self — 既有 `_build_coding_prompt` prompt 断言 | self-extension |
| `server/tests/test_coding_wave.py` (EXTEND) | test (integration, mock IO) | event-driven | self — `test_multi_wave_progression` (line 247) + `_settle_session` (line 172) | self-extension |

## Pattern Assignments

### `server/services/plan_orchestration/artifact_extraction.py` (utility, transform)

**Analog:** `server/services/plan_orchestration/wave_layering.py`（同包纯函数蓝本：`from __future__`、模块 docstring 声明「纯函数 无 IO/无 ORM」、`__all__` 显式导出、半可信输入逐字段 `.get`/`or []` 防御、fail-safe 不抛异常）。

**模块头 + `__all__` pattern**（`wave_layering.py:1-21`）:

```17:21:server/services/plan_orchestration/wave_layering.py
from __future__ import annotations

from graphlib import CycleError, TopologicalSorter

__all__ = ["build_repo_dep_edges", "build_repo_waves"]
```

**半可信输入逐字段防御 pattern**（`wave_layering.py:48-59` — `.get(..., "")` / `or []`，缺字段跳过，绝不抛）:

```48:59:server/services/plan_orchestration/wave_layering.py
    # task id → 所属仓（半可信防御：缺 id 跳过）。
    task_repo = {
        t["id"]: t.get("repository_id", "")
        for t in execution_plan
        if t.get("id")
    }
    # 任务级 DAG：task → 它依赖的 task（仅保留指向已知 task 的有效引用）。
    task_deps = {
        t["id"]: [d for d in (t.get("dependencies") or []) if d in task_repo]
        for t in execution_plan
        if t.get("id")
    }
```

**产物来源字段权威**（`subagent/models.py:280-287` — `build_produced_artifacts` 只读 TaskResult 已物化的 git 字段，绝不接 lazy ORM）:

```280:287:server/subagent/models.py
    # Git 产物（coding）
    branch_name = models.CharField(max_length=255, blank=True, default="")
    commit_sha = models.CharField(max_length=64, blank=True, default="")
    pr_url = models.URLField(blank=True, default="")
    modified_files = models.JSONField(default=list, blank=True, verbose_name="修改文件列表")

    # 原始输出（完整 result.json 内容）
    raw_output = models.JSONField(default=dict, blank=True, verbose_name="原始输出")
```

**To build:** 纯函数 `build_produced_artifacts(*, repository_id, repository_name, task_result) -> dict` + `classify_modified_files(modified_files) -> tuple[list, list]`（路径启发式归类，纯字符串匹配）。`task_result=None` → 落 `{"available": False}` 占位（D-02）。完整骨架见 RESEARCH.md「提取纯函数」Code Example（line 350-405）。绝不存 token/凭证（只 path/url/计数）。

---

### `server/services/plan_orchestration/artifact_injection.py` (utility, async collect + 纯渲染)

**Analog (async collect):** `wave_progression.py:190-208` `_collect_dispatchable_pending` —— async-safe M2M 反查范式（`async for task in ...filter(...)` + `task.depends_on.exclude(...)`，绝不裸迭代 lazy M2M）。

```196:208:server/services/plan_orchestration/wave_progression.py
    from delivery.models import RepoCodingTask, RepoCodingTaskStatus

    dispatchable: list = []
    async for task in RepoCodingTask.objects.filter(
        plan_version_id=plan_version_id,
        status=RepoCodingTaskStatus.PENDING,
    ):
        has_unmet = await task.depends_on.exclude(
            status=RepoCodingTaskStatus.DONE
        ).aexists()
        if not has_unmet:
            dispatchable.append(task)
    return dispatchable
```

**Analog (反向/正向 M2M async 迭代):** `wave_progression.py:178-187` `_block_downstream_transitive` —— `async for downstream in upstream.dependents.filter(...)` 证明 `async for x in task.<m2m>.all()/filter()` 是仓内既定安全范式（`acollect_upstream_artifacts` 用 `async for u in task.depends_on.all()` 对称）:

```178:187:server/services/plan_orchestration/wave_progression.py
        # 反查 dependents（依赖我者）中仍 pending 的下游；async for 安全迭代反向 M2M。
        async for downstream in upstream.dependents.filter(
            status=RepoCodingTaskStatus.PENDING
        ):
            await service.mark_blocked(downstream, [upstream_id])
            # downstream 现已 failed（blocked）→ 继续向其 dependents 传播（多跳传递闭包）。
            did = str(downstream.id)
            if did not in seen:
                seen.add(did)
                worklist.append(downstream)
```

**Analog (纯文本渲染 + 空守卫):** `coding.py:1580-1610` `_build_files_section` —— 纯渲染 helper，`if not any(...): return ""`（空 → 空串），逐行 append 拼 `"\n".join(lines)`。`render_upstream_artifacts_section` 直接镜像此结构（空 → `""`，零回归命门）:

```1596:1610:server/workflows/nodes/ai/coding.py
        if not any(files_by_action.values()):
            return ""

        lines = ["# 涉及文件"]
        for action, label in [
            ("create", "创建"),
            ("modify", "修改"),
            ("delete", "删除"),
        ]:
            if files_by_action[action]:
                lines.append(f"\n## {label}")
                for path in files_by_action[action]:
                    lines.append(f"- `{path}`")

        return "\n".join(lines)
```

**To build:** `async def acollect_upstream_artifacts(task) -> list[dict]`（沿直接 `depends_on` async 反查 `produced_artifacts`，跳过空/占位；建议末尾 `sorted(key=repository_id)` 保渲染确定性见 RESEARCH Open Q2）+ `def render_upstream_artifacts_section(artifacts) -> str`（空 → `""`）。完整骨架见 RESEARCH.md「收集 + 渲染」Code Example（line 408-449）。`__all__` 显式导出二者。

---

### `server/services/plan_orchestration/wave_progression.py` (MODIFY — `_backfill_running_terminal`)

**Self-extension:** 在已有 `_backfill_running_terminal` 循环（line 126-154）的 `await service.mark_done(task)`（line 144）**之后**追加 fail-soft 提取段。`sess`（line 139 已取出）直接复用。

**注入点上下文**（line 139-153，`mark_done` 在 143-144）:

```139:153:server/services/plan_orchestration/wave_progression.py
        sess = await SubAgentSession.objects.filter(id=sid).afirst()
        if sess is None:
            continue
        sess_status = str(sess.status)
        if sess_status in _SUBAGENT_DONE:
            await service.mark_done(task)
        elif sess_status in _SUBAGENT_FAILED:
            await service.mark_failed(
                task,
                {
                    "reason": "container_failed",
                    "subagent_status": sess_status,
                    "error": sess.last_error or "",
                },
            )
```

**fail-soft async ORM 安全约束（模块 docstring 已立，line 20-21）:** `*_id` 标量 / `afirst` / `aexists` / `async for`，绝不裸访问 lazy-FK。提取段用 `TaskResult.objects.filter(session=sess).afirst()` + `Repository.objects.filter(id=task.repository_id).afirst()`，整段独立 `try/except` `logger.warning` 降级（绝不向外冒泡 — Pitfall 3）。完整骨架见 RESEARCH.md Pattern 1（line 194-230）。

**关键约束（Pitfall）:**
- 提取**只挂此处**（D-01 唯一 done 收口）；不在 `mark_failed` 分支提取（A2：failed 仓无成功产物）。
- 提取段 try/except 独立于 `mark_done`（mark_done 成功后即使提取失败 task 仍正确 done）。
- 绝不在此文件直接写 `task.produced_artifacts`（必须经 `service.record_produced_artifacts` — D-14 字段级守护会拦）。

---

### `server/delivery/services/repo_coding_task_service.py` (MODIFY — `record_produced_artifacts`)

**Self-extension:** 镜像 `mark_done`/`_mark_done_sync`（line 106-115）的「async public + `@sync_to_async` private + `filter().update()`」三段范式。

**镜像蓝本**（`mark_done` 范式，line 106-115）:

```106:115:server/delivery/services/repo_coding_task_service.py
    async def mark_done(self, task: RepoCodingTask) -> None:
        """task.status→done（条件更新幂等：仅 running→done，重复 callback no-op）。"""
        await self._mark_done_sync(task)

    @sync_to_async
    def _mark_done_sync(self, task: RepoCodingTask) -> int:
        # 条件更新：仅 running→done；影响行数 0 → no-op（已 done / 非 running 不报错）。
        return RepoCodingTask.objects.filter(
            id=task.id, status=RepoCodingTaskStatus.RUNNING
        ).update(status=RepoCodingTaskStatus.DONE, updated_at=timezone.now())
```

**To build:** `record_produced_artifacts(task, artifacts)` + `@sync_to_async _record_produced_artifacts_sync`，用 `RepoCodingTask.objects.filter(id=task.id).update(produced_artifacts=artifacts, updated_at=timezone.now())`。完整骨架见 RESEARCH.md Pattern 3（line 243-254）。

**关键约束（Pitfall 4）:** **不**加 `status=RUNNING` guard（提取发生在 `mark_done` 之后 task 已 done，加 guard 会影响 0 行写不进）。用 `.objects.filter(id=...).update(...)`（**不**用 `task.produced_artifacts=...; task.save()` — 既符合 INV-6 grep 守护对允许 writer 文件的 `.objects.update` 正向覆盖，又避免 D-14 字段级旁路写盲区）。`timezone` 已 import（line 25），`structlog logger` 已就绪（line 29）。

---

### `server/workflows/nodes/ai/coding.py` (MODIFY — dispatch 链透传)

**Self-extension:** 4 个既有方法增 defaulted 参数透传，**零回归命门**靠 defaulted 参数 + 空段不渲染。

**1. `_build_coding_prompt`（line 1534-1578）— 注入段（D-08）:** 现 parts 顺序 `global_context(1546) → 分支(1549) → 任务 → 文件(1566) → 要求`。新增 `upstream_artifacts: list[dict] | None = None`，在 `global_context` 之后插非空上游段（守卫范式逐字对齐既有 `files_section`，line 1566-1568）:

```1544:1568:server/workflows/nodes/ai/coding.py
        parts: list[str] = []

        if global_context:
            parts.append(f"# 项目背景\n\n{global_context}")

        parts.append(f"# 分支信息\n\n目标分支: `{branch_name}`")
        ...
        # 文件列表
        files_section = self._build_files_section(tasks)
        if files_section:
            parts.append(files_section)
```

新增段守卫（对齐上面 `if files_section:`）:
```python
        upstream_section = render_upstream_artifacts_section(upstream_artifacts or [])
        if upstream_section:                # 空 → 不 append（零回归，对齐 files_section 守卫）
            parts.append(upstream_section)
```
完整改造见 RESEARCH.md「零回归注入」Code Example（line 453-469）。

**2. `_run_repo_coding`（line 1338-1357）— 透传:** 现已是 defaulted-kwargs 签名范式（`node_execution_id=""`/`anthropic_api_key=""` 等，line 1346-1349），新增 `upstream_artifacts: list[dict] | None = None` 同范式；在 `prompt = self._build_coding_prompt(tasks, global_context, branch_name)`（line 1357）增传 `upstream_artifacts=upstream_artifacts`:

```1357:1357:server/workflows/nodes/ai/coding.py
        prompt = self._build_coding_prompt(tasks, global_context, branch_name)
```

**3. `_dispatch_wave`（line 520-560）— 透传:** 现循环 `_run_repo_coding(...)`（line 546-559）。新增 `upstream_artifacts_by_repo: dict[str, list[dict]] | None = None`（**默认 None/`{}` 保首发 wave 0 零回归**），调用处增 `upstream_artifacts=(upstream_artifacts_by_repo or {}).get(repo_id, [])`:

```546:560:server/workflows/nodes/ai/coding.py
        coding_tasks = [
            self._run_repo_coding(
                repository=repositories[repo_id],
                tasks=repo_groups[repo_id],
                branch_name=branch_name,
                base_branch=base_branch,
                global_context=global_context,
                config=config,
                node_execution_id=node_execution_id,
                anthropic_api_key=anthropic_api_key,
                anthropic_base_url=anthropic_base_url,
                user_pat=user_pat,
            )
            for repo_id in repo_ids
        ]
```

**4. `_dispatch_next_wave`（line 844-907）— 收集上游（唯一注入收集点 D-07）:** 现已建 `tasks_by_repo`（line 856）并调 `_dispatch_wave`（line 885-900）。在调 `_dispatch_wave` 前沿 `tasks_by_repo` 收集 `acollect_upstream_artifacts(task)`，传入 `_dispatch_wave(..., upstream_artifacts_by_repo=...)`:

```855:868:server/workflows/nodes/ai/coding.py
        dispatch_tasks = result.get("dispatch", [])
        tasks_by_repo = {str(t.repository_id): t for t in dispatch_tasks}
        dispatch_repo_ids = list(tasks_by_repo.keys())
        ...
        service = RepoCodingTaskService()
```

收集（RESEARCH line 472-481）:
```python
        upstream_by_repo: dict[str, list[dict]] = {}
        for repo_id, task in tasks_by_repo.items():
            upstream_by_repo[repo_id] = await acollect_upstream_artifacts(task)
```

**关键约束:**
- 首发 wave 0 经 `_execute_with_branch` 调 `_dispatch_wave` **不传** `upstream_artifacts_by_repo`（默认 `{}` → 各仓 `[]` → prompt 逐字等价，Pitfall 2 零回归）。只有 `_dispatch_next_wave`（wave 推进）收集并传。
- import 在方法内局部 import（对齐既有 `from delivery.services import RepoCodingTaskService` line 852 范式），避免模块级循环 import。
- 容器 prompt 即编码上下文，不新增第二条 global_context 通道（D-08）。

---

### `server/services/plan_orchestration/__init__.py` (MODIFY — barrel)

**Self-extension:** 镜像既有 `from services.plan_orchestration.wave_layering import (...)` + `from services.plan_orchestration.wave_progression import (...)` 导入块（line 52-59）与 `__all__` 追加（line 91-94）。

```52:59:server/services/plan_orchestration/__init__.py
from services.plan_orchestration.wave_layering import (
    build_repo_dep_edges,
    build_repo_waves,
)
from services.plan_orchestration.wave_progression import (
    aadvance_coding_waves,
    acurrent_wave_all_terminal,
)
```

```91:94:server/services/plan_orchestration/__init__.py
    "build_repo_waves",
    "build_repo_dep_edges",
    "acurrent_wave_all_terminal",
    "aadvance_coding_waves",
```

**To add:** import + `__all__` 追加 `build_produced_artifacts`、`classify_modified_files`（来自 `artifact_extraction`）、`acollect_upstream_artifacts`、`render_upstream_artifacts_section`（来自 `artifact_injection`）。

---

### `server/tests/services/plan_orchestration/test_artifact_extraction.py` (NEW — unit, DB-free)

**Analog:** `test_wave_layering.py` —— 纯函数测试，**无 `django_db`、无 IO**，模块 docstring 声明覆盖场景 + 小 `_task(...)` factory helper + 直接 import from barrel。

```1:13:server/tests/services/plan_orchestration/test_wave_layering.py
"""wave_layering 拓扑分层纯函数单测（Phase 44-02，WAVE-01）。

覆盖 5 场景：空依赖零回归 / 线性链 / 菱形 / 环 fail-fast / 同仓取 max。
纯函数测试，无 ``django_db``、无 IO。
"""

from __future__ import annotations

from services.plan_orchestration import build_repo_dep_edges, build_repo_waves


def _task(tid: str, repo: str, deps: list[str] | None = None) -> dict:
    return {"id": tid, "repository_id": repo, "dependencies": deps or []}
```

**To build (D-11):** 构造**未保存**的 `TaskResult(result_type="git", modified_files=[...])` 内存实例（不触 DB，A3）测 `build_produced_artifacts`。场景：① git TaskResult 含 openapi/proto/schema 路径 → 正确归类 `api_contracts`/`openapi`；② `task_result=None` → `{"available": False}` 占位不抛；③ 空 `modified_files` → 结构合法各桶空、`diff_summary.files_changed==0`。

---

### `server/tests/services/plan_orchestration/test_artifact_injection.py` (NEW — unit, DB-free)

**Analog:** 同 `test_wave_layering.py`（纯函数测试范式）。

**To build (D-12):** 测 `render_upstream_artifacts_section` 纯函数（无 `django_db`）：多上游 dict → 段含各仓 `repository_name`/契约文件名；空 list → 返回 `""`（零回归命门断言）。

---

### `server/tests/delivery/test_repo_coding_task_service.py` (EXTEND — unit, django_db)

**Self-extension:** 追加 `test_record_produced_artifacts`，镜像 `test_mark_done_idempotent`（line 80-97）的「create → mark_running → 操作 → aget 重读断言 → 重复操作断言幂等」流程；复用既有 `_make_repo`/`_make_plan_version` helper（line 28-40）。

```80:97:server/tests/delivery/test_repo_coding_task_service.py
@pytest.mark.asyncio
async def test_mark_done_idempotent() -> None:
    """running→done 第一次成功；对已 done task 再 mark_done → no-op 不报错、仍 done。"""
    plan_version = await _make_plan_version()
    repo = await _make_repo()
    rid = str(repo.id)
    svc = RepoCodingTaskService()
    tasks = await svc.create_tasks_for_plan(plan_version, {rid: 0}, {})
    task = tasks[rid]
    await svc.mark_running(task, None)

    await svc.mark_done(task)
    reread = await RepoCodingTask.objects.aget(id=task.id)
    assert reread.status == RepoCodingTaskStatus.DONE

    # 重复 mark_done → no-op，不抛、status 仍 done。
    await svc.mark_done(task)
    reread2 = await RepoCodingTask.objects.aget(id=task.id)
    assert reread2.status == RepoCodingTaskStatus.DONE
```

**To build (D-05):** done task 写 `produced_artifacts`（无 status guard，done task 可写）→ aget 重读断言 `produced_artifacts == {...}`；重复写同产物 → 覆盖式 no-op 语义（再 aget 断言不变）。

---

### `server/tests/delivery/test_repo_coding_task_inv6_guard.py` (EXTEND — 源码扫描守护)

**Self-extension:** 现守护正则（line 31-41）拦 `.objects.<write>` / 实例化 / 链式 save，但 **拦不住** `task.produced_artifacts = {...}; task.save(...)` 字段赋值旁路（Pitfall 6）。

```31:41:server/tests/delivery/test_repo_coding_task_inv6_guard.py
# A：RepoCodingTask.objects.<write>
_RE_ORM_WRITE = re.compile(
    r"\bRepoCodingTask\.objects\."
    r"(?:create|bulk_create|get_or_create|update_or_create|update)\b"
)
# B：直接实例化（"\s*\(" 紧跟；case-sensitive 天然排除 RepoCodingTaskStatus( ——
#    它以 RepoCodingTaskStatus 开头，正则 \bRepoCodingTask\s*\( 在 "Status" 处不匹配
#    \s*\( 故安全，枚举非写）
_RE_INSTANTIATE = re.compile(r"\bRepoCodingTask\s*\(")
# C：链式实例化 + save
_RE_INSTANCE_SAVE = re.compile(r"\bRepoCodingTask\([^)]*\)\.save\(")
```

`_is_scanned`（line 53-62）与 `_ALLOWED_WRITER`（line 29）控制扫描范围。

**To build (D-14):** 新增正则 `\.produced_artifacts\s*=`（字段赋值），断言只允许出现在 `_ALLOWED_WRITER`（service）+ `delivery/models/`（模型字段定义）中，否则 fail——把字段级旁路写纳入守护。沿用 `_iter_py_files`/`_is_scanned` 扫描框架。

---

### `server/tests/test_coding_node.py` (EXTEND — unit)

**Self-extension:** 追加 `_build_coding_prompt` 带/不带 `upstream_artifacts` 两测。**零回归逐字断言** 是命门（不带 → prompt 与现行为字节级一致）。

**To build (D-12):** ① 带非空 `upstream_artifacts` → prompt 含「上游产物」段 + 上游契约文件名 + 段位于 global_context 之后；② 不带（`None`/`[]`） → prompt 与基线**逐字一致**（直接构造期望字符串断言 `==`，防 Pitfall 2 空段漂移）。

---

### `server/tests/test_coding_wave.py` (EXTEND — integration, mock IO)

**Self-extension:** 追加 D-13 端到端，复用既有 `_dispatched`（line 66-86）+ `_stub_provider_resolution`（line 46-63）fixture + `_settle_session`（line 172-185）+ `_resume`（line 188-190）+ `_make_plan_version`/`_make_repo` harness；蓝本 = `test_multi_wave_progression`（line 247）。

**`_settle_session` 已建 TaskResult（line 172-185）— D-13 直接复用/扩展含 openapi 文件:**

```172:185:server/tests/test_coding_wave.py
async def _settle_session(plan_version: PlanVersion, repo_id: str, *, ok: bool) -> None:
    """把某仓 RepoCodingTask 关联的 SubAgentSession 置终态（模拟容器完成）。"""
    task = await RepoCodingTask.objects.aget(plan_version=plan_version, repository_id=repo_id)
    sess = await SubAgentSession.objects.aget(id=task.subagent_session_id)
    sess.status = SubAgentSession.Status.COMPLETED if ok else SubAgentSession.Status.ERROR
    sess.last_error = "" if ok else "container boom"
    await sess.asave(update_fields=["status", "last_error"])
    if ok:
        await TaskResult.objects.acreate(
            session=sess,
            pr_url=f"https://mr/{repo_id}",
            modified_files=["f.py"],
            raw_output={},
        )
```

**dispatch prompt 断言锚点（捕获 DispatchTask）:** `_dispatched_repo_ids`（line 193-194）经 `t.metadata["repository_id"]` 取，证明 DispatchTask metadata 是断言面 → D-13 断言 wave2 DispatchTask 的 prompt/metadata 含 wave1 契约文件名。

**To build (D-13/D-15):** 构造 wave1 后端 + wave2 前端（`depends_on` 跨仓边，蓝本 `test_multi_wave_progression`）；wave1 `_settle_session(ok=True)` 的 TaskResult `modified_files` 含 openapi 文件 → resume 触发提取落 `produced_artifacts` → resume 推进 wave2 dispatch → 断言捕获的 wave2 DispatchTask `prompt`/`metadata` 含 wave1 契约；另加 fail-soft 测（提取异常 → wave 仍推进、注入段空）。

## Shared Patterns

### async ORM 安全（async 上下文绝不裸访问 lazy-FK/M2M）
**Source:** `wave_progression.py:20-21`（docstring 约束）、`wave_progression.py:139`（`*_id` 标量 + `afirst`）、`wave_progression.py:179`（`async for ... .filter()`）
**Apply to:** `artifact_extraction`（入参用已物化标量/TaskResult 实例）、`artifact_injection.acollect_upstream_artifacts`（`async for u in task.depends_on.all()`）、`wave_progression._backfill_running_terminal` 提取段（`TaskResult.objects.filter(session=sess).afirst()` / `Repository.objects.filter(id=task.repository_id).afirst()`）
```python
sess = await SubAgentSession.objects.filter(id=sid).afirst()   # *_id 标量 + afirst
async for downstream in upstream.dependents.filter(status=...):  # async for 安全迭代 M2M
```

### fail-soft 降级（副作用失败仅 warning，绝不冒泡使回调 5xx）
**Source:** `wave_progression.py:91`（「本函数不吞异常，由调用方包 try/except swallow」）、`coding.py:510-517`（只记 `has_*` 布尔/source，不记明文）
**Apply to:** `wave_progression._backfill_running_terminal` 提取段（独立 try/except `logger.warning`）、`coding._dispatch_next_wave` 收集（异常降级注入空段）
```python
log.info("anthropic_credential_resolved", source=credential_source,
         has_base_url=bool(validated_base_url), has_api_key=bool(resolved_api_key))
```
**关键:** 产物/日志绝不含 token/凭证，只 `has_*` 布尔/计数/path/url。

### INV-6 单一写入入口（字段写库只经 service，模型层零业务方法）
**Source:** `repo_coding_task_service.py:1-17`（模块 docstring）、`repo_coding_task.py:16-18`（模型层不写业务方法）、`test_repo_coding_task_inv6_guard.py`（grep 守护）
**Apply to:** `produced_artifacts` 写库只经 `RepoCodingTaskService.record_produced_artifacts`；`wave_progression`/`coding` 绝不直接写 `task.produced_artifacts`
```python
# 写库范式（filter().update()，在允许 writer 文件内）
return RepoCodingTask.objects.filter(id=task.id).update(
    produced_artifacts=artifacts, updated_at=timezone.now(),
)
```

### 纯函数 + 空守卫零回归（空输入 → 空串 → 不 append）
**Source:** `coding.py:1596-1610`（`_build_files_section` 空 → `""`）、`coding.py:1566-1568`（`if files_section: parts.append(...)` 守卫）
**Apply to:** `render_upstream_artifacts_section`（空 → `""`）、`_build_coding_prompt`（`if upstream_section: parts.append(...)`）
**关键:** 这是 Pitfall 2「空产物零回归」的命门——空段绝不进 `parts`（否则 `"\n\n---\n\n".join` 多空白分隔）。

### defaulted 参数透传（新参数默认 None/{}，保既有调用路径逐字不变）
**Source:** `coding.py:1346-1349`（`_run_repo_coding` 既有 defaulted kwargs 范式 `node_execution_id=""` 等）
**Apply to:** `_build_coding_prompt(upstream_artifacts=None)`、`_run_repo_coding(upstream_artifacts=None)`、`_dispatch_wave(upstream_artifacts_by_repo=None)`
**关键:** 首发 wave 0 路径不传新参 → 默认空 → prompt 字节级等价（零回归）。

## No Analog Found

无。本 phase 所有新文件均在同包/同类有直接 analog（纯函数 → `wave_layering.py`；async collect → `wave_progression.py`；service 写 → `mark_done`；node 透传 → 既有 dispatch 链；测试 → `test_wave_layering.py`/`test_repo_coding_task_service.py`/`test_coding_wave.py`）。

## Metadata

**Analog search scope:** `server/services/plan_orchestration/`、`server/delivery/services/`、`server/delivery/models/`、`server/workflows/nodes/ai/`、`server/subagent/`、`server/tests/services/plan_orchestration/`、`server/tests/delivery/`、`server/tests/`
**Files scanned:** 11（wave_layering / wave_progression / repo_coding_task_service / __init__ / coding.py 4 段 / repo_coding_task model / TaskResult model / inv6_guard test / test_wave_layering / test_repo_coding_task_service / test_coding_wave）
**Pattern extraction date:** 2026-06-16
**Out-of-scope ignored:** `.claude/worktrees/`（仓内 clone，未映射）
