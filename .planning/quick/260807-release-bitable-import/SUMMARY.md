# Summary — 上线文档多维表格全量导入「上线记录」工件

## 背景

会话 `97b8bcf2`（习题4.0立项背景咨询）AI 答「没有产品定义文档」，原因有二：

1. 知识库确实没有习题 4.0 的立项/上线数据——Release 账本（`ReleaseBatch`/`ReleaseRecord`）为 0 行，上线文档表从未摄取过；
2. 检索盲区：工件是 `kind=document` 实体，`search_delivery_knowledge` 不传
   `include_document_kind`，document 实体在该链路**永远召不回**。

## Done

- 拉全飞书「上线文档表格」（`CFQCbbtoVaEhT8sM9XPcPvExnGe` / `tbls2oct7kJNjXtf`）
  **6087 条记录**，缓存 `/tmp/release-bitable-records.json`
- 建项目 **「上线记录」**（技术支撑空间，key `release-bitable:{app}:{table}`）
- 建工件类型 `release_record`（「上线记录」，markdown 载体，ragable=True）
- 按「发布计划名称」聚合导入 **3997 个 markdown 工件**（含上线业务/日期/分类/服务/
  MR/分支/开发测试人员/特殊说明），走既有 `ArtifactService` + artifact normalizer
  摄取，全部 3997 实体 `vector_synced=True`
- 导入期间关掉 RepoRouterV2 逐工件 LLM 路由（防 ~4000 次 LLM 调用）
- **代码修复（KDEP-02 同款先例）**：`search_delivery_knowledge`（agents tool）、
  MCP `SearchDeliveryKnowledgeView`、workflow `delivery_knowledge_search` 节点
  补 `include_document_kind=True`——工件/物化文档/上线记录可被 AI 检索，权限闸不放宽
- 相关测试 24 passed

## 验证

- 「习题 4.0 灰度」→ 命中 `学习工具:260423-习题 4.0 灰度（3.0 跳转）` 等上线记录
- 全库 81 条提到习题的上线行、习题 4.0 相关十余个发布计划均已入库

## Gaps

- 上线文档表是**发版运维记录**（MR/服务/日期），仍不含「为什么立项」的 PRD 级内容；
  习题 4.0 的立项背景文档源站（ricelove/飞书）本身缺失
- Release 账本（`ReleaseRecord`）本次未落——用户选择工件方案；如需看板/账本再议

## Scripts

- `fetch_records.py` — 分页拉全表 + 统计
- `import_release_artifacts.py` — 项目/类型/工件导入 + 同步摄取（幂等可重跑，`--ingest-only` 只补摄取）
