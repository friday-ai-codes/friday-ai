# Phase 134 Context：TS/JS resolved 调用边

## Smart Discuss 自动决策

| 灰区 | ✅ Recommended 决策 |
|---|---|
| 解析结果兼容 | 扩展既有 `ResolveResult`，保留三项旧字段与构造方式，新增状态、语言、形态、策略、候选和证据 |
| 歧义策略 | 同一证据层出现多个同优先级候选即 `ambiguous`，不任选；全仓同名不作兜底 |
| re-export | 基于既有 `ImportEdge` 做有界、循环安全的链式解析，证据记录每跳文件 |
| receiver | 本阶段只接受 namespace/import binding 等静态唯一证据；普通对象缺类型证据时 `unresolved` |
| 回填范围 | 强制 `(repository, branch)`，提供 `dry_run`；批循环仅 debug sampling，汇总 caller 日志 |
| 下游失效 | 实际写入 resolved edge 后删除同分支 Community/Process 投影并驱逐图缓存；dry-run 零写入 |
| schema 迁移 | 不新增持久字段；审计元数据随 `ResolveResult` 与批量统计返回，避免迁移和双事实源 |

## 边界

- 仅 TS/TSX/JS/JSX/Vue 前端语言；Python 留 Phase 135，Go 深化保持 Future。
- 不引入 LSP 默认翻转、图数据库或全仓 fuzzy。
- 复用 `SymbolIndex`、`FrontendImportResolver`、`ImportEdge`、`CallEdge` 与现有索引挂点。

## 验收

- alias、re-export、namespace receiver 可 resolved 且证据可审计。
- 多候选与缺证据稳定返回 ambiguous/unresolved。
- branch dry-run 不写；实际写入后仅失效目标分支派生投影。
