"""spec 治理 REST API 守护测试（Phase 50-03，SPECST-01/02/03，D-50-3/D-50-4）。

覆盖：

- list：GET /api/specs/ 返回 + ?status= / ?repository_id= 过滤 + 非法参数 400。
- detail：GET /api/specs/<id>/ 含 body / reviews 倒序 / relations；不存在 404。
- transition：认证用户 submit_for_review 成功；非 superuser approve 403；superuser
  approve 产 approve 评审；reject 需 comment（缺失 400）回 draft；非法流转 400；
  越权(403) 与不存在(404) 不混淆。

async + sync_to_async 跨线程写库 → transaction=True。
"""

from __future__ import annotations

import uuid

import pytest

from delivery.models import Document, DocumentType, SddSpec, SddSpecStatus
from repositories.models import Repository

pytestmark = pytest.mark.django_db(transaction=True)


def _make_repo() -> Repository:
    return Repository.objects.create(
        name=f"repo-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )


def _make_spec(status: str = SddSpecStatus.DRAFT, repo: Repository | None = None) -> SddSpec:
    repo = repo or _make_repo()
    return SddSpec.objects.create(repository=repo, status=status)


# ---- list ----


def test_list_requires_auth(api_client) -> None:
    resp = api_client.get("/api/specs/")
    assert resp.status_code in (401, 403)


def test_list_returns_specs(authenticated_client) -> None:
    _make_spec(SddSpecStatus.DRAFT)
    _make_spec(SddSpecStatus.IN_REVIEW)
    resp = authenticated_client.get("/api/specs/")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_filter_by_status(authenticated_client) -> None:
    _make_spec(SddSpecStatus.DRAFT)
    target = _make_spec(SddSpecStatus.IN_REVIEW)
    resp = authenticated_client.get("/api/specs/?status=in_review")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == str(target.id)


def test_list_filter_by_repository(authenticated_client) -> None:
    repo_a = _make_repo()
    repo_b = _make_repo()
    spec_a = _make_spec(repo=repo_a)
    _make_spec(repo=repo_b)
    resp = authenticated_client.get(f"/api/specs/?repository_id={repo_a.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == str(spec_a.id)


def test_list_invalid_status_400(authenticated_client) -> None:
    resp = authenticated_client.get("/api/specs/?status=bogus")
    assert resp.status_code == 400


def test_list_invalid_repository_id_400(authenticated_client) -> None:
    resp = authenticated_client.get("/api/specs/?repository_id=not-a-uuid")
    assert resp.status_code == 400


# ---- detail ----


def test_detail_includes_body_and_relations(authenticated_client) -> None:
    repo = _make_repo()
    repo.facets = {"methodology": "SDD"}
    repo.save(update_fields=["facets"])
    doc = Document.objects.create(document_type=DocumentType.SDD_SPEC)
    from delivery.models import DocumentVersion

    version = DocumentVersion.objects.create(
        document=doc, version=1, content="## spec 正文", content_hash="h"
    )
    doc.current_version = version
    doc.save(update_fields=["current_version"])
    spec = SddSpec.objects.create(repository=repo, document=doc)

    resp = authenticated_client.get(f"/api/specs/{spec.id}/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["body"] == "## spec 正文"
    assert body["relations"]["repository"]["methodology"] == "SDD"
    assert body["reviews"] == []


def test_detail_not_found_404(authenticated_client) -> None:
    resp = authenticated_client.get(f"/api/specs/{uuid.uuid4()}/")
    assert resp.status_code == 404


# ---- transition ----


def test_submit_for_review_by_authenticated(authenticated_client) -> None:
    spec = _make_spec(SddSpecStatus.DRAFT)
    resp = authenticated_client.post(
        f"/api/specs/{spec.id}/transition/", {"action": "submit_for_review"}, format="json"
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_review"
    spec.refresh_from_db()
    assert spec.status == SddSpecStatus.IN_REVIEW


def test_non_superuser_approve_forbidden_403(authenticated_client) -> None:
    spec = _make_spec(SddSpecStatus.IN_REVIEW)
    resp = authenticated_client.post(
        f"/api/specs/{spec.id}/transition/", {"action": "approve"}, format="json"
    )
    assert resp.status_code == 403
    spec.refresh_from_db()
    assert spec.status == SddSpecStatus.IN_REVIEW


def test_superuser_approve_creates_review(authenticated_admin_client) -> None:
    spec = _make_spec(SddSpecStatus.IN_REVIEW)
    resp = authenticated_admin_client.post(
        f"/api/specs/{spec.id}/transition/",
        {"action": "approve", "comment": "LGTM"},
        format="json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "approved"
    assert len(body["reviews"]) == 1
    assert body["reviews"][0]["decision"] == "approve"
    assert body["reviews"][0]["comment"] == "LGTM"
    assert body["reviews"][0]["reviewer"] == "admin"


def test_superuser_reject_requires_comment_400(authenticated_admin_client) -> None:
    spec = _make_spec(SddSpecStatus.IN_REVIEW)
    resp = authenticated_admin_client.post(
        f"/api/specs/{spec.id}/transition/", {"action": "reject"}, format="json"
    )
    assert resp.status_code == 400
    spec.refresh_from_db()
    assert spec.status == SddSpecStatus.IN_REVIEW


def test_superuser_reject_returns_to_draft(authenticated_admin_client) -> None:
    spec = _make_spec(SddSpecStatus.IN_REVIEW)
    resp = authenticated_admin_client.post(
        f"/api/specs/{spec.id}/transition/",
        {"action": "reject", "comment": "需修订"},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "draft"


def test_illegal_transition_400(authenticated_admin_client) -> None:
    spec = _make_spec(SddSpecStatus.DRAFT)
    resp = authenticated_admin_client.post(
        f"/api/specs/{spec.id}/transition/", {"action": "approve"}, format="json"
    )
    assert resp.status_code == 400
    spec.refresh_from_db()
    assert spec.status == SddSpecStatus.DRAFT


def test_invalid_action_400(authenticated_client) -> None:
    spec = _make_spec(SddSpecStatus.DRAFT)
    resp = authenticated_client.post(
        f"/api/specs/{spec.id}/transition/", {"action": "bogus"}, format="json"
    )
    assert resp.status_code == 400


def test_transition_not_found_404(authenticated_client) -> None:
    resp = authenticated_client.post(
        f"/api/specs/{uuid.uuid4()}/transition/",
        {"action": "submit_for_review"},
        format="json",
    )
    assert resp.status_code == 404


def test_forbidden_takes_precedence_over_not_found(authenticated_client) -> None:
    """非 superuser 对不存在 spec 发受限 action：先 403（权限早于存在性检查）。"""
    resp = authenticated_client.post(
        f"/api/specs/{uuid.uuid4()}/transition/", {"action": "approve"}, format="json"
    )
    assert resp.status_code == 403
