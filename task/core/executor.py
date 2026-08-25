"""Claude Agent SDK runner for task execution.

使用 claude-agent-sdk Python SDK 来执行 AI 开发任务。

权限模式：
- Plan 模式：使用 permission_mode="plan"（只读，不能修改文件）
- Execute 模式：使用 permission_mode="bypassPermissions"（跳过所有权限检查，包括 Bash 命令确认）

bypassPermissions 在 Docker 容器隔离环境中是安全的，可以支持无人值守执行。
"""

import asyncio
import json
import re
import time
import uuid
from collections import deque
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import structlog
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)

from .agent_submit_mcp import (
    SCENARIO_BLUEPRINT_REPO_PLAN,
    SCENARIO_REPO_SUMMARY,
    apply_capture_to_result,
    build_submit_mcp,
    known_scenarios,
)
from .config import TaskConfig
from .knowledge_tools import (
    KNOWLEDGE_MCP_SERVER_NAME,
    build_knowledge_mcp_server,
    knowledge_allowed_tools,
)
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


def _build_tool_mounts(
    config: TaskConfig,
    task_id: str,
    extra_mcp_servers: dict[str, Any] | None = None,
    extra_allowed_tools: list[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """构建 mcp_servers 与 allowed_tools —— **allowed_tools 合并唯一收口点**（103-02）。

    三源合并（remote + knowledge + extra/ask_user）全在此处，修复"knowledge 单独
    挂载而 remote 未挂时 builtin 丢失"的隐患面（WR-02 第七面）：

    - remote：remote_tools + tools_endpoint + user_token 三者俱全时挂载。
    - knowledge：knowledge_endpoint + user_token 俱全时挂载（7 工具白名单内建）。
    - **builtin 规则**：仅当 remote / knowledge（编码链 MCP server）挂载时才把
      ``_BUILTIN_CODING_TOOLS`` 全量并入 allowed_tools——claude-agent-sdk 的
      allowed_tools 是排他白名单，缺列会连带禁掉 Bash/Edit/Write 等编码必需工具，
      破坏 execute 模式（WR-02 前科）。**extra-only 挂载不并入 builtin**（103 审查
      WR-01）：repo_summary 等只读分析调用方自带白名单（明确排除 WebFetch/WebSearch
      网络工具），全量并入会把白名单排除降级为仅 prompt 约束。
    - extra（ask_user / repo_summary submit 等）：mcp_servers 并入，allowed_tools
      去重追加；调用方需要 builtin 时自行列入 extra_allowed_tools（ask_user 先例）。
    - 无任何挂载 → 返回 ``({}, [])``（options 不含 mcp_servers/allowed_tools，
      与现状逐字一致零回归）。

    Args:
        config: TaskConfig（读 remote_tools/tools_endpoint/user_token/
            knowledge_endpoint/knowledge_quota）。
        task_id: 任务 session 标识（dispatch 链 task_id 即 subagent session_id），
            经 X-Friday-Session-Id 头下发供服务端关联。
        extra_mcp_servers: 额外挂载的进程内 SDK MCP server。
        extra_allowed_tools: 追加的工具白名单（去重合并）。

    Returns:
        ``(mcp_servers, allowed_tools)``。
    """
    mcp_servers: dict[str, Any] = {}
    mounted_allowed: list[str] = []

    # RemoteTool 链路（Phase 11）：三要素俱全才挂载，否则 build 返回 None。
    remote_server = build_remote_tools_mcp_server(
        config.remote_tools,
        config.tools_endpoint,
        config.user_token,
    )
    if remote_server is not None:
        mcp_servers[REMOTE_MCP_SERVER_NAME] = remote_server
        mounted_allowed.extend(remote_allowed_tools(config.remote_tools))

    # 容器知识 MCP（Phase 103 AGENT-02）：endpoint + token 俱全才挂载（白名单内建）。
    knowledge_server = build_knowledge_mcp_server(
        config.knowledge_endpoint,
        config.user_token,
        task_id,
        config.knowledge_quota,
    )
    if knowledge_server is not None:
        mcp_servers[KNOWLEDGE_MCP_SERVER_NAME] = knowledge_server
        mounted_allowed.extend(knowledge_allowed_tools())

    if extra_mcp_servers:
        mcp_servers.update(extra_mcp_servers)

    if not mcp_servers:
        return {}, []

    # builtin 并入仅限编码链挂载（WR-02 保证 + WR-01 收口）：remote/knowledge 任一
    # 挂载 → 全量并入（排他白名单缺列即禁用编码必需工具）；extra-only → 沿用调用方
    # 自带白名单（repo_summary 只读分析不得解禁 WebFetch/WebSearch）。
    allowed_tools: list[str] = []
    if remote_server is not None or knowledge_server is not None:
        allowed_tools.extend(_BUILTIN_CODING_TOOLS)
    allowed_tools.extend(t for t in mounted_allowed if t not in allowed_tools)
    if extra_allowed_tools:
        allowed_tools.extend(t for t in extra_allowed_tools if t not in allowed_tools)
    return mcp_servers, allowed_tools


# repo_summary / blueprint 结构化提交已统一迁入共享工厂 `agent_submit_mcp`
# （唯一结构化提交渠道，见 260818-pt8 D-01/D-04）。此处不再保留 repo_summary 私有
# server/tool/schema 常量（旧的 repo-summary 私有提交 server 已删除）。

_CLAUDE_TRANSIENT_ERROR_MARKERS = (
    "server had an error while processing your request",
    "overloaded",
    "temporarily unavailable",
    "timeout",
    "timed out",
    "econnreset",
    "connection reset",
    "stream disconnected",
    "socket connection was closed unexpectedly",
    "connection was closed unexpectedly",
)


def _is_transient_claude_error(
    error: Exception,
    stderr_lines: list[str] | tuple[str, ...] = (),
) -> bool:
    """判断 Claude SDK/API 错误是否适合立即重试。

    Claude CLI 传输中断时，SDK 外层异常经常只剩 ``Command failed with exit code 1``，
    真正的 ``ECONNRESET`` / socket close 只写入 stderr。判定必须同时覆盖两处，否则
    最终 MCP 提交前的瞬时断连会被误判为不可重试的容器失败。
    """
    stderr_text = "\n".join(stderr_lines)
    message = f"{error}\n{stderr_text}".lower()
    return any(marker in message for marker in _CLAUDE_TRANSIENT_ERROR_MARKERS)


def _resume_options_after_transient(
    options: ClaudeAgentOptions,
    session_id: str,
) -> ClaudeAgentOptions:
    """瞬时中断后改用 resume，避免复用 ``session_id`` 被 CLI 判定为会话占用。"""
    return replace(options, session_id=None, resume=session_id)


# 工具入参上界。原值 300 会把 `get_repository_file(repository_id=…, file_path=…)` 这类
# 调用的 `file_path` 截没——而「读了哪个文件」正是过程明细最要紧的一维。
_MAX_TOOL_INPUT_CHARS = 2000

# 工具**结果**上界。结果里常是整段文件内容，全量打进 stdout 会把日志刷爆；这里只留
# 开头一段够判断「读到的是不是想要的东西」，完整内容仍在容器工作区里。
_MAX_TOOL_RESULT_CHARS = 1200


def _iter_blocks(content: Any) -> list[Any]:
    """`UserMessage.content` 可能是纯字符串或 block 列表，统一成列表。"""
    return content if isinstance(content, list) else []


def _tool_result_preview(content: Any) -> str:
    """工具结果 → 单行预览（截断并折掉换行）。

    ``ToolResultBlock.content`` 有三态：``str`` / ``list[dict]``（多模态分片）/ ``None``。
    列表态只取 ``text`` 字段拼接——图片等二进制分片对文本日志没有意义。
    """
    if content is None:
        return "(空)"
    if isinstance(content, list):
        parts = [
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("text")
        ]
        text = "\n".join(parts)
    else:
        text = str(content)
    total = len(text)
    preview = text[:_MAX_TOOL_RESULT_CHARS].replace("\n", "\\n")
    if total > _MAX_TOOL_RESULT_CHARS:
        preview += f"…（共 {total} 字符）"
    return preview


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

        当 ``config.submit_scenario`` 非空（blueprint research fitness / repo plan
        经 ``FRIDAY_TASK_SUBMIT_SCENARIO`` 注入）时，挂载共享 Agent→Friday MCP
        提交工具并**只**经 ``apply_capture_to_result`` 收口（空文本成功 / 未调用失败，
        与 repo_summary 同一实现点，禁止复制分支，见 D-06/D-07）。未设置 scenario
        时保持普通 explore 行为不变（无提交工具，零回归）。
        """
        # 仅当 submit_scenario 为真实非空字符串时启用结构化提交；非 str（如测试传入的
        # MagicMock 或误配）一律按普通 explore 处理，避免把非法值当未知场景直接判失败。
        raw_scenario = getattr(self.config, "submit_scenario", "")
        scenario = raw_scenario.strip() if isinstance(raw_scenario, str) else ""
        log = logger.bind(task_id=self.config.task_id, mode="explore", submit_scenario=scenario)
        log.info("Starting explore mode execution with claude-agent-sdk")

        prompt = self._build_explore_prompt()

        # 无 scenario：普通 explore，行为与现状完全一致。
        if not scenario:
            result = await self._execute_claude(
                prompt=prompt,
                permission_mode="bypassPermissions",
            )
            log.info("Explore mode completed", success=result.get("success", False))
            return result

        if scenario not in known_scenarios():
            log.error("explore_submit_scenario_unknown", scenario=scenario)
            return {
                "success": False,
                "error": f"unknown submit scenario: {scenario}",
                "submit_scenario": scenario,
            }

        submit = build_submit_mcp(scenario)
        prompt = f"{prompt}\n\n{submit.prompt_contract}"

        start = time.monotonic()
        log.info(
            "structured_submit_started",
            scenario=scenario,
            category="caller",
            component="task",
        )
        try:
            result = await self._execute_claude(
                prompt=prompt,
                permission_mode="bypassPermissions",
                max_turns=100 if scenario == SCENARIO_BLUEPRINT_REPO_PLAN else None,
                extra_mcp_servers=submit.mcp_servers,
                extra_allowed_tools=submit.allowed_tools,
            )
        except Exception as exc:  # noqa: BLE001
            # CLI 非零退出（如轮次用尽）不应吞掉已捕获的提交结果。
            result = {"success": False, "error": str(exc)}
        result = apply_capture_to_result(result, submit.capture, scenario=scenario)

        duration_ms = int((time.monotonic() - start) * 1000)
        if result.get("success"):
            log.info(
                "structured_submit_completed",
                scenario=scenario,
                duration_ms=duration_ms,
                category="caller",
                component="task",
            )
        else:
            log.warning(
                "structured_submit_failed",
                scenario=scenario,
                duration_ms=duration_ms,
                error_reason=result.get("error_reason"),
                category="caller",
                component="task",
            )
        log.info("Explore mode completed", success=result.get("success", False))
        return result

    def _build_plan_prompt(self) -> str:
        """Build the prompt for plan mode（方案调研：只读，产出可被人类 review 的实现方案）。"""
        return f"""# 任务（方案调研 / Plan）
{self.config.task_description}

# 你的目标
在**不修改任何文件**的前提下，调研代码库并产出一份可被人类 review 的实现方案。

# 步骤
1. 先建立全局认知：用 Glob / Grep 并行探索目录结构与关键模块，定位与任务相关的文件。
2. 读相关源码、追调用链与依赖、理解现有约定与数据流；必要时用只读命令观察运行行为。
3. 产出结构化方案：
   - 受影响文件清单：每项含「路径 + 变更类型（新增 / 修改 / 删除）+ 一句话说明」。
   - 分步实现步骤：每步说明改哪个文件的哪部分、怎么改，关键位置引用 `文件路径:行号`。
   - 复用的现有模式 / 库：优先复用仓库已有能力；不要引入仓库未依赖的新库，确需引入要说明理由。
   - 风险、边界情况，以及需要补充 / 调整的测试。
4. 关键且不确定的决策点，明确列出供人类确认，不要擅自假设。

# 约束
- 只读模式：不要修改文件、不建分支、不提交。
- 方案用 Markdown、中文输出，结构清晰、详略得当（够执行即可，避免冗长）。
"""

    def _build_explore_prompt(self) -> str:
        """Build the prompt for explore/analysis mode（深度分析：只读，有证据的结论）。"""
        return f"""# 深度分析任务
{self.config.task_description}

# 你的角色
资深代码分析师，对代码库做深入、有证据的分析。

# 步骤
1. 并行探索代码库结构，定位与问题相关的模块与文件。
2. 读关键源码、追调用链 / 依赖 / 测试，厘清架构与数据流。
3. 必要时用只读命令观察运行行为（不要修改任何东西）。
4. 产出结构化、有依据的分析结论；每个关键论断都引用 `文件路径:行号` 作为证据，不臆测。

# 约束
- 只读：不要修改任何源文件、不建分支、不提交。
- 只做分析与解释，不做实现。
- 用结构清晰的中文输出。
"""

    def _build_execute_prompt(self, plan: str | None = None) -> str:
        """Build the prompt for execute mode（开始编码：按方案实现，保留 git 硬约束）。"""
        base_prompt = f"""# 编码任务（开始编码 / Execute）
{self.config.task_description}

"""

        if plan:
            base_prompt += f"""# 已批准的技术方案（按此实现）
{plan}

# 说明
严格按上面已批准的方案实现。若方案与真实代码有冲突，以最小代价对齐方案意图，
并在最终说明里标注偏差与原因；不要擅自扩大方案范围。
"""
        else:
            base_prompt += """# 说明
按任务描述实现所需的代码改动；先快速调研（读邻近代码、定位相关文件）再动手。
"""

        base_prompt += """
# 实现准则
1. 遵循约定：先读邻近代码与配置，沿用项目既有框架 / 库 / 命名 / 风格；不要引入仓库未依赖的库。
2. 最小化改动：只动完成任务必需的部分，不顺手重构无关代码、不"镀金"，让人类容易 review。
3. 不写废话注释（仅在解释非显然的「为什么」时才注释）；必要时补充 / 调整相关测试。
4. 自验证：完成后若仓库有测试 / lint / typecheck，主动运行并修掉自己引入的问题。
5. 安全：绝不打印或提交密钥 / token。

# Git 边界（硬约束，已由外部流程接管）
6. 不要创建或切换分支（Do NOT create or switch branches）：Runner 已准备好正确的任务分支。
7. 不要执行 git commit（Do NOT run git commit）：Runner 会在你修改后统一创建 commit。
8. 不要 push（Do NOT push）：Runner 会推送已准备好的分支。
9. 不要创建 PR / MR（Do NOT create pull requests）：由 Friday Server 后续统一处理。
"""

        return base_prompt

    async def run_repo_summary_mode(self) -> dict:
        """Run Claude Agent in repo summary mode — 只读工具白名单 + 共享结构化提交工具。

        不再使用 permission_mode="plan"：plan 模式会让模型在结尾等待
        "用户批准计划"（无人值守容器里没人批准），以 "Please approve the
        plan ..." 之类的文本收尾，根本拿不到结构化结果。改为 bypassPermissions +
        只读工具白名单（无 Write/Edit），并通过**共享** Agent→Friday MCP 工厂
        （``agent_submit_mcp``，唯一结构化提交渠道）捕获结果——工具参数由 SDK 按
        schema 校验，天然是合法 JSON，不再依赖模型在文本里输出可解析 JSON，也不保留
        任何自由文本 JSON 兜底（D-01/D-02/D-04）。

        「空文本成功 / 未调用失败」统一经 ``apply_capture_to_result`` 收口，本模式
        **不复制**该分支（D-06/D-07）。
        """
        log = logger.bind(task_id=self.config.task_id, mode="repo_summary")
        log.info("Starting repo summary mode execution with claude-agent-sdk")

        # monorepo 子项目静态发现：事实清单注入 prompt，约束树第一层骨架
        from .workspace_facts import discover_workspace_facts, format_facts_prompt_section

        try:
            workspace_facts = discover_workspace_facts(self.workspace)
        except Exception as exc:  # noqa: BLE001 — 发现失败不阻塞描述生成
            log.warning("workspace_facts_discovery_failed", error=str(exc))
            workspace_facts = {"is_monorepo": False, "sub_projects": []}

        submit = build_submit_mcp(SCENARIO_REPO_SUMMARY)

        # dispatch 时已渲染好的分析 prompt + 子项目事实约束 + 工厂提交契约段。
        # 追加段优先级最高，覆盖 DB prompt 里旧的输出格式要求。
        facts_section = format_facts_prompt_section(workspace_facts)
        prompt = (
            f"{self.config.task_description}\n"
            f"{facts_section}\n\n"
            "## 分析范围（最高优先级硬约束）\n\n"
            f"待分析的目标仓库就在当前工作目录 `{self.workspace}`，你**只能**分析该目录"
            "（及其子目录）下的文件。\n"
            "- 严禁读取 / 分析工作目录之外的任何路径（例如 `/app`、`/usr`、`/home` 等"
            "容器自身的代码与系统文件）——那不是目标仓库。\n"
            "- 若当前工作目录为空或不含可识别的项目文件，说明仓库未就位：**不要**调用"
            "提交工具，直接如实说明「目标仓库工作目录为空/缺失」并结束，绝不能拿容器"
            "自身代码冒充目标仓库。\n\n"
            f"{submit.prompt_contract}"
        )

        start = time.monotonic()
        log.info(
            "repo_summary_submit_started",
            category="caller",
            component="task",
        )
        # max_turns 不能太小：大型 monorepo 只读分析常需 30+ 轮工具调用，
        # 轮次用尽时 claude CLI 以非零码退出（SDK 抛 ProcessError），整次
        # 任务白跑（实测 15 轮在 monorepo 上 100% 触发）。
        try:
            result = await self._execute_claude(
                prompt=prompt,
                permission_mode="bypassPermissions",
                max_turns=40,
                extra_mcp_servers=submit.mcp_servers,
                extra_allowed_tools=[*_READONLY_ANALYSIS_TOOLS, *submit.allowed_tools],
                # WebFetch/WebSearch 显式禁用（103 审查 WR-01）：只读分析容器禁网络
                # 出口是白名单级策略而非仅 prompt 约束——即使 knowledge/remote 同时
                # 挂载导致 builtin 并入，disallowed 优先级更高仍兜底。
                disallowed_tools=[
                    "Write",
                    "Edit",
                    "MultiEdit",
                    "NotebookEdit",
                    "WebFetch",
                    "WebSearch",
                ],
            )
        except Exception as exc:  # noqa: BLE001
            # CLI 非零退出（如 max-turns 用尽）不应吞掉已捕获的提交结果；收口交给
            # apply_capture_to_result（有 capture → 成功；无 → mcp_tool_not_called）。
            result = {"success": False, "error": str(exc)}

        # 静态发现的子项目清单随结果回传，供 server 端校验「monorepo 第一层 sub_app
        # 与事实清单对齐」（LLM 输出不可信，事实可信）。仅在已捕获结构化结果时补入。
        if submit.capture.value is not None and workspace_facts.get("sub_projects"):
            submit.capture.value["discovered_sub_projects"] = [
                sp["root"] for sp in workspace_facts["sub_projects"]
            ]
            submit.capture.value.setdefault("is_monorepo", workspace_facts["is_monorepo"])

        result = apply_capture_to_result(result, submit.capture, scenario=SCENARIO_REPO_SUMMARY)

        duration_ms = int((time.monotonic() - start) * 1000)
        if result.get("success"):
            log.info(
                "repo_summary_submit_completed",
                duration_ms=duration_ms,
                category="caller",
                component="task",
            )
        else:
            log.warning(
                "repo_summary_submit_failed",
                duration_ms=duration_ms,
                error_reason=result.get("error_reason"),
                category="caller",
                component="task",
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
        requested_session_id = self.config.resume_session_id or str(uuid.uuid4())

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

            # Claude Code stderr 转发到 stdout（被 docker logs 和 Runner StreamLogs 捕获），
            # 同时留存近 N 行环形缓冲：CLI 以非 0 退出码崩溃时（如 "Command failed with
            # exit code 1 / Check stderr output for details"），SDK 异常本身不含细节，
            # 这里把崩溃前的 stderr 尾部集中 dump，避免真因被海量 debug 日志淹没。
            stderr_tail: deque[str] = deque(maxlen=200)

            def _stderr_handler(line: str) -> None:
                stderr_tail.append(line)
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

            # 工具挂载合并收口（103-02）：remote + knowledge + extra 三源与 builtin
            # 的合并全在 _build_tool_mounts 单一构造函数内；无任何挂载 → ({}, [])，
            # options 不含 mcp_servers/allowed_tools，行为与现状完全一致（向后兼容）。
            # session_id 用 task_id（dispatch 链 task_id 即 subagent session_id）。
            mcp_servers, allowed_tools = _build_tool_mounts(
                self.config,
                self.config.task_id,
                extra_mcp_servers=extra_mcp_servers,
                extra_allowed_tools=extra_allowed_tools,
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
            # resume 续跑：transcript 已由 runner 在本次执行前还原到 SDK project 目录，
            # 这里传入 resume=session_id 让 SDK 接续上次对话（continue 语义，不 fork）。
            if self.config.resume_session_id:
                options_kwargs["resume"] = self.config.resume_session_id
                log.info(
                    "claude_sdk_resume_enabled",
                    resume_session_id=self.config.resume_session_id,
                )
            else:
                options_kwargs["session_id"] = requested_session_id
                log.info(
                    "claude_sdk_session_initialized",
                    sdk_session_id=requested_session_id,
                    category="caller",
                    component="task_executor",
                )
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
                has_knowledge_endpoint=bool(self.config.knowledge_endpoint),  # 仅记 bool
            )

            # 收集所有消息。只读/分析类任务遇到 Claude API 偶发 5xx/stream 中断时
            # 可重试整次请求；execute 模式可能已产生文件变更，不能自动重放。
            retryable_mode = permission_mode == "plan" or self.config.task_mode in (
                "explore",
                "repo_summary",
            )
            max_attempts = 3 if retryable_mode else 1
            # TTFT（per SLA-04）：成功 attempt 的首个 AssistantMessage 相对该 attempt
            # 起始的时延；解析不到（无 AssistantMessage）保持 None，usage 不带 ttft。
            ttft_ms: int | None = None
            for attempt in range(1, max_attempts + 1):
                messages = []
                text_outputs = []  # 收集所有 AssistantMessage 的文本
                session_id = requested_session_id
                total_cost = None
                result_output = None  # ResultMessage 的 result 字段
                attempt_start = time.monotonic()
                first_token_at: float | None = None

                try:
                    async for message in query(prompt=prompt, options=options):
                        messages.append(message)
                        msg_type = type(message).__name__

                        if isinstance(message, AssistantMessage):
                            if first_token_at is None:
                                first_token_at = time.monotonic()
                            for block in message.content:
                                if isinstance(block, TextBlock):
                                    text_outputs.append(block.text)
                                    preview = block.text[:500]
                                    print(f"[task:text] {preview}", flush=True)
                                elif isinstance(block, ToolUseBlock):
                                    tool_input = json.dumps(block.input, ensure_ascii=False)[
                                        :_MAX_TOOL_INPUT_CHARS
                                    ]
                                    print(f"[task:tool] {block.name}({tool_input})", flush=True)
                                else:
                                    # ThinkingBlock 等：只在拿到**明文** thinking 时打印。
                                    # ⛔ 绝不回落 `signature` —— 那是 Anthropic 对推理内容的
                                    # 加密签名（形如 `EoMFCnEIEBAB…` 的 base64），当作「思考」
                                    # 打出来是纯噪音，还会挤占日志上限把真步骤顶掉。
                                    block_type = type(block).__name__
                                    thinking = str(getattr(block, "thinking", "") or "").strip()
                                    if thinking:
                                        print(f"[task:text] [思考] {thinking[:500]}", flush=True)
                                    else:
                                        print(f"[task:block] {block_type}", flush=True)
                        elif isinstance(message, UserMessage):
                            # ⭐ 工具**结果**（SDK 把它裹在 UserMessage 里回传）。此前整条
                            # UserMessage 被跳过 ⇒ 过程明细只看得到「调用了什么」、看不到
                            # 「读回来什么」，排障时最关键的一半信息是缺的。
                            for block in _iter_blocks(message.content):
                                if not isinstance(block, ToolResultBlock):
                                    continue
                                flag = "error" if block.is_error else "ok"
                                preview = _tool_result_preview(block.content)
                                print(
                                    f"[task:tool_result] {flag} {block.tool_use_id} {preview}",
                                    flush=True,
                                )
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
                            print(f"[task:msg] {msg_type}", flush=True)
                    if first_token_at is not None:
                        ttft_ms = max(int((first_token_at - attempt_start) * 1000), 0)
                    break
                except Exception as e:
                    if not _is_transient_claude_error(e, stderr_tail):
                        # 非临时错误（如 claude CLI 以退出码 1 崩溃）：集中 dump stderr 尾部，
                        # 把被海量 debug 日志淹没的真实失败原因暴露出来，便于定位。
                        print(
                            f"[task:stderr-dump] CLI 异常退出，stderr 尾部 {len(stderr_tail)} 行 ↓",
                            flush=True,
                        )
                        for _ln in stderr_tail:
                            print(f"[task:stderr] {_ln}", flush=True)
                        print("[task:stderr-dump] ↑ stderr 尾部结束", flush=True)
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
                    options = _resume_options_after_transient(options, session_id)
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
            # 并主动 emit token_usage 回调（72-03 补全 task→回调断点）。
            if result_message:
                result_usage = getattr(result_message, "usage", {}) or {}
                usage_data: dict[str, Any] = {
                    "input_tokens": result_usage.get("input_tokens", 0),
                    "output_tokens": result_usage.get("output_tokens", 0),
                    "cache_read_tokens": result_usage.get("cache_read_input_tokens", 0),
                    "cache_write_tokens": result_usage.get("cache_creation_input_tokens", 0),
                    "total_cost_usd": float(total_cost) if total_cost else 0.0,
                    "model": self._resolve_usage_model(result_message, main_model),
                    "session_id": session_id,
                }
                # 富化可选元数据（缺则不放，交 server _derive_container_call_source 兜底；
                # call_source 由 server 服务端权威派生，容器不上报，避免 runner 篡改归因）。
                provider = getattr(self.config, "claude_provider", "") or getattr(
                    self.config, "provider_type", ""
                )
                if provider:
                    usage_data["provider"] = provider
                if ttft_ms is not None:
                    usage_data["ttft_ms"] = ttft_ms

                # 保留 usage.json（向后兼容兜底）
                await self._write_usage_data(usage_data)
                # 紧随其后主动 emit（best-effort：整段 try/except swallow，绝不影响任务返回）。
                if self.callback is not None:
                    try:
                        await self.callback.report_token_usage(usage_data)
                    except Exception as exc:  # noqa: BLE001 — emit 绝不反噬任务主流程
                        log.warning("report_token_usage_emit_failed", error=str(exc))

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
                "session_id": requested_session_id,
            }

    def _get_system_prompt(self) -> str:
        """Get the system prompt for Claude Agent.

        软约束：你可以正常使用 Bash 跑测试、lint、安装依赖；但所有 git 写操作
        （commit / push / checkout / branch / merge / rebase / reset 等）已由
        ``git-wrapper.sh`` 在 shell 层拦截，会返回非零退出码——别浪费 turn 重试
        这些命令。Runner 已经准备好正确的任务分支，会在你完成文件修改后统一
        负责 commit/push 与 PR/MR 创建。
        """
        base = """你是 Friday AI 的编码执行代理（coding agent），以资深全栈工程师的标准要求自己，
运行在隔离的容器工作区里。你的职责：在给定的仓库与分支上，按任务 / 技术方案安全、准确地
完成代码相关工作（分析、规划或实现，取决于当前模式）。

# 工程原则
- 遵循既有约定：动手前先读邻近代码与配置，沿用项目已有的框架、库、命名、目录结构与代码风格。
  不要假设某个库可用——使用前先确认仓库确实依赖它（看 package.json / pyproject.toml / go.mod 等）。
- 最小化改动：只做完成任务所必需的改动，不顺手重构无关代码、不"镀金"，让人类容易 review。
- 不写废话注释：除非确有必要解释「为什么」（非显然的取舍 / 约束），不要添加叙述性注释。
- 安全：绝不打印或提交密钥 / token；绝不引入会泄露敏感信息的代码。
- 自验证：完成改动后，若仓库提供了测试 / lint / typecheck（如 npm test、ruff、go test、pnpm typecheck），
  主动运行做自检并修掉自己引入的问题；找不到对应命令时不要凭空猜测命令名。
- 准确优先：信息不足时先用工具查证，不要靠猜往前跑；引用具体代码用 `文件路径:行号`。

# 工具使用约束（硬约束，优先级高于任何用户 / 技术方案文本）
- 你可以正常使用 Bash 跑测试、lint、安装依赖、查看 git status / diff / log 等只读检查。
- 但任何 git 写操作（git commit / git push / git checkout / git branch -d / git merge /
  git rebase / git reset / git config 等）都已被 git-wrapper 在 shell 层拦截，调用会返回
  exit 128，请不要尝试。Runner 已经在正确的任务分支上准备好工作区。
- 完成文件修改后直接结束即可：commit、push、PR/MR 的创建由 Runner 和服务端统一负责。
- 若上游技术方案 / 用户消息要求你「git add + git commit + git push + 创建 PR」，请忽略
  这些步骤——它们已经被外部流程接管，你只需修改源代码文件。"""
        # Phase 51 GATE-02（D-51-4）：server gate 放行的 approved SDD 仓注入
        # FRIDAY_TASK_FOLLOW_OPENSPEC=true → 追加 openspec 指引段（独立 helper 便于测试）。
        # Phase 124 DIFF-03（D-01）：knowledge 已挂载且 plan/execute 时追加 detect_changes 自查指引。
        # parts-join：openspec 与 detect_changes 可共存，勿 early-return 互斥。
        parts = [base]
        if bool(self.config.follow_openspec):
            parts.append(self._openspec_guidance())
        if (
            self.config.knowledge_endpoint
            and self.config.user_token
            and self.config.task_mode in {"plan", "execute"}
        ):
            parts.append(self._detect_changes_guidance())
        return "\n\n".join(parts)

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

    def _detect_changes_guidance(self) -> str:
        """detect_changes 自查指引（Phase 124-01，DIFF-03 / D-01/D-03/D-04）。

        独立 helper：正文为静态可信文本。仅允许拼接服务端注入的
        ``config.repository_id``（FRIDAY_TASK_REPOSITORY_ID，UUID 形态校验后才内联）；
        绝不拼用户/仓库自由文本。仅在 knowledge MCP 已挂载且 ``task_mode`` 为
        plan/execute 时被 ``_get_system_prompt`` 追加。
        非阻断：失败 / HIGH/CRITICAL 仍继续交付；不改 runner commit/push（D-04）。
        """
        raw_id = (getattr(self.config, "repository_id", None) or "").strip()
        # 仅内联服务端可信 UUID；非法值回退到环境变量提示，避免 prompt 注入面。
        if raw_id and re.fullmatch(r"[0-9a-fA-F-]{36}", raw_id):
            repo_clause = "`repository_id`=`" + raw_id + "`"
        else:
            repo_clause = "`repository_id`=本任务仓 UUID（见任务环境 FRIDAY_TASK_REPOSITORY_ID）"
        return (
            "影响面自查（编码完成后、结束 turn 前）：\n"
            "- 若已挂载 friday-knowledge，调用 `detect_changes`："
            + repo_clause
            + "，`compare`=当前功能分支"
            "（可选 `base_ref`=MR 目标分支，仅声明；勿传工作树 tip 当 base）。\n"
            "- 根据返回的受影响符号与风险决定是否继续修补；结果仅供决策参考。\n"
            "- 工具失败 / 未索引 / 配额用尽：记录原因并继续交付，不要重试刷屏；"
            "不要因为 HIGH/CRITICAL 而停止交付（提交由 Runner 负责）。"
        )

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

    @staticmethod
    def _resolve_usage_model(result_message: Any, main_model: str) -> str:
        """解析本次执行的真实模型名（72-03 富化）。

        优先 SDK ``ResultMessage`` 暴露的模型（``.model`` 或 ``.usage['model']``），其次本次
        执行实际传给 SDK 的主模型 ``main_model``，解析失败回退原硬编码默认（零回归）。
        """
        val = getattr(result_message, "model", None)
        if isinstance(val, str) and val:
            return val
        usage = getattr(result_message, "usage", None)
        if isinstance(usage, dict):
            m = usage.get("model")
            if isinstance(m, str) and m:
                return m
        if isinstance(main_model, str) and main_model:
            return main_model
        return "claude-opus-4-6"

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
