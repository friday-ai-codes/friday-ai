"""``analyze_repository_relevance`` 工具 Pydantic schema。

字段冻结契约由 ``tests/agents/test_repository_relevance_tool.py`` 的
schema snapshot fixture（``tests/agents/fixtures/repository_relevance_input_schema.json``）
守护，schema 漂移触发 diff 必须可 review。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RepositoryRelevanceInput(BaseModel):
    """LLM 可见 input schema —— ``space_id`` / ``conversation_id`` 由 chat_runner
    自动注入（与 ``create_coding_plan`` 同模式），但仍出现在 schema 中以便对
    schema snapshot 守门。"""

    query: str = Field(min_length=1, description="用户的跨仓需求 query，单一概念优先")
    space_id: str = Field(description="空间 UUID（auto-injected by chat_runner）")
    conversation_id: str = Field(
        description="会话 UUID（auto-injected by chat_runner）"
    )
    top_k: int = Field(default=5, ge=1, le=20)
    threshold: float = Field(default=0.5, ge=0.0, le=1.0)


class RepositoryRelevanceCandidate(BaseModel):
    repository_id: str
    repository_name: str
    score: float = Field(ge=0.0, le=1.0)
    level: Literal["high", "medium", "low"]
    evidence: str
    selected_by_ai: bool
    selected_by_user_final: bool
    # PageIndex v2 扩展（可选，legacy 路径为空）：monorepo 子应用归属及其根目录
    sub_project: str = ""
    sub_project_paths: list[str] = Field(default_factory=list)
    # 分数可拆解（ROUTE-07）：信号名 → 贡献值，Σ贡献 == score（后端打分核心
    # INV-R1/R3 保证）。legacy 聚合路径 / 历史 trace 为空 dict，前端静默降级。
    breakdown: dict[str, float] = Field(default_factory=dict)
    # 分层呈现（ROUTE-01/02，107-07）：归属组，缺省（空串）由前端视为 global。
    group: str = ""
    # 信任标记（trusted / needs_confirmation）；本 phase 与 group == global 语义重合，
    # 前端不额外渲染第二个徽标，字段仅作数据契约留存。
    trust: str = ""
    # 旁路排序分（凸组合结果，D-3 硬约束：绝不覆盖 score）。前端排序用
    # score_ranked ?? score，**徽标与分数分解合计行继续用 score**——两个可见分数会
    # 产生「徽标 87% 却排在 91% 前面」的无法解释现象。None = Stage 1 未参与重排。
    score_ranked: float | None = None
    # 刻意不加后端留痕说明字段：UI-SPEC 的 T-107-06 明确前端只渲染前端常量、不渲染
    # 后端自由文本，该留痕留在 router 侧即可——少一个字段少一条泄漏面。


class RepositoryRelevanceOutput(BaseModel):
    candidates: list[RepositoryRelevanceCandidate]
    threshold: float
    total_candidates: int
    trace_id: str
    # 结果级事实（RELY-03 / ROUTE-01）：与 trace 落库的同一组值，供**实时对话链路**
    # 直接渲染。缺了这四个字段，降级横幅与分组分区只有在刷新页面（走 detail payload）
    # 或改一次勾选（走 override 响应）之后才出现——也就是在用户最需要看到的那一刻
    # （对话进行中）恒不生效。全部带默认值，legacy / 历史输出形状不变。
    router_version: str = ""
    degraded: bool = False
    degrade_reason: str = ""
    block_order: list[str] = Field(default_factory=list)
