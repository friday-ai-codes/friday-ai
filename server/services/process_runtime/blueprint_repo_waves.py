"""blueprint_repo_waves —— 按 API provider/consumer 关系的波次预排（BUS-02，Phase 113-04）。

**纯函数模块**：零 ORM、零 IO、零 LLM（形态照 `wave_layering.build_repo_waves`，可零 DB 单测）。

这是跨仓依赖的**第一道防线**：让 provider 仓进更早的波次先产出接口契约，`await_blueprint_context`
只兜「预排推不出来的动态依赖」，避免退化成人人互等（CONTEXT 锁定）。

三条纪律：

1. **成环不静默打平**：成环的仓如实上报在 `cycles` 里，同时**仍出现在 waves 里**（不丢仓），
   由调用方开澄清线程交人裁决。整个环当一个「超级节点」排一波：环的上游在它之前、环的（传递）
   下游在它之后（MN-10 —— 把环的依赖边整段剔除会让环的下游被排到环之前，顺序恰好反）。
2. **找不到 provider 不静默**：写进 `unresolved_consumed`（113-05 的 `needs_support` 前置信号）。
3. **半可信输入逐字段 `.get` 防御**：输入是容器/LLM 产物，缺键、类型不符一律跳过，绝不抛。
"""

from __future__ import annotations

__all__ = ["build_api_waves", "match_api"]


def match_api(consumed: dict, provided: dict) -> bool:
    """一条 `apis_consumed` 项是否被一条 `apis_provided` 项满足（纯函数）。

    判定顺序（`from_repository_id` 的显式指定优先级更高，但那由 :func:`build_api_waves` 处理，
    不在本函数内 —— 本函数只回答「契约形状是否对得上」）：

    1. `(method, path)` 全等（method 大小写不敏感，两侧都空视为相等）；
    2. 否则 `name` 全等；
    3. 否则不匹配。
    """
    if not isinstance(consumed, dict) or not isinstance(provided, dict):
        return False
    c_path = str(consumed.get("path") or "").strip()
    p_path = str(provided.get("path") or "").strip()
    if c_path and c_path == p_path:
        c_method = str(consumed.get("method") or "").strip().upper()
        p_method = str(provided.get("method") or "").strip().upper()
        if c_method == p_method:
            return True
    c_name = str(consumed.get("name") or "").strip()
    p_name = str(provided.get("name") or "").strip()
    return bool(c_name) and c_name == p_name


def build_api_waves(repo_plans: dict[str, dict]) -> dict:
    """按 API provider→consumer 关系拓扑分层（Kahn），provider 仓进更早波次。

    Args:
        repo_plans: `{repository_id: section}`。`section` 只需要 `apis_provided` /
            `apis_consumed` 两个键 —— 既可以是 `acollect_repo_plans` 的真实产物，也可以是
            首轮预排时的**预估输入**（确认门锁定条目自带的接口信息）。喂什么由调用方决定，
            本函数不猜、不编造。

    Returns:
        **恒定四键形状**（下游无需判空分支）::

            {
              "waves": {1: [rid, ...], 2: [rid, ...]},
              "edges": [{"from": provider_rid, "to": consumer_rid, "api": name}],
              "cycles": [[rid, rid], ...],
              "unresolved_consumed": [{"repository_id": rid, "api": name}],
            }

        零输入 → `{"waves": {}, "edges": [], "cycles": [], "unresolved_consumed": []}`。
    """
    nodes = sorted({str(rid) for rid in (repo_plans or {}) if str(rid or "")})
    empty = {"waves": {}, "edges": [], "cycles": [], "unresolved_consumed": []}
    if not nodes:
        return empty

    provided_index = {rid: _api_list(repo_plans.get(rid), "apis_provided") for rid in nodes}
    # 前驱表：consumer → 它依赖的 provider 集合（provider 必须先行）。
    providers_of: dict[str, set[str]] = {rid: set() for rid in nodes}
    edges: list[dict] = []
    seen_edges: set[tuple[str, str, str]] = set()
    unresolved: list[dict] = []

    for rid in nodes:
        for consumed in _api_list(repo_plans.get(rid), "apis_consumed"):
            api_name = str(consumed.get("name") or consumed.get("path") or "")
            provider = _resolve_provider(rid, consumed, nodes, provided_index)
            if not provider:
                unresolved.append({"repository_id": rid, "api": api_name})
                continue
            providers_of[rid].add(provider)
            signature = (provider, rid, api_name)
            if signature not in seen_edges:
                seen_edges.add(signature)
                edges.append({"from": provider, "to": rid, "api": api_name})

    cycles = _find_cycles(providers_of)
    cyclic = {rid for cycle in cycles for rid in cycle}
    waves = _layer(nodes, providers_of, cyclic=cyclic)
    return {
        "waves": waves,
        "edges": edges,
        "cycles": cycles,
        "unresolved_consumed": unresolved,
    }


# ── 内部纯函数 ────────────────────────────────────────────────────────────


def _api_list(section: object, key: str) -> list[dict]:
    """取 section 的 API 清单（半可信：非 dict / 非 list / 非 dict 元素一律剔除）。"""
    if not isinstance(section, dict):
        return []
    raw = section.get(key)
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _resolve_provider(
    consumer: str,
    consumed: dict,
    nodes: list[str],
    provided_index: dict[str, list[dict]],
) -> str:
    """定位某条 consumed 的 provider 仓：显式 `from_repository_id` 优先，否则按契约形状匹配。

    显式指定优先是有意的：容器自己声明「我要消费 B 仓的东西」比服务端猜形状更可信，
    且路径/名称还没定稿时（B 仓方案未产出）只有这条线索能建边。
    """
    explicit = str(consumed.get("from_repository_id") or "").strip()
    if explicit and explicit != consumer and explicit in provided_index:
        return explicit
    for other in nodes:
        if other == consumer:
            continue
        if any(match_api(consumed, provided) for provided in provided_index[other]):
            return other
    return ""


def _find_cycles(providers_of: dict[str, set[str]]) -> list[list[str]]:
    """有向图找环（DFS + 栈回溯，同一环只返一次；含自环）。

    形态与 `BlueprintContextService.find_wait_cycles` 同源（**复制不 import**：本模块是零依赖
    纯函数模块，不该为一个算法去 import delivery 服务层）。
    """
    cycles: list[list[str]] = []
    signatures: set[frozenset[str]] = set()
    visited: set[str] = set()
    stack: list[str] = []
    on_stack: set[str] = set()

    def _visit(node: str) -> None:
        visited.add(node)
        stack.append(node)
        on_stack.add(node)
        for nxt in sorted(providers_of.get(node, set())):
            if nxt in on_stack:
                cycle = stack[stack.index(nxt) :]
                signature = frozenset(cycle)
                if signature not in signatures:
                    signatures.add(signature)
                    cycles.append(list(cycle))
            elif nxt not in visited:
                _visit(nxt)
        stack.pop()
        on_stack.discard(node)

    for node in sorted(providers_of):
        if node not in visited:
            _visit(node)
    return cycles


def _layer(
    nodes: list[str], providers_of: dict[str, set[str]], *, cyclic: set[str]
) -> dict[int, list[str]]:
    """Kahn 分层（wave 从 1 起）；成环的仓整体当一个「超级节点」排一波，绝不丢仓。

    零依赖输入 → 全部 wave 1（可完全并行，与预排前的行为逐字一致，零回归）。

    **环的下游仍排在环之后**（MN-10）：把成环仓的依赖边整段过滤掉会让「依赖环中某仓」的非环
    仓落到 wave 1 —— 顺序恰好反了（D 依赖环里的 A，D 却先派发，开工时 A 的契约必然不在总线
    上，只能退化成 `await` 或长等待退出，第一道防线在这条分支上整体失效，并直接放大「全员长
    等待」的触发概率）。故按 SCC 缩点的思路分三段：环的上游 → 环 → 环的（传递）下游。
    """
    if not cyclic:
        return _kahn(nodes, providers_of, start_wave=1)

    downstream = _downstream_of(nodes, providers_of, cyclic)
    upstream = [rid for rid in nodes if rid not in cyclic and rid not in downstream]
    waves = _kahn(upstream, providers_of, start_wave=1)
    cycle_wave = max(waves) + 1 if waves else 1
    waves[cycle_wave] = sorted(cyclic)
    waves.update(_kahn(sorted(downstream), providers_of, start_wave=cycle_wave + 1))
    return waves


def _downstream_of(
    nodes: list[str], providers_of: dict[str, set[str]], cyclic: set[str]
) -> set[str]:
    """（传递）依赖任一成环仓的非环仓集合（不动点迭代，至多 ``len(nodes)`` 轮，绝不无界）。"""
    downstream: set[str] = set()
    changed = True
    while changed:
        changed = False
        for rid in nodes:
            if rid in cyclic or rid in downstream:
                continue
            deps = providers_of.get(rid, set())
            if (deps & cyclic) or (deps & downstream):
                downstream.add(rid)
                changed = True
    return downstream


def _kahn(
    subset: list[str], providers_of: dict[str, set[str]], *, start_wave: int
) -> dict[int, list[str]]:
    """对 ``subset`` 做 Kahn 分层，wave 从 ``start_wave`` 起；**子集外的依赖视作已满足**。

    调用方保证子集外的前驱都已排在 ``start_wave`` 之前（上游段无子集外前驱；下游段的子集外
    前驱只可能是环本身或环的上游），故这里把依赖夹到子集内是安全的。
    """
    members = set(subset)
    pending = {rid: providers_of.get(rid, set()) & members for rid in subset}
    waves: dict[int, list[str]] = {}
    placed: set[str] = set()
    wave = start_wave
    while pending:
        ready = sorted(rid for rid, deps in pending.items() if not (deps - placed))
        if not ready:
            # 理论不可达（环已单独成波）；兜底把剩余仓平铺，绝不无界循环、绝不丢仓。
            waves[wave] = sorted(pending)
            break
        waves[wave] = ready
        placed |= set(ready)
        for rid in ready:
            pending.pop(rid, None)
        wave += 1
    return waves
