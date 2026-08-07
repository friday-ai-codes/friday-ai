---
task: friday-subagents
created: 2026-08-08
mode: quick
---

# Quick Task: Friday 技术方案 subagent 定义与分发

## 目标

把 Friday 的技术方案编排能力做成宿主 agent（Claude Code / Cursor）可自动委托的 subagent：
本地 subagent 只当「薄壳司机」（发起 → 转达澄清 → 轮询取件），方案产出完全由 Friday 服务端
`process_runtime` 编排完成。对齐业界 subagent 最佳实践（单一职责、最小工具白名单、
description 驱动自动委托、一次性无状态调用、需要用户决策时结构化返回而非代答）。

## 交付物

1. `skills/agents/friday-plan.md` — 技术方案编排专员 subagent（canonical Claude Code 格式，
   `tools:` 白名单限定 `mcp__friday__*` 方案链工具；两段式调用协议：发起段返回待确认问题即止，
   续跑段提交确认并轮询到终态；同时覆盖 feature tech plan 三段链与蓝图澄清链）。
2. `skills/agents/friday-research.md` — 只读交付上下文调研专员 subagent（召回/检索类工具白名单，
   返回带 ID 出处的证据摘要，保持主上下文干净）。
3. 安装器支持 agents 分发：
   - `lib/agents.mjs`：cursor / claude-code 增加 agents 目录约定；
   - `lib/installer.mjs`：`bundledAgents` + `installAgentsForAgent`（Cursor 变体剥离
     Claude 专属 frontmatter：tools/color/effort）；
   - `bin/friday-ai-skills.mjs`：安装流程与 list 输出接入；
   - `package.json`：files 增加 `agents/`，版本 0.6.0 → 0.7.0；
   - `.claude-plugin/plugin.json`：增加 `"agents": "./agents"`（插件形态自动带 subagent）。
4. 文档：`skills/README.md`（Subagents 一节）、`skills/skills/friday/SKILL.md` 与
   `friday-solution/SKILL.md`（委托指引）、`mcp/README.md`（配套说明）。

## 验证

- `node bin/friday-ai-skills.mjs list` 列出技能与 subagent；
- `npm run pack:dry-run` 确认 tarball 含 `agents/`；
- 安装器在临时目录跑 `install --project --agent cursor --agent claude-code`，
  确认 `.cursor/agents/`（无 tools 键）与 `.claude/agents/`（含 tools 键）各就各位。
