"""blueprint/v1 权威结构 schema 与校验（Phase 111-01，SCHEMA-01 / SCHEMA-07）。

TechnicalBlueprint v1 的唯一 schema 事实源（DESIGN §3.2–§3.13）：

- ``BLUEPRINT_JSON_SCHEMA``：六段固定骨架（repo_associations / current_state_analysis /
  implementation_overview / api_contracts / impact_analysis / interaction_flows）
  + meta + requirement_spec + must_haves + 文档级 citations 引用池，Block/Citation
  基元以 ``$defs`` 复用。
- ``validate_blueprint``：jsonschema 结构校验 + 五项后置检查（块内 citations id
  ∈ 文档级引用池；items[].feature_point_id ∈ feature_points[].id；items /
  current_state_analysis 的 repository_id ∈ repo_associations；引用池 key ==
  条目 citation_id；items / feature_points / api_contracts 的 id 唯一）。
  无 ``schema_version`` 的旧 MergedPlan 形状（隐式 v0）直接 pass-through，零迁移。
- ``iter_blocks`` / ``diff_blueprint_blocks``：block 级走查与版本间三分类 diff
  （added / removed / modified），供版本演进与 114 重锚定消费。

**纯函数**（无 IO / 无 ORM / 无 LLM），仅依赖 stdlib + jsonschema。与
``merged_plan.py`` 平级并存：本模块绝不修改它，v0 校验路径零变化（§13.2 冻结纪律）。
section_path 形状对齐 DESIGN §6.1 anchor.section_path（点分 + ``[id]`` 索引）。
"""

from __future__ import annotations

import json
from typing import Any, Iterator

import jsonschema

__all__ = [
    "BLUEPRINT_SCHEMA_VERSION",
    "BLUEPRINT_JSON_SCHEMA",
    "validate_blueprint",
    "iter_blocks",
    "diff_blueprint_blocks",
]

BLUEPRINT_SCHEMA_VERSION = "blueprint/v1"

# blueprint/v1 jsonschema（Draft 2020-12）。description 兼作 LLM prompting 说明，
# 对齐 technical_plan.py 惯例；additionalProperties 保持默认允许（兼容演进）。
BLUEPRINT_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "TechnicalBlueprint",
    "description": "blueprint/v1 技术蓝图：六段固定骨架 + 需求规格 + 验收锚点 + 文档级引用池",
    "type": "object",
    "$defs": {
        "block": {
            "type": "object",
            "description": "最小可锚定/可编辑内容单元（DESIGN §3.2）",
            "required": ["block_id", "type"],
            "properties": {
                "block_id": {
                    "type": "string",
                    "minLength": 1,
                    "description": "块稳定标识（版本间编辑保留、新增才生成；不强制 ULID 格式）",
                },
                "type": {
                    "type": "string",
                    "enum": ["paragraph", "pseudocode", "table", "list", "mermaid"],
                    "description": "块类型",
                },
                "text": {
                    "description": "paragraph/mermaid 为字符串；list 为条目字符串数组",
                },
                "code": {
                    "type": "object",
                    "description": "pseudocode 专用：{language, source}",
                },
                "rows": {
                    "type": "array",
                    "description": "table 专用：行数组（每行为单元格数组）",
                },
                "citations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "本块结论依据的引用 id（必须存在于文档级引用池）",
                },
            },
        },
        "block_list": {
            "type": "array",
            "items": {"$ref": "#/$defs/block"},
            "description": "Block 序列",
        },
        "citation": {
            "type": "object",
            "description": "文档级去重存放的引用条目（DESIGN §3.2）",
            "required": ["citation_id", "source_type"],
            "properties": {
                "citation_id": {
                    "type": "string",
                    "minLength": 1,
                    "description": "引用 id（块内 citations 引用的键）",
                },
                "source_type": {
                    "type": "string",
                    "enum": [
                        "knowledge_entity",
                        "rag_chunk",
                        "repo_file",
                        "artifact_version",
                        "blueprint",
                        "repo_charter",
                        "work_item",
                        "feishu_doc",
                        "url",
                    ],
                    "description": "引用来源类型",
                },
                "source_id": {
                    "type": "string",
                    "description": "对应实体主键 / chunk id / URL",
                },
                "locator": {
                    "type": "object",
                    "description": "文件路径/行号/heading/chunk 等定位信息",
                },
                "quote": {"type": "string", "description": "被引用的关键原文摘录"},
                "title": {"type": "string", "description": "展示用标题快照"},
            },
        },
    },
    "required": [
        "schema_version",
        "meta",
        "requirement_spec",
        "repo_associations",
        "current_state_analysis",
        "implementation_overview",
        "api_contracts",
        "impact_analysis",
        "interaction_flows",
        "must_haves",
        "citations",
    ],
    "properties": {
        "schema_version": {
            "type": "string",
            "const": BLUEPRINT_SCHEMA_VERSION,
            "description": "schema 判别字段（旧 MergedPlan 隐式 v0 无此字段）",
        },
        "meta": {
            "type": "object",
            "description": "文档元信息（DESIGN §3.4）",
            "required": ["title", "project_id"],
            "properties": {
                "title": {"type": "string", "minLength": 1, "description": "蓝图标题"},
                "summary": {"$ref": "#/$defs/block_list", "description": "执行摘要"},
                "project_id": {
                    "type": "string",
                    "minLength": 1,
                    "description": "所属项目 id（一个项目一份活跃蓝图）",
                },
                "space_id": {"type": "string", "description": "所属空间 id"},
                "requirement_refs": {
                    "type": "array",
                    "description": "需求来源引用（项目 PRD / feature list / 既有 feature 方案 / work item）",
                },
                "language": {"type": "string", "description": "文档语言，默认 zh-CN"},
                "revision_round": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "修订轮次（AI 审查打回 / 人审驳回 +1）",
                },
            },
        },
        "requirement_spec": {
            "type": "object",
            "description": "需求规格（锁 WHAT，规格门通过后锁定；DESIGN §3.5）",
            "required": ["goal", "feature_points"],
            "properties": {
                "goal": {"$ref": "#/$defs/block_list", "description": "一段话可证伪目标"},
                "background": {"$ref": "#/$defs/block_list", "description": "需求背景"},
                "feature_points": {
                    "type": "array",
                    "description": "功能点清单（与 feature list 条目一一对齐）",
                    "items": {
                        "type": "object",
                        "required": ["id", "title", "intent"],
                        "properties": {
                            "id": {
                                "type": "string",
                                "minLength": 1,
                                "description": "功能点 id（fp_*）",
                            },
                            "title": {
                                "type": "string",
                                "minLength": 1,
                                "description": "功能点标题",
                            },
                            "intent": {
                                "type": "string",
                                "enum": ["greenfield", "brownfield", "fix"],
                                "description": "功能点意图分类（净新增 / 存量改造 / 缺陷修复；驱动 blueprint_route 加权，DESIGN §5.7）",
                            },
                            "description": {
                                "$ref": "#/$defs/block_list",
                                "description": "功能点描述",
                            },
                            "module": {
                                "type": "string",
                                "description": "所属功能模块/章节名（可选；驱动 blueprint_route 的 placement unit 聚合，缺失时不得凭空发明）",
                            },
                            "source_ref": {
                                "type": "string",
                                "description": "requirement_refs 内的来源标识",
                            },
                            "acceptance_criteria": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "可机械验证的验收句",
                            },
                            "test_cases": {
                                "type": "array",
                                "description": "测试用例（name + given_when_then）",
                            },
                        },
                    },
                },
                "boundaries": {
                    "type": "object",
                    "description": "范围边界（in_scope / out_of_scope）",
                },
                "constraints": {
                    "type": "array",
                    "description": "约束清单（id/text/kind/citations）",
                },
                "ambiguity_report": {
                    "type": "object",
                    "description": "规格门放行时的歧义度终值快照",
                },
            },
        },
        "repo_associations": {
            "type": "array",
            "description": "六段之 1：仓库关联（direct=本方案编码改动 / indirect=依赖不改动；DESIGN §3.6）",
            "items": {
                "type": "object",
                "required": ["repository_id", "repository_name", "role"],
                "properties": {
                    "repository_id": {
                        "type": "string",
                        "minLength": 1,
                        "description": "仓库 id",
                    },
                    "repository_name": {
                        "type": "string",
                        "minLength": 1,
                        "description": "仓库名",
                    },
                    "role": {
                        "type": "string",
                        "enum": ["direct", "indirect"],
                        "description": "direct=要在其中编码改动 / indirect=被依赖但本方案不改动",
                    },
                    "rationale": {
                        "type": "object",
                        "description": "为什么选它：参考了什么、符合哪些原则",
                        "properties": {
                            "text": {
                                "$ref": "#/$defs/block_list",
                                "description": "选仓理由叙述",
                            },
                            "constraint_refs": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "关联 requirement_spec.constraints 的约束 id",
                            },
                            "citations": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "证据引用 id（活跃度数据/相似功能代码/规范文档）",
                            },
                        },
                    },
                    "responsibility": {
                        "$ref": "#/$defs/block_list",
                        "description": "本仓在方案中的职责（阶段 1 确认门锁定）",
                    },
                    "fitness": {
                        "type": "object",
                        "description": "阶段 1 逐仓调研的适配判定快照",
                        "properties": {
                            "verdict": {
                                "type": "string",
                                "enum": ["suitable", "partial", "unsuitable"],
                                "description": "适配判定",
                            },
                            "reasons": {
                                "$ref": "#/$defs/block_list",
                                "description": "判定理由",
                            },
                            "citations": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "证据引用 id",
                            },
                        },
                    },
                    "planned_change_summary": {
                        "$ref": "#/$defs/block_list",
                        "description": "direct 专属：本仓要做什么改动（细节在实现概述）",
                    },
                    "capabilities_used": {
                        "type": "array",
                        "description": "indirect 专属：会被用到的能力清单",
                    },
                    "routing_evidence": {
                        "type": "object",
                        "description": "承接路由层输出的证据快照（score/confidence 等）",
                    },
                    "decided_by": {
                        "type": "string",
                        "enum": ["ai", "human"],
                        "description": "角色判定是 AI 提议还是人工确认/改判",
                    },
                    "confirmed_at_gate": {
                        "type": "boolean",
                        "description": "是否经阶段 1 用户确认门锁定",
                    },
                    "support_needed": {
                        "$ref": "#/$defs/block_list",
                        "description": "需要该仓团队配合的事项",
                    },
                },
            },
        },
        "current_state_analysis": {
            "type": "array",
            "description": "六段之 2：现状分析（按仓组织，每条 finding 必须带引用；DESIGN §3.7）",
            "items": {
                "type": "object",
                "required": ["repository_id", "findings"],
                "properties": {
                    "repository_id": {
                        "type": "string",
                        "minLength": 1,
                        "description": "仓库 id",
                    },
                    "summary": {
                        "$ref": "#/$defs/block_list",
                        "description": "该仓与本需求相关的现状综述",
                    },
                    "findings": {
                        "type": "array",
                        "description": "调研结论清单",
                        "items": {
                            "type": "object",
                            "required": ["id", "text", "kind", "citations"],
                            "properties": {
                                "id": {
                                    "type": "string",
                                    "minLength": 1,
                                    "description": "结论 id（cs_*）",
                                },
                                "topic": {"type": "string", "description": "结论主题"},
                                "text": {
                                    "$ref": "#/$defs/block_list",
                                    "description": "结论叙述",
                                },
                                "kind": {
                                    "type": "string",
                                    "enum": ["capability", "gap", "risk", "convention"],
                                    "description": "结论类型",
                                },
                                "related_feature_points": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "相关功能点 id",
                                },
                                "citations": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "必填：代码文件/知识条目证据引用 id",
                                },
                            },
                        },
                    },
                },
            },
        },
        "implementation_overview": {
            "type": "object",
            "description": "六段之 3：实现概述（需求叙事 → 模块 → 实现项；DESIGN §3.8）",
            "required": ["requirement_narrative", "items"],
            "properties": {
                "requirement_narrative": {
                    "$ref": "#/$defs/block_list",
                    "description": "完整需求「如何实现」的总叙事",
                },
                "modules": {
                    "type": "array",
                    "description": "功能模块层",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "模块 id（mod_*）"},
                            "name": {"type": "string", "description": "模块名"},
                            "feature_point_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "覆盖的功能点 id",
                            },
                            "repository_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "涉及仓库 id（功能↔模块↔仓库映射）",
                            },
                            "narrative": {
                                "$ref": "#/$defs/block_list",
                                "description": "模块级「如何实现」叙事",
                            },
                        },
                    },
                },
                "items": {
                    "type": "array",
                    "description": "功能点实现项（最细粒度，execution_plan 的派生源）",
                    "items": {
                        "type": "object",
                        "required": [
                            "id",
                            "feature_point_id",
                            "repository_id",
                            "change_type",
                            "title",
                        ],
                        "properties": {
                            "id": {
                                "type": "string",
                                "minLength": 1,
                                "description": "实现项 id（impl_*）",
                            },
                            "feature_point_id": {
                                "type": "string",
                                "minLength": 1,
                                "description": "对应功能点 id（必须可解析到 requirement_spec.feature_points）",
                            },
                            "module_id": {"type": "string", "description": "所属模块 id"},
                            "repository_id": {
                                "type": "string",
                                "minLength": 1,
                                "description": "目标仓库 id",
                            },
                            "change_type": {
                                "type": "string",
                                "enum": ["create", "modify", "remove", "indirect_refine"],
                                "description": "变更类型（新建/改动/删除/间接完善）",
                            },
                            "title": {
                                "type": "string",
                                "minLength": 1,
                                "description": "实现项标题",
                            },
                            "how": {
                                "$ref": "#/$defs/block_list",
                                "description": "具体怎么做（可含 pseudocode 块）",
                            },
                            "existing_integration": {
                                "$ref": "#/$defs/block_list",
                                "description": "改造项与既有功能如何配合",
                            },
                            "files_touched": {
                                "type": "array",
                                "description": "涉及文件（action 三值 create/modify/remove；派生 execution_plan 时 remove→delete）",
                                "items": {
                                    "type": "object",
                                    "required": ["path", "action"],
                                    "properties": {
                                        "path": {
                                            "type": "string",
                                            "minLength": 1,
                                            "description": "仓内相对路径",
                                        },
                                        "action": {
                                            "type": "string",
                                            "enum": ["create", "modify", "remove"],
                                            "description": "文件动作",
                                        },
                                        "note": {"type": "string", "description": "备注"},
                                    },
                                },
                            },
                            "depends_on": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "依赖的实现项 id（供派生 execution_plan 依赖边）",
                            },
                            "wave": {
                                "type": "integer",
                                "minimum": 1,
                                "description": "实施波次（≥1）",
                            },
                            "test_strategy": {
                                "$ref": "#/$defs/block_list",
                                "description": "测试策略（结合规格 test_cases）",
                            },
                            "citations": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "证据引用 id",
                            },
                        },
                    },
                },
            },
        },
        "api_contracts": {
            "type": "array",
            "description": "六段之 4：API 契约（provided 提供 + consumed 消费；DESIGN §3.9）",
            "items": {
                "type": "object",
                "required": ["id", "name", "kind", "direction"],
                "properties": {
                    "id": {
                        "type": "string",
                        "minLength": 1,
                        "description": "契约 id（api_*）",
                    },
                    "name": {"type": "string", "minLength": 1, "description": "契约名"},
                    "kind": {
                        "type": "string",
                        "enum": ["http", "rpc", "event", "mq"],
                        "description": "接口类型",
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["provided", "consumed"],
                        "description": "provided=本方案新提供 / consumed=需要调用别人",
                    },
                    "repository_id": {"type": "string", "description": "归属仓库 id"},
                    "method": {"type": "string", "description": "HTTP method"},
                    "path": {"type": "string", "description": "接口路径"},
                    "description": {
                        "$ref": "#/$defs/block_list",
                        "description": "接口说明",
                    },
                    "request_example": {"type": "object", "description": "请求示例"},
                    "response_example": {"type": "object", "description": "响应示例"},
                    "request_schema": {
                        "type": "object",
                        "description": "请求 jsonschema（可选）",
                    },
                    "response_schema": {
                        "type": "object",
                        "description": "响应 jsonschema（可选）",
                    },
                    "data_source": {
                        "type": "object",
                        "description": "consumed 专属：数据来源说明",
                        "properties": {
                            "from_service": {"type": "string", "description": "来源服务"},
                            "from_api": {"type": "string", "description": "来源接口"},
                            "fields_needed": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "需要的字段",
                            },
                            "availability": {
                                "type": "string",
                                "enum": ["existing", "needs_support"],
                                "description": "数据已有 or 需对方支持产出",
                            },
                            "support_repository_id": {
                                "type": "string",
                                "description": "needs_support 时：哪个仓要配合",
                            },
                            "notes": {
                                "$ref": "#/$defs/block_list",
                                "description": "补充说明",
                            },
                        },
                    },
                    "consumers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "消费方模块 id",
                    },
                    "citations": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "证据引用 id",
                    },
                },
            },
        },
        "impact_analysis": {
            "type": "object",
            "description": "六段之 5：影响范围（业务语言优先，代码维度佐证；DESIGN §3.10）",
            "required": ["business_impact", "affected_features"],
            "properties": {
                "business_impact": {
                    "$ref": "#/$defs/block_list",
                    "description": "对现有业务造成什么影响（自然语言）",
                },
                "affected_features": {
                    "type": "array",
                    "description": "受影响的既有功能清单",
                    "items": {
                        "type": "object",
                        "required": ["feature", "kind"],
                        "properties": {
                            "feature": {
                                "type": "string",
                                "minLength": 1,
                                "description": "既有功能名",
                            },
                            "repository_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "涉及仓库 id",
                            },
                            "kind": {
                                "type": "string",
                                "enum": ["behavior_change", "perf", "compat", "data", "none"],
                                "description": "影响类型",
                            },
                            "description": {
                                "$ref": "#/$defs/block_list",
                                "description": "影响描述",
                            },
                            "citations": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "证据引用 id",
                            },
                        },
                    },
                },
                "regression_scope": {
                    "type": "array",
                    "description": "需要回归测试到什么程度",
                    "items": {
                        "type": "object",
                        "properties": {
                            "area": {"type": "string", "description": "回归区域"},
                            "level": {
                                "type": "string",
                                "enum": ["full", "smoke", "none"],
                                "description": "回归级别",
                            },
                            "reason": {"type": "string", "description": "理由"},
                        },
                    },
                },
                "compat_risks": {
                    "$ref": "#/$defs/block_list",
                    "description": "兼容风险（承接原 §7 字段）",
                },
                "data_migrations": {
                    "type": "array",
                    "description": "数据迁移清单（description + reversible）",
                },
                "rollback_plan": {
                    "$ref": "#/$defs/block_list",
                    "description": "回滚方案",
                },
            },
        },
        "interaction_flows": {
            "type": "array",
            "description": "六段之 6：业务与接口交互流程（页面→接口→参数→数据流向；DESIGN §3.11）",
            "items": {
                "type": "object",
                "required": ["id", "name", "steps"],
                "properties": {
                    "id": {
                        "type": "string",
                        "minLength": 1,
                        "description": "流程 id（flow_*）",
                    },
                    "name": {"type": "string", "minLength": 1, "description": "流程名"},
                    "trigger": {"type": "string", "description": "触发条件"},
                    "steps": {
                        "type": "array",
                        "description": "步骤序列",
                        "items": {
                            "type": "object",
                            "required": ["seq", "actor", "action"],
                            "properties": {
                                "seq": {"type": "integer", "description": "步骤序号"},
                                "actor": {
                                    "type": "string",
                                    "description": "执行方（frontend/backend/service:*/user）",
                                },
                                "action": {"type": "string", "description": "动作"},
                                "component": {"type": "string", "description": "涉及组件"},
                                "api_ref": {
                                    "type": "string",
                                    "description": "引用 api_contracts 的契约 id",
                                },
                                "data_in": {"type": "string", "description": "输入数据"},
                                "data_out": {"type": "string", "description": "输出数据"},
                                "note": {
                                    "$ref": "#/$defs/block_list",
                                    "description": "补充说明",
                                },
                            },
                        },
                    },
                    "alternative_paths": {
                        "type": "array",
                        "description": "备选路径（condition + steps）",
                    },
                    "mermaid": {
                        "type": "string",
                        "description": "由 steps 确定性生成的时序图源码",
                    },
                    "citations": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "证据引用 id",
                    },
                },
            },
        },
        "must_haves": {
            "type": "object",
            "description": "goal-backward 验收锚点（DESIGN §3.12）",
            "required": ["truths", "artifacts", "key_links"],
            "properties": {
                "truths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可观察行为断言",
                },
                "artifacts": {
                    "type": "array",
                    "description": "必须存在的产物（path + provides）",
                },
                "key_links": {
                    "type": "array",
                    "description": "关键链接（from/to/via）",
                },
            },
        },
        "decision_log": {
            "type": "array",
            "description": "已解决澄清线程的决策快照（可选；DESIGN §3.13）",
        },
        "deferred_ideas": {
            "type": "array",
            "description": "scope 外想法（可选，防扩 scope）",
        },
        "execution_plan": {
            "type": "array",
            "description": "确认后确定性派生的执行计划段（可选；形状对齐 technical_plan schema，DESIGN §3.14）",
        },
        "citations": {
            "type": "object",
            "description": "文档级引用池：{citation_id: Citation}，块内只存 id",
            "additionalProperties": {"$ref": "#/$defs/citation"},
        },
    },
}

# 预编译校验器：schema 体量大，避免每次调用重新编译（RESEARCH P6）。
_VALIDATOR = jsonschema.Draft202012Validator(BLUEPRINT_JSON_SCHEMA)


# 校验报错出口长度上限：jsonschema 对 type/enum/const 类失败会把被校验实例的 repr
# 整段拼进 message 且不做截断，而蓝图 content 是半可信正文（可能夹带代码片段/凭证
# 样本），报错会进 DRF 响应体与调用方异常日志——出口统一脱敏 + 截断（MJ-03）。
_MAX_ERROR_CHARS = 500
_TRUNCATED_SUFFIX = "…（已截断）"


def _format_error(path: str, message: Any) -> str:
    """校验报错唯一出口：脱敏 + 截断，只保留定位信息与开头的可读原因。"""
    text = str(message)
    try:
        from common.logging import redact_secrets_in_text

        text = redact_secrets_in_text(text)
    except Exception:  # noqa: BLE001 — 脱敏不可用时也不能让校验器抛（fail-safe）
        pass
    if len(text) > _MAX_ERROR_CHARS:
        text = text[:_MAX_ERROR_CHARS] + _TRUNCATED_SUFFIX
    return f"{path}: {text}"


def _iter_citation_refs(node: Any) -> Iterator[str]:
    """递归走查任意节点，产出所有「key 为 citations 且值为 list」中的字符串引用 id。"""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "citations" and isinstance(value, list):
                for cid in value:
                    if isinstance(cid, str):
                        yield cid
            else:
                yield from _iter_citation_refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_citation_refs(item)


def validate_blueprint(content: Any) -> tuple[bool, str | None]:
    """校验 blueprint/v1 content：jsonschema 结构 + 后置引用完整性。

    无 ``schema_version == "blueprint/v1"`` 的 content 视为隐式 v0（旧 MergedPlan
    形状）直接 pass-through 返回 ``(True, None)``——v0 的真正校验仍由
    ``validate_technical_plan`` 负责（builtin_types 判别分支），本函数不重复。

    Args:
        content: 半可信 blueprint dict（LLM 装配产物 / API 输入）。

    Returns:
        ``(True, None)`` 合法；``(False, error_message)`` 非法（报错经
        :func:`_format_error` 脱敏 + 截断，绝不原样回显整段被校验实例）。绝不外抛异常。
    """
    if not isinstance(content, dict):
        return False, "content 必须是 JSON 对象"
    if content.get("schema_version") != BLUEPRINT_SCHEMA_VERSION:
        return True, None
    try:
        errors = sorted(_VALIDATOR.iter_errors(content), key=lambda e: e.json_path)
        if errors:
            first = errors[0]
            return False, _format_error(first.json_path, first.message)

        # 后置检查 (a)：引用完整性——全文档任何块/条目的 citations 引用 id
        # 必须存在于顶层 citations 引用池（跳过引用池本身）。
        pool = content.get("citations")
        pool_keys = set(pool.keys()) if isinstance(pool, dict) else set()
        for key, value in content.items():
            if key == "citations":
                continue
            for cid in _iter_citation_refs(value):
                if cid not in pool_keys:
                    return False, f"引用 {cid} 不存在于文档级引用池"

        # 后置检查 (b)：items[].feature_point_id 必须可解析到 requirement_spec。
        spec = content.get("requirement_spec")
        feature_points = spec.get("feature_points") if isinstance(spec, dict) else []
        fp_ids = {
            fp.get("id") for fp in (feature_points or []) if isinstance(fp, dict) and fp.get("id")
        }
        overview = content.get("implementation_overview")
        items = overview.get("items") if isinstance(overview, dict) else []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            fp_id = item.get("feature_point_id")
            if fp_id not in fp_ids:
                item_id = item.get("id") or "?"
                return (
                    False,
                    f"implementation_overview.items[{item_id}].feature_point_id "
                    f"{fp_id!r} 无法解析到 requirement_spec.feature_points",
                )

        # 后置检查 (c)：repository_id 引用完整性——items / current_state_analysis 引用的
        # 仓库必须出现在 repo_associations。坏 id 过门会被派生器原样搬进 execution task，
        # 失败点被推到编码执行期（下游 dispatcher 拿它建分支/克隆仓）。
        assoc_ids = {
            assoc.get("repository_id")
            for assoc in (content.get("repo_associations") or [])
            if isinstance(assoc, dict) and assoc.get("repository_id")
        }
        for item in items or []:
            if not isinstance(item, dict):
                continue
            rid = item.get("repository_id")
            if rid not in assoc_ids:
                item_id = item.get("id") or "?"
                return (
                    False,
                    f"implementation_overview.items[{item_id}].repository_id "
                    f"{rid!r} 不在 repo_associations 中",
                )
        for idx, analysis in enumerate(content.get("current_state_analysis") or []):
            if not isinstance(analysis, dict):
                continue
            rid = analysis.get("repository_id")
            if rid not in assoc_ids:
                return (
                    False,
                    f"current_state_analysis[{idx}].repository_id "
                    f"{rid!r} 不在 repo_associations 中",
                )

        # 后置检查 (d)：引用池 key 必须等于条目自身的 citation_id（MN-09）。两者不一致
        # 时块内按哪个引用都可能被误判（悬空引用放过 / 合法引用误报）。
        if isinstance(pool, dict):
            for key, entry in pool.items():
                if isinstance(entry, dict) and entry.get("citation_id") != key:
                    return (
                        False,
                        f"citations[{key}].citation_id {entry.get('citation_id')!r} "
                        f"与引用池键不一致",
                    )

        # 后置检查 (e)：标识唯一性（MN-08）。重复 id 会让按 id 建索引的下游（派生器的
        # item→repo 映射、模块/契约引用）静默取到后者，投影出错误的依赖边。
        for label, records in (
            ("requirement_spec.feature_points", feature_points or []),
            ("implementation_overview.items", items or []),
            ("api_contracts", content.get("api_contracts") or []),
        ):
            seen_ids: set[str] = set()
            for record in records:
                if not isinstance(record, dict):
                    continue
                record_id = record.get("id")
                if not isinstance(record_id, str) or not record_id:
                    continue
                if record_id in seen_ids:
                    return False, f"{label} 存在重复 id {record_id!r}"
                seen_ids.add(record_id)
        return True, None
    except Exception as exc:  # 防御性兜底：半可信输入恒不抛（fail-safe）
        return False, _format_error("blueprint 校验异常", exc)


def _item_key(item: dict, key: str, index: int) -> str:
    """列表项的 section_path 索引：优先取标识字段值，缺失回退位置下标。"""
    value = item.get(key)
    if value is None or value == "":
        return str(index)
    return str(value)


def iter_blocks(content: Any) -> list[tuple[str, dict]]:
    """确定性走查全部已知 Block[] 落位，返回 ``(section_path, block)`` 列表。

    section_path 用点分 + ``[id]`` 索引（如 ``implementation_overview.items[impl_01].how``），
    对齐 DESIGN §6.1 anchor.section_path 形状——114 重锚定与 115 渲染消费同一路径约定。
    逐字段 ``.get`` 防御，只收带非空 ``block_id`` 的 dict。
    """
    results: list[tuple[str, dict]] = []
    if not isinstance(content, dict):
        return results

    def collect(path: str, blocks: Any) -> None:
        if not isinstance(blocks, list):
            return
        for block in blocks:
            if isinstance(block, dict) and block.get("block_id"):
                results.append((path, block))

    meta = content.get("meta")
    if isinstance(meta, dict):
        collect("meta.summary", meta.get("summary"))

    spec = content.get("requirement_spec")
    if isinstance(spec, dict):
        collect("requirement_spec.goal", spec.get("goal"))
        collect("requirement_spec.background", spec.get("background"))
        for idx, fp in enumerate(spec.get("feature_points") or []):
            if not isinstance(fp, dict):
                continue
            fp_key = _item_key(fp, "id", idx)
            collect(
                f"requirement_spec.feature_points[{fp_key}].description",
                fp.get("description"),
            )

    for idx, assoc in enumerate(content.get("repo_associations") or []):
        if not isinstance(assoc, dict):
            continue
        base = f"repo_associations[{_item_key(assoc, 'repository_id', idx)}]"
        rationale = assoc.get("rationale")
        if isinstance(rationale, dict):
            collect(f"{base}.rationale.text", rationale.get("text"))
        collect(f"{base}.responsibility", assoc.get("responsibility"))
        fitness = assoc.get("fitness")
        if isinstance(fitness, dict):
            collect(f"{base}.fitness.reasons", fitness.get("reasons"))
        collect(f"{base}.planned_change_summary", assoc.get("planned_change_summary"))
        collect(f"{base}.support_needed", assoc.get("support_needed"))

    for idx, analysis in enumerate(content.get("current_state_analysis") or []):
        if not isinstance(analysis, dict):
            continue
        base = f"current_state_analysis[{_item_key(analysis, 'repository_id', idx)}]"
        collect(f"{base}.summary", analysis.get("summary"))
        for f_idx, finding in enumerate(analysis.get("findings") or []):
            if not isinstance(finding, dict):
                continue
            f_key = _item_key(finding, "id", f_idx)
            collect(f"{base}.findings[{f_key}].text", finding.get("text"))

    overview = content.get("implementation_overview")
    if isinstance(overview, dict):
        collect(
            "implementation_overview.requirement_narrative",
            overview.get("requirement_narrative"),
        )
        for idx, module in enumerate(overview.get("modules") or []):
            if not isinstance(module, dict):
                continue
            m_key = _item_key(module, "id", idx)
            collect(
                f"implementation_overview.modules[{m_key}].narrative",
                module.get("narrative"),
            )
        for idx, item in enumerate(overview.get("items") or []):
            if not isinstance(item, dict):
                continue
            base = f"implementation_overview.items[{_item_key(item, 'id', idx)}]"
            collect(f"{base}.how", item.get("how"))
            collect(f"{base}.existing_integration", item.get("existing_integration"))
            collect(f"{base}.test_strategy", item.get("test_strategy"))

    for idx, contract in enumerate(content.get("api_contracts") or []):
        if not isinstance(contract, dict):
            continue
        base = f"api_contracts[{_item_key(contract, 'id', idx)}]"
        collect(f"{base}.description", contract.get("description"))
        data_source = contract.get("data_source")
        if isinstance(data_source, dict):
            collect(f"{base}.data_source.notes", data_source.get("notes"))

    impact = content.get("impact_analysis")
    if isinstance(impact, dict):
        collect("impact_analysis.business_impact", impact.get("business_impact"))
        for idx, feature in enumerate(impact.get("affected_features") or []):
            if not isinstance(feature, dict):
                continue
            feat_key = _item_key(feature, "feature", idx)
            collect(
                f"impact_analysis.affected_features[{feat_key}].description",
                feature.get("description"),
            )
        collect("impact_analysis.compat_risks", impact.get("compat_risks"))
        collect("impact_analysis.rollback_plan", impact.get("rollback_plan"))

    for idx, flow in enumerate(content.get("interaction_flows") or []):
        if not isinstance(flow, dict):
            continue
        flow_key = _item_key(flow, "id", idx)
        for s_idx, step in enumerate(flow.get("steps") or []):
            if not isinstance(step, dict):
                continue
            step_key = _item_key(step, "seq", s_idx)
            collect(
                f"interaction_flows[{flow_key}].steps[{step_key}].note",
                step.get("note"),
            )

    return results


def _block_fingerprint(block: dict) -> str:
    return json.dumps(block, sort_keys=True, ensure_ascii=False)


def diff_blueprint_blocks(old_content: Any, new_content: Any) -> dict:
    """两版本 block 级 diff：按 block_id 对齐，产出三分类（SCHEMA-07）。

    Returns:
        ``{"added": [...], "removed": [...], "modified": [...]}``——三组 block_id
        列表，各组 sorted 保证确定性输出。modified 判定用 canonical JSON 序列化比对。
    """
    old_map = {block["block_id"]: block for _path, block in iter_blocks(old_content)}
    new_map = {block["block_id"]: block for _path, block in iter_blocks(new_content)}
    added = sorted(set(new_map) - set(old_map))
    removed = sorted(set(old_map) - set(new_map))
    modified = sorted(
        bid
        for bid in set(old_map) & set(new_map)
        if _block_fingerprint(old_map[bid]) != _block_fingerprint(new_map[bid])
    )
    return {"added": added, "removed": removed, "modified": modified}
