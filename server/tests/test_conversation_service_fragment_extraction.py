"""implementation Task 1: 字节级无损断言 — 抽取出的模块级常量正确。

重构目标：把 `_build_system_prompt` 内的局部字面量抽为模块级 `Final[str]`，
供 0002 data migration 跨 app import 时作为 seed。
断言常量结构（开头、关键词、换行）而非完整字节比对（避免与 0002 migration hash 测试冗余）。
"""
from __future__ import annotations

from chat.conversation_service import (
    _CODING_GUIDANCE,
    _ENDING_RULES,
    _SEARCH_USAGE_RULES,
    _STRATEGY_DEEP_ANALYSIS,
    _STRATEGY_DEFAULT,
    _TOOL_BUDGET_RULES,
    ROLE_PROMPTS,
)


def test_strategy_default_starts_correctly() -> None:
    """_STRATEGY_DEFAULT 单策略形态：仅快速检索，禁止主动 deep_analysis。

    历史上含"策略一 / 策略二"双策略，会诱导 LLM 在未开「深度分析」开关时
    自主调用 deep_analysis。重构为单策略后该现象消失，工具闸门由
    `_get_tool_names(force_deep_analysis=...)` 落实。
    """
    assert _STRATEGY_DEFAULT.startswith("回答策略 - 快速检索")
    assert "search_repository_code" in _STRATEGY_DEFAULT
    # 反向断言：旧的双策略关键词不再出现
    assert "策略一" not in _STRATEGY_DEFAULT
    assert "策略二" not in _STRATEGY_DEFAULT
    # 明确禁用 deep_analysis 主动调用
    assert "不要主动调用 deep_analysis" in _STRATEGY_DEFAULT


def test_strategy_deep_analysis_is_final_str() -> None:
    """_STRATEGY_DEEP_ANALYSIS 以"用户已开启"开头包含关键指令。

    Phase P15：升级为「路由器 / 派单员」语义 — RAG 仅定位仓库、
    必须并行 dispatch 多个 deep_analysis 容器。关键词随之更新。
    """
    assert _STRATEGY_DEEP_ANALYSIS.startswith("用户已开启「深度分析」")
    # P15 新语义：RAG 工具被严格限定为「定位仓库」
    assert "只能用来「定位哪些仓库相关」" in _STRATEGY_DEEP_ANALYSIS
    # P15 新语义：强制并行 dispatch
    assert "必须并行 dispatch" in _STRATEGY_DEEP_ANALYSIS
    assert "并行 dispatch N 个" in _STRATEGY_DEEP_ANALYSIS
    # P15 新语义：宁可多开
    assert "宁可多开" in _STRATEGY_DEEP_ANALYSIS


def test_strategy_deep_analysis_prepares_with_graph_walk() -> None:
    """_STRATEGY_DEEP_ANALYSIS：派单前用 find_related_code 沿关系图做好准备。

    用户诉求：深度分析模式应「做好全部准备后再调用仓库深度分析」——
    搜到具体符号/文件后用 find_related_code 摸清跨文件/跨仓关联，既避免漏派
    间接相关仓库，又能写出聚焦的 task_description。准备充分再并行 dispatch。
    """
    assert "find_related_code" in _STRATEGY_DEEP_ANALYSIS
    assert "派单前做好准备" in _STRATEGY_DEEP_ANALYSIS
    assert "准备充分再 dispatch" in _STRATEGY_DEEP_ANALYSIS
    assert "task_description" in _STRATEGY_DEEP_ANALYSIS
    # 旧的并行 dispatch / 定位语义不被破坏
    assert "只能用来「定位哪些仓库相关」" in _STRATEGY_DEEP_ANALYSIS
    assert "必须并行 dispatch" in _STRATEGY_DEEP_ANALYSIS


def test_coding_guidance_has_leading_newline() -> None:
    """_CODING_GUIDANCE 前导换行 + "编码任务识别"开头。"""
    # 原函数内 coding_guidance 以 "\n编码任务识别" 开头（保持前导换行）
    assert _CODING_GUIDANCE.startswith("\n编码任务识别：\n")
    assert "create_coding_plan" in _CODING_GUIDANCE
    assert "update_coding_plan" in _CODING_GUIDANCE
    # SPINE-02（109-05）：口径改为「编排产出方案版本 → 投影」，两个编排工具都要提名，
    # 且不再教模型撰写方案正文。
    assert "start_plan_research" in _CODING_GUIDANCE
    assert "start_feature_solution" in _CODING_GUIDANCE
    assert "分步实现步骤" not in _CODING_GUIDANCE


def test_ending_rules_three_lines() -> None:
    """_ENDING_RULES 含 3 行结尾规则，末尾为"用中文回答"。"""
    # 3 行结尾规则（每行一个 \n）
    assert _ENDING_RULES.count("\n") == 3
    assert "用中文回答。\n" in _ENDING_RULES
    assert "不要在回复中描述工具操作" in _ENDING_RULES


def test_role_prompts_has_five_roles() -> None:
    """ROLE_PROMPTS 保持 5 个 role key 不变。"""
    assert set(ROLE_PROMPTS.keys()) == {"developer", "pm", "designer", "qa", "general"}


def test_tool_budget_rules_fragment_present() -> None:
    """_TOOL_BUDGET_RULES 包含工具调用预算关键约束（与 _ToolBudget 实现强耦合）。"""
    assert "工具调用预算" in _TOOL_BUDGET_RULES
    # max_turns 数值不在 fragment 里写死，只说"约 50 次"以容忍配置漂移
    assert "50 次" in _TOOL_BUDGET_RULES
    # browse_file_content 单文件硬上限提示
    assert "browse_file_content" in _TOOL_BUDGET_RULES
    assert "3 次" in _TOOL_BUDGET_RULES
    # 去重提示
    assert "去重" in _TOOL_BUDGET_RULES


def test_search_usage_rules_fragment_present() -> None:
    """_SEARCH_USAGE_RULES 包含 search_repository_code 的正反例与调优建议。

    这是 Phase P15 关键 prompt 修复，避免 LLM 把多个关键词塞进一个
    query 导致 0 结果。
    """
    assert "search_repository_code 使用规范" in _SEARCH_USAGE_RULES
    # 正例
    assert "studyRoom" in _SEARCH_USAGE_RULES
    assert "UserService" in _SEARCH_USAGE_RULES
    # 反例（用户实际遇到的）
    assert "shareRoom" in _SEARCH_USAGE_RULES
    assert "灾难性差" in _SEARCH_USAGE_RULES
    # 调优建议
    assert "min_score" in _SEARCH_USAGE_RULES


def test_search_usage_rules_guides_graph_walk() -> None:
    """_SEARCH_USAGE_RULES 引导「搜到代码片段后用 find_related_code 沿关系图深入」。

    避免 LLM 只会 RAG 模糊检索、拿到孤立片段就停手，不利用已注册的 chunk 级
    关系图遍历能力（CALL / IMPORT / TEST_OF）做更深入的需求分析。
    """
    assert "find_related_code" in _SEARCH_USAGE_RULES
    assert "关系图" in _SEARCH_USAGE_RULES
    # 上下游 / 测试三类典型用法都给了示例
    assert "upstream" in _SEARCH_USAGE_RULES
    assert "downstream" in _SEARCH_USAGE_RULES
    assert "TEST_OF" in _SEARCH_USAGE_RULES
