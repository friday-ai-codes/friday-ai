"""PlanValidator —— MergedPlan 跨仓语义校验纯函数（Phase 40-01 Task 3，DOMAIN §7）。

让架构师 agent「不只是更贵的总结器」：对融合产出的 §7 MergedPlan 做 5 项跨仓语义
校验（MERGE-02 拦截 + MERGE-03 跨仓依赖建模），返回结构化报告
``{"valid": bool, "errors": [...], "warnings": [...]}``，每个 error/warning 形如
``{"check": <check_name>, "message": <定位串>}``。

**纯函数**（无 IO / 无 ORM / 无 LLM）。半可信输入（LLM 合成产物）逐字段 ``isinstance``
+ ``.get`` 防御，缺字段当空集/空 list 处理，**绝不抛异常**（fail-safe，对齐 verify_plan
范式，T-40-01-01）；拓扑/迁移检查对节点去重且不递归无界（防 DoS，T-40-01-02）。

约定数据形状（固化于本 docstring，供 40-02 synthesizer prompt 对齐）：

- ``dependency_dag``：邻接表 ``{repo_id: [depended_repo_id, ...]}``（repo_id → 其依赖的仓）。
- ``execution_plan[].dependencies``：task id 列表（task 维度有向边）。
- ``execution_plan[].api_contracts_exposed``：本仓对外暴露契约（name/id 串或 dict）。
- ``execution_plan[].dependencies_on_other_repos``：本仓依赖的他仓契约引用。
- ``api_contracts[]``：跨仓契约汇总（顶层）。
- ``release_order``：repo_id 列表（发布顺序）。
- ``data_migrations[]``：项含 ``{repository_id, ...}``（出现顺序即迁移顺序）。
- ``rollback_plan``：``{repo_id: <步骤>}`` dict / 含 ``repositories`` 列表 / 步骤 list。
"""

from __future__ import annotations

from typing import Any

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
    errors: list[dict] = []
    warnings: list[dict] = []

    if not isinstance(merged, dict):
        errors.append(
            {"check": "contract_consistency", "message": "MergedPlan 必须是对象（dict）"}
        )
        return {"valid": False, "errors": errors, "warnings": warnings}

    for check in (
        _check_non_empty_plan,
        _check_field_shapes,
        _check_contract_consistency,
        _check_acyclic,
        _check_migration_order,
        _check_release_order,
        _check_rollback_completeness,
    ):
        try:
            errs, warns = check(merged)
        except Exception as exc:  # noqa: BLE001 — 半可信输入恒 fail-safe（不抛）
            errs, warns = (
                [{"check": check.__name__, "message": f"校验内部异常：{exc}"}],
                [],
            )
        errors.extend(errs)
        warnings.extend(warns)

    return {"valid": not errors, "errors": errors, "warnings": warnings}


# ---- 数据形状辅助（半可信防御） ----


def _execution_plan(merged: dict) -> list[dict]:
    raw = merged.get("execution_plan")
    return [t for t in raw if isinstance(t, dict)] if isinstance(raw, list) else []


def _dependency_dag(merged: dict) -> dict[str, list[str]]:
    """归一化 dependency_dag 为 ``{repo_id: [dep_repo_id...]}``（半可信防御）。"""
    raw = merged.get("dependency_dag")
    dag: dict[str, list[str]] = {}
    if not isinstance(raw, dict):
        return dag
    for node, deps in raw.items():
        node_key = str(node)
        if isinstance(deps, list):
            dag[node_key] = [str(d) for d in deps if d is not None]
        else:
            dag[node_key] = []
    return dag


def _contract_key(item: Any) -> str:
    """把契约引用归一化为 name/id 串（dict 取 name/id/contract/ref，str 原样）。"""
    if isinstance(item, dict):
        for key in ("name", "id", "contract", "ref"):
            value = item.get(key)
            if value:
                return str(value)
        return ""
    return str(item) if item else ""


# ---- 前置校验：非空 + 字段形状 ----


def _check_non_empty_plan(merged: dict) -> tuple[list[dict], list[dict]]:
    """⓪ execution_plan 非空：零任务「主方案」拒绝（WR-01）。

    JSON Schema 对 execution_plan 仅要求 ``type: array`` 无 ``minItems``，空数组过 schema
    闸口；其余跨仓检查对空集亦静默跳过 → 零可执行任务的 MergedPlan 会被当 canonical 落库 +
    done。显式拦截，让架构师「不只是更贵的总结器」（DOMAIN §7 / 40-01 Task 2 behavior）。
    """
    if not _execution_plan(merged):
        return (
            [{"check": "non_empty_plan", "message": "execution_plan 为空（无可执行任务）"}],
            [],
        )
    return [], []


def _check_field_shapes(merged: dict) -> tuple[list[dict], list[dict]]:
    """⓪′ 跨仓字段形状校验：字段「存在但类型不符」记 error（WR-02）。

    半可信防御原把类型不符字段一律当空处理（``dependency_dag`` 非 dict → ``{}``、
    ``data_migrations``/``release_order`` 非 list → 跳过），导致一份真实成环/顺序倒置但
    字段形状错误的方案因「形状不对」反而过验（false-pass）。此处区分「字段缺省（合法跳过）」
    与「字段存在但形状非法（记 error，不再无声降级为空）」。
    """
    errors: list[dict] = []
    dag = merged.get("dependency_dag")
    if dag is not None and not isinstance(dag, dict):
        errors.append(
            {
                "check": "dependency_cycle",
                "message": "dependency_dag 形状非法（应为邻接表 dict），跨仓依赖/环检测无法执行",
            }
        )
    migrations = merged.get("data_migrations")
    if migrations is not None and not isinstance(migrations, list):
        errors.append(
            {
                "check": "migration_order",
                "message": "data_migrations 形状非法（应为 list），迁移顺序校验无法执行",
            }
        )
    release = merged.get("release_order")
    if release is not None and not isinstance(release, list):
        errors.append(
            {
                "check": "release_order",
                "message": "release_order 形状非法（应为 list），发布顺序校验无法执行",
            }
        )
    return errors, []


# ---- 5 项跨仓语义校验 ----


def _check_contract_consistency(merged: dict) -> tuple[list[dict], list[dict]]:
    """① 契约一致性：依赖引用的契约须在暴露集（顶层 api_contracts ∪ 各仓 exposed）。"""
    exposed: set[str] = set()
    for item in merged.get("api_contracts", []) or []:
        key = _contract_key(item)
        if key:
            exposed.add(key)
    for task in _execution_plan(merged):
        for item in task.get("api_contracts_exposed", []) or []:
            key = _contract_key(item)
            if key:
                exposed.add(key)

    errors: list[dict] = []
    for task in _execution_plan(merged):
        from_repo = str(task.get("repository_id") or task.get("id") or "?")
        for ref in task.get("dependencies_on_other_repos", []) or []:
            key = _contract_key(ref)
            if key and key not in exposed:
                errors.append(
                    {
                        "check": "contract_consistency",
                        "message": f"仓 {from_repo} 依赖的契约「{key}」未在任何仓暴露",
                    }
                )
    return errors, []


def _check_acyclic(merged: dict) -> tuple[list[dict], list[dict]]:
    """② 依赖 DAG 无环：合并 dependency_dag + execution_plan[].dependencies 检测环。"""
    # 统一成去重有向图（节点为字符串，含自环显式判环）
    graph: dict[str, set[str]] = {}

    def _add_edge(src: str, dst: str) -> None:
        graph.setdefault(src, set())
        graph.setdefault(dst, set())
        if src != dst:
            graph[src].add(dst)

    self_loops: list[str] = []
    for node, deps in _dependency_dag(merged).items():
        graph.setdefault(node, set())
        for dep in deps:
            if dep == node:
                self_loops.append(node)
            _add_edge(node, dep)
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

    errors: list[dict] = []
    for node in self_loops:
        errors.append(
            {"check": "dependency_cycle", "message": f"节点「{node}」存在自环依赖"}
        )

    cycle = _find_cycle(graph)
    if cycle:
        errors.append(
            {
                "check": "dependency_cycle",
                "message": "依赖存在环：" + " → ".join(cycle),
            }
        )
    return errors, []


def _find_cycle(graph: dict[str, set[str]]) -> list[str]:
    """DFS 三色检测环；命中返回环上节点列表（去重边，不递归无界——显式栈）。"""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = dict.fromkeys(graph, WHITE)

    for start in graph:
        if color[start] != WHITE:
            continue
        # 显式栈：(node, iterator)；path 记录当前 DFS 路径用于回溯环
        stack: list[tuple[str, Any]] = [(start, iter(sorted(graph[start])))]
        path: list[str] = [start]
        color[start] = GRAY
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt in it:
                if color.get(nxt, WHITE) == GRAY:
                    # 命中环：截取 path 中 nxt 到末尾
                    idx = path.index(nxt) if nxt in path else 0
                    return path[idx:] + [nxt]
                if color.get(nxt, WHITE) == WHITE:
                    color[nxt] = GRAY
                    stack.append((nxt, iter(sorted(graph.get(nxt, set())))))
                    path.append(nxt)
                    advanced = True
                    break
            if not advanced:
                color[node] = BLACK
                stack.pop()
                if path:
                    path.pop()
    return []


def _check_migration_order(merged: dict) -> tuple[list[dict], list[dict]]:
    """③ 迁移顺序合理：被依赖仓的迁移须排在依赖仓之前（无迁移项跳过）。"""
    migrations = merged.get("data_migrations")
    if not isinstance(migrations, list) or not migrations:
        return [], []
    index: dict[str, int] = {}
    for i, item in enumerate(migrations):
        if isinstance(item, dict):
            repo = item.get("repository_id") or item.get("repo")
            if repo and str(repo) not in index:
                index[str(repo)] = i

    errors: list[dict] = []
    for repo, deps in _dependency_dag(merged).items():
        for dep in deps:
            # repo 依赖 dep → dep 迁移须先行（index[dep] < index[repo]）
            if repo in index and dep in index and index[dep] > index[repo]:
                errors.append(
                    {
                        "check": "migration_order",
                        "message": (
                            f"迁移顺序倒置：被依赖仓 {dep} 的迁移排在依赖仓 {repo} 之后"
                        ),
                    }
                )
    return errors, []


def _check_release_order(merged: dict) -> tuple[list[dict], list[dict]]:
    """④ 发布顺序与依赖一致：被依赖仓须先发；缺发布节点 → warning。"""
    raw = merged.get("release_order")
    order = [str(r) for r in raw if r is not None] if isinstance(raw, list) else []
    index = {repo: i for i, repo in enumerate(order)}

    errors: list[dict] = []
    warnings: list[dict] = []
    for repo, deps in _dependency_dag(merged).items():
        for dep in deps:
            # repo 依赖 dep → dep 须先发（index[dep] < index[repo]）
            if repo in index and dep in index:
                if index[dep] > index[repo]:
                    errors.append(
                        {
                            "check": "release_order",
                            "message": (
                                f"发布顺序违反依赖：依赖仓 {repo} 先于被依赖仓 {dep} 发布"
                            ),
                        }
                    )
            elif repo in index or dep in index:
                warnings.append(
                    {
                        "check": "release_order",
                        "message": f"发布顺序缺依赖节点（repo={repo} dep={dep}）",
                    }
                )
    return errors, warnings


def _check_rollback_completeness(merged: dict) -> tuple[list[dict], list[dict]]:
    """⑤ 回滚完整：rollback_plan 非空且覆盖 execution_plan 涉及各仓。"""
    rollback = merged.get("rollback_plan")
    if not rollback:  # None / "" / {} / [] 皆视为空
        return [{"check": "rollback_completeness", "message": "rollback_plan 为空（缺回滚策略）"}], []

    required = {
        str(t.get("repository_id"))
        for t in _execution_plan(merged)
        if t.get("repository_id")
    }
    if not required:
        return [], []

    covered = _rollback_covered_repos(rollback)
    missing = sorted(required - covered)
    if missing:
        return [
            {
                "check": "rollback_completeness",
                "message": f"rollback_plan 未覆盖仓：{', '.join(missing)}",
            }
        ], []
    return [], []


def _rollback_covered_repos(rollback: Any) -> set[str]:
    """从 rollback_plan 解析已覆盖仓集合（多形状容错）。"""
    covered: set[str] = set()
    if isinstance(rollback, dict):
        repos = rollback.get("repositories")
        if isinstance(repos, list):
            for item in repos:
                if isinstance(item, dict):
                    rid = item.get("repository_id") or item.get("repo")
                    if rid:
                        covered.add(str(rid))
                elif item:
                    covered.add(str(item))
            return covered
        # 形如 {repo_id: <步骤>}：键即覆盖仓（排除已知 meta 键）
        for key in rollback:
            if key not in ("steps", "description", "summary"):
                covered.add(str(key))
        return covered
    if isinstance(rollback, list):
        for item in rollback:
            if isinstance(item, dict):
                rid = item.get("repository_id") or item.get("repo")
                if rid:
                    covered.add(str(rid))
            elif item:
                covered.add(str(item))
    return covered
