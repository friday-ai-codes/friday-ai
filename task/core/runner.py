"""Task Runner - Main entry point for task container execution.

这个模块是容器模式的入口点，通过环境变量读取配置。
CLI 模式使用 cli 模块作为入口点。

执行流程：
1. 读取环境变量配置
2. 设置 Git 仓库
3. 根据模式执行任务（plan 或 execute）
4. 报告结果（如果配置了回调 URL）
"""

import asyncio
import os
import shutil
import sys
from pathlib import Path

import httpx
import structlog
from git.exc import GitCommandError
from structlog.stdlib import BoundLogger

from git_ops import GitOperations
from integrations import CallbackClient

from .config import TaskConfig
from .executor import ClaudeRunner

# Configure structured logging
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

# 镜像内 Friday skills 固定路径（Dockerfile COPY assets/skills/ 的目标）；
# 本地 CLI / 旧镜像无此目录时注入静默跳过（零回归）。
IMAGE_SKILLS_DIR = Path("/opt/friday/skills")

_GIT_IDENTITY_ENV = {
    "GIT_AUTHOR_NAME": "Friday Codes AI Agent",
    "GIT_AUTHOR_EMAIL": "ai@friday.codes",
    "GIT_COMMITTER_NAME": "Friday Codes AI Agent",
    "GIT_COMMITTER_EMAIL": "ai@friday.codes",
}

def _filter_friday_scratch(status_output: str) -> str:
    """从 ``git status --porcelain`` 输出中剔除工具自身的暂存目录。

    清单是 ``git_ops.operations.TOOL_SCRATCH_DIRS``（``.friday`` / ``.claude``）——
    与 setup 阶段写 ``.git/info/exclude`` 的那份**同源**，⛔ 不在此另写字面量。
    本函数是兜底：即便 exclude 因故未生效（如镜像内代码旧于修复），explore 洁净度
    校验也不会把工具产物误判为用户改动。保留其余所有条目（含真实的未跟踪 / 已修改
    文件），逐行按 porcelain v1 解析路径。
    """
    from git_ops.operations import TOOL_SCRATCH_DIRS

    kept: list[str] = []
    for line in status_output.splitlines():
        if not line.strip():
            continue
        # porcelain v1：前两列为状态码 XY，第 3 列为空格，其后为路径（重命名为 "old -> new"）
        path = line[3:].strip() if len(line) > 3 else ""
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        if " -> " in path:  # 重命名/复制：取目标路径判断
            path = path.split(" -> ", 1)[1].strip().strip('"')
        if any(path == name or path.startswith(f"{name}/") for name in TOOL_SCRATCH_DIRS):
            continue
        kept.append(line)
    return "\n".join(kept)


class TaskRunner:
    """Main task runner that orchestrates the entire task execution."""

    _EXECUTE_MODES = {"execute", "coding", "coding_commit"}

    def __init__(self, config: TaskConfig):
        """Initialize task runner with config."""
        self.config = config
        self.git_ops = GitOperations(config)
        self.callback = CallbackClient(config)
        self.claude: ClaudeRunner | None = None
        self._task_branch: str | None = None  # Store branch name for push

    async def run(self) -> int:
        """Run the task and return exit code."""
        log = logger.bind(
            task_id=self.config.task_id,
            project_id=self.config.project_id,
            mode=self.config.task_mode,
        )

        log.info(
            "Task runner starting",
            git_url=self.config.git_repo_url,
            branch=self.config.git_branch,
            has_api_key=bool(self.config.claude_api_key),
            has_callback_url=bool(self.config.callback_url),
        )

        try:
            # Report started
            await self.callback.report_started()

            # Set up Git repository
            log.info("Setting up Git repository")
            await self.git_ops.setup()

            # 注入 Friday skills 到 workspace/.claude/skills/（同名跳过不覆盖，
            # best-effort——各 task_mode 统一生效，经 executor setting_sources=["project"]
            # 既有通道加载，零 executor 改动）
            self._inject_skills(log)

            # Setup task-specific branch based on branch_strategy (work item)
            # CRITICAL: Branch must be created/switched BEFORE any Claude coding execution
            branch_name = self.config.git_branch
            if self._needs_task_branch():
                # Use branch_strategy if provided, otherwise fall back to git_new_branch or default
                branch_strategy = self.config.branch_strategy or self.config.git_new_branch
                self._task_branch = await self.git_ops.setup_task_branch(
                    branch_strategy=branch_strategy,
                    task_id=self.config.task_id,
                )
                branch_name = self._task_branch
                await self.callback.report_git_ready(branch_name)
                if not self._is_safe_work_branch(branch_name):
                    error = (
                        f"Refusing to run coding task on protected/base branch: {branch_name}. "
                        "A dedicated work branch is required."
                    )
                    log.error(
                        "unsafe_task_branch",
                        branch=branch_name,
                        base_branch=self.config.git_branch,
                    )
                    await self.callback.report_error(error, "branch")
                    return 1
                log.info("Task branch ready for coding", branch=branch_name)
            else:
                log.info("Plan mode - staying on branch", branch=branch_name)

            # Initialize Claude runner（传入 callback 供 coding 遇阻 HITL 的 ask_user 发问）
            self.claude = ClaudeRunner(
                self.config, self.git_ops.get_workspace_path(), callback=self.callback
            )

            # resume 续跑：若配置了 resume_session_id，把 server 经 env 分片下发的
            # transcript 还原到 SDK project 目录，供 executor 的 ClaudeAgentOptions(resume) 接续。
            if self.config.resume_session_id:
                self._restore_resume_transcript(log)

            # Execute based on mode
            if self.config.task_mode == "plan":
                return await self._run_plan_mode(log, branch_name)
            elif self.config.task_mode == "explore":
                return await self._run_explore_mode(log)
            elif self.config.task_mode == "repo_summary":
                return await self._run_repo_summary_mode(log)
            else:
                return await self._run_execute_mode(log, branch_name)

        except Exception as e:
            log.exception("Task execution failed")
            await self.callback.report_error(str(e), "execution")
            return 1

        finally:
            self.git_ops.cleanup()
            log.info("Task runner finished")

    def _needs_task_branch(self) -> bool:
        """coding 任务必须始终在独立工作分支上执行。"""
        return self.config.task_mode in self._EXECUTE_MODES

    def _is_safe_work_branch(self, branch_name: str) -> bool:
        """工作分支不能为空，也不能等于基础/保护分支。"""
        protected = {"main", "master", "develop", self.config.git_branch}
        return bool(branch_name) and branch_name not in protected

    def _inject_skills(self, log) -> None:
        """把镜像内 Friday skills 注入 {workspace}/.claude/skills/（best-effort）。

        - 镜像无 skills 目录（本地 CLI / 旧镜像）→ debug 后静默返回，零回归；
        - 目标同名技能已存在 → 跳过不覆盖（仓库自带 skills 优先，逐目录判断）；
        - 全程吞异常只 warning——skills 注入绝不因失败挂掉任务。
        """
        try:
            if not IMAGE_SKILLS_DIR.is_dir():
                log.debug("skills_injection_skipped_no_source", source=str(IMAGE_SKILLS_DIR))
                return

            target_base = Path(self.git_ops.get_workspace_path()) / ".claude" / "skills"
            target_base.mkdir(parents=True, exist_ok=True)

            injected: list[str] = []
            skipped: list[str] = []
            for source in sorted(IMAGE_SKILLS_DIR.iterdir()):
                if not source.is_dir():
                    continue
                target = target_base / source.name
                if target.exists():
                    # 仓库自带同名 skill 优先，不覆盖
                    skipped.append(source.name)
                    continue
                shutil.copytree(source, target)
                injected.append(source.name)

            log.info("skills_injected", injected=injected, skipped=skipped)
        except Exception as e:
            log.warning("skills_injection_failed", error=str(e))

    async def _run_plan_mode(self, log, branch_name: str) -> int:
        """Run in plan mode to generate implementation plan."""
        log.info("Running in plan mode")

        assert self.claude is not None, "ClaudeRunner not initialized"
        result = await self.claude.run_plan_mode()

        if not result.get("success"):
            error = result.get("error", "Unknown error")
            log.error("Plan generation failed", error=error)
            await self.callback.report_error(error, "planning")
            return 1

        plan = result.get("output", "")
        await self.callback.report_completed(
            output={"text": plan, "task_type": "coding_plan"},
            result_type="text",
        )

        log.info("Plan mode completed successfully")
        return 0

    async def _run_explore_mode(self, log) -> int:
        """Run in explore mode for deep code analysis (no commits)."""
        log.info("Running in explore mode")

        assert self.claude is not None, "ClaudeRunner not initialized"
        result = await self.claude.run_explore_mode()

        if not result.get("success"):
            error = result.get("error", "Unknown error")
            log.error("Explore failed", error=error)
            await self.callback.report_error(error, "execution")
            return 1

        if not await self._check_workspace_clean(log):
            return 1

        # 260818-pt8 D-01/D-02/D-08：结构化提交场景（blueprint fitness / repo plan）经共享
        # MCP 工厂捕获 `mcp_result`。有 scenario 时权威结果=`mcp_result`（executor 已在
        # 未捕获时判 success=False，上面已 report_error 返回）；普通 explore（无 scenario）
        # 保持既有 `output.text` 契约，零回归。
        submit_scenario = str(result.get("submit_scenario") or "").strip()
        mcp_result = result.get("mcp_result")

        # ⭐ 分析产物必须显式随 completed 帧上报（与 plan / repo_summary 模式同款契约）：
        # server 端蓝图调研 / 拟方案回调（subagent/api/callbacks._parse_blueprint_repo_plan
        # 等）只认结构化 `output.mcp_result`——不上报时 server 收到的只有 runner 的容器退出
        # 通知，全部解析为空、任务被判 failed（实测四仓调研/拟方案全灭的根因）。
        #
        # resume 支撑（同 execute 模式，runner.py 的 _run_execute_mode）：蓝图调研/拟方案
        # 容器全部跑 explore 模式，SDK 会话 transcript 不随 completed 帧上传的话，
        # `SubAgentSession` 留痕恒空、`_aresume_env` 永远查不到可续会话 ⇒ 同仓重派
        # （长等待/澄清后续跑）只能全新执行。读失败仅丢续跑能力，不影响产物上报。
        # 仅成功捕获结构化结果时才上传可 resume 的 transcript（D-08：失败路径已在上面
        # report_error 早退，不会走到这里上传污染 transcript）。
        sdk_session_id = str(result.get("session_id") or "")
        sdk_transcript = ""
        if sdk_session_id:
            from core.sdk_sessions import read_transcript

            sdk_transcript = read_transcript(sdk_session_id, str(self.git_ops.get_workspace_path()))

        if submit_scenario and isinstance(mcp_result, dict):
            output_payload: dict = {
                "task_type": "explore",
                "submit_scenario": submit_scenario,
                "mcp_result": mcp_result,
            }
        else:
            output_payload = {
                "text": str(result.get("output", "") or ""),
                "task_type": "explore",
            }

        await self.callback.report_completed(
            output=output_payload,
            result_type="text",
            sdk_session_id=sdk_session_id,
            sdk_transcript=sdk_transcript,
        )

        log.info("Explore mode completed successfully", submit_scenario=submit_scenario)
        return 0

    async def _check_workspace_clean(self, log) -> bool:
        """Explore mode must leave the workspace untouched."""
        repo = getattr(self.git_ops, "repo", None)
        if repo is None:
            log.warning("workspace_check_skipped_no_repo", task_id=self.config.task_id)
            return True

        try:
            status_output = repo.git.status("--porcelain")
        except Exception as exc:
            log.error("workspace_check_failed", error=str(exc), task_id=self.config.task_id)
            await self.callback.report_error(
                f"无法检查工作区状态: {exc}",
                "workspace",
            )
            return False

        # 剔除 Friday 自身写入工作区的 .friday/ 暂存目录，避免把自己的产物当成用户未提交变更。
        status_output = _filter_friday_scratch(status_output)

        if status_output.strip():
            log.error(
                "workspace_not_clean",
                task_id=self.config.task_id,
                git_status=status_output,
            )
            await self.callback.report_error(
                f"Explore 模式结束后工作区存在未提交变更:\n{status_output}",
                "workspace",
            )
            return False

        log.info("workspace_clean", task_id=self.config.task_id)
        return True

    async def _run_repo_summary_mode(self, log: BoundLogger) -> int:
        """Run in repo summary mode — plan permission, sanitize output, new callback."""
        log.info("Running in repo summary mode")

        assert self.claude is not None, "ClaudeRunner not initialized"
        result = await self.claude.run_repo_summary_mode()

        if not result.get("success"):
            error_msg = result.get("error", "Unknown error")
            log.error("repo_summary_failed", error=error_msg)
            await self.callback.report_failed(error_msg)
            return 1

        # 260818-pt8 D-01/D-02：唯一权威结果=共享 MCP 工厂捕获的 `mcp_result`（dict）。
        # 删除 `_extract_summary_json` / `_sanitize_summary` 自由文本兜底路径；结构化提交
        # 未捕获时 executor 已判 success=False（上面已 report_failed）。
        mcp_result = result.get("mcp_result")
        if not isinstance(mcp_result, dict):
            log.error("repo_summary_mcp_result_missing")
            await self.callback.report_failed(
                "repo_summary_mcp_result_missing: 容器未经共享 MCP 提交结构化结果"
            )
            return 1

        await self.callback.report_completed(
            output={
                "task_type": "repo_summary",
                "submit_scenario": result.get("submit_scenario", "repo_summary"),
                "mcp_result": mcp_result,
            },
            result_type="text",
        )

        log.info("repo_summary_completed")
        return 0

    def _load_resume_transcript(self) -> str:
        """从 env 重组 resume transcript（server 经 dispatch metadata 分片下发）。

        单环境变量受 MAX_ARG_STRLEN(~128KB) 限制，故大 transcript 拆成
        ``FRIDAY_TASK_RESUME_TRANSCRIPT_CHUNKS`` 个 ``FRIDAY_TASK_RESUME_TRANSCRIPT_{i}``；
        兼容单值 ``FRIDAY_TASK_RESUME_TRANSCRIPT``。缺失返回空串（走语义重建回退）。
        """
        single = os.environ.get("FRIDAY_TASK_RESUME_TRANSCRIPT", "")
        if single:
            return single

        try:
            chunk_count = int(os.environ.get("FRIDAY_TASK_RESUME_TRANSCRIPT_CHUNKS", "0"))
        except ValueError:
            chunk_count = 0
        if chunk_count <= 0:
            return ""

        parts = [
            os.environ.get(f"FRIDAY_TASK_RESUME_TRANSCRIPT_{i}", "")
            for i in range(chunk_count)
        ]
        return "".join(parts)

    def _restore_resume_transcript(self, log: BoundLogger) -> None:
        """把 resume transcript 还原到本地 SDK project 目录（fail-soft）。"""
        from core.sdk_sessions import write_transcript

        transcript = self._load_resume_transcript()
        if not transcript:
            log.info(
                "resume_transcript_absent",
                resume_session_id=self.config.resume_session_id,
            )
            return

        restored = write_transcript(
            self.config.resume_session_id or "",
            str(self.git_ops.get_workspace_path()),
            transcript,
        )
        log.info(
            "resume_transcript_restore",
            resume_session_id=self.config.resume_session_id,
            restored=restored,
            size=len(transcript),
        )

    async def _run_execute_mode(self, log, branch_name: str) -> int:
        """Run in execute mode to implement changes.

        根据 task_type 分流:
        - coding_commit (Phase): 仅 amend commit message + push
        - coding (Phase / 默认): AI coding + commit(临时 msg) + push + 回传 suggested_commit_message
        """
        # Phase: coding_commit 模式 (per contract)
        if self.config.task_type == "coding_commit":
            return await self._run_commit_mode(log, branch_name)

        # === Phase / 默认 coding 流程 ===
        log.info("Running in execute mode")

        assert self.claude is not None, "ClaudeRunner not initialized"
        plan = await self.claude.get_session_summary()
        result = await self.claude.run_execute_mode(plan)

        if not result.get("success"):
            error = result.get("error", "Unknown error")
            log.error("Execution failed", error=error)
            await self.callback.report_error(error, "execution")
            return 1

        # 防御纵深 #1：commit 前先强制 reset 回任务分支（restore_task_branch）。
        # 防御纵深 #2：reset 仍未到达就触发 ensure_current_branch 兜底失败。
        restored = await self.git_ops.restore_task_branch(branch_name)
        if not restored or not await self.git_ops.ensure_current_branch(branch_name):
            error = (
                f"Claude execution switched away from prepared branch: {branch_name}. "
                "Refusing to commit or push from an unexpected branch."
            )
            log.error("Execution branch drift detected", expected_branch=branch_name)
            await self.callback.report_error(error, "branch")
            return 1

        raw_diff_summary = await self.git_ops.get_diff_summary()
        diff_summary = raw_diff_summary if isinstance(raw_diff_summary, str) else ""
        raw_modified_files = await self.git_ops.get_modified_files()
        modified_files = (
            raw_modified_files
            if isinstance(raw_modified_files, list)
            and all(isinstance(path, str) for path in raw_modified_files)
            else []
        )

        if not diff_summary.strip() and not modified_files:
            log.warning("No changes to commit")
            await self.callback.report_status(
                status="no_changes",
                message="No code changes were made",
            )
            return 0

        # 单阶段流程：在 commit 前生成最终 commit message，避免后续再启动
        # coding_commit 容器执行 amend + force push。
        suggested_commit_message = await self._generate_suggested_commit_message(
            diff_summary=diff_summary,
            task_title=self.config.task_title,
            modified_files=modified_files,
        )
        commit_sha = await self.git_ops.commit_changes(suggested_commit_message)

        if not commit_sha:
            log.warning("No changes to commit")
            await self.callback.report_status(
                status="no_changes",
                message="No code changes were made",
            )
            return 0

        # Push branch with retry (work item)
        try:
            await self.git_ops.push_branch_with_retry(branch_name)
            await self.callback.report_push_complete(
                branch_name=branch_name,
                commit_sha=commit_sha,
                modified_files=modified_files,
            )
        except GitCommandError as e:
            log.error("Push failed after retries", error=str(e))
            await self.callback.report_error(str(e), "push")
            return 1

        # 回传 suggested_commit_message 到 SubAgentSession.last_output (per contract)
        await self.callback.report_suggested_commit_message(suggested_commit_message)
        log.info(
            "suggested_commit_message_sent",
            msg_preview=suggested_commit_message[:80],
        )
        # === End implementation 新增 ===

        # Report completion
        await self.callback.report_execution_complete(
            branch_name=branch_name,
            commit_sha=commit_sha,
            diff_summary=diff_summary,
        )

        # resume 支撑：读出本次 SDK 会话 transcript，随 completed 帧上传 server 落库，
        # 供 7 天内改方案/回溯续跑（read 失败仅丢恢复能力，不影响主流程）。
        sdk_session_id = str(result.get("session_id") or "")
        sdk_transcript = ""
        if sdk_session_id:
            from core.sdk_sessions import read_transcript

            sdk_transcript = read_transcript(
                sdk_session_id, str(self.git_ops.get_workspace_path())
            )

        # implementation contract: 显式发 completed 帧携带 git 元数据。
        # progress 帧（push_complete / suggested_commit_message / execution_complete）
        # 上面已经发过，server 端 progress 渲染依赖；此处补 completed 帧让 server
        # _handle_completed 走全 TaskResult 写入 + resume coding_graph。
        await self.callback.report_completed(
            output={
                "text": diff_summary,
                "branch_name": branch_name,
                "commit_sha": commit_sha,
                "suggested_commit_message": suggested_commit_message,
                "modified_files": modified_files,
                "task_type": "coding",
            },
            result_type="text",
            sdk_session_id=sdk_session_id,
            sdk_transcript=sdk_transcript,
        )

        log.info("Execute mode completed successfully", commit=commit_sha[:8])
        return 0

    async def _generate_suggested_commit_message(
        self,
        diff_summary: str,
        task_title: str,
        modified_files: list[str],
    ) -> str:
        """基于 diff 和任务标题生成 AI 建议的 commit message。

        失败时回退到本地模板，但绝不把完整 task_description / prompt 拼进 commit body。
        """
        fallback = self._fallback_commit_message(task_title, diff_summary)
        if not self.config.claude_api_key:
            return fallback

        base_url = (self.config.claude_base_url or "https://api.anthropic.com").rstrip("/")
        model = self.config.claude_small_model or self.config.claude_model or "claude-haiku-4-5"
        files_text = "\n".join(f"- {path}" for path in modified_files[:20]) or "- 未获取到文件列表"
        prompt = (
            "请根据以下编码任务结果生成一个 Git commit message。\n\n"
            "要求：\n"
            "1. 使用 Conventional Commits 格式。\n"
            "2. 第一行格式为 `<type>: <中文摘要>`，摘要不超过 72 个字符。\n"
            "3. 空一行后写 body，最多 5 行，概括为什么和改了什么。\n"
            "4. 只输出 commit message 本身，不要 Markdown，不要解释。\n"
            "5. 不要复述原始任务 prompt、执行规格、分支信息或 Task ID。\n\n"
            f"任务标题：{task_title or '实现代码变更'}\n\n"
            f"变更文件：\n{files_text}\n\n"
            f"Diff stat：\n{diff_summary[:1200]}"
        )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{base_url}/v1/messages",
                    headers={
                        "x-api-key": self.config.claude_api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": model,
                        "max_tokens": 400,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
            response.raise_for_status()
            text = self._extract_commit_message_from_anthropic(response.json())
            return text or fallback
        except Exception as e:
            logger.warning("suggested_commit_message_ai_failed", error=str(e))
            return fallback

    @staticmethod
    def _extract_commit_message_from_anthropic(data: object) -> str:
        """从 Anthropic Messages API 响应里提取文本。"""
        if not isinstance(data, dict):
            return ""
        content = data.get("content")
        if not isinstance(content, list):
            return ""
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts).strip()

    @staticmethod
    def _fallback_commit_message(task_title: str, diff_summary: str) -> str:
        """AI 不可用时的安全 commit message 模板。"""
        title = (task_title or "implement changes").strip()
        body = (diff_summary or "No diff summary available").strip()[:300]
        return f"feat: {title}\n\n{body}".strip()

    async def _run_commit_mode(self, log: BoundLogger, branch_name: str) -> int:
        """Phase: 使用用户确认的 commit message 执行 git commit --amend + push。

        Phase 已完成 coding + commit(临时 message) + push。
        Phase checkout 分支后执行 amend commit message 并 force push。
        Per contract/contract。
        """
        commit_message = self.config.commit_message
        if not commit_message:
            log.error("commit_mode_missing_message", task_id=self.config.task_id)
            await self.callback.report_error("缺少 commit message", "commit")
            return 1

        log.info("commit_mode_start", task_id=self.config.task_id, branch=branch_name)

        # amend 最近一次 commit 的 message（使用 asyncio.create_subprocess_exec 直接执行 git 命令）
        # GitOperations 没有 run_command 方法，直接使用 subprocess
        workspace = self.git_ops.get_workspace_path()

        # Runner 自己的 git 写操作必须走 /usr/bin/git 绕过 PATH 中的 wrapper；
        # wrapper 在 coding / coding_commit 模式下会拒绝 commit/push 等命令，
        # 用 real git 才能正常 amend 和 force-push。
        git_env = {**os.environ, **_GIT_IDENTITY_ENV}
        try:
            proc = await asyncio.create_subprocess_exec(
                "/usr/bin/git", "commit", "--amend", "-m", commit_message,
                cwd=str(workspace),
                env=git_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode != 0:
                error_msg = stderr.decode().strip() if stderr else "unknown error"
                raise RuntimeError(f"git commit --amend failed: {error_msg}")
            log.info("commit_amended", result=stdout.decode()[:200] if stdout else "")
        except Exception as e:
            log.error("commit_amend_failed", error=str(e))
            await self.callback.report_error(f"commit amend 失败: {e}", "commit")
            return 1

        # 获取新的 commit SHA（同样走 /usr/bin/git）
        try:
            proc = await asyncio.create_subprocess_exec(
                "/usr/bin/git", "rev-parse", "HEAD",
                cwd=str(workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            commit_sha = stdout.decode().strip() if stdout else ""
        except Exception:
            commit_sha = ""

        # force push (--force-with-lease 安全 force push, per security mitigation)
        try:
            proc = await asyncio.create_subprocess_exec(
                "/usr/bin/git", "push", "--force-with-lease", "origin", branch_name,
                cwd=str(workspace),
                env=git_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.config.git_timeout
            )
            if proc.returncode != 0:
                error_msg = stderr.decode().strip() if stderr else "unknown error"
                raise RuntimeError(f"git push --force-with-lease failed: {error_msg}")
        except Exception as e:
            log.error("push_failed", error=str(e))
            await self.callback.report_error(f"push 失败: {e}", "push")
            return 1

        modified_files = await self.git_ops.get_modified_files()
        await self.callback.report_push_complete(
            branch_name=branch_name,
            commit_sha=commit_sha,
            modified_files=modified_files,
        )

        diff_summary = await self.git_ops.get_diff_summary()
        await self.callback.report_execution_complete(
            branch_name=branch_name,
            commit_sha=commit_sha,
            diff_summary=diff_summary,
        )

        # implementation contract: Phase 完成同样发 completed 帧（task_type="coding_commit"），
        # 让 server 端 _update_coding_session_on_complete 走 Phase 分支 resume graph。
        await self.callback.report_completed(
            output={
                "text": "commit message amended and pushed",
                "branch_name": branch_name,
                "commit_sha": commit_sha,
                "modified_files": modified_files,
                "task_type": "coding_commit",
            },
            result_type="text",
        )

        log.info("commit_mode_complete", commit_sha=commit_sha[:8] if commit_sha else "")
        return 0


async def main() -> int:
    """Main entry point for container mode."""
    logger.info("Container mode main() starting")

    try:
        config = TaskConfig()
        logger.info(
            "TaskConfig loaded successfully",
            task_id=config.task_id,
            mode=config.task_mode,
        )
    except Exception:
        logger.exception("Failed to load configuration")
        return 1

    runner = TaskRunner(config)
    return await runner.run()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
