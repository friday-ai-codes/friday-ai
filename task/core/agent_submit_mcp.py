"""共享 Agent→Friday MCP 结构化提交工厂（**唯一结构化提交渠道**）。

三个场景经此工厂统一提交结构化结果：

- ``repo_summary``：仓库结构化描述（含能力树 / 章程）。
- ``blueprint_research_fitness``：蓝图调研的仓库适配度结论。
- ``blueprint_repo_plan``：蓝图阶段 2 的分仓实现方案（RepoPlan）。

设计要点（对齐 260818-pt8 锁定决策 D-01/D-02/D-04/D-06/D-07）：

- 模型经进程内 MCP server（``friday-submit``）的 tool call **参数**提交结果，参数由
  claude-agent-sdk 按 ``input_schema`` 校验，天然是合法 JSON —— 不再依赖模型在文本里
  输出可解析 JSON（prompt 约束不可靠），也**不保留**任何自由文本 JSON 解析 / fallback。
- 场景隔离：每次 ``build_submit_mcp`` 返回独立 ``CaptureStore``，A 场景的 capture 不会被
  B 场景污染；未知场景 ``get_scenario`` 抛 ``ValueError``。
- ``apply_capture_to_result`` 是「空文本成功 / 未调用失败」的**唯一收口**：各执行模式只调用
  它，禁止内联复制该分支。

⚠️ 观测（D-10）：handler 只记录 scenario/tool 标量，**绝不** dump 工具参数正文（可能含
仓库敏感内容）。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import structlog
from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server

logger = structlog.get_logger()

# ── 场景 ID（固定三值，禁止在别处硬编码字面量） ──────────────────────────────
SCENARIO_REPO_SUMMARY = "repo_summary"
SCENARIO_BLUEPRINT_FITNESS = "blueprint_research_fitness"
SCENARIO_BLUEPRINT_REPO_PLAN = "blueprint_repo_plan"

# 共享 MCP server 名 + 全名前缀。全名形如 ``mcp__friday-submit__submit_repo_summary``。
SUBMIT_MCP_SERVER_NAME = "friday-submit"

# ``apply_capture_to_result`` 未捕获时的稳定失败原因（服务端 / runner 可据此判定）。
MCP_TOOL_NOT_CALLED = "mcp_tool_not_called"
MAX_SUBMIT_PAYLOAD_BYTES = 512 * 1024
MAX_SUBMIT_STRING_CHARS = 50_000
MAX_SUBMIT_ARRAY_ITEMS = 500

# ── 与服务端同源的枚举（schema 对照测防漂移；task 侧不得运行时 import Django） ──
FITNESS_VERDICTS = ("suitable", "partial", "unsuitable")
FITNESS_ROLES = ("direct", "indirect")
REPO_PLAN_ROLES = ("direct", "indirect")
REPO_PLAN_CHANGE_TYPES = ("create", "modify", "remove", "indirect_refine")
REPO_PLAN_AVAILABILITY = ("existing", "needs_support")
# repo_plan.impl_items[] 逐项 required（与 blueprint_repo_plan_schema.py 同源）
REPO_PLAN_IMPL_ITEM_REQUIRED = ("item_id", "title", "change_type", "how")


# ── 数据结构 ────────────────────────────────────────────────────────────────


@dataclass
class CaptureStore:
    """一次执行内的结构化捕获槽（handler 写入，收口读取）。"""

    value: dict[str, Any] | None = None


@dataclass
class ScenarioSpec:
    """场景注册项：schema / tool 名 / 提示词契约。"""

    scenario: str
    tool_name: str
    description: str
    input_schema: dict[str, Any]
    prompt_contract: str


@dataclass
class BuiltSubmitMcp:
    """``build_submit_mcp`` 产物：挂载所需的一切 + 本次执行的捕获槽。"""

    scenario: str
    server_name: str
    tool_name: str
    full_tool_name: str
    mcp_servers: dict[str, Any]
    allowed_tools: list[str]
    prompt_contract: str
    capture: CaptureStore = field(default_factory=CaptureStore)


# ── 注册表 ──────────────────────────────────────────────────────────────────

_SCENARIOS: dict[str, ScenarioSpec] = {}


def register_scenario(spec: ScenarioSpec) -> None:
    """注册一个提交场景（同名覆盖，便于测试重载）。"""
    _apply_schema_limits(spec.input_schema)
    _SCENARIOS[spec.scenario] = spec


def _apply_schema_limits(schema: Any) -> None:
    """递归补齐进程内 MCP 的通用资源上界与 closed-object 契约。"""
    if not isinstance(schema, dict):
        return
    schema_type = schema.get("type")
    if schema_type == "string":
        schema.setdefault("maxLength", MAX_SUBMIT_STRING_CHARS)
    elif schema_type == "array":
        schema.setdefault("maxItems", MAX_SUBMIT_ARRAY_ITEMS)
    elif schema_type == "object" and isinstance(schema.get("properties"), dict):
        schema.setdefault("additionalProperties", False)
    _apply_schema_limits(schema.get("items"))
    for child in (schema.get("properties") or {}).values():
        _apply_schema_limits(child)


def validate_submit_payload(payload: dict[str, Any]) -> int:
    """序列化并校验提交体字节上界，返回实际 UTF-8 字节数。"""
    try:
        byte_len = len(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("payload_not_json_serializable") from exc
    if byte_len > MAX_SUBMIT_PAYLOAD_BYTES:
        raise ValueError(f"payload_too_large: {byte_len} bytes exceeds {MAX_SUBMIT_PAYLOAD_BYTES}")
    return byte_len


def get_scenario(scenario: str) -> ScenarioSpec:
    """取场景规格；未知场景抛 ``ValueError``（不静默兜底）。"""
    spec = _SCENARIOS.get(scenario)
    if spec is None:
        raise ValueError(f"unknown agent submit scenario: {scenario!r}")
    return spec


def known_scenarios() -> tuple[str, ...]:
    """已注册场景 ID（顺序不保证）。"""
    return tuple(_SCENARIOS.keys())


def full_tool_name(tool_name: str) -> str:
    """场景 tool 的 SDK 全名（``mcp__friday-submit__<tool>``）。"""
    return f"mcp__{SUBMIT_MCP_SERVER_NAME}__{tool_name}"


def build_submit_mcp(scenario: str) -> BuiltSubmitMcp:
    """按场景构建进程内 MCP server + allowed tool + 提示词契约 + 独立捕获槽。

    handler 只把 tool call 参数写进 ``capture.value``（``dict(args)``），返回一句完成提示。
    ⚠️ 绝不 dump 参数正文（观测脱敏 D-10）。
    """
    spec = get_scenario(scenario)
    capture = CaptureStore()

    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        started_at = time.monotonic()
        try:
            payload_bytes = validate_submit_payload(args)
        except ValueError as exc:
            logger.warning(
                "agent_submit_mcp_rejected",
                scenario=spec.scenario,
                tool=spec.tool_name,
                reason=str(exc).split(":", 1)[0],
                duration_ms=max(int((time.monotonic() - started_at) * 1000), 0),
                user_id="system",
                category="caller",
                component="task_agent_submit_mcp",
            )
            return {
                "content": [{"type": "text", "text": f"结构化提交被拒绝：{exc}"}],
                "is_error": True,
            }
        capture.value = dict(args)
        logger.info(
            "agent_submit_mcp_captured",
            scenario=spec.scenario,
            tool=spec.tool_name,
            payload_bytes=payload_bytes,
            duration_ms=max(int((time.monotonic() - started_at) * 1000), 0),
            user_id="system",
            category="caller",
            component="task_agent_submit_mcp",
        )
        return {
            "content": [
                {
                    "type": "text",
                    "text": "结构化结果已提交，任务完成，请直接结束，不要再输出其它内容。",
                }
            ]
        }

    server = create_sdk_mcp_server(
        name=SUBMIT_MCP_SERVER_NAME,
        tools=[
            SdkMcpTool(
                name=spec.tool_name,
                description=spec.description,
                input_schema=spec.input_schema,
                handler=_handler,
            )
        ],
    )
    full = full_tool_name(spec.tool_name)
    return BuiltSubmitMcp(
        scenario=spec.scenario,
        server_name=SUBMIT_MCP_SERVER_NAME,
        tool_name=spec.tool_name,
        full_tool_name=full,
        mcp_servers={SUBMIT_MCP_SERVER_NAME: server},
        allowed_tools=[full],
        prompt_contract=spec.prompt_contract,
        capture=capture,
    )


def apply_capture_to_result(
    result: dict[str, Any], capture: CaptureStore, *, scenario: str
) -> dict[str, Any]:
    """「空文本成功 / 未调用失败」的**唯一收口**（D-06/D-07）。

    - 有 capture → 写入 ``mcp_result`` + ``submit_scenario``，强制 ``success=True``、pop ``error``
      （即使 SDK 因空文本 / CLI 非零退出误判失败，也以结构化提交为准）。
    - 无 capture → ``success=False`` + 稳定 ``error_reason=mcp_tool_not_called``（**绝不**把普通
      文本当成功）。

    Args:
        result: ``_execute_claude`` 返回的结果 dict（原地补字段并返回）。
        capture: 本次执行的捕获槽。
        scenario: 场景 ID（写入 ``submit_scenario``）。
    """
    if capture.value is not None:
        result["mcp_result"] = capture.value
        result["submit_scenario"] = scenario
        result["success"] = True
        result.pop("error", None)
        result.pop("error_reason", None)
        return result

    result["success"] = False
    result["submit_scenario"] = scenario
    result["error_reason"] = MCP_TOOL_NOT_CALLED
    result.setdefault(
        "error",
        f"{MCP_TOOL_NOT_CALLED}: 未调用结构化提交工具（scenario={scenario}），拒绝以自由文本兜底",
    )
    return result


# ── 场景 schema 与提示词契约 ────────────────────────────────────────────────

# 能力树节点扁平邻接表（parent_id 引用）：递归 JSON Schema 在部分模型上不稳定，
# 扁平结构对 LLM 更易产出且可被严格校验；server 端 callback 负责组装为嵌套树。
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
        "charter": {
            "type": "object",
            "description": (
                "意图面章程（基于源码阅读一等产出）：职责定位、owned 业务域、"
                "边界禁区、落点偏好。禁止臆造无证据领域；有路径引用请写入 citations。"
            ),
            "properties": {
                "positioning": {"type": "string"},
                "owned_domains": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "domain": {"type": "string"},
                            "status": {"type": "string"},
                            "note": {"type": "string"},
                            "citations": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
                "boundaries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "rule": {"type": "string"},
                            "decided_by": {"type": "string"},
                            "citations": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
                "placement_preferences": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string"},
                            "target": {"type": "string"},
                            "note": {"type": "string"},
                        },
                    },
                },
                "audience": {"type": "string"},
                "form": {"type": "string"},
                "evolution": {"type": "string"},
            },
        },
    },
    "required": ["overview", "tech_stack", "tree"],
}

_REPO_SUMMARY_PROMPT_CONTRACT = (
    "## 结果提交方式（最高优先级，覆盖上文的任何输出格式要求）\n\n"
    f"分析完成后，必须调用 `{full_tool_name('submit_repo_summary')}` 工具提交结构化结果，"
    "工具参数即为最终的仓库描述字段（含 tree 能力树节点列表）。\n"
    "- 不要把 JSON 写在普通文本回复里\n"
    "- 不需要任何人批准你的计划或结果，调用工具成功后直接结束任务"
)

_FITNESS_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "fitness": {
            "type": "object",
            "properties": {
                "verdict": {
                    "type": "string",
                    "enum": list(FITNESS_VERDICTS),
                    "description": "适配度结论：suitable / partial / unsuitable",
                },
                "reasons": {"type": "array", "items": {"type": "string"}},
                "citations": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["verdict"],
        },
        "role_suggestion": {
            "type": "string",
            "enum": list(FITNESS_ROLES),
            "description": "direct=需要改动本仓 / indirect=只需了解或被依赖",
        },
        "responsibility": {"type": "string", "description": "本仓在本次需求里承担的职责"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "citations": {"type": "array", "items": {"type": "string"}},
                },
            },
            "description": "逐条描述与本次需求相关的现状（已有能力、缺口、约束）",
        },
        "research_summary": {"type": "string"},
        "proposed_changes": {"type": "array", "items": {"type": "object"}},
        "candidate_files": {"type": "array", "items": {"type": "object"}},
        "api_contracts_exposed": {"type": "array", "items": {"type": "object"}},
        "dependencies_on_other_repos": {"type": "array", "items": {"type": "object"}},
    },
    "required": ["fitness", "role_suggestion", "responsibility", "findings"],
}

_FITNESS_PROMPT_CONTRACT = (
    "## 结果提交方式（最高优先级，覆盖上文的任何输出格式要求）\n\n"
    f"分析完成后，必须调用 `{full_tool_name('submit_blueprint_fitness')}` 工具提交结构化结果"
    "（fitness / role_suggestion / responsibility / findings 等字段即工具参数）。\n"
    "- 不要把 JSON 写在普通文本回复里；citations 必须是真实读到的文件路径或符号，不要编造\n"
    "- 调用工具成功后直接结束任务"
)

_REPO_PLAN_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": list(REPO_PLAN_IMPL_ITEM_REQUIRED),
    "properties": {
        "item_id": {"type": "string", "minLength": 1},
        "title": {"type": "string", "minLength": 1},
        "change_type": {"type": "string", "enum": list(REPO_PLAN_CHANGE_TYPES)},
        "how": {"type": "string"},
        "files_touched": {"type": "array", "items": {"type": "string"}},
        "depends_on": {"type": "array", "items": {"type": "string"}},
        "test_strategy": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "string"}},
    },
}

# repo_plan 段：与服务端 BLUEPRINT_REPO_PLAN_SCHEMA 同源（required role/impl_items；
# repository_id 由服务端权威写入，容器不必强填，故不入本 schema required）。
_REPO_PLAN_SECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["role", "impl_items"],
    "properties": {
        "repository_id": {"type": "string"},
        "role": {"type": "string", "enum": list(REPO_PLAN_ROLES)},
        "responsibility": {"type": "array", "items": {"type": "object"}},
        "current_state": {"type": "array", "items": {"type": "object"}},
        "impl_items": {"type": "array", "items": _REPO_PLAN_ITEM_SCHEMA},
        "apis_provided": {"type": "array", "items": {"type": "object"}},
        "apis_consumed": {"type": "array", "items": {"type": "object"}},
        "local_impact": {"type": "object"},
        "risks": {"type": "array", "items": {"type": "object"}},
        "open_question_thread_ids": {"type": "array", "items": {"type": "string"}},
    },
}

_REPO_PLAN_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"repo_plan": _REPO_PLAN_SECTION_SCHEMA},
    "required": ["repo_plan"],
}

_REPO_PLAN_PROMPT_CONTRACT = (
    "## 结果提交方式（最高优先级，覆盖上文的任何输出格式要求）\n\n"
    f"分析完成后，必须调用 `{full_tool_name('submit_blueprint_repo_plan')}` 工具提交结构化结果，"
    "工具参数顶层键为 `repo_plan`，其值为本仓分仓实现方案。\n"
    "- 不要把 JSON 写在普通文本回复里；citations 必须真实，不要编造\n"
    "- 调用工具成功后直接结束任务"
)


# ── 内建三场景注册（import 副作用，与 node registry 同范式） ────────────────

register_scenario(
    ScenarioSpec(
        scenario=SCENARIO_REPO_SUMMARY,
        tool_name="submit_repo_summary",
        description=(
            "提交最终的仓库结构化描述。分析完成后必须调用本工具提交结果，调用成功即代表任务完成。"
        ),
        input_schema=_REPO_SUMMARY_INPUT_SCHEMA,
        prompt_contract=_REPO_SUMMARY_PROMPT_CONTRACT,
    )
)
register_scenario(
    ScenarioSpec(
        scenario=SCENARIO_BLUEPRINT_FITNESS,
        tool_name="submit_blueprint_fitness",
        description="提交本仓对本次需求的适配度调研结论。调用成功即代表任务完成。",
        input_schema=_FITNESS_INPUT_SCHEMA,
        prompt_contract=_FITNESS_PROMPT_CONTRACT,
    )
)
register_scenario(
    ScenarioSpec(
        scenario=SCENARIO_BLUEPRINT_REPO_PLAN,
        tool_name="submit_blueprint_repo_plan",
        description="提交本仓的分仓实现方案（RepoPlan）。调用成功即代表任务完成。",
        input_schema=_REPO_PLAN_INPUT_SCHEMA,
        prompt_contract=_REPO_PLAN_PROMPT_CONTRACT,
    )
)
