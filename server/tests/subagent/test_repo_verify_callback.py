"""repo_verify 容器回调 → verdict 落 RepoVerifyTask 测试（Phase 88-03，REPO-02）。

**真实容器 E2E DEFERRED**（见 88-UAT.md A1）：全程 mock payload（mirror
``test_research_completion_callback``），覆盖：
- completion 解析结构化/JSON 文本 verdict → record_verdict（task done + verdict 落库 + 关联状态）；
- 空/不可解析 output → mark_verify_failed(empty_or_unparseable)；
- failure 回调 → mark_verify_failed(container_failed)；
- 非 repo_verify session 不触发 verify 钩子；
- verify 钩子异常 swallow，_handle_completed 仍返 200（Pitfall 4）；
- _derive_container_call_source(REPO_VERIFY) == repo_verify_container；
- parse_verify_verdict 结构化/JSON 围栏/不可解析。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from agents.models import AgentSession
from initiatives.models import (
    Project,
    RepoAssociation,
    RepoAssociationStatus,
    RepoVerifyTask,
    RepoVerifyTaskStatus,
)
from projects.models import Space
from repositories.models import Repository
from subagent.models import SubAgentSession

pytestmark = pytest.mark.django_db(transaction=True)


async def _setup(last_output_extra: dict | None = None):
    space = await Space.objects.acreate(name=f"cb-{uuid.uuid4().hex[:6]}")
    project = await Project.objects.acreate(space=space, name="P", feishu_project_key="")
    repo = await Repository.objects.acreate(
        name=f"r-{uuid.uuid4().hex[:6]}",
        git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )
    assoc = await RepoAssociation.objects.acreate(
        project=project, repository=repo, status=RepoAssociationStatus.VERIFYING
    )
    task = await RepoVerifyTask.objects.acreate(
        association=assoc, repository=repo, status=RepoVerifyTaskStatus.RUNNING
    )
    agent = await AgentSession.objects.acreate(session_id=f"agent-{uuid.uuid4().hex[:8]}")
    last_output = {
        "source": "repo_verify",
        "repo_verify_task_id": str(task.id),
        "association_id": str(assoc.id),
        "repository_id": str(repo.id),
    }
    if last_output_extra:
        last_output.update(last_output_extra)
    sub = await SubAgentSession.objects.acreate(
        session_id=f"repo-verify-{uuid.uuid4().hex[:8]}",
        main_session=agent,
        repo_url=repo.git_url,
        task_type=SubAgentSession.TaskType.REPO_VERIFY,
        status=SubAgentSession.Status.RUNNING,
        last_output=last_output,
    )
    return repo, assoc, task, sub


def _log() -> Any:
    log = AsyncMock()
    log.info = lambda *a, **kw: None
    log.debug = lambda *a, **kw: None
    log.warning = lambda *a, **kw: None
    return log


_PATCHES = (
    patch("subagent.api.callbacks._update_coding_session_on_complete", new_callable=AsyncMock),
    patch("subagent.api.callbacks._schedule_workflow_resume"),
    patch("subagent.api.callbacks._schedule_agent_session_resume"),
)


# ===========================================================================
# completion —— 解析 verdict 落库
# ===========================================================================


async def test_structured_verdict_recorded() -> None:
    """结构化 fit verdict → record_verdict（task done + verdict 落库 + 关联→verified）。"""
    repo, assoc, task, sub = await _setup()
    payload = {
        "result_type": "text",
        "output": {
            "fit": "fit",
            "confidence": "high",
            "summary": "本仓鉴权模块匹配",
            "evidence_files": ["auth/service.py"],
            "mismatch_reasons": [],
        },
    }
    from subagent.api.callbacks import _handle_completed

    with (_PATCHES[0], _PATCHES[1], _PATCHES[2]):
        resp = await _handle_completed(sub, payload, _log())

    assert resp.status_code == 200
    await task.arefresh_from_db()
    assert task.status == RepoVerifyTaskStatus.DONE
    assert task.verdict.get("fit") == "fit"
    assert task.verdict.get("evidence_files") == ["auth/service.py"]
    # per-repo 关联状态推进
    await assoc.arefresh_from_db()
    assert assoc.status == RepoAssociationStatus.VERIFIED


async def test_text_json_verdict_mismatch_rejects() -> None:
    """JSON 围栏文本 verdict mismatch → record_verdict + 关联→rejected。"""
    repo, assoc, task, sub = await _setup()
    payload = {
        "result_type": "text",
        "output": {
            "text": '```json\n{"fit": "mismatch", "mismatch_reasons": ["无对应业务代码"]}\n```'
        },
    }
    from subagent.api.callbacks import _handle_completed

    with (_PATCHES[0], _PATCHES[1], _PATCHES[2]):
        resp = await _handle_completed(sub, payload, _log())

    assert resp.status_code == 200
    await task.arefresh_from_db()
    assert task.status == RepoVerifyTaskStatus.DONE
    assert task.verdict.get("fit") == "mismatch"
    assert task.verdict.get("mismatch_reasons") == ["无对应业务代码"]
    await assoc.arefresh_from_db()
    assert assoc.status == RepoAssociationStatus.REJECTED


async def test_empty_output_marks_failed() -> None:
    """空/不可解析 output → mark_verify_failed(empty_or_unparseable)。"""
    repo, assoc, task, sub = await _setup()
    payload = {"result_type": "text", "output": {"text": "一段非 JSON 自由文本"}}
    from subagent.api.callbacks import _handle_completed

    with (_PATCHES[0], _PATCHES[1], _PATCHES[2]):
        resp = await _handle_completed(sub, payload, _log())

    assert resp.status_code == 200
    await task.arefresh_from_db()
    assert task.status == RepoVerifyTaskStatus.FAILED
    assert task.error.get("reason") == "empty_or_unparseable"


async def test_non_repo_verify_does_not_trigger() -> None:
    """非 repo_verify session（source 不符）→ 不改 task。"""
    repo, assoc, task, sub = await _setup(last_output_extra={"source": "other"})
    payload = {"result_type": "text", "output": {"fit": "fit"}}
    from subagent.api.callbacks import _handle_completed

    with (_PATCHES[0], _PATCHES[1], _PATCHES[2]):
        resp = await _handle_completed(sub, payload, _log())

    assert resp.status_code == 200
    await task.arefresh_from_db()
    assert task.status == RepoVerifyTaskStatus.RUNNING


async def test_completion_exception_swallowed_returns_200() -> None:
    """verify 完成钩子异常 → swallow，回调返 200（Pitfall 4 不回 5xx）。"""
    repo, assoc, task, sub = await _setup()
    payload = {"result_type": "text", "output": {"fit": "fit"}}
    from subagent.api.callbacks import _handle_completed

    async def _boom(*a, **kw):
        raise RuntimeError("downstream failure")

    with (
        _PATCHES[0], _PATCHES[1], _PATCHES[2],
        patch("subagent.api.callbacks._handle_repo_verify_completion", new=_boom),
    ):
        resp = await _handle_completed(sub, payload, _log())

    assert resp.status_code == 200


# ===========================================================================
# failure —— 容器失败 mark_verify_failed
# ===========================================================================


async def test_failure_marks_container_failed() -> None:
    """repo_verify 容器失败回调 → mark_verify_failed(container_failed)。"""
    repo, assoc, task, sub = await _setup()
    payload = {"error": "容器超时"}
    from subagent.api.callbacks import _handle_failed

    with (
        patch("subagent.api.callbacks._update_coding_session_on_fail", new_callable=AsyncMock),
        patch("subagent.api.callbacks._send_failure_notification", new_callable=AsyncMock),
        patch("subagent.api.callbacks._schedule_workflow_resume"),
        patch("subagent.api.callbacks._schedule_agent_session_resume"),
    ):
        resp = await _handle_failed(sub, payload, _log())

    assert resp.status_code == 200
    await task.arefresh_from_db()
    assert task.status == RepoVerifyTaskStatus.FAILED
    assert task.error.get("reason") == "container_failed"


# ===========================================================================
# call_source 映射 + parse_verify_verdict
# ===========================================================================


async def test_derive_call_source_repo_verify_container() -> None:
    """_derive_container_call_source(REPO_VERIFY session) == repo_verify_container。"""
    repo, assoc, task, sub = await _setup()
    from subagent.api.callbacks import _derive_container_call_source

    assert _derive_container_call_source(sub) == "repo_verify_container"


def test_parse_verify_verdict_variants() -> None:
    """parse_verify_verdict：结构化透传 / JSON 围栏提取 / 不可解析 None。"""
    from subagent.api.callbacks import parse_verify_verdict

    assert parse_verify_verdict({"fit": "fit"}) == {"fit": "fit"}
    parsed = parse_verify_verdict({"text": '```json\n{"fit": "unknown"}\n```'})
    assert parsed is not None and parsed["fit"] == "unknown"
    assert parse_verify_verdict({"text": "纯文本无 JSON"}) is None
    assert parse_verify_verdict({}) is None
    assert parse_verify_verdict(None) is None
