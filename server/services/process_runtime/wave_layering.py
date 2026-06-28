"""wave_layering —— execution_plan 拓扑分层纯函数（Phase 44-02，WAVE-01）。

把 ``MergedPlan.execution_plan[].dependencies``（task id 引用，非 repository_id——
权威见 ``workflows/schemas/technical_plan.py`` ``ExecutionTask.dependencies``）真正消费：
建任务级 DAG → 复用 ``plan_validator.validate_plan`` 做权威环检测（不重写）→ 用
``graphlib.TopologicalSorter`` Kahn 分层 → 投影为仓级 ``wave`` 与跨仓 ``depends_on`` 边。

**纯函数**（无 IO / 无 ORM / 无 LLM）。半可信输入（LLM 合成产物）逐字段 ``.get`` 防御，
逐字对齐 ``plan_validator`` 范式（``t.get("dependencies") or []``、
``t.get("repository_id", "")``）：缺 id 跳过、无效引用过滤、绝不 eval、绝不抛异常
（fail-safe）。环检测复用 ``validate_plan`` 的三色 DFS + 显式栈（防递归 DoS）。

零回归命门：``execution_plan`` 全空 ``dependencies`` ⇒ 所有仓 ``wave=0``（单 wave 全并行，
保留当前行为）。
"""

from __future__ import annotations

from graphlib import CycleError, TopologicalSorter

__all__ = ["build_repo_dep_edges", "build_repo_waves"]


def build_repo_waves(
    execution_plan: list[dict],
) -> tuple[dict[str, int], dict | None]:
    """把 ``execution_plan`` 折叠为 ``{repository_id: wave}``；有环则 fail-fast。

    边方向：task → 它依赖的 task（被依赖者先行）。仓 wave = 该仓所有 task 拓扑层级的
    **max**（保证依赖满足）。空依赖退化为单 wave 全并行（所有仓 ``wave=0``）。

    Args:
        execution_plan: 半可信任务列表，每项含 ``id`` / ``repository_id`` /
            ``dependencies``（dependencies 为其依赖的 **task id** 列表）。

    Returns:
        ``(repo_wave, None)``——成功分层，``repo_wave`` 为 ``{repository_id: wave_int}``。
        ``({}, {"reason": "dependency_cycle", "detail": [...]})``——检测到依赖环，不分层。
    """
    # 复用 plan_validator 做权威环检测（不重写）；仅取 dependency_cycle 项判定 fail-fast。
    from services.process_runtime.plan_validator import validate_plan

    report = validate_plan({"execution_plan": execution_plan})
    cycle_errs = [e for e in report["errors"] if e.get("check") == "dependency_cycle"]
    if cycle_errs:
        return {}, {"reason": "dependency_cycle", "detail": cycle_errs}

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

    # Kahn 分层：TopologicalSorter 把 value 视为 key 的前驱（依赖先行）。
    # 环检测已由 validate_plan 前置 fail-fast；此处再兜底 CycleError 永不抛。
    task_wave: dict[str, int] = {}
    try:
        sorter = TopologicalSorter(task_deps)
        sorter.prepare()
        layer = 0
        while sorter.is_active():
            ready = list(sorter.get_ready())  # 同层：前驱皆已就绪
            for tid in ready:
                task_wave[tid] = layer
                sorter.done(tid)
            layer += 1
    except CycleError as exc:  # 兜底：理论上不可达（validate_plan 已拦截）
        return {}, {"reason": "dependency_cycle", "detail": [{"check": "dependency_cycle", "message": str(exc)}]}

    # 仓 wave = 该仓所有 task 层级最大值（跳过空 rid）。
    repo_wave: dict[str, int] = {}
    for tid, wave in task_wave.items():
        rid = task_repo[tid]
        if rid:
            repo_wave[rid] = max(repo_wave.get(rid, 0), wave)
    return repo_wave, None


def build_repo_dep_edges(execution_plan: list[dict]) -> dict[str, list[str]]:
    """把任务级依赖投影为仓级 ``depends_on`` 邻接表（仅跨仓成边，去同仓自环）。

    ``taskA`` 依赖 ``taskB`` → ``repo(A)`` 依赖 ``repo(B)``；当且仅当 ``ra``、``rb`` 均非空
    且 ``ra != rb`` 时成边（同仓内部依赖不产生自环，无效引用过滤）。

    Args:
        execution_plan: 半可信任务列表（形状同 :func:`build_repo_waves`）。

    Returns:
        ``{repository_id: sorted([dep_repository_id, ...])}``——稳定有序的跨仓边集合。
    """
    task_repo = {
        t["id"]: t.get("repository_id", "")
        for t in execution_plan
        if t.get("id")
    }
    edges: dict[str, set[str]] = {}
    for t in execution_plan:
        # 与 build_repo_waves 同口径：无 id 任务不参与建边，否则会贡献仓级 depends_on 边
        # 却因被分层排除而不抬高该仓 wave，造成「同 wave 跨仓依赖」绕过首发派发 wave 保证。
        if not t.get("id"):
            continue
        ra = t.get("repository_id", "")
        for dep in (t.get("dependencies") or []):
            rb = task_repo.get(dep, "")
            if ra and rb and ra != rb:
                edges.setdefault(ra, set()).add(rb)
    return {rid: sorted(deps) for rid, deps in edges.items()}
