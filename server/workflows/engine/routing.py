"""路由/级联/死锁/输入收集核心（Phase 18 实现契约，ENG-02/04/05）。

本模块是调度主循环与回调续跑共用的纯函数路由核心：不 import Django ORM、
不依赖 WorkflowEngine，输入为 DAG 对象 + plain dict（节点状态 / next_handle），
pytest 零 DB 可测（与 Phase 17 ``template_resolver`` 同策略）。

四类判定的唯一语义源——消除审计定性的"两套路由实现漂移"根因：
- ``evaluate_node_readiness``：边感知就绪判定（ready/skip_failed/skip_unselected/blocked）
- ``select_successors``：handle 命中 + default 回退（存量工作流兼容，禁删）
- ``compute_skippable``：未选中/前置失败分支的 fixpoint 级联 skip
- ``diagnose_deadlock``：结构化死锁诊断（仅拓扑元数据，绝不含节点输出值）
- ``collect_inputs``：按 target_handle 的非破坏性输入归集

语义锁定项（来自 CONTEXT/RESEARCH，禁止收紧）：
- 汇合节点"一条活路即执行"：所有入边已解析且 ≥1 条选中 → ready；
  全部已解析且 0 条选中 → skip_unselected（菱形汇合一活一死判 ready）。
- default 回退：源 next_handle 无任何匹配出边时，default 边视为选中。
- 前置失败 ANY 语义：任一 forward 依赖 failed（非 tolerated）→ skip_failed。
- back-edge（反馈环）不参与就绪/级联判定。
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from workflows.engine.dag import DAG, DAGNode

# 节点状态常量（state.statuses 的取值；调用方负责把 NE 状态映射到这些字面值）
STATUS_COMPLETED = "completed"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"
STATUS_TOLERATED = "tolerated"
STATUS_WAITING = "waiting"
STATUS_RUNNING = "running"
STATUS_PENDING = "pending"

# "已解析"终态集合（边的源节点处于这些状态即视为该入边已确定，不再阻塞下游）。
# 注意 failed 不在此集合——前置失败由 skip_failed 提前短路处理。
_RESOLVED_STATUSES = {STATUS_COMPLETED, STATUS_SKIPPED, STATUS_TOLERATED}

# "选中态"集合（源节点真正产出了选中分支的状态）。skipped 虽已解析但不选中。
_SELECTABLE_STATUSES = {STATUS_COMPLETED, STATUS_TOLERATED}


@dataclass
class RoutingState:
    """路由判定的状态快照（全部为 plain dict，由调用方填充）。

    ``statuses``：node_id → 上述 STATUS_* 常量之一。
    ``handles``：node_id → next_handle（缺省 "default"）。

    两字段来源由调用方决定，纯函数不感知来源（封堵 RESEARCH Pitfall 2 的
    双来源不对称）：主循环热路径用内存 ``result["handle"]`` 填 handles；
    重入重建用 DB ``output_data["_next_handle"]`` 填 handles。
    """

    statuses: dict = field(default_factory=dict)
    handles: dict = field(default_factory=dict)


def _forward_edges(dag_node: "DAGNode") -> list:
    """节点的 forward 入边（过滤掉源 ∈ back_edge_sources 的反馈环边）。"""
    return [edge for edge in dag_node.incoming_edges if edge[0] not in dag_node.back_edge_sources]


def _edge_selected(dag: "DAG", source_id: str, edge_handle: str, state: RoutingState) -> bool:
    """判断源节点的 next_handle 是否选中了该 source_handle 的边。

    选中规则（与 scheduler.py:1411-1420 现状逐语义等价）：
    - next_handle == 边 source_handle → 选中；
    - 回退兼容：源 next_handle 在源节点 outgoing 全部 handle 桶中无任何匹配时，
      source_handle == "default" 的边视为选中（承载存量工作流，禁删）。
    """
    next_handle = state.handles.get(source_id, "default")
    if next_handle == edge_handle:
        return True

    source_node = dag.nodes.get(source_id)
    if source_node is not None and next_handle not in source_node.outgoing:
        return edge_handle == "default"
    return False


def evaluate_node_readiness(dag: "DAG", node_id: str, state: RoutingState) -> str:
    """边感知就绪判定，返回 "ready" | "skip_failed" | "skip_unselected" | "blocked"。

    语义（RESEARCH Pattern 3）：
    - 无 forward 入边的入口节点恒 "ready"；
    - 任一 forward 入边源 status == failed（非 tolerated）→ "skip_failed"（ANY 语义）；
    - 全部 forward 入边已解析（源 ∈ _RESOLVED_STATUSES）：≥1 条选中 → "ready"，
      0 条选中 → "skip_unselected"（汇合节点一条活路即执行）；
    - 否则（存在未解析入边）→ "blocked"。
    """
    dag_node = dag.nodes[node_id]
    forward_edges = _forward_edges(dag_node)
    if not forward_edges:
        return "ready"

    for source_id, _source_handle, _target_handle in forward_edges:
        if state.statuses.get(source_id) == STATUS_FAILED:
            return "skip_failed"

    all_resolved = all(
        state.statuses.get(source_id) in _RESOLVED_STATUSES for source_id, _sh, _th in forward_edges
    )
    if not all_resolved:
        return "blocked"

    for source_id, source_handle, _target_handle in forward_edges:
        if state.statuses.get(source_id) not in _SELECTABLE_STATUSES:
            continue
        if _edge_selected(dag, source_id, source_handle, state):
            return "ready"
    return "skip_unselected"


def select_successors(dag: "DAG", node_id: str, next_handle: str) -> list:
    """按 handle 选择后继：命中返回该桶，未命中且 handle != "default" 时回退 default 桶。

    与 scheduler.py:1411-1420 现状逐语义等价（characterization，禁止收紧）。
    """
    successors = dag.get_successors(node_id, next_handle)
    if not successors and next_handle != "default":
        successors = dag.get_successors(node_id, "default")
    return successors


def compute_skippable(dag: "DAG", state: RoutingState, pending) -> dict:
    """对 pending 集合 fixpoint 计算可 skip 的节点，返回 {node_id: 原因}。

    凡 evaluate 为 skip_*（skip_failed/skip_unselected）的节点记入结果，并在本轮内
    把其 status 临时视为 skipped 继续迭代，直至 fixpoint。不修改入参 state（纯函数，
    复制内部工作副本）。
    """
    working_statuses = dict(state.statuses)
    work_state = RoutingState(statuses=working_statuses, handles=state.handles)
    result: dict = {}
    remaining = set(pending)

    changed = True
    while changed:
        changed = False
        for node_id in list(remaining):
            verdict = evaluate_node_readiness(dag, node_id, work_state)
            if verdict in ("skip_failed", "skip_unselected"):
                result[node_id] = verdict
                working_statuses[node_id] = STATUS_SKIPPED
                remaining.discard(node_id)
                changed = True

    return result


def diagnose_deadlock(dag: "DAG", state: RoutingState, pending) -> dict | None:
    """结构化死锁诊断，无死锁返回 None。

    判定条件（CONTEXT 锁定，三要素齐备缺一即误报/漏报）：pending 非空、
    state.statuses 中无任何节点处于 waiting/running、pending 中无任何节点 ready。

    满足时返回 ``{"reason": "deadlock", "pending": [...]}``，每个 pending 项列出其
    未解析的 forward 入边。**只含拓扑元数据（名称/short_id/状态/handle），绝不读取
    节点输出值**（V5 信息泄露防线，同 Phase 17 约定）；不抛异常，由 scheduler 写入
    amark_failed（引擎"结果不外抛"约定）。
    """
    if not pending:
        return None

    for status in state.statuses.values():
        if status in (STATUS_WAITING, STATUS_RUNNING):
            return None

    for node_id in pending:
        if evaluate_node_readiness(dag, node_id, state) == "ready":
            return None

    pending_report = []
    for node_id in sorted(pending):
        dag_node = dag.nodes[node_id]
        waiting_on = []
        for source_id, source_handle, _target_handle in _forward_edges(dag_node):
            src_status = state.statuses.get(source_id, "unknown")
            if src_status in _RESOLVED_STATUSES:
                continue
            src_node = dag.nodes.get(source_id)
            waiting_on.append(
                {
                    "node": src_node.node.name if src_node else source_id,
                    "short_id": src_node.node.short_id if src_node else source_id,
                    "status": src_status,
                    "handle": source_handle,
                }
            )
        pending_report.append(
            {
                "node": dag_node.node.name,
                "short_id": dag_node.node.short_id,
                "waiting_on": waiting_on,
            }
        )

    return {"reason": "deadlock", "pending": pending_report}


def collect_inputs(dag: "DAG", node_id: str, node_outputs: dict) -> dict:
    """按入边 target_handle 归集上游输出（RESEARCH Pattern 5 非破坏性叠加规则）。

    取节点 incoming_edges 按 source_id 字符串排序逐条处理：
    1. 扁平合并上游输出（``inputs.update(node_outputs[source])``，现状语义保底）；
    2. 若边 target_handle 非空且非 "default"：当且仅当 target_handle 不在该上游自身
       的输出 dict 键中时，设 ``inputs[target_handle] = 上游完整输出``——同名键不覆盖
       规则防止 plan 链双重嵌套。

    characterization 锚点（RESEARCH §5 两条真实节点链，端口期望互相矛盾，此规则是
    唯一同时兼容两者的交集）：
    - ai_plan_generation → ai_coding(plan)：上游输出顶层已有 "plan" 键 → 不覆盖，
      coding.get_input("plan") 仍拿到方案对象本身（plan_generation.py:329-352 /
      coding.py:706-712）。
    - <上游> → <下游(port)>：上游输出顶层无该端口键时 → 补端口键，下游
      get_input(port) 命中完整上游输出（端口非破坏性叠加规则）。
    """
    dag_node = dag.nodes.get(node_id)
    if dag_node is None:
        return {}

    inputs: dict = {}
    for source_id, _source_handle, target_handle in sorted(
        dag_node.incoming_edges, key=lambda edge: str(edge[0])
    ):
        if source_id not in node_outputs:
            continue
        upstream = node_outputs[source_id]
        if isinstance(upstream, dict):
            inputs.update(upstream)
            if target_handle and target_handle != "default" and target_handle not in upstream:
                inputs[target_handle] = upstream
        elif target_handle and target_handle != "default":
            inputs[target_handle] = upstream

    return inputs
