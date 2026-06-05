"""Tests for CLI module."""

from click.testing import CliRunner

from cli import main


class TestCLI:
    """CLI 基础功能测试。"""

    def test_cli_help(self):
        """测试 --help 选项。"""
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Friday Task" in result.output

    def test_cli_version(self):
        """测试 --version 选项。"""
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_plan_help(self):
        """测试 plan 子命令帮助。"""
        runner = CliRunner()
        result = runner.invoke(main, ["plan", "--help"])
        assert result.exit_code == 0
        assert "--git-url" in result.output
        assert "--description" in result.output
        assert "--branch" in result.output

    def test_exec_help(self):
        """测试 exec 子命令帮助。"""
        runner = CliRunner()
        result = runner.invoke(main, ["exec", "--help"])
        assert result.exit_code == 0
        assert "--git-url" in result.output
        assert "--new-branch" in result.output
        assert "--resume" in result.output

    def test_resume_help(self):
        """测试 resume 子命令帮助。"""
        runner = CliRunner()
        result = runner.invoke(main, ["resume", "--help"])
        assert result.exit_code == 0
        assert "--session-id" in result.output
        assert "--mode" in result.output

    def test_plan_missing_required(self):
        """测试缺少必填参数。"""
        runner = CliRunner()
        result = runner.invoke(main, ["plan"])
        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()

    def test_exec_missing_required(self):
        """测试缺少必填参数。"""
        runner = CliRunner()
        result = runner.invoke(main, ["exec"])
        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()
