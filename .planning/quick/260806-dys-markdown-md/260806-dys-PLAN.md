---
quick_id: 260806-dys
slug: markdown-md
status: complete
date: 2026-08-06
---

# Quick 260806-dys：功能点节点名残留 markdown 标记

## 问题

项目作战室右栏 Feature 大盘里，部分功能点名显示成 `#### 功能点 A：页面结构…`，模块名同理会带 `##`。

## 根因（两层）

1. **数据层** — `server/initiatives/services/feature_list_import.py::_materialize_features`
   在 LLM 只给 `name_line`（行号）时走 `_slice_lines` **按行号裁原文**，整行连着
   `#### ` / `- [ ] ` 一起存进节点名，没有任何剥壳。同一份文档里 LLM 有时给干净的
   `name`、有时给 `name_line`，这正是「模块 1 干净、模块 3 带 `####`」的原因。
2. **展示层** — `web/src/components/common/InlineMarkdown.vue` 用 `md.renderInline()`。
   `renderInline` 按设计**只解析行内语法**，ATX 标题、列表、引用这些块级标记不参与解析，
   于是原样显示。

## 方案

| # | 任务 | 文件 |
|---|------|------|
| 1 | 新增 markdown → 纯文本工具：markdown-it token 流为主，同步剥壳兜底（避免首帧闪 `####`） | `web/src/utils/markdownText.ts` |
| 2 | `InlineMarkdown` 加 `plain` 模式；大盘模块/功能点/验收项名与详情弹窗标题改纯文本 | `InlineMarkdown.vue` / `FeatureBoard.vue` / `FeatureDetailModal.vue` |
| 3 | 后端解析时清洗**名称**的 markdown 标记，新数据不再带标记 | `feature_list_import.py` |

## 边界

- **只清洗名称**：验收项与 `source` 原文仍逐字保留（解析契约要求可回溯原文），
  展示层按需剥壳。
- 存量数据不做 migration：展示层剥壳即可，且 `work_item_index` 按名称匹配，
  改存量名会打断已建工作项的关联。
- 可观测性：纯展示/解析归一，无新调用入口、无新 LLM 调用 → 不新增埋点。
