"""DAG (Directed Acyclic Graph) builder and utilities."""
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
import structlog
if TYPE_CHECKING:
 from workflows.models import Workflow, WorkflowEdge, WorkflowNode
logger = structlog.get_logger
@dataclass
class DAGNode:
 """DAG 节点包装"""
 node: "WorkflowNode"
 incoming: set[str] = field(default_factory=set) # 入边的源节点 ID
 outgoing: dict[str, set[str]] = field(default_factory=dict) # {handle: {target_node_ids}}
 @property
 def id(self) -> str:
 return str(self.node.id)
 @property
 def in_degree(self) -> int:
 return len(self.incoming)
class DAG:
 """有向无环图
 用于工作流的拓扑排序和执行调度。
 """
 def __init__(self):
 self.nodes: dict[str, DAGNode] = {}
 self.edges: list["WorkflowEdge"] =
 @classmethod
 def from_workflow(cls, workflow: "Workflow") -> "DAG":
 """从工作流模型构建 DAG"""
 dag = cls
 # 添加所有节点
 for node in workflow.nodes.all:
 dag.nodes[str(node.id)] = DAGNode(node=node)
 # 添加所有边
 for edge in workflow.edges.all:
 source_id = str(edge.source_node_id)
 target_id = str(edge.target_node_id)
 handle = edge.source_handle
 if source_id in dag.nodes and target_id in dag.nodes:
 # 记录入边
 dag.nodes[target_id].incoming.add(source_id)
 # 记录出边
 if handle not in dag.nodes[source_id].outgoing:
 dag.nodes[source_id].outgoing[handle] = set
 dag.nodes[source_id].outgoing[handle].add(target_id)
 dag.edges.append(edge)
 return dag
 @classmethod
 async def afrom_workflow(cls, workflow: "Workflow") -> "DAG":
 """从工作流模型构建 DAG（async 版本）"""
 dag = cls
 async for node in workflow.nodes.all:
 dag.nodes[str(node.id)] = DAGNode(node=node)
 async for edge in workflow.edges.all:
 source_id = str(edge.source_node_id)
 target_id = str(edge.target_node_id)
 handle = edge.source_handle
 if source_id in dag.nodes and target_id in dag.nodes:
 dag.nodes[target_id].incoming.add(source_id)
 if handle not in dag.nodes[source_id].outgoing:
 dag.nodes[source_id].outgoing[handle] = set
 dag.nodes[source_id].outgoing[handle].add(target_id)
 dag.edges.append(edge)
 return dag
 def validate(self) -> list[str]:
 """验证 DAG 是否有效"""
 errors =
 # 检查是否有环
 if self.has_cycle:
 errors.append("工作流存在循环依赖")
 # 检查是否有入口节点
 entry_nodes = self.get_entry_nodes
 if not entry_nodes:
 errors.append("工作流没有入口节点（触发器）")
 # 检查是否有孤立节点
 for node_id, dag_node in self.nodes.items:
 if dag_node.in_degree == 0 and not dag_node.outgoing:
 if dag_node.node.node_type not in (
 "manual_trigger",
 "webhook_trigger",
 ):
 errors.append(f"节点 '{dag_node.node.name}' 是孤立的")
 return errors
 def has_cycle(self) -> bool:
 """检测是否存在环（使用 DFS）"""
 WHITE, GRAY, BLACK = 0, 1, 2
 color = {node_id: WHITE for node_id in self.nodes}
 def dfs(node_id: str) -> bool:
 color[node_id] = GRAY
 dag_node = self.nodes[node_id]
 for targets in dag_node.outgoing.values:
 for target_id in targets:
 if color[target_id] == GRAY:
 return True # 发现回边，存在环
 if color[target_id] == WHITE and dfs(target_id):
 return True
 color[node_id] = BLACK
 return False
 for node_id in self.nodes:
 if color[node_id] == WHITE:
 if dfs(node_id):
 return True
 return False
 def get_entry_nodes(self) -> list[DAGNode]:
 """获取入口节点（入度为 0 的节点）"""
 return [dag_node for dag_node in self.nodes.values if dag_node.in_degree == 0]
 def get_successors(self, node_id: str, handle: str = "default") -> list[DAGNode]:
 """获取指定节点的后继节点"""
 dag_node = self.nodes.get(node_id)
 if not dag_node:
 return
 successor_ids = dag_node.outgoing.get(handle, set)
 return [self.nodes[sid] for sid in successor_ids if sid in self.nodes]
 def get_all_successors(self, node_id: str) -> list[DAGNode]:
 """获取所有后继节点（所有 handle）"""
 dag_node = self.nodes.get(node_id)
 if not dag_node:
 return
 all_successor_ids: set[str] = set
 for successor_ids in dag_node.outgoing.values:
 all_successor_ids.update(successor_ids)
 return [self.nodes[sid] for sid in all_successor_ids if sid in self.nodes]
 def topological_sort(self) -> list[DAGNode]:
 """拓扑排序"""
 in_degree = {node_id: dag_node.in_degree for node_id, dag_node in self.nodes.items}
 queue = [node_id for node_id, degree in in_degree.items if degree == 0]
 result =
 while queue:
 node_id = queue.pop(0)
 result.append(self.nodes[node_id])
 for successor in self.get_all_successors(node_id):
 in_degree[successor.id] -= 1
 if in_degree[successor.id] == 0:
 queue.append(successor.id)
 return result
