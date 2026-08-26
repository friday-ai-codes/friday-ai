"""Run the isolated HTTP canary for the Friday blueprint-controller contract.

This creates only synthetic 高三提分 fixture data in the configured database.  It never
reads Feishu, Multica, Git, or any configured production credential.  The public MCP
HTTP endpoints are then exercised over loopback with a freshly generated local PAT.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import django
from asgiref.sync import async_to_sync


def _post(base_url: str, token: str, endpoint: str, payload: dict[str, Any]) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"{base_url}{endpoint}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 -- loopback canary URL
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def _expect(status: int, actual: int, payload: dict, message: str) -> None:
    if actual != status:
        raise AssertionError(f"{message}: expected HTTP {status}, got {actual}: {payload}")


def _seed() -> tuple[str, str, str, str]:
    from access_tokens.models import AccessToken, generate_pat
    from accounts.models import User
    from delivery.models import (
        Artifact,
        BlueprintStatus,
        ConvergenceSession,
        ConvergenceSessionEntrypoint,
        ConvergenceSessionStatus,
    )
    from delivery.services import ArtifactService
    from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService
    from initiatives.models import Project, ProjectMember
    from interactions.ledger import create_interaction_run
    from mcp_tools.models import McpWorkItemContext, McpWorkItemTechnicalPlan
    from projects.models import Space
    from repositories.models import FileIndex, IndexStatus, Repository
    from runners.models import hash_token

    user = User.objects.create_user(
        username=f"canary-controller-{uuid.uuid4().hex[:10]}", password=uuid.uuid4().hex
    )
    token = generate_pat()
    AccessToken.objects.create(
        name="isolated-blueprint-canary",
        token_hash=hash_token(token),
        token_prefix=token[:12],
        token_suffix=token[-4:],
        created_by=user,
    )

    project_key = f"canary-gaosan-{uuid.uuid4().hex[:8]}"
    space = Space.objects.create(
        name=f"canary-space-{uuid.uuid4().hex[:8]}", feishu_project_key=project_key
    )
    project = Project.objects.create(
        id=uuid.uuid4(), space=space, name="高三提分专项（isolated canary）"
    )
    ProjectMember.objects.create(project=project, user=user)
    repositories = []
    for name in ("onion-learning", "study-course", "onion-practice"):
        repository = Repository.objects.create(
            name=name,
            git_url=f"https://example.invalid/{name}.git",
            default_branch="main",
            index_status=IndexStatus.INDEXED,
        )
        FileIndex.objects.create(
            repository=repository,
            file_path=f"src/{name}/blueprint.py",
            file_hash=f"canary-{name}-hash",
        )
        repositories.append(repository)

    fixture_path = (
        Path(__file__).resolve().parents[1]
        / "tests"
        / "fixtures"
        / "blueprint_golden"
        / "gaokao_boost.json"
    )
    content = copy.deepcopy(json.loads(fixture_path.read_text(encoding="utf-8"))["blueprint"])
    content.setdefault("meta", {})["project_id"] = str(project.id)
    artifact = async_to_sync(ArtifactService().create)(
        "technical_plan", content, created_by_user_id=str(user.id)
    )
    Artifact.objects.filter(id=artifact.id).update(
        blueprint_status=BlueprintStatus.NEEDS_CLARIFICATION
    )
    artifact.refresh_from_db()
    ConvergenceSession.objects.create(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.WORKFLOW,
        current_stage="spec_gate",
        status=ConvergenceSessionStatus.RUNNING,
        current_artifact_version_id=artifact.current_version_id,
        created_by=user,
    )

    run = create_interaction_run(token_fingerprint=hash_token(token), source="mcp")
    context = McpWorkItemContext.objects.create(
        run=run,
        space=space,
        feishu_project_key=project_key,
        work_item_type="story",
        work_item_id=20260826,
        name="高三提分专项",
        description="isolated fixture only",
    )
    matrix = [
        {
            "order": index,
            "repository_id": str(repository.id),
            "repository_name": repository.name,
            "base_branch": "main",
            "planned_branch": f"feat/canary-gaosan-{repository.name}",
            "change_goal": "验证蓝图批准后编码任务门禁",
            "candidate_files": [f"src/{repository.name}/blueprint.py"],
            "steps": ["按 Friday 蓝图执行"],
            "test_strategy": ["canary contract"],
            "risks": ["fixture only"],
            "rollback": "drop isolated canary database",
        }
        for index, repository in enumerate(repositories, start=1)
    ]
    plan = McpWorkItemTechnicalPlan.objects.create(
        run=run,
        context=context,
        space=space,
        feishu_project_key=project_key,
        work_item_type="story",
        work_item_id=20260826,
        title="高三提分专项技术蓝图（isolated canary）",
        status=McpWorkItemTechnicalPlan.Status.PARTIAL,
        plan_body={"repository_task_matrix": matrix},
        repository_tasks=matrix,
        blueprint_artifact_id=str(artifact.id),
    )
    question = "高三提分专项的学习权益校验应复用哪套既有接口？"
    thread = async_to_sync(BlueprintLifecycleService().open_thread)(
        artifact,
        kind="ai_clarification",
        blocking=True,
        question=question,
        anchor={"block_id": "gaosan-rights", "section_path": "implementation"},
        initiated_by_user_id=str(user.id),
    )
    thread.options = [
        {"id": "study-course", "label": "复用 study-course 的现有权益接口"},
        {"id": "new-api", "label": "新建专项权益接口"},
    ]
    thread.save(update_fields=["options"])
    return token, str(artifact.id), str(plan.id), str(thread.id)


def run(base_url: str) -> None:
    from delivery.models import Artifact, BlueprintStatus, BlueprintThread, ThreadStatus
    from mcp_tools.models import McpWorkItemRepoTask

    token, artifact_id, plan_id, thread_id = _seed()
    get_path = "/api/mcp/tools/get_technical_blueprint/"
    answer_path = "/api/mcp/tools/answer_blueprint_clarification/"
    rework_path = "/api/mcp/tools/request_technical_blueprint_changes/"
    approve_path = "/api/mcp/tools/approve_technical_blueprint/"
    tasks_path = "/api/mcp/tools/create_work_item_repo_tasks/"

    code, blocked = _post(base_url, token, tasks_path, {"technical_plan_id": plan_id})
    _expect(400, code, blocked, "coding must be blocked before approval")
    assert blocked["error_code"] == "blueprint_not_approved"

    code, initial = _post(base_url, token, get_path, {"artifact_id": artifact_id})
    _expect(200, code, initial, "read pending Friday blueprint")
    assert initial["pending_clarifications"][0]["thread_id"] == thread_id
    assert (
        initial["pending_clarifications"][0]["question"]
        == "高三提分专项的学习权益校验应复用哪套既有接口？"
    )
    assert initial["pending_clarifications"][0]["options"][0]["id"] == "study-course"

    code, answer = _post(
        base_url,
        token,
        answer_path,
        {"thread_id": thread_id, "body": "复用 study-course 的现有权益接口。"},
    )
    _expect(200, code, answer, "submit exact human clarification answer")
    assert answer["thread_id"] == thread_id
    assert BlueprintThread.objects.get(id=thread_id).status != ThreadStatus.OPEN

    # The full research/LLM stage is intentionally absent in this isolated fixture.  Mimic
    # its canonical terminal state so the actual review endpoints can be tested without any
    # external provider or Feishu credential.
    Artifact.objects.filter(id=artifact_id).update(blueprint_status=BlueprintStatus.PENDING_REVIEW)
    code, rework = _post(
        base_url,
        token,
        rework_path,
        {
            "artifact_id": artifact_id,
            "comment": "请明确高三专项复用 study-course 权益接口的回退策略。",
            "rework_scope": "merge",
        },
    )
    _expect(200, code, rework, "request canonical Friday rework")
    assert rework["status"] == "rejected"
    code, rework_blocked = _post(base_url, token, tasks_path, {"technical_plan_id": plan_id})
    _expect(400, code, rework_blocked, "coding must be blocked after rework")
    assert rework_blocked["error_code"] == "blueprint_not_approved"

    # Seed the completed rework output only; all controller actions before and after this
    # point remain real authenticated HTTP requests against the canary server.
    Artifact.objects.filter(id=artifact_id).update(blueprint_status=BlueprintStatus.PENDING_REVIEW)
    BlueprintThread.objects.filter(artifact_id=artifact_id, status=ThreadStatus.OPEN).update(
        status=ThreadStatus.RESOLVED
    )
    code, review = _post(base_url, token, get_path, {"artifact_id": artifact_id})
    _expect(200, code, review, "read reviewable Friday blueprint")
    assert review["pending_clarifications"] == []

    code, stale = _post(
        base_url,
        token,
        approve_path,
        {
            "artifact_id": artifact_id,
            "artifact_version_id": review["artifact_version_id"],
            "content_hash": "0" * 64,
            "technical_plan_id": plan_id,
        },
    )
    _expect(409, code, stale, "reject stale approval snapshot")
    assert stale["error_code"] == "stale"

    code, approved = _post(
        base_url,
        token,
        approve_path,
        {
            "artifact_id": artifact_id,
            "artifact_version_id": review["artifact_version_id"],
            "content_hash": review["content_hash"],
            "technical_plan_id": plan_id,
        },
    )
    _expect(200, code, approved, "approve the exact displayed Friday snapshot")
    code, reread = _post(base_url, token, get_path, {"artifact_id": artifact_id})
    _expect(200, code, reread, "read confirmed Friday blueprint")
    assert approved["artifact_version_id"] == reread["artifact_version_id"]
    assert approved["content_hash"] == reread["content_hash"]
    assert approved["markdown"] == reread["markdown"]

    code, first_tasks = _post(base_url, token, tasks_path, {"technical_plan_id": plan_id})
    _expect(200, code, first_tasks, "release coding only after exact approval")
    code, second_tasks = _post(base_url, token, tasks_path, {"technical_plan_id": plan_id})
    _expect(200, code, second_tasks, "idempotent coding-task resume")
    assert [task["task_id"] for task in first_tasks["tasks"]] == [
        task["task_id"] for task in second_tasks["tasks"]
    ]
    assert McpWorkItemRepoTask.objects.filter(technical_plan_id=plan_id).count() == len(
        first_tasks["tasks"]
    )

    print(
        json.dumps(
            {
                "status": "passed",
                "fixture": "高三提分专项",
                "checks": [
                    "clarification_exactness",
                    "answer",
                    "request_changes",
                    "stale_cas",
                    "markdown_version_hash_parity",
                    "coding_gate",
                    "idempotent_resume",
                ],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
    django.setup()
    try:
        run(args.base_url.rstrip("/"))
    except Exception as exc:  # noqa: BLE001 -- emit a redacted, actionable canary failure
        print(f"CANARY_E2E_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
