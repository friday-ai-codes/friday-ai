"""SubStepMixin - 子步骤生命周期 Mixin。
为任意节点类提供 _init_sub_steps 和 emit_sub_step 能力，
无需继承 AIAgentBaseNode。
从 AIAgentBaseNode 提取而来，AIAgentBaseNode 和 AICodingNode
均通过此 Mixin 获得子步骤功能。
"""
from typing import Any, ClassVar
from workflows.nodes.base import ExecutionContext
class SubStepMixin:
 """子步骤生命周期 Mixin。
 子类覆盖 sub_steps ClassVar 声明具体步骤列表，
 在 execute 中调用 _init_sub_steps 和 emit_sub_step 推进状态。
 """
 # 子步骤声明：子类覆盖此列表定义具体步骤 [(step_type, name), ...]
 sub_steps: ClassVar[list[tuple[str, str]]] =
 async def _init_sub_steps(self, context: ExecutionContext) -> None:
 """批量创建所有 pending 子步骤记录。
 执行开始时调用，前端可预知子步骤总数。
 子类若覆盖 execute 需在开头显式调用此方法。
 """
 if not self.sub_steps or not context.node_execution:
 return
 from workflows.models.execution import NodeExecution, NodeSubStep
 objs = [
 NodeSubStep(
 node_execution=context.node_execution,
 step_type=step_type,
 name=name,
 step_order=i,
 )
 for i, (step_type, name) in enumerate(self.sub_steps)
 ]
 await NodeSubStep.objects.abulk_create(objs)
 # 初始化进度缓存
 await NodeExecution.objects.filter(
 id=context.node_execution.id
 ).aupdate(sub_step_total_count=len(self.sub_steps))
 async def emit_sub_step(
 self,
 context: ExecutionContext,
 step_type: str,
 status: str,
 output_data: dict[str, Any] | None = None,
 ) -> None:
 """推进子步骤状态并广播事件。
 写库更新 NodeSubStep 状态，同步更新 NodeExecution 进度缓存，
 通过 Django signal 触发 WS 广播。
 Args:
 context: 节点执行上下文。
 step_type: 子步骤类型标识（与 sub_steps ClassVar 中的 step_type 对应）。
 status: 目标状态（SubStepStatus 枚举值）。
 output_data: 可选的输出数据（为前端展示预留）。
 """
 if not context.node_execution:
 return
 from django.db import models as db_models
 from django.utils import timezone
 from workflows.models.execution import NodeExecution, NodeSubStep, SubStepStatus
 update_fields: dict[str, Any] = {"status": status}
 if status == SubStepStatus.RUNNING:
 update_fields["started_at"] = timezone.now
 elif status in (SubStepStatus.COMPLETED, SubStepStatus.FAILED):
 update_fields["completed_at"] = timezone.now
 if output_data:
 update_fields["output_data"] = output_data
 await NodeSubStep.objects.filter(
 node_execution=context.node_execution,
 step_type=step_type,
 ).aupdate(**update_fields)
 # 更新进度缓存（仅 completed 状态递增）
 if status == SubStepStatus.COMPLETED:
 await NodeExecution.objects.filter(
 id=context.node_execution.id
 ).aupdate(
 sub_step_completed_count=db_models.F("sub_step_completed_count") + 1
 )
 # 取回更新后的 sub_step 并发送 signal
 sub_step = await NodeSubStep.objects.filter(
 node_execution=context.node_execution,
 step_type=step_type,
 ).afirst
 if sub_step:
 from workflows.signals import sub_step_updated
 sub_step_updated.send(
 sender=type(self),
 sub_step=sub_step,
 node_execution_id=context.node_execution.id,
 )
