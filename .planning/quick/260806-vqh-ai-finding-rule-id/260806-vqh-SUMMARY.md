---
quick_id: 260806-vqh
slug: ai-finding-rule-id
description: AI 审查 finding 的 rule_id 前缀汉化成中文标签
date: 2026-08-06
status: complete
---

# Quick Task 260806-vqh — 摘要

**One-liner:** AI 审查线程首条消息的 `[acceptance_uncovered]` 这类 snake_case 前缀，在
**展示层**剥出来换成「验收标准未覆盖」中文徽标 —— ⛔ 后端那行一个字没动，因为它是跨轮去重
的机器索引；汉化落在前端还顺带让历史线程零迁移生效。

## 改了什么

| 文件 | 改动 |
|------|------|
| `web/src/utils/blueprintFindingRules.ts` | 新增：`parseFindingBody` 前缀解析 + `FINDING_RULE_IDS`（22 条）+ `isKnownFindingRule` |
| `web/src/locales/zh-CN.json` | 新增 `knowledge.blueprints.thread.rule.*` 共 22 条标签 |
| `web/src/components/blueprint/BlueprintThreadCard.vue` | 消息行加规则徽标（原始 id 落 `title`），正文用剥离后的 `text`，折叠阈值同步 |
| `web/src/components/blueprint/BlueprintBlockedDialog.vue` | 40 字摘要先剥前缀再截断，已知规则拼「标签：正文」 |
| `web/src/utils/__tests__/blueprintFindingRules.test.ts` | 新增：解析四类行为 + i18n 漂移守卫 |
| `web/src/components/blueprint/__tests__/threadSidebar.spec.ts` | 新增 10a/10b/10c 三条线程卡用例 |

## ⛔ 为什么不改后端

`BlueprintThread` **没有 `rule_id` 字段**。跨轮去重靠正则从线程首条消息把它反查回来：

```python
_RULE_ID_TAG = re.compile(r"^\[([A-Za-z0-9_]+)\]")
```

`blueprint_review.py:2064` 写 `question=f"[{rule_id}] {detail}"`，`_aload_finding_threads`
按这个前缀建 `{dedupe_key: thread}` 索引。换成中文 ⇒ 正则失配 ⇒ 第二轮起既拿不到
「第 N 轮仍存在」留痕、也不进「本轮已消失 → resolve」的收尾循环 ⇒ **一条 open+blocking
的 BLOCKER 永久挡住 confirm，只能人工 dismiss**。这是 `check_gate_lock` docstring 用两段
篇幅记录的 114-MN-03 事故形态。

展示层汉化因此不只是「更省事」，而是**唯一不破坏索引的做法**；附带收益是历史线程
（本项目现有 45 条带前缀消息）无需数据迁移即刻生效。

## ⚠️ 一个跨语言陷阱

后端写的是显式字符类 `[A-Za-z0-9_]+` 而**不是** `\w+` —— Python 的 `\w` 是 Unicode 感知的、
**会匹配中文**，用它会把 `[已修复]` 这类人工处置留痕也当成规则标记。JS 的 `\w` 恒等于
ASCII `[A-Za-z0-9_]`，所以前端用 `\w`（ESLint `regexp/prefer-w` 要求）与后端等价，
但⛔ 反向移植时不可把 `\w` 直接搬回 Python。这条写进了模块 docstring。

## 效果

```text
[acceptance_uncovered] 当前节点轻高亮引导仅在 M3-unlock-state 描述中带过…
  ↓
AI  16:04  (验收标准未覆盖)
当前节点轻高亮引导仅在 M3-unlock-state 描述中带过…
```

未知 rule_id 回落原始 id 显示（⛔ 不吞掉分类）；`[已修复] …`、`第 2 轮仍存在：…` 这类
本就是人话的消息不渲染徽标、正文原样。

## 验证

**真实数据实测** —— 蓝图 `5b650e1a-2939-4aa9-90a1-1297c0aaead9` 的 158 条线程消息：
45 条带规则前缀且**全部命中中文标签、0 条未覆盖**，113 条无前缀消息原样不变。
出现的四类规则分别是 `acceptance_uncovered`(33) / `key_link_broken`(5) /
`citation_missing`(4) / `truth_unsupported`(3)。

**用例** —— 新增 30 条工具单测（含 22 条 i18n 漂移守卫参数化）+ 3 条线程卡组件用例；
`src/components/blueprint` 与 `src/utils` 合计 565 passed，`src/pages/knowledge` 42 passed。
`eslint` 与 `vue-tsc --noEmit` 均无本次引入的问题。

## 遗留

`BlueprintThreadCard.vue` 有两条既有的 tailwind 提示（`break-words` → `wrap-break-word`），
在本次未触碰的类名上，不在本任务范围内。
