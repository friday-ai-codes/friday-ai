"""Friday Task CLI - 命令行接口.

支持两种主要模式：
- plan: 分析代码库并生成实施计划（只读模式，不创建新分支）
- exec: 执行代码变更（创建新分支，提交并推送）
"""

import asyncio
import sys
import uuid

import click
import structlog

from core.config import TaskConfig
from core.executor import ClaudeRunner
from git_ops import GitOperations
from integrations import CallbackClient

# 配置 structlog
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


def generate_task_id() -> str:
    """生成唯一任务 ID."""
    return f"task-{uuid.uuid4().hex[:8]}"


def common_options(f):
    """共享的命令行选项装饰器."""
    f = click.option(
        "--git-url",
        envvar="FRIDAY_TASK_GIT_REPO_URL",
        required=True,
        help="Git 仓库 URL（SSH 或 HTTPS 格式）",
    )(f)
    f = click.option(
        "--branch",
        envvar="FRIDAY_TASK_GIT_BRANCH",
        default="main",
        help="基础分支名称（默认 main）",
    )(f)
    f = click.option(
        "--description",
        envvar="FRIDAY_TASK_TASK_DESCRIPTION",
        required=True,
        help="任务描述（用于 Claude prompt 和 commit 消息）",
    )(f)
    f = click.option(
        "--api-key",
        envvar="FRIDAY_TASK_CLAUDE_API_KEY",
        help="Claude API Key",
    )(f)
    f = click.option(
        "--base-url",
        envvar="FRIDAY_TASK_CLAUDE_BASE_URL",
        help="Claude API Base URL（可选，用于代理）",
    )(f)
    f = click.option(
        "--ssh-key",
        envvar="FRIDAY_TASK_GIT_SSH_KEY",
        help="SSH 私钥内容（用于 Git 认证）",
    )(f)
    f = click.option(
        "--access-token",
        envvar="FRIDAY_TASK_GIT_ACCESS_TOKEN",
        help="Git 访问令牌（用于 HTTPS 认证）",
    )(f)
    f = click.option(
        "--callback-url",
        envvar="FRIDAY_TASK_CALLBACK_URL",
        help="状态回调 URL（可选，不设置则仅记录日志）",
    )(f)
    f = click.option(
        "--session-dir",
        envvar="FRIDAY_TASK_SESSION_DIR",
        default="./sessions",
        help="会话存储目录（默认 ./sessions）",
    )(f)
    f = click.option(
        "--task-id",
        envvar="FRIDAY_TASK_TASK_ID",
        help="任务 ID（可选，不设置则自动生成）",
    )(f)
    f = click.option(
        "--project-id",
        envvar="FRIDAY_TASK_PROJECT_ID",
        default="cli",
        help="项目 ID（默认 cli）",
    )(f)
    f = click.option(
        "--no-ssl-verify",
        envvar="FRIDAY_TASK_GIT_SSL_VERIFY",
        is_flag=True,
        default=True,
        help="禁用 Git SSL 验证（用于自签名证书）",
    )(f)
    f = click.option(
        "--git-proxy",
        envvar="FRIDAY_TASK_GIT_HTTP_PROXY",
        help="Git HTTP/HTTPS 代理 URL",
    )(f)
    return f


@click.group()
@click.version_option(version="0.1.0", prog_name="friday-task")
def main():
    """Friday Task - AI 驱动的开发任务执行器.

    支持 plan（计划）和 exec（执行）两种模式。
    """
    pass


@main.command()
@common_options
def plan(
    git_url: str,
    branch: str,
    description: str,
    api_key: str | None,
    base_url: str | None,
    ssh_key: str | None,
    access_token: str | None,
    callback_url: str | None,
    session_dir: str,
    task_id: str | None,
    project_id: str,
    no_ssl_verify: bool,
    git_proxy: str | None,
):
    """执行计划模式 - 分析代码库并生成实施计划."""
    task_id = task_id or generate_task_id()

    config = _build_config(
        mode="plan",
        task_id=task_id,
        project_id=project_id,
        git_url=git_url,
        branch=branch,
        new_branch=None,
        description=description,
        api_key=api_key,
        base_url=base_url,
        ssh_key=ssh_key,
        access_token=access_token,
        callback_url=callback_url,
        session_dir=session_dir,
        ssl_verify=not no_ssl_verify,
        git_proxy=git_proxy,
    )

    exit_code = asyncio.run(_run_task(config))
    sys.exit(exit_code)


@main.command()
@common_options
@click.option(
    "--new-branch",
    envvar="FRIDAY_TASK_GIT_NEW_BRANCH",
    help="功能分支名称（可选，默认自动生成 friday/task-{id}）",
)
@click.option(
    "--resume",
    "resume_session",
    help="恢复已有会话 ID",
)
def exec(
    git_url: str,
    branch: str,
    description: str,
    api_key: str | None,
    base_url: str | None,
    ssh_key: str | None,
    access_token: str | None,
    callback_url: str | None,
    session_dir: str,
    task_id: str | None,
    project_id: str,
    no_ssl_verify: bool,
    new_branch: str | None,
    resume_session: str | None,
    git_proxy: str | None,
):
    """执行实现模式 - 创建分支并实现代码变更."""
    task_id = task_id or generate_task_id()

    config = _build_config(
        mode="execute",
        task_id=task_id,
        project_id=project_id,
        git_url=git_url,
        branch=branch,
        new_branch=new_branch,
        description=description,
        api_key=api_key,
        base_url=base_url,
        ssh_key=ssh_key,
        access_token=access_token,
        callback_url=callback_url,
        session_dir=session_dir,
        ssl_verify=not no_ssl_verify,
        resume_session=resume_session,
        git_proxy=git_proxy,
    )

    exit_code = asyncio.run(_run_task(config))
    sys.exit(exit_code)


@main.command()
@click.option("--session-id", required=True, help="要恢复的会话 ID")
@click.option(
    "--mode", type=click.Choice(["plan", "exec"]), default="exec", help="恢复后的执行模式"
)
@click.option(
    "--session-dir", envvar="FRIDAY_TASK_SESSION_DIR", default="./sessions", help="会话存储目录"
)
@click.option("--api-key", envvar="FRIDAY_TASK_CLAUDE_API_KEY", help="Claude API Key")
@click.option("--base-url", envvar="FRIDAY_TASK_CLAUDE_BASE_URL", help="Claude API Base URL")
def resume(
    session_id: str,
    mode: str,
    session_dir: str,
    api_key: str | None,
    base_url: str | None,
):
    """恢复已有会话继续执行."""
    import json
    from pathlib import Path

    mapping_file = Path(session_dir) / "mapping.json"
    if not mapping_file.exists():
        click.echo(f"错误: 未找到会话映射文件 {mapping_file}", err=True)
        sys.exit(1)

    try:
        mappings = json.loads(mapping_file.read_text())
        if session_id not in mappings:
            click.echo(f"错误: 未找到会话 {session_id}", err=True)
            sys.exit(1)

        session_info = mappings[session_id]
        task_id = session_info["task_id"]
        task_file = Path(session_dir) / f"{task_id}.json"
        if not task_file.exists():
            click.echo(f"错误: 未找到任务会话文件 {task_file}", err=True)
            sys.exit(1)

        task_data = json.loads(task_file.read_text())
    except json.JSONDecodeError as e:
        click.echo(f"错误: 会话文件格式错误: {e}", err=True)
        sys.exit(1)

    git_url = task_data.get("git_url", "")
    if not git_url:
        click.echo("错误: 会话缺少 git_url，无法恢复执行", err=True)
        sys.exit(1)

    click.echo(f"恢复会话 {session_id} (任务: {task_id})")

    # CLI 在本机运行，transcript 已在本地 ~/.claude，无需还原；
    # 仅重建 config 并设 resume_session_id 让 SDK 接续上次对话续跑。
    run_mode = "execute" if mode == "exec" else "plan"
    config = _build_config(
        mode=run_mode,
        task_id=task_id,
        project_id=task_data.get("project_id", "cli"),
        git_url=git_url,
        branch=task_data.get("git_branch", "main"),
        new_branch=None,
        description=task_data.get("description", "") or "继续上次会话",
        api_key=api_key,
        base_url=base_url,
        ssh_key=None,
        access_token=None,
        callback_url=None,
        session_dir=session_dir,
        ssl_verify=False,
        resume_session=session_id,
    )

    exit_code = asyncio.run(_run_task(config))
    sys.exit(exit_code)


def _build_config(
    mode: str,
    task_id: str,
    project_id: str,
    git_url: str,
    branch: str,
    new_branch: str | None,
    description: str,
    api_key: str | None,
    base_url: str | None,
    ssh_key: str | None,
    access_token: str | None,
    callback_url: str | None,
    session_dir: str,
    ssl_verify: bool,
    resume_session: str | None = None,
    git_proxy: str | None = None,
) -> TaskConfig:
    """构建任务配置对象."""
    if ssh_key:
        auth_type = "ssh"
    elif access_token:
        auth_type = "token"
    else:
        auth_type = "ssh"

    title = description[:50] + "..." if len(description) > 50 else description

    return TaskConfig(
        task_id=task_id,
        project_id=project_id,
        task_title=title,
        task_description=description,
        task_mode=mode,
        git_repo_url=git_url,
        git_branch=branch,
        git_new_branch=new_branch,
        git_auth_type=auth_type,
        git_ssh_key=ssh_key or "",
        git_access_token=access_token or "",
        git_ssl_verify=ssl_verify,
        git_http_proxy=git_proxy,
        claude_api_key=api_key or "",
        claude_base_url=base_url or "",
        callback_url=callback_url or "",
        session_dir=session_dir,
        resume_session_id=resume_session,
    )


async def _run_task(config: TaskConfig) -> int:
    """执行任务并返回退出码."""
    log = logger.bind(task_id=config.task_id, mode=config.task_mode)
    log.info("Task starting", git_url=config.git_repo_url, branch=config.git_branch)

    git_ops = GitOperations(config)
    callback = CallbackClient(config)

    try:
        await callback.report_started()
        await git_ops.setup()

        branch_name = config.git_branch
        if config.task_mode == "execute":
            feature_branch = config.git_new_branch or f"friday/task-{config.task_id}"
            branch_name = await git_ops.create_feature_branch(feature_branch)
            await callback.report_git_ready(branch_name)

        claude = ClaudeRunner(config, git_ops.get_workspace_path())

        if config.task_mode == "plan":
            return await _run_plan_mode(claude, callback, log)
        else:
            return await _run_execute_mode(claude, git_ops, callback, branch_name, config, log)

    except Exception as e:
        log.exception("Task execution failed")
        await callback.report_error(str(e), "execution")
        return 1
    finally:
        git_ops.cleanup()


async def _run_plan_mode(claude: ClaudeRunner, callback: CallbackClient, log) -> int:
    """执行 Plan 模式."""
    result = await claude.run_plan_mode()

    if not result.get("success"):
        await callback.report_error(result.get("error", "Unknown error"), "planning")
        return 1

    plan = result.get("output", "")
    click.echo("\n" + "=" * 60)
    click.echo("📋 实施计划:")
    click.echo("=" * 60)
    click.echo(plan)
    click.echo("=" * 60 + "\n")

    await callback.report_completed(
        output={"text": plan, "task_type": "coding_plan"},
        result_type="text",
    )
    return 0


async def _run_execute_mode(
    claude: ClaudeRunner,
    git_ops: GitOperations,
    callback: CallbackClient,
    branch_name: str,
    config: TaskConfig,
    log,
) -> int:
    """执行 Execute 模式."""
    plan = await claude.get_session_summary()
    result = await claude.run_execute_mode(plan)

    if not result.get("success"):
        await callback.report_error(result.get("error", "Unknown error"), "execution")
        return 1

    commit_message = f"feat: {config.task_title}\n\n{config.task_description}\n\nTask ID: {config.task_id}\nImplemented by Friday AI Agent"
    commit_sha = await git_ops.commit_changes(commit_message)

    if not commit_sha:
        await callback.report_status(status="no_changes", message="No code changes were made")
        click.echo("⚠️ 没有代码变更需要提交")
        return 0

    await git_ops.push_branch(branch_name)
    diff_summary = await git_ops.get_diff_summary()

    click.echo("\n" + "=" * 60)
    click.echo("✅ 执行完成!")
    click.echo("=" * 60)
    click.echo(f"分支: {branch_name}")
    click.echo(f"提交: {commit_sha[:8]}")
    click.echo(f"\n变更摘要:\n{diff_summary}")
    click.echo("=" * 60 + "\n")

    await callback.report_execution_complete(
        branch_name=branch_name,
        commit_sha=commit_sha,
        diff_summary=diff_summary,
    )
    return 0


if __name__ == "__main__":
    main()
