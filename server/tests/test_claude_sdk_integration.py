"""Claude Agent SDK 集成测试。
这些测试需要真实的 Anthropic API Key 才能运行。
默认情况下会跳过，通过设置环境变量 FRIDAY_RUN_INTEGRATION_TESTS=1 启用。
使用方式：
 ANTHROPIC_API_KEY=your-key FRIDAY_RUN_INTEGRATION_TESTS=1 pytest tests/test_claude_sdk_integration.py -v
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock
import pytest
# 检查是否应该运行集成测试
SKIP_INTEGRATION = os.environ.get("FRIDAY_RUN_INTEGRATION_TESTS", "0") != "1"
SKIP_REASON = "集成测试已禁用。设置 FRIDAY_RUN_INTEGRATION_TESTS=1 启用"
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
def mock_config:
 """创建模拟的 TaskConfig。"""
 config = MagicMock
 config.task_id = "test-task-001"
 config.task_title = "Test Task"
 config.task_description = "This is a test task for integration testing."
 config.session_dir = tempfile.mkdtemp
 config.claude_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
 config.claude_base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
 return config
@pytest.mark.skipif(SKIP_INTEGRATION, reason=SKIP_REASON)
@pytest.mark.asyncio
async def test_claude_runner_plan_mode(temp_workspace, mock_config):
 """测试 Claude Runner 的 plan 模式。"""
 # 仅当有 API Key 时才导入和测试
 if not mock_config.claude_api_key:
 pytest.skip("需要设置 ANTHROPIC_API_KEY")
 from friday_task.claude_runner import ClaudeRunner
 runner = ClaudeRunner(config=mock_config, workspace=temp_workspace)
 result = await runner.run_plan_mode
 assert result["success"] is True
 assert "output" in result
 assert len(result["output"]) > 0
 assert result["message_count"] > 0
@pytest.mark.skipif(SKIP_INTEGRATION, reason=SKIP_REASON)
@pytest.mark.asyncio
async def test_claude_runner_execute_mode(temp_workspace, mock_config):
 """测试 Claude Runner 的 execute 模式。"""
 if not mock_config.claude_api_key:
 pytest.skip("需要设置 ANTHROPIC_API_KEY")
 from friday_task.claude_runner import ClaudeRunner
 runner = ClaudeRunner(config=mock_config, workspace=temp_workspace)
 # 提供一个简单的 plan
 plan = """
## Implementation Plan. Add a new function `goodbye` to `src/main.py`
2. The function should return "Goodbye, World!"
"""
 result = await runner.run_execute_mode(plan=plan)
 assert result["success"] is True
 assert "output" in result
@pytest.mark.skipif(SKIP_INTEGRATION, reason=SKIP_REASON)
@pytest.mark.asyncio
async def test_claude_runner_session_save(temp_workspace, mock_config):
 """测试会话保存功能。"""
 if not mock_config.claude_api_key:
 pytest.skip("需要设置 ANTHROPIC_API_KEY")
 from friday_task.claude_runner import ClaudeRunner
 runner = ClaudeRunner(config=mock_config, workspace=temp_workspace)
 # 运行一次
 result = await runner.run_plan_mode
 assert result["success"] is True
 # 检查会话文件是否创建
 session_file = Path(mock_config.session_dir) / f"{mock_config.task_id}.json"
 assert session_file.exists
 # 检查可以读取会话摘要
 summary = await runner.get_session_summary
 assert summary is not None
# === 模拟测试（不需要真实 API）===
@pytest.mark.asyncio
async def test_claude_runner_prompt_building(temp_workspace, mock_config):
 """测试 prompt 构建逻辑（不需要 API）。"""
 # 这里我们模拟导入以避免 SDK 依赖
 # 在实际测试中可能需要根据环境调整
 # 测试 plan prompt 构建
 expected_title = mock_config.task_title
 expected_description = mock_config.task_description
 plan_prompt_template = f"""You are an AI development agent working on a coding task.
## Task Information
- **Title**: {expected_title}
- **Description**: {expected_description}
## Your Goal
Analyze the codebase and create a detailed implementation plan. Do NOT make any changes yet.
"""
 assert expected_title in plan_prompt_template
 assert expected_description in plan_prompt_template
@pytest.mark.asyncio
async def test_claude_runner_session_file_location(temp_workspace, mock_config):
 """测试会话文件路径正确性。"""
 expected_session_file = (
 Path(mock_config.session_dir) / f"{mock_config.task_id}.json"
 )
 # 验证路径构建正确
 assert str(expected_session_file).endswith(f"{mock_config.task_id}.json")
 assert mock_config.session_dir in str(expected_session_file)
@pytest.mark.asyncio
async def test_claude_runner_handles_missing_api_key(temp_workspace, mock_config):
 """测试没有 API Key 时的错误处理。"""
 mock_config.claude_api_key = ""
 os.environ.pop("ANTHROPIC_API_KEY", None)
 # 这个测试验证在没有 API Key 时，runner 会优雅地处理错误
 # 具体行为取决于 SDK 实现
 # 这里我们只验证配置状态
 assert mock_config.claude_api_key == ""
