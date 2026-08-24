# Phase 139 Context：五消费面契约收敛

## Smart Discuss 自动决策

| 灰区 | ✅ Recommended 决策 |
|---|---|
| 真源 | `server/contracts/graph-query.v1.json` 为唯一 canonical manifest |
| hash | 对 manifest 原始 bytes 做 SHA-256，生成物与运行响应均透出 |
| service | 只负责 canonical 算法与版本元数据，不感知协议 |
| Chat/Django MCP | 只做鉴权、上下文注入、输入映射与 RetrievalTrace |
| npm MCP | 构建前生成 TS；tool discovery 透出 input/output schema 与 contract metadata |
| 编码容器 | 从同 manifest 生成 Python schema，并进入 knowledge allowed-tools |
| 构建闸 | conformance 比较完整 manifest hash；npm prepack 验证 bundle 含版本/hash |
| 留痕 | MCP 与 Chat 只写 scope/count/status/hash，不把 query 正文写 RetrievalTrace |

## 边界

不改前端，不新增依赖，不复制查询算法到任何适配面。
