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
from typing import Any, Literal

import structlog
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SdkMcpTool,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
    query,
)

from .config import TaskConfig
from .question_loop import (
    ASK_USER_MCP_SERVER_NAME,
    ask_user_allowed_tools,
    build_ask_user_mcp_server,
)
from .remote_tools import (
    REMOTE_MCP_SERVER_NAME,
    build_remote_tools_mcp_server,
    remote_allowed_tools,
)

logger = structlog.get_logger()

# SDK 支持的权限模式
PermissionModeType = Literal["default", "acceptEdits", "plan", "bypassPermissions"]

# 编码 agent 依赖的内建工具。claude-agent-sdk 的 ``allowed_tools`` 是排他白名单：
# 一旦显式设置，未列入的工具会被限制。挂载 RemoteTool MCP server 时若把
# allowed_tools 设成「仅远程工具名」，会连带禁掉 Bash/Edit/Write 等编码必需工具，
# 破坏 execute 模式。因此挂载远程工具时，必须把这些内建工具与远程工具一并列入
# （WR-02）。名称对齐 server/agents/sdk/runner.py 中枚举的内建工具集合。
_BUILTIN_CODING_TOOLS = [
    "Bash",
    "Read",
    "Edit",
    "Write",
    "MultiEdit",
    "Glob",
    "Grep",
    "LS",
    "TodoWrite",
    "WebFetch",
    "WebSearch",
]

# repo_summary 模式的只读分析工具白名单。不含 Write/Edit（无需改文件）、
# 不含 WebFetch/WebSearch（prompt 约束禁止网络请求）。Bash 用于 ls 等只读检查，
# git 写操作已被 git-wrapper.sh 在 shell 层拦截。
_READONLY_ANALYSIS_TOOLS = [
    "Bash",
    "Read",
    "Glob",
    "Grep",
    "LS",
    "TodoWrite",
]

# repo_summary 结构化提交工具：模型通过 tool call 的参数提交结果，
# 参数由 SDK 按 input_schema 校验，天然是合法 JSON——不再依赖模型在
# 文本里输出可解析的 JSON（prompt 约束不可靠）。
REPO_SUMMARY_MCP_SERVER_NAME = "repo-summary"
REPO_SUMMARY_TOOL_NAME = "submit_summary"

# 能力树节点采用扁平邻接表（parent_id 引用）而非嵌套结构：
# 递归 JSON Schema（$ref/$defs）在部分模型上校验/生成不稳定，扁平结构对
# LLM 更易产出且可被严格校验；server 端 callback 负责组装为嵌套树。
_TREE_NODE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "node_id": {
            "type": "string",
            "description": "节点唯一 ID，层级编号格式：0001 / 0001-01 / 0001-01-01",
        },
        "parent_id": {
            "type": ["string", "null"],
            "description": "父节点 node_id；顶层节点为 null",
        },
        "node_type": {
            "type": "string",
            "enum": ["sub_app", "module", "capability"],
            "description": (
                "节点层级语义：sub_app=monorepo 子应用（仅 monorepo 顶层使用）；"
                "module=代码中真实存在的模块/目录；capability=一条需求能描述清楚的功能点"
            ),
        },
        "title": {"type": "string", "description": "节点名称，用业务语言（中文优先）"},
        "summary": {"type": "string", "description": "节点职责的一句话描述（中文）"},
        "keywords": {
            "type": "array",
            "items": {"type": "string"},
            "description": "检索关键词（业务词 + 技术词混合）",
        },
        "paths": {
            "type": "array",
            "items": {"type": "string"},
            "description": "节点对应的真实目录/文件相对路径（必须实际存在，禁止虚构）",
        },
    },
    "required": ["node_id", "parent_id", "node_type", "title", "summary"],
}

_REPO_SUMMARY_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "overview": {"type": "string", "description": "项目总体描述，用中文撰写"},
        "tech_stack": {
            "type": "array",
            "items": {"type": "string"},
            "description": "主要技术栈列表，保留英文技术名称",
        },
        "is_monorepo": {
            "type": "boolean",
            "description": "是否为 monorepo（含多个子应用/子包）",
        },
        "tree": {
            "type": "array",
            "items": _TREE_NODE_SCHEMA,
            "description": (
                "层级能力树的扁平节点列表（parent_id 邻接表）。"
                "monorepo 仓库第一层必须是 sub_app 节点；"
                "之下为 module 节点（对应真实目录），叶子为 capability 节点"
                "（粒度=一条需求能描述清楚的功能点，如「消息撤回」）。"
                "总节点数不超过 80，树深不超过 4 层。"
            ),
        },
        "facets": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": (
                "语义分面标签 {维度: 取值}。仅当 prompt 提供了受控词表时填写，"
                "且只能从词表中选值；选不出填 '未分类'"
            ),
        },
        "modules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name", "description"],
            },
            "description": "（兼容字段）主要模块列表（不超过 10 个）",
        },
        "entry_points": {
            "type": "array",
            "items": {"type": "string"},
            "description": "主要入口文件路径",
        },
        "build_commands": {
            "type": "array",
            "items": {"type": "string"},
            "description": "构建命令",
        },
        "testing_commands": {
            "type": "array",
            "items": {"type": "string"},
            "description": "测试命令",
        },
        "conventions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "代码规范和约定",
        },
    },
    "required": ["overview", "tech_stack", "tree"],
}

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

    def __init__(self, config: TaskConfig, workspace: Path, callback: Any = None):
        """Initialize Claude runner with config and workspace path.

        Args:
            callback: 可选 CallbackClient —— coding 遇阻 HITL（ask_user）发问需要它；
                未传入时不挂 ask_user 工具（向后兼容，编码行为零回归）。
        """
        self.config = config
        self.workspace = workspace
        self.callback = callback
        self.session_file = Path(config.session_dir) / f"{config.task_id}.json"
        self.mapping_file = Path(config.session_dir) / "mapping.json"
        # repo_summary 模式下由 submit_summary 工具 handler 填充的结构化结果
        self._captured_summary: dict[str, Any] | None = None

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

        # 遇阻 HITL（Phase 47）：挂载 ask_user 供编码 agent 遇阻向人提问。
        # 向后兼容：无 callback / standalone 时 build_ask_user_mcp_server 返回 None，不挂工具。
        extra_mcp_servers: dict[str, Any] | None = None
        extra_allowed_tools: list[str] | None = None
        ask_user_server = (
            build_ask_user_mcp_server(self.config, self.callback)
            if self.callback is not None
            else None
        )
        if ask_user_server is not None:
            extra_mcp_servers = {ASK_USER_MCP_SERVER_NAME: ask_user_server}
            # allowed_tools 是排他白名单：挂 ask_user 时必须把编码内建工具一并列入，
            # 否则会连带禁掉 Bash/Edit/Write 等编码必需工具（WR-02 同因）。_execute_claude
            # 内对已存在项去重，故与 RemoteTool 白名单共存安全。
            extra_allowed_tools = [*_BUILTIN_CODING_TOOLS, *ask_user_allowed_tools()]

        result = await self._execute_claude(
            prompt=prompt,
            permission_mode="bypassPermissions",
            extra_mcp_servers=extra_mcp_servers,
            extra_allowed_tools=extra_allowed_tools,
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

    async def _handle_submit_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        """repo_summary 提交工具 handler — 捕获结构化结果到实例属性。"""
        self._captured_summary = dict(args)
        return {
            "content": [
                {
                    "type": "text",
                    "text": "仓库描述已提交，任务完成，请直接结束，不要再输出其它内容。",
                }
            ]
        }

    async def run_repo_summary_mode(self) -> dict:
        """Run Claude Agent in repo summary mode — 只读工具白名单 + 结构化提交工具。

        不再使用 permission_mode="plan"：plan 模式会让模型在结尾等待
        "用户批准计划"（无人值守容器里没人批准），以 "Please approve the
        plan ..." 之类的文本收尾，根本拿不到 JSON。改为 bypassPermissions +
        只读工具白名单（无 Write/Edit），并通过进程内 MCP 工具
        submit_summary 捕获结构化结果——工具参数由 SDK 按 schema 校验，
        不再依赖模型在文本里输出合法 JSON。
        """
        log = logger.bind(task_id=self.config.task_id, mode="repo_summary")
        log.info("Starting repo summary mode execution with claude-agent-sdk")

        self._captured_summary = None

        # monorepo 子项目静态发现：事实清单注入 prompt，约束树第一层骨架
        from .workspace_facts import discover_workspace_facts, format_facts_prompt_section

        try:
            workspace_facts = discover_workspace_facts(self.workspace)
        except Exception as exc:  # noqa: BLE001 — 发现失败不阻塞描述生成
            log.warning("workspace_facts_discovery_failed", error=str(exc))
            workspace_facts = {"is_monorepo": False, "sub_projects": []}

        summary_server = create_sdk_mcp_server(
            name=REPO_SUMMARY_MCP_SERVER_NAME,
            tools=[
                SdkMcpTool(
                    name=REPO_SUMMARY_TOOL_NAME,
                    description=(
                        "提交最终的仓库结构化描述。分析完成后必须调用本工具提交结果，"
                        "调用成功即代表任务完成。"
                    ),
                    input_schema=_REPO_SUMMARY_INPUT_SCHEMA,
                    handler=self._handle_submit_summary,
                )
            ],
        )

        submit_tool = f"mcp__{REPO_SUMMARY_MCP_SERVER_NAME}__{REPO_SUMMARY_TOOL_NAME}"
        # dispatch 时已渲染好的分析 prompt + 子项目事实约束 + 任务侧强制追加的
        # 提交方式说明。追加段优先级最高，覆盖 DB prompt 里旧的输出格式要求。
        facts_section = format_facts_prompt_section(workspace_facts)
        prompt = (
            f"{self.config.task_description}\n"
            f"{facts_section}\n\n"
            "## 结果提交方式（最高优先级，覆盖上文的任何输出格式要求）\n\n"
            f"分析完成后，必须调用 `{submit_tool}` 工具提交结构化结果，"
            "工具参数即为最终的仓库描述字段（含 tree 能力树节点列表）。\n"
            "- 不要把 JSON 写在普通文本回复里\n"
            "- 不需要任何人批准你的计划或结果，调用工具成功后直接结束任务"
        )

        # max_turns 不能太小：大型 monorepo 只读分析常需 30+ 轮工具调用，
        # 轮次用尽时 claude CLI 以非零码退出（SDK 抛 ProcessError），整次
        # 任务白跑（实测 15 轮在 monorepo 上 100% 触发）。
        try:
            result = await self._execute_claude(
                prompt=prompt,
                permission_mode="bypassPermissions",
                max_turns=40,
                extra_mcp_servers={REPO_SUMMARY_MCP_SERVER_NAME: summary_server},
                extra_allowed_tools=[*_READONLY_ANALYSIS_TOOLS, submit_tool],
                disallowed_tools=["Write", "Edit", "MultiEdit", "NotebookEdit"],
            )
        except Exception as exc:  # noqa: BLE001
            # CLI 非零退出（如 max-turns 用尽）不应吞掉已捕获的提交结果；
            # 未捕获到结果时给出可诊断的错误，而非裸 ProcessError。
            if not self._captured_summary:
                log.error("repo_summary_claude_failed", error=str(exc))
                return {
                    "success": False,
                    "error": (
                        f"Claude 执行中断（疑似轮次用尽仍未调用 submit_summary 提交结果）: {exc}"
                    ),
                }
            log.warning("repo_summary_claude_exit_after_submit", error=str(exc))
            result = {"success": True, "output": ""}

        # 只要工具捕获到结构化结果，就以它为准（即使模型最后没有任何文本输出，
        # _execute_claude 会因 empty response 误判失败——这里覆盖回 success）。
        if self._captured_summary:
            # 静态发现的子项目清单随结果回传，供 server 端校验
            # "monorepo 第一层 sub_app 与事实清单对齐"（LLM 输出不可信，事实可信）
            if workspace_facts.get("sub_projects"):
                self._captured_summary["discovered_sub_projects"] = [
                    sp["root"] for sp in workspace_facts["sub_projects"]
                ]
                self._captured_summary.setdefault("is_monorepo", workspace_facts["is_monorepo"])
            result["structured_summary"] = self._captured_summary
            result["output"] = json.dumps(self._captured_summary, ensure_ascii=False, indent=2)
            result["success"] = True
            result.pop("error", None)
        elif result.get("success"):
            log.warning(
                "repo_summary_tool_not_called",
                output_preview=str(result.get("output", ""))[:200],
            )

        log.info("Repo summary mode completed", success=result.get("success", False))
        return result

    async def _execute_claude(
        self,
        prompt: str,
        permission_mode: PermissionModeType = "bypassPermissions",
        max_turns: int | None = None,
        extra_mcp_servers: dict[str, Any] | None = None,
        extra_allowed_tools: list[str] | None = None,
        disallowed_tools: list[str] | None = None,
    ) -> dict:
        """Execute Claude Agent SDK with the given prompt.

        Args:
            extra_mcp_servers: 额外挂载的进程内 SDK MCP server（如 repo_summary
                的结构化提交工具），与 RemoteTool MCP server 合并。
            extra_allowed_tools: 追加到 allowed_tools 白名单的工具名。注意
                allowed_tools 是排他白名单——一旦非空，未列入的工具会被限制。
            disallowed_tools: 显式禁用的工具名（优先级高于 allowed_tools）。
        """
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
            main_model = self.config.claude_sonnet_model or self.config.claude_model or "sonnet"

            # RemoteTool 链路（Phase 11）：仅当 remote_tools + user_token + tools_endpoint
            # 三者俱全时构建进程内 SDK MCP server；否则 build_* 返回 None，options 不含
            # mcp_servers/allowed_tools，行为与现状完全一致（向后兼容）。
            mcp_server = build_remote_tools_mcp_server(
                self.config.remote_tools,
                self.config.tools_endpoint,
                self.config.user_token,
            )

            options_kwargs = dict(
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
            mcp_servers: dict[str, Any] = {}
            allowed_tools: list[str] = []
            if mcp_server is not None:
                mcp_servers[REMOTE_MCP_SERVER_NAME] = mcp_server
                # allowed_tools 是排他白名单：必须把内建编码工具与远程工具一并列入，
                # 否则挂载远程工具会连带禁掉 Bash/Edit/Write，破坏 execute 编码（WR-02）。
                allowed_tools = [
                    *_BUILTIN_CODING_TOOLS,
                    *remote_allowed_tools(self.config.remote_tools),
                ]
            if extra_mcp_servers:
                mcp_servers.update(extra_mcp_servers)
            if extra_allowed_tools:
                allowed_tools.extend(t for t in extra_allowed_tools if t not in allowed_tools)
            if mcp_servers:
                options_kwargs["mcp_servers"] = mcp_servers
            if allowed_tools:
                options_kwargs["allowed_tools"] = allowed_tools
            if disallowed_tools:
                options_kwargs["disallowed_tools"] = disallowed_tools
            options = ClaudeAgentOptions(**options_kwargs)

            log.info(
                "Executing Claude Agent SDK",
                permission_mode=permission_mode,
                workspace=str(self.workspace),
                has_api_key=bool(self.config.claude_api_key),
                has_base_url=bool(self.config.claude_base_url),
                has_user_token=bool(self.config.user_token),  # 脱敏：仅记 bool
                remote_tool_count=len(self.config.remote_tools),
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
                                    thinking = getattr(block, "thinking", "") or getattr(
                                        block, "signature", ""
                                    )
                                    if thinking:
                                        print(f"[task:text] [思考] {thinking[:500]}", flush=True)
                                    else:
                                        print(f"[task:block] {block_type}", flush=True)
                        elif isinstance(message, SystemMessage):
                            subtype = getattr(message, "subtype", "")
                            # 过滤掉无意义的 system 子类型
                            if subtype not in ("", "null", None):
                                print(f"[task:system] subtype={subtype}", flush=True)
                        elif isinstance(message, ResultMessage):
                            session_id = message.session_id
                            total_cost = message.total_cost_usd
                            if message.result:
                                result_output = message.result
                            print(
                                f"[task:result] session={session_id} cost=${total_cost}", flush=True
                            )
                        else:
                            # 跳过 UserMessage 等 SDK 内部消息，它们对用户无意义
                            if msg_type != "UserMessage":
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
        base = """你是一个资深的全栈开发工程师，精通各种编程语言和框架，能够：
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
        # Phase 51 GATE-02（D-51-4）：server gate 放行的 approved SDD 仓注入
        # FRIDAY_TASK_FOLLOW_OPENSPEC=true → 追加 openspec 指引段（独立 helper 便于测试）。
        # 默认 False → 返回 base 与现状逐字一致（零回归，D-51-5）。
        if bool(self.config.follow_openspec):
            return base + "\n\n" + self._openspec_guidance()
        return base

    def _openspec_guidance(self) -> str:
        """openspec 指引段（Phase 51-03，D-51-4）：指示 agent 按 openspec 流程编码。

        独立 helper（静态可信文本，无外部输入拼接，无 prompt 注入面），仅在
        ``follow_openspec`` 为真时被 ``_get_system_prompt`` 追加。
        """
        return """openspec / SDD 编码约定（本仓为 SDD/openspec 治理仓，必须遵循）：
- 本仓采用 openspec 规格驱动开发（SDD）：编码必须遵循 `openspec/` 目录下已批准（approved）的
  spec / change proposal，按 spec 描述的 delta 实现，不得偏离已批准规格自行扩张范围。
- 动手前优先查阅仓库内 openspec skill（`.claude/skills/` 已由运行时原生加载）与 `openspec/`
  下的 spec 文档 / change proposal，理解目标规格与变更增量后再实现。
- 实现须与已批准 spec 保持一致：spec 未覆盖的改动应谨慎，必要时在产出说明中标注与 spec 的关系。"""

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
