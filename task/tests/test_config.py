"""Tests for config module."""

import pytest
from pydantic import ValidationError

from core import TaskConfig


class TestTaskConfig:
    """TaskConfig 测试。"""

    def test_config_from_params(self, temp_session_dir):
        """测试通过参数直接构建配置。"""
        config = TaskConfig(
            task_id="test-001",
            project_id="project-001",
            task_description="Test description",
            git_repo_url="git@github.com:test/repo.git",
            session_dir=temp_session_dir,
        )

        assert config.task_id == "test-001"
        assert config.project_id == "project-001"
        assert config.task_description == "Test description"
        assert config.task_mode == "plan"  # 默认值
        assert config.git_branch == "main"  # 默认值
        assert config.git_new_branch is None
        assert config.callback_url == ""  # 可选

    def test_config_required_fields(self):
        """测试必填字段验证。"""
        with pytest.raises(ValidationError):
            TaskConfig(
                # 缺少 task_id
                task_description="Test",
                git_repo_url="git@github.com:test/repo.git",
            )

    def test_config_optional_callback(self, temp_session_dir):
        """测试回调 URL 是可选的。"""
        config = TaskConfig(
            task_id="test-001",
            task_description="Test",
            git_repo_url="git@github.com:test/repo.git",
            session_dir=temp_session_dir,
        )

        # callback_url 应该是空字符串而不是引发错误
        assert config.callback_url == ""

    def test_config_new_branch(self, temp_session_dir):
        """测试 new_branch 参数。"""
        config = TaskConfig(
            task_id="test-001",
            task_description="Test",
            git_repo_url="git@github.com:test/repo.git",
            git_new_branch="friday/feature-test",
            session_dir=temp_session_dir,
        )

        assert config.git_new_branch == "friday/feature-test"

    def test_config_modes(self, temp_session_dir):
        """测试不同模式配置。"""
        for mode in ["plan", "execute"]:
            config = TaskConfig(
                task_id="test-001",
                task_description="Test",
                git_repo_url="git@github.com:test/repo.git",
                task_mode=mode,
                session_dir=temp_session_dir,
            )
            assert config.task_mode == mode

    def test_follow_openspec_default_false(self, temp_session_dir):
        """follow_openspec 默认 False（零回归 —— 未注入 env / 未传参）。"""
        config = TaskConfig(
            task_id="test-001",
            task_description="Test",
            git_repo_url="git@github.com:test/repo.git",
            session_dir=temp_session_dir,
        )
        assert config.follow_openspec is False

    def test_follow_openspec_param_true(self, temp_session_dir):
        """参数 follow_openspec=True → True。"""
        config = TaskConfig(
            task_id="test-001",
            task_description="Test",
            git_repo_url="git@github.com:test/repo.git",
            follow_openspec=True,
            session_dir=temp_session_dir,
        )
        assert config.follow_openspec is True

    def test_follow_openspec_env_mapping(self, temp_session_dir, monkeypatch):
        """env FRIDAY_TASK_FOLLOW_OPENSPEC=true → 经 env_prefix 自动映射 True。"""
        monkeypatch.setenv("FRIDAY_TASK_FOLLOW_OPENSPEC", "true")
        config = TaskConfig(
            task_id="test-001",
            task_description="Test",
            git_repo_url="git@github.com:test/repo.git",
            session_dir=temp_session_dir,
        )
        assert config.follow_openspec is True
