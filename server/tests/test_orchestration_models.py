"""OrchestrationRun Django 模型单元测试。"""

from __future__ import annotations

import uuid

import pytest

from chat.models import Conversation
from orchestration.models import OrchestrationRun
from orchestration.state import RunPhase
from projects.models import Space


@pytest.fixture
def _project(db: None) -> Space:
    return Space.objects.create(name="Test Space")


@pytest.fixture
def conversation(_project: Space) -> Conversation:
    return Conversation.objects.create(space=_project, title="测试对话")


@pytest.mark.django_db
class TestOrchestrationRunCreation:
    def test_run_creation(self, conversation: Conversation) -> None:
        run = OrchestrationRun.objects.create(
            conversation=conversation,
            thread_id=str(conversation.id),
        )
        assert run.pk is not None
        assert isinstance(run.run_id, uuid.UUID)

    def test_run_id_is_unique(self, conversation: Conversation) -> None:
        run1 = OrchestrationRun.objects.create(
            conversation=conversation,
            thread_id=str(conversation.id),
        )
        run2 = OrchestrationRun.objects.create(
            conversation=conversation,
            thread_id=str(conversation.id),
        )
        assert run1.run_id != run2.run_id

    def test_thread_id_binding(self, conversation: Conversation) -> None:
        run = OrchestrationRun.objects.create(
            conversation=conversation,
            thread_id=str(conversation.id),
        )
        assert run.thread_id == str(conversation.id)

    def test_conversation_fk(self, conversation: Conversation) -> None:
        run = OrchestrationRun.objects.create(
            conversation=conversation,
            thread_id=str(conversation.id),
        )
        assert run.conversation_id == conversation.id
        assert conversation.orchestration_runs.count() == 1


@pytest.mark.django_db
class TestOrchestrationRunDefaults:
    def test_default_status(self, conversation: Conversation) -> None:
        run = OrchestrationRun.objects.create(
            conversation=conversation,
            thread_id=str(conversation.id),
        )
        assert run.status == OrchestrationRun.Status.PENDING
        assert run.status == "pending"

    def test_default_phase(self, conversation: Conversation) -> None:
        run = OrchestrationRun.objects.create(
            conversation=conversation,
            thread_id=str(conversation.id),
        )
        assert run.phase == OrchestrationRun.Phase.PLANNING
        assert run.phase == "planning"

    def test_default_checkpoint_id(self, conversation: Conversation) -> None:
        run = OrchestrationRun.objects.create(
            conversation=conversation,
            thread_id=str(conversation.id),
        )
        assert run.checkpoint_id == ""

    def test_default_metadata(self, conversation: Conversation) -> None:
        run = OrchestrationRun.objects.create(
            conversation=conversation,
            thread_id=str(conversation.id),
        )
        assert run.metadata == {}


@pytest.mark.django_db
class TestOrchestrationRunQueryset:
    def test_ordering_by_created_at_desc(self, conversation: Conversation) -> None:
        run1 = OrchestrationRun.objects.create(
            conversation=conversation,
            thread_id=str(conversation.id),
        )
        run2 = OrchestrationRun.objects.create(
            conversation=conversation,
            thread_id=str(conversation.id),
        )
        runs = list(OrchestrationRun.objects.all())
        assert runs[0].pk == run2.pk
        assert runs[1].pk == run1.pk

    def test_multiple_runs_per_conversation(self, conversation: Conversation) -> None:
        for _ in range(3):
            OrchestrationRun.objects.create(
                conversation=conversation,
                thread_id=str(conversation.id),
            )
        assert conversation.orchestration_runs.count() == 3


@pytest.mark.django_db
class TestOrchestrationRunProjection:
    def test_projection_from_workflow_state(self, conversation: Conversation) -> None:
        """可从 WorkflowState 的 phase 值更新 OrchestrationRun。"""
        run = OrchestrationRun.objects.create(
            conversation=conversation,
            thread_id=str(conversation.id),
        )
        state_phase = RunPhase.EXECUTING.value
        run.phase = state_phase
        run.status = OrchestrationRun.Status.RUNNING
        run.save()

        run.refresh_from_db()
        assert run.phase == "executing"
        assert run.status == "running"

    def test_str_representation(self, conversation: Conversation) -> None:
        run = OrchestrationRun.objects.create(
            conversation=conversation,
            thread_id=str(conversation.id),
        )
        s = str(run)
        assert "OrchestrationRun(" in s
        assert "pending" in s


@pytest.mark.django_db
class TestOrchestrationRunChoices:
    def test_status_choices_count(self) -> None:
        assert len(OrchestrationRun.Status.choices) == 6

    def test_phase_choices_count(self) -> None:
        assert len(OrchestrationRun.Phase.choices) == 7

    def test_status_values(self) -> None:
        expected = {"pending", "running", "waiting", "interrupted", "completed", "error"}
        assert {v for v, _ in OrchestrationRun.Status.choices} == expected

    def test_phase_values(self) -> None:
        expected = {"planning", "executing", "waiting", "finalizing", "completed", "error"}
        expected.add("waiting_clarification")
        assert {v for v, _ in OrchestrationRun.Phase.choices} == expected
