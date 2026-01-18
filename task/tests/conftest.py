"""Test configuration and fixtures for Friday Task."""
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock
import pytest
@pytest.fixture
def temp_workspace:
 """创建临时工作空间。"""
 with tempfile.TemporaryDirectory as tmpdir:
 workspace = Path(tmpdir)
 # 创建一个简单的项目结构
 (workspace / "README.md").write_text("# Test Project\n\nA test project.")
 (workspace / "src").mkdir
 (workspace / "src" / "main.py").write_text(
 '"""Main module."""\n\ndef hello:\n return "Hello, World!"\n'
 )
 yield workspace
@pytest.fixture
def temp_session_dir:
 """创建临时会话目录。"""
 with tempfile.TemporaryDirectory as tmpdir:
 yield tmpdir
@pytest.fixture
def mock_config(temp_session_dir):
 """创建模拟的 TaskConfig。"""
 config = MagicMock
 config.task_id = "test-task-001"
 config.project_id = "test-project-001"
 config.task_title = "Test Task"
 config.task_description = "This is a test task for integration testing."
 config.task_mode = "plan"
 config.git_repo_url = "git@github.com:test/repo.git"
 config.git_branch = "main"
 config.git_new_branch = None
 config.session_dir = temp_session_dir
 config.claude_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
 config.claude_base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
 config.callback_url = ""
 config.callback_token = ""
 return config
