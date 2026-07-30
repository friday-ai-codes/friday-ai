"""blueprint_repo_waves —— 按 API provider/consumer 关系的波次预排（BUS-02，Phase 113-04）。

**纯函数模块**：零 ORM、零 IO、零 LLM（形态照 `wave_layering.build_repo_waves`，可零 DB 单测）。

这是跨仓依赖的**第一道防线**：让 provider 仓进更早的波次先产出接口契约，`await_blueprint_context`
只兜「预排推不出来的动态依赖」，避免退化成人人互等（CONTEXT 锁定）。

三条纪律：

1. **成环不静默打平**：成环的仓如实上报在 `cycles` 里，同时**仍出现在 waves 的最后一波**（不丢仓），
   由调用方开澄清线程交人裁决。
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
    """Kahn 分层（wave 从 1 起）；成环的仓统一挂在**最后一波**，绝不丢仓。

    零依赖输入 → 全部 wave 1（可完全并行，与预排前的行为逐字一致，零回归）。
    """
    remaining = [rid for rid in nodes if rid not in cyclic]
    pending = {
        rid: {p for p in providers_of.get(rid, set()) if p not in cyclic} for rid in remaining
    }
    waves: dict[int, list[str]] = {}
    placed: set[str] = set()
    wave = 1
    while pending:
        ready = sorted(rid for rid, deps in pending.items() if not (deps - placed))
        if not ready:
            # 理论不可达（环已剔除）；兜底把剩余仓平铺，绝不无界循环、绝不丢仓。
            waves[wave] = sorted(pending)
            placed |= set(pending)
            pending = {}
            break
        waves[wave] = ready
        placed |= set(ready)
        for rid in ready:
            pending.pop(rid, None)
        wave += 1
    if cyclic:
        last = max(waves) + 1 if waves else 1
        waves[last] = sorted(cyclic)
    return waves
