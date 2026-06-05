"""initial implementation plan Task 1: Repository AI summary 模型层测试。

测试 Repository 模型扩展字段、AISummaryStatus 枚举、
SubAgentSession.TaskType.REPO_SUMMARY、RepositorySerializer 新字段、
以及 0003 prompt 种子 migration。
"""

import pytest
from django.apps import apps

from repositories.models import AISummaryStatus, Repository
from repositories.serializers import RepositorySerializer
from subagent.models import SubAgentSession


@pytest.mark.django_db
class TestRepositoryAISummaryFields:
    """Test 1 & 2: Repository 模型 AI summary 字段。"""

    def test_repository_has_ai_summary_fields(self, repository: Repository) -> None:
        """Repository 实例有 ai_summary / ai_summary_status / ai_summary_generated_at / ai_summary_error 四个字段。"""
        assert hasattr(repository, "ai_summary")
        assert hasattr(repository, "ai_summary_status")
        assert hasattr(repository, "ai_summary_generated_at")
        assert hasattr(repository, "ai_summary_error")

    def test_ai_summary_status_default_is_not_started(self, repository: Repository) -> None:
        """AISummaryStatus.NOT_STARTED 是 ai_summary_status 的默认值。"""
        assert repository.ai_summary_status == AISummaryStatus.NOT_STARTED
        assert repository.ai_summary_status == "not_started"

    def test_ai_summary_default_values(self, repository: Repository) -> None:
        """新建仓库的 AI summary 字段都有合理的默认值。"""
        assert repository.ai_summary is None
        assert repository.ai_summary_generated_at is None
        assert repository.ai_summary_error == ""


@pytest.mark.django_db
class TestSubAgentSessionRepoSummaryType:
    """Test 3: SubAgentSession.TaskType.REPO_SUMMARY 枚举。"""

    def test_repo_summary_task_type_exists(self) -> None:
        """SubAgentSession.TaskType.REPO_SUMMARY 枚举值为 'repo_summary'。"""
        assert SubAgentSession.TaskType.REPO_SUMMARY == "repo_summary"
        assert SubAgentSession.TaskType.REPO_SUMMARY.label == "Repository Summary"


@pytest.mark.django_db
class TestRepositorySerializerAISummaryFields:
    """Test 4: RepositorySerializer 输出包含 AI summary 字段。"""

    def test_serializer_includes_ai_summary_fields(self, repository: Repository) -> None:
        """RepositorySerializer 输出包含 ai_summary / ai_summary_status / ai_summary_generated_at / ai_summary_error。"""
        serializer = RepositorySerializer(repository)
        data = serializer.data
        assert "ai_summary" in data
        assert "ai_summary_status" in data
        assert "ai_summary_generated_at" in data
        assert "ai_summary_error" in data

    def test_ai_summary_fields_are_read_only(self) -> None:
        """AI summary 四个字段在 serializer 中是只读的。"""
        read_only = RepositorySerializer.Meta.read_only_fields
        assert "ai_summary" in read_only
        assert "ai_summary_status" in read_only
        assert "ai_summary_generated_at" in read_only
        assert "ai_summary_error" in read_only


@pytest.mark.django_db
class TestPromptSeedMigration:
    """Test 5: 0003 prompt 种子 migration 的数据。"""

    def test_repo_summary_prompt_seed_exists(self) -> None:
        """repo.summary_generator prompt 种子已入库，slug/category/scope 正确。"""
        Prompt = apps.get_model("prompts", "Prompt")
        prompt = Prompt.objects.filter(
            slug="repo.summary_generator",
            scope="system",
        ).first()
        assert prompt is not None, "repo.summary_generator prompt 种子未找到"
        assert prompt.category == "repo_analysis"
        assert prompt.is_builtin is True

    def test_repo_summary_prompt_has_active_version(self) -> None:
        """repo.summary_generator 有活跃版本且 body 非空。"""
        Prompt = apps.get_model("prompts", "Prompt")
        prompt = Prompt.objects.filter(
            slug="repo.summary_generator",
            scope="system",
        ).first()
        assert prompt is not None
        assert prompt.active_version is not None
        assert len(prompt.active_version.body) > 0
