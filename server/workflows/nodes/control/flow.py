"""Control flow nodes: Delay and Parallel."""
import asyncio
from workflows.nodes.base import (
 BaseNode,
 ExecutionContext,
 NodeCategory,
 NodePort,
 NodeResult,
 PortType,
)
from workflows.nodes.registry import register_node
@register_node
class DelayNode(BaseNode):
 """延迟节点
 暂停工作流执行指定时间。
 """
 node_type = "delay"
 display_name = "延迟"
 description = "暂停工作流执行指定时间"
 icon = "clock"
 category = NodeCategory.CONTROL
 execution_mode = "server_local"
 config_schema = {
 "type": "object",
 "properties": {
 "delay_seconds": {
 "type": "integer",
 "title": "延迟秒数",
 "description": "延迟执行的秒数",
 "default": 60,
 "minimum": 1,
 "maximum": 86400, # 最多 24 小时
 },
 "delay_until": {
 "type": "string",
 "title": "延迟到指定时间",
 "description": "ISO 格式时间字符串，优先于 delay_seconds",
 "default": "",
 },
 },
 }
 inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
 outputs = [NodePort(name="default", label="输出", port_type=PortType.OBJECT)]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 config = context.node_config
 delay_seconds = config.get("delay_seconds", 60)
 delay_until = config.get("delay_until", "")
 # Calculate actual delay
 actual_delay = delay_seconds
 if delay_until:
 try:
 from datetime import datetime
 target_time = datetime.fromisoformat(delay_until.replace("Z", "+00:00"))
 now = datetime.now(target_time.tzinfo)
 delta = (target_time - now).total_seconds
 if delta > 0:
 actual_delay = int(delta)
 else:
 actual_delay = 0
 except (ValueError, TypeError):
 pass # Use delay_seconds if parsing fails
 if actual_delay > 0:
 await asyncio.sleep(actual_delay)
 return NodeResult(
 status="completed",
 output={
 **context.input_data,
 "_delay_seconds": actual_delay,
 },
 next_handle="default",
 )
@register_node
class ParallelNode(BaseNode):
 """并行执行节点 (Fork)
 将输入复制到多个输出分支，实现并行执行。
 注意：这是 Fork 节点，Join 操作由 DAG 调度器自动处理。
 """
 node_type = "parallel"
 display_name = "并行分支"
 description = "将工作流分成多个并行分支"
 icon = "git-fork"
 category = NodeCategory.CONTROL
 execution_mode = "server_local"
 config_schema = {
 "type": "object",
 "properties": {
 "branches": {
 "type": "array",
 "title": "分支配置",
 "items": {
 "type": "object",
 "properties": {
 "name": {
 "type": "string",
 "title": "分支名称",
 },
 "enabled": {
 "type": "boolean",
 "title": "启用",
 "default": True,
 },
 },
 },
 "default": [
 {"name": "分支 1", "enabled": True},
 {"name": "分支 2", "enabled": True},
 ],
 },
 "pass_input": {
 "type": "boolean",
 "title": "传递输入",
 "description": "是否将输入数据传递给所有分支",
 "default": True,
 },
 },
 }
 inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
 outputs = # Dynamic outputs based on branches
 @classmethod
 def get_dynamic_outputs(cls, config: dict) -> list[NodePort]:
 """根据配置动态生成输出端口"""
 outputs =
 branches = config.get("branches", )
 for i, branch in enumerate(branches):
 if branch.get("enabled", True):
 outputs.append(
 NodePort(
 name=f"branch_{i}",
 label=branch.get("name", f"分支 {i + 1}"),
 port_type=PortType.OBJECT,
 )
 )
 return outputs
 async def execute(self, context: ExecutionContext) -> NodeResult:
 config = context.node_config
 branches = config.get("branches", )
 pass_input = config.get("pass_input", True)
 # Build output for each enabled branch
 output_data = {}
 active_branches =
 for i, branch in enumerate(branches):
 if branch.get("enabled", True):
 branch_name = f"branch_{i}"
 active_branches.append(branch_name)
 if pass_input:
 output_data[branch_name] = context.input_data.copy
 else:
 output_data[branch_name] = {}
 return NodeResult(
 status="completed",
 output={
 "active_branches": active_branches,
 "branch_data": output_data,
 **context.input_data,
 },
 # 特殊处理：返回所有分支（由调度器处理）
 next_handle="__parallel__",
 )
@register_node
class JoinNode(BaseNode):
 """并行汇合节点 (Join)
 等待多个并行分支完成后汇合。
 """
 node_type = "join"
 display_name = "并行汇合"
 description = "等待所有并行分支完成后继续"
 icon = "git-merge"
 category = NodeCategory.CONTROL
 execution_mode = "server_local"
 config_schema = {
 "type": "object",
 "properties": {
 "wait_mode": {
 "type": "string",
 "title": "等待模式",
 "enum": ["all", "any", "count"],
 "default": "all",
 "description": "all=等待全部, any=任一完成, count=指定数量",
 },
 "wait_count": {
 "type": "integer",
 "title": "等待数量",
 "description": "wait_mode=count 时生效",
 "default": 1,
 "minimum": 1,
 },
 "merge_strategy": {
 "type": "string",
 "title": "合并策略",
 "enum": ["array", "object", "first", "last"],
 "default": "array",
 "description": "如何合并各分支的输出",
 },
 "timeout": {
 "type": "integer",
 "title": "超时(秒)",
 "description": "等待超时时间，0 表示不超时",
 "default": 0,
 },
 },
 }
 inputs = # Dynamic inputs
 outputs = [NodePort(name="default", label="输出", port_type=PortType.OBJECT)]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 config = context.node_config
 merge_strategy = config.get("merge_strategy", "array")
 # Collect all inputs from previous nodes
 previous_outputs = context.previous_outputs
 # Merge based on strategy
 if merge_strategy == "array":
 merged = list(previous_outputs.values)
 elif merge_strategy == "object":
 merged = {}
 for node_id, output in previous_outputs.items:
 merged[node_id] = output
 elif merge_strategy == "first":
 merged = next(iter(previous_outputs.values), {})
 elif merge_strategy == "last":
 merged = list(previous_outputs.values)[-1] if previous_outputs else {}
 else:
 merged = list(previous_outputs.values)
 return NodeResult(
 status="completed",
 output={
 "merged_data": merged,
 "branch_count": len(previous_outputs),
 "source_nodes": list(previous_outputs.keys),
 },
 next_handle="default",
 )
