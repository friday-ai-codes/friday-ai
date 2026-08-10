---
slug: repo-association-signal-fusion
date: 2026-08-10
status: complete
---

# 项目选仓接入「章程 + 历史」三分量融合 — 复跑评测 + study-course 召回诊断

## 提交

- `e78fcbdb` feat(repositories): 项目选仓接入章程+历史三分量融合
- 文件：repo_association_service.py（_fuse_extended_signals）、blueprint_route_history.py（acting_user 参数）、test_repo_association_service.py（融合用例 + signal_fusion 留痕）
- 测试：tests/initiatives/test_repo_association_service.py 7 passed

## 复跑评测（接入融合后，走 _fuse_extended_signals 链路）

`result-rerun-fusion.json`，5 次真实上游调用（Stage1 缓存旁路）：

| 指标 | 接入前(A组生产默认) | 接入后(本次) |
|---|---|---|
| 4 仓全中 | 0/5 | **4/5** |
| 平均命中 | 2.40/4 | **3.80/4** |
| study-course | 0/5 | **5/5** |
| onion-learning | 2/5 | 4/5 |
| onion-practice / study-user-status | 5/5 | 5/5 |

唯一未全中的 run 5：onion-learning 被 study-practice / study-flow 挤出（top-5 名额零和）。

## study-course 召回根因（为什么它"应该"进、过去却进不了）

study-course 是洋葱学园 **Go C 端学习课程后端**（course/homework/video/register/textbook 等 gRPC，GraphFileIndex 184 文件），能力树 `ai_summary_tree` 写得很好（课程内容体系/视频/习题作业/专项课总复习/学案/笔记…）。「高三提分专项」语料的模块（课程包权益、章节树、视频讲解、习题、学习进度）与它**高度对口**——它确实是正确落点。

过去 0/5 的根因不是"它没做这个需求"，而是 **Stage 0 召回天花板**：它的最佳节点在节点级检索全局仅排 ~#80，原 `STAGE0_NODE_K=50` 把它挡在候选之外，从未进入喂给 LLM 的集合。本次接入的**多探针 RRF + charter/history 融合**把它稳定拉回 top-5（5/5）。

注：study-course 语义 RAG 仅 2 文件/10 chunk（挂在 feat/coding-agent-base，remote HEAD=master），但那是另一条 RAG 链，**不是**路由 Stage 0 的数据源（Stage 0 吃 repo_index_nodes 能力树向量）。
