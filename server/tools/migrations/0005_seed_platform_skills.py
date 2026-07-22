"""种子两个平台多步 Skill + 7 个步骤 builtin 工具（LOOP-04 / 101-04）。

- ``pre_coding_research``：编码前调研 —— route_repositories → search_rag_chunks
  → search_delivery_knowledge → search_learning_cases。
- ``post_coding_capture``：编码后沉淀 —— summarize_branch → create_learning_case
  → report_project_knowledge。

步骤参数语义（tools/sources/skill.py 实现，101-04 Task 2）：**skill 顶层 arguments
透传合并进每一步、步内静态 arguments 优先**（``{**arguments, **step_args}``）。
故 skill input_schema 中声明的键（如 query / repository_id 等）会注入
每个步骤，步骤 handler ``**kwargs`` 容忍多余键、只取自己认识的键。

安全（101 CR-01）：``user_id`` 权限主体**不进 input_schema**——该键由
``RemoteToolExecuteView`` 以 PAT 所有者服务端权威注入，客户端传值一律被覆写，
绝不作为客户端可填参数对外声明。

范本照抄 0002_seed_builtin_tools（get_or_create + reverse 按名字删除）。
"""

from django.db import migrations

_STEP_TOOLS = [
    {
        "name": "route_repositories",
        "description": "按需求文本路由候选仓库（RepoRouterV2 两阶段推理式路由）",
        "handler": "tools.handlers.skill_steps.route_repositories",
        "timeout": 30,
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "需求 / 提问文本"},
                "top_k": {"type": "integer", "description": "候选仓库数上限", "default": 3},
                "repository_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "限定候选仓库范围（可选，缺省全库）",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_rag_chunks",
        "description": "对候选仓库执行 dense+sparse 混合语义检索（RAG chunks）",
        "handler": "tools.handlers.skill_steps.search_rag_chunks",
        "timeout": 30,
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "查询文本"},
                "repository_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "候选仓库 id 列表（可由 route_repositories 结果提供）",
                },
                "top_k": {"type": "integer", "description": "返回条数上限", "default": 10},
                "branch_name": {"type": "string", "description": "分支名（可选，缺省 base 分支）"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_delivery_knowledge",
        "description": "交付知识混合检索（DeliveryKnowledgeSearchService，user 权限主体 fail-closed）",
        "handler": "tools.handlers.skill_steps.search_delivery_knowledge",
        "timeout": 30,
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "查询文本"},
                "top_k": {"type": "integer", "description": "返回条数上限", "default": 5},
                "project_ids": {"type": "array", "items": {"type": "string"}},
                "repository_ids": {"type": "array", "items": {"type": "string"}},
                "entity_kinds": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_learning_cases",
        "description": "历史 learning case 向量检索（hint 提权 rerank，user 权限主体 fail-closed）",
        "handler": "tools.handlers.skill_steps.search_learning_cases",
        "timeout": 30,
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "查询文本"},
                "work_item_type": {"type": "string", "description": "工作项类型过滤（可选）"},
                "repo_hints": {"type": "array", "items": {"type": "string"}},
                "file_hints": {"type": "array", "items": {"type": "string"}},
                "symbol_hints": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "description": "返回条数上限", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "summarize_branch",
        "description": "分支 diff 摘要（files/risks/test_suggestions/mr_draft）",
        "handler": "tools.handlers.skill_steps.summarize_branch",
        "timeout": 60,
        "input_schema": {
            "type": "object",
            "properties": {
                "repository_id": {"type": "string", "description": "仓库 UUID"},
                "source_branch": {"type": "string", "description": "源分支"},
                "target_branch": {"type": "string", "description": "目标分支（缺省仓库默认分支）"},
                "max_files": {"type": "integer", "description": "文件数上限", "default": 30},
            },
            "required": ["repository_id", "source_branch"],
        },
    },
    {
        "name": "create_learning_case",
        "description": "由技术方案沉淀 learning case（入库 + 统一知识摄取入图）",
        "handler": "tools.handlers.skill_steps.create_learning_case",
        "timeout": 60,
        "input_schema": {
            "type": "object",
            "properties": {
                "technical_plan_id": {"type": "string", "description": "技术方案 UUID"},
                "outcome": {"type": "string", "description": "结果短词（如 success）"},
                "root_cause": {"type": "string", "description": "问题技术根因"},
                "solution_notes": {"type": "string", "description": "做法与原因"},
                "tests": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["technical_plan_id"],
        },
    },
    {
        "name": "report_project_knowledge",
        "description": "项目知识上报（MemoryService draft 路径，pending 草稿待人工确认）",
        "handler": "tools.handlers.skill_steps.report_project_knowledge",
        "timeout": 30,
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目 UUID"},
                "content": {"type": "string", "description": "沉淀内容"},
                "source_conversation_id": {"type": "string", "description": "来源会话 id（可选）"},
            },
            "required": ["project_id", "content"],
        },
    },
]

_SKILLS = [
    {
        "name": "pre_coding_research",
        "description": (
            "编码前调研：路由候选仓库 → 代码语义检索 → 交付知识检索 → 历史 learning case。"
            "顶层 arguments（query/repository_ids 等）透传合并进每一步。"
        ),
        "timeout": 120,
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        "config": {
            "steps": [
                {"tool_name": "route_repositories", "arguments": {}},
                {"tool_name": "search_rag_chunks", "arguments": {}},
                {"tool_name": "search_delivery_knowledge", "arguments": {}},
                {"tool_name": "search_learning_cases", "arguments": {}},
            ]
        },
    },
    {
        "name": "post_coding_capture",
        "description": (
            "编码后沉淀：分支 diff 摘要 → 沉淀 learning case → 项目知识上报。"
            "顶层 arguments（repository_id/source_branch/technical_plan_id 等）透传合并进每一步。"
        ),
        "timeout": 180,
        "input_schema": {
            "type": "object",
            "properties": {
                "repository_id": {"type": "string"},
                "source_branch": {"type": "string"},
                "target_branch": {"type": "string"},
                "technical_plan_id": {"type": "string"},
                "outcome": {"type": "string"},
                "root_cause": {"type": "string"},
                "solution_notes": {"type": "string"},
                "project_id": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["repository_id", "source_branch"],
        },
        "config": {
            "steps": [
                {"tool_name": "summarize_branch", "arguments": {}},
                {"tool_name": "create_learning_case", "arguments": {}},
                {"tool_name": "report_project_knowledge", "arguments": {}},
            ]
        },
    },
]

_ALL_NAMES = [t["name"] for t in _STEP_TOOLS] + [s["name"] for s in _SKILLS]


def seed_platform_skills(apps, schema_editor):
    RemoteTool = apps.get_model("tools", "RemoteTool")
    for tool in _STEP_TOOLS:
        RemoteTool.objects.get_or_create(
            name=tool["name"],
            defaults={
                "description": tool["description"],
                "source": "builtin",
                "input_schema": tool["input_schema"],
                "timeout": tool["timeout"],
                "is_active": True,
                "config": {"handler": tool["handler"]},
            },
        )
    for skill in _SKILLS:
        RemoteTool.objects.get_or_create(
            name=skill["name"],
            defaults={
                "description": skill["description"],
                "source": "skill",
                "input_schema": skill["input_schema"],
                "timeout": skill["timeout"],
                "is_active": True,
                "config": skill["config"],
            },
        )


def reverse(apps, schema_editor):
    RemoteTool = apps.get_model("tools", "RemoteTool")
    RemoteTool.objects.filter(name__in=_ALL_NAMES).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("tools", "0004_delete_tooltokenbinding"),
    ]

    operations = [
        migrations.RunPython(seed_platform_skills, reverse),
    ]
