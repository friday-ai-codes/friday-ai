"""SessionCapture 只读回放授权（D-02 / RECALL-03）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from initiatives.models import SessionCapture
from knowledge.access_scope import resolve_allowed_project_ids, resolve_allowed_repository_ids

if TYPE_CHECKING:
    from accounts.models import User

__all__ = ["aget_readable_capture"]


async def aget_readable_capture(
    capture_id: object,
    user: User | None,
) -> SessionCapture | None:
    """返回调用者可回放的 Capture；缺失与未授权统一收口为 ``None``。"""

    capture = await (
        SessionCapture.objects.select_related("repository", "project")
        .filter(pk=capture_id)
        .afirst()
    )
    if capture is None or user is None:
        return None
    if user.is_superuser:
        return capture

    user_id = getattr(user, "id", None)
    if user_id is None or capture.initiated_by_user_id != str(user_id):
        return None

    if capture.repository_id is not None:
        repository_id = str(capture.repository_id)
        allowed_repositories = await resolve_allowed_repository_ids(
            user,
            repository_ids=[repository_id],
        )
        if repository_id not in allowed_repositories:
            return None

    if capture.project_id is not None:
        project_id = str(capture.project_id)
        allowed_projects = await resolve_allowed_project_ids(user, [project_id])
        if project_id not in allowed_projects:
            return None

    return capture
