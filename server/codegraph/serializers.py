"""codegraph REST API 序列化器 —— 4 个 ModelSerializer 映射 codegraph 模型字段。"""
from rest_framework import serializers
from codegraph.models import CallEdge, Endpoint, ImportEdge, Symbol
class SymbolSerializer(serializers.ModelSerializer):
 """Symbol 序列化器。
 关键差异 1：start_line/end_line 模型字段对外别名为 line_start/line_end。
 """
 line_start = serializers.IntegerField(source="start_line", read_only=True)
 line_end = serializers.IntegerField(source="end_line", read_only=True)
 class Meta:
 model = Symbol
 fields = [
 "id",
 "name",
 "symbol_type",
 "file_path",
 "line_start",
 "line_end",
 "signature",
 "is_async",
 ]
class CallEdgeSerializer(serializers.ModelSerializer):
 """CallEdge 序列化器。call_type 只有 DIRECT/METHOD/ATTRIBUTE（无 INHERITANCE）。"""
 class Meta:
 model = CallEdge
 fields = [
 "id",
 "caller_symbol_id",
 "callee_name",
 "call_type",
 "line_number",
 ]
class ImportEdgeSerializer(serializers.ModelSerializer):
 """ImportEdge 序列化器。"""
 class Meta:
 model = ImportEdge
 fields = [
 "id",
 "source_file",
 "target_module",
 "imported_names",
 "is_relative",
 ]
class EndpointSerializer(serializers.ModelSerializer):
 """Endpoint 序列化器。"""
 class Meta:
 model = Endpoint
 fields = [
 "id",
 "http_method",
 "url_path",
 "handler_name",
 "view_type",
 "file_path",
 "line_number",
 ]
__all__ = [
 "CallEdgeSerializer",
 "EndpointSerializer",
 "ImportEdgeSerializer",
 "SymbolSerializer",
]
