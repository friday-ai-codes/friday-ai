# Phase 14: 全触发点接入与 diff 归档 - Context

**Gathered:** 2026-06-11
**Status:** Ready for planning
**Mode:** Smart discuss — infrastructure/pipeline phase（自动判定，决策留给执行）

<domain>
## Phase Boundary

六类触发点全部接通，编码产出的全量 diff 归档落库并与既有代码图谱打通，需求→方案→代码全链路在图中闭环。

本阶段交付（KMOD-05, INGEST-01, INGEST-02, INGEST-04, ENH-01）：
- workflow 触发点：`ai_plan_generation` 节点产出技术方案时自动摄取需求与方案实体并建 `HAS_PLAN` 边（含方案审批通过事件）
- 编码完成回调触发点：TaskResult/CodingTask 回调时经 git platform 拉取全量 diff 归档落库（DiffArchiver：unidiff 解析到文件级、关联 commit SHA / MR URL / 仓库元数据、超大 diff 压缩存储），摄取 code_change 实体并关联到对应方案/需求
- 飞书触发点：工作项关键事件（产出方案/触发编码/工作项更新）摄取带事件时间的快照（名称、描述、自定义字段、PRD 与技术方案文档正文、关联工作项）
- ENH-01：code_change 经 `MODIFIES_CHUNK` 边（file+symbol+commit_sha 懒解析）关联 ChunkRegistry，可反查"这个函数被哪些需求改过"；若符号级对齐受阻可按 ROADMAP Note 降级为文件级起步（符号级在 phase 内作为明确交付项跟踪）
- 大 diff 防线：万行级 diff（含生成文件）分层切块、生成文件跳过、批量写入，经大 diff 夹具验证

不在本阶段：检索（Phase 15）、入口暴露（Phase 16）。

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — pipeline/infrastructure phase。以 ROADMAP Phase 14 success criteria 与 Phase 12/13 已交付契约为准。

已锁定的硬约束（不可偏离）：
- 复用 Phase 13 统一摄取管线：触发点只构造 IngestionRequest/normalizer + `aschedule_ingestion`，不各写摄取逻辑
- 图写入只走 GraphStore；payload schema 以 `knowledge/collection.py` 常量为唯一事实源
- diff 归档表（KMOD-05）按 Phase 12 预留方式本阶段随 migration 建（CodeChangeArchive 当时定案不建 stub，本阶段定型）
- `MODIFIES_CHUNK` 边 target_chunk_id 不做 FK（Phase 12 XOR 约束已就位）；懒解析（file+symbol+commit_sha 记录即可，不强制实时对齐）
- Git 平台凭证走既有 git_platform service 层（数据库加密凭证，不读 env）
- 生成文件跳过、超大 diff 压缩存储（PITFALLS 防线）

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- Phase 13 全套摄取基建：`knowledge/ingestion.py`（aschedule_ingestion / ingest_events / apply_edge_specs）、`chunking.py`、`vector_ops.py`、`sources/` normalizer 注册表
- `server/workflows/nodes/ai/plan_generation.py`：`ai_plan_generation` 工作流节点（workflow 触发点挂点）
- `server/subagent/api/callbacks.py`：编码完成回调入口（TaskResult/CodingTask）
- `server/services/git_platform/`：git 平台集成（拉取 diff/MR 元数据）
- `server/code_relations/models.py` ChunkRegistry（MODIFIES_CHUNK 目标）
- `server/services/feishu.py` / `feishu_doc.py`：飞书工作项与文档读取
- `server/knowledge/models.py` EdgeRelation.MODIFIES_CHUNK 枚举占位（Phase 12 已留）

### Established Patterns
- 触发点接线范式（Phase 13 已验证）：行级锚点 + 异常全吞不阻塞宿主 + 单元测试断言投递
- unidiff 解析、压缩存储参照既有 diff 处理（如有）；大文本分层切块参照 chunking.py
- 测试：宿主套件零回归 + knowledge 套件 + 大 diff 夹具

### Integration Points
- `workflows/nodes/ai/plan_generation.py` 成功产出方案处（+ 审批通过事件处）
- `subagent/api/callbacks.py` 编码完成回调成功路径
- 飞书事件处理处（工作项更新/方案产出/触发编码）
- `knowledge/` 内新增 diff_archive 模型与 normalizer（sources/）

</code_context>

<specifics>
## Specific Ideas

ENH-01 降级路径已获 ROADMAP 授权：符号级受阻 → 文件级起步不阻塞，符号级仍为本阶段明确交付项跟踪。

</specifics>

<deferred>
## Deferred Ideas

None — discuss skipped（infrastructure phase）。

</deferred>
