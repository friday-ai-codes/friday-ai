"""AIPlanGenerationNode - AI-powered technical plan generation workflow node.

Orchestrates multi-repository analysis and generates structured technical plans
via LLM-driven tool scheduling. Supports iterative refinement through Feishu
card interactions with verify_plan validation loop.
"""

import json
import os
import re
from typing import Any, ClassVar, Final

import structlog

from agents.core.result import AgentResult
from prompts.keys import PromptSlugs
from prompts.services import get_active_prompt
from workflows.nodes.ai.base_agent import AIAgentBaseNode
from workflows.nodes.base import (
    ExecutionContext,
    NodePort,
    NodeResult,
    PortType,
)
from workflows.nodes.registry import register_node
from workflows.schemas.technical_plan import (
    TECHNICAL_PLAN_JSON_SCHEMA,
    validate_technical_plan,
)

logger = structlog.get_logger()


# implementation Task 1: 从原 get_system_prompt f-string 抽取为模块级 Final[str]
# 供 0002 data migration 跨 app import 作为 seed；{schema_json} 改为 {{schema_json}} Jinja2 占位符
# 字节级与原 f-string 等价(除了 schema_json 占位符从 {schema_json} → {{schema_json}})
_PLAN_GENERATION_BASE_PROMPT: Final[
    str
] = """你是一位资深技术方案架构师，负责分析需求并生成结构化技术方案。

## 角色与职责

你需要：
1. 理解用户的需求描述
2. 分析关联仓库的代码结构和依赖关系
3. 生成符合规范的结构化技术方案
4. 通过 verify_plan 验证后，调用 submit_technical_plan 工具提交最终方案

注意：方案的飞书文档生成、卡片推送与人工审批均由下游独立节点
（`human_approval(mode=plan_feishu)`、`feishu_doc_create`、`notify_feishu_im`）负责，
本节点**只专注产出方案本身**，不要自行推送或等待审批。

## 工作流程

### 第一阶段：需求分析与方案生成

1. **分析需求**：仔细阅读用户的需求描述和上游节点提供的上下文
2. **仓库分析**：使用 search_repository_code 工具分析相关仓库的代码结构
   - 有依赖关系的仓库串行分析（先分析被依赖方）
   - 无依赖关系的仓库可以交替分析
3. **生成方案**：基于分析结果，生成完整的技术方案（结构化对象）

### 第二阶段：验证并提交（结构化工具调用，强约束）

4. **调用 verify_plan**：将生成的方案传给 verify_plan 工具验证
5. **处理验证结果**：
   - 验证失败（valid=false）：根据错误信息修正方案，重新验证（**最多重试 3 轮**）
   - 验证通过（valid=true）：调用 **submit_technical_plan** 工具，以结构化入参 `plan`
     提交最终方案。这是方案产出的**唯一终止动作**。
6. 提交后用一句话简短确认即可结束，**不要**把方案 JSON 再写进文本回复。

### 终止条件

- 调用 submit_technical_plan 成功提交方案（信息充分时）
- 调用 request_clarification 发起澄清（信息不足时）

### 重要规则（务必遵守）

- **方案只能通过 submit_technical_plan 工具提交**，禁止把方案 JSON 写进自由文本 / ```json``` 代码块。
  下游严格从工具调用入参读取结构化方案；写进文本不会被采纳。
- 如果需求描述不清晰、信息不足或存在歧义，**不要猜测、不要自行假设**：立即调用
  **request_clarification** 工具，以结构化入参传入 `reason`（原因）与 `questions`（待补充问题列表），
  然后结束。系统会据此分流到下游人工处理节点（need_clarification 出口）。
  **本节点不直接向用户提问**，也不要把澄清内容写进文本回复。
- 信息充分时正常生成方案并 verify_plan 通过后调用 submit_technical_plan；此时**不要**调用 request_clarification。
- 你的每一轮迭代都应该调用至少一个工具（search_repository_code、verify_plan、submit_technical_plan 等），不要空转。

## 方案结构（submit_technical_plan 的 plan 入参必须符合以下 JSON Schema）

```json
{{schema_json}}
```

### 关键字段说明

- `title`: 方案标题，清晰描述方案主题
- `summary`: 方案摘要，work-item 字概述方案内容和关键决策
- `execution_plan`: 任务列表，每个任务必须指定目标仓库和分支策略
- `execution_plan[].coding_instruction`: 详细的编码指令，供下游 AI 编码节点使用

## 注意事项

- 每个任务必须绑定一个仓库（repository_id + repository_name）
- 任务间的依赖关系通过 dependencies 字段声明
- coding_instruction 应该足够详细，让不了解上下文的 AI 也能执行
- 方案验证失败时仔细阅读错误信息，针对性修正"""


@register_node
class AIPlanGenerationNode(AIAgentBaseNode):
    """AI 技术方案生成节点。

    通过 Orchestrator Agent 编排多仓库分析，自动生成结构化技术方案。
    专注产出 `TechnicalPlan`（含 markdown），不负责飞书推送/审批——
    飞书文档生成、卡片推送与人工审批均交由下游独立节点
    （`human_approval(mode=plan_feishu)` / `feishu_doc_create` / `notify_feishu_im`）。

    Workflow: 分析需求 → 调度工具分析仓库 → 生成方案 → verify_plan 验证
    → 失败则重试(最多3轮) → 输出最终方案（下游节点接管审批/推送）
    """

    node_type: ClassVar[str] = "ai_plan_generation"
    display_name: ClassVar[str] = "AI 方案生成"
    description: ClassVar[str] = "AI 自动跨仓库分析需求，生成结构化技术方案"
    icon: ClassVar[str] = "file-text"

    # 子步骤声明：分析需求 → 生成计划 → 审查计划
    sub_steps: ClassVar[list[tuple[str, str]]] = [
        ("analyze", "分析需求"),
        ("generate_plan", "生成计划"),
        ("review", "审查计划"),
    ]

    def __init__(self) -> None:
        """初始化实例，声明 implementation 预渲染 base_prompt 实例属性。"""
        super().__init__()
        # execute() 预渲染结果注入口；get_system_prompt 从此读取
        self._precomputed_base_prompt: str | None = None
        self._similar_history_markdown: str = ""

    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            **AIAgentBaseNode.config_schema["properties"],
            "system_prompt": {
                "type": "string",
                "title": "System Prompt (追加)",
                "description": "追加到默认 System Prompt 末尾的自定义指令",
                "default": "",
            },
            "user_prompt": {
                "type": "string",
                "title": "User Prompt",
                "description": "需求描述，支持模板变量 {{nodes.ID.field}}",
            },
            "include_repos": {
                "type": "array",
                "title": "必须包含的仓库",
                "items": {"type": "string"},
                "default": [],
            },
            "exclude_repos": {
                "type": "array",
                "title": "必须排除的仓库",
                "items": {"type": "string"},
                "default": [],
            },
            "max_iterations": {
                "type": "integer",
                "title": "最大迭代轮次",
                "description": "Agent Loop 最大迭代次数（方案生成需要更多轮次）",
                "default": 50,
                "minimum": 10,
                "maximum": 200,
            },
            "timeout_minutes": {
                "type": "integer",
                "title": "超时时间 (分钟)",
                "description": "方案生成的最大超时时间（默认 30 分钟，方案生成涉及多轮工具调用需要更长时间）",
                "default": 30,
                "minimum": 5,
                "maximum": 120,
            },
            "enabled_tools": {
                "type": "array",
                "title": "额外工具",
                "description": "除默认工具外额外启用的工具名称",
                "items": {"type": "string"},
                "default": [],
            },
            "auto_inject_similar_history": {
                "type": "boolean",
                "title": "自动注入相似历史交付",
                "default": True,
            },
            "similar_history_top_k": {
                "type": "integer",
                "title": "相似历史 top_k",
                "default": 5,
                "minimum": 1,
                "maximum": 20,
            },
            "similar_history_as_of": {
                "type": "string",
                "title": "相似历史 as_of",
                "description": "ISO8601 可选",
                "default": "",
            },
        },
        "required": ["user_prompt"],
    }

    inputs: ClassVar[list[NodePort]] = [
        NodePort(
            name="default",
            label="需求输入",
            port_type=PortType.OBJECT,
            required=False,
            description="上游节点输出，可在模板中通过 {{nodes.ID.field}} 引用",
        ),
    ]

    outputs: ClassVar[list[NodePort]] = [
        NodePort(
            name="default",
            label="技术方案",
            port_type=PortType.OBJECT,
            description="包含 plan（结构化方案）、final_answer、usage",
            schema={
                "type": "object",
                "properties": {
                    "plan": {"type": "object"},
                    "final_answer": {"type": "string"},
                    "usage": {"type": "object"},
                },
            },
        ),
        NodePort(
            name="need_clarification",
            label="需澄清",
            port_type=PortType.OBJECT,
            description=(
                "需求信息不足、需要人工补充时走此出口；"
                "输出 questions（待澄清问题列表）/ reason（原因）。"
                "可连接下游人工处理节点（如 human_approval / wait_feishu）。"
            ),
            schema={
                "type": "object",
                "properties": {
                    "need_clarification": {"type": "boolean"},
                    "questions": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                },
            },
        ),
        NodePort(
            name="error",
            label="失败",
            port_type=PortType.OBJECT,
            description="错误信息",
        ),
    ]

    # ===== Hook method overrides =====

    def get_system_prompt(self, context: ExecutionContext) -> str:
        """生成 Orchestrator 角色的 System Prompt。

        implementation Task 1/6 双路径：
        - 若 self._precomputed_base_prompt 已由 execute() 预填（Prompt Center 渲染结果），直接使用
        - 否则降级到模块级常量 _PLAN_GENERATION_BASE_PROMPT 的 .replace() 替换路径
          （供单元测试直接调用 hook 时使用）
        """
        precomputed = getattr(self, "_precomputed_base_prompt", None)
        if precomputed is not None:
            base_prompt = precomputed
        else:
            schema_json = json.dumps(TECHNICAL_PLAN_JSON_SCHEMA, ensure_ascii=False, indent=2)
            base_prompt = _PLAN_GENERATION_BASE_PROMPT.replace("{{schema_json}}", schema_json)

        # 追加用户自定义 system_prompt
        custom_prompt = context.node_config.get("system_prompt", "")
        if custom_prompt:
            custom_rendered = context.render_template(custom_prompt)
            base_prompt += f"\n\n## 额外指令\n\n{custom_rendered}"

        return base_prompt

    def get_user_prompt(self, context: ExecutionContext) -> str:
        """从 config 读取 user_prompt 并注入上下文。"""
        config = context.node_config
        user_prompt = context.render_template(config.get("user_prompt", ""))

        # 注入上游节点输出
        upstream_context = ""
        if context.input_data:
            upstream_context = "\n\n## 上游节点输出\n\n"
            upstream_context += json.dumps(context.input_data, ensure_ascii=False, indent=2)

        # 注入仓库过滤信息
        repo_context = ""
        include_repos: list[str] = config.get("include_repos", [])
        exclude_repos: list[str] = config.get("exclude_repos", [])
        if include_repos:
            repo_context += f"\n\n**必须包含的仓库:** {', '.join(include_repos)}"
        if exclude_repos:
            repo_context += f"\n\n**排除的仓库:** {', '.join(exclude_repos)}"

        history = getattr(self, "_similar_history_markdown", "") or ""
        history_block = f"\n\n{history}" if history else ""
        return f"{user_prompt}{upstream_context}{repo_context}{history_block}"

    def get_enabled_tools(self, context: ExecutionContext) -> list[str] | None:
        """返回方案生成节点需要的工具集。

        D1 解耦：移除「自动推送」职责的 send_plan_card / create_feishu_document——
        方案的飞书文档生成、卡片推送与审批挂起交由下游 human_approval(mode=plan_feishu)
        + feishu_doc_create + notify_feishu_im 承担，本节点只产出方案。
        保留 fetch_feishu_document（只读取材，非推送）。

        单一职责（need_clarification 出口）：移除节点内 ask_user_question——本节点不再
        就地挂起向用户提问（避免无 chat_id 时死循环）。信息不足时由 LLM 输出
        need_clarification JSON，节点经 need_clarification 出口分流到下游人工节点处理。
        """
        base_tools = [
            "verify_plan",
            "submit_technical_plan",
            "request_clarification",
            "fetch_feishu_document",
            "search_repository_code",
        ]

        # 加上 config 中额外指定的工具
        extra_tools: list[str] = context.node_config.get("enabled_tools", [])
        for t in extra_tools:
            if t not in base_tools:
                base_tools.append(t)

        return base_tools

    def get_max_iterations(self, context: ExecutionContext) -> int:
        """方案生成默认 50 轮（多轮迭代需要更多轮次）。"""
        value: int = context.node_config.get("max_iterations", 50)
        return value

    def map_output(self, result: AgentResult) -> dict[str, Any]:
        """从 AgentResult 提取方案并验证格式。

        权威来源：**工具调用入参**（不再依赖 LLM 在自由文本里输出 ```json``` 代码块）。
        优先级：
          1. request_clarification 工具调用 → need_clarification 出口
          2. submit_technical_plan 工具调用入参 → 结构化方案
          3. verify_plan 工具调用入参（兼容：现网 prompt 仍走 verify_plan）
          4. 兜底：解析 final_answer 文本（旧行为，防御未启用新工具的历史路径）

        产出方案时同时生成 ``plan_markdown``（干净的卡片渲染），并把 ``final_answer``
        覆盖为该渲染，使下游飞书卡片（推送方案到群）展示结构化内容而非 LLM 原始自由文本；
        原始文本保留在 ``raw_answer`` 供排障。
        """
        # 1. 工具调用：澄清优先
        clar_call = self._find_last_tool_call("request_clarification")
        if clar_call is not None:
            questions = clar_call.get("questions") or []
            if isinstance(questions, str):
                questions = [questions]
            questions = [str(q).strip() for q in questions if str(q).strip()]
            reason = str(clar_call.get("reason", ""))
            return {
                "need_clarification": True,
                "questions": questions,
                "reason": reason,
                "final_answer": self._render_clarification_markdown(questions, reason),
                "raw_answer": result.final_answer,
                "usage": result.usage,
            }

        # 2/3. 工具调用：提交方案（submit_technical_plan 优先，verify_plan 兼容兜底）
        plan_dict = self._extract_plan_from_tool_calls()

        # 4. 兜底：旧文本解析路径（未启用新工具的历史 prompt / 异常情况）
        if plan_dict is None:
            legacy_clar = self._extract_clarification(result.final_answer)
            if legacy_clar is not None:
                return {
                    "need_clarification": True,
                    "questions": legacy_clar["questions"],
                    "reason": legacy_clar["reason"],
                    "final_answer": self._render_clarification_markdown(
                        legacy_clar["questions"], legacy_clar["reason"]
                    ),
                    "raw_answer": result.final_answer,
                    "usage": result.usage,
                }
            plan_dict = self._extract_plan_from_result(result)

        if plan_dict is not None:
            is_valid, error_msg = validate_technical_plan(plan_dict)
            markdown = self._render_plan_markdown(plan_dict)
            output: dict[str, Any] = {
                "plan": plan_dict,
                "plan_markdown": markdown,
                # 覆盖 final_answer 为干净渲染：卡片模板多用 {{nodes.x.final_answer}}，
                # 原始 LLM 文本（含 "Now I have enough understanding..." 前言）移到 raw_answer。
                "final_answer": markdown,
                "raw_answer": result.final_answer,
                "usage": result.usage,
            }
            if not is_valid:
                logger.warning("plan_validation_failed_in_map_output", error=error_msg)
                output["error"] = f"方案格式验证警告: {error_msg}"
            return output

        # 无法提取结构化方案，返回原始输出
        return {
            "plan": None,
            "error": "未能从 Agent 工具调用 / 输出中提取结构化方案",
            "final_answer": result.final_answer,
            "raw_output": result.output,
            "usage": result.usage,
        }

    def _find_last_tool_call(self, tool_name: str) -> dict[str, Any] | None:
        """从 base_agent 捕获的工具调用历史里取最后一次指定工具的入参。"""
        calls = getattr(self, "_captured_tool_calls", None) or []
        for entry in reversed(calls):
            if isinstance(entry, dict) and entry.get("tool") == tool_name:
                tool_input = entry.get("input")
                return tool_input if isinstance(tool_input, dict) else None
        return None

    def _extract_plan_from_tool_calls(self) -> dict[str, Any] | None:
        """从工具调用入参提取结构化方案：submit_technical_plan 优先，verify_plan 兼容。"""
        submit = self._find_last_tool_call("submit_technical_plan")
        if submit is not None and isinstance(submit.get("plan"), dict):
            logger.info(
                "plan_captured_from_tool_call",
                category="sampling",
                component="workflow_node",
                tool="submit_technical_plan",
            )
            return submit["plan"]
        verify = self._find_last_tool_call("verify_plan")
        if verify is not None and isinstance(verify.get("plan"), dict):
            logger.info(
                "plan_captured_from_tool_call",
                category="sampling",
                component="workflow_node",
                tool="verify_plan",
            )
            return verify["plan"]
        return None

    @staticmethod
    def _render_clarification_markdown(questions: list[str], reason: str) -> str:
        """把澄清问题渲染为干净的飞书 lark_md 文本。"""
        lines = ["**为生成技术方案，请补充以下信息：**", ""]
        for i, q in enumerate(questions, 1):
            lines.append(f"{i}. {q}")
        if reason:
            lines.append("")
            lines.append(f"*原因：{reason}*")
        return "\n".join(lines)

    @staticmethod
    def _render_plan_markdown(plan: dict[str, Any]) -> str:
        """把结构化技术方案渲染为干净的飞书 lark_md 卡片正文。

        取代直接把 LLM 自由文本（含前言 + ```json``` 代码块）塞进卡片。
        """
        if not isinstance(plan, dict):
            return ""

        parts: list[str] = []
        title = str(plan.get("title", "")).strip()
        if title:
            parts.append(f"**{title}**")

        summary = str(plan.get("summary", "")).strip()
        if summary:
            parts.append(summary)

        tasks = plan.get("execution_plan") or []
        if isinstance(tasks, list) and tasks:
            parts.append(f"**📋 执行计划（共 {len(tasks)} 项）**")
            for i, task in enumerate(tasks, 1):
                if not isinstance(task, dict):
                    continue
                name = str(task.get("name", f"任务 {i}")).strip()
                repo = str(task.get("repository_name", "")).strip()
                head = f"**{i}. {name}**"
                if repo:
                    head += f"  `{repo}`"
                parts.append(head)
                desc = str(task.get("description", "")).strip()
                if desc:
                    parts.append(desc)
                instruction = str(task.get("coding_instruction", "")).strip()
                if instruction:
                    snippet = instruction if len(instruction) <= 300 else instruction[:300] + "…"
                    parts.append(f"> {snippet}")

        risks = plan.get("risks") or []
        if isinstance(risks, list) and risks:
            # 用 • 字面项目符号而非 Markdown `- ` 列表：lark_md 不支持列表语法，
            # markdown 组件也仅 ≥7.6 渲染；• 在所有客户端都按字面正常显示，跨版本稳定。
            bullets = "\n".join(f"• {str(r).strip()}" for r in risks if str(r).strip())
            parts.append(f"**⚠️ 风险**\n{bullets}")

        assumptions = plan.get("assumptions") or []
        if isinstance(assumptions, list) and assumptions:
            bullets = "\n".join(f"• {str(a).strip()}" for a in assumptions if str(a).strip())
            parts.append(f"**📝 假设**\n{bullets}")

        return "\n\n".join(p for p in parts if p)

    # ===== Execute override with sub-step tracking =====

    async def execute(self, context: ExecutionContext) -> NodeResult:
        """执行 AI 方案生成，包含子步骤状态追踪。

        子步骤：analyze（分析需求）→ generate_plan（生成计划）→ review（审查计划）。
        """
        from workflows.models.execution import SubStepStatus

        # 预渲染 base prompt（必须在 super().execute 之前）
        # super().execute 会调用 self.get_system_prompt(context) 读取 self._precomputed_base_prompt
        # 但若 user_prompt 为空，按惯例应立刻短路返回 failed，不做任何昂贵 DB/Prompt 查询
        if not context.node_config.get("user_prompt", "").strip():
            return NodeResult(
                status="failed",
                error="User Prompt 不能为空",
                next_handle="error",
            )

        schema_json = json.dumps(TECHNICAL_PLAN_JSON_SCHEMA, ensure_ascii=False, indent=2)
        project = await self._get_project(context)
        # contract retreat path: schema_json 体量 4KB+，如果走 render_prompt 会被
        # implementation services._sanitize_variables 的 1024 字符截断切成残缺 JSON。
        # 此处手工读取 active version body（或 fallback 常量）并做 str.replace，
        # 绕过 Jinja2 sandbox + 清洗流程。仍然保留 3 态语义：DB hit / DB empty /
        # PROMPT_CENTER_DISABLED_KEYS 命中（与 render_prompt 行为等价）。
        disabled_keys = {
            s.strip()
            for s in os.environ.get("PROMPT_CENTER_DISABLED_KEYS", "").split(",")
            if s.strip()
        }
        if PromptSlugs.AI_NODE_PLAN_GENERATION in disabled_keys:
            body_template = _PLAN_GENERATION_BASE_PROMPT
        else:
            version = await get_active_prompt(
                PromptSlugs.AI_NODE_PLAN_GENERATION,
                project_id=str(project.id) if project else None,
            )
            body_template = version.body if version is not None else _PLAN_GENERATION_BASE_PROMPT
        self._precomputed_base_prompt = body_template.replace("{{schema_json}}", schema_json)

        self._similar_history_markdown = ""
        if context.node_config.get("auto_inject_similar_history", True):
            rendered_prompt = context.render_template(
                context.node_config.get("user_prompt", "")
            ).strip()
            if rendered_prompt:
                # Phase 17 严格解析语义：as_of 模板渲染移出 best-effort try——
                # TemplateResolutionError 必须 fail-fast 直达 scheduler，
                # 不得被相似历史注入的吞错分支静默改写为"跳过注入继续执行"。
                as_of_raw = context.render_template(
                    context.node_config.get("similar_history_as_of", "") or ""
                )
                try:
                    from knowledge.exposure import format_search_results_markdown, parse_as_of
                    from knowledge.retrieval import DeliveryKnowledgeSearchService

                    as_of = parse_as_of(as_of_raw or None)
                    user = await self._get_user(context)
                    if user is not None:
                        svc = DeliveryKnowledgeSearchService()
                        project_id = str(project.id) if project else None
                        hits = await svc.search_similar(
                            rendered_prompt,
                            user=user,
                            top_k=int(context.node_config.get("similar_history_top_k") or 5),
                            project_ids=[project_id] if project_id else None,
                            as_of=as_of,
                        )
                        self._similar_history_markdown = format_search_results_markdown(
                            hits, as_of=as_of
                        )
                except Exception as exc:
                    logger.warning("plan_generation_similar_history_failed", error=str(exc))

        # 初始化子步骤记录
        await self._init_sub_steps(context)

        # Phase: 分析需求（prompt 构建和准备）
        await self.emit_sub_step(context, "analyze", SubStepStatus.RUNNING)
        await self.emit_sub_step(context, "analyze", SubStepStatus.COMPLETED)

        # Phase: 生成计划（Agent 执行）
        await self.emit_sub_step(context, "generate_plan", SubStepStatus.RUNNING)
        try:
            result = await super().execute(context)
        except Exception:
            await self.emit_sub_step(context, "generate_plan", SubStepStatus.FAILED)
            raise
        await self.emit_sub_step(context, "generate_plan", SubStepStatus.COMPLETED)

        # 信息不足分支：LLM 判定需澄清 → 走 need_clarification 出口分流到下游人工节点，
        # 本节点不产出方案、不投递知识库。
        if (
            result.status != "failed"
            and isinstance(result.output, dict)
            and result.output.get("need_clarification")
        ):
            await self.emit_sub_step(context, "review", SubStepStatus.RUNNING)
            await self.emit_sub_step(context, "review", SubStepStatus.COMPLETED)
            return NodeResult(
                status="completed",
                output=result.output,
                next_handle="need_clarification",
            )

        # Phase: 审查计划（结果验证）
        await self.emit_sub_step(context, "review", SubStepStatus.RUNNING)
        if result.status == "failed":
            await self.emit_sub_step(context, "review", SubStepStatus.FAILED)
        else:
            await self.emit_sub_step(context, "review", SubStepStatus.COMPLETED)

            # INGEST-01（14-04）：方案产出成功 → 投递统一摄取（只投 ID，零取材；
            # aschedule_ingestion 内部异常全吞，接线处不包 try/except）
            from knowledge import ingestion  # lazy import 防循环

            await ingestion.aschedule_ingestion(
                ingestion.IngestionRequest(
                    "workflow_plan",
                    f"{context.execution_id}:{context.node_id}",
                    "workflow_plan_generated",
                )
            )

        return result

    # ===== Private helpers =====

    def _extract_plan_from_result(self, result: AgentResult) -> dict[str, Any] | None:
        """尝试从 AgentResult 中提取技术方案 JSON。

        检查 metadata 中的 plan、output 列表中的工具调用结果、
        以及 final_answer 中的 JSON 块。
        """
        # 1. 检查 metadata 中是否直接有 plan
        if result.metadata and isinstance(result.metadata.get("plan"), dict):
            return result.metadata["plan"]

        # 2. 检查 output（工具调用历史）中的 verify_plan 结果
        if result.output and isinstance(result.output, list):
            for entry in reversed(result.output):
                if isinstance(entry, dict) and entry.get("tool") == "verify_plan":
                    tool_input = entry.get("input", {})
                    if isinstance(tool_input, dict) and "plan" in tool_input:
                        return tool_input["plan"]

        # 3. 从 final_answer 中提取 JSON 块
        if result.final_answer:
            return self._extract_json_from_text(result.final_answer)

        return None

    @staticmethod
    def _extract_clarification(text: str | None) -> dict[str, Any] | None:
        """从文本中识别「需澄清」JSON：``{"need_clarification": true, ...}``。

        支持 ```json``` 代码块或整段直接 JSON。命中返回归一化的
        ``{"questions": [...], "reason": ...}``；否则返回 None。
        """
        if not text:
            return None
        candidates = re.findall(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        candidates.append(text)
        for block in candidates:
            try:
                data = json.loads(block.strip())
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, dict) and data.get("need_clarification") is True:
                questions = data.get("questions") or []
                if isinstance(questions, str):
                    questions = [questions]
                return {
                    "questions": [
                        str(q).strip() for q in questions if str(q).strip()
                    ],
                    "reason": str(data.get("reason", "")),
                }
        return None

    @staticmethod
    def _extract_json_from_text(text: str) -> dict[str, Any] | None:
        """从文本中提取 JSON 对象（支持 ```json 代码块）。"""
        # 尝试 ```json ... ``` 格式
        json_blocks = re.findall(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        for block in json_blocks:
            try:
                data = json.loads(block.strip())
                if isinstance(data, dict) and "title" in data:
                    return data
            except json.JSONDecodeError:
                continue

        # 尝试直接解析整个文本
        try:
            data = json.loads(text.strip())
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

        return None
