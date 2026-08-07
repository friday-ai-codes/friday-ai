---
task: friday-subagents
status: complete
completed: 2026-08-08
---

# Summary: Friday 技术方案 subagent 定义与分发

## 做了什么

把 Friday 的技术方案编排能力做成宿主 agent（Claude Code / Cursor）可自动委托的
subagent，对齐业界 subagent 最佳实践（单一职责、最小工具白名单、description 驱动
自动委托、一次性无状态调用、用户决策结构化带回而非代答）。

## 交付物

- `skills/agents/friday-plan.md`：技术方案编排专员 subagent。canonical Claude Code
  格式（`tools:` 白名单限定 `mcp__friday__*` 方案链工具 + Read/Bash）。覆盖两条链：
  feature tech plan 三段链（发起段返回 questions + session_id 即止 → 主对话确认 →
  续跑段 confirm + 轮询到终态）与飞书蓝图澄清链（取件 → 逐条作答 → 续取终稿）。
  五条铁律：不代答、不跳步、一次性调用、不编造、不回显凭证。
- `skills/agents/friday-research.md`：只读交付上下文调研专员 subagent（17 个只读
  工具白名单），消化召回结果后返回带 ID 出处的证据摘要。
- 安装器：`lib/agents.mjs` 增加 cursor/claude-code 的 subagent 目录约定与
  `subagentsDirFor`/`supportsSubagents`；`lib/installer.mjs` 增加 `bundledSubagents`
  / `transformSubagent`（Cursor 变体剥离 tools/color/effort/model 键）/
  `installSubagentsForAgent`；`bin/friday-ai-skills.mjs` 接入安装流程、list 输出与
  向导提示；`package.json` files 增加 `agents/`、版本 0.6.0 → 0.7.0；
  `.claude-plugin/plugin.json` 增加 `"agents": "./agents"`（插件形态自动带上）。
- 文档：`skills/README.md` 新增「Subagents（2 个）」一节；`friday/SKILL.md` 新增
  「Subagent 委托」一节；`friday-solution/SKILL.md` 新增委托三步；
  `friday-feishu/SKILL.md` 补蓝图异步澄清协议；`mcp/README.md` 更新配套说明。

## 验证

- `node bin/friday-ai-skills.mjs list`：8 技能 + 2 subagent 正常列出。
- `npm run pack:dry-run`：tarball 含 `agents/friday-plan.md`、`agents/friday-research.md`。
- 沙箱 `install --project --agent cursor --agent claude-code`：`.cursor/agents/`
  变体无 tools/color 键、`.claude/agents/` 保留完整 frontmatter，技能安装不受影响。

## 决策记录

- subagent 数量收敛为 2（plan + research），不做 per-chain 细分——业界共识是少量
  高内聚 subagent 优于一堆细碎定义。
- 确认/澄清环节永远留在主对话：subagent 是一次性无状态调用，无法与用户交互，
  设计上以「原样带回待确认项」代替任何形式的代答。
- Codex / Gemini CLI / OpenCode 无原生 subagent 机制：安装器自动跳过，由 skill
  正文引导主 agent 直接驱动，流程与护栏一致。
- MCP server（`mcp/`）本次不动代码：现有 pending/轮询/作答工具形状已与 MCP Tasks
  扩展（2026-07-28 spec，`io.modelcontextprotocol/tasks`）语义对齐，待 Tier 1 客户端
  支持后再在 stdio server 做标准 Tasks 映射（服务端 DelegateResult 无需改动）。
