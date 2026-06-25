"""MergeRequestService 守护测试（Phase 80，MR-01/02）：

- github/gitlab webhook 解析 open/merged/closed/review
- 幂等去重（同 dedup_key 不重复同步）
- 原始 payload 脱敏后落库（MergeRequestEvent.raw_payload）
- upsert 状态推进
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async

from initiatives.models import MergeRequest, MergeRequestEvent, MRStatus
from initiatives.services import MergeRequestService

pytestmark = pytest.mark.django_db(transaction=True)


def _github_payload(action="opened", number=42, merged=False, state="open"):
    return {
        "action": action,
        "pull_request": {
            "number": number,
            "html_url": "https://github.com/o/r/pull/42",
            "title": "feat: x",
            "state": state,
            "merged": merged,
            "head": {"ref": "feat/x"},
            "base": {"ref": "main"},
        },
        "repository": {"html_url": "https://github.com/o/r"},
    }


def _gitlab_payload(state="opened", iid=7, action="open"):
    return {
        "object_kind": "merge_request",
        "object_attributes": {
            "iid": iid,
            "url": "https://gitlab.com/o/r/-/merge_requests/7",
            "title": "feat: y",
            "source_branch": "feat/y",
            "target_branch": "main",
            "state": state,
            "action": action,
        },
        "project": {"web_url": "https://gitlab.com/o/r"},
    }


async def test_github_open_then_merged_status_progression():
    svc = MergeRequestService()
    r1 = await svc.sync_from_webhook(
        platform="github", payload=_github_payload(), dedup_key="gh-1"
    )
    assert r1["created"] is True
    assert r1["status"] == MRStatus.OPEN

    r2 = await svc.sync_from_webhook(
        platform="github",
        payload=_github_payload(action="closed", merged=True, state="closed"),
        dedup_key="gh-2",
    )
    assert r2["created"] is False
    assert r2["status"] == MRStatus.MERGED
    assert await MergeRequest.objects.filter(platform="github", external_id="42").acount() == 1


async def test_idempotent_dedup_same_key():
    svc = MergeRequestService()
    await svc.sync_from_webhook(platform="github", payload=_github_payload(), dedup_key="dup")
    r = await svc.sync_from_webhook(
        platform="github", payload=_github_payload(), dedup_key="dup"
    )
    assert r["deduped"] is True
    assert await MergeRequestEvent.objects.filter(dedup_key="dup").acount() == 1


async def test_gitlab_merged_and_review():
    svc = MergeRequestService()
    await svc.sync_from_webhook(
        platform="gitlab", payload=_gitlab_payload(), dedup_key="gl-1"
    )
    r = await svc.sync_from_webhook(
        platform="gitlab",
        payload=_gitlab_payload(state="merged", action="merge"),
        dedup_key="gl-2",
    )
    assert r["status"] == MRStatus.MERGED
    # review approval
    rev = await svc.sync_from_webhook(
        platform="gitlab",
        payload=_gitlab_payload(state="opened", action="approved"),
        dedup_key="gl-3",
    )
    mr = await MergeRequest.objects.aget(pk=rev["mr_id"])
    assert mr.review_status == "approved"


async def test_raw_payload_redacted_in_event():
    svc = MergeRequestService()
    payload = _github_payload()
    payload["sender_token"] = "sk-ant-supersecretvalue1234567890abc"
    await svc.sync_from_webhook(platform="github", payload=payload, dedup_key="redact-1")
    ev = await MergeRequestEvent.objects.aget(dedup_key="redact-1")
    raw = await sync_to_async(lambda: str(ev.raw_payload))()
    assert "sk-ant-supersecretvalue1234567890abc" not in raw


async def test_unknown_pr_payload_ignored():
    svc = MergeRequestService()
    r = await svc.sync_from_webhook(
        platform="github", payload={"action": "ping"}, dedup_key="ignore-1"
    )
    assert r["ignored"] is True
