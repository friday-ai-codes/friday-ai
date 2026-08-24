---
phase: 139
status: passed
fixes_applied: 5
---

# Phase 139 Code Review

## 自动修复

1. Chat async 测试事务隔离导致 fixture FK 不可见：改为 transaction DB。
2. npm 初版只验证 source schema：增加 `prepack` bundle contract/hash 硬闸。
3. `query_service` / `process_index` component 漂移为 `codegraph`：统一为 `code_graph`。
4. 旧观测守护把新 caller 入口误判为纯内核：仅对白名单入口放宽 caller，其他内核仍 sampling。
5. Phase 133 benchmark 直连内部 cache 与 barrel 守护未同步 public query contract：改走包根并扩展
   精确公开面测试。

## 结论

最终 access/observability/conformance 全绿；无 schema 漂移、权限绕过、未打包工具或明文 query
RetrievalTrace 残留。
