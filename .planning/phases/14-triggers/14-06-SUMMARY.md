---
phase: 14-triggers
plan: 06
subsystem: knowledge
tags: [ingest-02, kmod-05, enh-01, task-result, diff-archive, implemented-by, modifies-chunk]
requires:
  - 14-01 EdgeSpec chunk 扩展 / chunk_in_edges / apply_edge_specs chunk 边幂等
  - 14-03 archive_code_change / ArchiveResult（DiffArchiver 全部重 IO）
  - 14-04 workflow_plan 锚 key（{execution_id}:{node_id}）与生成节点回查写法
  - 13-02/13-03 统一摄取管线 + aschedule_ingestion 接线范式
provides:
  - knowledge/sources/task_result.py（TaskResult → DiffArchiver 编排 + [tech_plan 锚, code_change] 双事件，chat/workflow 双路径方案回溯）
  - 编码完成三锚点接线：create_pr_or_skip_node ×2 / _resume_after_containers / callbacks 旧兼容分支
  - _resume_after_containers mr_results 投递前持久化进 node_execution.output_data（workflow 路径 mr_url 权威源）
  - SC#4 反查链路端到端测试（chunk_in_edges → code_change → IMPLEMENTED_BY → tech_plan → HAS_PLAN → work_item）
affects:
  - Phase 15 检索（code_change payload 恒带 project_id/repository_id 权限维度）
tech-stack:
  added: []
  patterns:
    - mr_url 权威源三路：chat=CodingSession.pr_url / workflow=output_data["mr_results"]（回退 merge_requests）/ legacy=task_result.pr_url
    - 时序防线：diff 归档挂 MR/PR 创建之后，容器回调主路径零投递
    - 先持久化后投递：normalizer 重读的数据在投递前已落库
key-files:
  created:
    - server/knowledge/sources/task_result.py
  modified:
    - server/orchestration/coding_graph.py
    - server/workflows/nodes/ai/coding.py
    - server/subagent/api/callbacks.py
    - server/tests/knowledge/test_triggers.py
decisions:
  - workflow 路径 mr_results 缺失时回退读 output_data["merge_requests"]（_build_output 落点，每项同样有 repository_id/mr_url/mr_id）——checker 附加建议按引擎实际持久化键名落地（其命名 succeeded_repos 在 _build_output 中是计数 int，非列表）
  - workflow 路径仓库归属经 output_data["pending_sessions"] 按 session_id 匹配（dispatch 时服务端写入），兜底 session.repo_url 匹配 Repository.git_url（同为服务端写入，防引擎覆盖 output_data）
  - callbacks 旧兼容分支无条件投递（pr_url 空串时归档走 branch diff 仍有价值）；graph 主路径零改动
metrics:
  duration: ~14min
  tasks: 2
  files: 5
completed: 2026-06-12
---

# Phase 14 Plan 06: 编码完成三锚点接入与 task_result normalizer Summary

INGEST-02 端到端落地：编码完成（chat PR/skip、workflow MR 创建后、旧兼容回调）三类锚点投递统一摄取，task_result normalizer 在后台经 DiffArchiver 归档全量 diff 并产出 [tech_plan 锚(IMPLEMENTED_BY), code_change(MODIFIES_CHUNK)] 双事件——需求→方案→代码变更→代码块全链路在图中闭环（SC#4 三跳反查 Test 6 端到端钉死），KMOD-05/ENH-01 同步闭环。

## Tasks Completed

| Task | Name | Commits | Key Files |
|------|------|---------|-----------|
| 1 | sources/task_result.py normalizer（DiffArchiver 编排 + 双事件双路径）（TDD） | 8178b0ab (RED) / d3d053db (GREEN) | task_result.py, test_triggers.py |
| 2 | 编码完成三锚点接线（coding_graph ×2 / coding.py / callbacks 旧兼容）（TDD） | 82b3d5ec (RED) / 6d218c7b (GREEN) | coding_graph.py, coding.py, callbacks.py, test_triggers.py |

## 交付物对照（must_haves）

- ✅ chat（PR 创建成功 / skip-PR）与 workflow（MR 创建后）各投递一次；容器回调主路径零投递（Test 3 时序防线，graph 管理 session 完成回调 captured == []）
- ✅ normalizer 经 `diff_archive.archive_code_change`（唯一重 IO 调用）归档全量 diff，产出 tech_plan 锚（IMPLEMENTED_BY EdgeSpec 挂锚事件，target 经 `generate_entity_id("code_change","task_result",session_id)` 唯一入口）+ code_change 事件（content=ArchiveResult.content，MODIFIES_CHUNK chunk EdgeSpec 原样转挂）
- ✅ code_change payload 恒带 project_id/repository_id 与 archive_id/commit_sha/mr_url/统计摘要；diff 原文特征串零进 payload（Test 1 断言）
- ✅ mr_url 权威源三路（blocker 修复锚）：Test 1/2 均以「TaskResult.pr_url 为空 + 权威源有值」真实形态钉死——chat 取 CodingSession.pr_url、workflow 取 node_execution.output_data["mr_results"]（Task 2 投递前持久化，Test 2 重读 DB 断言）、`task_result.pr_url` 仅出现在 legacy 分支（grep 钉死）
- ✅ SC#4 反查全链路（Test 6）：ingest_events 真实入图后 chunk_in_edges(chunk_id) → code_change 实体 → traverse(direction="in") 沿 IMPLEMENTED_BY 达 tech_plan（depth 1）、沿 HAS_PLAN 达 work_item（depth 2）
- ✅ 归属从服务端权威 FK 取：last_output 注入伪仓库特征串零泄漏（Test 5，T-14-22；`rg "last_output" task_result.py` 零命中）
- ✅ 异常隔离：run_in_background 抛 RuntimeError 时 create_pr_or_skip_node 与 _resume_after_containers 仍正常完成（Test 异常隔离）

## Deviations from Plan

### 设计微调（语义不变 / checker 建议按实际落地）

**1. workflow mr_results 回退键名：`merge_requests` 而非 `succeeded_repos`**
- checker 附加建议写"回退读 output_data['succeeded_repos']"；实读 `_build_output` 发现 `succeeded_repos` 是 changes_summary 里的计数 int，引擎覆盖 output_data 后真正"每项含 repository_id/mr_url/mr_id"的列表键是顶层 `merge_requests`。按语义意图（封引擎覆盖竞态窗口）落在 `merge_requests`。

**2. workflow 路径仓库归属补充 pending_sessions / repo_url 双源**
- plan 步 2 未指明 workflow 路径 repository 的具体取数路径；实现经 `node_execution.output_data["pending_sessions"]` 按 session_id 匹配（dispatch 时服务端写入），兜底 `session.repo_url`（同为 dispatch 时服务端写入）匹配 Repository.git_url——两源均为服务端权威数据，符合 T-14-22 纪律。

**3. `_get_coding_session` select_related 增加 `subagent_session`**
- 接线处取 `coding_session.subagent_session.session_id` 需 async 安全；在既有查询上追加 select_related（Rule 3：避免 SynchronousOnlyOperation 阻塞接线）。

**4. docstring 措辞避开 `last_output` 字面量**
- 验收锚点 `rg "last_output"` 零命中含注释/docstring；T-14-22 纪律说明改写为"容器回写输出零接触"。

其余按计划逐字执行。

## Known Stubs

无。

## Threat Flags

无新增面：本 plan 接线只投 ID（无新网络端点/auth 路径/schema 变更）；T-14-22/23/24/25 缓解全部按 plan threat_model 落地（Test 5 / 既有三层幂等 / payload 断言 / 异常隔离用例）。

## Verification

- `uv run pytest tests/knowledge/ tests/test_coding_session_graph.py tests/test_coding_session_service.py tests/mcp_tools/` → 267 passed（phase full suite，零回归）
- `uv run pytest tests/knowledge/test_triggers.py -k coding` → 13 passed（新增方法名全 `test_coding_*` 前缀，--collect-only 非空选中）
- `uv run python manage.py makemigrations --check --dry-run` → 退出码 0（No changes detected）
- 验收锚点：`rg -c "aschedule_ingestion"` coding_graph.py==2 / coding.py==1 / callbacks.py==1；`rg "from knowledge.ingestion import" orchestration/ workflows/ subagent/` 零命中（Pitfall 9）；`rg "mr_results" coding.py` 含 output_data 持久化命中；`rg "last_output" task_result.py` 零命中；`rg "generate_entity_id" task_result.py` 命中
- `rg "WITH RECURSIVE" server/ --type py -l` → 非测试代码仅 graph_store.py（test_graph_store.py 为既有测试断言文案）
- `ruff check` + `ruff format --check`：本 plan 触碰/新建文件全部通过；workflows/ 既有 13 个 lint 错误与三个宿主文件整文件 format 漂移为范围外既有问题（登记 deferred-items.md，14-04 同款处置）

## Self-Check: PASSED

- FOUND: server/knowledge/sources/task_result.py
- FOUND: server/tests/knowledge/test_triggers.py（TestCodingTaskResultNormalizer ×6 + TestCodingTriggers ×5）
- FOUND: 接线命中 orchestration/coding_graph.py（×2）/ workflows/nodes/ai/coding.py / subagent/api/callbacks.py
- FOUND: commit 8178b0ab / d3d053db / 82b3d5ec / 6d218c7b
- tests green（phase full suite 267 passed）/ makemigrations --check 干净
