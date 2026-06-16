# Phase 44: RepoCodingTask + execution_plan DAG 拓扑分层 + wave 调度 - Pattern Map

**Mapped:** 2026-06-16
**Files analyzed:** 11 (new/modified)
**Analogs found:** 11 / 11（全部有强分析对象，纯内部新增能力，无外部依赖）

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `server/delivery/models/repo_coding_task.py` | model | CRUD (persistence) | `server/delivery/models/research_task.py` (`RepoResearchTask`) | exact |
| `server/delivery/models/__init__.py` | barrel/config | — | 同文件现有 `research_task` 导出块 | exact |
| `server/delivery/migrations/0017_repocodingtask.py` | migration | DDL | `server/delivery/migrations/0013_reporesearchtask_partialplan.py` | exact |
| `server/delivery/services/repo_coding_task_service.py` | service | CRUD (write-entry, INV-6) | `server/delivery/services/research_service.py` (`ResearchService`) | exact |
| `server/delivery/services/__init__.py` | barrel/config | — | 同文件现有 `ResearchService` 导出块 | exact |
| `server/services/plan_orchestration/wave_layering.py` | service/pure-fn | transform (graph) | `server/services/plan_orchestration/plan_validator.py` (`_check_acyclic`/`validate_plan`) | role+flow |
| `server/services/plan_orchestration/wave_progression.py` | service/pure-fn | event-driven (barrier) | `research_aggregation.py` (`amaybe_complete_research`) + `resume.py` (`adrive_*`) | role+flow |
| `server/workflows/nodes/ai/coding.py` (MODIFY) | workflow node | event-driven (dispatch+resume) | 自身 `_execute_with_branch` / `_resume_after_containers` + `research_adapter.dispatch` | self |
| `server/tests/delivery/test_repo_coding_task_models.py` | test | unit | 现有 delivery 模型测试 | role-match |
| `server/tests/delivery/test_repo_coding_task_service.py` | test | unit | 现有 service 状态推进测试 | role-match |
| `server/tests/delivery/test_repo_coding_task_inv6_guard.py` | test | unit (source scan) | `server/tests/delivery/test_research_inv6_guard.py` | exact |
| `server/tests/services/plan_orchestration/test_wave_layering.py` | test | unit | plan_validator 测试范式 | role-match |
| `server/tests/services/plan_orchestration/test_wave_progression.py` | test | unit/integration | research_aggregation 测试范式 | role-match |

---

## Pattern Assignments

### `server/delivery/models/repo_coding_task.py` (model, CRUD)

**Analog:** `server/delivery/models/research_task.py`（同 app 姊妹模型，逐项镜像）

**Imports + 状态枚举 + 模型骨架**（research_task.py 行 20-86）：

```20:86:server/delivery/models/research_task.py
import uuid

from django.db import models


class RepoResearchTaskStatus(models.TextChoices):
    """RepoResearchTask 子任务级状态枚举（5 态，逐字对齐 DOMAIN §6/§14）。"""

    PENDING = "pending", "待派发"
    RUNNING = "running", "调研中"
    DONE = "done", "已完成"
    FAILED = "failed", "失败"
    STALE = "stale", "已过期"


class RepoResearchTask(models.Model):
    """每仓并行调研子任务（子任务级状态机 + 可靠恢复底座，DOMAIN §6/§14）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 归属一次 PlanSession 编排；删 session 级联删其调研子任务
    session = models.ForeignKey(
        "delivery.PlanSession",
        on_delete=models.CASCADE,
        related_name="research_tasks",
    )
    # 被调研仓（跨 app 真实 FK，repositories 是稳定基础 app）；related_name="+" 不污染
    # Repository 反查
    repository = models.ForeignKey(
        "repositories.Repository",
        on_delete=models.CASCADE,
        related_name="+",
    )
    # dispatch 容器后回填；删容器会话不删 task（SET_NULL）
    subagent_session = models.ForeignKey(
        "subagent.SubAgentSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    status = models.CharField(
        max_length=16,
        choices=RepoResearchTaskStatus.choices,
        default=RepoResearchTaskStatus.PENDING,
    )
    # 来自 Phase 38 routing 的 high/medium/low
    routed_confidence = models.CharField(max_length=16, blank=True, default="")
    # 重试计数（RESEARCH-02 单仓重试）
    attempt = models.IntegerField(default=0)
    # 失败结构化诊断
    error = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "delivery_repo_research_task"
        verbose_name = "仓库调研子任务"
        verbose_name_plural = "仓库调研子任务"
        indexes = [
            models.Index(fields=["session", "status"]),
            models.Index(fields=["repository"]),
        ]

    def __str__(self) -> str:
        return f"RepoResearchTask({self.id}, {self.status})"
```

**Copy-from delta（RepoCodingTask 相对 RepoResearchTask 的差异，参 44-RESEARCH Pattern 1 + CONTEXT Area 1）：**
- `session FK → delivery.PlanSession` ⟶ 改为 `plan_version FK → delivery.PlanVersion`，`on_delete=CASCADE`，`related_name="coding_tasks"`（真实 FK，**不**用 PlanSession 软引用）。
- 状态枚举去掉 `STALE`（仅 4 态 `pending/running/done/failed`）——stale 是调研重索引语义，编码期无。
- 新增 `wave = models.IntegerField(default=0)`（拓扑层级，service 写入）。
- 新增 `depends_on = models.ManyToManyField("self", symmetrical=False, blank=True, related_name="dependents")`（有向 DAG 仓级边）。
- 新增 `produced_artifacts = models.JSONField(default=dict, blank=True)`（本 phase 仅立字段）。
- 新增 `follow_openspec = models.BooleanField(default=False)`（SDD 预留，不消费）。
- 去掉 `routed_confidence`（调研专属）。保留 `subagent_session SET_NULL`、`attempt`、`error JSONField`、`created_at`/`updated_at` 逐字。
- `Meta`：`db_table="delivery_repo_coding_task"`、中文 verbose_name、`indexes=[Index(["plan_version","wave","status"]), Index(["repository"])]`。
- **模型层零业务方法**（仅 `__str__`），守 INV-6（grep 守护）。

---

### `server/delivery/models/__init__.py` (barrel)

**Analog:** 同文件现有 research_task 导出块（行 40-44 + `__all__` 行 84-86）

```40:44:server/delivery/models/__init__.py
from delivery.models.research_task import (
    PartialPlan,
    RepoResearchTask,
    RepoResearchTaskStatus,
)
```

**Apply:** 新增 `from delivery.models.repo_coding_task import (RepoCodingTask, RepoCodingTaskStatus)`，并在 `__all__` 追加两名（镜像行 84-86 的 `"RepoResearchTask", "RepoResearchTaskStatus"` 模式）。

---

### `server/delivery/migrations/0017_repocodingtask.py` (migration, DDL)

**Analog:** `server/delivery/migrations/0013_reporesearchtask_partialplan.py`（多 app 依赖 + CreateModel + AddIndex）

```10:14:server/delivery/migrations/0013_reporesearchtask_partialplan.py
    dependencies = [
        ('delivery', '0012_alter_plansession_recall_context'),
        ('repositories', '0036_git_instance_credential'),
        ('subagent', '0013_alter_tokenusage_provider_type'),
    ]
```

**Apply（参 44-RESEARCH Pitfall 6）：**
- **必须用 `python manage.py makemigrations delivery` 自动生成**，不手写（M2M self through 表 `repo_coding_task_depends_on` 须 Django 自动建）。
- 生成的 `dependencies` 须含 `('delivery', '0016_clarification')`（当前最新，见下）+ `repositories` 最新 + `subagent` 最新（FK 目标）。镜像 0013 的多依赖结构。
- 当前最新 delivery 迁移确认为 `0016_clarification`（其 `dependencies` 仅 `('delivery','0015_plansessionevent')`），故新迁移序号 `0017`、父依赖 `0016_clarification`。
- 生成后核对：`RepoCodingTask` 含 plan_version/repository/subagent_session FK + depends_on M2M + AddIndex（plan_version,wave,status / repository）。

---

### `server/delivery/services/repo_coding_task_service.py` (service, INV-6 write-entry)

**Analog:** `server/delivery/services/research_service.py`（`@sync_to_async` 包同步实现 + 条件更新幂等）

**Imports + service 骨架 + create_tasks 幂等 get_or_create**（research_service.py 行 19-70）：

```19:70:server/delivery/services/research_service.py
from __future__ import annotations

import hashlib
import json
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db.models import F
from django.utils import timezone

from delivery.models import PartialPlan, RepoResearchTask, RepoResearchTaskStatus

logger = structlog.get_logger(__name__)

__all__ = ["ResearchService"]


class ResearchService:
    """RepoResearchTask / PartialPlan 状态与落库唯一入口（INV-6 精神）。"""

    async def create_tasks_for_session(
        self, session: Any, deep_repos: list[dict]
    ) -> list[RepoResearchTask]:
        """为每个需深入仓建 RepoResearchTask（status=pending, attempt=0），幂等。"""
        return await self._create_tasks_sync(session, deep_repos)

    @sync_to_async
    def _create_tasks_sync(
        self, session: Any, deep_repos: list[dict]
    ) -> list[RepoResearchTask]:
        tasks: list[RepoResearchTask] = []
        for item in deep_repos:
            repository_id = item.get("repository_id")
            if not repository_id:
                continue
            task, _created = RepoResearchTask.objects.get_or_create(
                session=session,
                repository_id=repository_id,
                defaults={
                    "status": RepoResearchTaskStatus.PENDING,
                    "routed_confidence": item.get("routed_confidence", "") or "",
                    "attempt": 0,
                },
            )
            tasks.append(task)
        return tasks
```

**状态推进 + error 包装**（research_service.py 行 72-99）：

```72:99:server/delivery/services/research_service.py
    async def mark_running(self, task: RepoResearchTask, subagent_session: Any) -> None:
        """task.status→running，回填 subagent_session 外键。"""
        await self._mark_running_sync(task, subagent_session)

    @sync_to_async
    def _mark_running_sync(self, task: RepoResearchTask, subagent_session: Any) -> None:
        task.status = RepoResearchTaskStatus.RUNNING
        task.subagent_session = subagent_session
        task.save(update_fields=["status", "subagent_session", "updated_at"])

    async def mark_done(self, task: RepoResearchTask) -> None:
        """task.status→done。"""
        await self._mark_done_sync(task)

    @sync_to_async
    def _mark_done_sync(self, task: RepoResearchTask) -> None:
        task.status = RepoResearchTaskStatus.DONE
        task.save(update_fields=["status", "updated_at"])

    async def mark_failed(self, task: RepoResearchTask, error: Any) -> None:
        """task.status→failed，error JSON 落库（非 dict 包成 {"message": str}）。"""
        await self._mark_failed_sync(task, error)

    @sync_to_async
    def _mark_failed_sync(self, task: RepoResearchTask, error: Any) -> None:
        task.status = RepoResearchTaskStatus.FAILED
        task.error = error if isinstance(error, dict) else {"message": str(error)}
        task.save(update_fields=["status", "error", "updated_at"])
```

**条件更新幂等 status guard（关键范式，wave 推进/mark_done 幂等照此）**（research_service.py 行 157-170）：

```157:170:server/delivery/services/research_service.py
        updated = RepoResearchTask.objects.filter(
            id=task.id,
            status__in=[RepoResearchTaskStatus.FAILED, RepoResearchTaskStatus.STALE],
        ).update(
            status=RepoResearchTaskStatus.PENDING,
            attempt=F("attempt") + 1,
            updated_at=timezone.now(),
        )
        if updated != 1:
            raise ValueError(
                f"RepoResearchTask {task.id} 非 failed/stale 态不可重试（当前 status={task.status}）"
            )
        task.refresh_from_db()
        return task
```

**Copy-from delta（RepoCodingTaskService，参 44-RESEARCH Pattern 2 + CONTEXT Area 3）：**
- `__all__ = ["RepoCodingTaskService"]`，`from delivery.models import RepoCodingTask, RepoCodingTaskStatus`。
- `create_tasks_for_plan(plan_version, repo_waves: dict[str,int], repo_dep_edges: dict[str,list[str]])`：镜像 `_create_tasks_sync` 的 `get_or_create(plan_version=..., repository_id=...)` 幂等范式，额外写 `wave`，并在同步块内用 `task.depends_on.set(...)`（M2M）连边（须在同步 `@sync_to_async` 块内做 M2M，避免 async lazy 访问）。
- `mark_running(task, subagent_session)` / `mark_done(task)` / `mark_failed(task, error)` 逐字镜像（去掉 `record_partial`/`retry_task`/`invalidate_*`/`mark_stale` 等调研专属方法）。
- 新增 `mark_blocked(task, upstream_ids)`：`status=failed` + `error={"reason": "upstream_failed", "upstream": [...]}`（下游阻断，CONTEXT Area 4）。
- **幂等优先用条件 `.update(...).filter(status__in=[...])` + 影响行数判定**（如 `mark_done` 仅 running→done），让重复 callback no-op（参上方条件更新范式）。

---

### `server/services/plan_orchestration/wave_layering.py` (pure-fn, transform)

**Analog:** `plan_validator.py`（半可信纯函数防御 + 复用 `validate_plan` 做环检测）

**复用环检测（不重写）**（plan_validator.py 行 28-76）：

```28:76:server/services/plan_orchestration/plan_validator.py
__all__ = ["CHECK_NAMES", "validate_plan"]

# 校验 check 名常量（供调用方/测试对齐）
CHECK_NAMES = (
    "non_empty_plan",
    "contract_consistency",
    "dependency_cycle",
    "migration_order",
    "release_order",
    "rollback_completeness",
)


def validate_plan(merged: Any) -> dict:
    """对 §7 MergedPlan 跑非空 + 形状 + 5 项跨仓语义校验，汇总结构化报告。

    Returns:
        ``{"valid": bool, "errors": [{check, message}...], "warnings": [...]}``。
        顶层非 dict 等半可信输入恒不抛异常（返回 valid=False + 防御 error）。
    """
```

**半可信 execution_plan 解析范式（缺字段补 []，dependencies = task id）**（plan_validator.py 行 82-84 + 216-225）：

```216:225:server/services/plan_orchestration/plan_validator.py
    for task in _execution_plan(merged):
        task_id = str(task.get("id") or "")
        if not task_id:
            continue
        graph.setdefault(task_id, set())
        for dep in task.get("dependencies", []) or []:
            dep_key = str(dep)
            if dep_key == task_id:
                self_loops.append(task_id)
            _add_edge(task_id, dep_key)
```

**schema 权威确认**（technical_plan.py 行 34 + 161-163）—— `dependencies` 是 task id，**非** repository_id：

```32:35:server/workflows/schemas/technical_plan.py
    coding_instruction: str = ""  # Detailed coding instructions for AI
    files: list[TaskFile] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)  # Task IDs this depends on
    estimated_hours: float = 0
```

**Apply（参 44-RESEARCH Code Examples「拓扑分层」+「仓级 depends_on 边投影」）：**
- `build_repo_waves(execution_plan) -> tuple[dict[str, int], dict | None]`：先 `validate_plan({"execution_plan": ...})` 取 `dependency_cycle` errors → 有环返回 `({}, {"reason":"dependency_cycle","detail":...})` fail-fast；否则用 `graphlib.TopologicalSorter` 的 `get_ready()`/`done()` 批接口分层（同层=同 wave），task wave 折叠为仓 wave 取 **max**。
- `build_repo_dep_edges(execution_plan) -> dict[str, list[str]]`：`taskA→taskB` 投影为 `repo(A)→repo(B)`，**去同仓自环**（`ra != rb` 才成边）。
- 半可信防御逐字对齐 plan_validator：`t.get("dependencies") or []`、`t.get("repository_id", "")`、缺 id 跳过，绝不抛/不 eval。
- 空依赖 → 全仓 wave=0（零回归命门，参 Pitfall 2）。

---

### `server/services/plan_orchestration/wave_progression.py` (pure-fn, event-driven barrier)

**Analog:** `research_aggregation.py`（barrier 全终态 + status guard 幂等）+ `resume.py`（入口无关 helper）

**barrier 全终态判定（终态含 failed，不是仅 done）**（research_aggregation.py 行 35-70）：

```35:70:server/services/plan_orchestration/research_aggregation.py
# barrier 完成判定集（§14：所有 RepoResearchTask done/failed → merging）。
# stale/pending/running 非终态——stale 须重跑后才满足。
TERMINAL_STATUSES = {RepoResearchTaskStatus.DONE, RepoResearchTaskStatus.FAILED}

# 阻塞 barrier 完成的「在途」状态
_PENDING_STATUSES = (
    RepoResearchTaskStatus.PENDING,
    RepoResearchTaskStatus.RUNNING,
    RepoResearchTaskStatus.STALE,
)
...
async def aall_research_tasks_terminal(session_id: Any) -> bool:
    """该 session 至少有一个 RepoResearchTask 且无任何在途态（全部 done/failed）。

    无任何 task → 返回 True（无需调研，直接可推进）。
    """
    from delivery.models import RepoResearchTask

    total = await RepoResearchTask.objects.filter(session_id=session_id).acount()
    if total == 0:
        return True
    pending = await RepoResearchTask.objects.filter(
        session_id=session_id, status__in=_PENDING_STATUSES
    ).aexists()
    return not pending
```

**幂等 guard + 经 service 推进（不直接写 status）**（research_aggregation.py 行 73-88）：

```73:88:server/services/plan_orchestration/research_aggregation.py
async def amaybe_complete_research(
    session: PlanSession, *, session_service: PlanSessionService | None = None
) -> bool:
    """所有 RepoResearchTask 终态则经 service 推 research_complete（→ merging）。

    guard ``session.status == researching``（并发已推进 → no-op return False）；
    经 ``transition(session, "research_complete")`` 转移（**不直接写 status**，engine 纯度）。
    返回是否推进。
    """
    if str(session.status) != str(PlanSessionStatus.RESEARCHING):
        return False
    if not await aall_research_tasks_terminal(session.id):
        return False
    svc = session_service or PlanSessionService()
    await svc.transition(session, "research_complete")
    return True
```

**入口无关 helper 设计要点 + async ORM 安全（lazy import 规避环、`*_id` 标量）**（resume.py 行 24-79）：

```24:77:server/services/plan_orchestration/resume.py
async def adrive_plan_session_to_pause_or_terminal(
    engine: Any, session: Any, *, max_steps: int = 20
) -> Any:
    """续驱 PlanSession 到「重挂起短路点」或终态 ``{DONE, FAILED}`` 后返回该 session。
    ...
    """
    # 函数内 lazy import 规避 import 环（resume → models / barrel）
    from delivery.models import Clarification, PlanSession, PlanSessionStatus
    from services.plan_orchestration import aall_research_tasks_terminal

    terminal = {PlanSessionStatus.DONE, PlanSessionStatus.FAILED}
    steps = 0
    while session.status not in terminal:
        steps += 1
        ...
        # researching 在途短路：仍有在途调研 → 等下一次容器回调，不再 advance
        if session.status == PlanSessionStatus.RESEARCHING and not await aall_research_tasks_terminal(
            session.id
        ):
            return session
        await engine.advance(session)
        session = await PlanSession.objects.aget(id=session.id)
    return session
```

**Apply（参 44-RESEARCH Pattern 3 + Code Examples 幂等 gate）：**
- `acurrent_wave_all_terminal(plan_version_id, wave) -> bool`：镜像 `aall_research_tasks_terminal`——`RepoCodingTask.objects.filter(plan_version_id=..., wave=..., status__in=[PENDING, RUNNING]).aexists()` → 取反（终态含 failed）。
- `aadvance_coding_waves(plan_version_id, *, service=None) -> dict`：入口无关续驱——① 回填 running task 终态（经 service，按 `subagent_session_id` 关联 SubAgentSession.status，用 `*_id` 标量/`async for`，**绝不裸访问 lazy-FK**）② wave gate 判定 ③ 上游 failed → 下游 `depends_on` 链 `service.mark_blocked` ④ 返回下一 wave 待 dispatch task / `{"all_terminal": True}`。
- 幂等：重复调用经 service 条件更新 no-op；状态只经 `RepoCodingTaskService`，绝不直接写 `task.status`。
- 当前 wave = DB 重算（存在 pending/running 的最小 wave），**不读内存**（Pitfall 7）。

---

### `server/workflows/nodes/ai/coding.py` (MODIFY — workflow node)

**Analog（自身）:** `execute`（resume 分支检测）+ `_execute_with_branch`（dispatch + waiting_event）+ `_resume_after_containers`（回调收尾）+ `research_adapter.dispatch`（dispatch→mark_running 范式）

**resume 分支检测（`_resume_from_callback` 标记，wave 推进重入点）**（coding.py 行 219-235）：

```219:235:server/workflows/nodes/ai/coding.py
        # 0. 检查是否从 waiting_event 恢复
        if context.node_execution:
            output_data = getattr(context.node_execution, "output_data", None)
            if isinstance(output_data, dict):
                # 检查是否有恢复标记（容器完成后）
                if output_data.get("_resume_from_callback"):
                    # 恢复路径：不重复 init，直接从 create_mr 开始
                    await self.emit_sub_step(context, "create_mr", SubStepStatus.RUNNING)
                    return await self._resume_after_containers(context, output_data, log)
```

**仓级分组（现成，wave 调度粒度 = 仓级）**（coding.py 行 720-729）：

```720:729:server/workflows/nodes/ai/coding.py
    def _group_by_repository(
        self, execution_plan: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        """按 repository_id 分组任务。"""
        groups: dict[str, list[dict[str, Any]]] = {}
        for task in execution_plan:
            repo_id: str = task.get("repository_id", "")
            if repo_id:
                groups.setdefault(repo_id, []).append(task)
        return groups
```

**并行 dispatch + 单仓异常隔离（现成，wave 内 dispatch 保留此范式）**（coding.py 行 415-466）：

```415:466:server/workflows/nodes/ai/coding.py
        coding_tasks = [
            self._run_repo_coding(
                repository=repositories[repo_id],
                tasks=tasks,
                ...
            )
            for repo_id, tasks in repo_groups.items()
        ]
        results: list[dict[str, Any] | BaseException] = await asyncio.gather(
            *coding_tasks, return_exceptions=True
        )

        # 6. 分离 waiting_event / error
        waiting_sessions: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        ...
```

**waiting_event 挂起 + output_data 承载恢复状态（无状态上下文走 output_data，wave 状态走 DB）**（coding.py 行 468-490）：

```468:490:server/workflows/nodes/ai/coding.py
        # 7. 如果有 waiting_event，挂起 workflow
        if waiting_sessions:
            return NodeResult(
                status="waiting_event",
                output={
                    "pending_sessions": [...],
                    "failed_repos": failed,
                    "plan_data": plan_data,
                    "branch_name": branch_name,
                    "base_branch": base_branch,
                    "plan_title": plan_title,
                    "repositories": {...},
                },
            )
```

**dispatch → mark_running 经 service 范式**（research_adapter.py 行 201-216）：

```201:216:server/services/plan_orchestration/research_adapter.py
        dispatch_task = DispatchTask(
            ...
            node_execution_id=self.node_execution_id or "",
        )
        await get_dispatcher().dispatch(dispatch_task)
        await self.research_service.mark_running(task, subagent_session)
```

**Apply（参 44-RESEARCH Architecture Diagram + CONTEXT Area 3，薄接线，回归风险最小化）：**
- `_execute_with_branch` 首发段：在 `_group_by_repository` 后，调 `RepoCodingTaskService.create_tasks_for_plan(plan_version, build_repo_waves(...), build_repo_dep_edges(...))` 建 RepoCodingTask 行（INV-6 单一写入）；有环 → 返回 `NodeResult(status="failed", error={"reason":"dependency_cycle",...})`，不进 dispatch。
- 仅 dispatch **当前 wave（= 最小 pending wave）且 depends_on 全 done** 的仓（保留 `asyncio.gather(..., return_exceptions=True)` + dispatch 后 `service.mark_running`）。
- 空依赖退化：全仓 wave=0 → 一次性 dispatch 全部 = 现行为字节级等价（零回归，Pitfall 2，须有断言测试）。
- `_resume_after_containers` 改为先调 `aadvance_coding_waves(plan_version_id)`：若返回下一 wave 待 dispatch → dispatch + 再 `waiting_event`；若 `all_terminal` → 走现有 MR 创建 + 飞书卡片收尾段（部分成功：done 仓出 MR，failed/blocked 如实标注）。
- **不新建调度循环**——wave N→N+1 由容器回调 `_schedule_workflow_resume` 触发节点重入自驱（callbacks.py 不改契约）。

---

## Shared Patterns

### INV-6 单一写入入口 grep 守护
**Source:** `server/tests/delivery/test_research_inv6_guard.py`
**Apply to:** `test_repo_coding_task_inv6_guard.py`（逐字镜像，仅换模型名 + `_ALLOWED_WRITER`）

```28:50:server/tests/delivery/test_research_inv6_guard.py
# 唯一允许写两模型的模块（相对 server/）
_ALLOWED_WRITER = "delivery/services/research_service.py"

# A：<Model>.objects.<write>
_RE_ORM_WRITE = re.compile(
    r"\b(?:RepoResearchTask|PartialPlan)\.objects\."
    r"(?:create|bulk_create|get_or_create|update_or_create|update)\b"
)
# B：直接实例化
_RE_INSTANTIATE = re.compile(r"\b(?:RepoResearchTask|PartialPlan)\s*\(")
# C：链式实例化 + save
_RE_INSTANCE_SAVE = re.compile(r"\b(?:RepoResearchTask|PartialPlan)\([^)]*\)\.save\(")
```

**Delta:** 模型名 → `RepoCodingTask`（单模型），`_ALLOWED_WRITER = "delivery/services/repo_coding_task_service.py"`。`_is_scanned` 排除集（tests/ / migrations/ / delivery/models/ + writer 自身）逐字保留。两个测试函数（`test_inv6_no_bypass_*` + `test_inv6_writer_actually_writes`）一并镜像。**注意正则天然排除 `RepoCodingTaskStatus(`**（枚举非写，参原注释行 36-38）。

### async ORM 安全（规避 SynchronousOnlyOperation）
**Source:** `research_service.py`（`@sync_to_async` 包同步块）+ `research_aggregation.py`（`*_id` filter / `aexists`/`acount`）+ `resume.py`（lazy import）
**Apply to:** 所有 service 写 / wave_progression 读 / coding.py 改造段
- ORM 写：service 内 `@sync_to_async def _xxx_sync(...)`，同步块内访问 FK/M2M（`task.depends_on.set(...)`）。
- ORM 读（async 上下文）：`RepoCodingTask.objects.filter(plan_version_id=..., ...).aexists()/acount()`、`subagent_session_id` 标量、`async for`，绝不裸访问 `task.repository`/`task.subagent_session`。
- lazy import 规避 import 环（`from delivery.models import RepoCodingTask` 放函数内）。

### fail-soft callback swallow（wave 推进不让回调 5xx）
**Source:** `callbacks.py:_schedule_workflow_resume`（fire-and-forget，行 198；不改契约）+ resume.py fail-soft
**Apply to:** wave 推进副作用全程独立 try/except + `logger.warning` 降级（参 44-RESEARCH Pitfall 4）。

---

## No Analog Found

无。本 phase 全部新增文件均在仓内有强分析对象（model/service/migration/test 逐项镜像 research_* 系列；wave 纯函数镜像 plan_validator + research_aggregation；node 改造基于自身既有 dispatch/resume 通路）。`graphlib.TopologicalSorter` 为 Python 3.14 stdlib（无仓内 analog 但标准库自带，参 44-RESEARCH Code Examples）。

---

## Metadata

**Analog search scope:** `server/delivery/models/`、`server/delivery/services/`、`server/delivery/migrations/`、`server/services/plan_orchestration/`、`server/workflows/nodes/ai/`、`server/workflows/schemas/`、`server/subagent/api/`、`server/tests/delivery/`
**Files scanned:** 11 analog 文件（research_task / research_service / models barrel / services barrel / 0013+0016 migration / plan_validator / research_aggregation / resume / coding.py / technical_plan schema / research_adapter / test_research_inv6_guard / callbacks）
**Pattern extraction date:** 2026-06-16
**Key constraints honored:** Python 3.14、async adrf、`sync_to_async`/`*_id` 标量、ruff line 100、中文 docstring、INV-6 单一写入、不另造调度（复用 callback resume）、dependencies = task id（非 repository_id）、wave gate = 全终态（done|failed）。
