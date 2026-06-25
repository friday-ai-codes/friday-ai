"""ProjectScopedQuerysetMixin：自动注入项目级 queryset 过滤。"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class ProjectScopedQuerysetMixin:
    """自动按用户 membership 过滤 queryset 的 ViewSet Mixin。

    要求 Model 有 project FK（可通过 project_field 配置跨表查询路径）。
    superuser 跳过过滤，看到所有数据。

    用法::

        class WorkflowViewSet(ProjectScopedQuerysetMixin, ModelViewSet):
            project_field = "space"  # 默认值

        class ExecutionViewSet(ProjectScopedQuerysetMixin, ReadOnlyModelViewSet):
            project_field = "workflow__space"  # 跨表查询

    注意 MRO：此 Mixin 必须在 ModelViewSet/ReadOnlyModelViewSet 之前继承。
    """

    # 到 space 的查询路径，子类可覆盖
    project_field: str = "space"

    def get_queryset(self) -> Any:
        qs = super().get_queryset()  # type: ignore[misc]
        request = self.request  # type: ignore[attr-defined]
        user = request.user

        if not user.is_authenticated:
            return qs.none()

        # superuser 看所有数据
        if user.is_superuser:
            return qs

        # 普通用户按 membership 过滤
        filter_key = f"{self.project_field}__memberships__user"
        return qs.filter(**{filter_key: user}).distinct()
