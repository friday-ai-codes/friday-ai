---
gsd_state_version: 1.0
milestone: v0.7.0
milestone_name: 方案编排
status: in_progress
last_updated: "2026-06-16T01:00:00.000Z"
last_activity: 2026-06-16 — Phase 36 complete (passed + reviewed + fixed)
progress:
  total_phases: 7
  completed_phases: 1
  total_plans: 3
  completed_plans: 3
  percent: 14
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-12 after v0.3.0 milestone)

**Core value:** 让团队"开箱即用、安全地"把需求自动变成代码；v0.7.0 把「需求 → 一份高质量多仓主技术方案」做成可复用的 map-reduce 多 agent 编排引擎（拆分 → 路由 → 召回 → 澄清 → 并行调研 → 架构师融合），并立 canonical `TechnicalPlan` 脊柱、编排状态机 `PlanSession` 与事件 taxonomy——作为 v0.8 多仓编码、v0.9 SDD 的方案底座。
**Current focus:** Phase 37 — canonical TechnicalPlan + TechnicalPlanService + 旧路径软链/迁移

## Current Position

Phase: 37 (next) — Phase 36 complete
Plan: —
Status: Phase 36 ✅ complete (verification passed, code review fixed: CR-01/WR-01/IN-01/IN-02)
Last activity: 2026-06-16 — Phase 36 executed + verified + reviewed + fixed

## Milestone Overview (v0.7.0 — Phases 36–42)

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 36 | 前置修复 + 编排引擎骨架 + PlanSession 状态机 | PF-01, PF-02, ORCH-01, ORCH-02 | ✅ Complete |
| 37 | canonical TechnicalPlan + TechnicalPlanService + 旧路径软链/迁移 | PLAN-01, PLAN-02, PLAN-03 | Not started |
| 38 | 路由 + 召回接入 | ROUTE-01, RECALL-01 | Not started |
| 39 | 并行调研子 agent | RESEARCH-01, RESEARCH-02, RESEARCH-03 | Not started |
| 40 | 架构师融合 + MergedPlan + PlanValidator + 跨仓依赖 | MERGE-01, MERGE-02, MERGE-03 | Not started |
| 41 | HITL 澄清 + 事件 taxonomy + 工作流入口 | CLARIFY-01, ENTRY-01, EVENT-01 | Not started |
| 42 | Chat 入口薄封装 | ENTRY-02 | Not started |

**Execution order:** 36 → 37 → 38 → 39 → 40 → 41 → 42（严格顺序）。依赖链：前置修复+引擎骨架(36) → canonical 方案脊柱(37) → 路由+召回(38) → 并行调研(39) → 架构师融合(40) → 澄清+事件+工作流入口(41) → Chat 入口(42)。每个 phase 都建立在前序编排骨架之上。

**前置修复（PREFLIGHT，作 Phase 36 内 blocking 必修）:** PF-01（`search_code` 工具名漂移 + 未知工具静默 continue）、PF-02（`verify_plan` schema 漂移 `tasks` vs `execution_plan`）——方案质量 + PlanValidator 的地基，开工前必修。

**UI 触面:** Phase 41（工作流入口：工作流节点 + 可能的 plan-session 视图）、Phase 42（Chat 入口薄封装：对话发起编排）标 UI hint。

**关键约束:** INV-2（方案可追溯到 `WorkItem`，chat 自然语言允许 null 但显式标记）、INV-5（对外暴露 progress/trace 事件非模型私有 CoT）、INV-6（方案解析/创建只经 `TechnicalPlanService`，禁旁路写表）。已锁决策：filter_then_container 调研、architect_subagent 融合 + 结构化 MergedPlan + PlanValidator、工作流+Chat 双入口复用同一 engine（工作流先行）、事件 taxonomy 本里程碑即落。

**设计底座:** `.planning/ROADMAP-vNext.md §v0.7`（流水线 6 段/概念/现状坐标/已确认决策）、`.planning/DOMAIN-MODEL.md` §5（canonical TechnicalPlan + service + 迁移规则）/§6（编排状态机 + 子任务级状态 + 可靠恢复规则 + SDD 扩展点）/§7（PartialPlan/MergedPlan/PlanValidator schema）/§14（PlanSession 转移表）/§15（事件 payload 规格）、`.planning/PREFLIGHT.md`（PF-01/02）。

## Milestone Overview (v0.6.0 — shipped 2026-06-15)

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 27 | 飞书接口前置修复 | FIX-01..04 | ✅ Complete |
| 28 | WorkItem 脊柱 + 单一 upsert 入口 | WIT-01..05 | ✅ Complete |
| 29 | 评论事件流 | CMT-01..02 | ✅ Complete |
| 30 | Document + REFERENCES 边 | DOC-01..02 | ✅ Complete |
| 31 | Release 账本 + Bitable adapter 骨架 | REL-01..02 | ✅ Complete |
| 32 | 一键摄取编排 | ING-01 | ✅ Complete |
| 33 | 历史 diff 冻结 + bi-temporal 失效 | HDIFF-01..02 | ✅ Complete |
| 34 | 评论入图 + 片段→需求反查 | RREF-01..02 | ✅ Complete |
| 35 | 截图识别需求 | VIS-01 | ✅ Complete |

## Milestone Overview (v0.4.0 — shipped 2026-06-13)

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 17 | 变量引用链路修复 | VAR-01..04 | ✅ Complete |
| 18 | 执行引擎状态机修复 | ENG-01..05 | ✅ Complete |
| 19 | 节点定义单一事实源 | SSOT-01..03 | ✅ Complete |
| 20 | 保存即合法与模板修复 | VAL-01..03, TPL-01..03 | ✅ Complete |
| 21 | 触发模型与执行可观测 | TRIG-01..03, OBS-01..03 | ✅ Complete |

## Performance Metrics

**Milestone v0.3.0:**

| Metric | Value |
|--------|-------|
| Phases completed | 5/5 |
| Plans completed | 23/23 |
| Requirements delivered | 28/28 |
| Phase 12 P01 | 10min | 3 tasks | 10 files |
| Phase 12 P02 | 12min | 3 tasks | 2 files |
| Phase 12 P03 | 8min | 3 tasks | 7 files |
| Phase 13 P13-02 | 12min | 2 tasks | 3 files |
| Phase 13 P13-03 | ~16min | 3 tasks | 7 files |
| Phase 14 P02 | ~8min | 2 tasks | 4 files |
| Phase 14 P03 | 16min | 3 tasks | 4 files |
| Phase 14 P04 | 14min | 2 tasks | 4 files |
| Phase 14 P05 | 12min | 2 tasks | 3 files |
| Phase 14 P06 | 14min | 2 tasks | 5 files |

**Milestone v0.5.0:**

| Metric | Value |
|--------|-------|
| Phase 22 P01 | ~9min | 2 tasks | 5 files |
| Phase 22 P02 | ~6min | 2 tasks | 3 files |
| Phase 22 P04 | ~13min | 2 tasks | 8 files |
| Phase 22 P06 | ~9min | 2 tasks | 2 files |
| Phase 22 P03 | ~35min | 3 tasks | 8 files |
| Phase 23 P01 | ~10min | 2 tasks | 3 files |
| Phase 23 P02 | ~30min | 2 tasks | 7 files |
| Phase 23 P03 | ~25min | 2 tasks | 2 files |
| Phase 23 P04 | ~20min | 2 tasks | 5 files |
| Phase 24 P01 | ~22min | 2 tasks | 4 files |
| Phase 24 P02 | ~18min | 2 tasks | 4 files |
| Phase 24 P03 | ~12min | 2 tasks | 4 files |
| Phase 24 P04 | ~10min | 2 tasks | 5 files |
| Phase 25 P01 | ~9min | 2 tasks | 5 files |
| Phase 25 P02 | ~5min | 2 tasks | 5 files |
| Phase 25 P03 | ~13min | 2 tasks | 4 files |
| Phase 25 P04 | ~10min | 2 tasks | 2 files |
| Phase 26 P01 | 20 | 2 tasks | 4 files |
| Phase 26 P05 | ~12min | 3 tasks | 4 files |
| Phase 26 P02 | ~15min | 3 tasks | 4 files |
| Phase 26 P03 | ~25min | 3 tasks | 7 files |
| Phase 26 P04 | ~9min | 3 tasks | 9 files |
| Phase 26 P06 (gap) | ~20min | 2 tasks | 7 files |
| Phase 27 P27-01 | ~15min | 3 tasks | 3 files |
| Phase 27 P27-02 | 12min | 3 tasks | 2 files |
| Phase 27 P27-03 | ~5min | 2 tasks | 2 files |
| Phase 28 P28-01 | ~12min | 3 tasks | 12 files |
| Phase 29 P29-01 | ~8min | 2 tasks | 4 files |
| Phase 29 P02 | 18min | 2 tasks | 5 files |
| Phase 30 P01 | 10min | 2 tasks | 4 files |
| Phase 30 P02 | 25min | 2 tasks | 4 files |
| Phase 30 P30-03 | ~20min | 2 tasks | 3 files |
| Phase 31 P31-01 | 5m | 3 tasks | 4 files |
| Phase 31 P02 | 7m | 3 tasks | 4 files |
| Phase 31 P03 | 6m | 3 tasks | 5 files |
| Phase 32 P01 | 25m | 2 tasks | 7 files |
| Phase 32 P02 | 40m | 2 tasks | 9 files |
| Phase 32 P03 | 12m | 3 tasks | 7 files |
| Phase 33 P01 | 30min | 3 tasks | 12 files |
| Phase 34 P34-01 | 22min | 3 tasks | 10 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table; v0.2.0 full phase detail in `.planning/milestones/v0.2.0-ROADMAP.md`.

- [Phase 12]: EntityKind/EdgeRelation 枚举字面值锁死（kind 进 uuid5 PK 派生，改名即数据迁移）；MODIFIES_CHUNK 为 Phase 14 占位
- [Phase 12]: generate_entity_id 拼接格式 kind:source_kind:source_id + 独立 KNOWLEDGE_NAMESPACE；CodeChangeArchive 不预建（Phase 14 自带 migration）
- [Phase 12]: GraphStore 递归 CTE anchor path 不含起点（环回到起点计 1 次后终止）；direction=both 多跳与 MySQL 后端显式 NotImplementedError
- [Phase 12]: payload schema 8 索引字段第一天定型（含权限维度），回归测试锁键集合；ensure 不匹配 raise 绝不删库，重建唯一入口 rebuild_delivery_knowledge --yes 命令
- [Phase ?]: 13-02: hash 相等绝不产生新版本——needs_revector 走 revectorize_version 补写向量，不建版本行不置 invalid_at
- [Phase ?]: 13-02: 边非严格同事务——apply_edge_specs 幂等可重入，skipped/needs_revector 事件仍执行边阶段自愈
- [Phase ?]: 14-02: 截断 helper truncate_diff_lines 放 base.py 模块级双客户端共用；既有 get_merge_request_diff 内联截断不动（零回归）
- [Phase ?]: 14-02: base get_branch_diff 抽象化分两步——Task 1 NotImplementedError 占位、Task 2 双实现齐备后转 @abstractmethod，避免瞬时打破 GitHubClient 实例化
- [Phase 14]: 14-04: 审批事件 source_id 恒为生成节点 key（OQ-2），接线处换算、normalizer 单纯
- [Phase 14]: 14-04: workflow_plan normalizer 兼容 trigger_data.raw_payload 与 payload 双键取飞书工作项锚
- [Phase 14]: 14-05：飞书三 handler 只投三元组 ID（取材全在 normalizer 后台），文档拉取失败降级为缺段快照 + warning
- [Phase ?]: 14-06: workflow mr_results 回退键按引擎实际落点 merge_requests（checker 建议的 succeeded_repos 实为计数 int）
- [Phase ?]: 14-06: workflow 仓库归属经 output_data.pending_sessions 匹配 + session.repo_url 兜底（双源均服务端写入，T-14-22）
- [Phase 22]: 22-01: 排除判定唯一入口 services.exclusion.is_excluded(repository_id, rel_path)，Wave 2 plans 直接引用不得另起炉灶；失败模式二分（构造期非法 regex fail-loud / 运行期 fail-closed True + exclusion.blocked 埋点）
- [Phase 22]: 22-01: dir 规则 = 相对仓库根前缀（目录本身 + 子树）；glob 用 fnmatch.translate 大小写敏感跨 / 匹配；per-repo source=global+enabled=False 行作为关闭全局默认的 override 标记
- [Phase 22]: 22-01: BUILTIN_GLOBAL_DEFAULTS 内置安全默认即使无任何配置也生效（向后兼容 + 开箱即用，per D-04）
- [Phase 22]: 22-02: scan_directory 用注入式 is_excluded_rel 回调（Callable，非 matcher 对象）保持纯函数无硬依赖避免循环导入；扫描期回调异常 fail-closed（跳过文件/剪子树）
- [Phase 22]: 22-02: indexer full + incremental 两路径预取 build_matcher_for_repo（async）并注入同步 scan_directory，被排除文件从源头不进 files_to_process/local_hashes（存量清理留 Phase 23）
- [Phase 22]: 22-02: PF-04 关闭——scan_directory 不再谎称 .gitignore，注释/docstring 如实描述「目录名 + 扩展名白名单 + 排除匹配器」
- [Phase 22]: 22-06: MCP HTTP 直读面（grep/get_file/list/find_related）挂接单一匹配器 fail-closed；get_file 对 requested+resolved 双判定防后缀绕过；grep 过滤后重算 total/files_with_matches 避免泄漏存在性；matcher 构造异常用 _FailClosedMatcher 兜底（排除一切，不放行）
- [Phase 22]: 22-06: 只在 view 层过滤（不改 repo_mirror.py 助手），不重复 22-03 已覆盖的 search_rag_chunks；为保持最小 diff 未对 views.py 跑整文件 ruff format（预存 I001/非规范，超范围）
- [Phase 22]: 22-04: serialize_rules_for_repo 绝不返回空（异常/无配置回退 BUILTIN_GLOBAL_DEFAULTS），不下传 = 容器面裸奔；matcher 与容器下传共用 _resolve_effective_specs（单一合并真相，_load_specs_from_db 保留别名）
- [Phase 22]: 22-04: 两条编码派发路径（chat build_dispatch_metadata + workflow _run_repo_coding）均无条件注入 env_FRIDAY_TASK_EXCLUDE_PATTERNS（仅规则模式，无凭证）
- [Phase 22]: 22-04: task 容器侧独立轻量匹配器（不 import server，语义对齐 dir/glob/regex），prune_excluded clone 后删被排除文件、跳过任意层级 .git/（T-22-15）；删除重试 chmod +w → 持久失败抛 ExclusionPruneError 使 setup 失败（fail-closed，T-22-16，绝不残留可读）
- [Phase 22]: 22-03: search_rag 是 RAG 单一 chokepoint——每 repo 预取 matcher、收集前过滤，覆盖 chat/agent/workflow 所有经 HybridSearchService 的调用方；图谱邻居（hop1/hop2/cross-repo）在 _search_graph_capable 预先剔除（渲染+返回字段双覆盖），无 repo 归属对 repo_ids matcher 做 any 命中（保守 fail-closed）
- [Phase 22]: 22-03: browse_file_content 入口拒读 + fuzzy resolved_path 复判防后缀绕过（T-22-09），返回 chunks=[]+error 无明文；list_space_structure 文件树过滤；search_repository_code 兜底过滤防未来旁路回流；matcher 构造/判定异常一律 fail-closed
- [Phase 22]: 22-03: ⚠️ 旁路读取面未覆盖（需收尾 plan）——index_views.py _vector_search 与 deprecated layered_search._l3_hybrid_search 直读 BranchAwareSearchService.search 不经 search_rag，被排除文件可漏出（见 22-03 SUMMARY Threat Flags / deferred-items.md）
- [Phase 22]: 22-GAP: ✅ 上述 index_views 旁路面（现 CodeSearchView._search，认证 REST `POST /api/repositories/<id>/search/`，前端 searchCode 在用）已闭合——返回前挂 build_matcher_for_repo + is_excluded fail-closed（构造失败整仓库丢弃 / 单项判定异常丢弃 + log surface=code_search，total 由过滤后集合重算），补对称守护测试（56d230553）；layered_search._l3_hybrid_search 经 22-VERIFICATION 研判为 deprecated 内部 helper、生产不可达，非缺口
- [Phase 23]: 23-01: 统一删除入口 services.purge.purge_file(repository_id, rel_path) + PurgeResult，是 Qdrant 主+overlay / FileIndex / ChunkRegistry(+ChunkEdge) / codegraph 五面的唯一删除收口点；Wave 2/3 清理与对账一键清理须复用，不得另起删除逻辑。best-effort 逐面隔离 + PurgeResult.failures（不静默假装全净）
- [Phase 23]: 23-01: PF-03 收口——run_incremental_index / run_git_diff_index 的 DELETE 分支收敛到 purge_file（消除「只删 Qdrant 不删 FileIndex/ChunkRegistry」孤儿）；PF-05 收口——overlay 删除遍历 RepositoryBranchIndex.collection_name 逐删 file_path
- [Phase 23]: 23-01: ChunkRegistry 删除务必走 queryset.adelete() 逐实例触发 pre_delete 信号联动清边（绝不绕过信号）；codegraph 分支枚举归一化（is_base/branch_name==base → ""，feature 用原名）避免 RepositoryBranchIndex(base="main") 与 codegraph(base="") 口径漂移漏删；保留 indexer 既有 codegraph 孤儿清理块（精确单分支删除，与 purge_file 幂等不冲突）
- [Phase 23]: 23-01: ⚠️ purge_file 暂未覆盖 repo_summaries / index_nodes 面（DOMAIN §9.3 普通列其余面），后续清理 plan 如需可扩展
- [Phase 23]: 23-02: compute_reconciliation = FileIndex ∪ ChunkRegistry file_path 双源并 ∩ 复用 22 build_matcher_for_repo；degraded 仅由匹配器构造抛错触发（单文件 is_excluded 运行期异常由 matcher 内部 fail-closed 命中兜底，不污染 degraded），W3 贯通 dataclass→serializer→client 不谎报「已一致」假干净
- [Phase 23]: 23-02: run_cleanup 逐差异文件调 23-01 purge_file（best-effort 逐文件隔离），终态 failures 非空→failed 否则 completed；清理后 best-effort 后台调度 repo_summaries+repo_index_nodes 重建（可重建聚合，失败不致命）
- [Phase 23]: 23-02: CleanupRun 持久化（status/mode/match_count/failures/sensitive/error，(repository,-started_at) 索引取最近一次）；清理经 run_in_background 后台派发（API 先建 running 行拿 run_id 立即 202，D-04/T-23-08），状态端点回流结果（含敏感 unscrubbed/caveat，W1/W2）
- [Phase 23]: 23-02: 敏感模式懒导入契约 services.sensitive_purge.purge_sensitive_planes(repository_id, purged_paths)（23-03 提供，普通模式零依赖）；未就绪→failures + CleanupRun.error，普通清理结果不受损。审计事件 purge.started/purge.completed（mode/repository_id/match_count/failures）
- [Phase 23]: 23-03: 敏感清理委托落点 services.sensitive_purge.purge_sensitive_planes —— 四面 helper（CodeChangeArchive/TaskResult/ActionLog/loose-text）逐面 try/except 隔离，返回 dict {scrubbed:{plane:{scrubbed,deleted}}, unscrubbed, caveat, errors} 落 CleanupRun.sensitive
- [Phase 23]: 23-03: CodeChangeArchive file 级 scrub recompute **不调 parse_diff_files**（其解析平台 MRDiffFile 对象而非 unified-diff 文本，W4 类型不符）；改为过滤既有 files JSON 列表重算计数 + 按 `diff --git a/old b/new` 边界切段剔除目标文件 diff（new/old 任一命中即剔除），decompress_diff/compress_diff 重压缩；仅含被排除文件整行删，含他文件保留他文件部分（T-23-13 不误删）
- [Phase 23]: 23-03: TaskResult/ActionLog 关联键 = _normalize_repo_url(session.repo_url)==_normalize_repo_url(repo.git_url)（去 .git/末尾斜杠/小写）；归一不匹配的记录完全不动（T-23-12 保守，宁漏勿误删他仓产物）
- [Phase 23]: 23-03: message parts/content 无 repo 关联键（Conversation 绑 Project 非 Repository）→ best-effort 子串脱敏（_redact_value 只替换命中被排除路径的 str 叶子，保留同载荷其余字段，不整库清空 T-23-13）；prompt_snapshot/backups/git_objects 记 unscrubbed + SENSITIVE_PLANES_CAVEAT 如实声明 git object/历史/备份不承诺物理消失（§9.1 T-23-11，绝不假装清除）
- [Phase 23]: 23-04: 前端 web/src/api/reconcile.ts + ReconcilePanel.vue 兑现 EXCL-06 可见闭环；degraded 前端落地——degraded=true → 显式『对账不可信』警示 + 禁用双清理按钮、绝不渲染空态/已一致（W3）；普通/敏感双入口分离（§9.2），敏感强确认直取 §9.1『不可逆 + 仅清 Friday 派生/操作记录可定位内容，不承诺从 git 历史或备份物理消失』
- [Phase 24]: 24-01: 确定性检测器 services.sensitive_detect.detect_sensitive_files(repository_id, repo_path) async 入口——独立有界遍历（**不**复用 indexer 扩展名白名单扫描，否则漏 .env/id_rsa/*.pem）；遍历跳过集仅 .git/node_modules，**不**纳入 BUILTIN dir 默认（.ssh/secrets 恰是要识别的目标，偏离 PLAN 措辞 Rule 1）；1MiB+二进制 NUL 嗅探+symlink 跳过（T-24-02）
- [Phase 24]: 24-01: reason 经唯一构造入口 _redact_reason(kind, line_no) 只写「类型+行号」，绝不回填命中文本/group 值（T-24-01）；审计 sensitive.detected 仅计数/severity。内容扫描模块级编译正则 _SECRET_PATTERNS（私钥块/AWS AKIA+赋值/GitHub gh[pousr]_/Slack xox/通用 api_key|secret|password|token 赋值）+ 高熵 Shannon≥4.0 跳注释行；content 命中即 real_secret，高熵单独命中降 likely_sensitive
- [Phase 24]: 24-01: 持久化单一入口 _upsert_suggestion 经 aupdate_or_create(repository_id, path)——dismissed 仅在升级为 real_secret（旧非 real_secret）时重置 pending 打扰，否则保留 dismissed 不复扰；accepted 保留不动；severity 合并取最高（real_secret>likely_sensitive>config_review），detector 有内容命中取 content 否则 heuristic
- [Phase 24]: 24-01: 文件名启发式复用 services.exclusion.BUILTIN_GLOBAL_DEFAULTS 的 glob 基线（_build_filename_globs 仅 glob 型，fnmatch.translate + re.IGNORECASE，basename 兜底 BL-01），命中返回 config_review 基线
- [Phase 24]: 24-02: run_full_index FINALIZING 末尾（_refresh_tree_facts 之后、return success 之前）经 run_in_background(lambda: detect_sensitive_files(self.repository_id, repo_path), name="sensitive-detect:{id}") best-effort 派发——**不** await 结果，整段 try/except 吞派发异常 warning sensitive_detect_dispatch_failed，检测失败/派发失败绝不阻断索引 success（D-04/T-24-05）。触发 guard 沿用 auto-after-index 范式：复刻派发模板 helper + 源码 token 漂移 guard（不跑重依赖完整索引）
- [Phase 24]: 24-02: 可选 LLM 二分类 services.sensitive_detect.classify_ambiguous_files(repository_id, candidates: list[AmbiguousCandidate])——确定性段始终启用、LLM 段对 ambiguous 子集可选；aresolve_or_error→ProviderMissingError / 缺 default_model / 任何调用解析异常一律 return 0 graceful 退化不冒泡（T-24-07），确定性结果不依赖 LLM 成功
- [Phase 24]: 24-02: 隐私加固（偏离 PLAN『截断 N 字符』措辞 Rule 2）——_build_llm_feature 只送「文件名+扩展名+has_sensitive_keyword 布尔」，sample_text 正文仅本地计算布尔信号绝不进请求；real_secret 强命中排除出候选；新增 _redact_llm_reason 对 LLM 理由做高熵串+_SECRET_PATTERNS 替换 [已脱敏] 服务端兜底（T-24-06 纵深防御）。命中产 likely_sensitive/detector=llm 经统一 _upsert_suggestion 入库，仅 pending 绝不建规则/删数据（T-24-08）
- [Phase 24]: 24-03: 敏感建议 REST API 走独立 APIView + 显式 `<uuid:repository_id>/sensitive-suggestions/`(list) + `.../{suggestion_id}/action/`(action) 路由（对齐 Phase 22 exclusions idiom）；SensitiveFileSuggestionSerializer 全字段 read_only（状态仅经专用 action 改，禁直接 PATCH，T-24-09/10）；list 默认仅 pending、?status=all 全量，severity 优先级 Python 侧映射排序（real_secret>likely_sensitive>config_review）+ detected_at desc；accept 用 aget_or_create（唯一约束含 source）实现幂等避免二次 accept 500（T-24-12）→ 建 RepoExclusionRule(source=ai_suggested,rule_type=glob) + 标 accepted + invalidate_matcher_cache；accept 绝不删数据（NEVER silent-delete，response 仅附 cleanup_available 引导，删除仍由 Phase 23 reconcile/cleanup 显式触发 T-24-10）
- [Phase 24]: 24-04: 前端 sensitiveSuggestionsApi（list/accept/dismiss）+ SensitiveSuggestionsPanel.vue 兑现 EXCL-03 用户可见闭环；real_secret 列表顶部 destructive 横幅 + 行内危险底色双重突出（data-testid=real-secret-alert 供测试稳定定位，T-24-15）；accept 经 useConfirmDialog 二次确认明示「新增排除规则、不会自动删除已索引内容、需在清理面板显式执行」（T-24-14），dismiss 无确认（无破坏性）；accept/dismiss 后 invalidate 自身建议 key + repository-exclusions key 使新建 ai_suggested 规则即时显现于排除面板；前端保序渲染后端已排序结果（不前端重排）；面板 prop 命名 repoId（依 PLAN，区别既有面板 repositoryId）；守护测试以真实 zh-CN.json 作 messages 断言告警/确认措辞防被改空（T-24-13 reason 仅渲染脱敏文本）
- [Phase 25]: 25-01: ChunkRegistry 行号回填无新 migration（line_start/line_end + chunkreg_line_range_valid 约束已存在于 0003/0004，per D-02）；行号直接取 CodeChunk.start_line/end_line（1-based 闭区间），与同处写入 Qdrant payload start_line/end_line 同源保证两侧一致；ChunkRegistryRow TypedDict 新增 line_start/line_end 键作 _build_points→_bulk_upsert 同源契约（mypy 拦截漏传）
- [Phase 25]: 25-01: _bulk_upsert_registry_atomic update 判定显式纳入「行号变化」（obj.line_start/line_end != row[...]），避免仅行号位移、hash/路径/index 未变时漏更新（否则 25-02 反查命中错位，T-25-03）；错乱区间（line_end<line_start）由既有 CheckConstraint 拒绝 IntegrityError（T-25-01），indexer 不静默落错；None 行号合法落 NULL（历史/非 AST 回退兼容，不强制回填历史）
- [Phase 25]: 25-02: find_chunk_at(repository_id, file_path, line, *, branch_name) 反查入口先 build_matcher_for_repo 再查询——构造失败/路径归一 None/is_excluded 命中（含判定异常）一律 fail-closed 返回空 + log_exclusion_blocked(surface=chunk_at)，绝不放行（T-25-04，对齐 rag_search 范式）；查询条件含 line_start/line_end__isnull=False（NULL 历史 row 天然不命中）+ 闭区间 lte/gte；多 chunk 命中返回全部，按区间宽度 (line_end-line_start) 升序、次序稳定按 chunk_index（最具体优先，per Claude's Discretion）；仅读 ChunkRegistry 不触 Qdrant
- [Phase 25]: 25-02: GET /api/repositories/<id>/chunk-at/?path=&line=&branch_name= 走独立 ChunkAtView APIView（adrf）+ 显式路由（router include 之后，UUID 通配安全），IsAuthenticated 保护（T-25-06）；被排除文件与无命中对外同形返回 {"chunks": []} 200 不泄漏存在性（T-25-05）；path 必填、line 正整数校验（<1/非法→400），不存在仓库→404；service 不抛 past view（normalize None→空，T-25-07）
- [Phase 25]: 25-03: commit 历史索引专用边界 Repository.commit_index_boundary_sha（migration 0035 AddField，nullable 无回填）**独立于** last_indexed_commit_sha（代码 chunk 边界），绝不复用避免口径串味；index_commits 仅 upsert 成功才推进 boundary 到 HEAD（无新 commit/embedding 缺失/upsert 失败均不推进，绝不丢 commit，T-25-09）
- [Phase 25]: 25-03: commit 文档落主 collection + payload kind=commit（与代码 chunk 同检索面经既有 search_rag 召回、可区分/过滤，无需改检索）；确定性 uuid5(ns, repo_id:sha) point id + 合成 file_path=.friday/commits/{sha}+chunk_index=0 保既有去重 key 唯一且不被排除规则误命中（T-25-10）；变更摘要复用 Phase 22 build_matcher_for_repo/is_excluded fail-closed 剔除被排除文件、只含路径不内联 diff 正文（T-25-08）
- [Phase 25]: 25-03: 增量 git log boundary..HEAD，boundary 失效（force-push/rebase 报错）回退首轮 --max-count=COMMIT_INDEX_FIRST_RUN_CAP(500)+--no-merges bounded 全量（T-25-11）；--format 用 git 占位符 %x00(字段)/%x1e(记录) 而非内嵌真实 NUL（子进程参数不可含 NUL，否则 ValueError: embedded null byte），解析侧按实际字节切分；git diff-tree 加 --root 纳入根 commit；hybrid 判定/sparse 生成复用 IndexerService._is_hybrid_enabled/_generate_sparse_vectors 不另写
- [Phase 25]: 25-04: commit 索引唯一挂接点 services.indexer._run_commit_index——仅 base 路径（if not branch:）在 _run_sensitive_detection 之后、finally rmtree(temp_dir) 之前 await（沿用 Phase 24 BL-01 时序：index_commits 需读真实克隆 git 历史，绝不后台派发去遍历即将删除的目录）；全量+增量均流经此函数，首轮/增量区分由 index_commits 内部 commit_index_boundary_sha 处理；整段 try/except 吞异常仅 warning commit_index_dispatch_failed，commit 索引失败/缺供应商绝不阻断 return index_result 的 success 终态（best-effort，对齐 _run_sensitive_detection / T-25-12）
- [Phase 25]: 25-04: 召回端到端守护无真实 Qdrant——捕获 index_commits upsert 的 commit point，mock BranchAwareSearchService.search 对其按 query substring 命中 content 返回，模拟语义召回；build_matcher_for_repo 用真实实现（仅 builtin 全局默认）真正经过 search_rag 排除/去重 chokepoint，验证合成 file_path=.friday/commits/{sha} 不被排除可召回、被排除文件不泄漏（T-25-13）、增量只新增（T-25-14）
- [Phase 23]: 23-04: 派发后双查询模式——mutation 成功 → 开启第二个 useQuery 轮询 getCleanupStatus（refetchInterval=(q)=> status==='running'?2000:false）+ invalidate reconcile 观察归零；CleanupRun.sensitive.unscrubbed/caveat 如实渲染真实后端结果（非静态文案，W1/W2）。测试以真实 zh-CN.json 作 i18n messages 守护威胁缓解措辞不被改空；W5 vue-tsc 门禁真实生效（spec createI18n messages 类型不符被捕获修复）
- [Phase ?]: 26-01: 实例凭证落在 repositories app，表 git_instance_credentials，host 唯一 + Fernet 加密 token
- [Phase ?]: 26-01: 凭证解析单一入口 resolve_git_token_sync——per-repo token 优先 → 实例池 host fallback → None，Wave 2 统一调用
- [Phase ?]: 26-05: search_rag_chunks 多仓参数（repository_ids/all_repositories/max_repos），mirror grep；多仓经 search_rag chokepoint 每仓 fail-closed，结果按 item.repository_id 标注来源
- [Phase 26]: 26-02: clone/index、bare 镜像 fetch、图谱克隆三路径统一经凭证解析器取 token（aresolve_git_token / resolve_git_token_sync），消除内联 GitCredential→decrypt_value；per-repo 优先、host 实例池 fallback；同 host 多仓共享一份凭证；token 仅进单次 clone/fetch argv 不入日志
- [Phase 26]: 26-04: 实例凭证 REST CRUD——读/写序列化器分离（read 只含 has_token 布尔无明文 token、write access_token=write_only）；GitInstanceCredentialsView/DetailView 走 IsSuperUser，encrypt_value 写入、空 token 的 PATCH 不清空既有 token、日志仅记 host/has_token；host 唯一性视图层 aexists+IntegrityError 双兜底给中文报错；路由字面段须在 router include 之前；base-branch 校验改经 aresolve_git_token（实例池仓库也可校验），TestConnection 验证入参 token 流程不变；前端 /admin/git-credentials 管理页 token password 不回填、留空=不改、提交清空，列表仅 has_token 徽标；守护测试后端 8 + 前端 2 全绿（DB 密文/响应/日志/前端无明文 + 非管理员 403）
- [Phase 26]: 26-03: git 平台 MR/PR 客户端（_get_client / create_mr_for_task / coding.py MR 段）+ 编码容器 dispatch token 注入（coding.py dispatch / coding_session_service 两处）+ diff archive 拉取五处取 token 统一经 aresolve_git_token，per-repo 优先 → host 实例池 fallback；解析器 None 时各调用方保留既有缺凭证报错/降级（行为不回退）；token 仅传 client/进 dispatch payload 不入日志；守护测试覆盖同 host 共享 + per-repo 优先 + 缺凭证报错不回退 + 不泄漏
- [Phase 26]: 26-06(gap): 26-VERIFICATION 发现 26-02/03 之外仍有残留 6 文件 ≥8 处内联 decrypt_value(encrypted_token) 绕过解析器（pr.py PR+cross-ref、coding_graph.py 冲突预检+PR、code_review.py get_merge_request_diff、summary_service.py + chat_tools.py 两处容器 dispatch、views.py TestConnection 既有仓库分支）→ 全部改经 aresolve_git_token；TestConnection 仅『既有仓库 repository_id』分支接解析器、『用户当场输入 token』分支不变；code_review 去无用 select_related('credential')；缺凭证保留各自既有文案（行为不回退）；新建 test_git_credential_gap_wiring.py（dispatch 注入 + 平台 client 两类代表入口，6 测）；grep 确认全 server 除解析器自身已无 resolver-bypassing 取 token
- [Phase 27]: 27-02: get_work_item/get_comments 移除 work_item_type=story 默认改必填(fail-loud TypeError)，WorkItemInfo 新增带默认 feishu_fields(完整元数据)+fields 拍平双写向后兼容；接入 27-01 helper——硬路径 strict_response_json fail-loud、comments/relations 端点 safe_response_json fail-soft 返回[]，relations 标注 origin=feishu_relation_api；全 services.feishu 调用方已显式传 type，零回归
- [Phase 27]: 27-03: near-dup feishu.client 接入 27-01 共享 helper，落 FIX-01/03/04，与 canonical services/feishu.py 同源同断言消除解析漂移；work_item_type 必填 fail-loud、WorkItemInfo 新增带默认 feishu_fields、get_comments safe_response_json fail-soft；本 client 无 relation 端点故不涉 FIX-02；全调用方已显式传 type 零回归
- [Phase 28]: 28-01: 新建 delivery app（注册 INSTALLED_APPS 在 feishu 之后），models 包按实体拆 work_item/sync_state/relation/status_event + curated re-export；id 一律 UUIDField(default=uuid4)；INV-1 由 WorkItem.Meta.unique_together(feishu_project_key, work_item_type, work_item_id) 在 DB 层强制（测试以 pytest.raises(IntegrityError) 守护）；feishu_fields=JSONField(default=list)、field_provenance=JSONField(default=dict)；WorkItemOrigin 含 bitable_import/mr_reverse 枚举占位（真实调用方 Phase 31/32）；本 plan 只建表，落库逻辑归 28-02 service（INV-6）；模型层无 create/save 业务逻辑
- [Phase 29]: 29-01: append-only WorkItemCommentEvent 模型只建表+枚举（CommentEventType 五值/ApprovalSemantic 三值默认 none），模型层无 create/save/就地改写方法——落库归 29-02 CommentEventService 单一入口（守 INV-6）；编辑/删除作为新事件行（CMT-02，模型单测守护两行并存）；edited/deleted 留枚举占位 deferred；复用 status_event append-only 范式 + (work_item, event_time) 索引
- [Phase ?]: 29-02: 评论事件落库唯一收口 append_events（INV-6 精神），去重锚 get_or_create 幂等；ingest 复用 Phase 27 get_comments 降配不回滚
- [Phase ?]: 29-02: 当前评论树为事件流读时投影 project_comment_tree（非事实表），编辑取最新/删除标记/线程层级/排序，绝不改事件行
- [Phase 30]: Document/DocumentVersion 操作态实体落 delivery app，逐字段对齐 DOMAIN §3/§12.5；版本链 supersedes self FK + unique_together(document, version)；本 plan 仅建表无落库逻辑（守 INV-6）
- [Phase 30]: DocumentService.upsert_from_feishu 单一写入入口（INV-6）：(feishu_tenant, external_ref) 去重 + content_hash 不翻版本 + supersedes 链 + facet 记录
- [Phase 30]: feishu_tenant 由 doc URL host 派生；_content_hash 复用 knowledge sha256 但不 import（INV-3）
- [Phase ?]: [Phase 30]: feishu_document normalizer 复用 feishu_work_item.normalize 锚事件 + _extract_doc_token/_fetch_doc_body 取材（不重写）；产出操作态 Document（DocumentService INV-6）+ knowledge document 实体 + work_item→REFERENCES→document 出边；feishu_work_item.py 不动（INV-3）
- [Phase ?]: [Phase 30]: doc token 取自 wi 锚事件 payload 的 prd_url/tech_doc_url（避免重复 get_work_item）；同 docx 二次拉取为 accepted tradeoff；doc 拉取/操作态写入失败降级 warning，缺段不缺实体不抛不回滚
- [Phase ?]: Release natural key 落独立字段 bitable_record_key（条件唯一），便于 31-03 幂等 upsert
- [Phase ?]: 31-02: ReleaseService 消费预组装 bitable_record_key 作自然键唯一来源（不在服务内重拼接，归 31-03 adapter）
- [Phase ?]: 32-03 前端一键摄取面板沿用派发→轮询范式（useMutation + 条件 refetchInterval），守护测试以真实 zh-CN.json 锁关键文案
- [Phase ?]: 33-01: commit 锚定复用 CodeChangeArchive.commit_sha/base_branch（不新增字段/migration）；chunk_content_hash 冻结进 KnowledgeEdge.metadata 供 HDIFF-02 对账
- [Phase 34]: 34-01: 片段→需求反查 service 复用 find_chunk_at + graph_store 逐跳 neighbors(direction in/out) 反向多跳，纯读/默认当前视图(as_of=None 排除失效边)/fail-closed；chunk_id 直接入参经 ChunkRegistry 复判 file_path 排除不绕过边界；REST(IsAuthenticated) + MCP reverse_lookup_requirements 同形结构化 {chunks,related_work_items,related_documents,paths}

### Pending Todos

[From .planning/todos/pending/ — ideas captured during sessions]

None.

### Blockers/Concerns

[Issues that affect future work]

- ✅ ~~v0.2.0 follow-up：实时明文 PAT 通道（contextvar）未接入，RemoteTool 链路休眠~~ —
  已于 2026-06-14 接入（commit 8cb50e928）：带 `friday_pat_` Bearer 的手动触发经请求级
  ContextVar → start_execution → ExecutionContext 瞬态字段下传，AICodingNode 据此注入
  `env_FRIDAY_TASK_USER_TOKEN`。明文绝不落库/进日志（PAT-02 守护测试通过）。
  **剩余**：chat/MCP 编码 dispatch 路径（`coding_session_service`）的 PAT 注入未覆盖；
  真实容器端 RTOOL-02/03/04 运行时仍需带 PAT 的真实 dispatch + 容器 E2E 人工验收（见 Deferred）。

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260610-oug | 修复仓库 URL 提示文案为仅支持 HTTPS，并将所有英文校验/错误提示汉化 | 2026-06-10 | c4c60c4f | [260610-oug-url-https](./quick/260610-oug-url-https/) |
| 260610-shc | OIDC 回调 URL 与登录跳转优先消费「站点 Host」(site_host) 系统设置 | 2026-06-10 | b01dc066 | [260610-shc-site-host-oidc](./quick/260610-shc-site-host-oidc/) |
| 260610-qmv | 修复 compose 部署下任务容器回调失败（发布 runner callback 端口）并抑制 claude CLI 403 遥测噪音 | 2026-06-10 | 68ddaa4c | [260610-qmv-compose-runner-callback-claude-cli-403](./quick/260610-qmv-compose-runner-callback-claude-cli-403/) |
| 260611-0pm | 打磨第 1 批：全仓口径对齐 + 过程痕迹清洗 + 社区脚手架 | 2026-06-11 | 7f0c4381 | [260611-0pm-polish-batch1](./quick/260611-0pm-polish-batch1/) |
| 260611-fky | 打磨仓库列表索引完成界面视觉 | 2026-06-11 | fa5e1b0a | [260611-fky-repository-list-polish](./quick/260611-fky-repository-list-polish/) |
| 260612-crc | 修复 clarification 答复后 resume 后台任务因继承请求 contextvars 崩溃、会话永久卡在等待态 | 2026-06-12 | e6374837 | [20260612-fix-clarification-resume-context](./quick/20260612-fix-clarification-resume-context/) |
| 260611-g31 | 打磨工作流列表与执行监控界面视觉 | 2026-06-11 | 9bc59746 | [260611-g31-workflow-execution-polish](./quick/260611-g31-workflow-execution-polish/) |
| 260611-ghb | 统一工作流卡片高度并收纳节点标签 | 2026-06-11 | c7af69b6 | [260611-ghb-workflow-card-uniform](./quick/260611-ghb-workflow-card-uniform/) |
| 260612-cifix | 修复 CI：smoke 列表移除已删除的 test_tool_bindings.py | 2026-06-12 | ec839757 | — |

## Deferred Items

Items acknowledged and deferred at milestone close. 2026-06-14 复盘清理后分三类：✅ 已解决、
🔒 需外部系统/全新实例（本地无法闭环）、🖐 纯观感人工验收（可后续浏览器抽验）。

### ✅ Resolved 2026-06-14（历史遗留清理）

| Category | Item | Resolution |
|----------|------|------------|
| tech_debt | VALIDATION.md（18-21）nyquist_compliant frontmatter 未翻转 | 回写 true（commit 37a3bd6b2，复核 tests/workflows/ 479 passed） |
| tech_debt | v0.3.0 W1：交付知识 `searchDeliveryKnowledge` 无 UI 消费 | index 占位页改为真实搜索页（5435fef23），浏览器实测搜索/空态正常 |
| tech_debt | v0.3.0 W2：timeline 节点级 provenance 未填充 | 前端渲染 node.provenance + 修后端 code_change 跨版本串味 bug（5435fef23） |
| tech_debt | v0.3.0 W3：graph enrich/related 边类型 | related.py 多跳取真实 edge.relation + 前端 relation 标签（5435fef23） |
| scope_v2 | Phase 21 project_ids/exclude_* 触发负向过滤 | _include/_exclude + Project UUID→feishu_project_key 映射（9ab638f13） |
| scope_v2 | Phase 20 input.*/trigger.* 严格静态校验 + IssuesPanel 点击居中 | graph_validator 严格校验（宽松降级）+ provide/inject fitView 居中（9ab638f13） |
| follow-up | v0.2.0 实时明文 PAT 通道未接入（RemoteTool 休眠） | ContextVar → ExecutionContext 瞬态字段下传，点亮 AICoding RTOOL（8cb50e928） |
| quick_task | 260610-oug-url-https / 260611-ghb-workflow-card-uniform（状态 unknown） | 复核两者均有 SUMMARY.md，确认已完成（标记过时，非遗留） |

### 🔒 需真实外部系统才能闭环（本地无法验证，保持 deferred）

| Item | 需要的环境 |
|------|-----------|
| Phase 14 真实 git platform 超大 diff 截断（TD-14） | 真实 GitLab/GitHub 大 MR |
| Phase 18 真实容器回调续跑 E2E | runner + Docker + 任务容器 + 真实编码 agent |
| Phase 21 真实飞书事件触发 + WS 断线降级观感 | 真实飞书应用 + 事件推送 |
| RTOOL-02/03/04 运行时（带 PAT 注入容器端到端） | 带 PAT 的真实 dispatch + 容器执行（通道已接入，待真实环境验收） |

### 🖐 纯观感人工验收（可后续浏览器抽验；2026-06-14 已部分实测）

| Item | 2026-06-14 状态 |
|------|----------------|
| Phase 17 变量所选即所得 / 端口防护 / 选择器去重（17-HUMAN-UAT 3 pending） | 有 P17 UAT 种子工作流；运行态错误展示由 tests/workflows 覆盖；未逐项点击 |
| Phase 19 画布编辑观感 | ✅ 浏览器实测：节点库 + 画布编辑器正常渲染（全节点类型可见） |
| Phase 20 IssuesPanel 交互 + 模板端到端执行 | ✅ 浏览器实测：编辑器打开 + 保存流程执行正常；校验逻辑由 graph_validator 测试覆盖 |
| Phase 21 suspended 显示 | 有 P21 suspended UAT 种子工作流 + 执行记录；前端 ExecutionStatus 由 vitest 覆盖 |
| Phase 01/02/06–11 人工验收 | 多为首启向导（需 no-superuser 全新实例）/ 身份令牌；本实例已有 superuser，需独立环境复验 |

## Session Continuity

Last session: 2026-06-16T00:00:00.000Z
Stopped at: v0.7.0 roadmap created (Phases 36–42)
Resume file: None
Next: 规划 Phase 36（前置修复 PF-01/02 + 编排引擎骨架 + PlanSession 状态机）

## Operator Next Steps

- Plan the first phase with /gsd-plan-phase 36
