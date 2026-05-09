"""代码知识图谱数据模型。"""
import uuid
from typing import TYPE_CHECKING
from django.db import models
if TYPE_CHECKING:
 from django.db.models import QuerySet
class Symbol(models.Model):
 """代码符号 —— 函数 / 类 / 方法 / 顶层变量。"""
 class SymbolType(models.TextChoices):
 FUNCTION = "FUNCTION", "函数"
 CLASS = "CLASS", "类"
 METHOD = "METHOD", "方法"
 VARIABLE = "VARIABLE", "变量"
 if TYPE_CHECKING:
 outgoing_calls: "QuerySet[CallEdge]"
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 repository = models.ForeignKey(
 "repositories.Repository",
 on_delete=models.CASCADE,
 related_name="symbols",
 )
 name = models.CharField(max_length=255, db_index=True)
 symbol_type = models.CharField(max_length=16, choices=SymbolType.choices, db_index=True)
 file_path = models.CharField(max_length=512, db_index=True)
 start_line = models.IntegerField
 end_line = models.IntegerField
 signature = models.TextField(blank=True)
 is_async = models.BooleanField(default=False)
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 class Meta:
 verbose_name = "符号"
 verbose_name_plural = "符号"
 indexes = [
 models.Index(fields=["repository", "file_path"]),
 models.Index(fields=["repository", "name"]),
 ]
 unique_together = [("repository", "file_path", "name", "start_line")]
 def __str__(self) -> str:
 return f"{self.name} ({self.symbol_type}) [{self.file_path}:{self.start_line}]"
class ImportEdge(models.Model):
 """Import 导入边 —— 文件 A 从模块 B 导入了哪些符号。"""
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 repository = models.ForeignKey(
 "repositories.Repository",
 on_delete=models.CASCADE,
 related_name="import_edges",
 )
 source_file = models.CharField(max_length=512, db_index=True)
 target_module = models.CharField(max_length=512, db_index=True)
 imported_names = models.JSONField(default=list)
 is_relative = models.BooleanField(default=False)
 created_at = models.DateTimeField(auto_now_add=True)
 class Meta:
 verbose_name = "导入边"
 verbose_name_plural = "导入边"
 indexes = [
 models.Index(fields=["repository", "source_file"]),
 models.Index(fields=["repository", "target_module"]),
 ]
 def __str__(self) -> str:
 return f"{self.source_file} -> {self.target_module}"
class CallEdge(models.Model):
 """调用边 —— 函数 A 在文件内调用了函数/方法 B。Phase 仅文件内解析。"""
 class CallType(models.TextChoices):
 DIRECT = "DIRECT", "直接调用"
 METHOD = "METHOD", "方法调用"
 ATTRIBUTE = "ATTRIBUTE", "属性访问"
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 repository = models.ForeignKey(
 "repositories.Repository",
 on_delete=models.CASCADE,
 related_name="call_edges",
 )
 caller_symbol = models.ForeignKey(
 Symbol,
 on_delete=models.CASCADE,
 related_name="outgoing_calls",
 )
 callee_name = models.CharField(max_length=255, db_index=True)
 call_type = models.CharField(max_length=16, choices=CallType.choices)
 line_number = models.IntegerField
 created_at = models.DateTimeField(auto_now_add=True)
 class Meta:
 verbose_name = "调用边"
 verbose_name_plural = "调用边"
 indexes = [
 models.Index(fields=["repository", "caller_symbol"]),
 models.Index(fields=["repository", "callee_name"]),
 ]
 def __str__(self) -> str:
 return f"{self.caller_symbol.name} -> {self.callee_name} [{self.call_type}]"
class Endpoint(models.Model):
 """API 端点 —— HTTP 方法 + URL 路径 + 处理函数的映射。"""
 class ViewType(models.TextChoices):
 FUNCTION_VIEW = "FUNCTION_VIEW", "函数视图"
 CLASS_VIEW = "CLASS_VIEW", "类视图"
 VIEWSET = "VIEWSET", "ViewSet"
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 repository = models.ForeignKey(
 "repositories.Repository",
 on_delete=models.CASCADE,
 related_name="endpoints",
 )
 http_method = models.CharField(max_length=16)
 url_path = models.CharField(max_length=512, db_index=True)
 handler_name = models.CharField(max_length=255)
 view_type = models.CharField(max_length=32, choices=ViewType.choices)
 file_path = models.CharField(max_length=512)
 line_number = models.IntegerField
 created_at = models.DateTimeField(auto_now_add=True)
 class Meta:
 verbose_name = "端点"
 verbose_name_plural = "端点"
 indexes = [
 models.Index(fields=["repository", "url_path"]),
 models.Index(fields=["repository", "handler_name"]),
 ]
 def __str__(self) -> str:
 return f"{self.http_method} {self.url_path} -> {self.handler_name}"
__all__ = [
 "Symbol",
 "ImportEdge",
 "CallEdge",
 "Endpoint",
]
