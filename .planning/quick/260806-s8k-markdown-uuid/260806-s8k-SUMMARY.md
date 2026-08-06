---
quick_id: 260806-s8k
slug: markdown-uuid
description: 修复蓝图 markdown 渲染器把仓库显示成 UUID
date: 2026-08-06
status: complete
---

# Quick Task 260806-s8k — 摘要

**One-liner:** 蓝图 markdown 渲染器从 `repo_associations` 建 `{repository_id: 仓名}` 映射，把
现状分析标题与四张表的仓库列从裸 UUID 换成仓名 —— ⛔ 不给渲染器加参数（签名断言是「未经确认」
标注不可关闭的唯一机器验形式），映射从 content 自身派生，渲染器仍是零 DB 的纯函数。

## 改了什么

| 文件 | 改动 |
|------|------|
| `server/services/process_runtime/blueprint_render.py` | 新增 `_repo_names` / `_repo_label` / `_join_repos`；四个 section 收 `names` 形参；入口建映射 |
| `server/tests/services/process_runtime/test_blueprint_render.py` | 夹具换真实 UUID 形态 + 补 `api_contracts.repository_id` / `affected_features.repository_ids`；新增四条仓名用例 |

五个渲染点改用仓名：现状分析三级标题、功能模块「涉及仓库」、实现项「仓库」、
API 契约「归属仓库」、受影响功能「涉及仓库」。

## 为什么这么修

仓名的权威位置 `repo_associations[].repository_name` 本来就在 content 里，渲染器却只在
「仓库关联」那一段用了它，其余段落各自直出 `repository_id`。

⛔ **没有给 `render_blueprint_markdown` 加 `repo_names` 参数**：`test_blueprint_render.py:151`
的 `inspect.signature` 断言要求参数名集合恰为 `{content, blueprint_status}`。从 content 派生
映射同时满足三件事 —— 守住签名不变量、渲染器保持纯函数（注册表契约
`ContentRenderer = Callable[[dict], str]` 也给不了 DB 会话）、不引入第二个真相源。

回落方向与前端各 section 的 `repoNames[id] || id` 逐字同口径：解析不到就落 id，⛔ 不留白。

## 影响面

同一个渲染器供三个面消费，一处修复三处生效：

1. 飞书导出 —— `delivery/api/blueprint_export_views.py:299`
2. 项目工作台资料面板的方案预览 —— `ArtifactTimelineSerializer.current_version_markdown`
   → `web/src/components/delivery/ArtifactTimeline.vue:277`
3. MCP `get_technical_blueprint` —— `mcp_tools/views.py:4639`

前端蓝图详情页（`knowledge/blueprints/[id].vue`）本就自己解析仓名，不受影响。

## 验证

**真实数据实测** —— 蓝图 `5b650e1a-2939-4aa9-90a1-1297c0aaead9`（v10，四个仓）渲染导出
markdown，含仓库 UUID 的行数 **39 → 0**；四个 `### 仓库 <UUID>` 标题变成
`### 仓库 frontend/onion-learning` 等。

**用例** —— `test_blueprint_render.py` 39 passed（新增 4 条）：

- `test_repository_references_render_names_never_raw_ids` —— 全篇断言 UUID **不出现**
- `test_repository_label_falls_back_to_id_when_name_is_missing` —— 关联表缺名回落 id
- `test_repository_reference_outside_associations_falls_back_to_id` —— 陌生仓回落自己的 id
- `test_repository_ids_list_renders_all_names_joined` —— 多仓列表逐个解析

**关联套件** —— `test_blueprint_consumer_seams.py` / `test_blueprint_inv6_guard.py` /
`test_artifact_timeline_api.py` 合计 97 passed；`ruff format` + `ruff check` 通过。

**已知既有失败（与本次无关）** —— `test_blueprint_export_views.py::test_export_event_is_not_in_blueprint_events`：
在本次改动 stash 掉后同样失败，来源是工作区里 `delivery/services/event_taxonomy.py` 的其他未提交改动。

## 遗留

`current_state_analysis` 的 schema 仍无 `repository_name` 字段（`blueprint_schema.py:324-335`），
仓名解析依赖 `repo_associations` 齐全。若某仓未登记进关联表，该段仍会显示 id —— 这是刻意的
回落而非静默丢信息，实际数据里四个仓都在关联表内。
