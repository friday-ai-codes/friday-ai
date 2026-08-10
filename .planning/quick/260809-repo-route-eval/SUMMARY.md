# 「高三提分专项」仓库路由 5 次复跑评测

日期：2026-08-09 ｜ 只读评测，未写业务库（不落 `RepoAssociation`）

## 实验设置

| 项 | 值 |
|---|---|
| 项目 | 高三提分专项 `75248ff9-3a22-4175-b940-6093d71eb4dc` |
| 空间 | 学习工具 `2f6ae28d-…97a85f94fcae`，30 个仓全部 indexed |
| 语料 | `feature_list` 工件（9 模块 / 45 功能点）+ `test_case` 工件（193 条测试标题） |
| 链路 | `RepoAssociationService._build_query` → `RepoRouterV2.route(use_llm=True)`，与 `propose` 唯一差别是不落库 |
| 模型 | `claude-opus-4-8[1m]`（`claude_code_config.model_mapping.haiku`，Stage 1 取 haiku 档） |
| 人工基线 | frontend/onion-learning、frontend/onion-practice、backend/study-user-status、backend/study-course |

Stage 1 自带输入哈希缓存（TTL 24h），直接跑 5 次会是 1 次真实调用 + 4 次缓存命中。
评测脚本用代理对象只旁路 `repo_router_v2:stage1:` 前缀的读写，保证 5 次都是真实上游调用。

## 结果

### A. 生产默认配置（`STAGE0_NODE_K=50`、`top_k=5`、Stage1 候选 8）

| 指标 | 值 |
|---|---|
| 4 个仓全中 | **0 / 5** |
| 候选集恰好等于这 4 个仓 | 0 / 5 |
| 平均命中 | 2.40 / 4 |

| 目标仓 | 被召回次数 |
|---|---|
| backend/study-user-status | 5/5 |
| frontend/onion-practice | 5/5 |
| frontend/onion-learning | 2/5 |
| backend/study-course | **0/5** |

明细：`result-prod-defaults.json`

### B. 放宽 Stage 0 召回（`STAGE0_NODE_K=300`、Stage1 候选 12、`top_k=5`）

全中 0/5，平均 2.40/4。study-course 升到 4/5，但 onion-learning 掉到 0/5——top-5 名额零和。
明细：`result-widened-recall.json`

### C. B + `top_k=8`

全中 **1/5**，平均 3.20/4。study-course / onion-practice / study-user-status 均 5/5，
onion-learning 仅 1/5。明细：`result-topk8.json`

## 归因

### 1. study-course 从未进候选 —— Stage 0 召回天花板，不是 LLM 判断错

- study-course 的能力树是建好的：`repo_index_nodes` 里 55 个节点。
- 但用本项目语料做节点级检索，它**最好的节点全局排 #80**；Stage 0 只取全局 top-50 节点
  （`STAGE0_NODE_K=50`）后按仓分桶 → study-course 拿到 0 个桶，**从未出现在喂给 LLM 的候选里**。
- 放宽到 300 后即稳定进候选（B/C 组 4~5/5）。

### 2. onion-learning 被 LLM 主动剔除 —— 排序问题

- Stage 0 里 onion-learning 排 **#2**（score 0.869，仅次于 study-user-status）。
- 但 opus 4.8 在多数轮次把它从输出里去掉，反而稳定输出 study-app / study-practice /
  study-flow / study-stream 这几个非目标仓。C 组放到 8 个名额后仍只有 1/5。

### 3. 4000 字符 query 预算：45 个功能点只有 7 个进了 query

- `_QUERY_CHAR_BUDGET = 4000`。本项目 feature list 完整语料 21166 字符、加测试用例 28872 字符。
- 实际只覆盖到**前 7 个功能点（9 个模块里的 2 个）**；**测试用例语料 100% 未进入 query**
  （拼接顺序在 feature list 之后，预算早已耗尽）。
- 但截断不是 study-course 落选的原因：单独用被截掉的后半段语料检索，study-course 同样进不了候选。

### 4. 去掉截断会让路由整体崩掉（健壮性缺口）

用 21k / 28k 字符的完整语料直接调 `route`，`router_version` 变成 `v1_fallback` 且**零候选**：
超长文本让 embedding 返回空 → `_stage0_node_search` 返回 `[]` → 走 v1 兜底。
即 4000 预算目前起的是"保护"作用，一旦放开就是静默全失败。

### 5. opus 4.8 拒收 `temperature`，幂等第三道防线失效

每次路由都先收到一次 400：

```
`temperature` is deprecated for this model
```

然后 `repo_router_v2_stage1_decode_params_dropped` 重建模型再调一次。后果：

- 每次路由多一次废调用 + 约 2~3s；
- `_STAGE1_DECODE_PARAMS`（temperature=0 / top_p=1 / seed=42）这道"固定 decode 参数"
  的幂等防线在该模型上**完全不生效** —— 这正是同一输入 5 次结果不同的原因。

另有一次 smoke run 的 Stage 1 超过 90s 超时（`REPO_ROUTER_STAGE1_TIMEOUT_SECONDS=90`），
降级为 `v2_stage0_only`；正常轮次 Stage 1 耗时约 20~25s。

### 6. 候选 repo_name 前缀不一致（下游匹配隐患）

`repo_name` 来自建索引时写入 Qdrant payload 的快照，未随仓库改名回填：

| 仓 | payload repo_name | DB name | built_at |
|---|---|---|---|
| onion-learning | `frontend/onion-learning` | `frontend/onion-learning` | 2026-06-25 |
| study-user-status | `backend/study-user-status` | `backend/study-user-status` | 2026-06-25 |
| onion-practice | `onion-practice` | `frontend/onion-practice` | 2026-06-22 |
| study-course | `study-course` | `backend/study-course` | 2026-06-22 |

06-22 那批索引带的是改名前的短名。路由本身按 repo_id 走不受影响，但任何按名字比对
的消费方（含本评测第一版）都会误判。

## 复现

```bash
cd server
uv run python ../.planning/quick/260809-repo-route-eval/route_eval.py --runs 5 \
    --out ../.planning/quick/260809-repo-route-eval/result-prod-defaults.json
uv run python ../.planning/quick/260809-repo-route-eval/diagnose.py
uv run python ../.planning/quick/260809-repo-route-eval/diagnose_index.py
uv run python ../.planning/quick/260809-repo-route-eval/diagnose_truncation.py
```
