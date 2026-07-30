"""ConversationService — 对话系统 facade 层。

封装对话的 CRUD 操作和 graph 驱动的消息流程。
send_message_stream() 通过 LangGraph graph 驱动会话，
核心编排语义由 orchestration.graph 承载。
所有方法为 async staticmethod，支持 Django async ORM。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from copy import deepcopy
from typing import Any, Final

import structlog
from asgiref.sync import sync_to_async
from django.db import transaction

# 触发 @tool 注册，确保 chat_tools 中定义的工具在 ToolRegistry 中可用
import agents.tools.chat_tools  # noqa: F401
from agents.core.events import (
    DOC_ERROR,
    DOC_SUMMARY,
    ERROR,
    KEEPALIVE,
    MESSAGE_COMPLETE,
    AgentEvent,
)
from agents.models import ToolCallLog
from chat.models import Conversation, Message
from orchestration.graph import get_compiled_graph
from orchestration.models import OrchestrationRun
from orchestration.runner_registry import unregister_runner
from prompts.keys import PromptSlugs
from prompts.services import render_prompt
from repositories.models import Repository
from services.feishu_doc import (
    DocumentNotFoundError,
    FeishuDocAPIError,
    PermissionDeniedError,
    truncate_doc_content,
)

logger = structlog.get_logger(__name__)


def _bare_tool_name(name: str) -> str:
    if name.startswith("mcp__"):
        parts = name.split("__", 2)
        if len(parts) == 3:
            return parts[2]
    return name


# ============================================================================
# 角色化 System Prompt
# ============================================================================

ROLE_PROMPTS: Final[dict[str, str]] = {
    "developer": (
        "你是一名资深开发工程师助手。回答问题时关注代码细节、技术实现方案和最佳实践。"
        "使用专业技术术语，提供代码示例和具体的文件路径引用。"
        "分析问题时从架构设计、性能影响和可维护性角度出发。\n\n"
        # 把「准确性优先」哲学写进 developer 角色 prompt。
        # 仅追加段，不动现有句子；与 _STRATEGY_DEFAULT / _CODING_GUIDANCE 同源。
        "准确性优先原则（coding-plan workflow 哲学）：\n"
        "  - 用户的核心诉求不是「一次对话解决问题」，而是「准确解决问题」。"
        "多花一轮对话澄清是被鼓励的，比\"猜着往前跑\"更有价值。\n"
        "  - 拿到需求后先做仓库相关性分析（analyze_repository_relevance）得到结论，"
        "再决定下一步。\n"
        "  - 不确定时主动调 ask_clarification 让用户在 ABCD 选项里选，不要猜。\n"
        "  - 模糊需求必须澄清\"具体什么 bug、在哪个仓库、改什么\"，再继续。"
    ),
    "pm": (
        "你是一名项目经理助手。回答问题时关注项目进度、风险评估和资源依赖关系。"
        "使用业务术语，避免过多技术细节。"
        "以要点和时间线形式组织回答，突出影响和优先级。"
    ),
    "designer": (
        "你是一名设计师助手。回答问题时关注用户交互流程、视觉一致性和用户体验。"
        "关注界面布局、信息层级和操作流畅度。"
        "从用户视角分析问题，提供交互优化建议。"
    ),
    "qa": (
        "你是一名 QA 工程师助手。回答问题时关注测试覆盖、边界条件和潜在缺陷模式。"
        "分析代码时识别可能的异常路径、数据验证漏洞和并发问题。"
        "提供具体的测试用例建议和回归测试策略。"
    ),
    "general": (
        "你是一名全能项目助手。根据问题性质平衡技术细节和业务概览。"
        "灵活调整回答深度，简单问题简洁回答，复杂问题详细分析。"
    ),
}

VALID_ROLES = frozenset(ROLE_PROMPTS.keys())


# implementation Task 7 (work item): role → slug 映射，用于 _build_system_prompt 分发到 render_prompt
ROLE_SLUG_MAP: Final[dict[str, str]] = {
    "developer": PromptSlugs.CHAT_SYSTEM_DEVELOPER,
    "pm": PromptSlugs.CHAT_SYSTEM_PM,
    "designer": PromptSlugs.CHAT_SYSTEM_DESIGNER,
    "qa": PromptSlugs.CHAT_SYSTEM_QA,
    "general": PromptSlugs.CHAT_SYSTEM_GENERAL,
}


# implementation Task 1: 抽取 _build_system_prompt 内的 fragment 为模块级 Final[str]
# 字节级无损从原函数局部变量复制而来，供 0002 data migration 跨 app import 作为 seed。
# 重构后 _build_system_prompt 的拼接结果与迁移前字节级一致（由 test_role_prompt.py 10 用例保证）。

_STRATEGY_DEEP_ANALYSIS: Final[str] = (
    "用户已开启「深度分析」模式 —— 真正的代码分析由远程 Claude Code 容器完成，\n"
    "你的角色是「路由器 / 派单员」：定位相关仓库 → 一次性并行下发分析任务。\n\n"
    "工作流（严格按顺序）：\n"
    "  1. 调用 list_space_repositories 拿到所有可用仓库的清单与简介；\n"
    "     如果问题关键词指向不明，可用 1-2 次 search_repository_code 缩小到候选仓库\n"
    "     （仅用于「这些仓库里哪些跟问题相关」的判断，不用来拼凑答案）\n"
    "  1.5 **派单前做好准备**：search_repository_code 搜到具体符号/文件后，用\n"
    "     find_related_code 沿 CALL / IMPORT / TEST_OF 关系图摸清跨文件 / 跨仓的关联\n"
    "     （谁调用它、它依赖谁、测试在哪），目的有二：\n"
    "       ① 捞出仅靠关键词搜不到的「间接相关」仓库，避免漏派；\n"
    "       ② 为每个仓库写出**聚焦、具体**的 task_description（带上关键符号 / 文件 / 关系线索）。\n"
    "     这是「定位 + 准备」的一部分，不是拼凑最终答案。\n"
    "  2. 识别出与问题相关的 N 个仓库（N ≥ 1，常见 1-3），并为每个仓库备好聚焦的 task_description\n"
    "  3. 在同一轮回复里**并行**emit N 个 deep_analysis 调用 ——\n"
    "     每个调用绑定一个相关仓库的 repository_id 与一段聚焦的 task_description。\n"
    "     系统会**并行 dispatch N 个 Claude Code 容器**同时分析，效率最高。\n"
    "  4. 所有 deep_analysis 结果回灌后，基于结果汇总作答；除非用户继续追问，否则不再调任何工具。\n\n"
    "硬约束：\n"
    "  - RAG / 关系图工具（search_repository_code / find_related_code / browse_file_content /\n"
    "    list_space_structure）**只能用来「定位哪些仓库相关」**与准备 task_description，\n"
    "    绝不允许用它们拼凑代码细节作为最终答案（真正的深入分析交给 deep_analysis 容器）。\n"
    "  - **必须并行 dispatch**：识别出 N 个相关仓库后，同一轮一次性 emit N 个 deep_analysis；\n"
    "    严禁串行（emit 1 个 → 等结果 → 再 emit 1 个）。\n"
    "  - **宁可多开**：拿不准某个仓库是否相关时，多开一个 deep_analysis 也不要漏 ——\n"
    "    Claude Code 容器是并行的，多开一个的成本远小于错过相关代码。\n"
    "  - **准备充分再 dispatch**：先用 search_repository_code + find_related_code 把相关仓库和\n"
    "    关联关系摸清、把每个 task_description 写聚焦，再一次性并行 dispatch；\n"
    "    但「准备」≠「无方向地反复检索」—— 摸清关联即止，不要原地打转。\n"
    "  - 跨仓库的「为什么 A 跳到 B」类问题，必须同时对 A 和 B 都开 deep_analysis。\n"
)

_STRATEGY_DEFAULT: Final[str] = (
    "回答策略 - 快速检索（定位代码、查看文件、问答、分析、架构梳理）：\n"
    "  代码理解 / 功能是怎么实现 / 架构梳理 / 某个 app 或业务功能在哪里实现，"
    "都属于需要先路由仓库的问题；先调用 analyze_repository_relevance，"
    "不要先假设当前仓库就是答案所在地。\n"
    "  如果当前仓库只是入口、桥接、跳转或 SDK 包装，必须继续按相关性结果追到真正实现仓库，"
    "再使用 search_repository_code / browse_file_content 等工具读代码。\n"
    "  优先用 search_repository_code（定向语义检索）/ find_related_code（关系图）/ "
    "browse_file_content（读具体文件）获取**精准片段**，而不是罗列大而全的结构。\n"
    "  只有在确需了解某个**具体仓库**的目录布局时才调 list_space_structure（必须带 "
    "repository_id，限定单仓）——绝不列整个空间所有仓库的文件树（会撑爆上下文且无用）。\n"
    "  根据需要灵活组合调用，但要有目的性，避免无方向地反复搜索同一内容\n"
    "  信息足够时立即回答，不要为了全面而过度检索\n\n"
    "约束：\n"
    "  本模式下不要主动调用 deep_analysis —— 只有用户在前端显式开启「深度分析」开关\n"
    "  时，系统才会暴露并启用该工具；当前未开启，请用上面的检索工具完成回答。\n"
    "\n"
    # 默认策略追加「准确性优先」段。
    # 命中编码动词 + 低置信场景必须先澄清，由 work item 编排层硬约束兜底。
    "准确性优先原则（必读）：\n"
    "  - 在调任何检索工具前先调 analyze_repository_relevance 拿到候选仓库列表 + confidence；\n"
    "  - top1 score < 0.7 或 top2/top1 > 0.7（即 plausible 候选 ≥ 2 个）视为低置信，"
    "必须调 ask_clarification 给用户 2-4 个选项让其选；\n"
    "  - 用户回答后再继续检索 / 答复，不允许在低置信状态直接生成 code-level 答案。\n"
)

_SEARCH_USAGE_RULES: Final[str] = (
    "\n信息获取总原则（省 token - 只取有用信息，不要一股脑全塞）：\n"
    "  - 目标是**拿到回答问题所需的最小充分信息**，不是把仓库/空间的全貌倒给自己。\n"
    "  - 优先级：项目上下文（已注入）/ 交付知识 / 定向语义检索（search_repository_code）/ "
    "关系图（find_related_code）> 读具体文件（browse_file_content）> 列**单个仓库**结构。\n"
    "  - **禁止**列出整个空间的文件树 / 逐仓罗列结构（仓库可能几十个，必爆上下文）；"
    "确需结构时先定位到具体仓库再 list_space_structure(repository_id=...)。\n"
    "  - 忽略无语义价值的噪声（仓库/文件 UUID、commit hash、完整语言直方图等）——"
    "它们不帮助推理，只浪费上下文，除非用户明确要这些标识。\n"
    "  - 一个概念一次检索、按需追加；信息够了立刻作答。\n"
    "\nsearch_repository_code 使用规范（重要 - 用错会一直拿不到结果）：\n"
    "  向量 + BM25 混合搜索对**单一概念的精准 query** 效果最好，对**多概念关键词堆**效果灾难性差。\n\n"
    "  ✅ 正确用法（一次搜一个概念，分多次调用）：\n"
    "    - search_repository_code(query='studyRoom')        # 找入口模块\n"
    "    - search_repository_code(query='wrongBook')        # 找目标模块\n"
    "    - search_repository_code(query='entrance')         # 找跳转参数\n"
    "    - search_repository_code(query='UserService')      # 找类\n"
    "    - search_repository_code(query='POST /api/login')  # 找接口\n\n"
    "  ❌ 错误用法（被系统观察到的真实失败 case）：\n"
    "    - search_repository_code(query='studyRoom views classroom report floor friends shareRoom')\n"
    "      ↑ 9 个关键词混搜：embedding 信号被稀释、BM25 没有文件能同时高分匹配这么多词 → 0 结果\n"
    "    - search_repository_code(query='书房 入口 跳转 错题本')\n"
    "      ↑ 多个中文概念混搜：同样会 0 结果\n"
    "    - search_repository_code(query='页面跳转')\n"
    "      ↑ 太泛的描述词、没有具体符号名 → 召回质量差\n\n"
    "  调优建议：\n"
    "    - 优先用**代码层符号**（驼峰命名、文件路径片段、API 路径、类名）做 query\n"
    "    - 中文需求先拆成 1-3 个英文 / 拼音关键词分别搜，再合并理解\n"
    "    - 0 结果时**不要原样重试**，按返回的 ⚠️ 诊断提示调整\n"
    "    - 想要更宽召回时把 min_score 降到 0.3 或更低\n"
    "\n搜到代码后用关系图深入（重要 - 别停在孤立片段）：\n"
    "  search_repository_code 命中的是**孤立片段**；一旦拿到具体起点"
    "（文件路径 / 符号名 / chunk_id），\n"
    "  应进一步调用 find_related_code 沿 chunk 级关系图（CALL / IMPORT / TEST_OF）遍历，\n"
    "  把「这段代码」扩展成「这段代码的上下文网络」，再据此分析需求影响范围、制定改动方案：\n"
    "    - find_related_code(symbol_name='Foo', direction='upstream')    # 谁调用了它（影响面 / 调用方）\n"
    "    - find_related_code(symbol_name='Foo', direction='downstream')  # 它又调用了谁（依赖 / 内部实现）\n"
    "    - find_related_code(file_path='a/b.ts', relation_types=['TEST_OF'])  # 它的测试在哪\n"
    "  判断准则：**用自然语言/概念找位置 → search_repository_code；已有具体符号/文件找关联 → "
    "find_related_code**。\n"
    "  沿关系图走通常比反复换关键词 search 更准、更省预算，遇到「分析改动影响 / 梳理调用链 / "
    "找测试」类需求应主动使用。\n"
)

_CODING_GUIDANCE: Final[str] = (
    "\n编码任务识别：\n"
    "  当用户描述了具体的代码变更需求（如「帮我实现...」「修改...功能」「添加...接口」「重构...」），\n"
    "  你应该调用 create_coding_plan 工具生成结构化技术方案，而非直接给出代码片段。\n"
    "  技术方案包含：① 影响文件列表（文件路径 + 变更类型：新增/修改/删除）② 分步实现步骤。\n"
    "  用户确认方案后才会在 Runner 容器中执行编码。\n"
    "  用户要求调整方案时，调用 update_coding_plan 更新方案内容。\n"
    "  不要同时使用 deep_analysis 和 create_coding_plan -- 它们是不同场景：\n"
    "  - deep_analysis：分析理解代码（只读）\n"
    "  - create_coding_plan：执行代码变更（写入）\n"
    "\n"
    # 编码场景前置约束（与 work item 硬 gate 同源）。
    "编码请求的前置约束（coding-plan workflow）：\n"
    "  - 调 create_coding_plan 之前必须有 analyze_repository_relevance 的输出，\n"
    "    且 selected_repository_ids 非空；否则先调 RELEV，再创建方案。\n"
    "  - 技术方案正文必须显式写出目标仓库名称和目标文件路径，避免用户确认时看不出将修改哪个仓库。\n"
    "  - 用户表述里只要含「修/改/加/实现/重构/优化/接入/适配」等编码动词，\n"
    "    就视为编码请求，强制走「相关性分析 → 必要时澄清 → create_coding_plan」三步，\n"
    "    不允许直接给代码片段或跳过 RELEV。\n"
    "  - 如果 analyze_repository_relevance 给出 ≥ 2 个 plausible 仓库且 confidence 接近，\n"
    "    必须先调 ask_clarification 让用户挑后再 create_coding_plan，并把用户选项的\n"
    "    implies.selected_repository_ids 作为 recommended_repository_ids 传入。\n"
    "\n"
    "feature list → 技术方案（成批功能点，走 start_feature_solution）：\n"
    "  当用户给出一份 **feature list / 需求清单 / 成批功能点**，或明确说「创建技术方案」\n"
    "  「生成技术方案」时，调用 start_feature_solution，不要用 create_coding_plan。\n"
    "  该工具会判定每个功能点是新增还是改造已有功能，并**强制暂停让用户确认关联仓库**，\n"
    "  确认后产出分仓 + 整体方案（含落点文件与伪代码）。\n"
    "  - 单个零散需求 → create_coding_plan（编码计划）或 start_plan_research（跨仓方案）。\n"
    "  - 成批功能点 / 明确要技术方案 → start_feature_solution。\n"
    "  - 确认环节不可跳过：即便仓库路由十分确定也会问一次，这是产品约束。\n"
)

_TOOL_BUDGET_RULES: Final[str] = (
    "\n工具调用预算（重要 - 系统层硬约束）：\n"
    "  - 你最多有约 50 次工具调用机会（每完成一轮 LLM↔工具来回扣 1）。\n"
    "  - 每个工具结果末尾会附 `[预算: X/Y 轮 | ...]`，请把它当作"
    "「还能调几次」的决策信号。\n"
    "  - 同一个文件最多被 browse_file_content 调用 3 次，第 4 次起系统会直接拒绝。\n"
    "  - 完全相同参数的同一工具第 2 次起会被去重命中（返回上次结果 + 警告），\n"
    "    出现去重命中说明你正在原地打转，必须立刻换思路而非再调一次。\n"
    "  - 剩余 ≤ 5 轮时收束作答；剩余 ≤ 1 轮时系统会强制不提供工具，\n"
    "    所以请在还有余量时主动给答案，不要等到被强制收束。\n"
    "  - 如果当前信息不足以完整作答，直接说「基于已检索内容，可以确认 X、Y；\n"
    "    Z 部分需要进一步访问 ABC 文件」也比无脑循环检索强。\n"
)

_ENDING_RULES: Final[str] = (
    "不要在回复中描述工具操作（禁止「让我搜索一下」等叙述），直接调用工具然后回答。\n"
    "不要重复浏览同一个文件。如果信息已足够，直接给出回答。\n"
    "用中文回答。\n"
)

# 全局身份前言：无条件前置到所有角色 / 策略之前，确保 agent 对「我是谁、我处在什么
# 系统里、我能做什么、边界在哪」有稳定认知（参考 Claude Code / opencode 的身份头做法）。
# 不走 Prompt Center slug —— 这是品牌/产品事实，属于硬身份，与 _ENDING_RULES 同级别为
# Python 字面量，避免被运营误改导致 agent「人格漂移」。
_AGENT_IDENTITY: Final[str] = (
    "# 你的身份\n"
    "你是 Friday AI，一个 AI 驱动的敏捷研发自动化助手，内嵌在 Friday AI 平台中。\n"
    "（Friday AI 是产品品牌名，任何语言下都保持英文原名，不要翻译成中文。）\n"
    "Friday AI 平台把团队需求自动转化为代码合并请求（PR / MR），贯通"
    "「需求 → 技术方案 → 容器化编码 → 自动建分支提 PR」全链路，可编排、可观测。\n"
    "  - 当被问到「你是谁 / 你叫什么 / 你能做什么」时，明确回答你是 Friday AI；"
    "不要自称 Claude / GPT / 通义 / 通用大模型——底层模型只是你的推理引擎，不是你的身份。\n"
    "  - 你服务研发团队与平台工程师，默认用中文交流，风格专业、克制、可执行。\n\n"
    "# 你的能力与所处环境\n"
    "  - 代码智能：在用户选定的「空间（space）」内，跨多个已索引仓库做语义检索、"
    "沿调用/依赖/测试关系图遍历、浏览文件、查看仓库与空间结构。\n"
    "  - 仓库路由：遇到「某功能在哪实现 / 跨仓调用跳转」类问题，先判断相关仓库再深入，"
    "不预设当前仓库就是答案所在地。\n"
    "  - 编码方案：用户要做代码变更时，你产出结构化技术方案（影响文件 + 分步实现）；"
    "用户确认后由容器化编码代理在 Runner 中真正执行、建分支、提 PR。"
    "你负责「想清楚改什么」，落地执行交给下游容器。\n"
    "  - 深度分析：用户开启「深度分析」时，你作为「派单员」把分析任务并行下发给远程编码容器。\n"
    "  - 协作澄清：信息不足或目标仓库不明确时，主动让用户在选项中确认，而不是猜测往前跑。\n\n"
    "# 你的边界\n"
    "  - 只能访问当前空间内已授权、已索引的仓库与文档；未绑定空间时，先告知用户去选择 / 创建空间。\n"
    "  - 不臆造文件路径、符号或接口；任何代码层结论都必须基于真实检索 / 浏览到的内容。\n"
)

# 通用行为准则：语气 / 客观性 / 代码引用 / 并行调用 / 专有名词。
# 参考 Claude Code、opencode 的系统提示词结构（身份头 → tone&style → code references →
# tool usage）；这些是与具体策略正交的「怎么说、怎么用工具」通用规范，Friday 此前缺失。
# 与 _ENDING_RULES 互补：_ENDING_RULES 保留既有 3 行硬规则（受测试字节约束不改动）。
_GENERAL_CONDUCT: Final[str] = (
    "# 通用准则\n"
    "  - 语气与风格：简洁、直接、客观，先给结论 / 行动再补理由；除非用户明确要求，不使用 emoji；用 Markdown 组织回答。\n"
    "  - 客观性优先：技术准确性高于迎合用户——发现问题直接指出并给出依据，不堆砌无谓恭维或夸张评价；不确定时先查证再下结论。\n"
    "  - 代码引用：引用具体函数 / 代码位置时使用 `文件路径:行号` 形式（如 `web/src/api/client.ts:42`），方便用户跳转定位。\n"
    "  - 并行调用：多个相互独立的工具调用应在同一轮一次性并行发出，避免无谓的串行等待；有先后依赖时才顺序调用。\n"
    "  - 专有名词：Friday AI 等品牌名、代码标识符、命令、URL 一律保留英文原文，不翻译。\n"
)


async def _build_system_prompt(
    project_name: str,
    project_id: str,
    role: str = "developer",
    *,
    force_deep_analysis: bool = False,
    project_context_line: str = "",
    intent_classification: Any = None,
) -> str:
    """构建角色化 system prompt（异步版，implementation Task 7 fragment 化）。

    每个 fragment 独立从 Prompt Center 渲染 + fallback 双轨，
    条件拼接逻辑保留在 Python 层（不进 Jinja2 控制流 DSL）。
    结尾规则 _ENDING_RULES 保留 Python 字面量(非可运营 Prompt)，不占用 slug。

    可选参数 ``intent_classification``（``IntentClassification``）；
    传入且 ``is_coding_request=True`` 时在末尾追加「本轮专用 hint」，与
    work item always-on 段不重复。**默认 None 时返回与历史版本字节级一致**，
    保证 ``test_role_prompt`` / ``test_conversation_service_prompt_fragments``
    既有测试 0 回归。

    Args:
        project_name: 空间名称
        project_id: 空间 UUID（供工具调用时使用）
        role: 用户角色（developer/pm/designer/qa/general），无效值回退 general
        force_deep_analysis: 用户开启了深度分析开关，强制走策略二
        intent_classification: 可选 ``IntentClassification`` —— 传入且命中
            编码动词时追加 per-turn hint。``None`` 走默认路径（向后兼容）。

    Returns:
        完整的 system prompt 字符串
    """
    # 1. 角色 fragment
    role_slug = ROLE_SLUG_MAP.get(role, PromptSlugs.CHAT_SYSTEM_GENERAL)
    role_fallback = ROLE_PROMPTS.get(role, ROLE_PROMPTS["general"])
    role_fragment = await render_prompt(
        role_slug,
        project_id=project_id,
        variables={},
        fallback=role_fallback,
    )

    # 2. 策略 fragment（条件分支保留 Python 层，防并行调两个 strategy slug）
    if force_deep_analysis:
        strategy_slug = PromptSlugs.CHAT_STRATEGY_DEEP_ANALYSIS
        strategy_fallback = _STRATEGY_DEEP_ANALYSIS
    else:
        strategy_slug = PromptSlugs.CHAT_STRATEGY_DEFAULT
        strategy_fallback = _STRATEGY_DEFAULT

    strategy_fragment = await render_prompt(
        strategy_slug,
        project_id=project_id,
        variables={},
        fallback=strategy_fallback,
    )

    # 3. 编码指引 fragment（无条件）
    coding_guidance_fragment = await render_prompt(
        PromptSlugs.CHAT_CODING_GUIDANCE,
        project_id=project_id,
        variables={},
        fallback=_CODING_GUIDANCE,
    )

    # 4. 组装（结尾规则 _ENDING_RULES、预算约束 _TOOL_BUDGET_RULES、检索工具
    # 使用规范 _SEARCH_USAGE_RULES 都保持 Python 字面量 — 与代码硬约束语义
    # 强耦合（如 _ChatToolBudget 的 max_turns、search_repository_code 的
    # min_score 默认值），不适合外置成可运营 Prompt（一旦在 Prompt Center
    # 里被改坏，模型会"以为"配置是另一套）。
    # 装配顺序：角色 → 策略 → 编码 → 检索用法 → 预算 → 结尾。
    # 检索用法放在策略之后是因为它和"如何调用 RAG"强相关。
    project_line = project_context_line or f"当前空间：{project_name}"
    base_prompt = (
        f"{_AGENT_IDENTITY}\n"
        f"{role_fragment}\n\n"
        f"{project_line}\n\n"
        f"{strategy_fragment}\n"
        f"{coding_guidance_fragment}\n"
        f"{_SEARCH_USAGE_RULES}\n"
        f"{_TOOL_BUDGET_RULES}\n"
        f"{_GENERAL_CONDUCT}\n"
        f"{_ENDING_RULES}"
    )

    # 可选 per-turn hint，仅在编码请求时追加。
    # is_coding_request=False 或 intent_classification=None → 字节级与历史一致。
    if intent_classification is None:
        return base_prompt
    is_coding = bool(getattr(intent_classification, "is_coding_request", False))
    if not is_coding:
        return base_prompt
    matched_verbs = getattr(intent_classification, "matched_verbs", ())
    verbs_text = "、".join(matched_verbs) if matched_verbs else "（未匹配）"
    hint = (
        "\n\n本轮检测到编码请求（命中动词：" + verbs_text + "）。硬约束：\n"
        "  - 必须先调用 analyze_repository_relevance 拿到候选仓库 + 置信度；\n"
        "  - 命中分布不明确（confidence=ambiguous）时优先调 ask_clarification；\n"
        "  - 上述步骤完成前不允许调 create_coding_plan。\n"
    )
    return base_prompt + hint


async def _get_tool_names(space_id: str) -> list[str]:
    """根据项目仓库索引状态返回可用工具列表。

    无空间（space_id 为空）：不注入任何空间工具
    有已索引仓库：注入全部工具（检索工具 + 项目工具 + 编码工具）
    无仓库或未索引：仅注入 get_space_overview（基础信息）
    """
    if not space_id:
        return []
    base_tools = ["get_space_overview"]
    full_tools = base_tools + [
        "browse_file_content",
        "list_space_structure",
        "search_repository_code",
        "list_space_repositories",
        "get_repository_info",
        "create_coding_plan",
        "update_coding_plan",
        # 协商工具，所有有索引仓库的项目都暴露给 LLM
        "ask_clarification",
    ]

    has_indexed = await Repository.objects.filter(
        spaces__id=space_id,
        index_status="indexed",
        is_deleted=False,
    ).aexists()

    return full_tools if has_indexed else base_tools


def _coerce_reference_item(
    tool_name: str,
    result_output: dict[str, Any],
    fallback_repo: str,
) -> dict[str, Any] | None:
    path = str(
        result_output.get("path")
        or result_output.get("file_path")
        or result_output.get("file")
        or ""
    )
    line_start = result_output.get("line_start") or result_output.get("start_line")
    line_end = result_output.get("line_end") or result_output.get("end_line")
    summary = str(
        result_output.get("summary")
        or result_output.get("snippet")
        or result_output.get("content_preview")
        or result_output.get("text")
        or ""
    ).strip()
    if not (path or summary):
        return None

    line = ""
    if line_start and line_end:
        line = f"L{line_start}-L{line_end}"
    elif line_start:
        line = f"L{line_start}"

    return {
        "repository": fallback_repo,
        "path": path,
        "line": line,
        "tool_name": tool_name,
        "summary": summary[:160],
    }


def _extract_reference_candidates(tool_name: str, arguments: dict[str, Any], result_output: Any) -> list[dict[str, Any]]:
    repo = str(
        arguments.get("repository")
        or arguments.get("repository_name")
        or arguments.get("repo")
        or "项目上下文"
    )

    items: list[dict[str, Any]] = []
    if isinstance(result_output, dict):
        candidate = _coerce_reference_item(tool_name, result_output, repo)
        if candidate:
            items.append(candidate)

        for key in ("results", "items", "matches"):
            values = result_output.get(key)
            if not isinstance(values, list):
                continue
            for value in values[:5]:
                if isinstance(value, dict):
                    candidate = _coerce_reference_item(tool_name, value, repo)
                    if candidate:
                        items.append(candidate)
    elif isinstance(result_output, list):
        for value in result_output[:5]:
            if isinstance(value, dict):
                candidate = _coerce_reference_item(tool_name, value, repo)
                if candidate:
                    items.append(candidate)

    return items


async def extract_reference_summaries(session_id: str, limit: int = 5) -> list[dict[str, Any]]:
    """Summarize tool-call outputs for compact card-friendly references."""

    if not session_id:
        return []

    references: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    logs = ToolCallLog.objects.filter(
        session__session_id=session_id,
        result_success=True,
    ).order_by("started_at")
    async for log in logs:
        for item in _extract_reference_candidates(log.tool_name, log.arguments or {}, log.result_output):
            key = (item["repository"], item["path"], item["line"])
            if key in seen:
                continue
            seen.add(key)
            references.append(item)
            if len(references) >= limit:
                return references
    return references


async def _handle_waiting_state(
    *,
    state: dict[str, Any],
    orch_run: OrchestrationRun,
    graph_config: dict[str, Any],
    conversation: Conversation,
    assistant_msg_id: uuid.UUID,
    agent_session: Any,
    session_id: str,
    model: str,
    content: str,
    notification_user_id: str | None,
    conv_id_str: str,
    do_finalize: Any,
) -> None:
    """处理 graph interrupt WAITING 状态：更新 OrchestrationRun + 注册 BarrierManager barrier。

    barrier 满足后由 _on_barrier_complete 回调执行 graph resume + finalize_conversation 落库。
    """
    from langgraph.types import Command

    from orchestration.barrier import get_barrier_manager

    await OrchestrationRun.objects.filter(id=orch_run.id).aupdate(
        status=OrchestrationRun.Status.WAITING,
        phase="waiting",
    )

    blocking_tasks = state.get("blocking_tasks", [])

    async def _on_barrier_complete(results: list[dict[str, Any]]) -> None:
        """barrier 满足后：resume graph + finalize。"""
        try:
            graph_for_resume = await get_compiled_graph()
            final_state: dict[str, Any] = {}
            async for chunk in graph_for_resume.astream(
                Command(resume=results),
                config=graph_config,
                stream_mode=["custom", "values"],
                version="v2",
            ):
                if chunk["type"] == "values":
                    final_state = chunk["data"]

            # 阻塞任务（deep_analysis）完成后的二次运行里 LLM 可能再调
            # ask_clarification（见 graph._execute_with_results）。此时 graph 在
            # wait_clarification_node interrupt，final_state.phase=waiting_clarification。
            # 必须走 clarification 等待收尾（落 WAITING + ConversationIntentTrace，
            # 由 ClarificationAnswerView/SkipView 之后 resume），绝不能像正常完成
            # 那样标 COMPLETED + finalize —— 否则会话被提前写成已完成、卡片不弹、
            # trace 不落，重蹈「无卡可答、永久等待」覆辙。
            if final_state.get("phase") == "waiting_clarification":
                await _handle_waiting_clarification_state(
                    state=final_state,
                    orch_run=orch_run,
                    conversation=conversation,
                    triggering_message_id="",
                    conv_id_str=conv_id_str,
                )
                logger.info(
                    "barrier_resume_waiting_clarification",
                    conversation_id=conv_id_str,
                    session_id=session_id,
                )
                return

            await OrchestrationRun.objects.filter(id=orch_run.id).aupdate(
                status=OrchestrationRun.Status.COMPLETED,
                phase=final_state.get("phase", "completed"),
            )

            # contract：barrier resume 路径也透传 parts（_execute_with_results 已注入 state）
            _parts_for_barrier = final_state.get("parts")
            await do_finalize(
                conversation=conversation,
                assistant_msg_id=assistant_msg_id,
                final_content=final_state.get("final_answer", ""),
                accumulated_thinking=final_state.get("accumulated_thinking", []),
                tool_calls=final_state.get("tool_calls", []),
                result_metadata=final_state.get("result_metadata", {}),
                agent_session=agent_session,
                session_id=session_id,
                model=model,
                user_message=content,
                notification_user_id=notification_user_id,
                publish_title_event=True,
                parts=_parts_for_barrier if isinstance(_parts_for_barrier, list) else [],
            )
            logger.info(
                "barrier_resume_finalized",
                conversation_id=conv_id_str,
                session_id=session_id,
            )
        except Exception:
            logger.exception(
                "barrier_resume_error",
                conversation_id=conv_id_str,
                session_id=session_id,
            )
            await OrchestrationRun.objects.filter(id=orch_run.id).aupdate(
                status=OrchestrationRun.Status.ERROR,
                phase="error",
            )
            await Conversation.objects.filter(id=conversation.id).aupdate(
                status=Conversation.Status.ERROR,
            )
            # 写入兜底错误消息，避免前端只显示 placeholder 而没有任何反馈
            try:
                from chat.models import Message

                error_reason = ""
                for r in results:
                    if not r.get("success"):
                        error_reason = r.get("error", "")
                        break
                if not await Message.objects.filter(id=assistant_msg_id).aexists():
                    await Message.objects.acreate(
                        id=assistant_msg_id,
                        conversation=conversation,
                        role=Message.Role.ASSISTANT,
                        content=error_reason or "深度分析任务执行失败，请稍后重试。",
                        metadata={
                            "session_id": session_id,
                            "model": model,
                            "status": "error",
                        },
                    )
            except Exception:
                logger.exception(
                    "barrier_resume_error_message_failed",
                    conversation_id=conv_id_str,
                )

    async def _on_barrier_progress(completed: int, total: int) -> None:
        logger.info(
            "barrier_task_progress",
            conversation_id=conv_id_str,
            completed_count=completed,
            total_count=total,
        )

    barrier = get_barrier_manager()
    await barrier.register(
        run_id=str(orch_run.run_id),
        thread_id=conv_id_str,
        tasks=blocking_tasks,
        graph_config=graph_config,
        on_complete=_on_barrier_complete,
        on_progress=_on_barrier_progress,
    )

    logger.info(
        "graph_waiting_barrier_registered",
        conversation_id=conv_id_str,
        blocking_task_count=len(blocking_tasks),
    )


async def _handle_waiting_clarification_state(
    *,
    state: dict[str, Any],
    orch_run: OrchestrationRun,
    conversation: Conversation,
    triggering_message_id: str,
    conv_id_str: str,
) -> None:
    """处理 graph interrupt WAITING_CLARIFICATION 状态（review review round Fix #1 + #2）。

    与 ``_handle_waiting_state``（blocking_tasks 路径）的对比：

    - **无 BarrierManager**：clarification 不依赖 subagent 任务完成，依赖用户
      通过 ``ClarificationAnswerView`` 提交答复后由 endpoint 自己 resume graph。
    - **不调 do_finalize**：会话维持 RUNNING 态等待用户答复；调 finalize 会把
      conversation 写成 completed / error 终态，让 resume 时再覆盖会与
      ``finalize.py`` 的 status_str="unknown" 分支冲突落 ERROR（work-item item-error.md 实测）。
    - **落 ConversationIntentTrace**：plan work item 设计的审计 + lookup 表。
      ``ClarificationAnswerView`` 通过 ``aget(clarification_id=...)`` 反查，
      若不落库则 endpoint 必 404、整条 clarification roundtrip 跑不通。

    幂等：``ConversationIntentTrace.clarification_id`` 是 unique；这里走
    ``aget_or_create`` 防 LangGraph interrupt 之后任何 resume 重放再次进入此分支
    时撞 unique 约束（设计上 wait_clarification_node 之后只会有 resume + new
    user message，不会再走本函数；防御性 get_or_create 是兜底）。
    """
    from chat.models import ConversationIntentTrace

    pending = state.get("pending_clarification") or {}
    clarification_id = pending.get("clarification_id")

    await OrchestrationRun.objects.filter(
        id=orch_run.id,
    ).exclude(status=OrchestrationRun.Status.INTERRUPTED).aupdate(
        status=OrchestrationRun.Status.WAITING,
        phase=OrchestrationRun.Phase.WAITING_CLARIFICATION,
    )

    if not clarification_id:
        logger.warning(
            "waiting_clarification_without_clarification_id",
            conversation_id=conv_id_str,
            run_id=str(orch_run.run_id),
            pending_keys=list(pending.keys()),
        )
        return

    _trace, created = await ConversationIntentTrace.objects.aget_or_create(
        clarification_id=clarification_id,
        defaults={
            "conversation": conversation,
            "triggering_message_id": triggering_message_id,
            "question": pending.get("question", ""),
            "options": pending.get("options", []),
        },
    )

    logger.info(
        "waiting_clarification_handled",
        conversation_id=conv_id_str,
        clarification_id=clarification_id,
        intent_trace_created=created,
        options_count=len(pending.get("options", [])),
    )


def _build_message_complete_event(
    *,
    final_content: str,
    result_metadata: dict[str, Any],
    model: str,
    session_id: str,
) -> AgentEvent:
    """构建兜底 MESSAGE_COMPLETE 事件，确保前端能收到最终正文。"""
    payload: dict[str, Any] = {
        "final_answer": final_content,
        "result": final_content,
        "status": result_metadata.get("status", "completed"),
        "model": model,
        "session_id": session_id,
        "usage": {
            "input_tokens": result_metadata.get("input_tokens", 0),
            "output_tokens": result_metadata.get("output_tokens", 0),
        },
    }
    if "cost_usd" in result_metadata:
        payload["cost_usd"] = result_metadata.get("cost_usd", 0)
    return AgentEvent(type=MESSAGE_COMPLETE, data=payload)


# ============================================================================
# 项目作战室 P2：共享会话权限辅助（项目成员/管理员判定 + 单会话执行时长）
# ============================================================================


async def _user_project_ids(user: Any) -> set[str]:
    """当前已认证用户作为成员的全部项目 id 集合（用于列「项目共享会话」）。"""
    if not getattr(user, "is_authenticated", False):
        return set()
    from initiatives.models import ProjectMember

    return {
        str(pid)
        async for pid in ProjectMember.objects.filter(user=user).values_list(
            "project_id", flat=True
        )
    }


async def _is_project_member(user: Any, project_id: Any) -> bool:
    """user 是否为 project_id 的项目成员。"""
    if not project_id or not getattr(user, "is_authenticated", False):
        return False
    from initiatives.models import ProjectMember

    return await ProjectMember.objects.filter(
        project_id=project_id, user=user
    ).aexists()


async def _is_project_admin(user: Any, project_id: Any) -> bool:
    """user 是否为 project_id 的项目管理员（主R / OWNER）。"""
    if not project_id or not getattr(user, "is_authenticated", False):
        return False
    from initiatives.models import ProjectMember, ProjectRole

    return await ProjectMember.objects.filter(
        project_id=project_id, user=user, role=ProjectRole.OWNER
    ).aexists()


async def compute_conversation_duration_ms(conversation_id: Any) -> int:
    """单条会话的执行时长（毫秒）= 该会话所有 OrchestrationRun 运行时长之和。

    口径：每个 run 取 ``updated_at - created_at`` 的毫秒差求和；无 run 返回 0。
    best-effort，异常吞掉返回 0（观测不反噬业务）。
    """
    try:
        total_ms = 0
        async for run in OrchestrationRun.objects.filter(
            conversation_id=conversation_id
        ).values("created_at", "updated_at"):
            start = run.get("created_at")
            end = run.get("updated_at")
            if start and end and end >= start:
                total_ms += int((end - start).total_seconds() * 1000)
        return total_ms
    except Exception:
        return 0


class ConversationService:
    """对话系统业务逻辑服务。"""

    @staticmethod
    async def aget_for_read(conversation_id: str, user: Any = None) -> Conversation:
        """读取 gate（项目作战室 P2）：owner 或「shared + bound_project 成员」可读。

        与 owner-only 的 ``aget_for_user`` 并列：本方法用于**只读路径**（详情/消息/
        runtime），让项目共享会话对项目成员可见；写/管理路径仍走 owner gate。
        越权/不存在统一抛 ``Conversation.DoesNotExist``（view 映射 404）。
        """
        conv = await Conversation.objects.aget(
            id=conversation_id, is_deleted=False
        )
        if not getattr(user, "is_authenticated", False):
            return conv  # 开放模式维持现状
        if conv.created_by_id == user.id:
            return conv
        if (
            conv.visibility == Conversation.Visibility.SHARED
            and conv.bound_project_id is not None
            and await _is_project_member(user, conv.bound_project_id)
        ):
            return conv
        raise Conversation.DoesNotExist(
            f"对话不存在或无权访问: {conversation_id}"
        )

    @staticmethod
    async def aset_visibility(
        conversation_id: str, user: Any, visibility: str
    ) -> Conversation:
        """互转会话可见性（个人↔共享）。仅创建者可操作（二次确认在前端）。

        共享要求 bound_project 非空；否则抛 ValueError（view 兜成 400）。
        越权（非创建者）抛 ``Conversation.DoesNotExist``（404）。
        """
        conv = await Conversation.objects.aget(
            id=conversation_id, is_deleted=False
        )
        if getattr(user, "is_authenticated", False) and conv.created_by_id != user.id:
            raise Conversation.DoesNotExist(
                f"对话不存在或无权操作: {conversation_id}"
            )
        if (
            visibility == Conversation.Visibility.SHARED
            and conv.bound_project_id is None
        ):
            raise ValueError("共享会话必须先绑定项目")
        conv.visibility = visibility
        await conv.asave(update_fields=["visibility", "updated_at"])
        logger.info(
            "conversation_visibility_changed",
            conversation_id=str(conv.id),
            visibility=visibility,
            category="caller",
            component="chat.conversation",
        )
        return conv

    @staticmethod
    async def aget_for_user(conversation_id: str, user: Any = None) -> Conversation:
        """owner-scoped 取单个会话——按 id 取会话的唯一收口入口（ISO-04）。

        隔离规则（仅对「已认证用户」生效，管理员不 bypass）：
            - user 已认证 → 仅返回 created_by == user 的会话；越权/不存在统一抛
              ``Conversation.DoesNotExist``（view 映射统一 404，杜绝存在性泄漏）。
            - user 未认证（开放模式 / 匿名）→ 不加 owner 过滤，维持开放行为。

        **不加任何管理员特权分支**（ISO-03：owner gate 无 superuser bypass）。
        用 queryset filter（``created_by=user``）而非惰性访问 ``.created_by``，
        避免 async 上下文的 SynchronousOnlyOperation（Pitfall 4）。

        Raises:
            Conversation.DoesNotExist: 会话不存在、已删除，或越权访问他人会话。
        """
        qs = Conversation.objects.filter(id=conversation_id, is_deleted=False)
        if getattr(user, "is_authenticated", False):
            qs = qs.filter(created_by=user)
        return await qs.aget()

    @staticmethod
    async def create_conversation(
        space_id: str | None,
        title: str = "新对话",
        model: str = "",
        user: Any = None,
        bound_project_id: str | None = None,
        visibility: str | None = None,
    ) -> Conversation:
        """创建新对话。

        Args:
            space_id: 空间 UUID；None 表示创建不绑定空间的通用对话
            title: 对话标题
            model: LLM 模型 ID（为空时运行时使用系统默认）
            user: 创建者；已认证则写入 created_by，未认证（开放模式）写 null（ISO-01）
            bound_project_id: 绑定项目（项目作战室）；非空则 chat 自动加载项目上下文
            visibility: personal/shared；shared 守护——必须有 bound_project，否则降级 personal

        Returns:
            新创建的 Conversation 实例
        """
        # 隔离仅对已认证用户生效：匿名/开放模式不写 owner。
        created_by = user if getattr(user, "is_authenticated", False) else None
        vis = visibility or Conversation.Visibility.PERSONAL
        # 守护：shared 必须绑定项目，否则回落 personal（防越权可见性泄漏）。
        if vis == Conversation.Visibility.SHARED and not bound_project_id:
            vis = Conversation.Visibility.PERSONAL
        conversation = await Conversation.objects.acreate(
            space_id=space_id,
            title=title,
            model=model,
            created_by=created_by,
            bound_project_id=bound_project_id,
            visibility=vis,
        )
        logger.info(
            "conversation_created",
            conversation_id=str(conversation.id),
            space_id=space_id,
            bound_project_id=str(bound_project_id) if bound_project_id else None,
            visibility=vis,
            title=title,
            category="caller",
            component="chat.conversation",
        )
        # 实时同步：新建会话广播给本人 / 项目成员（共享会话即时出现在他人列表）。
        from chat.realtime import abroadcast_conversation

        await abroadcast_conversation(conversation.id, event="created")
        return conversation

    @staticmethod
    async def switch_space(
        conversation: Conversation,
        space_id: str | None,
    ) -> Message | None:
        """会话内切换绑定空间。

        切换只改 ``conversation.space``，并落库一条 ``role=system`` 的
        ``space_switch`` 标记消息（前端渲染为分隔线、LLM 历史重建时注入切换标注）。
        历史消息保留不动 —— 下一个 turn ``build_sdk_config`` 从 ``project_id``
        读到新空间后，system prompt / 工具集自动基于新空间重建。

        Args:
            conversation: 目标会话（caller 已完成 owner gate / running 校验）
            space_id: 目标空间 UUID；None 表示切回不绑定空间的「通用对话」

        Returns:
            落库的 space_switch 系统消息；空间未变化时不落库，返回 None

        Raises:
            ValueError: 目标空间不存在
        """
        from projects.models import Space

        old_space_id = str(conversation.space_id) if conversation.space_id else None
        new_space_id = str(space_id) if space_id else None
        if old_space_id == new_space_id:
            return None

        new_space_name = ""
        if new_space_id is not None:
            try:
                project = await Space.objects.aget(id=new_space_id)
            except Space.DoesNotExist as exc:
                raise ValueError(f"空间不存在: {new_space_id}") from exc
            new_space_name = project.name

        old_space_name = ""
        if old_space_id is not None:
            old_space_name = (
                await Space.objects.filter(id=old_space_id)
                .values_list("name", flat=True)
                .afirst()
                or ""
            )

        conversation.space_id = new_space_id
        await conversation.asave(update_fields=["space", "updated_at"])

        content = (
            f"已切换空间到「{new_space_name}」"
            if new_space_id is not None
            else "已切换为通用对话（不绑定空间）"
        )
        message = await Message.objects.acreate(
            conversation=conversation,
            role=Message.Role.SYSTEM,
            content=content,
            metadata={
                "type": "space_switch",
                "from_space_id": old_space_id,
                "from_space_name": old_space_name,
                "to_space_id": new_space_id,
                "to_space_name": new_space_name,
            },
        )
        logger.info(
            "conversation_space_switched",
            conversation_id=str(conversation.id),
            from_space_id=old_space_id,
            to_space_id=new_space_id,
        )
        return message

    @staticmethod
    async def fork_conversation_before_message(
        conversation_id: str,
        message_id: str,
        edited_content: str,
    ) -> dict[str, Any]:
        """创建一个只包含目标 user message 之前历史的新 conversation 分支。

        edited_content 只用于校验与审计；真正的编辑后 user message 由现有
        send_message_stream 路径写入，避免出现第二套 user message 持久化逻辑。
        """
        content = edited_content.strip()
        if not content:
            raise ValueError("编辑后的内容不能为空")

        source = await Conversation.objects.aget(
            id=conversation_id,
            is_deleted=False,
        )
        try:
            target = await Message.objects.aget(
                id=message_id,
                conversation=source,
            )
        except (Message.DoesNotExist, ValueError, TypeError) as exc:
            raise ValueError("目标消息不存在或不属于本对话") from exc

        if target.role != Message.Role.USER:
            raise ValueError("只能编辑用户消息")

        # 编辑历史提问会 fork 出新会话；直接沿用源会话标题，不再追加「（编辑）」
        # 后缀（用户反馈该后缀无意义且污染侧栏）。标题超长截断到 200。
        fork_title = (source.title or "")[:200]

        forked = await Conversation.objects.acreate(
            space_id=source.space_id,
            title=fork_title,
            model=source.model,
            provider_credential_id_id=source.provider_credential_id_id,
            # 继承源对话的 owner，避免 fork 出 null-owner 孤儿对话：
            # 否则鉴权用户 fork 自己的对话后会被 owner gate 立即 404（含编辑消息的后续 stream/）
            created_by_id=source.created_by_id,
        )

        copied_count = 0
        async for prior in Message.objects.filter(
            conversation=source,
            created_at__lt=target.created_at,
        ).order_by("created_at"):
            await Message.objects.acreate(
                conversation=forked,
                role=prior.role,
                content=prior.content,
                tool_calls=deepcopy(prior.tool_calls),
                tool_call_id=prior.tool_call_id,
                metadata=deepcopy(prior.metadata),
                parts=deepcopy(prior.parts),
            )
            copied_count += 1

        messages = [
            message
            async for message in Message.objects.filter(conversation=forked).order_by("created_at")
        ]
        logger.info(
            "conversation_forked_for_edit",
            source_conversation_id=str(source.id),
            target_message_id=str(target.id),
            forked_conversation_id=str(forked.id),
            copied_count=copied_count,
        )
        return {"conversation": forked, "messages": messages}

    @staticmethod
    async def aclone_for_contribution(
        conversation_id: str,
        actor: Any,
    ) -> dict[str, Any]:
        """项目作战室 P2：把一个（共享/可读）会话整份克隆为「我的项目个人会话」。

        共享会话对项目成员只读；成员要发言即调用本方法 clone 一份归属自己的副本
        （``created_by=actor`` / ``visibility=personal``，继承 ``bound_project``），
        在副本里自由对话。语义参照 ``admin_fork_to_own``，但以「项目成员读权限」
        而非 superuser 授权：先经 ``aget_for_read`` 校验 actor 可读源会话。

        Returns:
            {"conversation_id": <新会话 id 字符串>}

        Raises:
            Conversation.DoesNotExist: 源会话不存在或 actor 无读权限（view 兜 404）。
        """
        source = await ConversationService.aget_for_read(conversation_id, actor)

        fork_title = (source.title or "新对话")
        suffix = "（我的副本）"
        fork_title = f"{fork_title[:200 - len(suffix)]}{suffix}"

        @sync_to_async
        def _copy_atomic() -> tuple[Conversation, int]:
            with transaction.atomic():
                forked = Conversation.objects.create(
                    space_id=source.space_id,
                    title=fork_title,
                    model=source.model,
                    provider_credential_id_id=source.provider_credential_id_id,
                    created_by=actor if getattr(actor, "is_authenticated", False) else None,
                    bound_project_id=source.bound_project_id,
                    visibility=Conversation.Visibility.PERSONAL,
                    status=Conversation.Status.DRAFT,
                )
                source_messages = list(
                    Message.objects.filter(conversation_id=source.id).order_by(
                        "created_at"
                    )
                )
                Message.objects.bulk_create(
                    [
                        Message(
                            conversation=forked,
                            role=msg.role,
                            content=msg.content,
                            tool_calls=deepcopy(msg.tool_calls),
                            tool_call_id=msg.tool_call_id,
                            metadata=deepcopy(msg.metadata),
                            parts=deepcopy(msg.parts),
                        )
                        for msg in source_messages
                    ]
                )
                return forked, len(source_messages)

        forked, copied_count = await _copy_atomic()
        logger.info(
            "conversation_cloned_for_contribution",
            source_conversation_id=str(source.id),
            forked_conversation_id=str(forked.id),
            copied_count=copied_count,
            category="caller",
            component="chat.conversation",
        )
        return {"conversation_id": str(forked.id)}

    # ========================================================================
    # 管理员只读会话后台（ADMVW-01/02/03）—— 物理分离的 admin_* 业务方法。
    #
    # 这些方法**无 owner 过滤**（调用方在 view 层由 IsSuperUser 授权跨用户读取），
    # 与 owner-scoped 的 aget_for_user / list_conversations / delete_conversation
    # **完全独立**：不在普通路径加任何 superuser bypass（ISO-03 不回退）。
    # ========================================================================

    @staticmethod
    async def admin_list_conversations(
        owner_id: str | None = None,
        q: str = "",
    ) -> list[Conversation]:
        """ADMVW-01：跨用户列出全部未删除会话（管理员只读后台）。

        **无 created_by 过滤**（跨用户全集）；可选叠加 owner_id / 标题关键字过滤。
        select_related("created_by", "space") 预取关联对象，避免 async 序列化时
        惰性访问 FK 触发 SynchronousOnlyOperation（Pitfall 1）；
        annotate(message_count=...) 供列表项展示消息数（无需 N+1 count）。

        Args:
            owner_id: 可选，按 created_by_id 过滤到单一 owner。
            q: 可选，标题 icontains 关键字（ORM 参数化，无注入）。

        Returns:
            按 updated_at 降序排列的会话列表（每条带 message_count 注解）。
        """
        from django.db.models import Count, Exists, OuterRef

        from chat.models import CodingPlan, CodingSession
        from delivery.models import ConvergenceSession, SddSpec

        qs = (
            Conversation.objects.filter(is_deleted=False)
            .select_related("created_by", "space")
            .annotate(message_count=Count("messages"))
            # 列表徽标聚合（SDD / 技术方案 / 编码）：与 owner-scoped list_conversations
            # 同源的 Exists 子查询，不引入 N+1、async 安全（annotate 出的布尔是实例列，
            # 序列化器直接读属性不触发 sync ORM）。
            .annotate(
                has_coding_plan=Exists(
                    CodingPlan.objects.filter(conversation_id=OuterRef("pk"))
                ),
                has_coding_session=Exists(
                    CodingSession.objects.filter(conversation_id=OuterRef("pk"))
                ),
                has_sdd_spec=Exists(
                    ConvergenceSession.objects.filter(
                        conversation_id=OuterRef("pk"),
                        current_artifact_version__isnull=False,
                        current_artifact_version__in=SddSpec.objects.filter(
                            artifact_version__isnull=False
                        ).values("artifact_version_id"),
                    )
                ),
            )
        )
        if owner_id:
            qs = qs.filter(created_by_id=owner_id)
        if q:
            qs = qs.filter(title__icontains=q)
        return [c async for c in qs.order_by("-updated_at")]

    @staticmethod
    async def admin_get_with_messages(conversation_id: str) -> dict[str, Any]:
        """ADMVW-01：取单个会话（无 owner 过滤）+ 其全部消息（管理员只读详情）。

        与 owner-scoped 的 get_conversation_with_messages 区别：本方法面向管理员，
        **不做 owner 过滤**（IsSuperUser 已授权跨用户读取）。会话 select_related
        预取 created_by/project（Pitfall 1）；消息按 created_at 升序。

        Raises:
            Conversation.DoesNotExist: 会话不存在或已删除（view 兜成 404）。
        """
        conversation = await Conversation.objects.select_related(
            "created_by",
            "space",
        ).aget(
            id=conversation_id,
            is_deleted=False,
        )
        messages = [
            msg
            async for msg in Message.objects.filter(
                conversation=conversation,
            ).order_by("created_at")
        ]
        return {"conversation": conversation, "messages": messages}

    @staticmethod
    async def admin_fork_to_own(
        conversation_id: str,
        admin_user: Any,
    ) -> dict[str, Any]:
        """ADMVW-03：把任意会话整份复制为一份归属当前管理员的新会话。

        以 fork_conversation_before_message 为蓝本，**三处差异**：
            1. created_by = 发起的管理员（显式归属，非继承源 owner，规避 Pitfall 5
               owner 继承错误——否则 admin fork 后续聊立刻被 owner gate 404）。
            2. 复制**全部**消息（去掉 created_at__lt 截断，整份拷贝）。
            3. status = DRAFT（新副本语义，规避 Pitfall 4 pin 冻结——源会话若为
               completed/stopped/error frozen 态，副本仍可被 admin 自由配置/续聊）。

        provider_credential_id 携带源值（与普通 fork 一致；status=DRAFT 不冻结，
        admin 可改）。无 owner 过滤（调用方 IsSuperUser 已授权）。

        Args:
            conversation_id: 源会话 UUID。
            admin_user: 发起 fork 的管理员（新副本的 created_by）。

        Returns:
            {"conversation_id": <新会话 id 字符串>}。

        Raises:
            Conversation.DoesNotExist: 源会话不存在或已删除（view 兜成 404）。
        """
        source = await Conversation.objects.aget(
            id=conversation_id,
            is_deleted=False,
        )

        fork_title = f"{source.title}（管理员副本）"
        if len(fork_title) > 200:
            suffix = "（管理员副本）"
            fork_title = f"{source.title[:200 - len(suffix)]}{suffix}"

        # WR-02：会话 + 全部消息的复制必须原子化，否则复制中途异常会留下
        # messages 不完整的 DRAFT 副本（孤儿数据）。收敛到单个 sync_to_async
        # 包裹的 transaction.atomic() 块，并用 bulk_create 一次性写入消息，
        # 保证「要么整份、要么不创建」。
        @sync_to_async
        def _copy_atomic() -> tuple[Conversation, int]:
            with transaction.atomic():
                forked = Conversation.objects.create(
                    space_id=source.space_id,
                    title=fork_title,
                    model=source.model,
                    provider_credential_id_id=source.provider_credential_id_id,
                    created_by=admin_user,
                    status=Conversation.Status.DRAFT,
                )
                source_messages = list(
                    Message.objects.filter(conversation_id=source.id).order_by(
                        "created_at"
                    )
                )
                Message.objects.bulk_create(
                    [
                        Message(
                            conversation=forked,
                            role=msg.role,
                            content=msg.content,
                            tool_calls=deepcopy(msg.tool_calls),
                            tool_call_id=msg.tool_call_id,
                            metadata=deepcopy(msg.metadata),
                            parts=deepcopy(msg.parts),
                        )
                        for msg in source_messages
                    ]
                )
                return forked, len(source_messages)

        forked, copied_count = await _copy_atomic()

        logger.info(
            "admin_conversation_forked",
            admin_id=str(getattr(admin_user, "id", "")),
            source_conversation_id=str(source.id),
            forked_conversation_id=str(forked.id),
            copied_count=copied_count,
        )
        return {"conversation_id": str(forked.id)}

    @staticmethod
    async def _fetch_doc_for_context(
        project: Any,
        doc_id: str,
    ) -> tuple[str | None, AgentEvent]:
        """读取飞书文档并返回 (markdown_content, sse_event)。

        成功时返回 (markdown, doc_summary_event)。
        失败时返回 (None, doc_error_event)。
        """
        from agents.tools.feishu_doc_tools import create_feishu_doc_client_for_project

        try:
            client = await create_feishu_doc_client_for_project(project)
        except ValueError as e:
            return None, AgentEvent(
                type=DOC_ERROR,
                data={"error_type": "not_configured", "message": str(e)},
            )

        try:
            markdown, _blocks = await client.get_document_content(doc_id)
            # 提取标题：取第一个非空行，去掉 # 前缀
            lines = [ln.strip() for ln in markdown.split("\n") if ln.strip()]
            title = lines[0].lstrip("# ").strip() if lines else "飞书文档"
            word_count = len(markdown)
            preview = "\n".join(lines[:3])

            markdown, was_truncated = truncate_doc_content(markdown)

            return markdown, AgentEvent(
                type=DOC_SUMMARY,
                data={
                    "doc_title": title,
                    "word_count": word_count,
                    "preview": preview,
                    "truncated": was_truncated,
                    "truncated_length": len(markdown) if was_truncated else word_count,
                },
            )
        except PermissionDeniedError as e:
            return None, AgentEvent(
                type=DOC_ERROR,
                data={"error_type": "permission_denied", "message": str(e)},
            )
        except DocumentNotFoundError as e:
            return None, AgentEvent(
                type=DOC_ERROR,
                data={"error_type": "not_found", "message": str(e)},
            )
        except FeishuDocAPIError as e:
            logger.warning("feishu_doc_read_failed", doc_id=doc_id, error=str(e))
            return None, AgentEvent(
                type=DOC_ERROR,
                data={"error_type": "unknown", "message": str(e)},
            )

    @staticmethod
    async def send_message_stream(
        conversation_id: str,
        content: str,
        role: str = "developer",
        notification_user_id: str | None = None,
        force_deep_analysis: bool = False,
        feishu_doc_id: str = "",
        project_context_line: str | None = None,
        search_branch: str | None = None,
        input_parts: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """流式发送消息 — 通过 LangGraph graph 驱动。

        签名保持不变，内部改为：
        1. 保存 user 消息
        2. 构建 SDK 配置
        3. 创建 OrchestrationRun
        4. 在独立 Task 中运行 graph.astream()，通过 Queue 桥接事件
        5. yield 事件（带 keepalive 心跳）
        6. graph 完成后调用 finalize_conversation() 落库
        """
        # lazy import 避免循环依赖（config.py 导入本模块的 _build_system_prompt）
        from chat.config import build_sdk_config
        from chat.finalize import finalize_conversation as do_finalize
        from chat.multimodal import ensure_image_input_supported, extract_text_from_parts
        from chat.parts import PARTS_SCHEMA_VERSION

        async def _hydrate_finalize_from_snapshot(
            orch: OrchestrationRun,
            state: dict[str, Any],
        ) -> tuple[str, list[str], list[dict[str, Any]], dict[str, Any]]:
            """中断/异常路径：graph 没走到 finalizing_node 时，从 OrchestrationRun.metadata
            ['streaming_snapshot'] 拼回 final_content / thinking / tool_calls，避免落库空消息。

            背景：用户点「停止生成」→ runner.interrupt() → _run_chat_stream 抛 CancelledError
            → executing_node re-raise → graph 异常退出，永远到不了 finalizing_node，state
            的 final_answer 是空字符串。_StreamingSnapshot 已经在 CancelledError 分支里把
            最后累积态 flush 到 metadata；这里读出来还原，保证「中断了一半的回答」落库到
            messages 表，刷新后从 hydrateMessages 路径也能看到这段被中断的内容。
            """
            final_content = state.get("final_answer", "") or ""
            accumulated_thinking = list(state.get("accumulated_thinking") or [])
            tool_calls_state = list(state.get("tool_calls") or [])

            if final_content and tool_calls_state:
                return final_content, accumulated_thinking, tool_calls_state, {}

            refreshed = await OrchestrationRun.objects.filter(id=orch.id).afirst()
            if refreshed is None or not isinstance(refreshed.metadata, dict):
                return final_content, accumulated_thinking, tool_calls_state, {}

            snap = refreshed.metadata.get("streaming_snapshot")
            if not isinstance(snap, dict):
                return final_content, accumulated_thinking, tool_calls_state, {}

            if not final_content:
                final_content = snap.get("pending_text", "") or ""
            if not accumulated_thinking and snap.get("thinking"):
                accumulated_thinking = [snap["thinking"]]
            snap_tools = snap.get("tool_calls")
            if not tool_calls_state and isinstance(snap_tools, list):
                tool_calls_state = [tc for tc in snap_tools if isinstance(tc, dict)]
            return final_content, accumulated_thinking, tool_calls_state, snap

        def _extract_state_parts(state: dict[str, Any]) -> list[dict[str, Any]]:
            """parts contract：从 graph state 读 collector parts。

            chat_runner 路径会在 ``_execute_first_run`` / ``_execute_with_results``
            把 ``runner.result.metadata['parts']`` 注入 state['parts']。其它路径
            （deep_analysis BarrierManager 回灌）暂不产 parts，落库走 legacy 兜底。
            """
            raw = state.get("parts")
            if isinstance(raw, list):
                return [p for p in raw if isinstance(p, dict)]
            return []

        conversation = await Conversation.objects.select_related(
            "space",
            "provider_credential_id",
        ).aget(
            id=conversation_id,
            is_deleted=False,
        )

        input_parts_data = list(input_parts or [])

        sdk_config, agent_session = await build_sdk_config(
            conversation,
            role=role,
            notification_user_id=notification_user_id,
            force_deep_analysis=force_deep_analysis,
            project_context_line=project_context_line,
        )
        session_id = sdk_config.session_id
        model = sdk_config.model
        conv_id_str = str(conversation.id)

        if any(part.get("type") == "image" for part in input_parts_data):
            # 注意：FK 字段名为 provider_credential_id，直接属性访问会触发同步
            # DB 查询（async 下 SynchronousOnlyOperation）。读 `_id` 列拿 UUID
            # 再异步查凭证，让「凭证绑定模型的模态配置」真正生效。
            from services.provider_config import _fetch_credential_by_id

            credential = None
            pinned_id = getattr(conversation, "provider_credential_id_id", None)
            if pinned_id:
                credential = await _fetch_credential_by_id(pinned_id)
            ensure_image_input_supported(
                provider_type=sdk_config.provider_type,
                model=model,
                available_models=getattr(credential, "available_models", None),
            )

        # review review round Fix #1/#2：保留 user message id 作为 ConversationIntentTrace.triggering_message_id
        # （waiting_clarification 路径需要 — 见 _handle_waiting_clarification_state）。
        user_msg_metadata: dict[str, Any] = {}
        user_msg_content = content
        if input_parts_data:
            user_msg_content = extract_text_from_parts(input_parts_data)
            user_msg_metadata["parts_schema_version"] = PARTS_SCHEMA_VERSION
            image_count = sum(1 for part in input_parts_data if part.get("type") == "image")
            if image_count:
                user_msg_metadata["image_count"] = image_count

        user_msg = await Message.objects.acreate(
            conversation=conversation,
            role=Message.Role.USER,
            content=user_msg_content,
            parts=input_parts_data,
            metadata=user_msg_metadata,
        )
        user_msg_id_str = str(user_msg.id)

        # 对话进入进行中状态
        conversation.status = Conversation.Status.RUNNING
        await conversation.asave(update_fields=["status"])

        # 实时同步：广播用户提问 + 进行中状态（其他参与者实时看到新消息与「运行中」）。
        from django.utils import timezone

        from chat.realtime import abroadcast_conversation, abroadcast_message

        await abroadcast_message(
            conversation.id,
            {
                "id": user_msg_id_str,
                "role": "user",
                "content": user_msg_content,
                "parts": input_parts_data,
                "metadata": user_msg_metadata,
                "created_at": timezone.now().isoformat(),
            },
        )
        await abroadcast_conversation(conversation.id)

        # 飞书文档预处理（per contract: 读取成功即自动注入上下文）
        doc_context_prefix = ""
        # 捕获 docSummary 给 finalize 落库（刷新回显飞书文档摘要卡）。
        # 形态与前端 metadata.docSummary 对齐（ChatMessageBubble.docSummary）。
        captured_doc_summary: dict[str, Any] | None = None
        if feishu_doc_id and conversation.space_id is None:
            # 无空间对话没有飞书凭证来源，直接推 doc_error 降级（不中断对话）
            yield AgentEvent(
                type=DOC_ERROR,
                data={
                    "error_type": "no_space",
                    "message": "当前对话未绑定空间，无法读取飞书文档；请选择空间后重试",
                },
            )
        elif feishu_doc_id:
            doc_markdown, doc_event = await ConversationService._fetch_doc_for_context(
                conversation.space, feishu_doc_id,
            )
            yield doc_event  # 推送 doc_summary 或 doc_error

            if doc_event.type == DOC_SUMMARY:
                _d = doc_event.data
                captured_doc_summary = {
                    "type": "summary",
                    "title": _d.get("doc_title", ""),
                    "wordCount": _d.get("word_count"),
                    "preview": _d.get("preview", ""),
                    "truncated": _d.get("truncated", False),
                    "truncatedLength": _d.get("truncated_length"),
                }
            elif doc_event.type == DOC_ERROR:
                captured_doc_summary = {
                    "type": "error",
                    "errorType": doc_event.data.get("error_type"),
                    "errorMessage": doc_event.data.get("message"),
                }

            if doc_markdown:
                doc_title = doc_event.data.get("doc_title", "飞书文档")
                doc_context_prefix = (
                    f"\n\n---\n## 参考文档：{doc_title}\n\n"
                    f"{doc_markdown}\n---\n\n"
                )

        assistant_msg_id = uuid.uuid4()

        orch_run = await OrchestrationRun.objects.acreate(
            conversation=conversation,
            thread_id=conv_id_str,
            status=OrchestrationRun.Status.RUNNING,
            phase=OrchestrationRun.Phase.PLANNING,
        )

        branch_for_tools = (search_branch or "").strip() or None

        graph_config: dict[str, Any] = {
            "configurable": {
                "thread_id": conv_id_str,
                "conversation_id": conv_id_str,
                "api_key": sdk_config.api_key,
                "api_base_url": sdk_config.api_base_url,
                "model": model,
                "session_id": session_id,
                "system_prompt": sdk_config.system_prompt,
                "space_id": sdk_config.space_id,
                # 项目级对话：必须把 bound_project_id 透到 graph_config —— executing_node
                # 用 cfg 重建 ChatRunnerConfig，少传会让 _get_tool_names 拿不到项目只读工具
                # （get_project_overview 等），system_prompt 已宣传却未绑定 → 模型调用报「未知工具」。
                "bound_project_id": sdk_config.bound_project_id,
                "role": role,
                "agent_session_id": str(agent_session.id),
                "notification_user_id": notification_user_id or "",
                "max_budget_usd": sdk_config.max_budget_usd,
                "default_search_branch": branch_for_tools,
                # 必须把开关透到 graph_config —— executing_node 会用 cfg 重新构造
                # ChatRunnerConfig，少传这个字段会让 _get_tool_names 拿不到
                # deep_analysis 工具，前端开了「深度分析」却始终走不到远程 runner。
                "force_deep_analysis": sdk_config.force_deep_analysis,
                # 同理：绑定模型的能力清单也必须透传，否则 runner 重建 config 时
                # available_models 丢失 → 图片模态门控回退全局推断 → 误判已配置
                # vision 的自定义模型（如 mimo-v2.5）不支持图片。
                "available_models": sdk_config.available_models,
            }
        }

        graph = await get_compiled_graph()
        event_queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue(maxsize=200)
        graph_state_holder: dict[str, Any] = {}

        async def _run_graph() -> None:
            """在独立 Task 中运行 graph，SSE 断连后仍继续执行。"""
            try:
                final_state: dict[str, Any] = {}
                async for chunk in graph.astream(
                    {
                        "user_message": doc_context_prefix + content,
                        "user_parts": input_parts_data,
                        "run_id": str(orch_run.run_id),
                    },
                    config=graph_config,
                    stream_mode=["custom", "values"],
                    version="v2",
                ):
                    if chunk["type"] == "custom":
                        event_data = chunk["data"]
                        event = AgentEvent(
                            type=event_data["type"],
                            data=event_data.get("data", {}),
                        )
                        try:
                            event_queue.put_nowait(event)
                        except asyncio.QueueFull:
                            pass
                    elif chunk["type"] == "values":
                        final_state = chunk["data"]

                graph_state_holder.update(final_state)
            except Exception as exc:
                logger.exception(
                    "graph_run_error",
                    conversation_id=conv_id_str,
                    session_id=session_id,
                )
                graph_state_holder["phase"] = "error"
                graph_state_holder["result_metadata"] = {"status": "error"}
                try:
                    event_queue.put_nowait(
                        AgentEvent(type=ERROR, data={"message": str(exc)}),
                    )
                except asyncio.QueueFull:
                    pass
            finally:
                try:
                    event_queue.put_nowait(None)  # 哨兵：通知消费循环 graph 结束
                except asyncio.QueueFull:
                    pass

        graph_task = asyncio.create_task(_run_graph())

        # 旁观者打字机：把发起者的 SSE 流逐事件镜像广播到共享会话分组。
        from chat.realtime import abroadcast_stream

        detached_finalizer = False
        message_complete_seen = False
        try:
            # 事件消费循环（带 keepalive 心跳）
            while True:
                try:
                    event = await asyncio.wait_for(
                        event_queue.get(), timeout=15.0,
                    )
                except TimeoutError:
                    yield AgentEvent(type=KEEPALIVE, data={})
                    continue

                if event is None:
                    break

                if event.type == MESSAGE_COMPLETE:
                    message_complete_seen = True
                    event.data.setdefault("model", model)
                    event.data.setdefault("session_id", session_id)

                # 旁观者打字机镜像（keepalive 仅心跳，无需广播）。
                if event.type != KEEPALIVE:
                    await abroadcast_stream(
                        conversation, {"type": event.type, **event.data}
                    )

                yield event

            # graph 完成，等待 Task 清理
            await graph_task

            state = graph_state_holder
            phase = state.get("phase", "")

            if phase == "waiting":
                # graph interrupt — blocking tasks 等待中
                await _handle_waiting_state(
                    state=state,
                    orch_run=orch_run,
                    graph_config=graph_config,
                    conversation=conversation,
                    assistant_msg_id=assistant_msg_id,
                    agent_session=agent_session,
                    session_id=session_id,
                    model=model,
                    content=content,
                    notification_user_id=notification_user_id,
                    conv_id_str=conv_id_str,
                    do_finalize=do_finalize,
                )
            elif phase == "waiting_clarification":
                # review review round Fix #1：graph interrupt — 等待用户回答 ClarificationCard。
                # 不调 do_finalize（保持 conversation RUNNING，由 ClarificationAnswerView
                # 在用户答复后 resume graph 时自己 finalize）。详见
                # _handle_waiting_clarification_state docstring + work-item item-error.md。
                await _handle_waiting_clarification_state(
                    state=state,
                    orch_run=orch_run,
                    conversation=conversation,
                    triggering_message_id=user_msg_id_str,
                    conv_id_str=conv_id_str,
                )
            else:
                # 正常完成 / 错误 / 中断
                final_content, accumulated_thinking, tool_calls, _snap = (
                    await _hydrate_finalize_from_snapshot(orch_run, state)
                )
                result_metadata = state.get("result_metadata", {})

                is_error = state.get("phase") == "error"
                # exclude(INTERRUPTED)：用户在 interrupt API 已把 OrchestrationRun
                # 写成 INTERRUPTED；graph 后到的完成态不能覆盖用户意图。
                await OrchestrationRun.objects.filter(
                    id=orch_run.id,
                ).exclude(status=OrchestrationRun.Status.INTERRUPTED).aupdate(
                    status=OrchestrationRun.Status.ERROR if is_error else OrchestrationRun.Status.COMPLETED,
                    phase=state.get("phase", OrchestrationRun.Phase.COMPLETED),
                )

                final_events = await do_finalize(
                    conversation=conversation,
                    assistant_msg_id=assistant_msg_id,
                    final_content=final_content,
                    accumulated_thinking=accumulated_thinking,
                    tool_calls=tool_calls,
                    result_metadata=result_metadata,
                    agent_session=agent_session,
                    session_id=session_id,
                    model=model,
                    user_message=content,
                    notification_user_id=notification_user_id,
                    publish_title_event=True,
                    parts=_extract_state_parts(state),
                    doc_summary=captured_doc_summary,
                )
                # finalize 已经落库，清掉 streaming_snapshot 避免 runtime API 又拉到陈旧快照
                from orchestration.graph import _clear_streaming_snapshot

                await _clear_streaming_snapshot(str(orch_run.run_id))
                if not message_complete_seen:
                    yield _build_message_complete_event(
                        final_content=final_content,
                        result_metadata=result_metadata,
                        model=model,
                        session_id=session_id,
                    )
                for title_event in final_events:
                    yield title_event

        except GeneratorExit:
            detached_finalizer = True
            logger.info(
                "sse_disconnected",
                conversation_id=conv_id_str,
                session_id=session_id,
            )

            async def _background_finalize() -> None:
                """后台等待 graph 完成并执行收尾。"""
                try:
                    await graph_task
                    state = graph_state_holder
                    phase = state.get("phase", "")

                    if phase == "waiting":
                        await _handle_waiting_state(
                            state=state,
                            orch_run=orch_run,
                            graph_config=graph_config,
                            conversation=conversation,
                            assistant_msg_id=assistant_msg_id,
                            agent_session=agent_session,
                            session_id=session_id,
                            model=model,
                            content=content,
                            notification_user_id=notification_user_id,
                            conv_id_str=conv_id_str,
                            do_finalize=do_finalize,
                        )
                    elif phase == "waiting_clarification":
                        # review review round Fix #1：后台路径同样处理 — 用户按停止键 SSE 断开后
                        # graph 在 wait_clarification_node 仍正常 interrupt()，这里需要
                        # 与在线分支等价的 elif 分支，否则 GeneratorExit 路径仍会落 ERROR。
                        await _handle_waiting_clarification_state(
                            state=state,
                            orch_run=orch_run,
                            conversation=conversation,
                            triggering_message_id=user_msg_id_str,
                            conv_id_str=conv_id_str,
                        )
                    else:
                        is_error = state.get("phase") == "error"
                        # 同 SSE 在线分支：guard 用户主动中断的终态不被 graph 完成
                        # 路径覆盖（_background_finalize 是 GeneratorExit 后才跑的，
                        # 用户按停止键 → SSE 断 → 此路径几乎必然进入）。
                        await OrchestrationRun.objects.filter(
                            id=orch_run.id,
                        ).exclude(status=OrchestrationRun.Status.INTERRUPTED).aupdate(
                            status=OrchestrationRun.Status.ERROR if is_error else OrchestrationRun.Status.COMPLETED,
                            phase=state.get("phase", OrchestrationRun.Phase.COMPLETED),
                        )
                        # 用户中断路径（GeneratorExit 几乎必然走这）：graph 抛
                        # CancelledError 时 state.final_answer 是空，必须从
                        # streaming snapshot 还原已经流出来的内容，否则 messages
                        # 表里只剩一条空 assistant 消息，刷新页面什么都没有。
                        final_content, accumulated_thinking, tool_calls_bg, _snap = (
                            await _hydrate_finalize_from_snapshot(orch_run, state)
                        )
                        await do_finalize(
                            conversation=conversation,
                            assistant_msg_id=assistant_msg_id,
                            final_content=final_content,
                            accumulated_thinking=accumulated_thinking,
                            tool_calls=tool_calls_bg,
                            result_metadata=state.get("result_metadata", {}),
                            agent_session=agent_session,
                            session_id=session_id,
                            model=model,
                            user_message=content,
                            notification_user_id=notification_user_id,
                            publish_title_event=False,
                            parts=_extract_state_parts(state),
                            doc_summary=captured_doc_summary,
                        )
                        # 已落库，清掉 streaming_snapshot 避免 runtime polling 拉到陈旧快照
                        from orchestration.graph import _clear_streaming_snapshot

                        await _clear_streaming_snapshot(str(orch_run.run_id))
                except Exception:
                    logger.exception(
                        "background_finalize_error",
                        conversation_id=conv_id_str,
                    )
                    await Conversation.objects.filter(id=conversation.id).aupdate(
                        status=Conversation.Status.ERROR,
                    )

            asyncio.create_task(_background_finalize())
            return

        finally:
            if not detached_finalizer:
                unregister_runner(conv_id_str)
            logger.debug(
                "conversation_facade_completed",
                conversation_id=conv_id_str,
                session_id=session_id,
            )

    @staticmethod
    async def resume_clarification_run(
        conversation_id: str,
        resume_payload: dict[str, Any],
    ) -> None:
        """用户答复 clarification 后恢复 graph 并完成收尾落库。

        ``ClarificationAnswerView`` 的后台 resume 入口。此前 view 直接
        ``graph.ainvoke(Command(resume=...), {"configurable": {"thread_id": ...}})``
        存在两个致命缺口（用户答复后 run 永久卡在 waiting_clarification 的根因）：

        1. **configurable 不会从 checkpoint 恢复** —— LangGraph checkpoint 只存
           state，api_key / model / system_prompt 等必须每次 invoke 重新传入。
           裸 config resume 后 ``_build_chat_runner`` 拿不到 api_key，静默返回
           ``phase=error``（不抛异常、不写 DB），OrchestrationRun 停留在
           ``status=WAITING, phase=waiting_clarification``。
        2. **resume 完成后无人收尾** —— 与 blocking_tasks 路径的
           ``_on_barrier_complete`` 不同，没有人更新 OrchestrationRun 终态、
           也没有人调 ``finalize_conversation`` 落 assistant 消息。

        本方法对齐 ``_on_barrier_complete``：重建完整 graph config →
        ``astream(Command(resume=...))`` → 更新 run 终态 + finalize 落库。
        """
        from langgraph.types import Command

        from chat.config import build_sdk_config
        from chat.finalize import finalize_conversation

        conversation = await Conversation.objects.select_related(
            "space", "provider_credential_id",
        ).aget(id=conversation_id, is_deleted=False)
        conv_id_str = str(conversation.id)

        # status 同时匹配 WAITING 与 RUNNING：正常 dispatch 会把 run 落成
        # WAITING，但后台 finalizer 被中途打断（dev reload / SSE 异常断开后台
        # 任务回收）时 run 会停在 ``status=running, phase=waiting_clarification``
        # 的孤儿态。resume / skip 必须能覆盖它，否则永久卡死。
        orch_run = await OrchestrationRun.objects.filter(
            conversation=conversation,
            status__in=[
                OrchestrationRun.Status.WAITING,
                OrchestrationRun.Status.RUNNING,
            ],
            phase=OrchestrationRun.Phase.WAITING_CLARIFICATION,
        ).order_by("-created_at").afirst()
        if orch_run is None:
            logger.warning(
                "clarification_resume_no_waiting_run",
                conversation_id=conv_id_str,
            )
            return

        reply_text = str(
            resume_payload.get("freeform_text")
            or resume_payload.get("selected_option_label")
            or "",
        )

        async def _mark_error(error_message: str) -> None:
            await OrchestrationRun.objects.filter(
                id=orch_run.id,
            ).exclude(status=OrchestrationRun.Status.INTERRUPTED).aupdate(
                status=OrchestrationRun.Status.ERROR,
                phase=OrchestrationRun.Phase.ERROR,
            )
            await Conversation.objects.filter(
                id=conversation.id,
            ).exclude(status=Conversation.Status.INTERRUPTED).aupdate(
                status=Conversation.Status.ERROR,
            )
            # 兜底错误消息：避免前端只看到 run 变 error 却没有任何反馈气泡
            try:
                await Message.objects.acreate(
                    conversation=conversation,
                    role=Message.Role.ASSISTANT,
                    content=error_message,
                    metadata={"status": "error"},
                )
            except Exception:
                logger.exception(
                    "clarification_resume_error_message_failed",
                    conversation_id=conv_id_str,
                )

        try:
            sdk_config, agent_session = await build_sdk_config(conversation)
        except Exception as e:
            # 不止 ValueError：任何配置阶段异常（如事件循环/executor 故障）都必须
            # 把 run 标成 error，否则会永久停在 waiting_clarification 等待态。
            logger.exception(
                "clarification_resume_config_error",
                conversation_id=conv_id_str,
            )
            await _mark_error(f"恢复对话失败：{e}")
            return

        session_id = sdk_config.session_id
        model = sdk_config.model

        # 与 send_message_stream 的 graph_config 同构 —— executing_node 会用
        # configurable 重新构造 ChatRunnerConfig，缺字段会导致静默降级。
        graph_config: dict[str, Any] = {
            "configurable": {
                "thread_id": conv_id_str,
                "conversation_id": conv_id_str,
                "api_key": sdk_config.api_key,
                "api_base_url": sdk_config.api_base_url,
                "model": model,
                "session_id": session_id,
                "system_prompt": sdk_config.system_prompt,
                "space_id": sdk_config.space_id,
                # 项目级对话：透传绑定项目 id（与 send_message_stream 同构），
                # 否则 resume 后 _get_tool_names 拿不到项目只读工具。
                "bound_project_id": sdk_config.bound_project_id,
                "role": "developer",
                "agent_session_id": str(agent_session.id),
                "notification_user_id": "",
                "max_budget_usd": sdk_config.max_budget_usd,
                "default_search_branch": None,
                "force_deep_analysis": sdk_config.force_deep_analysis,
                # 与 send_message_stream 同构：透传绑定模型能力清单，
                # 让 resume 后的图片模态门控同样以配置为准。
                "available_models": sdk_config.available_models,
            }
        }

        # 进入恢复执行态：前端 runtime polling 立刻能看到 phase 离开
        # waiting_clarification（executing_node 稍后还会自己持久化 phase）。
        await OrchestrationRun.objects.filter(id=orch_run.id).aupdate(
            status=OrchestrationRun.Status.RUNNING,
            phase=OrchestrationRun.Phase.EXECUTING,
        )
        await Conversation.objects.filter(
            id=conversation.id,
        ).exclude(status=Conversation.Status.INTERRUPTED).aupdate(
            status=Conversation.Status.RUNNING,
        )

        try:
            graph = await get_compiled_graph()
            final_state: dict[str, Any] = {}
            async for chunk in graph.astream(
                Command(resume=resume_payload),
                config=graph_config,
                stream_mode=["custom", "values"],
                version="v2",
            ):
                if chunk["type"] == "values":
                    final_state = chunk["data"]

            is_error = final_state.get("phase") == "error"
            await OrchestrationRun.objects.filter(
                id=orch_run.id,
            ).exclude(status=OrchestrationRun.Status.INTERRUPTED).aupdate(
                status=OrchestrationRun.Status.ERROR
                if is_error
                else OrchestrationRun.Status.COMPLETED,
                phase=final_state.get("phase", OrchestrationRun.Phase.COMPLETED),
            )

            raw_parts = final_state.get("parts")
            parts = (
                [p for p in raw_parts if isinstance(p, dict)]
                if isinstance(raw_parts, list)
                else []
            )
            await finalize_conversation(
                conversation=conversation,
                assistant_msg_id=uuid.uuid4(),
                final_content=final_state.get("final_answer", ""),
                accumulated_thinking=list(final_state.get("accumulated_thinking") or []),
                tool_calls=list(final_state.get("tool_calls") or []),
                result_metadata=final_state.get("result_metadata", {}),
                agent_session=agent_session,
                session_id=session_id,
                model=model,
                user_message=reply_text,
                publish_title_event=False,
                parts=parts,
            )
            logger.info(
                "clarification_resume_finalized",
                conversation_id=conv_id_str,
                session_id=session_id,
                is_error=is_error,
            )
        except Exception:
            logger.exception(
                "clarification_resume_error",
                conversation_id=conv_id_str,
                session_id=session_id,
            )
            await _mark_error("处理你的答复时出现异常，请重新发送消息。")

    @staticmethod
    async def list_conversations(
        user: Any = None,
        *,
        query: str | None = None,
        limit: int = 50,
        include_archived: bool = False,
        archived_only: bool = False,
        bound_project: str | None = None,
    ) -> list[Conversation]:
        """返回未删除对话列表，按 updated_at 降序。

        owner-scoped（ISO-02）：已认证用户仅列自己的会话（``created_by=user``）；
        未认证（开放模式）维持现状列全部。无管理员特权 bypass（ISO-03）。

        Args:
            query: 搜索关键词。非空时匹配 title **或** 任意消息 content（``messages__
                content__icontains``）—— 用户诉求「能搜到会话里面的内容」。
            limit: 最多返回多少条（默认 50，左侧列表 top 50）。<=0 表示不限。
            include_archived: 是否包含已归档会话（默认隐藏归档）。
            archived_only: 仅返回已归档会话（「查看已归档」入口）；优先级高于
                ``include_archived``。
        """
        from django.db.models import Exists, OuterRef, Q

        from chat.models import CodingPlan, CodingSession
        from delivery.models import ConvergenceSession, SddSpec

        # select_related("created_by")：列表项序列化器需读会话创建者简要（项目作战室
        # P2 贡献者头像/名字），async 路径必须预取避免惰性 FK 触发 SynchronousOnlyOperation。
        qs = Conversation.objects.filter(is_deleted=False).select_related("created_by")
        if archived_only:
            qs = qs.filter(is_archived=True)
        elif not include_archived:
            qs = qs.filter(is_archived=False)
        if getattr(user, "is_authenticated", False):
            # owner-scoped（ISO-02）+ 项目作战室 P2：叠加「我所在项目的共享会话」。
            project_ids = await _user_project_ids(user)
            own_q = Q(created_by=user)
            if project_ids:
                qs = qs.filter(
                    own_q
                    | Q(
                        visibility=Conversation.Visibility.SHARED,
                        bound_project_id__in=project_ids,
                    )
                )
            else:
                qs = qs.filter(own_q)
        # 项目作战室：按绑定项目过滤（项目页大盘只列本项目会话）。
        if bound_project:
            qs = qs.filter(bound_project_id=bound_project)

        q = (query or "").strip()
        if q:
            # title 或消息内容命中即返回；join messages 会产生重复行，distinct 去重。
            qs = qs.filter(
                Q(title__icontains=q) | Q(messages__content__icontains=q)
            ).distinct()

        # 列表徽标聚合（SDD / 技术方案 / 编码）：Exists 子查询，不引入 N+1、async 安全
        # （annotate 出的布尔是实例列，序列化器直接读属性不触发 sync ORM）。
        qs = qs.annotate(
            has_coding_plan=Exists(
                CodingPlan.objects.filter(conversation_id=OuterRef("pk"))
            ),
            has_coding_session=Exists(
                CodingSession.objects.filter(conversation_id=OuterRef("pk"))
            ),
            # SDD spec 反查：conversation → PlanSession(软引用会话) 且其 current_plan_version
            # 命中某条 SddSpec.plan_version（UUID 相等匹配，无需跨 app FK）。单层 OuterRef
            # 关联会话，内层 __in 为非关联子查询（全部 spec 的 plan_version 集合）。
            has_sdd_spec=Exists(
                ConvergenceSession.objects.filter(
                    conversation_id=OuterRef("pk"),
                    current_artifact_version__isnull=False,
                    current_artifact_version__in=SddSpec.objects.filter(
                        artifact_version__isnull=False
                    ).values("artifact_version_id"),
                )
            ),
        )

        qs = qs.order_by("-updated_at")
        if limit and limit > 0:
            qs = qs[:limit]
        return [c async for c in qs]

    @staticmethod
    async def get_conversation_with_messages(
        conversation_id: str,
    ) -> dict[str, Any]:
        """返回对话详情 + 全部历史消息。

        Args:
            conversation_id: 对话 UUID

        Returns:
            包含 conversation 和 messages 的 dict

        Raises:
            Conversation.DoesNotExist: 对话不存在或已删除
        """
        conversation = await Conversation.objects.aget(
            id=conversation_id,
            is_deleted=False,
        )
        messages = [
            msg async for msg in Message.objects.filter(
                conversation=conversation,
            ).order_by("created_at")
        ]
        return {
            "conversation": conversation,
            "messages": messages,
        }

    @staticmethod
    async def get_conversation_runtime(
        conversation_id: str,
    ) -> dict[str, Any]:
        """返回对话当前运行态 — 从 OrchestrationRun DB 读取真实 phase/status。"""
        from datetime import timedelta

        from django.utils import timezone

        from subagent.models import SubAgentSession

        terminal_statuses = {
            OrchestrationRun.Status.COMPLETED,
            OrchestrationRun.Status.ERROR,
            OrchestrationRun.Status.INTERRUPTED,
        }

        from uuid import UUID
        try:
            conv_uuid = UUID(conversation_id)
        except ValueError:
            conv_uuid = conversation_id
        orch_run = await OrchestrationRun.objects.filter(
            conversation_id=conv_uuid,
        ).order_by("-created_at").afirst()

        is_active = False
        orch_phase: str | None = None
        orch_status: str | None = None
        orch_run_id = ""
        task_progress: dict[str, int] | None = None

        # 孤儿 run（zombie）恢复：graph 已在 checkpoint 跑完终态，但收尾 task 被
        # 热重载 / 进程退出杀掉（详见 chat/recovery.py）→ 从 checkpoint 兜底落库，
        # 避免前端永久卡在「正在整理回答…」+ 空气泡。命中后 re-fetch 拿到终态行，
        # 走下面的 hydrateMessages 路径渲染 final assistant message。
        if orch_run is not None and orch_run.status in {
            OrchestrationRun.Status.RUNNING,
            OrchestrationRun.Status.WAITING,
        }:
            from chat.recovery import recover_orphaned_run

            try:
                if await recover_orphaned_run(orch_run):
                    refreshed = await OrchestrationRun.objects.filter(
                        id=orch_run.id,
                    ).afirst()
                    if refreshed is not None:
                        orch_run = refreshed
            except Exception:
                logger.warning(
                    "conversation_runtime_recovery_failed",
                    conversation_id=conversation_id,
                    exc_info=True,
                )

        if orch_run is not None:
            if orch_run.status in terminal_statuses:
                is_active = False
            elif (
                orch_run.status in {OrchestrationRun.Status.RUNNING, OrchestrationRun.Status.WAITING}
                and orch_run.created_at < timezone.now() - timedelta(hours=1)
            ):
                # 超时窗口：running/waiting 超 1 小时 → 视为 error，auto-close
                await OrchestrationRun.objects.filter(id=orch_run.id).aupdate(
                    status=OrchestrationRun.Status.ERROR,
                    phase=OrchestrationRun.Phase.ERROR,
                )
                is_active = False
                orch_status = OrchestrationRun.Status.ERROR
            else:
                is_active = True

            if orch_status is None:
                orch_status = orch_run.status
            orch_phase = orch_run.phase
            orch_run_id = str(orch_run.run_id)

            progress_meta = orch_run.metadata.get("progress") if isinstance(orch_run.metadata, dict) else None
            if isinstance(progress_meta, dict):
                task_progress = {
                    "completed": progress_meta.get("completed", 0),
                    "total": progress_meta.get("total", 0),
                }

        # 从 phase 推导向后兼容 mode
        mode: str | None = None
        if is_active:
            mode = "chat"

        # SSE 单向无状态，浏览器刷新会让前端流式渲染全部丢失。executing_node 把
        # 实时累积态写到 orch_run.metadata['streaming_snapshot']（详见
        # orchestration.graph._StreamingSnapshot）。仅在 is_active=True 时透传 —
        # 完成态由前端走 hydrateMessages 路径渲染 final assistant message，再读
        # snapshot 会导致 bubble 重影。
        streaming_snapshot: dict[str, Any] | None = None
        if is_active and orch_run is not None and isinstance(orch_run.metadata, dict):
            snap = orch_run.metadata.get("streaming_snapshot")
            if isinstance(snap, dict):
                streaming_snapshot = snap

        runtime: dict[str, Any] = {
            "conversation_id": conversation_id,
            "active": is_active,
            "mode": mode,
            "status": orch_status,
            "orchestration_run_id": orch_run_id,
            "phase": orch_phase,
            "task_progress": task_progress,
            "session_id": "",
            "task_description": "",
            "progress_message": "",
            "progress_percent": None,
            "logs": [],
            "coding_session": None,
            "streaming_snapshot": streaming_snapshot,
            "pending_clarification": None,
            "pending_plan_clarification": None,
        }

        # 待回复的澄清（ask_clarification）—— 刷新 / 切回会话时恢复 ClarificationCard。
        # waiting_clarification 期间澄清问题只存在图 checkpoint + ConversationIntentTrace，
        # 不落 Message；前端内存 pendingClarifications 刷新即丢，故这里回灌。
        # 仅在 run 活跃且处于 waiting_clarification 阶段时返回，避免历史会话遗留的
        # 未回答 trace（如旧版强制澄清被用户绕过）复活成幽灵卡片。
        if is_active and orch_phase == OrchestrationRun.Phase.WAITING_CLARIFICATION:
            from chat.models import ConversationIntentTrace

            trace = await ConversationIntentTrace.objects.filter(
                conversation_id=conv_uuid,
                answered_at__isnull=True,
            ).order_by("-created_at").afirst()
            if trace is not None and isinstance(trace.options, list) and trace.options:
                runtime["pending_clarification"] = {
                    "clarification_id": trace.clarification_id,
                    "question": trace.question,
                    "options": trace.options,
                    "allow_freeform": True,
                }

        # plan 编排澄清轮（CLARIFY-04 数据传输）：与上面 chat 单题 pending_clarification
        # （ConversationIntentTrace）**物理隔离**，独立 key 不污染既有 chat 澄清回归。
        # 检测本会话软引用关联的 PlanSession 是否存在 pending 结构化澄清轮 → 序列化多题
        # questions[] 供前端 91-05 渲染。只读、不写库；序列化失败 best-effort 吞为 None，
        # 绝不反噬 runtime。async 全程用 *_id 标量过滤，禁裸 lazy-FK。
        try:
            from delivery.models import (
                Clarification,
                ClarificationQuestion,
                ConvergenceSession,
            )
            from delivery.services import ClarificationService

            plan_session = (
                await ConvergenceSession.objects.filter(conversation_id=conv_uuid)
                .order_by("-created_at")
                .afirst()
            )
            if plan_session is not None and await ClarificationService().ahas_pending(
                plan_session.id
            ):
                pending_round = (
                    await Clarification.objects.filter(
                        session_id=plan_session.id, answered_at__isnull=True
                    )
                    .order_by("round_no")
                    .afirst()
                )
                if pending_round is not None:
                    questions = [
                        {
                            "question_id": str(q.id),
                            "question": q.question,
                            "qtype": q.qtype,
                            "options": q.options or [],
                            "recommended": q.recommended,
                            "selected": q.selected,
                            "freeform_text": q.freeform_text,
                        }
                        async for q in ClarificationQuestion.objects.filter(
                            clarification_id=pending_round.id
                        ).order_by("order")
                    ]
                    # 仅结构化轮（含子题）暴露；旧单题行（无子题）不渲染 plan 澄清卡。
                    if questions:
                        runtime["pending_plan_clarification"] = {
                            "clarification_id": str(pending_round.id),
                            "round_no": pending_round.round_no or 1,
                            "questions": questions,
                        }
        except Exception:
            # best-effort：plan 澄清序列化失败不反噬 runtime（保持 None 默认）。
            logger.warning(
                "conversation_runtime_plan_clarification_failed",
                conversation_id=conversation_id,
                exc_info=True,
            )
            runtime["pending_plan_clarification"] = None

        # deep_analysis 会话信息（向后兼容 + 多子会话各自独立日志）
        # order_by("-id") 是降序，最新的在最前。收集本对话全部 chat_deep_analysis
        # 子会话，供前端按会话分别渲染 swiper；latest 仍取第一个做向后兼容。
        deep_candidates: list[SubAgentSession] = []
        async for candidate in SubAgentSession.objects.filter(
            task_type=SubAgentSession.TaskType.EXPLORE,
            main_session__metadata__conversation_id=conversation_id,
        ).order_by("-id"):
            output = candidate.last_output or {}
            if isinstance(output, dict) and output.get("source") == "chat_deep_analysis":
                deep_candidates.append(candidate)

        def _session_to_deep_info(sess: SubAgentSession) -> dict[str, Any]:
            out = sess.last_output or {}
            prog = out.get("progress", {}) if isinstance(out, dict) else {}
            sess_logs = out.get("logs", []) if isinstance(out, dict) else []
            return {
                "session_id": sess.session_id,
                "task_description": out.get("task_description", "")
                if isinstance(out, dict)
                else "",
                "status": sess.status,
                "progress_message": prog.get("message", "")
                if isinstance(prog, dict)
                else "",
                "progress_percent": prog.get("progress")
                if isinstance(prog, dict)
                else None,
                "logs": sess_logs if isinstance(sess_logs, list) else [],
            }

        # deep_sessions 用升序（与工具调用出现顺序一致），把降序结果反转即可。
        runtime["deep_sessions"] = [
            _session_to_deep_info(s) for s in reversed(deep_candidates)
        ]

        latest_deep_session = deep_candidates[0] if deep_candidates else None

        if latest_deep_session is not None:
            output = latest_deep_session.last_output or {}
            progress = output.get("progress", {}) if isinstance(output, dict) else {}
            logs = output.get("logs", []) if isinstance(output, dict) else []
            deep_info = {
                "session_id": latest_deep_session.session_id,
                "task_description": output.get("task_description", "")
                if isinstance(output, dict)
                else "",
                "progress_message": progress.get("message", "")
                if isinstance(progress, dict)
                else "",
                "progress_percent": progress.get("progress")
                if isinstance(progress, dict)
                else None,
                "logs": logs if isinstance(logs, list) else [],
            }
            if latest_deep_session.status in {
                SubAgentSession.Status.PENDING,
                SubAgentSession.Status.RUNNING,
            }:
                runtime.update(
                    {
                        "active": True,
                        "mode": "deep_analysis",
                        "status": latest_deep_session.status,
                        **deep_info,
                    }
                )
            else:
                # 终态：ERROR / TIMEOUT / CANCELLED / COMPLETED
                runtime.update(
                    {
                        **deep_info,
                        "deep_analysis_status": latest_deep_session.status,
                        "deep_analysis_error": latest_deep_session.failure_reason
                        or latest_deep_session.last_error
                        or "",
                    }
                )
                # 如果 deep analysis 已失败但主流程还在 waiting，
                # 将 active 设为 False 避免前端无限轮询
                if (
                    latest_deep_session.status
                    in {
                        SubAgentSession.Status.ERROR,
                        SubAgentSession.Status.TIMEOUT,
                        SubAgentSession.Status.CANCELLED,
                    }
                    and orch_run
                    and orch_run.status == OrchestrationRun.Status.WAITING
                ):
                    is_active = False
                    runtime["active"] = False
                    runtime["status"] = latest_deep_session.status
                    if runtime.get("mode") is None:
                        runtime["mode"] = "deep_analysis"

        # CodingSession 运行态检测 (implementation)
        from chat.models import CodingSession

        coding_session = await CodingSession.objects.filter(
            conversation_id=conversation_id,
            status__in=[
                CodingSession.Status.CONFIRMED,
                CodingSession.Status.RUNNING,
                CodingSession.Status.AWAITING_CONFIRMATION,
            ],
        ).order_by("-created_at").afirst()

        if coding_session is not None:
            runtime["active"] = True
            runtime["mode"] = "coding"
            runtime["coding_session"] = {
                "id": str(coding_session.id),
                "status": coding_session.status,
                "tech_plan": coding_session.tech_plan,
                "affected_files": coding_session.affected_files,
                "branch_name": coding_session.branch_name,
                "target_branch": coding_session.target_branch,
                "confirmation_step": coding_session.confirmation_step,
                "suggested_commit_message": coding_session.suggested_commit_message,
                "suggested_pr_title": coding_session.suggested_pr_title,
                "suggested_pr_description": coding_session.suggested_pr_description,
                "conflict_check_result": coding_session.conflict_check_result or None,
                "diff_summary": coding_session.diff_summary or None,
            }

            # 从 SubAgentSession.last_output 获取编码中间产出（per contract, contract）
            if coding_session.subagent_session_id:
                subagent_session = await SubAgentSession.objects.filter(
                    id=coding_session.subagent_session_id,
                ).afirst()
                if subagent_session and isinstance(subagent_session.last_output, dict):
                    coding_progress = subagent_session.last_output.get("coding_progress")
                    if coding_progress and isinstance(coding_progress, dict):
                        runtime["coding_session"]["coding_progress"] = {
                            "modified_files": coding_progress.get("modified_files", []),
                            "recent_tool_calls": coding_progress.get("recent_tool_calls", []),
                            "updated_at": coding_progress.get("updated_at", ""),
                        }
        else:
            # 检查是否有刚完成/失败的 CodingSession（最近 5 分钟内）
            recent_cutoff = timezone.now() - timedelta(minutes=5)
            recent_coding = await CodingSession.objects.filter(
                conversation_id=conversation_id,
                status__in=[CodingSession.Status.COMPLETED, CodingSession.Status.FAILED],
                updated_at__gte=recent_cutoff,
            ).order_by("-updated_at").afirst()
            if recent_coding is not None:
                runtime["coding_session"] = {
                    "id": str(recent_coding.id),
                    "status": recent_coding.status,
                    "pr_url": recent_coding.pr_url,
                    "branch_name": recent_coding.branch_name,
                    "error_message": recent_coding.error_message,
                    "affected_files": recent_coding.affected_files,
                }

        # 附加最近 CodingPlan + 每仓 session 快照
        #
        # 与 coding_session 字段独立并存（向后兼容旧前端单仓路径）；新前端读
        # runtime.coding_plan.sessions[]。commit_sha 来自 SubAgentSession.task_result
        # （implementation contract 落库后才有真值），缺失时空字符串降级渲染。
        from chat.models import CodingPlan

        coding_plan_payload: dict[str, Any] | None = None
        latest_plan = (
            await CodingPlan.objects.filter(conversation_id=conv_uuid)
            .order_by("-created_at")
            .afirst()
        )
        if latest_plan is not None:
            from django.core.exceptions import ObjectDoesNotExist

            sessions = [
                s
                async for s in CodingSession.objects.filter(
                    coding_plan=latest_plan
                )
                .select_related("repository", "subagent_session", "subagent_session__task_result")
                .order_by("created_at", "repository__name")
            ]

            session_items: list[dict[str, Any]] = []
            for s in sessions:
                commit_sha = ""
                if s.subagent_session is not None:
                    try:
                        task_result = s.subagent_session.task_result
                    except ObjectDoesNotExist:
                        task_result = None
                    if task_result is not None:
                        commit_sha = str(task_result.commit_sha or "")
                session_items.append(
                    {
                        "session_id": str(s.id),
                        "repository_id": str(s.repository_id),
                        "repository_name": s.repository.name,
                        "branch_name": s.branch_name,
                        "target_branch": s.target_branch,
                        "status": s.status,
                        "pr_url": s.pr_url,
                        "commit_sha": commit_sha,
                        "error_message": s.error_message,
                    }
                )

            coding_plan_payload = {
                "plan_id": str(latest_plan.id),
                "title": latest_plan.title,
                "sessions": session_items,
                # 方案来源与正文（Phase 109）：前端据 provenance 渲染「未经代码调研」
                # 告示；provenance 只由服务端写，runtime 无写路径。
                "provenance": latest_plan.provenance,
                "tech_plan": latest_plan.tech_plan,
                "affected_files": latest_plan.affected_files or [],
                "recommended_repository_ids": latest_plan.recommended_repository_ids
                or [],
                "source_artifact_version_id": (
                    str(latest_plan.source_artifact_version_id)
                    if latest_plan.source_artifact_version_id
                    else None
                ),
                "feishu_doc_token": latest_plan.feishu_doc_token or "",
                "feishu_doc_url": latest_plan.feishu_doc_url or "",
            }
            logger.debug(
                "runtime.coding_plan_attached",
                conversation_id=conversation_id,
                plan_id=coding_plan_payload["plan_id"],
                sessions_count=len(session_items),
            )

        runtime["coding_plan"] = coding_plan_payload

        return runtime

    @staticmethod
    async def delete_conversation(conversation_id: str, user: Any = None) -> None:
        """软删除对话。

        owner-scoped（ISO-04）：已认证用户仅能删自己的会话；越权/不存在统一抛
        ``Conversation.DoesNotExist``（0 行更新即抛，view 映射 404）。无管理员
        特权 bypass（ISO-03）；未认证（开放模式）维持现状。

        Args:
            conversation_id: 对话 UUID
            user: 操作者；已认证则按 owner 过滤

        Raises:
            Conversation.DoesNotExist: 对话不存在、已删除，或越权删除他人会话
        """
        # 项目作战室 P2：共享会话删除限「创建者 + 项目管理员（主R）」。
        # 个人会话维持 owner-only（ISO-04）。已认证用户先做权限判定再软删。
        if getattr(user, "is_authenticated", False):
            conv = await Conversation.objects.filter(
                id=conversation_id, is_deleted=False
            ).afirst()
            if conv is None:
                raise Conversation.DoesNotExist(
                    f"对话不存在或已删除: {conversation_id}"
                )
            allowed = conv.created_by_id == user.id
            if (
                not allowed
                and conv.visibility == Conversation.Visibility.SHARED
                and conv.bound_project_id is not None
            ):
                allowed = await _is_project_admin(user, conv.bound_project_id)
            if not allowed:
                raise Conversation.DoesNotExist(
                    f"对话不存在或无权删除: {conversation_id}"
                )
            await Conversation.objects.filter(id=conv.id).aupdate(is_deleted=True)
        else:
            # 未认证（开放模式）维持现状：无 owner 过滤直接软删。
            updated = await Conversation.objects.filter(
                id=conversation_id, is_deleted=False
            ).aupdate(is_deleted=True)
            if updated == 0:
                raise Conversation.DoesNotExist(
                    f"对话不存在或已删除: {conversation_id}"
                )

        logger.info(
            "conversation_deleted",
            conversation_id=conversation_id,
            category="caller",
            component="chat.conversation",
        )
