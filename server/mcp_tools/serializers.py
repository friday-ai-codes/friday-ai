"""MCP read tools 请求 schema。"""

from __future__ import annotations

import re
from typing import Any, cast

from rest_framework import serializers

# compare / base_ref 安全形态：与 ``services.repo_mirror._SAFE_REF_RE`` 同形字面量副本，
# 避免 serializers 早加载路径拖入 mirror 子系统。另允许完整 40 位 sha。
_SAFE_COMPARE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@+-]{0,254}$")
_FULL_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")

#: assumptions 三档的**字面量副本**（116-REVIEW MJ-02）。单一事实源是
#: ``services.process_runtime.blueprint_ambiguity_score.ASSUMPTIONS_TIERS``——⛔ 本模块不在
#: 模块级 import 它：那会把整个 ``services.process_runtime`` 包（含大量 ORM 依赖）拖进
#: MCP 请求解析这条早加载路径。副本与事实源的一致性由
#: ``tests/services/process_runtime/test_blueprint_assumptions_tiers.py`` 的守卫断言盯着
#: （与 ``_SCHEMA_SNAPSHOT`` 的「字面量副本 + 守卫」同款约定）。
_ASSUMPTIONS_TIER_CHOICES: tuple[str, ...] = ("strict", "balanced", "assume_more")


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
    max_tokens = serializers.IntegerField(
        required=False, default=8000, min_value=1, max_value=32000
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
    start_line = serializers.IntegerField(
        required=False, min_value=1, allow_null=True, default=None
    )
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


class ImpactAnalysisRequestSerializer(serializers.Serializer):
    repository_id = serializers.UUIDField(required=True)
    branch = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    symbol_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    symbol = serializers.CharField(required=False, allow_blank=True, default="")
    file_path = serializers.CharField(required=False, allow_blank=True, default="")
    symbol_type = serializers.CharField(required=False, allow_blank=True, default="")
    # T-122-遍历 DoS 第一道闸：生产解析边入度 max 2,803，d1 就能到近 3,000 条
    max_depth = serializers.IntegerField(default=3, min_value=1, max_value=3)
    min_confidence = serializers.FloatField(default=1.0, min_value=0.0, max_value=1.0)
    include_low_confidence = serializers.BooleanField(default=False)
    # T-122-遍历 DoS：单次响应条数硬上限，与内核 DEFAULT_RESULT_LIMIT 对齐
    limit = serializers.IntegerField(default=200, min_value=1, max_value=200)
    # D-11：跨仓不递归，上界 1
    max_cross_repo_hops = serializers.IntegerField(default=1, min_value=0, max_value=1)
    exclude_test_files = serializers.BooleanField(default=False)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        has_id = bool(attrs.get("symbol_id"))
        has_name = bool(str(attrs.get("symbol") or "").strip())
        if has_id == has_name:
            raise serializers.ValidationError("必须且只能提供 symbol_id 或 symbol 之一")
        return attrs


class DetectChangesRequestSerializer(serializers.Serializer):
    """``detect_changes`` 请求契约（Phase 123 DIFF-01/02 / D-02）。

    ⛔ 不含 ``branch`` 图 overlay 字段——交叠坐标锁定索引水位（D-01）；
    ``compare`` 为 head，``base_ref`` 仅声明透出，不改 diff 左端。
    """

    repository_id = serializers.UUIDField(required=True)
    compare = serializers.CharField(required=True, allow_blank=False, max_length=255)
    base_ref = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, default=None
    )
    # T-123-DOS：上下界与 impact_analysis 同表
    max_depth = serializers.IntegerField(default=3, min_value=1, max_value=3)
    min_confidence = serializers.FloatField(default=1.0, min_value=0.0, max_value=1.0)
    include_low_confidence = serializers.BooleanField(default=False)
    limit = serializers.IntegerField(default=200, min_value=1, max_value=200)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        compare = str(attrs.get("compare") or "").strip()
        if not compare:
            raise serializers.ValidationError({"compare": "compare 不能为空"})
        if ".." in compare or any(ord(c) < 32 for c in compare):
            raise serializers.ValidationError({"compare": "compare 含非法字符"})
        if not (_SAFE_COMPARE_RE.match(compare) or _FULL_SHA_RE.match(compare)):
            raise serializers.ValidationError({"compare": "compare 格式非法"})
        attrs["compare"] = compare

        raw_base = attrs.get("base_ref")
        if raw_base is None or str(raw_base).strip() == "":
            attrs["base_ref"] = None
        else:
            base_ref = str(raw_base).strip()
            if ".." in base_ref or any(ord(c) < 32 for c in base_ref):
                raise serializers.ValidationError({"base_ref": "base_ref 含非法字符"})
            if not _SAFE_COMPARE_RE.match(base_ref):
                raise serializers.ValidationError({"base_ref": "base_ref 格式非法"})
            attrs["base_ref"] = base_ref
        return attrs


class ListProcessesRequestSerializer(serializers.Serializer):
    """``list_processes`` 请求契约（Phase 126 EXEC-02 / D-06）。"""

    repository_id = serializers.UUIDField(required=True)
    branch = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    community_class = serializers.ChoiceField(
        choices=["intra_community", "cross_community"],
        required=False,
        allow_null=True,
        default=None,
    )
    symbol_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    limit = serializers.IntegerField(default=50, min_value=1, max_value=200)


class GetProcessRequestSerializer(serializers.Serializer):
    """``get_process`` 请求契约（Phase 126 EXEC-02 / D-06）。"""

    repository_id = serializers.UUIDField(required=True)
    branch = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    process_key = serializers.CharField(required=True, allow_blank=False, max_length=640)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        key = str(attrs.get("process_key") or "").strip()
        if not key:
            raise serializers.ValidationError({"process_key": "process_key 不能为空"})
        attrs["process_key"] = key
        return attrs


class TraceCallPathRequestSerializer(serializers.Serializer):
    repository_id = serializers.UUIDField(required=True)
    branch = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    source_symbol_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    source = serializers.CharField(required=False, allow_blank=True, default="")
    source_file_path = serializers.CharField(required=False, allow_blank=True, default="")
    target_symbol_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    target = serializers.CharField(required=False, allow_blank=True, default="")
    target_file_path = serializers.CharField(required=False, allow_blank=True, default="")
    min_confidence = serializers.FloatField(default=1.0, min_value=0.0, max_value=1.0)
    include_low_confidence = serializers.BooleanField(default=False)
    # T-122-遍历 DoS：等长备选路径条数上限
    alt_path_cap = serializers.IntegerField(default=10, min_value=1, max_value=50)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        has_source_id = bool(attrs.get("source_symbol_id"))
        has_source = bool(str(attrs.get("source") or "").strip())
        if has_source_id == has_source:
            raise serializers.ValidationError(
                "必须且只能提供 source_symbol_id 或 source 之一"
            )
        has_target_id = bool(attrs.get("target_symbol_id"))
        has_target = bool(str(attrs.get("target") or "").strip())
        if has_target_id == has_target:
            raise serializers.ValidationError(
                "必须且只能提供 target_symbol_id 或 target 之一"
            )
        return attrs


class ReverseLookupRequestSerializer(serializers.Serializer):
    repository_id = serializers.UUIDField(required=True)
    file_path = serializers.CharField(required=False, allow_blank=True, default="")
    line = serializers.IntegerField(required=False, allow_null=True, default=None, min_value=1)
    chunk_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    branch = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        has_file_line = (
            bool(str(attrs.get("file_path") or "").strip()) and attrs.get("line") is not None
        )
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
    """create_coding_plan 请求契约（UNIFY-01 对照）。

    同步语义与 improve_coding_plan 完全同型：HTTP 请求内同步 await 统一编排至
    pause/terminal——``DONE→completed``、``FAILED→failed``、research/clarify 在途
    立即短路返回 ``partial`` + ``session_id``（不阻塞等容器，调用方不挂起不超时）。
    详见 :class:`ImproveCodingPlanRequestSerializer` 的契约描述。

    与 improve 的差异（IN-01，review 104）：``context_chunks`` 当前 accepted-but-ignored
    （收敛后编排自带召回，不折入 requirement）；improve 侧则折入 feedback 块被消费。
    """

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
    """improve_coding_plan 请求契约（UNIFY-01 定版，与 create_coding_plan 同型）。

    改版语义：携带 feedback 的**统一编排重跑**产新 ``McpCodingPlanVersion``
    （``version = current_version + 1``，递增语义不变），非旧确定性"往 steps 追加一行"。

    同步语义：HTTP 请求内同步 await 编排至 pause/terminal——
    - ``DONE`` → 响应 ``status="completed"``；
    - ``FAILED`` → ``status="failed"``：**不产新版本、不推进 current_version**（WR-01，
      review 104——瞬时编排失败不得把默认执行的"当前方案"静默替换成空方案）；响应键集
      不变，``version`` / ``version_id`` 回填改版前最新版本；
    - research/clarify 在途（容器执行中）→ **立即短路**返回 ``status="partial"`` +
      ``session_id``（不阻塞等容器，Cursor 侧调用不挂起不超时）；partial 后可经
      ``get_coding_execution`` / 后续调用凭 ``session_id`` 跟进。

    request 键集不变（accepted-but-advisory）：``context_chunks`` 若提供则经
    ``normalize_context_chunks`` 截断（≤20 条、content 预览 500 字符）后折入 feedback 块
    作为补充上下文（WR-03，review 104——系统边界限体积）；``max_steps`` 收敛到编排后
    不再截断步骤，仅保留兼容。
    """

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
    source_branch = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=255
    )
    target_branch = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=255
    )
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
    source_branch = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=255
    )
    target_branch = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=255
    )
    title = serializers.CharField(required=False, allow_blank=True, default="", max_length=200)
    description = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=20000
    )
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
    project_key = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=128
    )
    work_item_type = serializers.CharField(
        required=False, allow_blank=False, default="story", max_length=80
    )
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
    folder_token = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=200
    )
    create_document = serializers.BooleanField(required=False, default=True)
    write_comment = serializers.BooleanField(required=False, default=True)
    #: assumptions 档位（116-REVIEW MJ-02）——蓝图规格门的「交互密度」旋钮：
    #: ``strict`` 更爱问、``balanced`` = 默认档（与不传逐字等价）、``assume_more`` 更少问。
    #: ⭐ 只调阈值与轮数，⛔ **绝不跳过规格门**（问得更少 ≠ 不问）。
    #: ⚠️ 仅在 ``mcp`` 入口开关切到 ``technical_blueprint`` 时生效；缺省空串 ⇒ 走默认档。
    assumptions_tier = serializers.ChoiceField(
        choices=["", *_ASSUMPTIONS_TIER_CHOICES],
        required=False,
        allow_blank=True,
        default="",
    )


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
    outcome = serializers.CharField(
        required=False, allow_blank=True, default="unknown", max_length=80
    )
    root_cause = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=5000
    )
    solution_notes = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=10000
    )
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
    """学习案例检索请求（KNOW-02）。

    自 v0.17.0 起结果按统一向量检索排序（``DeliveryKnowledgeSearchService``，
    entity_kinds=["learning_case"]）；响应 ``score`` 为向量融合分（0-1 浮点），
    语义由旧 token 命中计数变更为向量分。``repo_hints`` / ``file_hints`` /
    ``symbol_hints`` / ``work_item_type`` 参与查询文本增强与结果层提权排序，
    不再是摆设参数。请求/响应键集与 v0.16 完全一致（TOOL_SCHEMA_SNAPSHOT 守门）。
    """

    query = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=2000,
        help_text=(
            "检索问题描述（建议必填）：结果按统一向量检索排序，score 为向量融合分"
            "（0-1 浮点，自 v0.17.0 起语义由 token 命中计数变更为向量分）；"
            "query 与全部 hints 拼装后为空时直接返回空结果（向量检索无「无查询返回最新」语义）。"
        ),
    )
    work_item_type = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=80
    )
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
    source_conversation_id = serializers.UUIDField(required=False, allow_null=True, default=None)
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


class CreateFeatureTechPlanRequestSerializer(serializers.Serializer):
    """feature list 技术方案发起请求（两段式第一段）。

    三种取数源，至少给一个（优先级 ``feature_list_text`` > ``project_id`` > ``branch_name``）：
    项目已录入的 feature list、分支反查项目（复用手动绑定的 ``ProjectBranch``）、或直接贴原文。

    ``repository_ids`` 只是**候选范围收窄**，不代表最终选仓——最终关联仓库一律由用户在
    ``confirm_feature_tech_plan`` 确认（产品硬约束：路由再确定也要问一次）。
    """

    project_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    branch_name = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=255
    )
    repository_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    feature_list_text = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=200000
    )
    repository_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
        default=list,
        max_length=20,
    )

    def validate(self, attrs: dict) -> dict:
        if (
            not attrs.get("project_id")
            and not str(attrs.get("branch_name") or "").strip()
            and not str(attrs.get("feature_list_text") or "").strip()
        ):
            raise serializers.ValidationError(
                "必须提供 project_id、branch_name 或 feature_list_text 之一"
            )
        return attrs


class ConfirmFeatureTechPlanRequestSerializer(serializers.Serializer):
    """feature list 技术方案确认请求（两段式第二段）。

    ``answers`` 形如 ``[{question_id, selected, freeform_text}]``。允许为空表示「全部按推荐
    执行」——未覆盖到的题服务端按 ``recommended`` 兜底作答，避免漏答让会话永久挂起。
    """

    session_id = serializers.UUIDField(required=True)
    answers = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        allow_empty=True,
        default=list,
        max_length=20,
    )


class GetFeatureTechPlanRequestSerializer(serializers.Serializer):
    """feature list 技术方案状态查询请求（调研在途时轮询本工具取最终方案）。"""

    session_id = serializers.UUIDField(required=True)


# Blueprint Context Bus 容器读写入参（BUS-01，Phase 113-02）。
# ⭐ 两个 serializer **都不提供任何会话入参字段**：目标会话一律由 view 解析（任务 token 自带
# 的 ``session_id`` 为权威源，``X-Friday-Session-Id`` 仅冗余校验，见
# ``_aresolve_blueprint_session`` 四道校验），请求体无跨会话入参面 —— 这是「第三道校验
# （目标条目同会话）」的结构性成立方式。``repository_id`` 虽在入参里，但 view 会用服务端
# 权威值**覆写**它（CR-01），保留只为向后兼容老镜像的请求体。
_BLUEPRINT_CONTEXT_KINDS = [
    "finding",
    "api_surface",
    "contract",
    "decision",
    "dependency_claim",
    "question",
]

# content 嵌套深度上界（MN-02，与 ``BlueprintContextService._MAX_CONTENT_DEPTH`` 同值）。
_MAX_CONTENT_DEPTH = 32


def _json_depth(value: Any, *, depth: int = 0) -> int:
    """半可信 JSON 的嵌套深度（**自身有界**：到达上界即停，不会因探测深度而递归爆栈）。"""
    if depth > _MAX_CONTENT_DEPTH:
        return depth
    if isinstance(value, dict):
        children = list(value.values())
    elif isinstance(value, list):
        children = list(value)
    else:
        return depth
    if not children:
        return depth
    return max(_json_depth(child, depth=depth + 1) for child in children)


class ReadBlueprintContextRequestSerializer(serializers.Serializer):
    """蓝图共享上下文总线读取请求（全部可选：无参 = 拉本会话全部 active 条目）。

    ``since_seq`` 支撑容器侧增量轮询（带上次返回的 ``max_seq`` 即可只取新增）；
    ``limit`` 上界 200 与 ``BlueprintContextService._MAX_READ_LIMIT`` 双重夹紧
    （T-113-11：防无界 read 拉爆容器上下文）。
    """

    key_prefix = serializers.CharField(required=False, allow_blank=True, default="", max_length=200)
    kind = serializers.ChoiceField(
        choices=_BLUEPRINT_CONTEXT_KINDS,
        required=False,
        allow_blank=True,
        default="",
    )
    repository_id = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=64
    )
    since_seq = serializers.IntegerField(required=False, min_value=0, default=0)
    limit = serializers.IntegerField(required=False, min_value=1, max_value=200, default=50)


class ReportBlueprintContextRequestSerializer(serializers.Serializer):
    """蓝图共享上下文总线写入请求（写入即对同会话并行容器可见）。

    ``content`` 必须是 JSON 对象（不接受 list/标量）——入库前经
    ``BlueprintContextService._redact_json`` 递归脱敏，容器传入的凭证不会落库。
    """

    key = serializers.CharField(required=True, allow_blank=False, max_length=200)
    kind = serializers.ChoiceField(choices=_BLUEPRINT_CONTEXT_KINDS, required=True)
    repository_id = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=64
    )
    content = serializers.JSONField(required=True)

    def validate(self, attrs: dict) -> dict:
        content = attrs.get("content")
        if not isinstance(content, dict):
            raise serializers.ValidationError("content 必须是 JSON 对象")
        # MN-02：深度预检放在 serializer 侧，让「过深」以 **400 invalid_params** 被拒，而不是
        # 一路走到 service 的无界递归抛 `RecursionError`、再被 view 兜底折叠成不可归因的
        # 200 + `internal_error`（写入方拿不到原因）。service 侧另有同名深度闸兜底。
        if _json_depth(content) > _MAX_CONTENT_DEPTH:
            raise serializers.ValidationError(f"content 嵌套层数超过 {_MAX_CONTENT_DEPTH} 层上限")
        return attrs


class GetTechnicalBlueprintRequestSerializer(serializers.Serializer):
    """技术蓝图续取请求（Phase 116-06，GATE-01）。

    ⭐ **寻址键是 ``artifact_id`` 而不是 ``session_id``**：既有 20 个蓝图端点全部以
    ``artifact_id`` 为一级键并按它挂项目范围闸；且**同一 artifact 上可并存**
    ``technical_plan`` 与 ``technical_blueprint`` 两条会话——按会话寻址会踩回 112 review
    的那条 CRITICAL（「按 artifact 取最近一条会话」跨 process 污染）。
    """

    artifact_id = serializers.CharField(required=True, allow_blank=False, max_length=64)


class AnswerBlueprintClarificationRequestSerializer(serializers.Serializer):
    """蓝图澄清作答请求（Phase 116-06，GATE-01）。

    ``artifact_id`` 可选，仅作二次校验（传了就必须与线程实际归属一致）——范围闸本身
    一律由 view 从线程反查出的 artifact 推导，⛔ 不信调用方自报的归属。
    """

    thread_id = serializers.CharField(required=True, allow_blank=False, max_length=64)
    body = serializers.CharField(required=True, allow_blank=True, trim_whitespace=False)
    artifact_id = serializers.CharField(required=False, allow_blank=True, default="", max_length=64)


# ── 蓝图环节单跑（stage sandbox）工具（.planning/quick/20260806-blueprint-stage-runner）──


class RouteBlueprintReposRequestSerializer(serializers.Serializer):
    """三分量蓝图路由单跑请求（区别于粗版 ``route_repositories``：含章程/历史融合与 pin）。

    ``requirement_text`` 与 ``requirement_spec`` 至少给一个；``ignore_pin=True`` 跳过项目
    手动绑定的固定路由短路（对比「人工绑定 vs 自动路由」的能力测试口）。
    """

    requirement_text = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=8000
    )
    requirement_spec = serializers.JSONField(required=False, allow_null=True, default=None)
    project_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    include_repository_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
        default=list,
        max_length=50,
    )
    exclude_repository_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
        default=list,
        max_length=50,
    )
    ignore_pin = serializers.BooleanField(required=False, default=False)
    top_k = serializers.IntegerField(required=False, default=5, min_value=1, max_value=10)

    def validate(self, attrs: dict) -> dict:
        spec = attrs.get("requirement_spec")
        if spec is not None and not isinstance(spec, dict):
            raise serializers.ValidationError("requirement_spec 须为 JSON 对象")
        if not str(attrs.get("requirement_text") or "").strip() and not spec:
            raise serializers.ValidationError("requirement_text 与 requirement_spec 至少提供一个")
        return attrs


class GenerateRequirementSpecRequestSerializer(serializers.Serializer):
    """需求规格单跑请求：拆功能点 + intent 补齐 + 四维歧义打分（零落库）。"""

    requirement_text = serializers.CharField(
        required=True, allow_blank=False, max_length=20000
    )
    # 直采功能点（每项 {"title", "intent"?, "module"?, "layer"?}）：非空即跳过 LLM 拆分。
    feature_points = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        allow_empty=True,
        default=list,
        max_length=200,
    )
    prior_context = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=8000
    )
    assumptions_tier = serializers.ChoiceField(
        choices=["strict", "balanced", "assume_more"],
        required=False,
        allow_blank=True,
        default="",
    )
    classify_intents = serializers.BooleanField(required=False, default=True)


class StartRepoResearchRequestSerializer(serializers.Serializer):
    """沙箱调研发起请求：对显式仓库集跑蓝图调研链（direct 容器深调研 / indirect 轻量合成）。"""

    requirement_text = serializers.CharField(
        required=True, allow_blank=False, max_length=20000
    )
    requirement_spec = serializers.JSONField(required=False, allow_null=True, default=None)
    project_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    # 每项 {"repository_id", "role"?: direct|indirect, "confidence"?: high|medium|low}
    repositories = serializers.ListField(
        child=serializers.DictField(),
        required=True,
        allow_empty=False,
        max_length=10,
    )

    def validate_requirement_spec(self, value: object) -> object:
        if value is not None and not isinstance(value, dict):
            raise serializers.ValidationError("requirement_spec 须为 JSON 对象")
        return value


class GetRepoResearchRequestSerializer(serializers.Serializer):
    """沙箱调研结果轮询请求（仅限会话创建者，非本人中性 404）。"""

    session_id = serializers.UUIDField(required=True)


class ApplyRepoAssociationRequestSerializer(serializers.Serializer):
    """采纳写回请求：把选定仓库集 bind/unbind 到项目（``ProjectBranch(source=manual)``）。

    这是 stage 单跑家族**唯一**的写回路径——路由/调研结果永远只是提案，写回由用户显式
    调用本工具决定（`ProjectBranchService` 成员 fail-closed + 审计）。
    """

    project_id = serializers.UUIDField(required=True)
    action = serializers.ChoiceField(choices=["bind", "unbind"], required=False, default="bind")
    # 每项 {"repository_id", "branch_name"?}；branch_name 缺省取仓库默认分支。
    bindings = serializers.ListField(
        child=serializers.DictField(),
        required=True,
        allow_empty=False,
        max_length=20,
    )


# 三个 feature 方案工具共用同一响应形状（FeatureSolutionState.as_dict + run_id）。
_FEATURE_SOLUTION_RESPONSE_KEYS = [
    "session_id",
    "status",
    "project_id",
    "source",
    "feature_count",
    "truncated",
    "classification",
    "routing",
    "questions",
    "clarification_id",
    "plan",
    "markdown",
    "artifact_version_id",
    "error",
    "run_id",
]


TOOL_SCHEMA_SNAPSHOT: dict[str, dict[str, object]] = {
    "route_repositories": {
        "request": ["query", "top_k"],
        "response": ["query", "ranked_repos", "total", "run_id"],
    },
    "search_rag_chunks": {
        "request": [
            "repository_id",
            "repository_ids",
            "all_repositories",
            "max_repos",
            "query",
            "branch",
            "top_k",
            "max_tokens",
        ],
        "response": [
            "query",
            "repository_id",
            "repository_ids",
            "branch",
            "results",
            "related_edges",
            "total_tokens",
            "run_id",
        ],
    },
    "get_repository": {
        "request": ["repository_id"],
        "response": ["repository", "run_id"],
    },
    "list_repository_files": {
        "request": ["repository_id", "branch", "path", "recursive", "page", "page_size"],
        "response": [
            "repository_id",
            "branch",
            "path",
            "items",
            "total",
            "page",
            "page_size",
            "run_id",
        ],
    },
    "get_repository_file": {
        "request": ["repository_id", "file_path", "branch", "start_line", "end_line", "max_lines"],
        "response": [
            "repository_id",
            "branch",
            "file_path",
            "content",
            "truncated",
            "total_chunks",
            "returned_lines",
            "max_lines",
            "source",
            "commit_sha",
            "total_lines",
            "run_id",
        ],
    },
    "grep_repository": {
        "request": [
            "repository_id",
            "repository_ids",
            "all_repositories",
            "max_repos",
            "pattern",
            "branch",
            "regex",
            "case_sensitive",
            "paths",
            "include_globs",
            "exclude_globs",
            "context_lines",
            "max_matches",
            "output_mode",
            "max_tokens",
        ],
        "response": [
            "pattern",
            "output_mode",
            "repositories",
            "total_matches",
            "truncated",
            "run_id",
        ],
    },
    "find_related_chunks": {
        "request": [
            "repository_id",
            "branch",
            "chunk_id",
            "file_path",
            "symbol_name",
            "relation_types",
            "hops",
            "direction",
            "limit",
        ],
        "response": ["repository_id", "branch", "source", "related_chunks", "run_id"],
    },
    "reverse_lookup_requirements": {
        "request": ["repository_id", "file_path", "line", "chunk_id", "branch"],
        "response": ["chunks", "related_work_items", "related_documents", "paths", "run_id"],
    },
    "impact_analysis": {
        "request": [
            "repository_id",
            "branch",
            "symbol_id",
            "symbol",
            "file_path",
            "symbol_type",
            "max_depth",
            "min_confidence",
            "include_low_confidence",
            "limit",
            "max_cross_repo_hops",
            "exclude_test_files",
        ],
        "response": [
            "ok",
            "tool",
            "repository_id",
            "branch",
            "seed",
            "query",
            "groups",
            "risk_level",
            "risk_inputs",
            "summary",
            "cross_repo",
            "affected_processes",
            "staleness",
            "graph",
            "error_code",
            "error",
            "run_id",
        ],
    },
    "detect_changes": {
        "request": [
            "repository_id",
            "compare",
            "base_ref",
            "max_depth",
            "min_confidence",
            "include_low_confidence",
            "limit",
        ],
        "response": [
            "ok",
            "tool",
            "repository_id",
            "diff_base_sha",
            "diff_head_sha",
            "base_ref",
            "files",
            "impacts",
            "summary",
            "affected_processes",
            "staleness",
            "graph",
            "error_code",
            "error",
            "run_id",
        ],
    },
    "trace_call_path": {
        "request": [
            "repository_id",
            "branch",
            "source_symbol_id",
            "source",
            "source_file_path",
            "target_symbol_id",
            "target",
            "target_file_path",
            "min_confidence",
            "include_low_confidence",
            "alt_path_cap",
        ],
        "response": [
            "ok",
            "tool",
            "repository_id",
            "branch",
            "query",
            "found",
            "reason",
            "source",
            "target",
            "path",
            "hops",
            "path_confidence",
            "equal_length_path_count",
            "equal_length_path_count_capped",
            "alternatives_note",
            "staleness",
            "graph",
            "error_code",
            "error",
            "run_id",
        ],
    },
    "analyze_repository": {
        "request": ["repository_id", "branch", "focus", "context_chunks", "max_files"],
        "response": ["analysis_id", "repository_id", "branch", "analysis", "evidence", "run_id"],
    },
    "create_coding_plan": {
        "request": [
            "repository_id",
            "branch",
            "requirement",
            "analysis_id",
            "context_chunks",
            "max_steps",
        ],
        "response": [
            "plan_id",
            "version_id",
            "version",
            "repository_id",
            "branch",
            "plan",
            "evidence",
            "run_id",
            "session_id",
            "status",
        ],
    },
    "improve_coding_plan": {
        "request": ["plan_id", "feedback", "context_chunks", "max_steps"],
        "response": [
            "plan_id",
            "version_id",
            "version",
            "repository_id",
            "branch",
            "plan",
            "change_summary",
            "risk_delta",
            "evidence",
            "run_id",
            "session_id",
            "status",
        ],
    },
    "execute_coding_plan": {
        "request": [
            "plan_id",
            "version_id",
            "branch_name",
            "target_branch",
            "retry_of_execution_id",
            "timeout_seconds",
        ],
        "response": [
            "execution_id",
            "plan_id",
            "version_id",
            "repository_id",
            "status",
            "branch_name",
            "target_branch",
            "coding_session_id",
            "subagent_session_id",
            "commit_sha",
            "file_changes",
            "test_results",
            "push_result",
            "last_diff",
            "runner_logs",
            "recovery_state",
            "dispatch_payload",
            "error",
            "retry_of_execution_id",
            "retry_count",
            "run_id",
        ],
    },
    "get_coding_execution": {
        "request": ["execution_id"],
        "response": [
            "execution_id",
            "plan_id",
            "version_id",
            "repository_id",
            "status",
            "branch_name",
            "target_branch",
            "coding_session_id",
            "subagent_session_id",
            "commit_sha",
            "file_changes",
            "test_results",
            "push_result",
            "last_diff",
            "runner_logs",
            "recovery_state",
            "dispatch_payload",
            "error",
            "retry_of_execution_id",
            "retry_count",
            "run_id",
        ],
    },
    "summarize_branch": {
        "request": ["execution_id", "repository_id", "source_branch", "target_branch", "max_files"],
        "response": [
            "execution_id",
            "repository_id",
            "source_branch",
            "target_branch",
            "summary",
            "mr_draft",
            "run_id",
        ],
    },
    "create_merge_request": {
        "request": [
            "execution_id",
            "repository_id",
            "source_branch",
            "target_branch",
            "title",
            "description",
            "reviewer_usernames",
            "remove_source_branch",
        ],
        "response": [
            "execution_id",
            "repository_id",
            "source_branch",
            "target_branch",
            "mr",
            "execution_status",
            "run_id",
        ],
    },
    "get_feishu_work_item_context": {
        "request": [
            "project_id",
            "project_key",
            "work_item_type",
            "work_item_id",
            "fields",
            "include_comments",
        ],
        "response": [
            "context_id",
            "project_id",
            "work_item",
            "relations",
            "documents",
            "comments",
            "context",
            "status",
            "run_id",
        ],
    },
    "create_feishu_technical_plan": {
        "request": [
            "context_id",
            "repository_ids",
            "repo_hints",
            "context_chunks",
            "similar_cases",
            "title",
            "folder_token",
            "create_document",
            "write_comment",
            # 116-REVIEW MJ-02：assumptions 档位（蓝图规格门的交互密度旋钮，缺省空串 = 默认档）。
            "assumptions_tier",
        ],
        "response": [
            "technical_plan_id",
            "context_id",
            "project_id",
            "plan",
            "markdown",
            "repository_tasks",
            "evidence",
            "feishu_document",
            "comment",
            "status",
            "retry_state",
            "run_id",
            # 116-REVIEW MJ-03：失败原因回传（成功时为空串）。回退前 `error` / `error_stage`
            # 只落 `McpWorkItemTechnicalPlan` 行，agent 读的响应体里没有任何解释。
            "error",
            "error_stage",
            # Phase 116-06（GATE-01）：⭐ **仅在 mcp 入口开关切到 `technical_blueprint`
            # 时出现**的三个追加键（开关关闭时响应与改动前逐字相同）。它们必须同步进
            # 本快照——`report_blueprint_context` 那条 `redispatched` 的教训逐字适用：
            # 漏在 snapshot 里会让容器侧/外部客户端按已发布契约以为它不存在。
            # ⚠️ 状态键取名 `blueprint_current_status` 而非 `blueprint_status`：后者作为
            # 响应字典键会命中 INV-6 的 `_RE_FIELD_DICT_KEY`（字段级旁路守卫）。
            "blueprint_artifact_id",
            "blueprint_current_status",
            "pending_clarifications",
        ],
    },
    "create_work_item_repo_tasks": {
        "request": ["technical_plan_id"],
        "response": ["technical_plan_id", "tasks", "total", "run_id"],
    },
    "execute_work_item_repo_tasks": {
        "request": [
            "technical_plan_id",
            "task_ids",
            "create_missing",
            "dispatch",
            "create_merge_requests",
            "write_back",
            "timeout_seconds",
            "reviewer_usernames",
        ],
        "response": [
            "technical_plan_id",
            "tasks",
            "summary",
            "document_update",
            "comment",
            "status",
            "run_id",
        ],
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
    "report_project_state": {
        "request": ["project_id", "branch_name", "repository_id", "apis"],
        "response": ["applied", "reason", "results", "total_applied", "run_id"],
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
    "create_feature_tech_plan": {
        "request": [
            "project_id",
            "branch_name",
            "repository_id",
            "feature_list_text",
            "repository_ids",
        ],
        "response": _FEATURE_SOLUTION_RESPONSE_KEYS,
    },
    "confirm_feature_tech_plan": {
        "request": ["session_id", "answers"],
        "response": _FEATURE_SOLUTION_RESPONSE_KEYS,
    },
    "get_feature_tech_plan": {
        "request": ["session_id"],
        "response": _FEATURE_SOLUTION_RESPONSE_KEYS,
    },
    "read_blueprint_context": {
        "request": ["key_prefix", "kind", "repository_id", "since_seq", "limit"],
        "response": ["entries", "count", "max_seq", "error", "run_id"],
    },
    "report_blueprint_context": {
        # MN-08：`redispatched` 是 113-04 追加的真实响应键，漏在 snapshot 里会让容器侧 /
        # 外部客户端按已发布契约以为它不存在（snapshot 是对外契约，不是内部注释）。
        "response": [
            "applied",
            "reason",
            "entry_id",
            "seq",
            "satisfied_waiters",
            "redispatched",
            "run_id",
        ],
        "request": ["key", "kind", "repository_id", "content"],
    },
    # 蓝图异步澄清协议（GATE-01，Phase 116-06）：MCP 入口不再 skip_clarification ⇒
    # 立即返回 pending → 经 `answer_blueprint_clarification` 作答 → 用
    # `get_technical_blueprint` 续取终稿。⛔ **不建第三个 list 工具**：pending 清单内联
    # 在 `get_technical_blueprint` 的 `pending_clarifications` 里。
    "get_technical_blueprint": {
        "request": ["artifact_id"],
        "response": [
            "artifact_id",
            "session_id",
            "current_status",
            "title",
            "version_no",
            "sections",
            "markdown",
            "pending_clarifications",
            "run_id",
        ],
    },
    "answer_blueprint_clarification": {
        "request": ["thread_id", "body", "artifact_id"],
        "response": [
            "status",
            "thread_id",
            "artifact_id",
            "current_status",
            "reflow",
            "run_id",
        ],
    },
    # ── 蓝图环节单跑（stage sandbox）家族：route / spec / research 单跑 + 显式采纳写回。
    # 前四个是 dry-run / 只读提案面；`apply_repo_association` 是家族里唯一写回路径。
    "route_blueprint_repos": {
        "request": [
            "requirement_text",
            "requirement_spec",
            "project_id",
            "include_repository_ids",
            "exclude_repository_ids",
            "ignore_pin",
            "top_k",
        ],
        # 与 stage_state["routing"] 契约（112-03 顶层 8 键）逐键同形 + run_id。
        "response": [
            "router_version",
            "auto_selected",
            "intent",
            "weights_used",
            "charter_supplement_count",
            "unjustified_boundary_hit_count",
            "candidates",
            "citations",
            "run_id",
        ],
    },
    "generate_requirement_spec": {
        "request": [
            "requirement_text",
            "feature_points",
            "prior_context",
            "assumptions_tier",
            "classify_intents",
        ],
        "response": ["requirement_spec", "ambiguity", "source", "run_id"],
    },
    "start_repo_research": {
        "request": ["requirement_text", "requirement_spec", "project_id", "repositories"],
        "response": ["session_id", "dispatched", "synthesized", "degraded", "tasks", "run_id"],
    },
    "get_repo_research": {
        "request": ["session_id"],
        "response": ["session_id", "all_terminal", "tasks", "run_id"],
    },
    "apply_repo_association": {
        "request": ["project_id", "action", "bindings"],
        "response": ["project_id", "action", "results", "run_id"],
    },
    "list_processes": {
        "request": [
            "repository_id",
            "branch",
            "community_class",
            "symbol_id",
            "limit",
        ],
        "response": [
            "ok",
            "tool",
            "repository_id",
            "branch",
            "processes",
            "summary",
            "as_of",
            "staleness",
            "degradation",
            "error_code",
            "error",
            "run_id",
        ],
    },
    "get_process": {
        "request": ["repository_id", "branch", "process_key"],
        "response": [
            "ok",
            "tool",
            "repository_id",
            "branch",
            "process",
            "process_key",
            "as_of",
            "staleness",
            "degradation",
            "error_code",
            "error",
            "run_id",
        ],
    },
}
