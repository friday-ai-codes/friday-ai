---
slug: index-counter-fix
date: 2026-08-10
---

# 四仓职责 / 高三提分落地 / 召回稳定性分析

## 一、四个仓各自做了什么（master 实证）

「高三提分专项」= 面向高三学生的**单题型 4 节点解锁学习链路**（入口→单题型学习页→真题检测→知识卡片→视频讲解→同型题检验→完成页→进度掌握），含「重难点培优四级目录」。

| 仓 | 形态 | 高三提分里的改动（master 实证） |
|---|---|---|
| **frontend/onion-learning** | Vue3 monorepo 前端（学习工具） | 提分专项的**前端载体**。`apps/learn-rapid-score-boost`（极速提分营）+ `apps/learn-topic-complete`（单题型学习完成页）。改 complete.vue / knowledge-card.vue / topic.vue / improveScore.ts / 新手引导 onboardingGuide / 兼容鸿蒙 |
| **frontend/onion-practice** | 做题框架 monorepo（Problem 4.0） | 提分专项的**做题内核**。`apps/group-a` + `packages/plugins/landscapeRealExam`（真题检测）/ `landscapeCountDown`（倒计时）/ `landscapeProblemTitle` + 错题本举一反三。真题检测、同型题检验都落在做题框架 |
| **backend/study-user-status** | Go BFF（用户学习状态聚合） | 提分专项的**状态后端**。学习进度、掌握程度、同步刷题接入 AI 视频推荐、批量错题推荐视频。覆盖精准学/同步课程树/学习记录 |
| **backend/study-course** | Go 后端（课程内容 API） | 提分专项的**内容后端**。`new_problem_type.go` 重难点培优四级目录（三级压平→四级真实目录，免费试学聚合）。章节树/视频/习题/专项课总复习 |

**为什么恰好是这四个**：一个完整学习闭环 = 前端载体（onion-learning）× 做题内核（onion-practice）× 状态后端（study-user-status）× 内容后端（study-course）。四仓职责**正交互补**，各管一层，合起来才是这个需求的全链路。人工选对得很准。

## 二、召回机制为何不能稳定命中这四仓

诊断结论：**主因是召回机制缺陷（一阶召回天花板 + breadth 偏置 + 截断），次因是章程边界缺失**——不是仓库职责边界不清（四仓职责其实很清晰）。

### 机制缺陷（主因）

1. **一阶召回天花板（Stage 0 top-K 截断）**
   study-course 最佳节点全局排 #80，旧 `STAGE0_NODE_K=50` 把它挡在候选外，从未进 Stage 1 的 LLM 视野。reranker/LLM 救不回没见过的文档。→ 已改 200。

2. **breadth（命中广度）偏置挤掉专精仓**
   多探针检索下，泛泛相关的仓在 8 个探针各捞几个节点累积 20~27 个；专精仓（study-course）只在少数探针强命中、仅 9 个节点。聚合分时 study-course 排 #58，因节点数少挤不进仓级 top-12。→ 已引入 cross-encoder 精排（不吃"出现次数"）+ `diversify_breadth` 去 breadth 入选。

3. **4000 字符 query 截断误伤检索**
   `_QUERY_CHAR_BUDGET=4000` 本是防 LLM 上下文，却加在检索入参上，45 功能点截到 7 个、测试语料 100% 没参与。→ 已拆分：检索吃全量多探针，prompt 单独截断 8000。

4. **opus 4.8 拒收 temperature → 幂等防线失效**
   每次路由先收一次 400，固定 decode 参数（temperature=0/seed=42）完全不生效，导致同输入 5 次结果不同。**这是"不稳定"的直接来源**。→ 待修：对该模型跳过 temperature。

### 章程边界缺失（次因）

- 四仓都有 AI 章程（2026-08-08 生成），`owned_domains` 笼统，**`boundaries`（负面清单/职责边界）全空**。
- 全库 257 章程，仅 78 有 boundaries（30%），179 个（70%）缺边界。
- 后果：charter_match 只能正向匹配"我做什么"，**无法用边界反向排除"我不做什么"**——于是 study-app / study-flow / study-practice 这些**名字相近、领域重叠**的仓无法被边界区分开，run 5 里 onion-learning 就被它们挤出 top-5。

## 三、如何完善（让 agent 基于事实稳定召回）

### 立即可做（机制层，收益已验证）

1. **修 opus decode 幂等**：对拒收 temperature 的模型跳过该参数，恢复"同输入同输出"。这是稳定性的最后一公里。
2. **保持当前 STAGE0_NODE_K=200 + cross-encoder 精排 + diversify_breadth**（已落地，4/5 全中）。

### 结构层（章程边界，治"定位模糊"）

3. **补全 179 个仓的 `boundaries`**：给每个仓写"我**不**做什么 / 与邻近仓的分界"。重点补学习/做题/课程这一族高度重叠的仓（study-app / study-flow / study-practice / study-stream / study-course / study-user-status / onion-learning / onion-practice），让 charter_match 能反向排除。
4. **`owned_domains` 细化到子域**：study-course 已做得较好（课程内容体系/视频/习题/专项课…），其余三仓偏笼统，应对齐到高三提分的模块粒度（入口/单题型/真题检测/知识卡片/视频讲解/同型题/完成页/进度掌握）。

### 事实层（让召回"基于事实"而非"基于名字"）

5. **用 git 提交历史校准 history_match**：四仓在高三提分窗口期都有真实提交（feat/260626.m-7024644100.高三提分专项 等）。这些 feat 分支名/提交信息是"这个需求落在这仓"的**人工事实标注**，应作为 history 分量的强信号——比语义相似更可靠。
6. **把"需求→仓"的人工确认结果回灌**：每次人工确认/修正选仓结果，写成该仓的正/负样本，喂给 charter 的 citations 与 history，形成飞轮。

## 四、一句话回答你的问题

> 是仓库职责边界不清晰？定位模糊？还是召回机制有问题？

**召回机制有问题（主因，已修）+ 章程边界缺失（次因，待补）。** 四仓职责本身清晰、人工选得准；是召回管线的一阶截断、breadth 偏置、截断 bug、decode 不幂等导致它们没被稳定召回；而边界缺失让"名字相近的干扰仓"无法被排除，加剧了不稳定。
