# Phase 88: 智能业务关联仓库 - Context

**Gathered:** 2026-06-26
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous) — 用户逐 Wave 选定

<domain>
## Phase Boundary

基于 feature list + 拆分看板，多轮交互式拟定并校验业务↔仓库关联：知识库（活跃度/功能梳理）+ RAG 多轮 + Agent 自处理 → 卡片引导式多轮澄清/确认 → 用户确认后逐仓自校验 → 最终卡片确认。

交付需求：REPO-01/02。
</domain>

<decisions>
## Implementation Decisions

### 候选仓库排序依据
- **语义相关度 + 仓库活跃度 综合打分**：结合知识库（活跃度/功能梳理）+ RAG 多轮检索，对候选仓库综合打分排序。
- Agent 自处理 + 发卡片引导式多轮澄清/确认涉及仓库（含用户自校验）。

### 确认后逐仓自校验深度
- **开 claude code task（容器化 agent）深入验证**：用户确认仓库后，对每个仓库**派 claude code task**（容器内运行编码 agent）深入仓库代码验证业务适配性，而非仅元数据/README 匹配。
- 自校验发现不符 → 可回退重确认。
- 校验完成 → 最终卡片确认。
- 容器任务复用 v0.12 durable + v0.8 dispatch；带 `initiated_by_user_id`；新增 LLM/召回埋点（call_source + RetrievalTrace）。

### 交互回路（REPO-01/02）
- 卡片引导式多轮澄清（CardKit）；用户确认仓库 → 逐仓 claude code task 自校验 → 最终卡片确认。
- 全程 fail-soft，单仓校验失败不阻断其余。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/services/git_platform/`：仓库元数据/活跃度。
- `server/services/` context packer + `server/knowledge/`：RAG 多轮 + 功能梳理。
- `server/agents/chat_runner.py` + `agents/tools/`：Agent 自处理。
- `server/services/feishu_im.py` + bot_cards：卡片引导多轮澄清/确认。
- `task/`(claude-agent-sdk runner) + `server/resumable/`(durable) + v0.8 多仓 dispatch：claude code task 逐仓自校验。
- v0.7/v0.8 RepoRouter（仓库路由）：本期增强为知识库+RAG+卡片 HITL。

### Established Patterns
- 多仓 wave 编码 dispatch + callback resume（v0.8）。
- 卡片 HITL 多轮（v0.11 CardKit）。
- RAG 多仓 fail-closed + RetrievalTrace 埋点。

### Integration Points
- 消费 Phase 87 拆分看板结果（feature → 子看板）。
- 输出仓库关联确认 → Phase 89 技术方案深化输入。

</code_context>

<specifics>
## Specific Ideas

- 用户明确"可以开个 claude code 的 task"做逐仓自校验——比纯 RAG 更重更准，深入仓库代码验证业务适配。

</specifics>

<deferred>
## Deferred Ideas

- None — 讨论保持在 phase scope 内。

</deferred>

<canonical_refs>
## Canonical References

- `.planning/project-workspace/MILESTONE-PROPOSAL.md` — §8 交付流水线（3 智能仓库关联）
- `.planning/REQUIREMENTS.md` — REPO-01/02
- `.planning/ROADMAP.md` — Phase 88 Success Criteria
- `.cursor/rules/observability-logging.mdc` — call_source/RetrievalTrace/initiated_by_user_id 强制项

</canonical_refs>
