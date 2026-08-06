---
quick_id: 260806-dys
slug: markdown-md
status: complete
date: 2026-08-06
---

# Quick 260806-dys 总结：功能点节点名去 markdown 标记

## 交付

| 层 | 改动 |
|----|------|
| 前端工具 | 新增 `web/src/utils/markdownText.ts`：`mdTokensToPlainText`（markdown-it token 流取文字）+ `stripMarkdownSync`（渲染器就绪前同步兜底） |
| 前端组件 | `InlineMarkdown` 新增 `plain` 模式；`FeatureBoard` 模块/功能点/验收项名与 `FeatureDetailModal` 标题改用纯文本 |
| 后端 | `feature_list_import.py` 新增 `_clean_node_name`，接入 `_materialize_modules` / `_materialize_features` / `_parse_modules_json` / `agenerate_module_outline` |

## 关键决策

- **只清洗名称**：`acceptance` 与 `source` 保持逐字原文（解析契约要求可回溯），
  展示层需要时再剥壳。
- **不做数据 migration**：存量节点名靠展示层剥壳即可；且 `work_item_index` 以名称为
  匹配键，改存量名会打断已建工作项关联。
- **同步兜底与 token 解析双路径**：token 流是权威结果，同步路径只为消除首帧闪烁，
  测试要求两者对同一输入给出相同结果。
- markdown-it 未启用 task-list 插件，`[ ]` 会留在 inline token 文本里，token 路径
  额外剥一次任务框。

## 验证

- 前端 `vitest`：46 passed（`markdownText` 24 + warroom 组件套件）
- 后端 `pytest`：`test_feature_list_import_parse.py` 23 passed；
  `test_feature_list_api/draft/extractor` 16 passed
- `vue-tsc --noEmit` 通过；`eslint` / `ruff check` / `ruff format` 干净

## 备注

- `pytest tests/initiatives/` 全量一度卡死，原因是本机 `make dev` 占用 `test_friday`
  测试库（teardown 报 “being accessed by other users”），与本次改动无关；按文件分批跑全绿。
- 可观测性：纯展示/解析归一，无新调用入口与 LLM 调用，未新增埋点。
- 未提交（用户未要求）。
