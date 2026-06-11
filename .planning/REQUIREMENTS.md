# Requirements: Friday AI — v0.3.0 交付知识图谱

**Defined:** 2026-06-11
**Core Value:** 让团队"开箱即用、安全地"把需求自动变成代码；v0.3.0 起需求/缺陷、技术方案、编码 diff 全链路 RAG 化并以时间感知知识图谱关联，任意入口都能召回相似历史需求及其完整迭代轨迹。

## v1 Requirements

### 知识模型（KMOD）

- [x] **KMOD-01**: 系统以统一实体模型存储四类交付知识实体——需求/缺陷（work_item）、技术方案（tech_plan）、代码变更（code_change：diff/commit/MR）、文档（document：PRD/技术方案文档），实体携带稳定业务引用（`source_kind` + `source_id`）与来源（feishu/chat/mcp/workflow）及事件时间
- [x] **KMOD-02**: 实体间关系以 bi-temporal 边存储（`valid_at`/`invalid_at` + `created_at`/`expired_at` 四时间戳），失效采用置位而非删除，历史可审计
- [x] **KMOD-03**: 同一实体的多次修改形成版本链（supersedes），旧版本保留且可按版本号回溯
- [x] **KMOD-04**: 图读写收敛于 GraphStore service 接口（内建 1–3 跳递归遍历、有效性过滤、防环与深度上限），调用方不得绕过接口裸写 SQL（保留换图引擎逃生门）
- [ ] **KMOD-05**: 编码产出的全量 diff 归档落库（unidiff 解析到文件级），关联 commit SHA / MR URL / 仓库元数据，超大 diff 压缩存储

### 知识摄取（INGEST）

- [ ] **INGEST-01**: 工作流 `ai_plan_generation` 产出技术方案时，自动摄取需求与方案实体并建立 `HAS_PLAN` 边（含方案审批通过事件）
- [ ] **INGEST-02**: 编码完成回调（TaskResult/CodingTask）时，自动归档全量 diff、摄取 code_change 实体并关联到对应方案/需求
- [x] **INGEST-03**: chat 对话产出 CodingPlan 或触发编码时，自动摄取提炼后的需求文本与方案（对话原文不入图）
- [ ] **INGEST-04**: 飞书工作项在关键事件（产出方案/触发编码/工作项更新）时摄取快照：名称、描述、自定义字段、PRD 文档与技术方案文档正文、关联工作项，均带事件时间
- [x] **INGEST-05**: MCP 工具链（`create_feishu_technical_plan` / `execute_work_item_repo_tasks` 等）产出方案或执行编码时自动摄取
- [ ] **INGEST-06**: 技术方案/需求被修改（多轮对话修改、审批驳回重生成、飞书文档更新）时重摄取为新版本：新版本向量入库、旧版本向量下线（`is_latest` 翻转兜底 + 物理删除），旧边写 `expired_at`
- [ ] **INGEST-07**: 摄取一律异步后台执行（`transaction.on_commit` + background runner），不阻塞请求/工作流主链路；幂等（重复事件不产生重复实体/版本）
- [ ] **INGEST-08**: 知识文本（需求/方案/PRD/diff）确定性 chunk 后经既有 EmbeddingService 向量化，写入独立 `delivery_knowledge` collection（hybrid dense+sparse，payload 含 entity_kind/entity_id/version/is_latest/project_id/event_time）

### 知识检索（RETR）

- [ ] **RETR-01**: 用户给定新需求文本，可召回 top-K 相似历史需求，并附带其关联的技术方案、代码变更与 MR 链接
- [ ] **RETR-02**: 用户可从任一实体出发双向查看关联上下游（需求→方案→diff→MR，反向亦可）
- [ ] **RETR-03**: 用户可查询一个需求的完整迭代轨迹：方案 v1→vN 与各次编码按时间排序的时间线（走 PG 版本链，不依赖向量库）
- [ ] **RETR-04**: 检索默认仅命中最新有效版本；被取代的内容不出现在默认结果中，显式标注 `superseded by vN` 后方可返回
- [ ] **RETR-05**: 检索融合向量召回 + 1–2 跳图扩散 + 时间衰减重排，已失效实体/边硬过滤（衰减只作用于状态类内容）
- [ ] **RETR-06**: 每条检索结果附出处 metadata：实体类型、版本号、valid 时间区间、来源链接（飞书工作项 URL / MR URL / 会话）
- [ ] **RETR-07**: 检索按 project/space 权限在 service 层内过滤（payload 含权限维度字段），越权内容不可见，入口 fail-closed

### 多入口暴露（EXPO）

- [ ] **EXPO-01**: MCP HTTP 查询工具（`search_delivery_knowledge` / `get_entity_timeline` / `get_related_entities`），PAT 认证 + interactions 审计，与既有 19 工具同体系
- [ ] **EXPO-02**: workflow 检索节点：方案生成前自动检索相似历史交付并注入上下文（使 `ai_plan_generation` 可消费历史 → 飞轮）
- [ ] **EXPO-03**: chat agent tools 暴露同一知识检索服务（@tool 注册 + langchain adapter）
- [ ] **EXPO-04**: npm Friday skill 封装知识检索工具链，外部 agent 可问"以前做过类似需求吗 / 这段代码为什么这么改"

### 增强（ENH）

- [ ] **ENH-01**: diff→chunk 符号级对齐：code_change 经 `MODIFIES_CHUNK` 边关联 ChunkRegistry 代码块（记 file+symbol+commit_sha 懒解析），支持反查"这个函数被哪些需求改过"
- [ ] **ENH-02**: LLM 相似度复评：相似需求召回结果二阶段分级（重复/相关/无关）并附一句话理由
- [ ] **ENH-03**: 前端只读实体详情页 + 关联时间线（列表/树形态，不做图画布编辑）
- [ ] **ENH-04**: as-of（point-in-time）历史时点查询暴露为检索工具参数（"2026-05 时这个需求的方案是什么"）

## v2 Requirements

### 知识洞察（INSIGHT）

- **INSIGHT-01**: 跨需求洞察报表（哪些模块返工最多、方案推翻率）— 离线分析，先积累数据
- **INSIGHT-02**: 检索权重自适应（α/half-life 按使用反馈调参）
- **INSIGHT-03**: 知识图谱与代码图谱（ChunkEdge）双向融合检索

## Out of Scope

| Feature | Reason |
|---------|--------|
| 全自动双向同步飞书（图谱回写工作项/全字段实时同步） | 回写=写权限+冲突解决+回环风暴；单向事件驱动快照已够 |
| LLM 自由文本实体/关系抽取 | 实体自带稳定业务 ID，抽取是负价值（贵、慢、漂移）；既定决策 |
| 在线图算法分析（社区发现/全图 PageRank） | 与 1–3 跳检索负载不同，会反推图数据库迁移；全局统计留离线 |
| 图谱可视化编辑器（画布增删实体/边） | 人工边必然腐烂（RTM 教训），破坏"工作流副产品"不变量 |
| 对话全量记忆化（Zep 式 agent memory） | 与会话隔离（v0.2.0）冲突、噪声大；仅摄取"成为需求"的节点 |
| 旧版本物理删除 | 历史轨迹查询是 table stakes；失效置位不删除 |
| 强一致同步索引（事件同步阻塞写图+写向量） | embedding 慢且可能失败；分钟级新鲜度容忍，异步幂等即可 |
| 引入 Neo4j 等图数据库 / 迁移既有 ChunkEdge | 基准实证 1–3 跳负载 PG 递归 CTE 反超 Neo4j；GraphStore 接口留逃生门 |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| KMOD-01 | Phase 12 | Complete |
| KMOD-02 | Phase 12 | Complete |
| KMOD-03 | Phase 12 | Complete |
| KMOD-04 | Phase 12 | Complete |
| KMOD-05 | Phase 14 | Pending |
| INGEST-01 | Phase 14 | Pending |
| INGEST-02 | Phase 14 | Pending |
| INGEST-03 | Phase 13 | Complete |
| INGEST-04 | Phase 14 | Pending |
| INGEST-05 | Phase 13 | Complete |
| INGEST-06 | Phase 13 | Pending |
| INGEST-07 | Phase 13 | Pending |
| INGEST-08 | Phase 13 | Pending |
| RETR-01 | Phase 15 | Pending |
| RETR-02 | Phase 15 | Pending |
| RETR-03 | Phase 15 | Pending |
| RETR-04 | Phase 15 | Pending |
| RETR-05 | Phase 15 | Pending |
| RETR-06 | Phase 15 | Pending |
| RETR-07 | Phase 15 | Pending |
| EXPO-01 | Phase 16 | Pending |
| EXPO-02 | Phase 16 | Pending |
| EXPO-03 | Phase 16 | Pending |
| EXPO-04 | Phase 16 | Pending |
| ENH-01 | Phase 14 | Pending |
| ENH-02 | Phase 15 | Pending |
| ENH-03 | Phase 16 | Pending |
| ENH-04 | Phase 16 | Pending |

**Coverage:**

- v1 requirements: 28 total
- Mapped to phases: 28 ✓
- Unmapped: 0

---
*Requirements defined: 2026-06-11*
*Last updated: 2026-06-11 after roadmap creation (traceability filled)*
