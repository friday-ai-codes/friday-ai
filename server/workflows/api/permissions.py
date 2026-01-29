"""Workflows API permissions."""
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView
from workflows.models import NodeExecution, Workflow, WorkflowExecution
class WorkflowPermission(BasePermission):
 """Permission for Workflow operations.
 - List: User can see workflows for projects they have access to
 - Retrieve: User can view if they have access to the project
 - Create: User can create if they have access to the project
 - Update/Delete: User can modify if they created it or are project admin
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
 project = obj.project
 # For read operations, check if user is project member
 if request.method in ["GET", "HEAD", "OPTIONS"]:
 return self._is_project_member(user, project)
 # For write operations, check if user is creator or project admin
 if request.method in ["PUT", "PATCH", "DELETE"]:
 if obj.created_by == user:
 return True
 return self._is_project_admin(user, project)
 # For POST (execute, duplicate), check project membership
 return self._is_project_member(user, project)
 def _is_project_member(self, user, project) -> bool:
 """Check if user is a member of the project."""
 # For now, allow all authenticated users
 # TODO: Implement actual project membership check
 return True
 def _is_project_admin(self, user, project) -> bool:
 """Check if user is an admin of the project."""
 # For now, allow if user created the project
 # TODO: Implement actual project admin check
 return project.created_by_id == user.id if hasattr(project, "created_by_id") else True
class ExecutionPermission(BasePermission):
 """Permission for WorkflowExecution operations.
 - List: User can see executions for workflows they have access to
 - Retrieve: User can view if they have access to the workflow
 - Pause/Resume/Cancel: User can control if they have access to the workflow
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
 project = workflow.project
 # Read access: project members
 if request.method in ["GET", "HEAD", "OPTIONS"]:
 return self._is_project_member(user, project)
 # Write access (pause/resume/cancel): workflow creator or project admin
 if workflow.created_by == user:
 return True
 return self._is_project_admin(user, project)
 def _is_project_member(self, user, project) -> bool:
 return True
 def _is_project_admin(self, user, project) -> bool:
 return project.created_by_id == user.id if hasattr(project, "created_by_id") else True
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
 approver_ids = node_config.get("approver_ids", )
 approver_usernames = node_config.get("approver_usernames", )
 if approver_ids or approver_usernames:
 # Check if current user is in approvers list
 if str(user.id) in [str(a) for a in approver_ids]:
 return True
 if user.username in approver_usernames:
 return True
 return False
 # No specific approvers configured - allow any project member
 project = obj.workflow_execution.workflow.project
 return self._is_project_member(user, project)
 def _is_project_member(self, user, project) -> bool:
 return True
class WebhookConfigPermission(BasePermission):
 """Permission for WebhookConfig operations.
 Same as WorkflowPermission - based on workflow access.
 """
 def has_permission(self, request: Request, view: APIView) -> bool:
 return request.user and request.user.is_authenticated
 def has_object_permission(self, request: Request, view: APIView, obj) -> bool:
 user = request.user
 if user.is_superuser:
 return True
 workflow = obj.workflow
 project = workflow.project
 if request.method in ["GET", "HEAD", "OPTIONS"]:
 return self._is_project_member(user, project)
 return workflow.created_by == user or self._is_project_admin(user, project)
 def _is_project_member(self, user, project) -> bool:
 return True
 def _is_project_admin(self, user, project) -> bool:
 return project.created_by_id == user.id if hasattr(project, "created_by_id") else True
