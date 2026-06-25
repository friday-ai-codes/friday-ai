"""AI Variable Extractor Node - Extract variables from text using AI."""

import json
from typing import Final

import structlog

from prompts.keys import PromptSlugs
from prompts.services import render_prompt
from workflows.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeCategory,
    NodePort,
    NodeResult,
    PortType,
)
from workflows.nodes.registry import register_node

logger = structlog.get_logger(__name__)


# implementation contract:
# - 3 个真变量从 .format() 单花括号 → Jinja2 双花括号: {variable_definitions}/{input_text}/{additional_prompt}
# - 原 JSON 示例内 f-string 转义 {{/}} 剥回真实 {/}（不再经过 .format()）
# AI 提取提示词模板
EXTRACTION_PROMPT_TEMPLATE: Final[str] = """请从以下文本中提取指定的变量信息。

需要提取的变量：
{{variable_definitions}}

文本内容：
---
{{input_text}}
---

{{additional_prompt}}

请严格按照以下 JSON 格式返回提取结果：
```json
{
  "variables": {
    "variableKey": "提取的值",
    ...
  },
  "extraction_notes": {
    "variableKey": "提取说明或未能提取的原因"
  }
}
```

注意：
1. 如果某个变量无法从文本中提取，请在 extraction_notes 中说明原因，variables 中不要包含该 key
2. 提取的值应该尽量保持原文中的表述
3. 确保返回的是有效的 JSON 格式"""


@register_node
class AIVariableExtractorNode(BaseNode):
    """AI 变量提取节点

    使用 AI 从非结构化文本中智能提取变量。
    适用于从自然语言描述中提取结构化信息。
    """

    node_type = "ai_variable_extractor"
    display_name = "AI 变量提取"
    description = "使用 AI 从文本中智能提取变量"
    icon = "sparkles"
    category = NodeCategory.AI
    execution_mode = "server_local"

    config_schema = {
        "type": "object",
        "properties": {
            "input_source": {
                "type": "string",
                "title": "输入来源",
                "description": "输入文本的来源路径，如 $.data.content 或直接的模板字符串",
                "default": "",
            },
            "variables": {
                "type": "array",
                "title": "目标变量",
                "description": "要提取的变量定义列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "title": "变量标识符",
                            "description": "在模板中引用时使用的 key",
                            "pattern": "^[a-zA-Z_][a-zA-Z0-9_]*$",
                        },
                        "name": {
                            "type": "string",
                            "title": "显示名称",
                            "description": "变量的中文名称",
                        },
                        "desc": {
                            "type": "string",
                            "title": "提取描述",
                            "description": "指导 AI 如何提取该变量的描述（必填）",
                        },
                        "required": {
                            "type": "boolean",
                            "title": "是否必填",
                            "description": "如果为 true，提取失败时节点将报错",
                            "default": False,
                        },
                    },
                    "required": ["key", "name", "desc"],
                },
            },
            "additional_prompt": {
                "type": "string",
                "title": "额外指导",
                "description": "给 AI 的额外提取指导（选填）",
                "default": "",
            },
            "model": {
                "type": "string",
                "title": "模型",
                "description": "使用的 LLM 模型",
                "default": "",
            },
            # 高级设置
            "max_thinking_tokens": {
                "type": "integer",
                "title": "最大思考 Token 数",
                "description": "Claude 扩展思考的 token 上限，仅 Claude 模型支持。留空使用默认值",
                "minimum": 1024,
                "maximum": 128000,
            },
            "max_budget_usd": {
                "type": "number",
                "title": "预算上限 (USD)",
                "description": "单次调用的美元成本上限，留空不限制",
                "minimum": 0.01,
                "maximum": 100.0,
            },
            "provider_credential_id": {
                "type": "string",
                "format": "uuid",
                "title": "Provider 凭证（节点级）",
                "description": "指定本节点使用的凭证 ID，空则按空间/系统默认解析。",
                "default": "",
            },
        },
        "required": ["variables"],
    }

    inputs = [
        NodePort(
            name="text",
            label="文本输入",
            port_type=PortType.STRING,
            required=True,
            description="要提取变量的文本内容",
        )
    ]

    outputs = [
        NodePort(
            name="variables",
            label="提取结果",
            port_type=PortType.OBJECT,
            description="提取的变量摘要",
        )
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        """执行 AI 变量提取"""
        config = context.node_config
        variables_config = config.get("variables", [])
        additional_prompt = config.get("additional_prompt", "")
        model = config.get("model", "")
        input_source = config.get("input_source", "")
        max_thinking_tokens: int | None = config.get("max_thinking_tokens")

        if not variables_config:
            return NodeResult(
                status="completed",
                output={"variables": {}, "message": "无目标变量定义"},
            )

        # 获取输入文本
        input_text = self._get_input_text(context, input_source)

        if not input_text:
            return NodeResult(
                status="failed",
                error="无输入文本",
            )

        # 构建变量定义描述
        variable_definitions = "\n".join(
            f"- {v['key']} ({v['name']}): {v['desc']}" for v in variables_config
        )

        # implementation contract: 提取 space_id 传给 Prompt Center（允许空间级覆盖）
        space_id: str | None = None
        if context.workflow_execution:
            from workflows.models import WorkflowExecution

            we = await WorkflowExecution.objects.select_related(
                "workflow__space"
            ).aget(id=context.workflow_execution.id)
            if we.workflow and we.workflow.space:
                space_id = str(we.workflow.space.id)

        # 构建完整提示词（走 Prompt Center + fallback 双轨）
        prompt = await render_prompt(
            PromptSlugs.AI_NODE_VARIABLE_EXTRACTOR,
            project_id=space_id,
            variables={
                "variable_definitions": variable_definitions,
                "input_text": input_text,
                "additional_prompt": additional_prompt,
            },
            fallback=EXTRACTION_PROMPT_TEMPLATE,
        )

        try:
            # 调用 AI（task：传入节点级 provider_credential_id）
            response, usage = await self._call_llm(
                prompt=prompt,
                model=model,
                context=context,
                max_thinking_tokens=max_thinking_tokens,
                provider_credential_id=config.get("provider_credential_id", ""),
            )

            # 解析响应
            extracted_data = self._parse_ai_response(response)

            if not extracted_data:
                return NodeResult(
                    status="failed",
                    error="AI 响应解析失败",
                    output={"raw_response": response},
                )

            extracted_variables = extracted_data.get("variables", {})
            extraction_notes = extracted_data.get("extraction_notes", {})

            # 注册提取的变量
            registered_variables: dict[str, dict] = {}
            errors: list[str] = []

            for var_config in variables_config:
                key = var_config["key"]
                name = var_config["name"]
                desc = var_config.get("desc", "")
                required = var_config.get("required", False)

                if key in extracted_variables:
                    value = extracted_variables[key]

                    # 注册全局变量
                    context.set_global_variable(
                        key=key,
                        name=name,
                        value=value,
                        desc=desc,
                        required=required,
                    )

                    registered_variables[key] = {
                        "name": name,
                        "value": value,
                    }

                    logger.info(
                        "ai_variable_extracted",
                        key=key,
                        name=name,
                    )
                else:
                    # 变量未提取到
                    note = extraction_notes.get(key, "未能从文本中提取")
                    if required:
                        errors.append(f"必填变量 '{name}' ({key}) 提取失败: {note}")
                    else:
                        logger.warning(
                            "ai_variable_not_extracted",
                            key=key,
                            name=name,
                            note=note,
                        )

            if errors:
                return NodeResult(
                    status="failed",
                    error="; ".join(errors),
                    output={
                        "variables": registered_variables,
                        "errors": errors,
                        "usage": usage,
                    },
                )

            return NodeResult(
                status="completed",
                output={
                    "variables": registered_variables,
                    "count": len(registered_variables),
                    "usage": usage,
                    "message": f"成功提取 {len(registered_variables)} 个变量",
                },
            )

        except Exception as e:
            logger.error("ai_variable_extraction_failed", error=str(e))
            return NodeResult(
                status="failed",
                error=f"AI 提取失败: {e}",
            )

    def _get_input_text(self, context: ExecutionContext, input_source: str) -> str:
        """获取输入文本"""
        # 如果指定了 input_source，使用模板渲染
        if input_source:
            # 如果是 JSONPath 格式，尝试从输入数据提取
            if input_source.startswith("$."):
                from jsonpath_ng import parse

                try:
                    jsonpath_expr = parse(input_source)
                    # 从输入数据或上游输出中查找
                    data = context.input_data
                    if not data:
                        for output in context.previous_outputs.values():
                            if output:
                                data = output
                                break

                    if data:
                        matches = jsonpath_expr.find(data)
                        if matches:
                            return str(matches[0].value)
                except Exception:
                    pass

            # 尝试作为模板渲染
            return context.render_template(input_source)

        # 默认从输入数据获取
        input_data = context.input_data
        if isinstance(input_data, str):
            return input_data

        # 尝试获取常见的文本字段
        if isinstance(input_data, dict):
            for key in ["text", "content", "description", "body", "message"]:
                if key in input_data:
                    return str(input_data[key])
            # 如果都没有，序列化整个对象
            return json.dumps(input_data, ensure_ascii=False, indent=2)

        # 从上游节点获取
        for output in context.previous_outputs.values():
            if isinstance(output, str):
                return output
            if isinstance(output, dict):
                for key in ["text", "content", "response", "description"]:
                    if key in output:
                        return str(output[key])

        return ""

    def _parse_ai_response(self, response: str) -> dict | None:
        """解析 AI 响应"""
        try:
            # 尝试提取 JSON 块
            if "```json" in response:
                start = response.find("```json") + 7
                end = response.find("```", start)
                json_str = response[start:end].strip()
            elif "```" in response:
                start = response.find("```") + 3
                end = response.find("```", start)
                json_str = response[start:end].strip()
            else:
                json_str = response.strip()

            return json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("ai_response_parse_failed", response=response[:500])
            return None

    async def _call_llm(
        self,
        prompt: str,
        model: str,
        context: ExecutionContext,
        max_thinking_tokens: int | None = None,
        provider_credential_id: str = "",
    ) -> tuple[str, dict]:
        """单 turn ainvoke 收敛（implementation / contract）。

        build_chat_model(resolved).bind(temperature=0.3).ainvoke([HumanMessage])；
        aresolve_or_error 主路径（contract），仅 model 字段走 claude_config fallback；
        capabilities 兜底输出上限（contract，原硬编码 4096 删除）。

        **task 启用**：`provider_credential_id` 非空时，aresolve_or_error 传
        `node_config={"provider_credential_id": provider_credential_id}`；命中节点级
        FK 后做 API tier scope 校验（work item 安全硬化）：resolved.credential_id
        指向的凭证若 scope=="project" 且 scope_id != project.id → 拒绝。
        security mitigation-01 disposition=mitigate 真正落地。
        """
        # 分歧 D / Pitfall #5：函数体内 import（测试双 patch seam 可覆盖）
        from typing import Any

        from langchain_core.messages import AIMessage, HumanMessage

        from agents.llm_factory import build_chat_model
        from services.provider_config import ProviderConfigService, ProviderMissingError

        project = None
        if context.workflow_execution:
            from workflows.models import WorkflowExecution

            we = await WorkflowExecution.objects.select_related(
                "workflow__space"
            ).aget(id=context.workflow_execution.id)
            if we.workflow:
                project = we.workflow.space

        node_config: dict[str, Any] | None = None
        if provider_credential_id:
            node_config = {"provider_credential_id": provider_credential_id}

        result = await ProviderConfigService.aresolve_or_error(
            node_config=node_config, project=project
        )
        if isinstance(result, ProviderMissingError):
            raise ValueError(
                f"未配置 {result.missing_provider} Provider 凭证："
                f"{result.recommended_action}"
            )
        resolved = result

        # work item API tier 安全硬化（security mitigation-01 disposition=mitigate）：
        # 节点级凭证 scope 校验，防跨 project 越权。仅当命中节点级 FK 时检查。
        # 权威路径 server/system/models.py L102。
        if resolved.source == "node" and resolved.credential_id is not None:
            from system.models import ProviderCredential

            try:
                cred = await ProviderCredential.objects.aget(
                    id=resolved.credential_id
                )
            except ProviderCredential.DoesNotExist as exc:
                raise ValueError(
                    f"未配置 Provider 凭证：provider_credential_id="
                    f"{resolved.credential_id} 不存在"
                ) from exc
            space_id_str = str(project.id) if project is not None else ""
            if cred.scope == "project" and str(cred.scope_id) != space_id_str:
                raise ValueError(
                    f"未配置 {resolved.provider_type.value} Provider 凭证："
                    f"节点 provider_credential_id 指向他 project 凭证，"
                    f"已拒绝（scope 校验失败）"
                )

        # contract：model 字段空值 fallback
        # 从 resolved.extra.default_model 读取（替代 v8.1 aget_claude_config 路径）
        if not model:
            model = (resolved.extra or {}).get("default_model", "") or ""
        if not model:
            raise ValueError("未配置默认模型，请在系统设置或空间设置中配置默认模型")

        # contract：输出长度由 capabilities 兜底；contract：.bind(temperature=0.3)
        chat_model = build_chat_model(
            resolved=resolved,
            model=model,
            max_thinking_tokens=max_thinking_tokens,
            streaming=False,
        )
        ai_msg: AIMessage = await chat_model.bind(temperature=0.3).ainvoke(
            [HumanMessage(content=prompt)]
        )

        content = ai_msg.content
        if isinstance(content, list):
            text = "".join(
                str(b.get("text", ""))
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        else:
            text = str(content) if content else ""
        meta = getattr(ai_msg, "usage_metadata", None) or {}
        return text, {
            "input_tokens": int(meta.get("input_tokens", 0) or 0),
            "output_tokens": int(meta.get("output_tokens", 0) or 0),
        }
