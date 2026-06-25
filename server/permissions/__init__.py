"""Permissions app: 项目级权限引擎。

使用方式::

    from permissions.services import PermissionService
    from permissions.api_permissions import IsSuperUser, IsProjectMember
    from permissions.mixins import ProjectScopedQuerysetMixin
    from permissions.models import SpaceMembership, SpaceRole
"""
