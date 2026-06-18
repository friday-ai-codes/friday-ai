"""codegraph REST API 序列化器 —— 4 个 ModelSerializer 映射 codegraph 模型字段
+ 1 个 GraphBuildHistorySerializer（implementation-03 list endpoint）。"""

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
    """CallEdge 序列化器。

    implementation 起暴露跨文件 / 模块级字段：caller_file / callee_symbol_id /
    callee_file / is_cross_file（均 nullable，DRF 自动允许 null）。
    call_type 取值含 DIRECT/METHOD/ATTRIBUTE/JSX/TEMPLATE_REF。
    """

    class Meta:
        model = CallEdge
        fields = [
            "id",
            "caller_symbol_id",
            "caller_file",
            "callee_name",
            "callee_symbol_id",
            "callee_file",
            "is_cross_file",
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


class GraphBuildHistorySerializer(serializers.Serializer):
    """GraphBuildHistory 记录序列化器（implementation-03 list endpoint）。

    字段口径与 ``IndexHistorySerializer``（``repositories/index_views.py:807``）同构 ——
    平铺 14 字段：id / trigger_type / status / 7 个 counts(files_* + symbols_count +
    imports_count + calls_count + endpoints_count) / started_at / finished_at /
    error_message / created_at，外加计算字段 ``duration_seconds``（构建耗时）。

    ``error_message`` 用 ``allow_blank=True``（与 model 的 ``default=""``
    语义对齐，区别于 ``IndexHistory.error_message`` 的 ``null=True`` 风格）。

    ``duration_seconds``：``finished_at - started_at`` 的秒数（保留 1 位小数）；
    仍在构建（无 ``finished_at``）或缺 ``started_at`` 时为 ``None``，由前端决定是否
    改用「实时计时」展示。
    """

    id = serializers.UUIDField()
    trigger_type = serializers.CharField()
    status = serializers.CharField()
    files_total = serializers.IntegerField()
    files_processed = serializers.IntegerField()
    files_failed = serializers.IntegerField()
    symbols_count = serializers.IntegerField()
    imports_count = serializers.IntegerField()
    calls_count = serializers.IntegerField()
    endpoints_count = serializers.IntegerField()
    started_at = serializers.DateTimeField(allow_null=True)
    finished_at = serializers.DateTimeField(allow_null=True)
    duration_seconds = serializers.SerializerMethodField()
    error_message = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()

    def get_duration_seconds(self, obj: object) -> float | None:
        """构建耗时（秒）：终态行才有；仍 RUNNING / 缺 started_at 时返 None。"""
        started_at = getattr(obj, "started_at", None)
        finished_at = getattr(obj, "finished_at", None)
        if started_at is None or finished_at is None:
            return None
        return round((finished_at - started_at).total_seconds(), 1)


__all__ = [
    "CallEdgeSerializer",
    "EndpointSerializer",
    "GraphBuildHistorySerializer",
    "ImportEdgeSerializer",
    "SymbolSerializer",
]
