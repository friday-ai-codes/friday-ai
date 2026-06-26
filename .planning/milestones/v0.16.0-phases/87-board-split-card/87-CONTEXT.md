# Phase 87: 看板拆分节点 + 群 + 流式卡片 - Context

**Gathered:** 2026-06-26
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous) — 用户逐 Wave 选定

<domain>
## Phase Boundary

基于 feature list 自动拆子看板并经群聊卡片人机协同确认：看板拆分节点（feature list → 子看板 work_item/create + 父子关联）+ 拉群 + bot 入群 + 拆分结果流式卡片 + 多轮重拆。

交付需求：BOARD-01/02。
</domain>

<decisions>
## Implementation Decisions

### feature list 输入来源
- **多源输入**：文件上传（md）+ 飞书文档链接（回拉正文）+ 粘贴文本。
- feature list 过大（如 82KB demo）→ 结构化抽取（模块→功能点→验收项）+ 分块 + token 预算降级。

### 子看板拆分粒度
- **每个 feature 一个子看板 work_item**（`work_item/create`，名=feature 名、描述=feature 原文，`relation_type=1` 关联项目跟踪），**模块作分组**。
- 父子关系类型缺失时降级（建看板不挂父子 + 提示去配置中心预配）。

### 群聊策略
- **复用项目群，无则建新群**：拆分结果优先发到项目已有群；项目无群则建新群 + 飞书 bot 入群。

### 拆分流程（BOARD-02）
- 拉群 + bot 入群 + 拆分结果流式卡片（「开始创建」/ 输入框+发送，复用 CardKit）。
- 用户点「开始创建」→ 直接建看板；用户输入信息 → 多轮重拆后重新发群。

### 工作流节点 + AI 会话可调
- 看板拆分做成工作流节点（自动注册）+ AI 会话可调用。
- 新增 LLM（看板拆分）赋 `call_source`（LOGGING-SPEC §4.1 登记新值）+ 上报请求/token/TTFT/上游错误码。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/workflows/nodes/`：BaseNode 子类自动注册（放 `<category>/` 即注册）——看板拆分节点落点。
- `server/services/feishu.py`：`work_item/create` + 父子关系（relation_type=1）；plan-phase 先 live 验证写 API（Phase 78 仅验证读）。
- `server/services/feishu_im.py` + bot_cards：CardKit v2 流式卡片（v0.11.0 CARD-01）+ create_chat 建群（v0.11.0 GROUP-01 CreateGroupChatNode）。
- `server/agents/chat_runner.py` + `agents/tools/`：AI 会话可调工具封装。
- `server/delivery/`(WorkItem)：子看板 work_item 落库。
- `.planning/feature-list-demo.md`：82KB 富文档抽取测试样本。

### Established Patterns
- 工作流节点：inputs/outputs ports + NodeResult，自动注册 + AI 会话可调。
- CardKit 流式：create_card_entity → send → stream_card_content → settle（sequence 递增）。
- 建群即拉人单步（FeishuIMService.create_chat）+ writeback feishu_chat_id（INV-6）。

### Integration Points
- feature list 输入复用 Phase 83 飞书文档回拉（飞书链接源）。
- 拆分结果 work_item 关联项目（Phase 82 ProjectWorkItemLink）。
- 下游 Phase 88 消费拆分看板做仓库关联。

</code_context>

<specifics>
## Specific Ideas

- 多源输入（用户明确：文件 + 飞书链接 + 文本三种都要）。
- 复用项目群（用户明确：不是每次拉新群）。

</specifics>

<deferred>
## Deferred Ideas

- 产品在系统内对话产出 feature list（PROJX-06，v2）——本期用外部产出的 feature list。

</deferred>

<canonical_refs>
## Canonical References

- `.planning/project-workspace/MILESTONE-PROPOSAL.md` — §8 交付流水线（1 看板拆分 / 2 拉群卡片）、§10 调研结论（work_item create+父子）
- `.planning/REQUIREMENTS.md` — BOARD-01/02
- `.planning/ROADMAP.md` — Phase 87 Success Criteria
- `.cursor/rules/observability-logging.mdc` — call_source/脱敏强制项

</canonical_refs>
