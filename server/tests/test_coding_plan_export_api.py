"""POST /api/chat/coding-plans/{id}/export-to-feishu/ 端点 pytest 覆盖（work item）。

测试矩阵：
    1. 成功路径（请求体带 folder_token + title）
    2. fallback 到 project.feishu_doc_folder_token
    3. folder_token 全空 → 400 + error_type=not_configured，不调 exporter
    4. CodingPlan 不存在 → 404
    5. PermissionDeniedError → 403 + error_type=permission_denied
    6. FeishuDocAPIError → 502 + error_type=api_error
    7. title 超长 → 400（serializer 校验失败）
    8. 不传 title → exporter 收到 title=None
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from chat.models import CodingPlan, Conversation
from projects.models import Project
from services.feishu_doc import FeishuDocAPIError, PermissionDeniedError

User = get_user_model()


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def export_user(db):
    """导出测试共享用户（owner gate 要求 conversation.created_by 与认证用户一致）。"""
    return User.objects.create_user(
        username=f"export_285_{uuid.uuid4().hex[:6]}",
        email=f"{uuid.uuid4().hex[:6]}@test.local",
        password="testpass123",
    )


@pytest.fixture
def coding_plan_with_project(db, export_user) -> CodingPlan:
    """构造 Project + Conversation + CodingPlan，复用 implementation 模型形态。

    Project.feishu_doc_folder_token 预填 `fk_fallback`，测试可按需改写。
    """
    suffix = uuid.uuid4().hex[:8]
    project = Project.objects.create(
        name=f"导出测试-checkpoint-{suffix}",
        feishu_project_key=f"project-{suffix}",
        feishu_doc_folder_token="fk_fallback",
        feishu_app_id="cli_test",
        feishu_app_secret_encrypted="enc_test",
    )
    conversation = Conversation.objects.create(
        project=project, title="对话-checkpoint", created_by=export_user
    )
    return CodingPlan.objects.create(
        conversation=conversation,
        title="示例方案",
        tech_plan="# 概要\n\n说明",
        affected_files=[],
    )


@pytest.fixture
def export_client(db, export_user) -> APIClient:
    """已认证的 APIClient（force_authenticate 注入用户）。"""
    client = APIClient()
    client.force_authenticate(user=export_user)
    return client


# ============================================================================
# Tests
# ============================================================================


MOCK_EXPORT_RESULT = {
    "doc_token": "doxcnTEST",
    "doc_url": "https://feishu.cn/docx/doxcnTEST",
}


@pytest.mark.django_db(transaction=True)
def test_export_success_with_request_folder_token(
    export_client: APIClient, coding_plan_with_project: CodingPlan
) -> None:
    """请求体带 folder_token + title → 200 + 完整响应体。"""
    plan = coding_plan_with_project
    with patch(
        "chat.views.export_coding_plan_to_feishu",
        new=AsyncMock(return_value=MOCK_EXPORT_RESULT),
    ) as mock_exporter:
        resp = export_client.post(
            f"/api/chat/coding-plans/{plan.id}/export-to-feishu/",
            {"folder_token": "fk_T", "title": "自定义标题"},
            format="json",
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["doc_token"] == "doxcnTEST"
    assert body["doc_url"].endswith("doxcnTEST")
    assert body["title"] == "自定义标题"
    assert "exported_at" in body and body["exported_at"]

    mock_exporter.assert_awaited_once()
    kwargs = mock_exporter.await_args.kwargs
    assert kwargs["folder_token"] == "fk_T"
    assert kwargs["title"] == "自定义标题"
    assert str(kwargs["coding_plan"].id) == str(plan.id)


@pytest.mark.django_db(transaction=True)
def test_export_falls_back_to_project_folder_token(
    export_client: APIClient, coding_plan_with_project: CodingPlan
) -> None:
    """不传 folder_token → 使用 project.feishu_doc_folder_token。"""
    plan = coding_plan_with_project
    with patch(
        "chat.views.export_coding_plan_to_feishu",
        new=AsyncMock(return_value={"doc_token": "d", "doc_url": "u"}),
    ) as mock_exporter:
        resp = export_client.post(
            f"/api/chat/coding-plans/{plan.id}/export-to-feishu/",
            {},
            format="json",
        )

    assert resp.status_code == 200
    assert mock_exporter.await_args.kwargs["folder_token"] == "fk_fallback"


@pytest.mark.django_db(transaction=True)
def test_export_400_when_no_folder_token_anywhere(
    export_client: APIClient, coding_plan_with_project: CodingPlan
) -> None:
    """请求与 project 都缺 folder_token → 400 not_configured，且不调 exporter。"""
    plan = coding_plan_with_project
    plan.conversation.project.feishu_doc_folder_token = ""
    plan.conversation.project.save(update_fields=["feishu_doc_folder_token"])

    with patch(
        "chat.views.export_coding_plan_to_feishu",
        new=AsyncMock(),
    ) as mock_exporter:
        resp = export_client.post(
            f"/api/chat/coding-plans/{plan.id}/export-to-feishu/",
            {},
            format="json",
        )

    assert resp.status_code == 400
    assert resp.json()["error_type"] == "not_configured"
    mock_exporter.assert_not_awaited()


@pytest.mark.django_db(transaction=True)
def test_export_404_unknown_plan(export_client: APIClient) -> None:
    resp = export_client.post(
        f"/api/chat/coding-plans/{uuid.uuid4()}/export-to-feishu/",
        {"folder_token": "fk_T"},
        format="json",
    )
    assert resp.status_code == 404


@pytest.mark.django_db(transaction=True)
def test_export_403_permission_denied(
    export_client: APIClient, coding_plan_with_project: CodingPlan
) -> None:
    plan = coding_plan_with_project
    with patch(
        "chat.views.export_coding_plan_to_feishu",
        new=AsyncMock(side_effect=PermissionDeniedError("no perm")),
    ):
        resp = export_client.post(
            f"/api/chat/coding-plans/{plan.id}/export-to-feishu/",
            {"folder_token": "fk_T"},
            format="json",
        )

    assert resp.status_code == 403
    assert resp.json()["error_type"] == "permission_denied"


@pytest.mark.django_db(transaction=True)
def test_export_502_api_error(
    export_client: APIClient, coding_plan_with_project: CodingPlan
) -> None:
    plan = coding_plan_with_project
    with patch(
        "chat.views.export_coding_plan_to_feishu",
        new=AsyncMock(side_effect=FeishuDocAPIError("rate limited")),
    ):
        resp = export_client.post(
            f"/api/chat/coding-plans/{plan.id}/export-to-feishu/",
            {"folder_token": "fk_T"},
            format="json",
        )

    assert resp.status_code == 502
    assert resp.json()["error_type"] == "api_error"


@pytest.mark.django_db(transaction=True)
def test_export_400_title_too_long(
    export_client: APIClient, coding_plan_with_project: CodingPlan
) -> None:
    plan = coding_plan_with_project
    resp = export_client.post(
        f"/api/chat/coding-plans/{plan.id}/export-to-feishu/",
        {"folder_token": "fk_T", "title": "x" * 201},
        format="json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db(transaction=True)
def test_export_default_title_none_when_omitted(
    export_client: APIClient, coding_plan_with_project: CodingPlan
) -> None:
    """不传 title → exporter 收到 title=None，让其内部回退 plan.title。"""
    plan = coding_plan_with_project
    with patch(
        "chat.views.export_coding_plan_to_feishu",
        new=AsyncMock(return_value=MOCK_EXPORT_RESULT),
    ) as mock_exporter:
        resp = export_client.post(
            f"/api/chat/coding-plans/{plan.id}/export-to-feishu/",
            {"folder_token": "fk_T"},
            format="json",
        )

    assert resp.status_code == 200
    assert mock_exporter.await_args.kwargs["title"] is None
    # 响应体 title 字段则回退到 plan.title
    assert resp.json()["title"] == "示例方案"


@pytest.mark.django_db(transaction=True)
def test_export_400_when_not_configured_from_exporter_valueerror(
    export_client: APIClient, coding_plan_with_project: CodingPlan
) -> None:
    """exporter 内部抛 ValueError（项目无飞书凭证）→ 400 not_configured。"""
    plan = coding_plan_with_project
    with patch(
        "chat.views.export_coding_plan_to_feishu",
        new=AsyncMock(side_effect=ValueError("项目未配置飞书应用凭证")),
    ):
        resp = export_client.post(
            f"/api/chat/coding-plans/{plan.id}/export-to-feishu/",
            {"folder_token": "fk_T"},
            format="json",
        )

    assert resp.status_code == 400
    assert resp.json()["error_type"] == "not_configured"
