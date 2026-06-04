"""MCP read tools 请求 schema。"""
from __future__ import annotations
from typing import cast
from rest_framework import serializers
class RouteRepositoriesRequestSerializer(serializers.Serializer):
 query = serializers.CharField(required=True, allow_blank=False, max_length=1000)
 top_k = serializers.IntegerField(required=False, default=3, min_value=1, max_value=10)
class SearchRagChunksRequestSerializer(serializers.Serializer):
 repository_id = serializers.UUIDField(required=True)
 query = serializers.CharField(required=True, allow_blank=False, max_length=1000)
 branch = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
 top_k = serializers.IntegerField(required=False, default=30, min_value=1, max_value=50)
 max_tokens = serializers.IntegerField(required=False, default=8000, min_value=1, max_value=32000)
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
 bool(str(attrs.get("file_path") or "").strip),
 bool(str(attrs.get("symbol_name") or "").strip),
 ]
 if sum(provided) != 1:
 raise serializers.ValidationError(
 "必须且只能提供 chunk_id、file_path、symbol_name 之一"
 )
 return attrs
class AnalyzeRepositoryRequestSerializer(serializers.Serializer):
 repository_id = serializers.UUIDField(required=True)
 branch = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
 focus = serializers.CharField(required=False, allow_blank=True, default="", max_length=1000)
 context_chunks = serializers.ListField(
 child=serializers.DictField,
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
 child=serializers.DictField,
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
 child=serializers.DictField,
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
 if attrs.get("project_id") or str(attrs.get("project_key") or "").strip:
 return attrs
 raise serializers.ValidationError("必须提供 project_id 或 project_key")
TOOL_SCHEMA_SNAPSHOT: dict[str, dict[str, object]] = {
 "route_repositories": {
 "request": ["query", "top_k"],
 "response": ["query", "ranked_repos", "total", "run_id"],
 },
 "search_rag_chunks": {
 "request": ["repository_id", "query", "branch", "top_k", "max_tokens"],
 "response": ["query", "repository_id", "branch", "results", "related_edges", "total_tokens", "run_id"],
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
 "response": ["repository_id", "branch", "file_path", "content", "truncated", "total_chunks", "returned_lines", "max_lines", "run_id"],
 },
 "find_related_chunks": {
 "request": ["repository_id", "branch", "chunk_id", "file_path", "symbol_name", "relation_types", "hops", "direction", "limit"],
 "response": ["repository_id", "branch", "source", "related_chunks", "run_id"],
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
}
