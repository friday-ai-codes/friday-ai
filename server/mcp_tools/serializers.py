"""MCP read tools 请求 schema。"""

from __future__ import annotations

from typing import cast

from rest_framework import serializers


class RouteRepositoriesRequestSerializer(serializers.Serializer):
    query = serializers.CharField(required=True, allow_blank=False, max_length=1000)
    top_k = serializers.IntegerField(required=False, default=3, min_value=1, max_value=10)


class SearchRagChunksRequestSerializer(serializers.Serializer):
    # 目标范围：repository_id（单仓便捷参数）/ repository_ids（显式多仓）/
    # all_repositories（显式全量跨仓，受 max_repos 限制），三者至少给一种。
    # 与 GrepRepositoryRequestSerializer 同语义：省略多仓参数 = 既有单仓行为。
    repository_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    repository_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
        default=list,
        max_length=20,
    )
    all_repositories = serializers.BooleanField(required=False, default=False)
    max_repos = serializers.IntegerField(required=False, default=10, min_value=1, max_value=20)
    query = serializers.CharField(required=True, allow_blank=False, max_length=1000)
    branch = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    top_k = serializers.IntegerField(required=False, default=30, min_value=1, max_value=50)
    max_tokens = serializers.IntegerField(required=False, default=8000, min_value=1, max_value=32000)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        targets = [str(rid) for rid in cast(list[object], attrs.get("repository_ids") or [])]
        single = attrs.get("repository_id")
        if single is not None and str(single) not in targets:
            targets.insert(0, str(single))
        if not targets and not attrs.get("all_repositories"):
            raise serializers.ValidationError(
                "必须提供 repository_id / repository_ids，或显式设置 all_repositories=true"
            )
        if str(attrs.get("branch") or "").strip() and len(targets) != 1:
            raise serializers.ValidationError("branch 仅支持单仓检索时指定")
        attrs["target_repository_ids"] = targets
        return attrs


class GetRepositoryRequestSerializer(serializers.Serializer):
    repository_id = serializers.UUIDField(required=True)


class ListRepositoryFilesRequestSerializer(serializers.Serializer):
    repository_id = serializers.UUIDField(required=True)
    branch = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    path = serializers.CharField(required=False, allow_blank=True, default="")
    recursive = serializers.BooleanField(required=False, default=False)
    page = serializers.IntegerField(required=False, default=1, min_value=1)
    page_size = serializers.IntegerField(required=False, default=50, min_value=1, max_value=200)


class GetRepositoryFileRequestSerializer(serializers.Serializer):
    repository_id = serializers.UUIDField(required=True)
    file_path = serializers.CharField(required=True, allow_blank=False, max_length=1000)
    branch = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    start_line = serializers.IntegerField(required=False, min_value=1, allow_null=True, default=None)
    end_line = serializers.IntegerField(required=False, min_value=1, allow_null=True, default=None)
    max_lines = serializers.IntegerField(required=False, default=500, min_value=1, max_value=2000)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        start_line = attrs.get("start_line")
        end_line = attrs.get("end_line")
        if (
            start_line is not None
            and end_line is not None
            and cast(int, start_line) > cast(int, end_line)
        ):
            raise serializers.ValidationError("start_line 不能大于 end_line")
        return attrs


class GrepRepositoryRequestSerializer(serializers.Serializer):
    # 目标范围：repository_id（单仓便捷参数）/ repository_ids（显式多仓）/
    # all_repositories（显式全量跨仓，受 max_repos 限制），三者至少给一种。
    repository_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    repository_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
        default=list,
        max_length=10,
    )
    all_repositories = serializers.BooleanField(required=False, default=False)
    max_repos = serializers.IntegerField(required=False, default=10, min_value=1, max_value=20)
    pattern = serializers.CharField(required=True, allow_blank=False, max_length=512)
    branch = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    regex = serializers.BooleanField(required=False, default=False)
    case_sensitive = serializers.BooleanField(required=False, default=True)
    paths = serializers.ListField(
        child=serializers.CharField(max_length=500),
        required=False,
        allow_empty=True,
        default=list,
        max_length=10,
    )
    include_globs = serializers.ListField(
        child=serializers.CharField(max_length=200),
        required=False,
        allow_empty=True,
        default=list,
        max_length=10,
    )
    exclude_globs = serializers.ListField(
        child=serializers.CharField(max_length=200),
        required=False,
        allow_empty=True,
        default=list,
        max_length=10,
    )
    context_lines = serializers.IntegerField(required=False, default=0, min_value=0, max_value=50)
    max_matches = serializers.IntegerField(required=False, default=100, min_value=1, max_value=500)
    output_mode = serializers.ChoiceField(
        required=False,
        default="content",
        choices=("content", "files_only", "count"),
    )
    max_tokens = serializers.IntegerField(
        required=False, default=8000, min_value=256, max_value=32000
    )

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        targets = [str(rid) for rid in cast(list[object], attrs.get("repository_ids") or [])]
        single = attrs.get("repository_id")
        if single is not None and str(single) not in targets:
            targets.insert(0, str(single))
        if not targets and not attrs.get("all_repositories"):
            raise serializers.ValidationError(
                "必须提供 repository_id / repository_ids，或显式设置 all_repositories=true"
            )
        if str(attrs.get("branch") or "").strip() and len(targets) != 1:
            raise serializers.ValidationError("branch 仅支持单仓检索时指定")
        attrs["target_repository_ids"] = targets
        return attrs


class FindRelatedChunksRequestSerializer(serializers.Serializer):
    repository_id = serializers.UUIDField(required=True)
    branch = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    chunk_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    file_path = serializers.CharField(required=False, allow_blank=True, default="")
    symbol_name = serializers.CharField(required=False, allow_blank=True, default="")
    relation_types = serializers.ListField(
        child=serializers.CharField(max_length=30),
        required=False,
        allow_empty=True,
        default=list,
    )
    hops = serializers.IntegerField(required=False, default=1, min_value=0, max_value=2)
    direction = serializers.ChoiceField(
        required=False,
        default="both",
        choices=("downstream", "upstream", "both"),
    )
    limit = serializers.IntegerField(required=False, default=20, min_value=1, max_value=50)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        provided = [
            bool(attrs.get("chunk_id")),
            bool(str(attrs.get("file_path") or "").strip()),
            bool(str(attrs.get("symbol_name") or "").strip()),
        ]
        if sum(provided) != 1:
            raise serializers.ValidationError(
                "必须且只能提供 chunk_id、file_path、symbol_name 之一"
            )
        return attrs


class ReverseLookupRequestSerializer(serializers.Serializer):
    repository_id = serializers.UUIDField(required=True)
    file_path = serializers.CharField(required=False, allow_blank=True, default="")
    line = serializers.IntegerField(required=False, allow_null=True, default=None, min_value=1)
    chunk_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    branch = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        has_file_line = bool(str(attrs.get("file_path") or "").strip()) and attrs.get("line") is not None
        has_chunk = bool(attrs.get("chunk_id"))
        if not has_file_line and not has_chunk:
            raise serializers.ValidationError("必须提供 (file_path 且 line) 或 chunk_id")
        return attrs


class AnalyzeRepositoryRequestSerializer(serializers.Serializer):
    repository_id = serializers.UUIDField(required=True)
    branch = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    focus = serializers.CharField(required=False, allow_blank=True, default="", max_length=1000)
    context_chunks = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        allow_empty=True,
        default=list,
        max_length=20,
    )
    max_files = serializers.IntegerField(required=False, default=80, min_value=1, max_value=200)


class CreateCodingPlanRequestSerializer(serializers.Serializer):
    repository_id = serializers.UUIDField(required=True)
    branch = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    requirement = serializers.CharField(required=True, allow_blank=False, max_length=8000)
    analysis_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    context_chunks = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        allow_empty=True,
        default=list,
        max_length=20,
    )
    max_steps = serializers.IntegerField(required=False, default=8, min_value=1, max_value=20)


class ImproveCodingPlanRequestSerializer(serializers.Serializer):
    plan_id = serializers.UUIDField(required=True)
    feedback = serializers.CharField(required=True, allow_blank=False, max_length=8000)
    context_chunks = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        allow_empty=True,
        default=list,
        max_length=20,
    )
    max_steps = serializers.IntegerField(required=False, default=10, min_value=1, max_value=30)


class ExecuteCodingPlanRequestSerializer(serializers.Serializer):
    plan_id = serializers.UUIDField(required=True)
    version_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    branch_name = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=255,
    )
    target_branch = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=255,
    )
    retry_of_execution_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    timeout_seconds = serializers.IntegerField(
        required=False,
        default=3600,
        min_value=60,
        max_value=21600,
    )


class GetCodingExecutionRequestSerializer(serializers.Serializer):
    execution_id = serializers.UUIDField(required=True)


class SummarizeBranchRequestSerializer(serializers.Serializer):
    execution_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    repository_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    source_branch = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    target_branch = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    max_files = serializers.IntegerField(required=False, default=50, min_value=1, max_value=200)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        if attrs.get("execution_id"):
            return attrs
        if attrs.get("repository_id") and attrs.get("source_branch") and attrs.get("target_branch"):
            return attrs
        raise serializers.ValidationError(
            "必须提供 execution_id，或同时提供 repository_id/source_branch/target_branch"
        )


class CreateMergeRequestRequestSerializer(serializers.Serializer):
    execution_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    repository_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    source_branch = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    target_branch = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    title = serializers.CharField(required=False, allow_blank=True, default="", max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default="", max_length=20000)
    reviewer_usernames = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        allow_empty=True,
        default=list,
        max_length=20,
    )
    remove_source_branch = serializers.BooleanField(required=False, default=True)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        if attrs.get("execution_id"):
            return attrs
        if attrs.get("repository_id") and attrs.get("source_branch") and attrs.get("target_branch"):
            return attrs
        raise serializers.ValidationError(
            "必须提供 execution_id，或同时提供 repository_id/source_branch/target_branch"
        )


class GetFeishuWorkItemContextRequestSerializer(serializers.Serializer):
    project_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    project_key = serializers.CharField(required=False, allow_blank=True, default="", max_length=128)
    work_item_type = serializers.CharField(required=False, allow_blank=False, default="story", max_length=80)
    work_item_id = serializers.IntegerField(required=True, min_value=1)
    fields = serializers.ListField(
        child=serializers.CharField(max_length=128),
        required=False,
        allow_empty=True,
        default=list,
        max_length=80,
    )
    include_comments = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        if attrs.get("project_id") or str(attrs.get("project_key") or "").strip():
            return attrs
        raise serializers.ValidationError("必须提供 project_id 或 project_key")


class CreateFeishuTechnicalPlanRequestSerializer(serializers.Serializer):
    context_id = serializers.UUIDField(required=True)
    repository_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
        default=list,
        max_length=10,
    )
    repo_hints = serializers.ListField(
        child=serializers.CharField(max_length=200),
        required=False,
        allow_empty=True,
        default=list,
        max_length=20,
    )
    context_chunks = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        allow_empty=True,
        default=list,
        max_length=30,
    )
    similar_cases = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        allow_empty=True,
        default=list,
        max_length=20,
    )
    title = serializers.CharField(required=False, allow_blank=True, default="", max_length=240)
    folder_token = serializers.CharField(required=False, allow_blank=True, default="", max_length=200)
    create_document = serializers.BooleanField(required=False, default=True)
    write_comment = serializers.BooleanField(required=False, default=True)


class CreateWorkItemRepoTasksRequestSerializer(serializers.Serializer):
    technical_plan_id = serializers.UUIDField(required=True)


class ExecuteWorkItemRepoTasksRequestSerializer(serializers.Serializer):
    technical_plan_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    task_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
        default=list,
        max_length=20,
    )
    create_missing = serializers.BooleanField(required=False, default=True)
    dispatch = serializers.BooleanField(required=False, default=True)
    create_merge_requests = serializers.BooleanField(required=False, default=True)
    write_back = serializers.BooleanField(required=False, default=True)
    timeout_seconds = serializers.IntegerField(
        required=False,
        default=3600,
        min_value=60,
        max_value=21600,
    )
    reviewer_usernames = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        allow_empty=True,
        default=list,
        max_length=20,
    )

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        if attrs.get("technical_plan_id") or attrs.get("task_ids"):
            return attrs
        raise serializers.ValidationError("必须提供 technical_plan_id 或 task_ids")


class CreateLearningCaseRequestSerializer(serializers.Serializer):
    technical_plan_id = serializers.UUIDField(required=True)
    outcome = serializers.CharField(required=False, allow_blank=True, default="unknown", max_length=80)
    root_cause = serializers.CharField(required=False, allow_blank=True, default="", max_length=5000)
    solution_notes = serializers.CharField(required=False, allow_blank=True, default="", max_length=10000)
    tests = serializers.ListField(
        child=serializers.CharField(max_length=500),
        required=False,
        allow_empty=True,
        default=list,
        max_length=50,
    )


class SearchDeliveryKnowledgeRequestSerializer(serializers.Serializer):
    query = serializers.CharField(required=True, max_length=4000)
    top_k = serializers.IntegerField(required=False, default=5, min_value=1, max_value=20)
    project_ids = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        allow_empty=True,
        default=list,
        max_length=50,
    )
    repository_ids = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        allow_empty=True,
        default=list,
        max_length=50,
    )
    entity_kinds = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        allow_empty=True,
        default=list,
        max_length=20,
    )
    as_of = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    include_superseded = serializers.BooleanField(required=False, default=False)


class GetEntityTimelineRequestSerializer(serializers.Serializer):
    entity_id = serializers.UUIDField(required=True)
    include_superseded = serializers.BooleanField(required=False, default=False)
    as_of = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)


class GetRelatedEntitiesRequestSerializer(serializers.Serializer):
    DIRECTION_CHOICES = ("both", "out", "in")

    entity_id = serializers.UUIDField(required=True)
    direction = serializers.ChoiceField(choices=DIRECTION_CHOICES, required=False, default="both")
    max_hops = serializers.IntegerField(required=False, default=2, min_value=1, max_value=3)
    as_of = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)


class SearchLearningCasesRequestSerializer(serializers.Serializer):
    query = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)
    work_item_type = serializers.CharField(required=False, allow_blank=True, default="", max_length=80)
    repo_hints = serializers.ListField(
        child=serializers.CharField(max_length=200),
        required=False,
        allow_empty=True,
        default=list,
        max_length=20,
    )
    file_hints = serializers.ListField(
        child=serializers.CharField(max_length=1000),
        required=False,
        allow_empty=True,
        default=list,
        max_length=50,
    )
    symbol_hints = serializers.ListField(
        child=serializers.CharField(max_length=200),
        required=False,
        allow_empty=True,
        default=list,
        max_length=50,
    )
    limit = serializers.IntegerField(required=False, default=5, min_value=1, max_value=20)


class LookupProjectByBranchRequestSerializer(serializers.Serializer):
    """分支名 → 项目反查请求（CURSOR-01 + BIND-02 显式多绑定）。"""

    branch_name = serializers.CharField(required=True, allow_blank=False, max_length=255)
    # 可选 repository_id（BIND-02）：Phase 86 IDE hook 通常知当前 repo，可用于跨仓同名
    # 分支收窄到具体仓的绑定；不传则跨仓返回候选（fail-soft 不变）。
    repository_id = serializers.UUIDField(required=False, allow_null=True, default=None)


class ReportProjectKnowledgeRequestSerializer(serializers.Serializer):
    """Cursor 沉淀上报写回请求（CURSOR-03，默认入 memory draft）。

    Phase 86 扩展（**可选**，向后兼容）：

    - ``writeback_mode``：``draft``（默认，CURSOR-03 不回退）/ ``active``（IDE stop hook
      用户授权 accepted deviation，MEMORY/RESEARCH 直写生效不落 draft）。
    - ``target``：``memory``（默认）/ ``research``（active 模式写 RESEARCH ProjectDoc 正文）。
    - ``distill``：是否在入库前经 best-effort LLM 精炼（call_source=ide_hook_distill）。
    """

    # project_id 可省略：未传时用 branch_name(+repository_id) 按当前分支反查唯一项目
    # （通用规则/hook 不写死项目，跨分支跨项目复用）。两者至少给一个。
    project_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    branch_name = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=255
    )
    repository_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    content = serializers.CharField(required=True, allow_blank=False, max_length=20000)
    source_conversation_id = serializers.UUIDField(
        required=False, allow_null=True, default=None
    )
    writeback_mode = serializers.ChoiceField(
        choices=["draft", "active"], required=False, default="draft"
    )
    target = serializers.ChoiceField(
        choices=["memory", "research"], required=False, default="memory"
    )
    distill = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs: dict) -> dict:
        if not attrs.get("project_id") and not str(attrs.get("branch_name") or "").strip():
            raise serializers.ValidationError("必须提供 project_id 或 branch_name")
        return attrs


class SearchProjectContextRequestSerializer(serializers.Serializer):
    """项目上下文语义召回请求（CTX-01 RAG 读半）。"""

    project_id = serializers.UUIDField(required=True)
    query = serializers.CharField(required=True, allow_blank=False, max_length=4000)
    top_k = serializers.IntegerField(required=False, default=5, min_value=1, max_value=20)
    entity_kinds = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        allow_empty=True,
        default=list,
        max_length=20,
    )


class GrepProjectRequestSerializer(serializers.Serializer):
    """项目上下文关键词 grep 请求（CTX-01 grep 读半）。"""

    project_id = serializers.UUIDField(required=True)
    query = serializers.CharField(required=True, allow_blank=False, max_length=1000)
    top_k = serializers.IntegerField(required=False, default=10, min_value=1, max_value=50)


class ReadProjectDocRequestSerializer(serializers.Serializer):
    """项目工作区单文档 file-read 请求（CTX-01 file-read 读半）。"""

    project_id = serializers.UUIDField(required=True)
    doc_type = serializers.CharField(required=True, allow_blank=False, max_length=64)


class ReportProjectStateRequestSerializer(serializers.Serializer):
    """IDE stop hook STATE 结构化 API 清单直写请求（HOOK-03）。

    ``apis`` 为结构化清单（每项 ``{method, path, params?, status?}``），经
    ``ProjectDocService.upsert_state_api`` 幂等写入 ``ProjectStateApi``（source=HOOK）。

    **逐条 fail-soft 设计**：``apis`` 仅做「列表非空 + 子项为 dict」的宽松校验——单项缺
    ``method``/``path`` 或 ``status`` 非法**不**整批 400 拒绝，而是在 view 内逐条校验/规范化
    （``method`` 大写、``path`` 去空白），非法项标失败、合法项照写（与 86 系列 fail-soft 一致）。
    """

    # project_id 可省略：未传时用 branch_name(+repository_id) 按当前分支反查唯一项目。
    project_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    branch_name = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=255
    )
    repository_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    apis = serializers.ListField(
        child=serializers.DictField(),
        required=True,
        allow_empty=False,
        max_length=200,
    )

    def validate(self, attrs: dict) -> dict:
        if not attrs.get("project_id") and not str(attrs.get("branch_name") or "").strip():
            raise serializers.ValidationError("必须提供 project_id 或 branch_name")
        return attrs


TOOL_SCHEMA_SNAPSHOT: dict[str, dict[str, object]] = {
    "route_repositories": {
        "request": ["query", "top_k"],
        "response": ["query", "ranked_repos", "total", "run_id"],
    },
    "search_rag_chunks": {
        "request": ["repository_id", "repository_ids", "all_repositories", "max_repos", "query", "branch", "top_k", "max_tokens"],
        "response": ["query", "repository_id", "repository_ids", "branch", "results", "related_edges", "total_tokens", "run_id"],
    },
    "get_repository": {
        "request": ["repository_id"],
        "response": ["repository", "run_id"],
    },
    "list_repository_files": {
        "request": ["repository_id", "branch", "path", "recursive", "page", "page_size"],
        "response": ["repository_id", "branch", "path", "items", "total", "page", "page_size", "run_id"],
    },
    "get_repository_file": {
        "request": ["repository_id", "file_path", "branch", "start_line", "end_line", "max_lines"],
        "response": ["repository_id", "branch", "file_path", "content", "truncated", "total_chunks", "returned_lines", "max_lines", "source", "commit_sha", "total_lines", "run_id"],
    },
    "grep_repository": {
        "request": ["repository_id", "repository_ids", "all_repositories", "max_repos", "pattern", "branch", "regex", "case_sensitive", "paths", "include_globs", "exclude_globs", "context_lines", "max_matches", "output_mode", "max_tokens"],
        "response": ["pattern", "output_mode", "repositories", "total_matches", "truncated", "run_id"],
    },
    "find_related_chunks": {
        "request": ["repository_id", "branch", "chunk_id", "file_path", "symbol_name", "relation_types", "hops", "direction", "limit"],
        "response": ["repository_id", "branch", "source", "related_chunks", "run_id"],
    },
    "reverse_lookup_requirements": {
        "request": ["repository_id", "file_path", "line", "chunk_id", "branch"],
        "response": ["chunks", "related_work_items", "related_documents", "paths", "run_id"],
    },
    "analyze_repository": {
        "request": ["repository_id", "branch", "focus", "context_chunks", "max_files"],
        "response": ["analysis_id", "repository_id", "branch", "analysis", "evidence", "run_id"],
    },
    "create_coding_plan": {
        "request": ["repository_id", "branch", "requirement", "analysis_id", "context_chunks", "max_steps"],
        "response": ["plan_id", "version_id", "version", "repository_id", "branch", "plan", "evidence", "run_id"],
    },
    "improve_coding_plan": {
        "request": ["plan_id", "feedback", "context_chunks", "max_steps"],
        "response": ["plan_id", "version_id", "version", "repository_id", "branch", "plan", "change_summary", "risk_delta", "evidence", "run_id"],
    },
    "execute_coding_plan": {
        "request": ["plan_id", "version_id", "branch_name", "target_branch", "retry_of_execution_id", "timeout_seconds"],
        "response": ["execution_id", "plan_id", "version_id", "repository_id", "status", "branch_name", "target_branch", "coding_session_id", "subagent_session_id", "commit_sha", "file_changes", "test_results", "push_result", "last_diff", "runner_logs", "recovery_state", "dispatch_payload", "error", "retry_of_execution_id", "retry_count", "run_id"],
    },
    "get_coding_execution": {
        "request": ["execution_id"],
        "response": ["execution_id", "plan_id", "version_id", "repository_id", "status", "branch_name", "target_branch", "coding_session_id", "subagent_session_id", "commit_sha", "file_changes", "test_results", "push_result", "last_diff", "runner_logs", "recovery_state", "dispatch_payload", "error", "retry_of_execution_id", "retry_count", "run_id"],
    },
    "summarize_branch": {
        "request": ["execution_id", "repository_id", "source_branch", "target_branch", "max_files"],
        "response": ["execution_id", "repository_id", "source_branch", "target_branch", "summary", "mr_draft", "run_id"],
    },
    "create_merge_request": {
        "request": ["execution_id", "repository_id", "source_branch", "target_branch", "title", "description", "reviewer_usernames", "remove_source_branch"],
        "response": ["execution_id", "repository_id", "source_branch", "target_branch", "mr", "execution_status", "run_id"],
    },
    "get_feishu_work_item_context": {
        "request": ["project_id", "project_key", "work_item_type", "work_item_id", "fields", "include_comments"],
        "response": ["context_id", "project_id", "work_item", "relations", "documents", "comments", "context", "status", "run_id"],
    },
    "create_feishu_technical_plan": {
        "request": ["context_id", "repository_ids", "repo_hints", "context_chunks", "similar_cases", "title", "folder_token", "create_document", "write_comment"],
        "response": ["technical_plan_id", "context_id", "project_id", "plan", "markdown", "repository_tasks", "evidence", "feishu_document", "comment", "status", "retry_state", "run_id"],
    },
    "create_work_item_repo_tasks": {
        "request": ["technical_plan_id"],
        "response": ["technical_plan_id", "tasks", "total", "run_id"],
    },
    "execute_work_item_repo_tasks": {
        "request": ["technical_plan_id", "task_ids", "create_missing", "dispatch", "create_merge_requests", "write_back", "timeout_seconds", "reviewer_usernames"],
        "response": ["technical_plan_id", "tasks", "summary", "document_update", "comment", "status", "run_id"],
    },
    "create_learning_case": {
        "request": ["technical_plan_id", "outcome", "root_cause", "solution_notes", "tests"],
        "response": ["learning_case_id", "case", "run_id"],
    },
    "search_learning_cases": {
        "request": ["query", "work_item_type", "repo_hints", "file_hints", "symbol_hints", "limit"],
        "response": ["query", "results", "total", "run_id"],
    },
    "search_delivery_knowledge": {
        "request": [
            "query",
            "top_k",
            "project_ids",
            "repository_ids",
            "entity_kinds",
            "as_of",
            "include_superseded",
        ],
        "response": ["query", "results", "total", "as_of", "run_id"],
    },
    "get_entity_timeline": {
        "request": ["entity_id", "include_superseded", "as_of"],
        "response": ["entity_id", "nodes", "total", "run_id"],
    },
    "get_related_entities": {
        "request": ["entity_id", "direction", "max_hops", "as_of"],
        "response": ["entity_id", "related", "total", "as_of", "run_id"],
    },
    "lookup_project_by_branch": {
        "request": ["branch_name", "repository_id"],
        "response": [
            "branch_name",
            "work_item_id",
            "repository_id",
            "matched",
            "project",
            "candidates",
            "context",
            "included_layers",
            "run_id",
        ],
    },
    "report_project_knowledge": {
        "request": ["project_id", "content", "source_conversation_id"],
        "response": ["accepted", "draft_id", "reason", "run_id"],
    },
    "search_project_context": {
        "request": ["project_id", "query", "top_k", "entity_kinds"],
        "response": ["project_id", "query", "results", "total", "run_id"],
    },
    "grep_project": {
        "request": ["project_id", "query", "top_k"],
        "response": ["project_id", "query", "results", "total", "run_id"],
    },
    "read_project_doc": {
        "request": ["project_id", "doc_type"],
        "response": ["project_id", "doc_type", "rendered_markdown", "blocks", "run_id"],
    },
}
