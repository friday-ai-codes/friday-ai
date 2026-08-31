---
phase: 14-triggers
verified: 2026-06-11T18:40:00Z
status: human_needed
score: 35/35 must-haves verified
overrides_applied: 0
human_verification:

  - test: "真实 git platform 拉 diff 截断边界（GitHub/GitLab API 超大 diff）"
    expected: "dev 环境配置真实仓库凭证，触发一次编码完成回调后，CodeChangeArchive 落库一行且 truncated 字段在平台侧截断/patch 缺失时为 True"
    why_human: "平台超大 diff 截断行为 [ASSUMED]（14-VALIDATION Manual-Only 项），单测仅 mock SDK，需真实仓库验证"
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: human_needed
---

# Phase 14: 全触发点接入与 diff 归档 Verification Report

**Phase Goal:** 六类触发点全部接通，编码产出的全量 diff 归档落库并与既有代码图谱打通，需求→方案→代码全链路在图中闭环
**Verified:** 2026-06-11T18:40:00Z（验证基于已提交 HEAD `7076f801`；工作区未提交改动 chat/task/web 不在本 phase 范围且不影响在案测试）
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths — ROADMAP Success Criteria（合同项）

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| SC1 | `ai_plan_generation` 产出方案时需求与方案实体入图并建 `HAS_PLAN` 边（含审批通过事件） | ✓ VERIFIED | `knowledge/sources/workflow_plan.py`（generate_entity_id + HAS_PLAN exclusive + `## 审批` 段防 hash 短路 L136）；`plan_generation.py:405` / `scheduler.py:1243` 双接线；`test_workflow_*` 10 用例全绿 |
| SC2 | 编码完成回调时 server 侧拉全量 diff 归档落库（unidiff 文件级解析、commit SHA/MR URL/仓库元数据、压缩存储）并摄取 code_change 关联方案/需求 | ✓ VERIFIED | `CodeChangeArchive`（models.py:353，zlib BinaryField + `uniq_codechange_source_commit`）+ migration 0003/0004；`diff_archive.archive_code_change`（675 行，九步编排 + aexists 幂等 + DataError/IntegrityError 降级）；`task_result.py` 双事件 + IMPLEMENTED_BY 挂锚；`test_coding_*` 11 用例全绿 |
| SC3 | 飞书工作项关键事件摄取带事件时间的快照（名称/描述/自定义字段/PRD 与方案文档正文/关联工作项） | ✓ VERIFIED | `knowledge/sources/feishu_work_item.py`（全量快照 + urlparse doc token + aware event_time）；`feishu/views.py` 三 handler 接线（rg 计数==3，webhook 零取材）；`test_feishu_*` 10 用例全绿 |
| SC4 | code_change 经 `MODIFIES_CHUNK` 边（file+symbol+commit_sha 懒解析）关联 ChunkRegistry，可反查"函数被哪些需求改过" | ✓ VERIFIED | EdgeSpec(target_chunk_id+metadata) + `uniq_kedge_chunk_active` partial unique + `graph_store.chunk_in_edges`；对齐阶梯 ①符号②行号③文件级封顶20④unresolved（test_symbol_level/test_file_level_fallback_capped/test_unresolved 全绿）；三跳反查端到端 `test_coding_sc4_reverse_chain_chunk_to_work_item` 通过 |
| SC5 | 万行级大 diff（含生成文件）摄取不拖垮管线：分层切块、生成文件跳过、批量写入经大 diff 夹具验证 | ✓ VERIFIED | `chunk_knowledge_text` diff-aware 分支（文件→hunk→硬切，chunk_kind="diff"）；`is_generated_file` + MAX_* 预算常量表；`test_large_diff_parse_and_generated_skip` / `test_large_diff_content_chunk_capped` 通过 |

### Observable Truths — PLAN must_haves（30 条，按 plan 分组）

| Plan | Truths | Status | Evidence |
|------|--------|--------|----------|
| 14-01（5 条） | 归档表落库往返 / unique 幂等锚 / chunk 边三连发幂等 / DB partial unique / diff-aware 确定性切块 | ✓ 5/5 | models.py 双约束 rg==2（含 0003/0004 migration）；`test_chunk_edge_triple_fire_idempotent`、`test_chunk_edge_partial_unique`、test_chunking 确定性用例全绿；ingestion.py 零 `KnowledgeEdge.objects`（边写收口 graph_store） |
| 14-02（3 条） | 双平台 get_branch_diff / truncated 响亮标记 / 异常不上抛 | ✓ 3/3 | base/gitlab/github 各 rg==1；tests/test_branch_diff.py + test_compare_branches 零回归（全绿在 336 passed 套件内） |
| 14-03（5 条） | unidiff 文件级解析+畸形降级 / 生成文件判定 / 对齐阶梯 resolution 标注 / DiffArchiver 端到端 / 10k+ 大 diff 夹具 | ✓ 5/5 | diff_archive.py 常量表全量（MAX_FILE_LEVEL_EDGES_PER_FILE=20、DIFF_FETCH_MAX_FILES=1000）；`branch_name=""` rg==5（Pitfall 7）；diff_archive 内零 graph_store/add_edge（只产出 EdgeSpec）；env 零读取 |
| 14-04（5 条） | 生成成功投递（失败零投递）/ 审批 source_id 恒生成节点 key / 双事件+HAS_PLAN / 审批段落防短路 / 异常隔离 | ✓ 5/5 | scheduler.py:1246 source_id=`{execution_id}:{generation_node_id}`；`test_workflow_plan_approval_delivers_generation_node_key`、`*_survives_runner_failure` ×2 通过；`from knowledge.ingestion import` 全仓零命中（Pitfall 9） |
| 14-05（5 条） | 三事件各投递一次（零取材）/ 全量快照分段 / 同 key 锚升级 v2 / event_time 恒 aware / 文档降级+异常隔离 | ✓ 5/5 | views.py rg==3；`test_feishu_same_key_reingest_upgrades_anchor_to_v2`、`test_feishu_event_time_always_aware`、`test_feishu_doc_fetch_failure_degrades_*` 通过 |
| 14-06（7 条） | 三锚点投递+回调时刻不归档 / 归档+双事件双边 / payload 权限维度+无 diff 原文 / mr_url 权威源三路 / SC#4 反查三跳 / 归属权威 FK / 异常隔离 | ✓ 7/7 | coding_graph rg==2（amark_completed 后）、coding.py==1（mr_results 先持久化 L643-646 后投递）、callbacks==1（仅 legacy 分支 L522）；task_result.py `last_output` 零命中、`task_result.pr_url` 仅 legacy 分支（L159-161）；`test_coding_callback_main_path_zero_delivery_legacy_delivers`（时序防线）、`test_coding_workflow_persists_mr_results_then_delivers`、`test_coding_sc4_reverse_chain_chunk_to_work_item` 通过 |

**Score:** 35/35 truths verified（5 ROADMAP SC + 30 plan must_haves）

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `server/knowledge/models.py` | CodeChangeArchive + chunk 边 partial unique | ✓ VERIFIED | L353 起；双约束显式命名 rg==3 命中（含 docstring）；WR-02 修复后 mr_url max_length=500 |
| `server/knowledge/migrations/0003_codechangearchive_and_more.py` + `0004_alter_codechangearchive_mr_url.py` | 建表+约束（0004 为 WR-02 修复） | ✓ VERIFIED | `makemigrations --check --dry-run` → "No changes detected" |
| `server/knowledge/ingestion.py` | EdgeSpec(target_chunk_id XOR + metadata) + chunk 幂等分支 | ✓ VERIFIED | L93-94 字段、L325 XOR 校验、零直接 ORM |
| `server/knowledge/graph_store.py` | chunk_in_edges 反查 | ✓ VERIFIED | L126 协议 + L244 实现；`WITH RECURSIVE` 全仓仅此文件（另一命中为审计测试断言本身） |
| `server/knowledge/chunking.py` | diff-aware 分支 | ✓ VERIFIED | `_DIFF_PROBE_RE` L37 + chunk_kind="diff" L162 |
| `server/knowledge/sources/__init__.py` | 三行注册 | ✓ VERIFIED | L24-26 |
| `server/services/git_platform/{base,gitlab_client,github_client}.py` | get_branch_diff 抽象+双实现 | ✓ VERIFIED | 各 rg==1 |
| `server/knowledge/diff_archive.py` | 纯函数+阶梯+DiffArchiver（min 200 行） | ✓ VERIFIED | 675 行，导出 archive_code_change/parse_diff_files/resolve_modified_chunks/build_code_change_content 齐备 |
| `server/knowledge/sources/workflow_plan.py` | 双事件 normalizer | ✓ VERIFIED | exports normalize，注册表可达，测试覆盖 |
| `server/knowledge/sources/feishu_work_item.py` | 全量快照 normalizer | ✓ VERIFIED | exports normalize；WR-03 urlparse 修复在案（L76） |
| `server/knowledge/sources/task_result.py` | DiffArchiver 编排+双事件 normalizer | ✓ VERIFIED | exports normalize；mr_url 三路定案落地 |
| 测试文件（test_diff_archive / test_modifies_chunk / test_branch_diff / test_triggers / conftest） | 全部用例组 | ✓ VERIFIED | 命名前缀约定（test_chunk_/large_/workflow_/feishu_/coding_）落实，`-k` 选中非空 |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| ingestion.py | graph_store.py | apply_edge_specs chunk 分支 add_edge(target_chunk_id, metadata) | ✓ WIRED | L331 |
| plan_generation.py | knowledge/ingestion | lazy import + aschedule_ingestion（成功分支尾部） | ✓ WIRED | L405（rg 计数 2 中 1 为注释） |
| scheduler.py approve_node | knowledge/ingestion | node_approved 后按 node_type 过滤 + 生成节点 key 重定向 | ✓ WIRED | L1243-1249 |
| feishu/views.py ×3 | knowledge/ingestion | 三 handler 尾部只投三元组 ID | ✓ WIRED | rg==3；update handler 缺 type_key 跳过（WR-04） |
| coding_graph.py ×2 | knowledge/ingestion | skip/PR 两分支 amark_completed 之后 | ✓ WIRED | L581 / L629 |
| coding.py | knowledge/ingestion + node_execution.output_data | mr_results 先持久化（asave update_fields）后逐 session 投递 | ✓ WIRED | L643-657 |
| callbacks.py | knowledge/ingestion | 仅旧兼容分支 legacy_coding_completed；_handle_completed 主路径零投递 | ✓ WIRED | L522；时序防线测试钉死 |
| task_result.py | diff_archive.py | archive_code_change 唯一重 IO 调用 | ✓ WIRED | L173 |
| diff_archive.py | git_platform / models / codegraph | get_git_platform_client + CodeChangeArchive.acreate + Symbol(branch_name="") 行重叠 | ✓ WIRED | 九步流 + Pitfall 7 rg==5 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| task_result normalizer → code_change 事件 | content/edge_specs | ArchiveResult ← 平台 diff ← GitCredential→client（真实 ORM acreate + 真实拉取，测试经 fake client 全路径走通） | Yes | ✓ FLOWING |
| feishu_work_item normalizer → 快照事件 | content 各段 | get_work_item/relations/get_document_content 后台真实取材（降级有独立路径） | Yes | ✓ FLOWING |
| chunk_in_edges 反查 | EdgeRecord 列表 | KnowledgeEdge ORM filter(invalid_at__isnull=True) | Yes | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Phase full suite（含宿主回归） | `uv run pytest tests/knowledge/ tests/test_coding_session_graph.py tests/test_coding_session_service.py tests/mcp_tools/ tests/feishu/ tests/test_branch_diff.py tests/test_compare_branches.py tests/test_ai_node_chain.py -q` | **336 passed, 2 skipped**, 0 failed (13.3s) | ✓ PASS |
| 模型/migration 一致 | `uv run python manage.py makemigrations --check --dry-run` | "No changes detected"，退出码 0 | ✓ PASS |
| raw SQL 收口审计 | `rg -l "WITH RECURSIVE" --type py` | 仅 graph_store.py（+审计测试断言文件自身） | ✓ PASS |
| 接线计数审计 | `rg -c aschedule_ingestion` | feishu/views.py==3、coding_graph.py==2、coding.py==1、callbacks.py==1、plan_generation.py==1（调用，另 1 为注释）、scheduler.py==1 | ✓ PASS |
| Pitfall 9 from-import 禁令 | `rg "from knowledge.ingestion import" feishu/ orchestration/ workflows/ subagent/` | 零命中 | ✓ PASS |

### Probe Execution

Step 7c: SKIPPED — 全仓无 `scripts/*/tests/probe-*.sh`，PLAN/SUMMARY 未声明 probe。

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| KMOD-05 | 14-01/02/03/06 | 全量 diff 归档落库（unidiff 文件级、commit SHA/MR URL/仓库元数据、压缩） | ✓ SATISFIED | CodeChangeArchive + archive_code_change 九步流 + mr_url 权威源三路 + 大 diff 夹具测试 |
| INGEST-01 | 14-04 | ai_plan_generation 产出/审批 → HAS_PLAN 入图 | ✓ SATISFIED | workflow_plan normalizer + 双接线 + 审批段落防短路测试 |
| INGEST-02 | 14-02/06 | 编码完成回调 → 归档 + code_change 关联方案/需求 | ✓ SATISFIED | 三锚点接线 + 时序防线（回调主路径零投递）测试 |
| INGEST-04 | 14-05 | 飞书工作项关键事件全量快照（带事件时间） | ✓ SATISFIED | feishu_work_item normalizer + 三 handler 接线 + 锚升级 v2 测试 |
| ENH-01 | 14-01/03/06 | MODIFIES_CHUNK 符号级对齐 + 反查 | ✓ SATISFIED | 对齐阶梯①-④ + chunk 边幂等双防线 + SC#4 三跳反查测试 |

孤儿需求检查：REQUIREMENTS.md 映射至 Phase 14 的恰为以上 5 项，无 ORPHANED。

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | 本 phase 全部修改文件 TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER 零命中 | — | 无 |

注：REVIEW.md WR-01..04 四项 Warning 已逐项确认修复落地（b74275c9 head 预算 / 06d4faec mr_url 500+DataError / 4123ef75 urlparse / 0dd11a21 缺 type_key 跳过），各有回归测试在案；IN-01 为已接受的已知权衡。

### Human Verification Required

#### 1. 真实 git platform 拉 diff 截断边界

**Test:** dev 环境配置真实 GitHub/GitLab 仓库凭证，触发一次编码完成回调（PR 创建或 skip-PR 路径），检查 CodeChangeArchive 行与 truncated 字段。
**Expected:** 归档行落库且字段完整；平台侧超大 diff 截断 / patch 缺失时 truncated=True 响亮标记。
**Why human:** 平台超大 diff 截断行为为 [ASSUMED] 假设（14-VALIDATION Manual-Only 项），单测全部 mock SDK（pytest-socket 禁网），无法自动化验证真实 API 边界。

### Gaps Summary

无 gap。35/35 must-haves 全部经代码 + 测试证据验证；全量套件 336 passed 零失败；migration 干净；全部 rg 收口审计达标；REVIEW 四项修复在案。仅一项 Manual-Only 真实平台边界验证待人工执行。

---

_Verified: 2026-06-11T18:40:00Z_
_Verifier: Claude (gsd-verifier)_
