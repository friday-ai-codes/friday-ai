"""分支名生成与校验 service 测试。

覆盖：类型推断、短描述提取、分支名格式拼接、字符集/长度/保护分支校验、唯一性校验。
"""

import uuid
from datetime import timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chat.branch_service import (
    generate_branch_name,
    generate_short_description,
    infer_branch_type,
    validate_branch_name,
)

# ============================================================================
# TestBranchTypeInference — 分支类型推断
# ============================================================================


class TestBranchTypeInference:
    """测试 infer_branch_type 根据 tech_plan 关键词返回 feat/fix/chore。"""

    def test_fix_keywords(self) -> None:
        """tech_plan 包含修复相关关键词时返回 'fix'。"""
        assert infer_branch_type("修复用户登录崩溃问题") == "fix"
        assert infer_branch_type("fix the login bug") == "fix"
        assert infer_branch_type("紧急 bug 修复") == "fix"
        assert infer_branch_type("页面崩溃需要处理") == "fix"

    def test_chore_keywords(self) -> None:
        """tech_plan 包含运维/重构关键词时返回 'chore'。"""
        assert infer_branch_type("重构数据库查询逻辑") == "chore"
        assert infer_branch_type("清理无用代码") == "chore"
        assert infer_branch_type("迁移到新框架") == "chore"
        assert infer_branch_type("chore: update deps") == "chore"
        assert infer_branch_type("refactor the auth module") == "chore"

    def test_test_keywords(self) -> None:
        """tech_plan 包含测试相关关键词时返回 'test'。"""
        assert infer_branch_type("补充单元测试") == "test"
        assert infer_branch_type("add e2e tests") == "test"
        assert infer_branch_type("完善用例覆盖") == "test"

    def test_default_feat(self) -> None:
        """不含 fix/chore/test 关键词时返回 'feat'。"""
        assert infer_branch_type("实现用户认证模块") == "feat"
        assert infer_branch_type("add new dashboard page") == "feat"
        assert infer_branch_type("新增导出功能") == "feat"

    def test_case_insensitive(self) -> None:
        """大小写混合仍能正确匹配。"""
        assert infer_branch_type("BUG in the system") == "fix"
        assert infer_branch_type("Fix the issue") == "fix"
        assert infer_branch_type("REFACTOR module") == "chore"
        assert infer_branch_type("Chore: cleanup") == "chore"


# ============================================================================
# TestShortDescription — 短描述提取
# ============================================================================


class TestShortDescription:
    """测试 generate_short_description 规则提取简短名称（中文优先，<=10 字）。"""

    def test_chinese_extraction(self) -> None:
        """中文方案提取首行核心描述，去空格、<=10 字。"""
        result = generate_short_description("实现 用户登录 模块")
        assert " " not in result
        assert len(result) <= 10
        assert "用户登录" in result

    def test_strips_markdown_heading(self) -> None:
        """剥离 markdown 标题标记，仅保留正文。"""
        result = generate_short_description("# 修复购物车结算异常\n详细说明……")
        assert not result.startswith("#")
        assert " " not in result
        assert len(result) <= 10

    def test_max_length(self) -> None:
        """超过 10 字时按字符截断。"""
        result = generate_short_description("一二三四五六七八九十十一十二")
        assert len(result) <= 10

    def test_empty_fallback(self) -> None:
        """空内容返回 'task' 兜底；纯中文返回中文简短名（不再 task）。"""
        assert generate_short_description("") == "task"
        assert generate_short_description("这是一个纯中文描述") == "这是一个纯中文描述"


# ============================================================================
# TestBranchNameGeneration — 分支名格式拼接
# ============================================================================


class TestBranchNameGeneration:
    """测试 generate_branch_name 拼接 {type}/{yymmdd}.{desc} 格式分支名。"""

    def test_format(self) -> None:
        """返回 '{type}/{yymmdd}.{desc}' 格式（支持中文 desc）。"""
        import re

        result = generate_branch_name("feat", "用户登录")
        assert re.fullmatch(r"feat/\d{6}\.用户登录", result), f"格式不匹配: {result}"

    def test_date_utc(self) -> None:
        """使用 UTC 日期（6 位 yymmdd）+ type/ 前缀。"""
        from datetime import datetime as real_datetime

        fixed_dt = real_datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc)
        with patch("chat.branch_service.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_dt
            mock_dt.side_effect = lambda *a, **kw: real_datetime(*a, **kw)
            result = generate_branch_name("fix", "登录崩溃")
            mock_dt.now.assert_called_once_with(timezone.utc)
            assert result == "fix/260409.登录崩溃"


# ============================================================================
# TestBranchValidation — 分支名校验（不含唯一性）
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestBranchValidation:
    """测试 validate_branch_name 多层校验逻辑。"""

    @pytest.fixture
    def dummy_repo_id(self):
        """提供一个虚拟的 repository UUID。"""

        return uuid.uuid4()

    @pytest.mark.asyncio
    async def test_valid_name(self, dummy_repo_id) -> None:
        """合法分支名通过校验。"""
        result = await validate_branch_name(
            "feat20260409.add-user-auth", dummy_repo_id
        )
        assert result.valid is True
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_invalid_chars(self, dummy_repo_id) -> None:
        """非法字符返回错误。"""
        result = await validate_branch_name("feat 2026/test@", dummy_repo_id)
        assert result.valid is False
        assert any("字符" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_double_dot(self, dummy_repo_id) -> None:
        """双点 '..' 返回错误。"""
        result = await validate_branch_name("feat..test", dummy_repo_id)
        assert result.valid is False
        assert any(".." in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_starts_with_dot(self, dummy_repo_id) -> None:
        """以 '.' 开头返回错误。"""
        result = await validate_branch_name(".feat-test", dummy_repo_id)
        assert result.valid is False

    @pytest.mark.asyncio
    async def test_ends_with_slash(self, dummy_repo_id) -> None:
        """以 '/' 结尾返回错误。"""
        result = await validate_branch_name("feat-test/", dummy_repo_id)
        assert result.valid is False

    @pytest.mark.asyncio
    async def test_ends_with_lock(self, dummy_repo_id) -> None:
        """以 '.lock' 结尾返回错误。"""
        result = await validate_branch_name("feat-test.lock", dummy_repo_id)
        assert result.valid is False
        assert any(".lock" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_too_long(self, dummy_repo_id) -> None:
        """256 字节分支名返回错误。"""
        long_name = "a" * 256
        result = await validate_branch_name(long_name, dummy_repo_id)
        assert result.valid is False
        assert any("长度" in e or "255" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_exactly_255_bytes(self, dummy_repo_id) -> None:
        """255 字节分支名通过校验。"""
        name_255 = "a" * 255
        result = await validate_branch_name(name_255, dummy_repo_id)
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_protected_main(self, dummy_repo_id) -> None:
        """'main' 返回保护分支错误。"""
        result = await validate_branch_name("main", dummy_repo_id)
        assert result.valid is False
        assert any("保护" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_protected_master(self, dummy_repo_id) -> None:
        """'master' 返回保护分支错误。"""
        result = await validate_branch_name("master", dummy_repo_id)
        assert result.valid is False
        assert any("保护" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_protected_develop(self, dummy_repo_id) -> None:
        """'develop' 返回保护分支错误。"""
        result = await validate_branch_name("develop", dummy_repo_id)
        assert result.valid is False
        assert any("保护" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_protected_release_pattern(self, dummy_repo_id) -> None:
        """'release/1.0' 返回保护分支错误。"""
        result = await validate_branch_name("release/1.0", dummy_repo_id)
        assert result.valid is False
        assert any("保护" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_protected_hotfix_pattern(self, dummy_repo_id) -> None:
        """'hotfix/urgent' 返回保护分支错误。"""
        result = await validate_branch_name("hotfix/urgent", dummy_repo_id)
        assert result.valid is False
        assert any("保护" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_empty_name(self, dummy_repo_id) -> None:
        """空分支名返回错误。"""
        result = await validate_branch_name("", dummy_repo_id)
        assert result.valid is False
        assert any("空" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_multiple_errors(self, dummy_repo_id) -> None:
        """同时违反多条规则时返回多个错误。"""
        # ".." 同时违反 "以 . 开头" 和 "包含 .." 两条规则
        result = await validate_branch_name("..lock", dummy_repo_id)
        assert result.valid is False
        assert len(result.errors) >= 2


# ============================================================================
# TestGitPlatformBranchExists — GitPlatformClient.branch_exists
# ============================================================================


class TestGitPlatformBranchExists:
    """测试 GitHub/GitLab 客户端的 branch_exists 实现。"""

    @pytest.mark.asyncio
    async def test_github_branch_exists_true(self) -> None:
        """mock PyGithub repo.get_branch 返回成功 -> True。"""
        from services.git_platform.github_client import GitHubClient

        client = GitHubClient(token="fake", owner="test", repo="repo")
        mock_repo = MagicMock()
        mock_repo.get_branch.return_value = MagicMock()  # 成功返回
        with patch.object(client, "_get_repo", return_value=mock_repo):
            result = await client.branch_exists("feat20260409.test")
        assert result is True
        mock_repo.get_branch.assert_called_once_with("feat20260409.test")

    @pytest.mark.asyncio
    async def test_github_branch_not_exists(self) -> None:
        """mock PyGithub repo.get_branch 抛 GithubException 404 -> False。"""
        from github import GithubException

        from services.git_platform.github_client import GitHubClient

        client = GitHubClient(token="fake", owner="test", repo="repo")
        mock_repo = MagicMock()
        mock_repo.get_branch.side_effect = GithubException(
            404, {"message": "Branch not found"}, None
        )
        with patch.object(client, "_get_repo", return_value=mock_repo):
            result = await client.branch_exists("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_gitlab_branch_exists_true(self) -> None:
        """mock python-gitlab project.branches.get 返回成功 -> True。"""
        from services.git_platform.gitlab_client import GitLabClient

        client = GitLabClient(
            base_url="https://gitlab.com", token="fake", project_path="ns/proj"
        )
        mock_project = MagicMock()
        mock_project.branches.get.return_value = MagicMock()
        with patch.object(client, "_get_project", return_value=mock_project):
            result = await client.branch_exists("feat20260409.test")
        assert result is True
        mock_project.branches.get.assert_called_once_with("feat20260409.test")

    @pytest.mark.asyncio
    async def test_gitlab_branch_not_exists(self) -> None:
        """mock python-gitlab project.branches.get 抛 GitlabGetError -> False。"""
        import gitlab.exceptions

        from services.git_platform.gitlab_client import GitLabClient

        client = GitLabClient(
            base_url="https://gitlab.com", token="fake", project_path="ns/proj"
        )
        mock_project = MagicMock()
        mock_project.branches.get.side_effect = gitlab.exceptions.GitlabGetError(
            "404 Branch Not Found"
        )
        with patch.object(client, "_get_project", return_value=mock_project):
            result = await client.branch_exists("nonexistent")
        assert result is False


# ============================================================================
# TestBranchUniqueness — 唯一性校验（DB + remote）
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestBranchUniqueness:
    """测试 validate_branch_name 的 DB 活跃会话 + remote 双重唯一性校验。"""

    @pytest.fixture
    def repo_id(self, repository):
        """返回测试仓库的 UUID。"""
        return repository.id

    @pytest.fixture
    def _create_session(self, repository, db):
        """工厂 fixture：创建带指定分支名和状态的 CodingSession（同步）。"""
        from chat.models import CodingSession, Conversation
        from projects.models import Project

        # 获取或创建 project
        project = Project.objects.filter(repositories=repository).first()
        if not project:
            project = Project.objects.create(
                name="Test Project",
                feishu_project_key="test-key",
            )
            project.repositories.add(repository)

        conversation = Conversation.objects.create(
            project=project,
            title="test conv",
        )

        def _factory(branch_name: str, status: str) -> CodingSession:
            return CodingSession.objects.create(
                conversation=conversation,
                repository=repository,
                branch_name=branch_name,
                status=status,
                tech_plan="test plan",
            )

        return _factory

    @pytest.mark.asyncio
    async def test_db_duplicate_active(self, repo_id, _create_session) -> None:
        """DB 中有同名 running 状态的 CodingSession -> 返回错误。"""
        from asgiref.sync import sync_to_async

        await sync_to_async(_create_session)("feat20260409.dup-branch", "running")
        result = await validate_branch_name("feat20260409.dup-branch", repo_id)
        assert result.valid is False
        assert any("已被" in e or "使用" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_db_duplicate_completed_ok(self, repo_id, _create_session) -> None:
        """DB 中有同名 completed 状态 -> 不冲突，通过。"""
        from asgiref.sync import sync_to_async

        await sync_to_async(_create_session)(
            "feat20260409.completed-branch", "completed"
        )
        result = await validate_branch_name(
            "feat20260409.completed-branch", repo_id
        )
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_remote_exists(self, repo_id) -> None:
        """mock git_client.branch_exists 返回 True -> 返回错误。"""
        mock_client = AsyncMock()
        mock_client.branch_exists.return_value = True
        result = await validate_branch_name(
            "feat20260409.remote-dup", repo_id, git_client=mock_client
        )
        assert result.valid is False
        assert any("远程" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_remote_not_exists(self, repo_id) -> None:
        """mock git_client.branch_exists 返回 False -> 通过。"""
        mock_client = AsyncMock()
        mock_client.branch_exists.return_value = False
        result = await validate_branch_name(
            "feat20260409.remote-ok", repo_id, git_client=mock_client
        )
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_no_git_client_skip_remote(self, repo_id) -> None:
        """git_client=None 时跳过 remote 校验，仅 DB 校验。"""
        result = await validate_branch_name(
            "feat20260409.no-client", repo_id, git_client=None
        )
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_exclude_session_id_skips_self(
        self, repo_id, _create_session
    ) -> None:
        """exclude_session_id 应把指定 session 从 DB 唯一性比对里剔除。

        回归 v18.2 bug：confirm 流程在 dispatch_coding_task 里二次校验
        coding_session.branch_name，此时 session 自己已经是 draft/confirmed
        active 状态 —— 不传 exclude_session_id 会撞自己报"已被活跃的编码会话使用"。
        """
        from asgiref.sync import sync_to_async

        session = await sync_to_async(_create_session)(
            "feat20260409.self-branch", "draft"
        )
        # 不传 exclude_session_id → 撞自己
        result_without = await validate_branch_name(
            "feat20260409.self-branch", repo_id
        )
        assert result_without.valid is False
        # 传 exclude_session_id → 通过
        result_with = await validate_branch_name(
            "feat20260409.self-branch",
            repo_id,
            exclude_session_id=session.id,
        )
        assert result_with.valid is True

    @pytest.mark.asyncio
    async def test_exclude_session_id_still_catches_others(
        self, repo_id, _create_session
    ) -> None:
        """exclude_session_id 仅剔除指定 session，其它同名 active session 仍要拦截。"""
        from asgiref.sync import sync_to_async

        self_session = await sync_to_async(_create_session)(
            "feat20260409.other-conflict", "draft"
        )
        await sync_to_async(_create_session)(
            "feat20260409.other-conflict", "running"
        )
        result = await validate_branch_name(
            "feat20260409.other-conflict",
            repo_id,
            exclude_session_id=self_session.id,
        )
        assert result.valid is False
        assert any("已被" in e or "使用" in e for e in result.errors)
