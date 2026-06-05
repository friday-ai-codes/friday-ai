"""Claude Agent SDK runner for task execution.

使用 claude-agent-sdk Python SDK 来执行 AI 开发任务。

权限模式：
- Plan 模式：使用 permission_mode="plan"（只读，不能修改文件）
- Execute 模式：使用 permission_mode="bypassPermissions"（跳过所有权限检查，包括 Bash 命令确认）

bypassPermissions 在 Docker 容器隔离环境中是安全的，可以支持无人值守执行。
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

import structlog
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from .config import TaskConfig

logger = structlog.get_logger()

# SDK 支持的权限模式
PermissionModeType = Literal["default", "acceptEdits", "plan", "bypassPermissions"]

_CLAUDE_TRANSIENT_ERROR_MARKERS = (
    "server had an error while processing your request",
    "overloaded",
    "temporarily unavailable",
    "timeout",
    "timed out",
    "econnreset",
    "connection reset",
    "stream disconnected",
)


def _is_transient_claude_error(error: Exception) -> bool:
    """判断 Claude SDK/API 错误是否适合立即重试。"""
    message = str(error).lower()
    return any(marker in message for marker in _CLAUDE_TRANSIENT_ERROR_MARKERS)


class ClaudeRunner:
    """Run Claude Agent SDK for AI-powered development."""

    def __init__(self, config: TaskConfig, workspace: Path):
        """Initialize Claude runner with config and workspace path."""
        self.config = config
        self.workspace = workspace
        self.session_file = Path(config.session_dir) / f"{config.task_id}.json"
        self.mapping_file = Path(config.session_dir) / "mapping.json"

    async def run_plan_mode(self) -> dict:
        """Run Claude Agent in plan mode to generate implementation plan.

        使用 plan 权限模式，只能读取文件，不能修改。
        """
        log = logger.bind(task_id=self.config.task_id, mode="plan")
        log.info("Starting plan mode execution with claude-agent-sdk")

        prompt = self._build_plan_prompt()

        result = await self._execute_claude(
            prompt=prompt,
            permission_mode="plan",  # 只读模式
        )

        log.info("Plan mode completed", success=result.get("success", False))
        return result

    async def run_execute_mode(self, plan: str | None = None) -> dict:
        """Run Claude Agent in execute mode to implement changes.

        使用 bypassPermissions 权限模式，跳过权限确认；保留 ``Bash`` 等全部工具
        以便 Claude 运行测试、lint、安装依赖。``git`` 写操作（commit / push /
        checkout 等）由 ``git-wrapper.sh`` 在 shell 层拦截，分支与 commit/push
        由 Runner 调 ``/usr/bin/git`` 直接执行（绕过 wrapper）。
        """
        log = logger.bind(task_id=self.config.task_id, mode="execute")
        log.info("Starting execute mode execution with claude-agent-sdk")

        prompt = self._build_execute_prompt(plan)

        result = await self._execute_claude(
            prompt=prompt,
            permission_mode="bypassPermissions",
        )

        log.info("Execute mode completed", success=result.get("success", False))
        return result

    async def run_explore_mode(self) -> dict:
        """Run Claude Agent in explore mode for deep code analysis.

        使用 bypassPermissions 权限模式（需要执行命令来分析代码），
        但不会修改或提交代码。Prompt 引导 Claude 只做分析。
        """
        log = logger.bind(task_id=self.config.task_id, mode="explore")
        log.info("Starting explore mode execution with claude-agent-sdk")

        prompt = self._build_explore_prompt()

        result = await self._execute_claude(
            prompt=prompt,
            permission_mode="bypassPermissions",
        )

        log.info("Explore mode completed", success=result.get("success", False))
        return result

    def _build_plan_prompt(self) -> str:
        """Build the prompt for plan mode."""
        return f"""You are an AI development agent working on a coding task.

## Task Information
- **Description**: {self.config.task_description}

## Your Goal
Analyze the codebase and create a detailed implementation plan. Do NOT make any changes yet.

## Instructions
1. Explore the codebase structure to understand the project
2. Identify relevant files that need to be modified or created
3. Create a step-by-step implementation plan with:
   - Files to modify/create
   - Specific changes needed for each file
   - Any dependencies or considerations
4. Estimate the complexity and potential risks

## Output Format
Provide your plan in a structured markdown format that can be reviewed by a human.
"""

    def _build_explore_prompt(self) -> str:
        """Build the prompt for explore/analysis mode."""
        return f"""You are a senior code analyst performing deep analysis on a codebase.

## Analysis Task
{self.config.task_description}

## Instructions
1. Explore the codebase thoroughly to understand its structure
2. Read relevant source files, trace call chains, analyze architecture
3. Run commands if needed to understand runtime behavior
4. Provide a detailed, well-structured analysis result

## Important
- Do NOT modify any source files
- Do NOT create new branches or commits
- Focus on analysis and explanation only
- Output your findings in clear, structured Chinese (中文)
"""

    def _build_execute_prompt(self, plan: str | None = None) -> str:
        """Build the prompt for execute mode."""
        base_prompt = f"""You are an AI development agent implementing a coding task.

## Task Information
- **Description**: {self.config.task_description}

"""

        if plan:
            base_prompt += f"""## Approved Plan
{plan}

## Instructions
Implement the changes according to the approved plan above.
"""
        else:
            base_prompt += """## Instructions
Implement the task as described. Make necessary code changes.
"""

        base_prompt += """
## Guidelines
1. Write clean, well-documented code
2. Follow existing code style and conventions
3. Add appropriate tests if applicable
4. Do NOT create or switch branches; the Runner has already prepared the correct branch
5. Do NOT run git commit; the Runner will create the commit after your edits
6. Do NOT push; the Runner will push the prepared branch
7. Do NOT create pull requests or merge requests; Friday Server handles that later
"""

        return base_prompt

    async def run_repo_summary_mode(self) -> dict:
        """Run Claude Agent in repo summary mode — plan permission, max 15 turns.

        以 plan 权限只读扫描仓库，生成结构化 JSON 描述。
        """
        log = logger.bind(task_id=self.config.task_id, mode="repo_summary")
        log.info("Starting repo summary mode execution with claude-agent-sdk")

        prompt = self.config.task_description  # dispatch 时已渲染好的 prompt

        result = await self._execute_claude(
            prompt=prompt,
            permission_mode="plan",
            max_turns=15,  # 覆盖默认 50，控制成本
        )

        log.info("Repo summary mode completed", success=result.get("success", False))
        return result

    async def _execute_claude(
        self,
        prompt: str,
        permission_mode: PermissionModeType = "bypassPermissions",
        max_turns: int | None = None,
    ) -> dict:
        """Execute Claude Agent SDK with the given prompt."""
        log = logger.bind(task_id=self.config.task_id)

        try:
            if not self.config.claude_api_key:
                log.warning("No ANTHROPIC_API_KEY configured!")

            # 检查工作目录
            workspace_path = Path(self.workspace)
            if not workspace_path.exists():
                log.error("Workspace directory does not exist", path=str(self.workspace))
            else:
                file_count = len(list(workspace_path.iterdir()))
                log.debug(
                    "Workspace ready",
                    path=str(self.workspace),
                    files=file_count,
                )

            # Claude Code stderr 转发到 stdout（被 docker logs 和 Runner StreamLogs 捕获）
            def _stderr_handler(line: str) -> None:
                print(f"[claude] {line}", flush=True)

            # 构建 env：通过 ClaudeAgentOptions(env=...) 注入，不污染宿主 os.environ
            env_vars: dict[str, str] = {}
            if self.config.claude_api_key:
                env_vars["ANTHROPIC_API_KEY"] = self.config.claude_api_key
            if self.config.claude_base_url:
                env_vars["ANTHROPIC_BASE_URL"] = self.config.claude_base_url

            # cc-switch 三档模型映射（Claude Code 模型映射）：把 Claude Code 的
            # opus/sonnet/haiku 模型别名映射到所选 provider 的具体模型。
            # haiku 档同时驱动子代理（Explore 等）——第三方网关默认 haiku 可能不可用。
            haiku_model = (
                self.config.claude_haiku_model
                or self.config.claude_small_model
                or self.config.claude_model
            )
            if haiku_model:
                env_vars["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = haiku_model
                env_vars["CLAUDE_CODE_SUBAGENT_MODEL"] = haiku_model
                log.debug("Sub-agent (haiku) model override", model=haiku_model)
            if self.config.claude_sonnet_model:
                env_vars["ANTHROPIC_DEFAULT_SONNET_MODEL"] = self.config.claude_sonnet_model
                log.debug("Sonnet tier model override", model=self.config.claude_sonnet_model)
            if self.config.claude_opus_model:
                env_vars["ANTHROPIC_DEFAULT_OPUS_MODEL"] = self.config.claude_opus_model
                log.debug("Opus tier model override", model=self.config.claude_opus_model)

            # 主模型优先级：sonnet 档（cc-switch 主力档）> claude_model > 默认 sonnet
            main_model = (
                self.config.claude_sonnet_model
                or self.config.claude_model
                or "sonnet"
            )

            options = ClaudeAgentOptions(
                system_prompt=self._get_system_prompt(),
                permission_mode=permission_mode,
                cwd=str(self.workspace),
                model=main_model,
                max_turns=max_turns or self.config.claude_max_turns,
                setting_sources=["project"],
                stderr=_stderr_handler,
                env=env_vars,
                extra_args={"debug-to-stderr": None},
            )

            log.info(
                "Executing Claude Agent SDK",
                permission_mode=permission_mode,
                workspace=str(self.workspace),
                has_api_key=bool(self.config.claude_api_key),
                has_base_url=bool(self.config.claude_base_url),
            )

            # 收集所有消息。只读/分析类任务遇到 Claude API 偶发 5xx/stream 中断时
            # 可重试整次请求；execute 模式可能已产生文件变更，不能自动重放。
            retryable_mode = permission_mode == "plan" or self.config.task_mode in (
                "explore",
                "repo_summary",
            )
            max_attempts = 3 if retryable_mode else 1
            for attempt in range(1, max_attempts + 1):
                messages = []
                text_outputs = []  # 收集所有 AssistantMessage 的文本
                session_id = None
                total_cost = None
                result_output = None  # ResultMessage 的 result 字段

                try:
                    async for message in query(prompt=prompt, options=options):
                        messages.append(message)
                        msg_type = type(message).__name__

                        if isinstance(message, AssistantMessage):
                            for block in message.content:
                                if isinstance(block, TextBlock):
                                    text_outputs.append(block.text)
                                    preview = block.text[:500]
                                    print(f"[task:text] {preview}", flush=True)
                                elif isinstance(block, ToolUseBlock):
                                    tool_input = json.dumps(block.input, ensure_ascii=False)[:300]
                                    print(f"[task:tool] {block.name}({tool_input})", flush=True)
                                else:
                                    # ThinkingBlock 等：尝试提取 thinking 内容，否则只打印类型名
                                    block_type = type(block).__name__
                                    thinking = getattr(block, 'thinking', '') or getattr(block, 'signature', '')
                                    if thinking:
                                        print(f"[task:text] [思考] {thinking[:500]}", flush=True)
                                    else:
                                        print(f"[task:block] {block_type}", flush=True)
                        elif isinstance(message, SystemMessage):
                            subtype = getattr(message, 'subtype', '')
                            # 过滤掉无意义的 system 子类型
                            if subtype not in ('', 'null', None):
                                print(f"[task:system] subtype={subtype}", flush=True)
                        elif isinstance(message, ResultMessage):
                            session_id = message.session_id
                            total_cost = message.total_cost_usd
                            if message.result:
                                result_output = message.result
                            print(f"[task:result] session={session_id} cost=${total_cost}", flush=True)
                        else:
                            # 跳过 UserMessage 等 SDK 内部消息，它们对用户无意义
                            if msg_type != 'UserMessage':
                                print(f"[task:msg] {msg_type}", flush=True)
                    break
                except Exception as e:
                    if not _is_transient_claude_error(e):
                        raise
                    if attempt >= max_attempts:
                        raise RuntimeError(
                            f"Claude SDK transient API error after {max_attempts} attempts: {e}"
                        ) from e

                    delay_seconds = min(2 ** (attempt - 1), 4)
                    log.warning(
                        "Claude SDK transient error, retrying",
                        attempt=attempt,
                        max_attempts=max_attempts,
                        delay_seconds=delay_seconds,
                        error=str(e),
                    )
                    print(
                        f"[task:text] Claude SDK transient error, retrying "
                        f"({attempt}/{max_attempts}): {e}",
                        flush=True,
                    )
                    await asyncio.sleep(delay_seconds)

            # 检查是否有 SDK 执行错误
            # 如果没有收到任何 AssistantMessage，且 usage 显示 0 tokens，说明 API 调用失败
            result_message = next((m for m in messages if isinstance(m, ResultMessage)), None)
            if result_message:
                result_subtype = getattr(result_message, "subtype", None)
                result_usage = getattr(result_message, "usage", {})
                input_tokens = result_usage.get("input_tokens", 0) if result_usage else 0
                output_tokens = result_usage.get("output_tokens", 0) if result_usage else 0

                # 检测执行错误：subtype 是 error_during_execution 或者没有产生任何 tokens
                if result_subtype == "error_during_execution" or (
                    input_tokens == 0 and output_tokens == 0
                ):
                    error_msg = f"Claude SDK execution failed: subtype={result_subtype}, input_tokens={input_tokens}, output_tokens={output_tokens}"
                    log.error(
                        "Claude SDK execution failed",
                        subtype=result_subtype,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        session_id=session_id,
                    )

                    # 保存会话信息（用于调试）
                    await self._save_session(
                        {
                            "output": "",
                            "messages": len(messages),
                            "session_id": session_id,
                            "cost": total_cost,
                            "error": error_msg,
                        }
                    )

                    return {
                        "success": False,
                        "error": error_msg,
                        "message_count": len(messages),
                        "session_id": session_id,
                        "cost": total_cost,
                        "details": {
                            "subtype": result_subtype,
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                        },
                    }

            # 确定最终输出：优先使用 ResultMessage.result，否则合并所有 TextBlock
            if result_output:
                final_output = result_output
            else:
                final_output = "\n".join(text_outputs)

            # 如果没有任何输出，也视为失败
            if not final_output.strip():
                error_msg = "Claude SDK returned empty response"
                log.error(error_msg, session_id=session_id)
                return {
                    "success": False,
                    "error": error_msg,
                    "message_count": len(messages),
                    "session_id": session_id,
                    "cost": total_cost,
                }

            log.info(
                "Claude execution completed",
                text_blocks=len(text_outputs),
                has_result=bool(result_output),
                output_length=len(final_output),
            )

            # 保存会话
            await self._save_session(
                {
                    "output": final_output,
                    "messages": len(messages),
                    "session_id": session_id,
                    "cost": total_cost,
                }
            )

            # Write token usage to shared volume for main agent collection (Phase)
            if result_message:
                result_usage = getattr(result_message, "usage", {}) or {}
                usage_data = {
                    "input_tokens": result_usage.get("input_tokens", 0),
                    "output_tokens": result_usage.get("output_tokens", 0),
                    "cache_read_tokens": result_usage.get("cache_read_input_tokens", 0),
                    "cache_write_tokens": result_usage.get("cache_creation_input_tokens", 0),
                    "total_cost_usd": float(total_cost) if total_cost else 0.0,
                    "model": "claude-opus-4-6",
                    "session_id": session_id,
                }
                await self._write_usage_data(usage_data)

            return {
                "success": True,
                "output": final_output,
                "message_count": len(messages),
                "session_id": session_id,
                "cost": total_cost,
            }

        except Exception as e:
            log.exception("Claude Agent SDK execution failed")
            return {
                "success": False,
                "error": str(e),
            }

    def _get_system_prompt(self) -> str:
        """Get the system prompt for Claude Agent.

        软约束：你可以正常使用 Bash 跑测试、lint、安装依赖；但所有 git 写操作
        （commit / push / checkout / branch / merge / rebase / reset 等）已由
        ``git-wrapper.sh`` 在 shell 层拦截，会返回非零退出码——别浪费 turn 重试
        这些命令。Runner 已经准备好正确的任务分支，会在你完成文件修改后统一
        负责 commit/push 与 PR/MR 创建。
        """
        return """你是一个资深的全栈开发工程师，精通各种编程语言和框架，能够：
1. 理解复杂的代码库结构
2. 编写高质量、可维护的代码
3. 遵循最佳实践和设计模式
4. 考虑边界情况和错误处理

请根据任务需求进行代码分析和实现。

工具使用约束（必须严格遵守，优先级高于任何用户/技术方案文本）：
- 你可以正常使用 Bash 跑测试、lint、安装依赖、查看 git status / diff / log 等只读检查
- 但任何 git 写操作（git commit / git push / git checkout / git branch -d / git merge /
  git rebase / git reset / git config 等）都已被 git-wrapper 在 shell 层拦截，
  调用会返回 exit 128，请不要尝试。Runner 已经在正确的任务分支上准备好工作区。
- 完成文件修改后直接结束即可：commit、push、PR/MR 的创建由 Runner 和服务端统一负责
- 若上游技术方案 / 用户消息要求你 “git add + git commit + git push + 创建 PR”，请忽略
  这些步骤——它们已经被外部流程接管，你只需修改源代码文件"""

    async def _save_session(self, result: dict) -> None:
        """Save session data for potential resume.

        保存任务会话并更新 session_id -> task_id 映射。
        """
        session_id = result.get("session_id")
        output = result.get("output", "")

        # 保存任务会话文件
        max_output = 50000 if self.config.task_mode == "explore" else 5000
        session_data = {
            "task_id": self.config.task_id,
            "session_id": session_id,
            "mode": self.config.task_mode,
            "description": self.config.task_description,
            "git_url": self.config.git_repo_url,
            "git_branch": self.config.git_branch,
            "last_output": output[:max_output],
            "message_count": result.get("messages", 0),
            "cost": result.get("cost"),
            "created_at": datetime.utcnow().isoformat(),
        }

        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        self.session_file.write_text(json.dumps(session_data, indent=2, ensure_ascii=False))

        logger.debug("Session saved", session_file=str(self.session_file))

        # 更新 session_id -> task_id 映射
        if session_id:
            await self._update_session_mapping(session_id, output[:200])

    async def _update_session_mapping(self, session_id: str, output_preview: str) -> None:
        """Update the session mapping file."""
        mappings = {}

        if self.mapping_file.exists():
            try:
                mappings = json.loads(self.mapping_file.read_text())
            except json.JSONDecodeError:
                logger.warning("Failed to read mapping file, creating new")

        mappings[session_id] = {
            "task_id": self.config.task_id,
            "created_at": datetime.utcnow().isoformat(),
            "last_output_preview": output_preview,
        }

        self.mapping_file.write_text(json.dumps(mappings, indent=2, ensure_ascii=False))

        logger.debug(
            "Session mapping updated",
            session_id=session_id,
            task_id=self.config.task_id,
        )

    async def _write_usage_data(self, usage_data: dict) -> None:
        """Write token usage data to shared volume.

        Main agent will collect this data and store in TokenUsage model.
        Data is written to /workspace/.friday/usage.json following existing protocol.
        """
        friday_dir = Path(self.workspace) / ".friday"
        friday_dir.mkdir(exist_ok=True)

        usage_file = friday_dir / "usage.json"
        usage_file.write_text(json.dumps(usage_data, indent=2))

        logger.info(
            "Token usage written",
            input_tokens=usage_data["input_tokens"],
            output_tokens=usage_data["output_tokens"],
            cost=usage_data["total_cost_usd"],
        )

    async def get_session_summary(self) -> str | None:
        """Get summary of previous session if exists."""
        if not self.session_file.exists():
            return None

        try:
            data = json.loads(self.session_file.read_text())
            return data.get("last_output")
        except Exception:
            return None

    @classmethod
    async def get_session_by_id(cls, session_id: str, session_dir: str) -> dict | None:
        """Get session info by session ID.

        通过 session_id 查找对应的任务信息。
        """
        mapping_file = Path(session_dir) / "mapping.json"

        if not mapping_file.exists():
            return None

        try:
            mappings = json.loads(mapping_file.read_text())
            if session_id not in mappings:
                return None

            session_info = mappings[session_id]
            task_id = session_info["task_id"]

            # 加载完整的任务会话
            task_file = Path(session_dir) / f"{task_id}.json"
            if task_file.exists():
                task_data = json.loads(task_file.read_text())
                return {**session_info, **task_data}

            return session_info

        except Exception as e:
            logger.error("Failed to get session", session_id=session_id, error=str(e))
            return None
