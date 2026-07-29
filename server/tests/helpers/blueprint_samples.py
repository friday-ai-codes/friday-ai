"""blueprint/v1 合法样例工厂（PLAN 111-01 创建，111-04 集成测试复用）。

``make_blueprint(**overrides)`` 返回一份六段齐全、引用完整的合法样例：

- citations 池 3 条（repo_file / rag_chunk / knowledge_entity），被 findings /
  rationale 等块引用；
- 2 个 direct + 1 个 indirect repo_association；
- 2 个 feature_point；
- 2 个 implementation item（含跨仓 depends_on、wave、files_touched——其中一条
  ``action="remove"`` 供派生器 remove→delete 映射断言）。

overrides 浅覆盖顶层 key（如 ``make_blueprint(interaction_flows=[])``）。
"""

from __future__ import annotations

import copy
from typing import Any

__all__ = ["make_blueprint"]


def _block(
    block_id: str,
    text: Any,
    *,
    block_type: str = "paragraph",
    citations: list[str] | None = None,
) -> dict[str, Any]:
    block: dict[str, Any] = {"block_id": block_id, "type": block_type, "text": text}
    if citations is not None:
        block["citations"] = citations
    return block


_BASE_BLUEPRINT: dict[str, Any] = {
    "schema_version": "blueprint/v1",
    "meta": {
        "title": "习题生成蓝图样例",
        "project_id": "proj-0001",
        "summary": [_block("blk_meta_summary", "为项目补齐习题生成能力的跨仓实现蓝图。")],
        "language": "zh-CN",
        "revision_round": 0,
    },
    "requirement_spec": {
        "goal": [_block("blk_spec_goal", "用户可在练习页一键生成个性化习题。")],
        "background": [_block("blk_spec_background", "现有习题为静态题库，无法按知识点生成。")],
        "feature_points": [
            {
                "id": "fp_01",
                "title": "习题生成接口",
                "description": [_block("blk_fp01_desc", "后端提供按知识点生成习题的接口。")],
                "acceptance_criteria": ["POST /api/practice/generate 返回习题列表"],
            },
            {
                "id": "fp_02",
                "title": "练习页生成入口",
                "description": [_block("blk_fp02_desc", "前端练习页接入生成入口并展示结果。")],
                "acceptance_criteria": ["练习页点击生成后 3s 内展示首批习题"],
            },
        ],
        "boundaries": {"in_scope": ["习题生成主链路"], "out_of_scope": ["批改能力"]},
    },
    "repo_associations": [
        {
            "repository_id": "repo-backend",
            "repository_name": "onion-practice",
            "role": "direct",
            "rationale": {
                "text": [
                    _block(
                        "blk_ra_backend_rationale",
                        "生成逻辑归属练习域后端。",
                        citations=["cit_repo_file"],
                    )
                ],
                "citations": ["cit_repo_file"],
            },
            "responsibility": [_block("blk_ra_backend_resp", "提供生成接口与题目持久化。")],
            "fitness": {
                "verdict": "suitable",
                "reasons": [_block("blk_ra_backend_fit", "已有题库模型与生成雏形。")],
                "citations": ["cit_repo_file"],
            },
            "planned_change_summary": [
                _block("blk_ra_backend_change", "新增生成接口并下线旧入口。")
            ],
            "decided_by": "ai",
            "confirmed_at_gate": True,
        },
        {
            "repository_id": "repo-frontend",
            "repository_name": "study-app",
            "role": "direct",
            "rationale": {
                "text": [
                    _block(
                        "blk_ra_frontend_rationale",
                        "练习页归属前端仓。",
                        citations=["cit_knowledge"],
                    )
                ],
                "citations": ["cit_knowledge"],
            },
            "responsibility": [_block("blk_ra_frontend_resp", "练习页接入生成入口。")],
            "fitness": {
                "verdict": "suitable",
                "reasons": [_block("blk_ra_frontend_fit", "组件化程度满足快速接入。")],
            },
            "planned_change_summary": [_block("blk_ra_frontend_change", "改造练习页与结果组件。")],
            "decided_by": "human",
            "confirmed_at_gate": True,
        },
        {
            "repository_id": "repo-shared",
            "repository_name": "study-course",
            "role": "indirect",
            "rationale": {
                "text": [_block("blk_ra_shared_rationale", "章节与知识点数据来源。")],
            },
            "capabilities_used": [
                {
                    "name": "章节目录接口",
                    "location": "src/api/chapters",
                    "how_used": "生成时取知识点",
                }
            ],
            "support_needed": [_block("blk_ra_shared_support", "需确认章节接口的知识点字段完备。")],
            "decided_by": "ai",
            "confirmed_at_gate": False,
        },
    ],
    "current_state_analysis": [
        {
            "repository_id": "repo-backend",
            "summary": [_block("blk_cs_backend_summary", "后端已有静态题库读取能力。")],
            "findings": [
                {
                    "id": "cs_01",
                    "topic": "生成能力现状",
                    "text": [
                        _block(
                            "blk_cs01_text",
                            "经调研，仓内存在旧生成入口，需改造为按知识点生成。",
                            citations=["cit_repo_file"],
                        )
                    ],
                    "kind": "capability",
                    "related_feature_points": ["fp_01"],
                    "citations": ["cit_repo_file"],
                }
            ],
        },
        {
            "repository_id": "repo-frontend",
            "findings": [
                {
                    "id": "cs_02",
                    "topic": "练习页调用链",
                    "text": [
                        _block(
                            "blk_cs02_text",
                            "练习页当前直连旧接口，缺少生成入口。",
                            citations=["cit_rag_chunk"],
                        )
                    ],
                    "kind": "gap",
                    "related_feature_points": ["fp_02"],
                    "citations": ["cit_rag_chunk"],
                }
            ],
        },
    ],
    "implementation_overview": {
        "requirement_narrative": [
            _block("blk_impl_narrative", "后端先落生成接口，前端随后接入展示。")
        ],
        "modules": [
            {
                "id": "mod_01",
                "name": "习题生成模块",
                "feature_point_ids": ["fp_01", "fp_02"],
                "repository_ids": ["repo-backend", "repo-frontend"],
                "narrative": [_block("blk_mod01_narrative", "生成接口与页面入口构成最小闭环。")],
            }
        ],
        "items": [
            {
                "id": "impl_01",
                "feature_point_id": "fp_01",
                "module_id": "mod_01",
                "repository_id": "repo-backend",
                "change_type": "create",
                "title": "新增习题生成接口",
                "how": [
                    _block("blk_impl01_how", "在练习域新增生成接口，复用题库模型。"),
                    {
                        "block_id": "blk_impl01_pseudo",
                        "type": "pseudocode",
                        "code": {
                            "language": "python",
                            "source": "def generate(chapter_id):\n    return build_questions(chapter_id)",
                        },
                    },
                ],
                "files_touched": [
                    {"path": "src/api/generate.py", "action": "create", "note": "生成入口"},
                    {
                        "path": "src/api/legacy_generate.py",
                        "action": "remove",
                        "note": "移除旧入口",
                    },
                ],
                "depends_on": [],
                "wave": 1,
                "test_strategy": [_block("blk_impl01_test", "接口级用例覆盖生成成功与超时降级。")],
                "citations": ["cit_repo_file"],
            },
            {
                "id": "impl_02",
                "feature_point_id": "fp_02",
                "module_id": "mod_01",
                "repository_id": "repo-frontend",
                "change_type": "modify",
                "title": "练习页接入生成入口",
                "how": [
                    _block(
                        "blk_impl02_how",
                        ["新增生成按钮", "轮询生成结果并渲染"],
                        block_type="list",
                    )
                ],
                "existing_integration": [
                    _block("blk_impl02_integration", "与既有练习提交链路共用结果组件。")
                ],
                "files_touched": [
                    {"path": "src/pages/Practice.vue", "action": "modify", "note": "接入入口"}
                ],
                "depends_on": ["impl_01"],
                "wave": 2,
                "citations": ["cit_rag_chunk"],
            },
        ],
    },
    "api_contracts": [
        {
            "id": "api_01",
            "name": "生成习题",
            "kind": "http",
            "direction": "provided",
            "repository_id": "repo-backend",
            "method": "POST",
            "path": "/api/practice/generate",
            "description": [_block("blk_api01_desc", "按章节与难度生成习题列表。")],
            "consumers": ["mod_01"],
            "citations": ["cit_repo_file"],
        },
        {
            "id": "api_02",
            "name": "章节目录",
            "kind": "http",
            "direction": "consumed",
            "repository_id": "repo-frontend",
            "method": "GET",
            "path": "/api/course/chapters",
            "data_source": {
                "from_service": "study-course",
                "from_api": "GET /api/course/chapters",
                "fields_needed": ["chapter_id", "knowledge_points"],
                "availability": "existing",
                "notes": [_block("blk_api02_notes", "章节接口已有，无需对方新增支持。")],
            },
        },
    ],
    "impact_analysis": {
        "business_impact": [
            _block("blk_impact_business", "练习主流程新增生成入口，不影响既有做题路径。")
        ],
        "affected_features": [
            {
                "feature": "练习提交链路",
                "repository_ids": ["repo-frontend"],
                "kind": "behavior_change",
                "description": [
                    _block("blk_impact_feature_desc", "结果组件复用可能引入渲染分支。")
                ],
                "citations": ["cit_rag_chunk"],
            }
        ],
        "regression_scope": [{"area": "习题提交链路", "level": "smoke", "reason": "共用结果组件"}],
        "compat_risks": [_block("blk_impact_compat", "旧生成入口下线需灰度。")],
        "rollback_plan": [_block("blk_impact_rollback", "关闭生成入口开关即可回滚。")],
    },
    "interaction_flows": [
        {
            "id": "flow_01",
            "name": "用户生成习题主路径",
            "trigger": "用户在练习页点击开始生成",
            "steps": [
                {
                    "seq": 1,
                    "actor": "frontend",
                    "action": "调用生成接口",
                    "component": "Practice.vue",
                    "api_ref": "api_01",
                    "data_in": "chapter_id, difficulty",
                    "data_out": "practice_id",
                    "note": [_block("blk_flow01_step1_note", "按钮置 loading，防重复提交。")],
                },
                {"seq": 2, "actor": "backend", "action": "生成并返回习题列表"},
            ],
        }
    ],
    "must_haves": {
        "truths": ["用户在练习页点击生成后 3s 内看到首批习题"],
        "artifacts": [{"path": "repo-backend/src/api/generate.py", "provides": "生成入口"}],
        "key_links": [
            {"from": "Practice.vue", "to": "POST /api/practice/generate", "via": "api_01"}
        ],
    },
    "citations": {
        "cit_repo_file": {
            "citation_id": "cit_repo_file",
            "source_type": "repo_file",
            "source_id": "repo-backend:src/api/legacy_generate.py",
            "locator": {
                "file_path": "src/api/legacy_generate.py",
                "line_start": 10,
                "line_end": 42,
            },
            "quote": "既有生成入口实现",
            "title": "legacy_generate.py",
        },
        "cit_rag_chunk": {
            "citation_id": "cit_rag_chunk",
            "source_type": "rag_chunk",
            "source_id": "chunk-0001",
            "quote": "前端练习页当前直连旧接口",
            "title": "练习页调用链检索片段",
        },
        "cit_knowledge": {
            "citation_id": "cit_knowledge",
            "source_type": "knowledge_entity",
            "source_id": "entity-0002",
            "quote": "repo-frontend 承载练习相关页面",
            "title": "仓库职责知识条目",
        },
    },
}


def make_blueprint(**overrides: Any) -> dict[str, Any]:
    """返回一份合法 blueprint/v1 深拷贝样例；``overrides`` 浅覆盖顶层 key。"""
    blueprint = copy.deepcopy(_BASE_BLUEPRINT)
    blueprint.update(overrides)
    return blueprint
