from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from rest_framework.test import APIClient

from interactions.models import InteractionEvent, InteractionRun, ToolCallRecord

pytestmark = pytest.mark.django_db


def test_skill_workflow_reuses_interaction_run(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _plaintext = mcp_client
    monkeypatch.setattr(
        "codegraph.services.repo_router_v2.RepoRouterV2.route",
        AsyncMock(
            return_value=SimpleNamespace(
                candidates=[
                    SimpleNamespace(
                        repo_id=str(indexed_repository.id),
                        repo_name=indexed_repository.name,
                        score=0.91,
                        reasoning="名称和摘要命中",
                        confidence="high",
                        sub_project="",
                        sub_project_paths=[],
                        matched_node_paths=[],
                    )
                ],
                router_version="v2",
                auto_selected=True,
            )
        ),
    )

    first_response = client.post(
        "/api/mcp/tools/route_repositories/",
        {"query": "auth", "top_k": 3},
        format="json",
        HTTP_X_FRIDAY_SKILL_STEP="discover.route",
    )
    assert first_response.status_code == 200
    run_id = first_response.json()["run_id"]

    second_response = client.post(
        "/api/mcp/tools/get_repository/",
        {"repository_id": str(indexed_repository.id)},
        format="json",
        HTTP_X_FRIDAY_RUN_ID=run_id,
        HTTP_X_FRIDAY_SKILL_STEP="discover.describe",
    )

    assert second_response.status_code == 200
    assert second_response.json()["run_id"] == run_id
    assert InteractionRun.objects.filter(run_id=run_id).count() == 1
    assert list(
        ToolCallRecord.objects.filter(run__run_id=run_id)
        .order_by("created_at")
        .values_list("tool_name", flat=True)
    ) == ["route_repositories", "get_repository"]
    skill_steps = [
        event.payload["step"]
        for event in InteractionEvent.objects.filter(
            run__run_id=run_id,
            event_type=InteractionEvent.EventType.SKILL_STEP,
        ).order_by("seq")
    ]
    assert skill_steps == ["discover.route", "discover.describe"]
