"""Workflows API permissions."""

from rest_framework.permissions import BasePermission
from typing import Any
from rest_framework.request import Request
from rest_framework.views import APIView

from permissions.models import SpaceRole
from permissions.services import PermissionService
from workflows.models import NodeExecution, Workflow, WorkflowExecution


class WorkflowPermission(BasePermission):
    """Permission for Workflow operations.

    - List: User can see workflows for projects they have access to
    - Retrieve: User can view if they have access to the project (viewer+)
    - Create: User can create if they are member+ of the project
    - Update/Delete: User can modify if they are member+ (creator or admin)
    - Execute/Duplicate: member+
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        # All authenticated users can list/create
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request: Request, view: APIView, obj: Workflow) -> bool:
        user = request.user

        # Superuser can do anything
        if user.is_superuser:
            return True

        # Check project membership
        project = obj.space

        # For read operations, check if user is project member (viewer+)
        if request.method in ["GET", "HEAD", "OPTIONS"]:
            return PermissionService.has_project_access(user, project, SpaceRole.VIEWER)

        # For write operations, check if user is member+
        if request.method in ["PUT", "PATCH", "DELETE"]:
            return PermissionService.has_project_access(user, project, SpaceRole.MEMBER)

        # For POST (execute, duplicate), check member+
        return PermissionService.has_project_access(user, project, SpaceRole.MEMBER)


class ExecutionPermission(BasePermission):
    """Permission for WorkflowExecution operations.

    - List: User can see executions for workflows they have access to (viewer+)
    - Retrieve: User can view if they have access to the workflow (viewer+)
    - Pause/Resume/Cancel: member+
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        return request.user and request.user.is_authenticated

    def has_object_permission(
        self, request: Request, view: APIView, obj: WorkflowExecution
    ) -> bool:
        user = request.user

        if user.is_superuser:
            return True

        # Check workflow access
        workflow = obj.workflow
        project = workflow.space

        # Read access: viewer+
        if request.method in ["GET", "HEAD", "OPTIONS"]:
            return PermissionService.has_project_access(user, project, SpaceRole.VIEWER)

        # Write access (pause/resume/cancel): member+
        return PermissionService.has_project_access(user, project, SpaceRole.MEMBER)


class ApprovalPermission(BasePermission):
    """Permission for approval operations.

    - Approve/Reject: User must be in the approvers list (if specified)
      or be a project member (if no specific approvers)
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request: Request, view: APIView, obj: NodeExecution) -> bool:
        user = request.user

        if user.is_superuser:
            return True

        # Get node config
        node = obj.node
        node_config = node.config or {}

        # Check if specific approvers are configured
        approver_ids = node_config.get("approver_ids", [])
        approver_usernames = node_config.get("approver_usernames", [])

        if approver_ids or approver_usernames:
            # Check if current user is in approvers list
            if str(user.id) in [str(a) for a in approver_ids]:
                return True
            if user.username in approver_usernames:
                return True
            return False

        # No specific approvers configured - allow any project member (member+)
        project = obj.workflow_execution.workflow.space
        return PermissionService.has_project_access(user, project, SpaceRole.MEMBER)


class WebhookConfigPermission(BasePermission):
    """Permission for WebhookConfig operations.

    - Read: viewer+
    - Write: admin+ (webhook 配置属于空间配置)
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request: Request, view: APIView, obj) -> bool:
        user = request.user

        if user.is_superuser:
            return True

        workflow = obj.workflow
        project = workflow.space

        if request.method in ["GET", "HEAD", "OPTIONS"]:
            return PermissionService.has_project_access(user, project, SpaceRole.VIEWER)

        return PermissionService.has_project_access(user, project, SpaceRole.ADMIN)


class AlertRulePermission(BasePermission):
    """告警规则权限。

    - List/Retrieve: VIEWER+
    - Create/Update/Delete workflow-specific rules: MEMBER+
    - Create/Update/Delete global rules (workflow=null): ADMIN+ (or superuser)
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        return request.user and request.user.is_authenticated

    def has_object_permission(
        self, request: Request, view: APIView, obj: Any
    ) -> bool:
        user = request.user
        if user.is_superuser:
            return True

        project = obj.space

        # 读操作：VIEWER+
        if request.method in ["GET", "HEAD", "OPTIONS"]:
            return PermissionService.has_project_access(
                user, project, SpaceRole.VIEWER
            )

        # 全局规则（workflow=null）：ADMIN+
        if obj.workflow is None:
            return PermissionService.has_project_access(
                user, project, SpaceRole.ADMIN
            )

        # 空间级规则：MEMBER+
        return PermissionService.has_project_access(
            user, project, SpaceRole.MEMBER
        )
