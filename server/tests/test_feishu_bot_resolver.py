"""Tests for Feishu bot thread and project resolvers."""

from __future__ import annotations

import pytest

from feishu.bot.project_resolver import ProjectResolver
from feishu.bot.thread_resolver import ThreadResolver
from feishu.models import FeishuBotMessage, FeishuBotThread
from projects.models import Space
from repositories.models import Repository


@pytest.mark.django_db(transaction=True)
class TestThreadResolver:
    async def test_quote_message_continues_existing_thread(self) -> None:
        thread = await FeishuBotThread.objects.acreate(chat_id="chat_1", root_message_id="root_1")
        await FeishuBotMessage.objects.acreate(
            message_id="root_1",
            thread=thread,
            chat_id="chat_1",
            sender_open_id="ou_1",
            message_type="text",
            normalized_text="旧问题",
            quote_message_id="",
            mentioned_bot=True,
            raw_payload={},
        )
        message = await FeishuBotMessage.objects.acreate(
            message_id="msg_2",
            thread=None,
            chat_id="chat_1",
            sender_open_id="ou_1",
            message_type="text",
            normalized_text="那这个呢",
            quote_message_id="root_1",
            mentioned_bot=True,
            raw_payload={},
        )

        resolution = await ThreadResolver().resolve(message)

        assert resolution.status == "continue"
        assert resolution.thread == thread

    async def test_explicit_new_question_creates_new_thread(self) -> None:
        message = await FeishuBotMessage.objects.acreate(
            message_id="msg_3",
            chat_id="chat_1",
            sender_open_id="ou_1",
            message_type="text",
            normalized_text="新问题：重新解释一下部署流程",
            quote_message_id="",
            mentioned_bot=True,
            raw_payload={},
        )

        resolution = await ThreadResolver().resolve(message)

        assert resolution.status == "new"

    async def test_ambiguous_short_message_requires_topic_clarification(self) -> None:
        await FeishuBotThread.objects.acreate(chat_id="chat_1", root_message_id="root_2")
        message = await FeishuBotMessage.objects.acreate(
            message_id="msg_4",
            chat_id="chat_1",
            sender_open_id="ou_1",
            message_type="text",
            normalized_text="这个呢",
            quote_message_id="",
            mentioned_bot=True,
            raw_payload={},
        )

        resolution = await ThreadResolver().resolve(message)

        assert resolution.status in {"continue", "awaiting_topic_clarification"}


@pytest.mark.django_db(transaction=True)
class TestProjectResolver:
    async def test_explicit_project_name_unique_match(self) -> None:
        repo = await Repository.objects.acreate(name="api-server", git_url="https://example.com/api.git")
        project = await Space.objects.acreate(name="Friday API", feishu_project_key="friday-api")
        await project.repositories.aadd(repo)
        message = await FeishuBotMessage.objects.acreate(
            message_id="msg_10",
            chat_id="chat_2",
            sender_open_id="ou_2",
            message_type="text",
            normalized_text="friday-api 这个项目的 SSE 为什么断了？",
            quote_message_id="",
            mentioned_bot=True,
            raw_payload={},
        )

        resolution = await ProjectResolver().resolve(message)

        assert resolution.status == "resolved"
        assert resolution.space == project

    async def test_ambiguous_repository_name_requests_clarification(self) -> None:
        repo1 = await Repository.objects.acreate(name="shared-repo", git_url="https://example.com/a.git")
        repo2 = await Repository.objects.acreate(name="shared-repo-ui", git_url="https://example.com/b.git")
        project1 = await Space.objects.acreate(name="Alpha")
        project2 = await Space.objects.acreate(name="Beta")
        await project1.repositories.aadd(repo1)
        await project2.repositories.aadd(repo2)
        message = await FeishuBotMessage.objects.acreate(
            message_id="msg_11",
            chat_id="chat_2",
            sender_open_id="ou_2",
            message_type="text",
            normalized_text="shared-repo 有个问题",
            quote_message_id="",
            mentioned_bot=True,
            raw_payload={},
        )

        resolution = await ProjectResolver().resolve(message)

        assert resolution.status == "awaiting_project_clarification"
        assert resolution.candidates

    async def test_recent_thread_project_can_be_reused(self) -> None:
        project = await Space.objects.acreate(name="Gamma")
        thread = await FeishuBotThread.objects.acreate(chat_id="chat_3", space=project)
        message = await FeishuBotMessage.objects.acreate(
            message_id="msg_12",
            thread=thread,
            chat_id="chat_3",
            sender_open_id="ou_3",
            message_type="text",
            normalized_text="继续看这个问题",
            quote_message_id="",
            mentioned_bot=True,
            raw_payload={},
        )

        resolution = await ProjectResolver().resolve(message, thread)

        assert resolution.status == "resolved"
        assert resolution.space == project
