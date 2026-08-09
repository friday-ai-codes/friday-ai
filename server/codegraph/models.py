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
        incoming_calls: "QuerySet[CallEdge]"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repository = models.ForeignKey(
        "repositories.Repository",
        on_delete=models.CASCADE,
        related_name="symbols",
    )
    # 分支隔离维度。"" = base 分支（与向量 overlay 语义同构），
    # feature 分支由 implementation 写入侧透传；max_length 对齐 RepositoryBranchIndex.branch_name。
    branch_name = models.CharField(max_length=200, default="", blank=True)
    name = models.CharField(max_length=255, db_index=True)
    symbol_type = models.CharField(max_length=16, choices=SymbolType.choices, db_index=True)
    file_path = models.CharField(max_length=512, db_index=True)
    start_line = models.IntegerField()
    end_line = models.IntegerField()
    signature = models.TextField(blank=True)
    is_async = models.BooleanField(default=False)
    # 该符号所属 RAG chunk_id（与 ChunkRegistry.chunk_id / Qdrant point_id
    # 同源）。索引时由「一套 AST 双供」同源回填，建立 chunk ↔ Symbol 双向绑定，取代
    # CallEdgeBuilder 等的 SymbolChunkResolver 行号 bisect 软对齐。NULL = 未绑定
    # （历史数据 / 该符号未命中任何 chunk）。不做 FK（per code_relations contract 柔性引用）。
    chunk_id = models.UUIDField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "符号"
        verbose_name_plural = "符号"
        indexes = [
            models.Index(fields=["repository", "file_path"]),
            models.Index(fields=["repository", "name"]),
            # 分支隔离复合索引（旧索引保留，新增并存）。
            models.Index(fields=["repository", "branch_name", "file_path"]),
        ]
        # branch_name 进 unique 是 Critical 1 防御性冗余，
        # implementation 写入侧必须同步透传 branch_name，否则撞约束（Pitfall 4）。
        unique_together = [("repository", "branch_name", "file_path", "name", "start_line")]

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
    # 分支隔离维度。"" = base 分支，feature 由 implementation 写入侧透传。
    branch_name = models.CharField(max_length=200, default="", blank=True)
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
            # 分支隔离复合索引。
            models.Index(fields=["repository", "branch_name", "source_file"]),
        ]

    def __str__(self) -> str:
        return f"{self.source_file} -> {self.target_module}"


class CallEdge(models.Model):
    """调用边 —— A 调用 B 的关系。

    implementation 起承载跨文件 / 模块级 caller / 外键化 callee：

    - ``caller_symbol`` 可空（``SET_NULL``）：模块级调用（不在任何函数体内）写成
      ``caller_symbol=NULL`` + ``caller_file=<文件>`` 的边。注意 ``caller_symbol``
      由 ``CASCADE`` 改 ``SET_NULL`` 后，删除 ``Symbol`` **不再**级联删除引用它的
      边（只置 NULL），per-file 幂等删除完全转移到 writer 按 ``caller_file`` 的
      显式删除（函数内边与模块级边统一清理，见 ``GraphWriter``）。
    - ``callee_symbol``（``SET_NULL`` + ``incoming_calls``）：删除 ``Symbol`` 不级联
      删除引用它的边，FK 自动置 NULL，并可经 ``incoming_calls`` 反查「谁调用我」。
      跨文件符号解析（裸名 → ``callee_symbol``/``callee_file``）属 implementation+，本表
      只产外键字段 + 完整 raw，留空待回填。
    - ``callee_name`` 始终保留作向后兼容兜底。
    """

    class CallType(models.TextChoices):
        DIRECT = "DIRECT", "直接调用"
        METHOD = "METHOD", "方法调用"
        ATTRIBUTE = "ATTRIBUTE", "属性访问"
        JSX = "JSX", "JSX 组件引用"
        TEMPLATE_REF = "TEMPLATE_REF", "模板组件引用"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repository = models.ForeignKey(
        "repositories.Repository",
        on_delete=models.CASCADE,
        related_name="call_edges",
    )
    # 分支隔离维度。"" = base 分支，feature 由 implementation 写入侧透传。
    branch_name = models.CharField(max_length=200, default="", blank=True)
    caller_symbol = models.ForeignKey(
        Symbol,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="outgoing_calls",
    )
    caller_file = models.CharField(max_length=512, db_index=True, default="")
    callee_name = models.CharField(max_length=255, db_index=True)
    callee_symbol = models.ForeignKey(
        Symbol,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="incoming_calls",
    )
    callee_file = models.CharField(max_length=512, null=True, blank=True, db_index=True)
    # selector / 对象调用的包或对象限定符，如 Go ``pkg.Func()`` 的 ``pkg``、
    # ``obj.method()`` 的 ``obj``。供 Go 跨包 selector 调用解析（work item）按 import
    # 本地名定位目标包目录；存量边默认 NULL，零破坏。
    callee_qualifier = models.CharField(
        max_length=255, null=True, blank=True, default=None, db_index=True
    )
    is_cross_file = models.BooleanField(default=False)
    call_type = models.CharField(max_length=16, choices=CallType.choices)
    line_number = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "调用边"
        verbose_name_plural = "调用边"
        indexes = [
            models.Index(fields=["repository", "caller_symbol"]),
            models.Index(fields=["repository", "callee_name"]),
            models.Index(fields=["repository", "caller_file"]),
            models.Index(fields=["repository", "callee_file"]),
            # 分支隔离复合索引。
            models.Index(fields=["repository", "branch_name", "caller_file"]),
        ]

    def __str__(self) -> str:
        # caller_symbol 可空：模块级边用 caller_file 兜底，避免 None.name 崩溃。
        caller_symbol = self.caller_symbol
        caller = caller_symbol.name if caller_symbol is not None else f"<{self.caller_file}>"
        return f"{caller} -> {self.callee_name} [{self.call_type}]"


class Endpoint(models.Model):
    """API 端点 —— HTTP 方法 + URL 路径 + 处理函数的映射。"""

    if TYPE_CHECKING:
        cross_repo_callers: "QuerySet[CrossRepoApiCall]"

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
    # 分支隔离维度。"" = base 分支，feature 由 implementation 写入侧透传。
    branch_name = models.CharField(max_length=200, default="", blank=True)
    http_method = models.CharField(max_length=16)
    url_path = models.CharField(max_length=512, db_index=True)
    handler_name = models.CharField(max_length=255)
    view_type = models.CharField(max_length=32, choices=ViewType.choices)
    file_path = models.CharField(max_length=512)
    line_number = models.IntegerField()
    metadata = models.JSONField(null=True, blank=True, default=None)  # ogin.G* 参数验证元数据
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "端点"
        verbose_name_plural = "端点"
        indexes = [
            models.Index(fields=["repository", "url_path"]),
            models.Index(fields=["repository", "handler_name"]),
            # 分支隔离复合索引。
            models.Index(fields=["repository", "branch_name", "file_path"]),
        ]

    def __str__(self) -> str:
        return f"{self.http_method} {self.url_path} -> {self.handler_name}"


class ApiWrapper(models.Model):
    """前端 ApiWrapper —— 封装 LowLevelHelper 调用的 export function。

    通过三步推断算法（implementation）自动识别：
    Step 0: axios 锚点定位 LowLevelHelper；Step 1: 反向找调用者为 ApiWrapper。
    metadata 存 JSDoc 元数据（work item）：@description/@author/@date/yapi URL。
    """

    if TYPE_CHECKING:
        call_sites: "QuerySet[ApiCallSite]"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repository = models.ForeignKey(
        "repositories.Repository",
        on_delete=models.CASCADE,
        related_name="api_wrappers",
    )
    # 分支隔离维度。"" = base 分支，feature 由 implementation 写入侧透传。
    branch_name = models.CharField(max_length=200, default="", blank=True)
    file_path = models.CharField(max_length=512, db_index=True)
    function_symbol = models.CharField(max_length=255)
    http_method = models.CharField(max_length=16)
    url_path_raw = models.CharField(max_length=512)
    url_path_pattern = models.CharField(max_length=512, db_index=True)
    detected_via = models.CharField(max_length=64, default="axios_anchor")
    line_number = models.IntegerField(default=0)
    metadata = models.JSONField(null=True, blank=True, default=None)  # JSDoc 元数据
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "API Wrapper"
        verbose_name_plural = "API Wrappers"
        indexes = [
            models.Index(fields=["repository", "url_path_pattern"]),
            models.Index(fields=["repository", "function_symbol"]),
            # 分支隔离复合索引。
            models.Index(fields=["repository", "branch_name", "file_path"]),
        ]
        # branch_name 进 unique（Pitfall 4：294 写入侧须同步透传）。
        unique_together = [("repository", "branch_name", "file_path", "function_symbol")]

    def __str__(self) -> str:
        return f"{self.http_method} {self.url_path_pattern} ({self.function_symbol})"


class ApiCallSite(models.Model):
    """ApiWrapper 调用点 —— 通过 volar textDocument/references 反向追踪（work item）。"""

    if TYPE_CHECKING:
        cross_repo_calls: "QuerySet[CrossRepoApiCall]"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repository = models.ForeignKey(
        "repositories.Repository",
        on_delete=models.CASCADE,
        related_name="api_call_sites",
    )
    api_wrapper = models.ForeignKey(
        ApiWrapper,
        on_delete=models.CASCADE,
        related_name="call_sites",
    )
    caller_file = models.CharField(max_length=512, db_index=True)
    caller_function = models.CharField(max_length=255)
    line_number = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "API Call Site"
        verbose_name_plural = "API Call Sites"
        indexes = [
            models.Index(fields=["repository", "caller_file"]),
            models.Index(fields=["api_wrapper"]),
        ]

    def __str__(self) -> str:
        return f"{self.caller_function} @ {self.caller_file}:{self.line_number} → {self.api_wrapper.function_symbol}"


class CrossRepoApiCall(models.Model):
    """跨仓 API 调用匹配记录 —— ApiCallSite × Endpoint offline join 结果。

    通过 offline join（implementation）按 (http_method, url_path_pattern) 精确匹配。
    match_confidence: 1.0 完全匹配 / 0.7 path-only / 0.4 部分匹配。
    per work item
    """

    if TYPE_CHECKING:
        pass

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    call_site = models.ForeignKey(
        ApiCallSite,
        on_delete=models.CASCADE,
        related_name="cross_repo_calls",
    )
    endpoint = models.ForeignKey(
        Endpoint,
        on_delete=models.CASCADE,
        related_name="cross_repo_callers",
    )
    match_confidence = models.FloatField(
        help_text="1.0=完全匹配 / 0.7=path-only / 0.4=部分匹配",
    )
    matched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "跨仓 API 调用"
        verbose_name_plural = "跨仓 API 调用"
        unique_together = [("call_site", "endpoint")]
        indexes = [
            models.Index(fields=["call_site"], name="crossrepo_call_site_idx"),
            models.Index(fields=["endpoint"], name="crossrepo_endpoint_idx"),
            models.Index(fields=["match_confidence"], name="crossrepo_confidence_idx"),
        ]

    def __str__(self) -> str:
        return (
            f"{self.call_site} → {self.endpoint} "
            f"[confidence={self.match_confidence}]"
        )


class SymbolCommunity(models.Model):
    """符号社区 —— Louvain（等）划分结果，成员以 JSON 软引用 Symbol.id。

    Phase 125 / MOD-01：独立模型纯加表，⛔ 不给 Symbol 加 community_id / FK / M2M。
    ``members`` 每项至少含 ``symbol_id``（UUID 字符串软引用），对齐 ``Symbol.chunk_id``
    柔性引用先例；增量索引 per-file 删建 Symbol 不会级联丢社区标注。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repository = models.ForeignKey(
        "repositories.Repository",
        on_delete=models.CASCADE,
        related_name="symbol_communities",
    )
    # 分支隔离维度。"" = base 分支（与 Symbol / 向量 overlay 语义同构）。
    branch_name = models.CharField(max_length=200, default="", blank=True)
    # 指纹派生稳定键（通常 member_fingerprint[:16]），仓内唯一。
    community_key = models.CharField(max_length=64)
    algorithm = models.CharField(max_length=32, default="louvain")
    member_count = models.PositiveIntegerField(default=0)
    members = models.JSONField(default=list)
    # 完整稳定键列表，供 Jaccard 对账；与 members 展示截断分离（WR-02）。
    member_keys = models.JSONField(default=list)
    top_files = models.JSONField(default=list)
    member_fingerprint = models.CharField(max_length=64, blank=True, default="")
    summary = models.TextField(null=True, blank=True)
    summary_model = models.CharField(max_length=128, null=True, blank=True)
    summary_generated_at = models.DateTimeField(null=True, blank=True)
    # 对齐 last_indexed_commit_sha 水位，供消费方判 stale。
    built_at_sha = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "符号社区"
        verbose_name_plural = "符号社区"
        unique_together = [("repository", "branch_name", "community_key")]
        indexes = [
            models.Index(fields=["repository", "branch_name"]),
            models.Index(fields=["repository", "branch_name", "member_fingerprint"]),
        ]

    def __str__(self) -> str:
        return (
            f"SymbolCommunity({self.community_key}, n={self.member_count}, "
            f"algo={self.algorithm})"
        )


class ProcessTrace(models.Model):
    """执行流摘要 —— Endpoint 入口正向 BFS 主干路径（Phase 126 / EXEC-01）。

    ⛔ 类名锁定为 ``ProcessTrace``，禁止命名 ``Process``（与
    ``services.process_runtime.ProcessEngine`` / ``ProcessDefinition`` 撞名）。
    ``entry_endpoint`` 为 JSON 快照，⛔ 不对 ``Endpoint`` 建 FK（索引删建会牵连）。
    ``steps`` 存主干有序摘要软引用，非整图展开。
    """

    class CommunityClass(models.TextChoices):
        INTRA_COMMUNITY = "intra_community", "社区内"
        CROSS_COMMUNITY = "cross_community", "跨社区"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repository = models.ForeignKey(
        "repositories.Repository",
        on_delete=models.CASCADE,
        related_name="process_traces",
    )
    # 分支隔离维度。"" = base 分支（与 Symbol / Endpoint / SymbolCommunity 同构）。
    branch_name = models.CharField(max_length=200, default="", blank=True)
    process_key = models.CharField(max_length=640)
    name = models.CharField(max_length=640)
    # Endpoint 快照：http_method / url_path / handler_name / file_path / line_number
    entry_endpoint = models.JSONField(default=dict)
    steps = models.JSONField(default=list)
    # 封闭枚举；无法对账时落空串 + rebuild 写 degradation（D-05）。
    community_class = models.CharField(
        max_length=32,
        choices=CommunityClass.choices,
        blank=True,
        default="",
    )
    step_count = models.PositiveIntegerField(default=0)
    # cycle / async_boundary / truncated 等过程级标记。
    flags = models.JSONField(default=dict, blank=True)
    # 对齐 last_indexed_commit_sha 水位，供消费方判 stale。
    built_at_sha = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "执行流"
        verbose_name_plural = "执行流"
        unique_together = [("repository", "branch_name", "process_key")]
        indexes = [
            models.Index(fields=["repository", "branch_name"]),
        ]

    def __str__(self) -> str:
        return f"ProcessTrace({self.process_key}, steps={self.step_count})"


__all__ = [
    "Symbol",
    "ImportEdge",
    "CallEdge",
    "Endpoint",
    "ApiWrapper",
    "ApiCallSite",
    "CrossRepoApiCall",
    "SymbolCommunity",
    "ProcessTrace",
]
