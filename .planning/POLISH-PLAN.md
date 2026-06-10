# 项目打磨计划（去 AI 味专项）

> 来源：2026-06-10 全仓审查（文档/Skills、后端、前端三路），目标是把项目从"流水线产出感"打磨成"有人负责感"。
> 原则：**打磨以减法和对齐为主，不引入新功能**。每项都有验收标准，做完一项勾一项。

## 进度

- [x] **P0-1 口径对齐** — 完成（quick 260611-0pm，commit 6ed6bccf8）
- [x] **P0-2 痕迹清洗（第一层）** — 完成（commit 0c63f0de2）：冒号前缀标记 734 行 + 个人路径泄漏 10+ 处
- [ ] **P0-2b 深层痕迹** — 新增遗留项：约 900+ 行无冒号的 `work item` / `per contract` 中缀引用，需按语义逐条改写
- [x] **P2-7 社区脚手架** — 完成（commit 7f0c43818）
- Star History：用户决定**保留**（原计划删除项作废）

## 总体诊断

项目已避开低级 AI 味（无 emoji 标题、无营销词、测试 516 个非占位、CI 完整）。剩余 AI 味来自四个深层信号：

1. 对外口径互相打架（文档与交付物脱节）
2. 内部 GSD 工作流痕迹泄漏到源码、测试和 git 历史
3. 巨型一次性生成文件（无人回头读过的形状）
4. 半接线的基础设施（装了不用的 i18n、不维护的 CHANGELOG）

---

## P0-1 全仓口径对齐验收 ｜ 工作量 1-2 天 ｜ 纯文档改动

AI 多轮迭代的标志性病症：每轮生成都对，拼起来是错的。

### 任务清单

- [ ] **统一 Skills 叙事**（最高优先）
  - 现状：三套口径打架
    - `docs/integrations/skills.md` 写 3 个聚合 skill（`friday-ai` / `friday-codebase-agent` / `friday-feishu-agent`）
    - `skills/README.md` 实际是 12 个原子 skill（`using-friday`、`friday-setup`、`friday-discover` … `friday-feishu-auto`）
    - `README.md`（131、222 行附近）和 `mcp/README.md`（42-45 行）主推 `npx skills add friday-ai-codes/skills --skill friday-codebase-agent`，**该 skill 目录已不存在**
  - 动作：决定主推口径（建议 12 原子 skill + 1 个入口 skill 的真实结构），全仓改齐 `README.md`、`README.en.md`、`docs/integrations/skills.md`、`docs/guide/friday-codebase-agent.md`、`mcp/README.md`、`skills/README.md`
  - 验收：`npx skills add ... --skill X` 中每个 `X` 在 `skills/skills/` 下真实存在
- [ ] **修正 `full_auto` 描述**
  - 现状：`docs/guide/friday-codebase-agent.md:62` 把 `full_auto` 描述成飞书链路；实际 `skills/skills/friday-auto/SKILL.md` 是纯编码端到端，飞书链路在 `friday-feishu-auto`
  - 验收：每个 workflow 描述与对应 SKILL.md 的定义一致
- [ ] **README Quick Start 补 `git clone`**
  - 现状：README 快速开始直接从 `scripts/setup.sh` 开始；`docs/guide/quick-start.md` 才有 clone 步骤
  - 动作：README 的 Quick Start 与 CI `open-source-smoke` job 的真实步骤对齐；中英 README 同步改
  - 验收：陌生人从 README 第一行复制粘贴可跑通
- [ ] **处理化石 `server/README.md`**
  - 现状：写着 Django 6.0、SQLite、emoji 分节（🛠️🚀📁🔐📡🐳），与真实栈（Django 5.1+、PostgreSQL）冲突
  - 动作：重写为简短的开发指引（指向主文档），或直接删除
- [ ] **对齐 CONTRIBUTING 与 commit checker**
  - 现状：`CONTRIBUTING.md` 说"不要用 scope"，`scripts/check_commit_messages.sh`（40、64 行）允许 `feat(scope):`，近期提交全带 scope
  - 动作：承认 scope（改 CONTRIBUTING），三者（CONTRIBUTING / checker / 实际习惯）统一
- [ ] **消除 README 与 docs 的逐字重复**
  - 现状："它能做什么"表格、"飞书深度集成"表格、Graph RAG 对比表在 README 和 `docs/guide/introduction.md`、`docs/internals/code-intelligence.md` 重复维护
  - 动作：README 只留 elevator pitch + 链接，细节只在 docs 维护一份
- [ ] **删 Star History 图表**（README 250-258 行附近）——年轻仓库放这个是增长黑客模板感

## P0-2 过程痕迹清洗 ｜ 工作量 0.5-1 天 ｜ 注释级改动

GSD 工作流的内部话语泄漏到了公开产物里，读者一眼识别出"agent 流水线产物"。

### 任务清单

- [ ] **清洗测试 docstring 的计划话语**
  - 已知样本：`server/tests/test_git_diff_index.py:1-13`（`implementation:`、`work item:`、"遗留至 v24.0 conftest 全局 fixture 重写"）
  - 动作：`rg -l 'implementation:|work item:|遗留至 v\d' server/tests` 全量排查，改写为描述测试行为本身的 docstring
- [ ] **清洗源码注释的内部决策引用**
  - 已知样本：
    - `server/services/graph_builder.py:58、71`（`CONTEXT decisions：三态 manual / auto_after_index...`）
    - `server/codegraph/views.py:505`（`per CONTEXT decisions implementation`）
  - 动作：保留 why（为什么不加锁、为什么三态），删掉对内部文档的引用
- [ ] **叙述式注释清理（顺手做）**
  - 已知样本：`server/identity/views.py:268` `# 获取用户信息`、`services/feishu.py:166、171、351、459`、`services/indexer.py:1280、1290、3357`
  - 动作：只复述下一行代码的注释直接删；有信息量的保留
- [ ] **git 历史卫生（向前生效，不改历史）**
  - 现状：main 历史有 `docs(quick-260610-qmv): ... plan/summary/state` 这类私有 workflow ID 提交
  - 动作：约定 `quick-*` / phase ID 不进 main 的 commit message（用 squash 或改 GSD 提交模板）

## P1-3 视觉证明 ｜ 工作量 0.5 天 ｜ 纯增量

- [ ] 现状：全站只有 1 张架构示意图（`docs/public/readme/how-it-works.png`），无任何 UI 截图 / GIF。"概念堆满、体验留白"是 AI 文案反模式
- [ ] 动作：补 3-5 张真实截图或 1 个 30 秒 GIF，候选场景：
  - 工作流编辑器画布（拖拽节点）
  - 执行详情页（DAG + 节点输入输出）
  - 飞书审批卡片 / 代码审查卡片实图
  - Web Chat 问代码库
- [ ] 位置：README 首屏 fold 内 + `docs/index.md` hero 区
- [ ] 同时把 `docs/index.md` 的 emoji feature grid（🔁🧠🚀 等约 20+ 处 LinkCard emoji）收敛，与 README 的克制风格统一

## P1-4 i18n 决断 ｜ 工作量：决策 0 天，迁移另立项

- [ ] 现状：vue-i18n 已装、`web/src/locales/zh-CN.json` 仅 153 行、全站只有 4 个文件用 `$t()`、412 个 vue 组件中 279 个 hardcode 中文 —— i18n 实际是死的摆设
- [ ] 决策二选一：
  - A. 删 vue-i18n，README 声明"当前中文 only，国际化在路线图"（诚实、零成本）
  - B. 立项真迁移（工作量大，建议进 v0.3 milestone，不在本次打磨范围）
- [ ] 不允许的状态：维持现状（装了不用是 AI 项目高频特征）

## P1-5 拆巨型文件 ｜ 工作量 2-3 天 ｜ 重构，需测试护航

| 文件 | 行数 | 建议拆法 |
| --- | --- | --- |
| `server/services/indexer.py` | 3562 | `indexer/qdrant.py`（8 个 `qdrant_*` helper）+ `indexer/diff.py`（`FileDiff` / `DiffAction` / `_parse_git_diff_output`）+ `indexer/service.py`（`IndexerService`） |
| `server/chat/views.py` | 2752 | 按资源拆 views 模块 |
| `server/chat/conversation_service.py` | 1911 | 按会话生命周期拆 |
| `web/src/components/chat/ChatMessageBubble.vue` | 1994（49 个函数/computed） | 按消息类型拆子组件 |
| `web/src/components/chat/ChatInput.vue` | 1526 | 拆附件 / 提及 / 工具条 |

- [ ] 优先拆 `indexer.py`（职责混杂最严重），其余视余力
- [ ] 验收：拆分前后测试全绿，公开 import 路径通过 `__init__.py` 保持兼容

## P1-6 错误信息专项 ｜ 工作量 1 天

- [ ] 现状："未知错误" 12+ 处兜底（`orchestration/coding_graph.py:161、361`、`agents/chat_runner.py:322`、`workflows/engine/scheduler.py:996、1071`、`feishu/cards/coding_result_card.py:128`、`workflows/hooks/feishu_sync.py:60、120`、`workflows/hooks/builtin.py:178`、`workflows/nodes/ai/coding.py:428`）
- [ ] 动作：逐处改成回答三件事的信息——发生了什么、可能原因、下一步做什么；飞书卡片上的报错附带可操作动作（重试 / 查看日志链接）
- [ ] 验收：用户视角不再出现裸的"未知错误"

## P2-7 社区脚手架 ｜ 工作量 0.5 天

- [ ] 补 `.github/ISSUE_TEMPLATE/`（bug report + feature request，YAML form）
- [ ] 补 `.github/PULL_REQUEST_TEMPLATE.md`
- [ ] 补 `CODE_OF_CONDUCT.md`（Contributor Covenant 即可）
- [ ] CHANGELOG 决断：每次 tag 同步维护 `CHANGELOG.md`（release.yaml 已接 git-cliff，补一步回写），或删除文件并在 README 声明"见 GitHub Releases"

## P2-8 Skills 模板收敛 ｜ 工作量 0.5 天

- [ ] 现状：12 个 SKILL.md 骨架完全相同，`Setup Gate` / `HTTP Fallback` 段落重复 N 份；`using-friday/SKILL.md` 的 "If there is even a 1% chance..." 是 agent 社区话术，偏戏剧化
- [ ] 动作：
  - `Setup Gate`、`HTTP Fallback`、`run_id` 纪律抽到共享 reference（如 `skills/skills/friday-execute/references/` 同级的 common 文档），各 skill 只写差异步骤
  - `using-friday` 的话术改为平实表述
- [ ] 注意：skills 是 submodule 独立仓库，需在对应仓库提交

---

## 不要动的（已经是加分项）

- README 开篇的购物车场景叙事、名词速查表
- `docs/` 信息架构（指南 / 部署 / internals / 集成 / API / 贡献）
- CI 流水线（path filter、gitleaks、compose smoke、Playwright、Trivy）
- 测试的真实断言风格（如 `dashboard-widgets.test.ts`）
- commit message 的认真程度（只需去掉私有 ID）

## 持续习惯

每次发版前跑一遍**陌生人测试**：假装第一次见这个仓库，从 README 第一行照着做到跑通，所有断点记入下一轮打磨清单。"细细打磨感"= 这个循环跑几十遍，没有捷径。

## 建议执行顺序

```text
第 1 批（纯减法，零风险）：P0-1 口径对齐 → P0-2 痕迹清洗 → P2-7 社区脚手架
第 2 批（小增量）：       P1-3 视觉证明 → P1-4 i18n 决断 → P2-8 Skills 收敛
第 3 批（重构）：         P1-6 错误信息 → P1-5 拆巨型文件
```
