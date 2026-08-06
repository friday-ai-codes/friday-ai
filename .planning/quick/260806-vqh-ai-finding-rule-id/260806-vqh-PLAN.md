---
quick_id: 260806-vqh
slug: ai-finding-rule-id
description: AI 审查 finding 的 rule_id 前缀汉化成中文标签
date: 2026-08-06
status: planned
---

# Quick Task 260806-vqh：AI 审查 finding 的 `[rule_id]` 前缀汉化

## 问题

AI 审查线程的首条消息形如 `[acceptance_uncovered] 当前节点轻高亮引导仅在 …`。
`detail` 正文本来就是中文，唯独开头那个 snake_case 的 `rule_id` 是给机器看的，
评审人读起来割裂。全量 22 个 rule_id 都有这个问题。

## ⛔ 不能改后端那行

`BlueprintThread` **没有 `rule_id` 字段**，跨轮去重靠正则从线程首条消息把它反查回来：

```python
_RULE_ID_TAG = re.compile(r"^\[([A-Za-z0-9_]+)\]")
```

`blueprint_review.py:2064` 写入 `question=f"[{finding['rule_id']}] {finding['detail']}"`，
`_aload_finding_threads` 再按这个前缀建 `{dedupe_key: thread}` 索引。把它换成中文，正则
（只接受 `[A-Za-z0-9_]+`）立刻失配 ⇒ 第二轮起既拿不到「第 N 轮仍存在」留痕、也不进
「本轮已消失 → resolve」的收尾循环 ⇒ **一条 open+blocking 的 BLOCKER 永久挡住 confirm**。
这正是 `check_gate_lock` docstring 用两段篇幅写下的事故形态（114-MN-03）。

⇒ **汉化做在展示层**。附带好处：历史线程（本项目现有 45 条）一并生效，⛔ 无需数据迁移。

## 方案

新增 `web/src/utils/blueprintFindingRules.ts`：前缀正则与后端**逐字同款**，解析出
`{ruleId, text}`；22 个已知 rule_id 走 i18n 中文标签，未知 id **回落原样显示**（⛔ 不吞）。

渲染侧把 rule_id 提成一枚徽标，正文只留 `detail`：

```text
[acceptance_uncovered] 当前节点轻高亮引导仅在 …
  ↓
(验收标准未覆盖) 当前节点轻高亮引导仅在 …
```

中文前缀（`[已修复]` 等）匹配不上该正则，天然保持原样 —— 这是沿用后端字符集的另一个收益。

## 标签表（22 条，逐条对齐后端 detail 语义）

| rule_id | 标签 | 来源 |
|---|---|---|
| `acceptance_uncovered` | 验收标准未覆盖 | LLM |
| `truth_unsupported` | 验收锚点无支撑 | LLM |
| `key_link_broken` | 关键链路断裂 | LLM |
| `constraint_conflict` | 与约束冲突 | LLM |
| `goal_backward_unavailable` | 逆向核对未执行 | 降级 meta |
| `precondition_missing` | 缺前置段落 | 规则① |
| `schema_version_missing` | 缺结构版本 | 规则① |
| `schema_invalid` | 结构校验未通过 | 规则① |
| `citation_missing` | 关键结论缺引用 | 规则② |
| `citation_missing_weak` | 断言缺引用 | 规则② |
| `role_mismatch` | 仓库角色不符 | 规则③ |
| `capability_unreferenced` | 依赖能力未被引用 | 规则③ |
| `api_ref_dangling` | 接口引用悬空 | 规则④ |
| `support_repo_missing` | 缺协作仓 | 规则④ |
| `forbidden_schedule` | 含排期表述 | 规则⑤ |
| `out_of_scope_introduced` | 引入范围外内容 | 规则⑤ |
| `constraint_ref_dangling` | 约束引用悬空 | 规则⑤ |
| `charter_violation` | 违反仓库章程 | 规则⑥ |
| `charter_boundary_risk` | 触碰章程边界 | 规则⑥ |
| `gate_lock_violation` | 偏离确认门锁定 | 门锁 |
| `gate_lock_violation_role` | 偏离锁定·角色 | 门锁 |
| `gate_lock_violation_responsibility` | 偏离锁定·职责 | 门锁 |

## Tasks

### 1. 解析工具 + 标签文案

- files: `web/src/utils/blueprintFindingRules.ts`、`web/src/locales/zh-CN.json`
- action: `parseFindingRule(body)` → `{ruleId, text}`；`isKnownFindingRule(id)`；
  i18n 加 `knowledge.blueprints.thread.rule.*` 共 22 键。
- verify: `pnpm vitest run src/utils/__tests__/blueprintFindingRules.test.ts`
- done: 有前缀剥离、无前缀原样、中文前缀不误剥、未知 id 回落四类行为。

### 2. 两个渲染点接上

- files: `web/src/components/blueprint/BlueprintThreadCard.vue`、
  `web/src/components/blueprint/BlueprintBlockedDialog.vue`
- action: 线程卡消息行加规则徽标、正文用剥离后的 `text`（折叠阈值同步改用 `text` 长度）；
  阻断弹窗的 40 字摘要改成「标签：正文」，不再被 22 字的 UUID 式前缀吃掉。
- verify: `pnpm vitest run src/components/blueprint`
- done: 页面上看不到 `acceptance_uncovered` 这类裸 id。

### 3. 回归用例

- files: `web/src/utils/__tests__/blueprintFindingRules.test.ts`、
  `web/src/components/blueprint/__tests__/threadSidebar.spec.ts`
- action: 工具单测 + 线程卡断言「渲染中文标签且裸 id 不出现」。
- verify: `pnpm vitest run src/utils src/components/blueprint`
- done: 新增用例全绿，既有用例不回归。

## must_haves

- truths:
  - 线程卡上 `[acceptance_uncovered]` 显示为「验收标准未覆盖」徽标，裸 id 不出现
  - 未知 rule_id 原样显示，⛔ 不被吞掉
  - `[已修复]` 等中文前缀不被误剥
  - ⛔ 后端 `question=f"[{rule_id}] …"` 与 `_RULE_ID_TAG` 一行未改，跨轮去重不受影响
- artifacts:
  - `web/src/utils/blueprintFindingRules.ts`
  - `web/src/locales/zh-CN.json` 的 `knowledge.blueprints.thread.rule`
- key_links:
  - `BlueprintThreadCard.vue` → `parseFindingRule`
  - `BlueprintBlockedDialog.vue` → `parseFindingRule`
