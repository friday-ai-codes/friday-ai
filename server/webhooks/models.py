"""Webhooks app models."""
import uuid
from django.db import models
from projects.models import Project
from tasks.models import Task
class WebhookLogStatus(models.TextChoices):
 """Webhook log status choices."""
 ACCEPTED = "accepted", "已接受"
 IGNORED = "ignored", "已忽略"
 ERROR = "error", "错误"
 DUPLICATE = "duplicate", "重复"
class WebhookLog(models.Model):
 """Log for incoming webhook requests."""
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 event_uuid = models.CharField(max_length=100, blank=True, null=True)
 event_type = models.CharField(max_length=100, blank=True, default="")
 project_key = models.CharField(max_length=100, blank=True, null=True)
 project = models.ForeignKey(
 Project,
 on_delete=models.SET_NULL,
 null=True,
 blank=True,
 related_name="webhook_logs",
 )
 raw_request = models.TextField
 status = models.CharField(
 max_length=20,
 choices=WebhookLogStatus.choices,
 default=WebhookLogStatus.ACCEPTED,
 )
 error_message = models.TextField(blank=True, null=True)
 created_at = models.DateTimeField(auto_now_add=True)
 class Meta:
 db_table = "webhook_logs"
 verbose_name = "Webhook 日志"
 verbose_name_plural = "Webhook 日志"
 ordering = ["-created_at"]
 def __str__(self):
 return f"{self.event_type} - {self.status}"
class WorkItemLog(models.Model):
 """Log for Feishu work item details."""
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 work_item_id = models.CharField(max_length=100)
 work_item_type = models.CharField(max_length=50, blank=True, default="")
 project_key = models.CharField(max_length=100, blank=True, null=True)
 project = models.ForeignKey(
 Project,
 on_delete=models.SET_NULL,
 null=True,
 blank=True,
 related_name="work_item_logs",
 )
 task = models.ForeignKey(
 Task,
 on_delete=models.SET_NULL,
 null=True,
 blank=True,
 related_name="work_item_logs",
 )
 raw_response = models.TextField
 created_at = models.DateTimeField(auto_now_add=True)
 class Meta:
 db_table = "work_item_logs"
 verbose_name = "工作项日志"
 verbose_name_plural = "工作项日志"
 ordering = ["-created_at"]
 def __str__(self):
 return f"WorkItem {self.work_item_id}"
