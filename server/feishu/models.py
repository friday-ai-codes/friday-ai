"""Feishu models: TriggerLog for unified webhook and work item logging."""
import uuid
from django.db import models
class TriggerLogStatus(models.TextChoices):
 """Trigger log status choices."""
 ACCEPTED = "accepted", "已接受"
 IGNORED = "ignored", "已忽略"
 ERROR = "error", "错误"
 DUPLICATE = "duplicate", "重复"
class TriggerLog(models.Model):
 """Unified log for Feishu webhook triggers and work item details.
 Combines the functionality of WebhookLog and WorkItemLog into a single
 model that tracks the complete event processing chain.
 """
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 # Project reference (use string reference to avoid circular import)
 project = models.ForeignKey(
 "projects.Project",
 on_delete=models.SET_NULL,
 null=True,
 blank=True,
 related_name="trigger_logs",
 )
 project_key = models.CharField(max_length=100, blank=True, null=True)
 # Webhook event info
 event_uuid = models.CharField(max_length=100, blank=True, null=True, unique=True)
 event_type = models.CharField(max_length=100, blank=True, default="")
 webhook_raw_request = models.TextField(blank=True, default="")
 # Work item info
 work_item_id = models.CharField(max_length=50, blank=True, null=True)
 work_item_type = models.CharField(max_length=50, blank=True, default="")
 work_item_name = models.CharField(max_length=500, blank=True, default="")
 work_item_raw_response = models.TextField(blank=True, default="")
 # Extracted key fields for display
 prd_url = models.URLField(max_length=1000, blank=True, default="")
 description = models.TextField(blank=True, default="")
 tech_doc_url = models.URLField(max_length=1000, blank=True, default="")
 # Status
 status = models.CharField(
 max_length=20,
 choices=TriggerLogStatus.choices,
 default=TriggerLogStatus.ACCEPTED,
 )
 error_message = models.TextField(blank=True, null=True)
 created_at = models.DateTimeField(auto_now_add=True)
 class Meta:
 db_table = "trigger_logs"
 verbose_name = "触发日志"
 verbose_name_plural = "触发日志"
 ordering = ["-created_at"]
 def __str__(self):
 return f"{self.event_type} - {self.work_item_name or self.work_item_id}"
# Key field constants for extracting from work item fields
class KeyFields:
 """Key field identifiers for work item fields."""
 PRD_URL = "field_bcff9b" # 需求文档链接
 DESCRIPTION = "description" # 需求描述
 TECH_DOC_URL = "field_3f6667" # 技术方案文档链接
