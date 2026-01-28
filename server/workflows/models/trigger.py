"""WorkflowTrigger model for event-based workflow triggering."""
import uuid
from django.db import models
class TriggerEventType(models.TextChoices):
 """飞书 Webhook 事件类型"""
 WORKITEM_CREATE = "WorkitemCreateEvent", "工作项创建"
 WORKITEM_STATUS = "WorkitemStatusEvent", "状态变更"
 WORKITEM_COMMENT = "WorkitemCommentEvent", "评论事件"
 WORKITEM_UPDATE = "WorkitemUpdateEvent", "字段更新"
 WORKFLOW_NODE_STATUS = "WorkFlowNodeStatusEvent", "节点流转"
 WORKITEM_FINISH = "WorkitemFinishEvent", "工作项完成"
 WORKITEM_DELETE = "WorkitemDeleteEvent", "工作项删除"
 WORKITEM_ABORTED = "WorkitemAbortedEvent", "工作项终止"
 WORKITEM_RESTORE = "WorkitemRestoreEvent", "工作项恢复"
 TASK_CREATE = "TaskCreateEvent", "任务创建"
 TASK_STATUS = "TaskStatusEvent", "任务状态变更"
 TASK_UPDATE = "TaskUpdateEvent", "任务修改"
class WorkflowTrigger(models.Model):
 """工作流触发器配置
 定义哪些飞书事件可以自动触发工作流执行。
 支持事件过滤和输入数据校验。
 """
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 workflow = models.ForeignKey(
 "workflows.Workflow",
 on_delete=models.CASCADE,
 related_name="triggers",
 verbose_name="工作流",
 )
 # 事件配置
 event_type = models.CharField(
 max_length=50,
 choices=TriggerEventType.choices,
 verbose_name="事件类型",
 help_text="监听的飞书 Webhook 事件类型",
 )
 # 过滤条件
 filter_config = models.JSONField(
 default=dict,
 blank=True,
 verbose_name="过滤条件",
 help_text="JSON 格式的过滤条件，如 project_key, work_item_type, status 等",
 )
 # 输入 Schema 校验
 input_schema = models.JSONField(
 default=dict,
 blank=True,
 verbose_name="输入参数 Schema",
 help_text="JSON Schema 格式，用于校验触发器输入数据",
 )
 # 状态
 is_active = models.BooleanField(
 default=True,
 verbose_name="是否启用",
 )
 # 触发器名称和描述（可选）
 name = models.CharField(
 max_length=200,
 blank=True,
 default="",
 verbose_name="触发器名称",
 )
 description = models.TextField(
 blank=True,
 default="",
 verbose_name="描述",
 )
 # 时间戳
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 class Meta:
 db_table = "workflow_triggers"
 verbose_name = "工作流触发器"
 verbose_name_plural = "工作流触发器"
 ordering = ["-created_at"]
 indexes = [
 models.Index(fields=["workflow", "is_active"]),
 models.Index(fields=["event_type", "is_active"]),
 ]
 # 同一工作流不能有重复的事件类型触发器（可根据需求移除）
 # unique_together = [("workflow", "event_type")]
 def __str__(self) -> str:
 name = self.name or self.get_event_type_display
 return f"{name} ({self.workflow.name})"
 def matches_event(self, event_type: str, payload: dict) -> bool:
 """检查事件是否匹配此触发器
 Args:
 event_type: 事件类型
 payload: Webhook payload
 Returns:
 是否匹配
 """
 # 事件类型必须匹配
 if self.event_type != event_type:
 return False
 # 触发器必须启用
 if not self.is_active:
 return False
 # 检查过滤条件
 return self._matches_filter(payload)
 def _matches_filter(self, payload: dict) -> bool:
 """检查 payload 是否满足过滤条件
 Args:
 payload: Webhook payload
 Returns:
 是否匹配
 """
 if not self.filter_config:
 return True
 for key, expected_value in self.filter_config.items:
 actual_value = self._get_nested_value(payload, key)
 if isinstance(expected_value, list):
 # 列表匹配：actual_value 在 expected_value 中
 if actual_value not in expected_value:
 return False
 elif actual_value != expected_value:
 return False
 return True
 def _get_nested_value(self, data: dict, key: str):
 """获取嵌套字典中的值，支持点分隔路径
 Args:
 data: 数据字典
 key: 键路径，如 "cur_work_item_status.state_key"
 Returns:
 对应的值，不存在则返回 None
 """
 keys = key.split(".")
 current = data
 for k in keys:
 if isinstance(current, dict):
 current = current.get(k)
 else:
 return None
 return current
 def validate_input(self, payload: dict) -> list[str]:
 """使用 JSON Schema 校验输入数据
 Args:
 payload: 输入数据
 Returns:
 错误列表，为空表示校验通过
 """
 if not self.input_schema:
 return
 import jsonschema
 errors =
 try:
 jsonschema.validate(payload, self.input_schema)
 except jsonschema.ValidationError as e:
 errors.append(str(e.message))
 except jsonschema.SchemaError as e:
 errors.append(f"Schema 错误: {e.message}")
 return errors
