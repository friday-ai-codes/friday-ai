"""IDE 读路径 hook 资产生成 + 下发端点守护测试（HOOK-01，86-03）。"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

from initiatives.models import Project, ProjectMember, ProjectRole
from initiatives.services.ide_hook_assets import (
    RUNTIME_CLAUDE_CODE,
    RUNTIME_CODEX,
    RUNTIME_CURSOR,
    build_read_path_assets,
)
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


@pytest.fixture
def space(db) -> Space:
    return Space.objects.create(name="Hook Space", feishu_project_key="hook-space")


@pytest.fixture
def project(db, space) -> Project:
    return Project.objects.create(
        space=space, name="登录重构项目", feishu_project_key="login-key"
    )


@pytest.fixture
def member(db, project) -> object:
    u = User.objects.create_user(username="hook_member", password="x")
    ProjectMember.objects.create(project=project, user=u, role=ProjectRole.OWNER)
    return u


# ------------------------------ 服务层（读路径资产生成）------------------------------


def test_read_path_cursor_rule_alwayson(project) -> None:
    bundle = build_read_path_assets(project, RUNTIME_CURSOR)
    assert bundle["runtime"] == RUNTIME_CURSOR
    files = bundle["files"]
    assert len(files) == 1
    rule = files[0]
    assert rule["path"].endswith(".mdc")
    assert "alwaysApply: true" in rule["content"]
    assert "lookup_project_by_branch" in rule["content"]
    assert "再编码" in rule["content"]
    # notes 显式声明 beforeSubmitPrompt 不能注入。
    assert "beforeSubmitPrompt" in bundle["notes"]


def test_read_path_claude_code_inject_assets(project) -> None:
    bundle = build_read_path_assets(project, RUNTIME_CLAUDE_CODE)
    assert bundle["runtime"] == RUNTIME_CLAUDE_CODE
    paths = {f["path"] for f in bundle["files"]}
    assert any(p.startswith(".claude/rules/") for p in paths)
    assert ".claude/hooks/friday-context-inject.sh" in paths
    assert ".claude/settings.json" in paths

    by_path = {f["path"]: f["content"] for f in bundle["files"]}
    # always-on 规则正文含强制流程。
    rule_content = next(v for p, v in by_path.items() if p.startswith(".claude/rules/"))
    assert "lookup_project_by_branch" in rule_content
    assert "再编码" in rule_content

    # UserPromptSubmit 注入脚本：调 lookup_project_by_branch + 失败静默 exit 0。
    script = by_path[".claude/hooks/friday-context-inject.sh"]
    assert "lookup_project_by_branch" in script
    assert "exit 0" in script
    assert "FRIDAY_PAT" in script
    # 不内嵌任何密钥（PAT 经环境变量传入）。
    assert "Authorization: Bearer ${FRIDAY_PAT}" in script

    # settings.json 注册 UserPromptSubmit。
    settings = json.loads(by_path[".claude/settings.json"])
    assert "UserPromptSubmit" in settings["hooks"]


def test_read_path_codex_rules_only(project) -> None:
    bundle = build_read_path_assets(project, RUNTIME_CODEX)
    assert bundle["runtime"] == RUNTIME_CODEX
    files = bundle["files"]
    assert len(files) == 1
    assert files[0]["path"] == "AGENTS.md"
    assert "lookup_project_by_branch" in files[0]["content"]
    assert "MCP" in bundle["notes"] and "rules" in bundle["notes"]


@pytest.mark.parametrize(
    "runtime", [RUNTIME_CURSOR, RUNTIME_CLAUDE_CODE, RUNTIME_CODEX]
)
def test_read_path_all_runtimes_have_redaction_notice(project, runtime) -> None:
    bundle = build_read_path_assets(project, runtime)
    blob = "\n".join(f["content"] for f in bundle["files"])
    # 脱敏告诫：绝不上报凭证/密钥/token。
    assert "token" in blob and ("凭证" in blob or "密钥" in blob)


def test_read_path_unknown_runtime_raises(project) -> None:
    with pytest.raises(ValueError):
        build_read_path_assets(project, "vscode")


# ------------------------------ 端点（按 runtime 下发）------------------------------


def test_route_reverse() -> None:
    url = reverse(
        "project-ide-hook-assets",
        kwargs={"project_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert url.endswith("/ide-hook-assets/")


@pytest.mark.parametrize(
    "runtime", ["cursor", "claude_code", "codex"]
)
def test_endpoint_returns_bundle_for_member(project, member, runtime) -> None:
    client = APIClient()
    client.force_authenticate(user=member)
    resp = client.get(
        f"/api/projects/{project.id}/ide-hook-assets/?runtime={runtime}"
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["runtime"] == runtime
    assert body["kind"] == "read"
    assert isinstance(body["files"], list) and body["files"]


def test_endpoint_claude_code_has_inject_asset(project, member) -> None:
    client = APIClient()
    client.force_authenticate(user=member)
    resp = client.get(
        f"/api/projects/{project.id}/ide-hook-assets/?runtime=claude_code"
    )
    assert resp.status_code == 200, resp.content
    paths = {f["path"] for f in resp.json()["files"]}
    assert ".claude/hooks/friday-context-inject.sh" in paths


def test_endpoint_invalid_runtime_400(project, member) -> None:
    client = APIClient()
    client.force_authenticate(user=member)
    resp = client.get(
        f"/api/projects/{project.id}/ide-hook-assets/?runtime=vscode"
    )
    assert resp.status_code == 400, resp.content


def test_endpoint_forbidden_for_outsider(project) -> None:
    outsider = User.objects.create_user(username="hook_outsider", password="x")
    client = APIClient()
    client.force_authenticate(user=outsider)
    resp = client.get(
        f"/api/projects/{project.id}/ide-hook-assets/?runtime=cursor"
    )
    assert resp.status_code == 403
