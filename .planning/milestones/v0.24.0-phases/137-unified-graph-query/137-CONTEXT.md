# Phase 137 Context：统一 GraphQueryService

## Smart Discuss 自动决策

| 灰区 | ✅ Recommended 决策 |
|---|---|
| 入口 | `GraphQueryService.query` 作为唯一版本化 service，先空白/权限/水位闸 |
| 融合 | Symbol 与 Process 使用固定权重 reciprocal-rank，round 后以稳定 ID 决胜 |
| 账本 | 每项返回 lane rank、贡献、Community enhancement、final score 与 ranking version |
| Community | 只由命中 Symbol 的 canonical membership 增强，不做额外 LLM |
| partial | lane 独立 fail-soft，schema 不变，capability 状态和 warning 显式 |
| 预算 | 先裁正文，再按稳定排名裁候选；总数与返回数分开、给 continuation hint |
| 水位 | repository/branch/commit 顶层唯一；Process/Community built_at 不同即不拼接 |
| impact | 本阶段只返回 `not_requested` 占位，bounded impact 与消歧留 Phase 138 |

## 边界

不新增 API/前端；五消费面接入留 Phase 139。
