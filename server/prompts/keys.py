"""所有内置 prompt 的 slug 常量 — 代码引用的单一权威来源。
新增 slug 时只改本文件；BUILTIN_SLUGS 自动派生。
这是防 v18.1 G3 同型错误的契约基石
（参考 server/agents/core/events.py:ALL_EVENT_TYPES 模式）。
"""
from __future__ import annotations
from typing import Final
class PromptSlugs:
 """所有内置 Prompt 的 slug 常量命名空间。
 命名约定：`<category>.<subcategory>.<specifier>` 小写点分。
 """
 # --- Chat Agent (5 roles + 2 strategies + 1 coding guidance) ---
 CHAT_SYSTEM_DEVELOPER: Final[str] = "chat.system.developer"
 CHAT_SYSTEM_PM: Final[str] = "chat.system.pm"
 CHAT_SYSTEM_DESIGNER: Final[str] = "chat.system.designer"
 CHAT_SYSTEM_QA: Final[str] = "chat.system.qa"
 CHAT_SYSTEM_GENERAL: Final[str] = "chat.system.general"
 CHAT_STRATEGY_DEFAULT: Final[str] = "chat.strategy.default"
 CHAT_STRATEGY_DEEP_ANALYSIS: Final[str] = "chat.strategy.deep_analysis"
 CHAT_CODING_GUIDANCE: Final[str] = "chat.coding_guidance"
 # --- Auxiliary Models (2) ---
 AUX_TITLE_GENERATION: Final[str] = "aux.title_generation"
 AUX_COMMIT_MESSAGE: Final[str] = "aux.commit_message"
 # --- AI Workflow Nodes (4) ---
 AI_NODE_PROMPT_DEFAULT: Final[str] = "ai_node.prompt.default_system"
 AI_NODE_CODE_REVIEW: Final[str] = "ai_node.code_review.system"
 AI_NODE_PLAN_GENERATION: Final[str] = "ai_node.plan_generation.system"
 AI_NODE_VARIABLE_EXTRACTOR: Final[str] = "ai_node.variable_extractor.template"
 # --- Feishu Bot (v19.0 拆分) ---
 FEISHU_GROUP_CHAT_SYSTEM: Final[str] = "feishu.group_chat.system"
 # --- Repository Summary (v19.0 Phase 依赖) ---
 REPO_SUMMARY_GENERATOR: Final[str] = "repo.summary_generator"
BUILTIN_SLUGS: frozenset[str] = frozenset(
 v
 for k, v in vars(PromptSlugs).items
 if not k.startswith("_") and isinstance(v, str)
)
# Load-time 契约锁：新增 slug 必须同时更新此断言
# 分类统计：Chat 8 (5 role + 2 strategy + 1 coding) + Aux 2 + AI Node 4 + Feishu 1 + Repo 1 = 16
assert len(BUILTIN_SLUGS) == 16, (
 f"BUILTIN_SLUGS count drift: got {len(BUILTIN_SLUGS)}, expected 16"
)
