# Roadmap: Friday AI — v0.3.0 交付知识图谱

**Milestone:** v0.3.0 交付知识图谱 — 需求/缺陷 ↔ 方案 ↔ 代码 GraphRAG 关联
**Created:** 2026-06-11
**Phases:** 5（Phase 12–16，接续 v0.2.0 的 Phase 11）
**Requirements:** 28 条 v1 需求，100% 映射

## Overview

把需求/缺陷（飞书或自然语言）、技术方案、编码 diff 全链路 RAG 化，并以带时间语义（bi-temporal）的知识图谱关联。构建顺序为严格依赖链：实体/边模型与 GraphStore 先行 → 统一摄取与版本化（首批触发点验证管线）→ 其余触发点 + 全量 diff 归档闭环 → 时间感知混合检索 → 多入口暴露与前端时间线。"第一天必须做对"的项（payload 权限字段、natural key、tombstone 协议、GraphStore 收口）全部压在 Phase 12–13。

## Phases

- [x] **Phase 12: 知识模型与图存储地基** - `knowledge` app 实体/版本/bi-temporal 边模型 + GraphStore 接口 + `delivery_knowledge` collection 生命周期 (completed 2026-06-11)
- [ ] **Phase 13: 统一摄取与版本化** - 幂等异步摄取管线 + 版本翻转/向量下线，接通 chat 与 MCP 首批触发点
- [ ] **Phase 14: 全触发点接入与 diff 归档** - workflow/编码回调/飞书三类触发点 + 全量 diff 归档与代码图谱对齐
- [ ] **Phase 15: 时间感知混合检索** - 向量召回 + 图扩散 + 时间衰减融合，相似需求召回与迭代轨迹查询
- [ ] **Phase 16: 多入口暴露与前端时间线** - MCP 工具 / chat tools / workflow 节点 / npm skill 四入口 + 前端只读详情页与 as-of 查询

## Phase Details

### Phase 12: 知识模型与图存储地基

**Goal**: 交付知识有统一、可审计、带时间语义的存储底座，图访问唯一收口于 GraphStore 接口
**Depends on**: Nothing（本里程碑首个阶段；依赖既有 Postgres/Qdrant 栈）
**Requirements**: KMOD-01, KMOD-02, KMOD-03, KMOD-04
**Success Criteria** (what must be TRUE):

  1. 四类实体（work_item / tech_plan / code_change / document）能以统一模型落库，携带 `source_kind` + `source_id` 稳定业务引用、来源（feishu/chat/mcp/workflow）与事件时间
  2. 实体间关系以 bi-temporal 四时间戳边（`valid_at`/`invalid_at` + `created_at`/`expired_at`）存储，失效是置位而非删除，失效后的边在默认遍历中不可见但历史可查
  3. 通过 GraphStore 接口可完成 1–3 跳递归遍历，自动施加有效性过滤、深度上限与防环；调用方拿不到绕过接口的裸 SQL 路径（边表 raw SQL 仅存在于 GraphStore 实现内）
  4. 同一实体的多次修改形成 supersedes 版本链，可按版本号回溯任意旧版本
  5. `delivery_knowledge` collection 创建/校验有显式生命周期管理：维度不匹配时拒绝并响亮报错（提供显式重建命令），绝不自动删库重建；payload schema（entity_kind/entity_id/version/is_latest/project_id/event_time 及权限维度字段）第一天即定型

**Plans:** 3/3 plans complete
Plans:
**Wave 1**

- [x] 12-01-PLAN.md — knowledge app 三模型（实体/版本链/bi-temporal 边）+ 全部 DB 约束 + 测试基建（Wave 0 合并）

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 12-02-PLAN.md — GraphStore 接口与递归 CTE 遍历（防环/深度 clamp/有效性过滤/raw SQL 收口 grep 审计）
- [x] 12-03-PLAN.md — delivery_knowledge collection 生命周期（payload schema 定型 + mismatch 拒绝 + --yes 显式重建命令）

### Phase 13: 统一摄取与版本化

**Goal**: 知识摄取成为业务流程的自动副产品——幂等、异步、版本化，检索面始终只见最新版；以 chat 与 MCP 两个形态最稳定的触发点验证管线
**Depends on**: Phase 12
**Requirements**: INGEST-03, INGEST-05, INGEST-06, INGEST-07, INGEST-08
**Success Criteria** (what must be TRUE):

  1. chat 对话产出 CodingPlan 或触发编码时，提炼后的需求文本与方案自动入图入向量（对话原文不入图），用户无需任何手动操作
  2. MCP 工具链（`create_feishu_technical_plan` / `execute_work_item_repo_tasks` 等）产出方案或执行编码时自动摄取
  3. 技术方案/需求被修改后重摄取为新版本：新版本向量入库、旧版本向量下线（`is_latest` 翻转兜底 + 物理删除）、旧边写 `expired_at`，检索默认只命中最新版
  4. 摄取一律 `transaction.on_commit` + background runner 异步执行，不阻塞请求/工作流主链路；同一事件重复投递不产生重复实体或重复版本（幂等键约束 + reconcile 对账命令可验证）
  5. 知识文本经确定性 chunk + 既有 EmbeddingService 向量化写入 `delivery_knowledge`（hybrid dense+sparse），payload 完整携带 entity_kind/entity_id/version/is_latest/project_id/event_time

**Plans:** 3/4 plans executed
Plans:
**Wave 1**

- [x] 13-01-PLAN.md — 向量化基建：vector_synced 迁移 + 确定性 chunker + vector_ops 写薄层（payload schema 锁定、失败响亮）

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 13-02-PLAN.md — 摄取核心：DTO + aschedule_ingestion（async on_commit A1 首验）+ 六步版本翻转事务序 + 边精细置位

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 13-03-PLAN.md — source normalizers（coding_plan/mcp_plan）+ 5 锚点触发接线（chat ×3 + MCP ×2，只接线）
- [ ] 13-04-PLAN.md — reconcile 对账命令（五检查项 dry-run/--fix）+ rebuild 全量重嵌入扩展

### Phase 14: 全触发点接入与 diff 归档

**Goal**: 六类触发点全部接通，编码产出的全量 diff 归档落库并与既有代码图谱打通，需求→方案→代码全链路在图中闭环
**Depends on**: Phase 13
**Requirements**: KMOD-05, INGEST-01, INGEST-02, INGEST-04, ENH-01
**Success Criteria** (what must be TRUE):

  1. 工作流 `ai_plan_generation` 产出技术方案时，需求与方案实体自动入图并建立 `HAS_PLAN` 边（含方案审批通过事件）
  2. 编码完成回调（TaskResult/CodingTask）时，server 侧经 git platform 拉取全量 diff 归档落库（unidiff 解析到文件级、关联 commit SHA / MR URL / 仓库元数据、超大 diff 压缩存储），并摄取 code_change 实体关联到对应方案/需求
  3. 飞书工作项在关键事件（产出方案/触发编码/工作项更新）时摄取带事件时间的快照，含名称、描述、自定义字段、PRD 与技术方案文档正文、关联工作项
  4. code_change 经 `MODIFIES_CHUNK` 边（file+symbol+commit_sha 懒解析）关联 ChunkRegistry 代码块，可反查"这个函数被哪些需求改过"
  5. 万行级大 diff（含生成文件）摄取不拖垮管线：分层切块、生成文件跳过、批量写入可经大 diff 夹具验证

**Plans**: TBD

### Phase 15: 时间感知混合检索

**Goal**: 任意新需求文本都能召回相似历史交付及完整迭代轨迹，结果始终是最新有效版本、带出处与时间限定，且按权限过滤
**Depends on**: Phase 14
**Requirements**: RETR-01, RETR-02, RETR-03, RETR-04, RETR-05, RETR-06, RETR-07, ENH-02
**Success Criteria** (what must be TRUE):

  1. 给定新需求文本可召回 top-K 相似历史需求，并附带关联的技术方案、代码变更与 MR 链接；二阶段 LLM 复评对召回结果分级（重复/相关/无关）并附一句话理由
  2. 从任一实体出发可双向查看关联上下游（需求→方案→diff→MR，反向亦可）
  3. 可查询一个需求的完整迭代轨迹：方案 v1→vN 与各次编码按时间排序的时间线，走 PG 版本链、不依赖向量库
  4. 检索融合向量召回 + 1–2 跳图扩散 + 时间衰减重排；默认仅命中最新有效版本，已失效实体/边硬过滤，被取代内容显式标注 `superseded by vN` 后方可返回
  5. 每条结果附出处 metadata（实体类型、版本号、valid 时间区间、来源链接）；权限过滤在 service 层内强制（签名携带 user、payload 权限字段过滤），越权内容不可见

**Plans**: TBD

### Phase 16: 多入口暴露与前端时间线

**Goal**: 同一知识检索 service 经四个程序化入口 + 前端只读页全部可达，方案生成自动消费历史形成飞轮，每个入口 fail-closed
**Depends on**: Phase 15
**Requirements**: EXPO-01, EXPO-02, EXPO-03, EXPO-04, ENH-03, ENH-04
**Success Criteria** (what must be TRUE):

  1. MCP HTTP 工具（`search_delivery_knowledge` / `get_entity_timeline` / `get_related_entities`）经 PAT 认证可用，interactions 审计与既有 19 工具同体系；A 用户 PAT 查 B 项目得空结果（越权用例通过）
  2. workflow 检索节点在方案生成前自动检索相似历史交付并注入上下文，`ai_plan_generation` 可消费历史
  3. chat agent tools 与 npm Friday skill 暴露同一检索服务，外部 agent 可问"以前做过类似需求吗 / 这段代码为什么这么改"并得到带出处的回答
  4. 前端有只读实体详情页 + 关联时间线（列表/树形态），用户可浏览需求→方案→代码变更的关联与版本历史
  5. as-of（point-in-time）历史时点查询作为检索工具参数可用（"2026-05 时这个需求的方案是什么"）

**Plans**: TBD
**UI hint**: yes

## Progress

**Execution Order:** 12 → 13 → 14 → 15 → 16（严格串行依赖链）

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 12. 知识模型与图存储地基 | 3/3 | Complete    | 2026-06-11 |
| 13. 统一摄取与版本化 | 3/4 | In Progress|  |
| 14. 全触发点接入与 diff 归档 | 0/? | Not started | - |
| 15. 时间感知混合检索 | 0/? | Not started | - |
| 16. 多入口暴露与前端时间线 | 0/? | Not started | - |

## Coverage Map

| Phase | Requirements | Count |
|-------|--------------|-------|
| 12 | KMOD-01, KMOD-02, KMOD-03, KMOD-04 | 4 |
| 13 | INGEST-03, INGEST-05, INGEST-06, INGEST-07, INGEST-08 | 5 |
| 14 | KMOD-05, INGEST-01, INGEST-02, INGEST-04, ENH-01 | 5 |
| 15 | RETR-01..07, ENH-02 | 8 |
| 16 | EXPO-01..04, ENH-03, ENH-04 | 6 |

**Total:** 28/28 v1 requirements mapped ✓（无孤儿、无重复）

## Notes

- **Phase 编号接续**：v0.2.0 止于 Phase 11，本里程碑从 Phase 12 起连续编号。
- **KMOD-05 归属 Phase 14**：diff 归档表结构可在 Phase 12 随 migrations 建好，但"归档落库"能力随 DiffArchiver 在 Phase 14 交付验证，故映射到 14。
- **ENH 类就近并入**：ENH-01（diff→chunk 符号级）随 DiffArchiver 落在 Phase 14；ENH-02（LLM 复评）是检索结果的二阶段处理落在 Phase 15；ENH-03（前端只读页）与 ENH-04（as-of 工具参数）属暴露面落在 Phase 16。ENH-01 若符号级对齐受阻，可按研究建议降级为文件级起步（不阻塞其他需求），符号级在 phase 内作为明确交付项跟踪。
- **研究标记**：Phase 15 需小范围深入研究（时间衰减参数 α/half-life、中文 query ↔ 英文 diff 跨语言召回质量，依赖 20–50 条评测集）；Phase 12/13/14/16 为本仓库既有模式拼装（ChunkEdge 范式 / indexer 摄取范式 / McpToolView + BaseNode 入口范式），标准实现即可。
- **关键防线（来自 PITFALLS）**：检索侧 `is_latest` filter 是版本下线第一道防线（删除只是优化）；有效性过滤埋进 GraphStore 接口而非靠约定；摄取入口只接线、不各写触发逻辑；payload 权限字段与 natural key 规则在 Phase 12–13 一次定对。

---
*Created: 2026-06-11*
*Milestone: v0.3.0*
