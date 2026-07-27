---
phase: quick-260727-het-friday-routing-feature-list-prd
plan: 01
status: complete
subsystem: skills
tags: [agent-skills, repo-routing, feature-list, docs]
requires: [skills submodule @488d9c4, TOOL_SCHEMA_SNAPSHOT]
provides: [friday-routing skill, 7-skill integration surface]
affects: [skills/, docs/integrations/skills.md, task/assets/skills/friday-code/]
tech-stack:
  added: []
  patterns: [zh-CN agent skill, 阶段分节骨架, HTTP 兜底 reference]
key-files:
  created:
    - skills/skills/friday-routing/SKILL.md
    - skills/skills/friday-routing/references/http-fallback.md
  modified:
    - skills/skills/friday/SKILL.md
    - skills/skills/friday-solution/SKILL.md
    - skills/skills/friday-code/SKILL.md
    - skills/lib/installer.mjs
    - skills/.claude-plugin/plugin.json
    - skills/README.md
    - docs/integrations/skills.md
    - task/assets/skills/friday-code/SKILL.md
decisions:
  - 纯 agent 驱动，不走 friday-solution 的三段式服务端编排
  - 产物只有七列路由矩阵，不出伪代码/模块详设/完整方案
  - friday-routing 刻意不进 task 容器，SKILL_NAMES 未扩展
metrics:
  duration: ~35min
  completed: 2026-07-27
---

# Quick Task 260727-het: 新增 friday-routing 技能 Summary

把「仓库路由 / 架构落点判定」从 `friday-solution` 的服务端黑盒里拆出来，做成纯 agent 驱动的 `friday-routing` 技能：输入 feature list / PRD，输出七列路由与落点判定矩阵，过程与证据全透明。

## friday-routing 最终章节骨架

```text
frontmatter（只有 name + description）
# Friday Routing
## 前置门槛                       —— MCP 不可用 / 401-403 → mcp setup；全程保留 run_id
## 铁律：纯 agent 驱动             —— 自编排原子工具、证据透明、澄清自己发起，不走三段式
## 取数源                         —— 四选一：当前 git 分支 / project_id / 贴的原文 / 本地文档
## 阶段一 — 索引健康度与候选仓收敛   （维度 8、1）
## 阶段二 — 落点下钻               （维度 2、3、4）
## 阶段三 — 跨仓依赖               （维度 5）
## 阶段四 — 影响面与历史           （维度 6、7）
## 阶段五 — 置信度定级与批量澄清     （维度 9 + 澄清协议四条）
## 阶段六 — 输出路由矩阵           —— 唯一产物
## 阶段七 — 结论沉淀               —— report_project_knowledge，按分支定位，fail-soft
## 护栏
## 与其它技能的边界
## HTTP 兜底                       —— 链接 references/http-fallback.md
```

### 矩阵七列定义

| 列 | 含义 |
| --- | --- |
| 功能点 | feature list / PRD 里的一条，编号对齐用户确认过的颗粒度 |
| 目标仓库 | monorepo 必须下钻到子应用（`ranked_repos[].sub_project`） |
| 落点（目录/文件） | 真实路径；判 new 时给建议目录并注明参照的同类结构 |
| 变更类型 | `new` / `modify` / `unclear` |
| 证据 | 真实文件路径或 chunk，来自工具返回而非推理 |
| 置信度 | high / medium / low（判据表写进阶段五） |
| 风险与跨仓依赖 | `reverse_lookup_requirements` 反查的回归面 + 接口契约另一侧 |

矩阵后附 `run_id`、涉及仓库清单、`new`/`modify`/`unclear` 计数、待澄清项编号。

## 7 处接入面实际改法

| 文件 | 改法 |
| --- | --- |
| `skills/skills/friday/SKILL.md` | 决策门新增 **4.4** 问（要矩阵走 routing / 要完整方案走 solution，与 4.5 显式区分）；技能路由表在 `friday-solution` 行**之前**插入 routing 行；直通模式意图分流句补 routing 分支 |
| `skills/skills/friday-solution/SKILL.md` | 边界表新增「只要路由与落点矩阵」→ `friday-routing`；表下补一句 routing 是其**上游**，矩阵可作第二步确认关联仓库的输入依据 |
| `skills/skills/friday-code/SKILL.md` | 阶段一护栏之后补一段：单需求走本阶段，成批功能点走 `friday-routing` |
| `skills/lib/installer.mjs` | `bootstrapBody` 技能清单 6 → 7；决策门新增第 5 条 routing 规则，原第 5/6 条顺延为 6/7 |
| `skills/.claude-plugin/plugin.json` | 只改 `description`：`6 skills` → `7 skills`，清单加 friday-routing，能力枚举补英文 routing 段落。`version` / `hooks` / `mcpServers` 未动 |
| `skills/README.md` | `## Skills（5 个）` → `（7 个）`，补 `friday-solution`（**既有缺口**）与 `friday-routing` 两行；「设计」5 → 7；「本地验证」注释 5 → 7；安装向导描述 5 → 7 |
| `docs/integrations/skills.md` | `6 个职责清晰的 skill` → `7 个`；表格在 `friday-dev` 与 `friday-solution` 之间插入 routing 行；「安装之后」路由句补 routing 分流。既有「33 个工具 / 30 个工具」计数不一致按计划**未动** |

## friday-code 镜像重同步的原因

`task/tests/test_skills_injection.py::TestSkillsHashConsistency` 逐文件 sha256 守卫 `task/assets/skills/{friday-code,friday-memory}/` 与子模块源目录一致。本次改了 `skills/skills/friday-code/SKILL.md`，不重跑 `python task/scripts/sync_skills.py` 就会双源漂移、CI 直接红。脚本原样执行（`SKILL_NAMES` **未扩展**），只重建了 `friday-code` / `friday-memory` 两个镜像——`friday-routing` 刻意不进容器：容器里跑的是编码 agent，routing 是 IDE / CLI 侧的调研技能。

## 验证结果

| 命令 | 结果 |
| --- | --- |
| `cd server && uv run pytest tests/mcp_tools/test_skills_snapshot_guard.py tests/mcp_tools/test_schema_snapshot.py -q` | 5 passed |
| `cd task && uv run pytest tests/test_skills_injection.py -q` | 6 passed |
| `node skills/bin/friday-ai-skills.mjs list` | 打包技能（7 个）：friday / friday-code / friday-dev / friday-feishu / friday-memory / friday-routing / friday-solution |

`server/mcp_tools/serializers.py` 零改动（`git status` 确认），`TOOL_SCHEMA_SNAPSHOT` 未漂移。

## 人工抽查结论

- **不含三段式工具**：`grep -E "create_feature_tech_plan|confirm_feature_tech_plan|get_feature_tech_plan"` 在 SKILL.md 与 http-fallback.md 上零命中。
- **不承诺越界产物**：护栏明写「不出伪代码、不出模块详细设计、不出完整技术方案文档」，并在边界表把这三类需求分流到 `friday-solution` / `friday-code`。
- **澄清协议四条齐备**：批量问 / 每题给具体选项 / 标推荐项与理由 / 答复前不拍板，且附了带推荐理由的选项式提问示例。
- **9 个调研维度全部落点**：仓库(阶段一)、落点(二)、变更类型(二)、证据(二+护栏)、跨仓依赖(三)、影响面(四)、历史(四)、索引健康度(一)、置信度(五)。
- **无明文凭证**：curl 示例一律 `${FRIDAY_BASE_URL}` / `${FRIDAY_ACCESS_TOKEN}` 占位；护栏明写绝不回显或上报 Access Token / 密钥 / 个人敏感信息。
- **工具名合规**：SKILL.md 反引号包裹的工具名全部来自 `TOOL_SCHEMA_SNAPSHOT` 键集，无自造工具名。

## 可观测性规范判定

本任务为纯文档 / 技能编写，**未新增或修改任何 API / 工作流节点 / 服务 / 任务 / webhook / 工具 / LLM 调用 / 召回**，无埋点面变更。`.cursor/rules/observability-logging.mdc` 的日志与指标条目本次**不适用**。

## Deviations from Plan

**1. [Rule 3 - 阻塞] 子模块本地 `main` 落后 origin/main 两个提交**
- **Found during:** Task 1 第 0 步
- **Issue:** `git -C skills switch main` 后 HEAD 落到 `17d2aaa`，而主仓子模块指针与 `origin/main` 都在 `488d9c4`。直接在此提交会让主仓指针**回退**，丢掉 `friday-solution` 技能。
- **Fix:** `git -C skills merge --ff-only origin/main` 快进到 `488d9c4` 后再开工。
- **Commit:** 无独立提交（分支操作）

其余按计划执行。

## Git 提交

| 仓库 | Hash | Message |
| --- | --- | --- |
| `skills/`（子模块，main） | `dc3b012` | `feat(friday-routing): 新增基于 feature list/PRD 的仓库路由与落点判定技能` |
| `skills/`（子模块，main） | `755aae2` | `docs(skills): 接入面同步 friday-routing 并补齐 README 技能表` |
| 主仓（main） | `b02bf9ce` | `feat(skills): 新增 friday-routing 技能并同步接入面与文档` |

`git -C skills status --branch` → `## main...origin/main [ahead 2]`，工作区干净，**不是 detached HEAD**。

## 遗留项（需用户决定）

1. **`skills/` 子模块未推远端**：`main` 领先 `origin/main` 两个提交（`dc3b012`、`755aae2`）。沿用 260726-uid 的做法，由用户自行决定何时执行 `git -C skills push origin main`。
2. **npm 包未发版**：本次未动 `.claude-plugin/plugin.json` 的 `version`（仍为 `0.5.0`）与 `package.json`。要让 `npx @friday-ai-codes/skills` 装到 `friday-routing`，需要用户决定何时 bump 版本并 `npm publish --access public`。
3. **`docs/integrations/skills.md` 的「33 个工具 / 30 个工具」计数不一致**：历史遗留，按计划本次未动，可另开任务修。

## Self-Check: PASSED

- `skills/skills/friday-routing/SKILL.md` — FOUND
- `skills/skills/friday-routing/references/http-fallback.md` — FOUND
- `task/assets/skills/friday-code/SKILL.md` — FOUND（sha256 与源一致）
- 提交 `dc3b012` / `755aae2`（子模块）、`b02bf9ce`（主仓）— 均 FOUND
