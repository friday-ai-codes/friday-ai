"""Workflow schemas for event handling and AI plan validation.

Defines JSON schemas for:
- Feishu webhook event types (used by frontend for data structure previews)
- Technical plan validation (used by AI planning nodes)
"""

from typing import Any

from .technical_plan import (
    TECHNICAL_PLAN_JSON_SCHEMA,
    ExecutionTask,
    TaskFile,
    TechnicalPlan,
    dict_to_technical_plan,
    validate_technical_plan,
)

__all__ = [
    # Technical plan schema
    "TechnicalPlan",
    "ExecutionTask",
    "TaskFile",
    "TECHNICAL_PLAN_JSON_SCHEMA",
    "validate_technical_plan",
    "dict_to_technical_plan",
    # Feishu event schemas
    "EVENT_SCHEMAS",
    "QUICK_FIELDS",
    "get_event_schema",
    "get_all_event_schemas",
    "get_quick_fields",
    "get_event_types",
]

# 常用字段快捷映射
QUICK_FIELDS = {
    "prd_url": {
        "key": "prdUrl",
        "name": "需求文档",
        "path": "$.payload.fields[?(@.key=='field_000001')].value",
        "desc": "PRD 文档链接",
    },
    "tech_doc_url": {
        "key": "techDocUrl",
        "name": "技术方案",
        "path": "$.payload.fields[?(@.key=='field_000009')].value",
        "desc": "技术方案文档链接",
    },
    "description": {
        "key": "description",
        "name": "描述",
        "path": "$.payload.fields[?(@.key=='description')].value",
        "desc": "工作项描述",
    },
    "work_item_name": {
        "key": "workItemName",
        "name": "工作项名称",
        "path": "$.payload.name",
        "desc": "工作项标题",
    },
    "work_item_id": {
        "key": "workItemId",
        "name": "工作项ID",
        "path": "$.payload.id",
        "desc": "工作项唯一标识",
    },
    "project_key": {
        "key": "projectKey",
        "name": "项目Key",
        "path": "$.payload.project_key",
        "desc": "飞书项目标识",
    },
}


# 事件类型 Schema 定义
EVENT_SCHEMAS: dict[str, dict[str, Any]] = {
    "WorkitemCreateEvent": {
        "title": "工作项创建事件",
        "description": "当飞书项目中创建新工作项时触发",
        "type": "object",
        "properties": {
            "header": {
                "type": "object",
                "title": "事件头",
                "properties": {
                    "uuid": {"type": "string", "title": "事件UUID"},
                    "event_type": {"type": "string", "title": "事件类型"},
                    "token": {"type": "string", "title": "Webhook Token"},
                },
            },
            "payload": {
                "type": "object",
                "title": "事件载荷",
                "properties": {
                    "project_key": {"type": "string", "title": "项目Key"},
                    "id": {"type": "string", "title": "工作项ID"},
                    "name": {"type": "string", "title": "工作项名称"},
                    "work_item_type_key": {"type": "string", "title": "工作项类型"},
                    "fields": {
                        "type": "array",
                        "title": "字段列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string", "title": "字段Key"},
                                "value": {"type": "any", "title": "字段值"},
                            },
                        },
                    },
                },
            },
        },
    },
    "WorkitemStatusEvent": {
        "title": "工作项状态变更事件",
        "description": "当工作项状态发生变化时触发",
        "type": "object",
        "properties": {
            "header": {
                "type": "object",
                "title": "事件头",
                "properties": {
                    "uuid": {"type": "string", "title": "事件UUID"},
                    "event_type": {"type": "string", "title": "事件类型"},
                },
            },
            "payload": {
                "type": "object",
                "title": "事件载荷",
                "properties": {
                    "project_key": {"type": "string", "title": "项目Key"},
                    "id": {"type": "string", "title": "工作项ID"},
                    "name": {"type": "string", "title": "工作项名称"},
                    "cur_work_item_status": {
                        "type": "object",
                        "title": "当前状态",
                        "properties": {
                            "state_key": {"type": "string", "title": "状态Key"},
                            "state_name": {"type": "string", "title": "状态名称"},
                        },
                    },
                    "pre_work_item_status": {
                        "type": "object",
                        "title": "变更前状态",
                        "properties": {
                            "state_key": {"type": "string", "title": "状态Key"},
                            "state_name": {"type": "string", "title": "状态名称"},
                        },
                    },
                },
            },
        },
    },
    "WorkFlowNodeStatusEvent": {
        "title": "工作流节点流转事件",
        "description": "当工作流节点状态变化时触发",
        "type": "object",
        "properties": {
            "header": {
                "type": "object",
                "title": "事件头",
                "properties": {
                    "uuid": {"type": "string", "title": "事件UUID"},
                    "event_type": {"type": "string", "title": "事件类型"},
                },
            },
            "payload": {
                "type": "object",
                "title": "事件载荷",
                "properties": {
                    "project_key": {"type": "string", "title": "项目Key"},
                    "id": {"type": "string", "title": "工作项ID"},
                    "status_change_type": {"type": "string", "title": "状态变更类型"},
                },
            },
        },
    },
    "WorkitemCommentEvent": {
        "title": "工作项评论事件",
        "description": "当工作项收到评论时触发",
        "type": "object",
        "properties": {
            "header": {
                "type": "object",
                "title": "事件头",
                "properties": {
                    "uuid": {"type": "string", "title": "事件UUID"},
                    "event_type": {"type": "string", "title": "事件类型"},
                },
            },
            "payload": {
                "type": "object",
                "title": "事件载荷",
                "properties": {
                    "project_key": {"type": "string", "title": "项目Key"},
                    "id": {"type": "string", "title": "工作项ID"},
                    "comment": {"type": "string", "title": "评论内容"},
                },
            },
        },
    },
    "WorkitemUpdateEvent": {
        "title": "工作项字段更新事件",
        "description": "当工作项字段被修改时触发",
        "type": "object",
        "properties": {
            "header": {
                "type": "object",
                "title": "事件头",
                "properties": {
                    "uuid": {"type": "string", "title": "事件UUID"},
                    "event_type": {"type": "string", "title": "事件类型"},
                },
            },
            "payload": {
                "type": "object",
                "title": "事件载荷",
                "properties": {
                    "project_key": {"type": "string", "title": "项目Key"},
                    "id": {"type": "string", "title": "工作项ID"},
                    "changed_fields": {
                        "type": "array",
                        "title": "变更字段列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string", "title": "字段Key"},
                                "old_value": {"type": "any", "title": "旧值"},
                                "new_value": {"type": "any", "title": "新值"},
                            },
                        },
                    },
                },
            },
        },
    },
}


def get_event_schema(event_type: str) -> dict | None:
    """获取事件类型的 Schema"""
    return EVENT_SCHEMAS.get(event_type)


def get_all_event_schemas() -> dict[str, dict]:
    """获取所有事件 Schema"""
    return EVENT_SCHEMAS


def get_quick_fields() -> dict[str, dict]:
    """获取常用字段快捷映射"""
    return QUICK_FIELDS


def get_event_types() -> list[dict]:
    """获取所有支持的事件类型列表"""
    return [
        {"key": key, "title": schema["title"], "description": schema.get("description", "")}
        for key, schema in EVENT_SCHEMAS.items()
    ]
