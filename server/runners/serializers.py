"""Runners app serializers."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from .models import RegistrationToken, Runner, RunnerEvent, RunnerTaskAssignment


class RegistrationTokenCreateSerializer(serializers.Serializer):
    description = serializers.CharField(required=False, default="", allow_blank=True)
    scope = serializers.ChoiceField(choices=["global", "project"], default="global")
    project_id = serializers.UUIDField(required=False, allow_null=True)
    expires_in = serializers.IntegerField(default=3600, min_value=60)
    tags = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    run_untagged = serializers.BooleanField(required=False, default=True)
    is_paused = serializers.BooleanField(required=False, default=False)
    is_protected = serializers.BooleanField(required=False, default=False)
    max_timeout = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=600
    )


class RegistrationTokenSerializer(serializers.ModelSerializer):
    is_valid = serializers.BooleanField(read_only=True)
    project_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = RegistrationToken
        fields = [
            "id",
            "description",
            "scope",
            "project_id",
            "tags",
            "run_untagged",
            "is_paused",
            "is_protected",
            "max_timeout",
            "is_used",
            "used_at",
            "expires_at",
            "created_at",
            "is_valid",
        ]
        read_only_fields = fields


class RunnerRegisterSerializer(serializers.Serializer):
    token = serializers.CharField()
    name = serializers.CharField(max_length=200)
    scope = serializers.ChoiceField(choices=["global", "project"], default="global")
    concurrent = serializers.IntegerField(default=1, min_value=1)
    version = serializers.CharField(required=False, default="", allow_blank=True)


class RunnerTaskBriefSerializer(serializers.ModelSerializer):
    """精简任务信息，用于 Runner 详情默认嵌套。"""

    id = serializers.CharField(source="session.session_id")
    name = serializers.CharField(source="session.task_type")

    class Meta:
        model = RunnerTaskAssignment
        fields = ["id", "name", "status"]


class RunnerTaskAssignmentSerializer(serializers.ModelSerializer):
    """完整任务信息。"""

    session_id = serializers.CharField(source="session.session_id")
    task_type = serializers.CharField(source="session.task_type")
    session_status = serializers.CharField(source="session.status")
    repo_url = serializers.URLField(source="session.repo_url")

    class Meta:
        model = RunnerTaskAssignment
        fields = [
            "id",
            "session_id",
            "task_type",
            "session_status",
            "repo_url",
            "assigned_at",
            "status",
            "completed_at",
        ]


class RunnerSerializer(serializers.ModelSerializer):
    current_task_list = serializers.SerializerMethodField()

    class Meta:
        model = Runner
        fields = [
            "id",
            "name",
            "token_prefix",
            "scope",
            "concurrent",
            "status",
            "version",
            "is_active",
            "is_paused",
            "is_protected",
            "run_untagged",
            "max_timeout",
            "description",
            "last_heartbeat",
            "ip_address",
            "registered_at",
            "tags",
            "current_tasks",
            "current_task_list",
        ]
        read_only_fields = fields

    def get_current_task_list(self, obj: Runner) -> list[dict[str, Any]]:
        qs = RunnerTaskAssignment.objects.filter(
            runner=obj,
            status__in=["assigned", "running"],
        ).select_related("session")
        request = self.context.get("request")
        if request and "current_tasks" in request.query_params.get("expand", ""):
            return RunnerTaskAssignmentSerializer(qs, many=True).data
        return RunnerTaskBriefSerializer(qs, many=True).data


class RunnerEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = RunnerEvent
        fields = ["id", "event_type", "detail", "created_at"]


class RunnerRegisterResponseSerializer(serializers.Serializer):
    runner_id = serializers.UUIDField()
    runner_token = serializers.CharField()
    name = serializers.CharField()
    scope = serializers.CharField()
