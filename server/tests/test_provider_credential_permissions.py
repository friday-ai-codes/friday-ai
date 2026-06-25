"""Provider 凭证 16 用例权限矩阵集成测试（contract 硬性契约）。

参考 context contract/contract + plan 实际交付的 ProviderCredentialPermission + get_queryset +
perform_acreate 契约，参数化 4 角色 × 场景组合成 16 用例矩阵。

矩阵设计原则（与 plan 实际代码对齐）：
- system_admin（is_superuser=True）：全通
- project_a_admin（SpaceRole.ADMIN）：system 读 + project_a 读写；跨项目 retrieve 返回 404
- project_a_member（SpaceRole.MEMBER）：本项目读写（MEMBER+ 即可写，plan 落地）
- project_a_viewer（SpaceRole.VIEWER）：本项目 + system 只读，写操作 403
- project_b_admin（SpaceRole.ADMIN）：project_b 读写；跨项目 retrieve/PATCH 404

contract 关键断言：跨项目 retrieve/PATCH/DELETE → **404**（非 403），防"凭证存在"事实泄漏
（get_queryset filter 用户可见 → detail 404 比 permission 403 更安全）。

本 plan 不消费 plan 的 toggle-active / refresh-models / types 端点，纯走 CRUD 基础端点。
"""

from __future__ import annotations

import json

import pytest
from rest_framework.test import APIClient

# ======================================================================
# 矩阵请求体模板（占位符 __PROJECT_A_ID__ 在测试体内按 fixture 替换）
# ======================================================================

REQUEST_BODIES: dict[str, dict] = {
    "CREATE_SYSTEM_ANTHROPIC": {
        "provider_type": "anthropic",
        "name": "matrix-sys-anth",
        "scope": "system",
        "default_model": "claude-3-5-sonnet-20241022",
        "available_models": [
            {
                "id": "claude-3-5-sonnet-20241022",
                "display_name": "Claude 3.5 Sonnet",
            }
        ],
        "config": {
            "api_key": "sk-ant-matrix-system-testing",
            "base_url": "https://api.anthropic.com",
        },
    },
    "CREATE_PROJECT_A_GEMINI": {
        "provider_type": "gemini",
        "name": "matrix-pa-gem",
        "scope": "project",
        "scope_id": "__PROJECT_A_ID__",
        "default_model": "gemini-1.5-pro",
        "available_models": [
            {"id": "gemini-1.5-pro", "display_name": "Gemini 1.5 Pro"}
        ],
        "config": {
            "api_key": "AIzaSy-matrix-project-a-testing",
        },
    },
    "CREATE_PROJECT_A_OLLAMA": {
        "provider_type": "ollama",
        "name": "matrix-pa-oll",
        "scope": "project",
        "scope_id": "__PROJECT_A_ID__",
        "default_model": "llama3.2",
        "available_models": [
            {"id": "llama3.2", "display_name": "llama3.2"}
        ],
        "config": {
            "base_url": "http://localhost:11434",
        },
    },
    "PATCH_RENAME": {"name": "matrix-renamed"},
}


# ======================================================================
# 16 用例权限矩阵（Cartesian 4 角色 × 4 场景抽样 + 跨项目防泄漏边界）
#
# 格式：(user_fixture_name, method, url_template, body_key_or_None, expected_status)
# url_template 支持 {project_a} / {project_b} / {project_a_cred} / {project_b_cred} 替换
# ======================================================================

PERMISSION_MATRIX: list[tuple[str, str, str, str | None, int]] = [
    # ---- system_admin（is_superuser）：全通 ----
    ("system_admin_user", "GET", "/api/providers/credentials/?scope=system", None, 200),
    (
        "system_admin_user",
        "GET",
        "/api/providers/credentials/?scope=project&project_id={project_a}",
        None,
        200,
    ),
    (
        "system_admin_user",
        "POST",
        "/api/providers/credentials/",
        "CREATE_SYSTEM_ANTHROPIC",
        201,
    ),
    (
        "system_admin_user",
        "DELETE",
        "/api/providers/credentials/{project_a_cred}/",
        None,
        204,
    ),
    # ---- project_a_admin：system 读 + project_a 读写；跨项目 retrieve 404 ----
    (
        "project_a_admin_user",
        "GET",
        "/api/providers/credentials/?scope=system",
        None,
        200,
    ),
    (
        "project_a_admin_user",
        "GET",
        "/api/providers/credentials/?scope=project&project_id={project_a}",
        None,
        200,
    ),
    (
        "project_a_admin_user",
        "POST",
        "/api/providers/credentials/",
        "CREATE_PROJECT_A_GEMINI",
        201,
    ),
    (
        "project_a_admin_user",
        "GET",
        "/api/providers/credentials/{project_b_cred}/",
        None,
        404,
    ),
    # ---- project_a_member：本项目读写（MEMBER+ 契约，plan 落地）----
    (
        "project_a_member_user",
        "GET",
        "/api/providers/credentials/?scope=project&project_id={project_a}",
        None,
        200,
    ),
    (
        "project_a_member_user",
        "POST",
        "/api/providers/credentials/",
        "CREATE_PROJECT_A_OLLAMA",
        201,
    ),
    (
        "project_a_member_user",
        "DELETE",
        "/api/providers/credentials/{project_b_cred}/",
        None,
        404,
    ),
    # ---- project_a_viewer：本项目 + system 只读；写操作禁止 ----
    (
        "project_a_viewer_user",
        "GET",
        "/api/providers/credentials/?scope=system",
        None,
        200,
    ),
    (
        "project_a_viewer_user",
        "POST",
        "/api/providers/credentials/",
        "CREATE_SYSTEM_ANTHROPIC",
        403,
    ),
    (
        "project_a_viewer_user",
        "PATCH",
        "/api/providers/credentials/{project_a_cred}/",
        "PATCH_RENAME",
        403,
    ),
    # ---- project_b_admin：跨项目访问 project_a 凭证一律 404 ----
    (
        "project_b_admin_user",
        "GET",
        "/api/providers/credentials/{project_a_cred}/",
        None,
        404,
    ),
    (
        "project_b_admin_user",
        "PATCH",
        "/api/providers/credentials/{project_a_cred}/",
        "PATCH_RENAME",
        404,
    ),
]


# ======================================================================
# helper：已认证的 APIClient
# ======================================================================


def _client_for(user) -> APIClient:
    """force_authenticate 注入用户，绕过 JWT login 路径（既有 test_provider_health 同模式）。"""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _format_body(body_key: str | None, project_a_id) -> dict | None:
    """构造请求体；__PROJECT_A_ID__ 占位符按 fixture id 替换。"""
    if body_key is None:
        return None
    body = json.loads(json.dumps(REQUEST_BODIES[body_key]))  # deep copy
    if body.get("scope_id") == "__PROJECT_A_ID__":
        body["scope_id"] = str(project_a_id)
    return body


# ======================================================================
# 矩阵测试（同步 def test_*，既有 test_provider_health 证明 DRF APIClient 可调 adrf ViewSet）
# ======================================================================


@pytest.mark.django_db
@pytest.mark.parametrize(
    "user_fixture,method,url_template,body_key,expected_status",
    PERMISSION_MATRIX,
)
def test_provider_credential_permission_matrix(
    user_fixture: str,
    method: str,
    url_template: str,
    body_key: str | None,
    expected_status: int,
    request: pytest.FixtureRequest,
    project_a,
    project_b,
    project_a_anthropic_credential,
    project_b_openai_credential,
) -> None:
    """contract 16 用例权限矩阵。

    每个用例断言 (user_fixture × HTTP method × URL) 三元组的精确 status code
    与 contract/contract 契约一致；失败时输出 user + method + URL + body 调试信息。
    """
    user = request.getfixturevalue(user_fixture)
    client = _client_for(user)

    url = url_template.format(
        project_a=project_a.id,
        project_b=project_b.id,
        project_a_cred=project_a_anthropic_credential.id,
        project_b_cred=project_b_openai_credential.id,
    )
    body = _format_body(body_key, project_a.id)

    if method == "GET":
        resp = client.get(url)
    elif method == "POST":
        resp = client.post(url, data=body, format="json")
    elif method == "PATCH":
        resp = client.patch(url, data=body or {}, format="json")
    elif method == "DELETE":
        resp = client.delete(url)
    else:
        pytest.fail(f"Unsupported method {method}")

    assert resp.status_code == expected_status, (
        f"user={user_fixture} {method} {url} body={body!r} "
        f"expected={expected_status} got={resp.status_code} resp={resp.content!r}"
    )


# ======================================================================
# 冒烟：未认证 GET list → 401（矩阵外断言，防 force_authenticate 漏网）
# ======================================================================


@pytest.mark.django_db
def test_anonymous_cannot_access_credentials() -> None:
    """未认证用户访问 list 端点必须 401（DRF IsAuthenticated 底线）。"""
    resp = APIClient().get("/api/providers/credentials/")
    assert resp.status_code in (401, 403), resp.content
