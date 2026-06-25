"""Technical Plan Schema for AI-generated technical plans.

Defines dataclasses and JSON Schema for validating LLM output
that will be consumed by CodingDispatcher.
"""

from dataclasses import dataclass, field
from typing import Any

import jsonschema


@dataclass
class TaskFile:
    """单个任务涉及的文件"""

    path: str
    action: str  # "create" | "modify" | "delete"
    description: str = ""


@dataclass
class ExecutionTask:
    """执行计划中的单个任务"""

    id: str
    name: str
    description: str
    repository_id: str  # Required: target repository
    repository_name: str
    branch_strategy: str  # Required: "feature" | "hotfix" | "release"
    coding_instruction: str = ""  # Detailed coding instructions for AI
    files: list[TaskFile] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)  # Task IDs this depends on
    estimated_hours: float = 0
    priority: int = 1


@dataclass
class TechnicalPlan:
    """技术方案完整结构"""

    # Overview
    title: str
    summary: str
    created_at: str

    # Projects involved
    projects: list[dict[str, Any]]  # [{id, name, repository_count}]

    # Execution plan
    execution_plan: list[ExecutionTask]

    # Metadata
    total_tasks: int = 0
    estimated_total_hours: float = 0
    risks: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    global_context: str = ""  # Shared context for all tasks


# JSON Schema for LLM prompting and validation
TECHNICAL_PLAN_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "TechnicalPlan",
    "description": "AI-generated technical plan for software development tasks",
    "type": "object",
    "required": ["title", "summary", "execution_plan"],
    "properties": {
        "title": {
            "type": "string",
            "description": "Technical plan title",
            "minLength": 1,
        },
        "summary": {
            "type": "string",
            "description": "Brief summary of the technical plan",
            "minLength": 1,
        },
        "created_at": {
            "type": "string",
            "description": "Creation date in ISO format (YYYY-MM-DD or ISO 8601)",
        },
        "projects": {
            "type": "array",
            "description": "Projects involved in this plan",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "repository_count": {"type": "integer"},
                },
            },
        },
        "execution_plan": {
            "type": "array",
            "description": "List of tasks to execute",
            "items": {
                "type": "object",
                "required": [
                    "id",
                    "name",
                    "repository_id",
                    "repository_name",
                    "branch_strategy",
                ],
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Unique task identifier",
                    },
                    "name": {
                        "type": "string",
                        "description": "Task name",
                    },
                    "description": {
                        "type": "string",
                        "description": "Detailed task description",
                    },
                    "repository_id": {
                        "type": "string",
                        "description": "Target repository ID",
                    },
                    "repository_name": {
                        "type": "string",
                        "description": "Target repository name",
                    },
                    "branch_strategy": {
                        "type": "string",
                        "enum": ["feature", "hotfix", "release"],
                        "description": "Git branch strategy for this task",
                    },
                    "coding_instruction": {
                        "type": "string",
                        "description": "Detailed coding instructions for AI",
                    },
                    "files": {
                        "type": "array",
                        "description": "Files to be created/modified/deleted",
                        "items": {
                            "type": "object",
                            "required": ["path", "action"],
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "File path relative to repository root",
                                },
                                "action": {
                                    "type": "string",
                                    "enum": ["create", "modify", "delete"],
                                    "description": "Action to perform on the file",
                                },
                                "description": {
                                    "type": "string",
                                    "description": "Description of changes to this file",
                                },
                            },
                        },
                    },
                    "dependencies": {
                        "type": "array",
                        "description": "Task IDs this task depends on",
                        "items": {"type": "string"},
                    },
                    "estimated_hours": {
                        "type": "number",
                        "description": "Estimated hours to complete",
                        "minimum": 0,
                    },
                    "priority": {
                        "type": "integer",
                        "description": "Task priority (1=highest)",
                        "minimum": 1,
                    },
                },
            },
        },
        "total_tasks": {
            "type": "integer",
            "description": "Total number of tasks",
            "minimum": 0,
        },
        "estimated_total_hours": {
            "type": "number",
            "description": "Total estimated hours",
            "minimum": 0,
        },
        "risks": {
            "type": "array",
            "description": "Identified risks",
            "items": {"type": "string"},
        },
        "assumptions": {
            "type": "array",
            "description": "Assumptions made in the plan",
            "items": {"type": "string"},
        },
        "global_context": {
            "type": "string",
            "description": "Shared context for all tasks",
        },
    },
}


def validate_technical_plan(data: dict[str, Any]) -> tuple[bool, str | None]:
    """Validate JSON against TechnicalPlanSchema.

    Args:
        data: Dictionary to validate against the schema

    Returns:
        Tuple of (is_valid, error_message).
        If valid, returns (True, None).
        If invalid, returns (False, error_message).
    """
    try:
        jsonschema.validate(data, TECHNICAL_PLAN_JSON_SCHEMA)
        return True, None
    except jsonschema.ValidationError as e:
        return False, str(e.message)


def dict_to_technical_plan(data: dict[str, Any]) -> TechnicalPlan:
    """Convert validated dict to TechnicalPlan dataclass.

    Args:
        data: Dictionary that has been validated against TECHNICAL_PLAN_JSON_SCHEMA

    Returns:
        TechnicalPlan dataclass instance

    Note:
        This function assumes the data has already been validated.
        Call validate_technical_plan() first to ensure data is valid.
    """
    # Convert execution_plan items to ExecutionTask dataclasses
    execution_tasks: list[ExecutionTask] = []
    for task_data in data.get("execution_plan", []):
        # Convert files to TaskFile dataclasses
        files: list[TaskFile] = []
        for file_data in task_data.get("files", []):
            files.append(
                TaskFile(
                    path=file_data["path"],
                    action=file_data["action"],
                    description=file_data.get("description", ""),
                )
            )

        execution_tasks.append(
            ExecutionTask(
                id=task_data["id"],
                name=task_data["name"],
                description=task_data.get("description", ""),
                repository_id=task_data["repository_id"],
                repository_name=task_data["repository_name"],
                branch_strategy=task_data["branch_strategy"],
                coding_instruction=task_data.get("coding_instruction", ""),
                files=files,
                dependencies=task_data.get("dependencies", []),
                estimated_hours=task_data.get("estimated_hours", 0),
                priority=task_data.get("priority", 1),
            )
        )

    return TechnicalPlan(
        title=data["title"],
        summary=data["summary"],
        created_at=data.get("created_at", ""),
        spaces=data.get("projects", []),
        execution_plan=execution_tasks,
        total_tasks=data.get("total_tasks", len(execution_tasks)),
        estimated_total_hours=data.get("estimated_total_hours", 0),
        risks=data.get("risks", []),
        assumptions=data.get("assumptions", []),
        global_context=data.get("global_context", ""),
    )
