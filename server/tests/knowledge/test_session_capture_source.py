"""session_capture RAG 摄取 source 守护测试（EVAL-03，143-01 RED）。

镜像 ``test_project_memory_source``：medium/high 精华 → KnowledgeEntity(document,
source_kind=session_capture, origin=MCP) ；low / 缺失 / 未完成评估返回空。无仓库无项目
的中高价值 Capture 仍产事件，避免 Phase 144 读侧过滤被误当成静默丢失。
"""

from __future__ import annotations

import json
import uuid

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from initiatives.models import ProjectMemory, SessionCapture
from initiatives.services import CaptureService, ProjectService
from initiatives.services.knowledge_graph import project_node_id
from knowledge.ingestion import IngestionRequest
from knowledge.models import EdgeRelation, EntityKind, EntityOrigin
from knowledge.sources import get_normalizer
from projects.models import Space
from repositories.models import Repository

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()

_FORBIDDEN_PAYLOAD_KEYS = {"question", "answer", "transcript", "distilled_essence", "essence"}
_SECRET = "sk-ant-abcdefghij1234567890"


@sync_to_async
def _make_user(prefix: str):
    suffix = uuid.uuid4().hex[:8]
    return User.objects.create_user(username=f"{prefix}-{suffix}", password="x")


async def _make_project_with_member(*, name: str = "Capture Source"):
    owner = await _make_user("source-owner")
    suffix = uuid.uuid4().hex[:8]
    space = await Space.objects.acreate(name=f"Source Space {suffix}")
    project, _ = await ProjectService().create(
        space=space,
        name=f"{name} {suffix}",
        feishu_project_key=f"src-{suffix}",
        created_by=owner,
    )
    return space, project, owner


async def _persist(actor, **overrides):
    params = {
        "question": "UNIQUE_QUESTION_TOKEN_CAPTURE",
        "answer": "UNIQUE_ANSWER_TOKEN_CAPTURE",
        "session_id": f"session-source-{uuid.uuid4().hex[:8]}",
        "actor": actor,
    }
    params.update(overrides)
    return await CaptureService().persist(**params)


async def _ready_for_ingest(capture_id, *, value_tier: str, distilled_essence: str):
    service = CaptureService()
    claimed = await service.claim_evaluation(capture_id)
    assert claimed is not None
    return await service.record_evaluation(
        capture_id,
        value_tier=value_tier,
        distilled_essence=distilled_essence,
    )


async def _normalize(source_id: str):
    normalize = get_normalizer("session_capture")
    return await normalize(IngestionRequest("session_capture", source_id, "test"))


@pytest.mark.parametrize("tier", ["medium", "high"])
async def test_session_capture_normalize_unanchored_medium_high_keeps_event(tier: str) -> None:
    actor = await _make_user(f"unanchored-{tier}")
    result = await _persist(actor)
    essence = f"{tier} 可独立召回的根因、方案与验证证据"
    await _ready_for_ingest(result.capture.id, value_tier=tier, distilled_essence=essence)

    events = await _normalize(str(result.capture.id))

    assert len(events) == 1
    event = events[0]
    assert event.kind == EntityKind.DOCUMENT
    assert event.origin == EntityOrigin.MCP
    assert event.source_kind == "session_capture"
    assert event.source_id == str(result.capture.id)
    assert event.content == essence
    assert "UNIQUE_QUESTION_TOKEN_CAPTURE" not in event.content
    assert "UNIQUE_ANSWER_TOKEN_CAPTURE" not in event.content
    assert event.repository_id is None
    assert event.space_id is None
    assert event.edges == ()
    assert set(event.payload) == {"capture_id", "value_tier", "repository_id", "project_id"}
    assert event.payload["capture_id"] == str(result.capture.id)
    assert event.payload["value_tier"] == tier
    assert event.payload["repository_id"] is None
    assert event.payload["project_id"] is None
    assert not (_FORBIDDEN_PAYLOAD_KEYS & set(event.payload))
    dumped = json.dumps(event.payload, ensure_ascii=False)
    assert "UNIQUE_QUESTION_TOKEN_CAPTURE" not in dumped
    assert essence not in dumped


async def test_session_capture_normalize_redacts_essence_only() -> None:
    actor = await _make_user("essence-redact")
    result = await _persist(actor)
    essence = f"决策：token={_SECRET}，用连接池"
    await _ready_for_ingest(
        result.capture.id,
        value_tier="high",
        distilled_essence=essence,
    )

    events = await _normalize(str(result.capture.id))

    assert len(events) == 1
    event = events[0]
    assert _SECRET not in event.content
    assert "REDACTED" in event.content
    assert "用连接池" in event.content
    assert "UNIQUE_QUESTION_TOKEN_CAPTURE" not in event.content
    assert "UNIQUE_ANSWER_TOKEN_CAPTURE" not in event.content
    assert _SECRET not in json.dumps(event.payload, ensure_ascii=False)


async def test_session_capture_normalize_project_adds_references_edge() -> None:
    _space, project, actor = await _make_project_with_member()
    result = await _persist(actor, project_id=project.id)
    await _ready_for_ingest(
        result.capture.id,
        value_tier="medium",
        distilled_essence="带项目锚的可检索精华",
    )

    events = await _normalize(str(result.capture.id))

    assert len(events) == 1
    event = events[0]
    assert event.space_id == str(project.space_id)
    assert event.payload["project_id"] == str(project.id)
    assert event.repository_id is None
    assert len(event.edges) == 1
    edge = event.edges[0]
    assert edge.relation == EdgeRelation.REFERENCES
    assert edge.target_entity_id == project_node_id(project.id)


async def test_session_capture_normalize_repository_scalar_without_project() -> None:
    space, _project, actor = await _make_project_with_member(name="Repo Only")
    repository = await Repository.objects.acreate(
        name=f"src-repo-{uuid.uuid4().hex[:8]}",
        git_url="https://git.example.com/team/source-only.git",
    )
    await space.repositories.aadd(repository)
    result = await _persist(actor, repository_id=repository.id)
    await _ready_for_ingest(
        result.capture.id,
        value_tier="high",
        distilled_essence="仓级精华仍可入统一知识库",
    )

    events = await _normalize(str(result.capture.id))

    assert len(events) == 1
    event = events[0]
    assert event.repository_id == str(repository.id)
    assert event.space_id is None
    assert event.payload["repository_id"] == str(repository.id)
    assert event.payload["project_id"] is None
    assert event.edges == ()


async def test_session_capture_normalize_low_returns_empty() -> None:
    actor = await _make_user("low-skip")
    result = await _persist(actor)
    await _ready_for_ingest(
        result.capture.id,
        value_tier="low",
        distilled_essence="低价值精华不得入向量",
    )
    before = await ProjectMemory.objects.acount()

    events = await _normalize(str(result.capture.id))

    assert events == []
    assert await ProjectMemory.objects.acount() == before
    assert await SessionCapture.objects.filter(pk=result.capture.id).aexists()


async def test_session_capture_normalize_missing_returns_empty() -> None:
    events = await _normalize(str(uuid.uuid4()))
    assert events == []


async def test_session_capture_normalize_incomplete_eval_returns_empty() -> None:
    actor = await _make_user("pending-skip")
    result = await _persist(actor)

    events = await _normalize(str(result.capture.id))

    assert events == []
