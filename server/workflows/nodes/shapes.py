"""端口能力契约（shape）取值常量集合（SLOT-01，Phase 92）。

`NodePort.shape` 是与 `port_type` 正交的「能力 / 内容契约」标识：匹配的不是数据
几何形状，而是能力语义——能产出 / 消费同一类内容 / 能力的端口才可连（per D-A）。

设计选择：用 ``str`` + 模块级 ``frozenset`` 常量集合，而非 ``Enum``。CONTEXT 明确
「契约取值应可扩展」（Phase 93 会引入更多 feishu_document / notification / approval
契约的连法），扁平字符串 + 常量集合比闭集 Enum 更灵活；端口声明处引用本集合保可读性。

**重要不变量**：`WorkflowGraphValidator` **不**强制端口 shape 取值 ∈ 本集合——契约
兼容仅靠「双端 shape 非空且相等」判定，未知取值不被闭集拦截。本集合仅为声明侧可读
性与已知能力清单铺底（Phase 93 磁吸消费），可随能力增长追加。
"""

# 已知能力契约取值（可扩展，非闭集）。本 phase 端口实际只贴
# clarification_request / clarification_answer / feishu_message 三项，其余为后续
# Phase（93+）铺底常量，不强制给现有端口赋值。
KNOWN_PORT_SHAPES: frozenset[str] = frozenset(
    {
        "clarification_request",
        "clarification_answer",
        "feishu_message",
        "technical_plan",
        "coding_assignment",
        "feishu_document",
        "approval_result",
        # 结构化 feature list（模块→功能点→验收项）：拆分节点产出、创建项目节点消费（#4）。
        "feature_list",
    }
)
