---
name: friday-memory
description: "Friday 的记忆层。当用户要把完成的任务沉淀为可复用经验（LearningCase）、在新工作前检索相似需求/缺陷修复经验，或查询历史交付知识——「以前做过类似需求吗」、实体版本时间线、需求→方案→MR 关联链、历史时点 as_of 查询——时使用。反向边界：当前任务无需历史经验/交付检索时，不必走本技能。"
---

# Friday Memory

Friday 的两层记忆，都通过 `friday` MCP server 工具访问：

| 记忆层 | 数据域 | 工具 |
| --- | --- | --- |
| **经验记忆（LearningCase）** | 任务级经验：根因、解法、已验证测试 | `create_learning_case` / `search_learning_cases` |
| **交付知识（Knowledge）** | 摄取后的全链路交付实体图谱：飞书需求 → 技术方案 → 代码变更/MR | `search_delivery_knowledge` / `get_entity_timeline` / `get_related_entities` |

**不是**代码仓库 RAG——查"X 在仓库 Y 里怎么实现的"用 `friday-code`（`search_rag_chunks` 等）。

## 前置门槛

看不到 `friday` MCP 工具，或调用返回 401/403，引导用户运行 `npx -y @friday-ai-codes/mcp setup`（见 `friday` 技能「环境未就绪」一节）。保留工作流首个响应的 `run_id`。

## 模式判定

| 用户意图 | 走哪层 / 工具顺序 |
| --- | --- |
| 任务做完了，把经验记下来 | 经验记忆：`create_learning_case` |
| 开始新需求前找相似经验 | 经验记忆：`search_learning_cases` |
| 「以前做过类似 X 吗」 | 交付知识：`search_delivery_knowledge` |
| 「这个需求后来怎么迭代的」 | 交付知识：`get_entity_timeline` |
| 「从需求追到方案和 MR」 | 交付知识：`search_delivery_knowledge` → `get_related_entities` |
| 「2026-05 时方案是什么」 | 交付知识：任意工具 + `as_of` ISO8601 |

## 经验记忆 — LearningCase

### 记录（执行完成或部分完成后）

1. `create_learning_case`，传 `technical_plan_id`、`outcome`、`root_cause`、`solution_notes` 和已验证的 `tests`。
2. 保存 `learning_case_id` 并写进最终报告。

### 检索（规划新工作前）

1. `search_learning_cases` 现为**统一向量检索**（与 `search_delivery_knowledge` 同一向量库与融合排序）：用需求标题/描述构造 `query`；`work_item_type`、`repo_hints`、`file_hints`、`symbol_hints` 作为**查询增强与排序提权**（拼入查询文本 + 命中加权 rerank），不再是关键词收窄过滤——hints 给得准会提升相关结果排名，给错不会漏召回；`limit` 控制返回条数。
2. 把相关结果作为 `similar_cases` 喂给 `friday-code` 阶段三或 `friday-feishu` 阶段二。

### 护栏

- 诚实记录：`outcome` 反映实际发生的结果（success / partial / failed），不是预期结果。
- LearningCase 创建失败不影响执行产出的有效性——修复报告的问题后重试即可。
- "先检索再规划"成本极低、常常决定方向；任何非平凡需求都建议先跑一次检索。
- 结果 `score` 为 0-1 向量融合分（越高越相关），只用于同一次检索内排序比较，不要跨检索设绝对阈值；检索依赖服务端向量库，暂时不可用时返回空 `results`（fail-soft），稍后重试即可。

## 交付知识 — Knowledge

### 推荐步骤

1. **`search_delivery_knowledge`** — `query`（必填），可选 `project_ids` / `top_k` / `as_of` / `include_superseded`。保留 `run_id` 与命中 `entity_id`。
2. 对高相关命中：**`get_entity_timeline`** — `entity_id`，看版本迭代与挂接的 code_change。
3. 需要扩散关联链：**`get_related_entities`** — `entity_id`, `direction`（both/out/in）, `max_hops`（1–3）, 可选 `as_of`。

### 护栏

- 引用结果中的 **provenance**（`feishu_url` / `mr_url` / `session_link`），无链接则说明「无出处」。
- 检索为空时**不要编造**历史需求或 MR。
- PAT 权限 fail-closed：无项目权限时返回空 `results`，不是 403 泄露。

### as_of 示例

用户问：「2026-05 时这个需求的方案是什么？」

```json
{
  "query": "用户登录优化",
  "project_ids": ["<project-uuid>"],
  "as_of": "2026-05-31T23:59:59+08:00"
}
```

## 输出

- 记录：`learning_case_id` 和一行案例摘要。
- 检索：按相关度排序的结果及其出处/解法笔记，外加 `run_id`。

## HTTP 兜底

MCP 不可用时见 [references/http-fallback.md](references/http-fallback.md)。
