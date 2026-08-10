---
slug: repo-index-audit
date: 2026-08-10
status: complete
---

# 仓库索引覆盖审计 + study-course master 改动溯源

## 核心结论：`indexed_files_total` 计数器失同步，语义向量实际完好

抽查 Qdrant ground-truth（get_collection_stats）：

| 仓 | Qdrant 点数 | Qdrant 文件数 | DB FileIndex 行 | DB `indexed_files_total` |
|---|---|---|---|---|
| backend/study-course | 4467 | 694 | 207 | **2** ← 错 |
| backend/growth-order-thirdparty | 16972 | 2060 | 1592 | **0** ← 错 |
| frontend/onion-practice | 13148 | 2438 | 1956 | **0** ← 错 |
| backend/alcibia_service（对照） | 31855 | 1082 | 994 | 994 ✓ |

- 131 个仓 `indexed_files_total=0`、121 个图正常（g>5）；**全部 131 仓 FileIndex 都有锚点、Qdrant 向量都在**。
- 共性：`auto_index_enabled=False`、`last_indexed_at≈2026-06-24`。
- 推断：06-24 前后某次索引完成后，`indexed_files_total` 计数被重置/未回写（auto_index 关闭，后续无增量触发回写），DB 计数与实际 Qdrant 存储失同步。**不是数据缺失，是统计字段陈旧。**
- 影响：路由 Stage 0 不吃这套（吃 repo_index_nodes 能力树），但任何按 `indexed_files_total` 判断"是否已索引"的 UI/逻辑会误报"未索引"。

## study-course 在 master 的改动（相对 feat/coding-agent-base）

feat/coding-agent-base tip = `0462f68`（2026-07-14，= merge-base）；master tip = `f1ee68a`（2026-07-28），领先 3 个提交：

```
f1ee68a zadig     Merge branch 'pre/26.07.27' into 'master'
49b494a zadig     Merge branch 'feat/newProblem-4' into 'pre/26.07.27'
b783fc6 yang.liu  feat: 重难点培优支持四级目录
```

改动文件（+558/-43）：`services/new_problem_type.go`、`new_problem_type_test.go`(+262)、`totalReview.go`(+1)、go.mod/go.sum，及 openspec 文档 5 个。

### 改动目的（openspec proposal）

**重难点培优章节接口从「三级压平」恢复为「四级真实目录」。**

- 现状问题：`GET /study-course/newProblemType/packageChapter` 在四级课程下把后台「章节—大节—小节—知识点」**强制压平成三级**（`convert4LevelTo3LevelChapter` 丢掉小节层、levelNum 4→3），客户端无法按真实四级展示。
- 本次：四级课程保持 `levelNum=4`，原位整形保留小节层；在每个有免费知识点的章节聚合虚拟「免费试学」大节+小节；过滤空层级；三级课程行为不变。
- **BREAKING**：四级课程该接口从三级响应恢复为四级响应，客户端须按 levelNum 解析。
- 入口 `handlers/new_problem_type.go`，上游仍 `course-bff.GetSpecialCourseTreeById`。

与「高三提分专项」语料的「重难点培优/专项课/章节树/四级目录」模块直接对应 —— 这正是 study-course 应被路由命中的业务依据。

注：master 改动只动 10 个文件，不影响"树有 244 文件"的事实 —— feat 与 master 两分支树都是全量的（feat=244 / master=250），master 只是相对 feat 多了这 3 个提交的增量。
