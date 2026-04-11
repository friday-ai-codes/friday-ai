"""Phase Task 1: 字节级无损断言 — 抽取出的模块级常量正确。
重构目标：把 `_build_system_prompt` 内的局部字面量抽为模块级 `Final[str]`，
供 0002 data migration 跨 app import 时作为 seed。
断言常量结构（开头、关键词、换行）而非完整字节比对（避免与 0002 migration hash 测试冗余）。
"""
from __future__ import annotations
from chat.conversation_service import (
 _CODING_GUIDANCE,
 _ENDING_RULES,
 _STRATEGY_DEEP_ANALYSIS,
 _STRATEGY_DEFAULT,
 ROLE_PROMPTS,
)
def test_strategy_default_starts_correctly -> None:
 """_STRATEGY_DEFAULT 以"你有两种策略应对用户问题"开头。"""
 assert _STRATEGY_DEFAULT.startswith("你有两种策略应对用户问题：\n\n")
 assert "deep_analysis" in _STRATEGY_DEFAULT
 assert "策略一 - 快速检索" in _STRATEGY_DEFAULT
 assert "策略二 - 深度分析" in _STRATEGY_DEFAULT
def test_strategy_deep_analysis_is_final_str -> None:
 """_STRATEGY_DEEP_ANALYSIS 以"用户已开启"开头包含关键指令。"""
 assert _STRATEGY_DEEP_ANALYSIS.startswith("用户已开启「深度分析」")
 assert "禁止仅用 RAG 工具拼凑回答" in _STRATEGY_DEEP_ANALYSIS
 assert "必须调用 deep_analysis" in _STRATEGY_DEEP_ANALYSIS
def test_coding_guidance_has_leading_newline -> None:
 """_CODING_GUIDANCE 前导换行 + "编码任务识别"开头。"""
 # 原函数内 coding_guidance 以 "\n编码任务识别" 开头（保持前导换行）
 assert _CODING_GUIDANCE.startswith("\n编码任务识别：\n")
 assert "create_coding_plan" in _CODING_GUIDANCE
 assert "update_coding_plan" in _CODING_GUIDANCE
def test_ending_rules_three_lines -> None:
 """_ENDING_RULES 含 3 行结尾规则，末尾为"用中文回答"。"""
 # 3 行结尾规则（每行一个 \n）
 assert _ENDING_RULES.count("\n") == 3
 assert "用中文回答。\n" in _ENDING_RULES
 assert "不要在回复中描述工具操作" in _ENDING_RULES
def test_role_prompts_has_five_roles -> None:
 """ROLE_PROMPTS 保持 5 个 role key 不变。"""
 assert set(ROLE_PROMPTS.keys) == {"developer", "pm", "designer", "qa", "general"}
