---
phase: 14
slug: triggers
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-11
updated: 2026-06-12
---

# Phase 14 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >=9.0.2 + pytest-django + pytest-asyncio（`asyncio_mode=auto`）+ pytest-socket |
| **Config file** | `server/pyproject.toml [tool.pytest.ini_options]`（`--disable-socket`） |
| **Quick run command** | `cd server && uv run pytest tests/knowledge/ -x` |
| **Full suite command** | `cd server && uv run pytest tests/knowledge/ tests/test_coding_session_graph.py tests/test_coding_session_service.py tests/mcp_tools/ -x` |
| **Estimated runtime** | quick ~30s / full ~120s |

---

## Sampling Rate

- **After every task commit:** Run `cd server && uv run pytest tests/knowledge/ -x`
- **After every plan wave:** Run full suite command（宿主 coding_graph / mcp_tools 零回归）
- **Before `/gsd-verify-work`:** full suite green + `makemigrations --check --dry-run` 干净 + rg 收口审计
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 14-01-T1 | 14-01 | 1 | KMOD-05 | T-14-01 / T-14-02 | CodeChangeArchive zlib 往返/unique 幂等/repository FK（权限维度）+ chunk 边 partial unique DB 防线随 0003 migration 定型 | unit | `uv run pytest tests/knowledge/test_diff_archive.py -x` | ✅ 14-01-T1 创建 | ⬜ pending |
| 14-01-T2 | 14-01 | 1 | ENH-01 | T-14-02 | EdgeSpec chunk 扩展 XOR 校验；chunk 边 3 连发幂等（apply_edge_specs 收口）；chunk_in_edges 反查收口 | unit | `uv run pytest tests/knowledge/test_modifies_chunk.py -x` | ✅ 14-01-T2 创建 | ⬜ pending |
| 14-01-T3 | 14-01 | 1 | KMOD-05 | T-14-03 | diff content 文件→hunk→硬切确定性切块、chunk_kind="diff"、可从 content 重派生（Pitfall 8） | unit | `uv run pytest tests/knowledge/test_chunking.py -x` | ✅ 既有扩展 | ⬜ pending |
| 14-02-T1 | 14-02 | 1 | KMOD-05 / INGEST-02 | T-14-05 / T-14-06 | GitLab get_branch_diff：截断响亮 truncated、SDK 异常不上抛、token 不入日志 | unit | `uv run pytest tests/test_branch_diff.py -x` | ✅ 14-02-T1 创建 | ⬜ pending |
| 14-02-T2 | 14-02 | 1 | KMOD-05 / INGEST-02 | T-14-06 / T-14-07 | GitHub get_branch_diff：patch 缺失降级 truncated、凭证零 env 读取 | unit | `uv run pytest tests/test_branch_diff.py -x` | ✅ 14-02-T1 已建 | ⬜ pending |
| 14-03-T1 | 14-03 | 2 | KMOD-05 + SC#5 大 diff | T-14-08 / T-14-09 | unidiff 文件级解析、畸形 diff 降级"只归档不解析"、生成文件判定、10k+ 行夹具（生成文件跳过/content 预算截断/统计正确） | unit | `uv run pytest tests/knowledge/test_diff_archive.py -k large -x`（同文件全量另跑 `-x`） | ✅ 14-01-T1 已建 | ⬜ pending |
| 14-03-T2 | 14-03 | 2 | ENH-01 | T-14-02 | 符号级→行号级→文件级降级阶梯；封顶 20；unresolved 记录；branch_name="" 锚 base；反查链路（chunk→code_change） | unit | `uv run pytest tests/knowledge/test_modifies_chunk.py -x` | ✅ 14-01-T2 已建 | ⬜ pending |
| 14-03-T3 | 14-03 | 2 | KMOD-05 | T-14-10 / T-14-12 | DiffArchiver 端到端：放大参数（Pitfall 2）、aexists 幂等短路、缺凭证降级、commit_sha/mr_url/仓库元数据落库、token 零泄漏 | unit | `uv run pytest tests/knowledge/test_diff_archive.py -x` | ✅ 14-01-T1 已建 | ⬜ pending |
| 14-04-T1 | 14-04 | 2 | INGEST-01 | T-14-13 / T-14-14 | workflow_plan 双事件 + HAS_PLAN exclusive；审批 content 含审批段（防 hash 短路）；trigger_data 判空降级；project_id 恒填 | unit | `uv run pytest tests/knowledge/test_triggers.py -k workflow -x` | ✅ 既有扩展 | ⬜ pending |
| 14-04-T2 | 14-04 | 2 | INGEST-01 | T-14-15 / T-14-16 | 生成/审批各投递一次；审批 source_id 恒生成节点 key（OQ-2）；非审批节点零投递；异常隔离 | unit + regression | `uv run pytest tests/knowledge/test_triggers.py -k workflow -x && uv run pytest tests/test_ai_node_chain.py -x` | ✅ 既有扩展 | ⬜ pending |
| 14-05-T1 | 14-05 | 3 | INGEST-04 | T-14-18 / T-14-20 / T-14-21 | 快照含 fields/relations/文档正文；文档失败降级；event_time 恒 aware（毫秒/兜底双场景）；13-03 锚同 key 升级 | unit | `uv run pytest tests/knowledge/test_triggers.py -k feishu -x` | ✅ 既有扩展 | ⬜ pending |
| 14-05-T2 | 14-05 | 3 | INGEST-04 | T-14-17 / T-14-19 | 飞书三事件各投递一次（三元组正确）；webhook 路径零取材；缺 ID 早退零投递；异常隔离 | unit + regression | `uv run pytest tests/knowledge/test_triggers.py -k feishu -x && uv run pytest tests/feishu/ -x` | ✅ 既有扩展 | ⬜ pending |
| 14-06-T1 | 14-06 | 4 | INGEST-02 / KMOD-05 / ENH-01 | T-14-22 / T-14-24 | task_result 双事件：IMPLEMENTED_BY 挂锚、MODIFIES_CHUNK 挂 code_change；**mr_url 权威源（chat=CodingSession.pr_url / workflow=output_data.mr_results，TaskResult.pr_url 仅 legacy；测试以 TaskResult.pr_url 为空 + 权威源有值的真实形态钉死）**；SC#4 反查全链路三跳（chunk_in_edges→code_change→tech_plan→work_item）端到端断言；归属权威 FK（last_output 零接触）；payload 权限维度恒带、diff 原文不进 payload | unit | `uv run pytest tests/knowledge/test_triggers.py -k coding -x` | ✅ 既有扩展 | ⬜ pending |
| 14-06-T2 | 14-06 | 4 | INGEST-02 | T-14-23 / T-14-25 | chat PR/skip + workflow MR 创建后各投递；**workflow 路径投递前 mr_results 持久化进 node_execution.output_data（重读 DB 断言）**；容器回调主路径零投递（时序防线）；旧兼容分支投递；宿主零回归 + full suite 收口 | unit + regression | `uv run pytest tests/knowledge/test_triggers.py -k coding -x && uv run pytest tests/test_coding_session_graph.py tests/test_coding_session_service.py -x` | ✅ 既有扩展 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**特别测试（防线固化）：**
- 时序防线：diff 归档挂 MR 创建之后（`create_pr_or_skip_node` / `_resume_after_containers`），测试断言回调时刻不归档（14-06-T2 Test 3）
- 畸形 diff 防线（V5）：unidiff 解析失败 warning 降级"只归档不解析"，不拖垮摄取（14-03-T1 Test 2）
- chunk 边幂等：`uniq_kedge_active` 对 chunk 边不生效（target_entity NULL）——代码级幂等收口 apply_edge_specs + partial unique `uniq_kedge_chunk_active` DB 防线（14-01-T1/T2）
- 权限维度：CodeChangeArchive 带 repository FK（14-01-T1）；KnowledgeEntity 写入恒带 project_id/repository_id（14-04-T1 / 14-05-T1 / 14-06-T1）
- mr_url 权威源（checker blocker 修复）：TaskResult.pr_url 两条主路径恒空——chat 取 CodingSession.pr_url、workflow 取投递前持久化的 node_execution.output_data["mr_results"]；测试以"TaskResult.pr_url 为空 + 权威源有值"的真实形态构造，禁止 TaskResult(pr_url=...) 掩蔽（14-06-T1 Test 1/2、14-06-T2 Test 2）
- SC#4 反查全链路：chunk_in_edges → code_change → IMPLEMENTED_BY → tech_plan → HAS_PLAN → work_item 三跳端到端断言（14-06-T1 Test 6）
- 测试命名约定：各组方法名统一 test_workflow_* / test_feishu_* / test_coding_* / test_chunk_* / test_large_* 前缀，保证 `-k` 选中非空且精确（pytest -k 大小写敏感，不依赖 PascalCase 类名）

---

## Wave 0 Requirements

> 规划定案：不设独立 Wave 0 计划——测试文件所有权 = 首个消费它的任务创建（与 PLAN 内 `<files>` 一一对应），下列映射即归属。

- [ ] `server/tests/knowledge/test_diff_archive.py` — 14-01-T1 创建（模型/约束用例），14-03-T1 扩展（纯函数 + `build_large_diff` 大 diff 夹具），14-03-T3 扩展（DiffArchiver service 用例）
- [ ] `server/tests/knowledge/test_modifies_chunk.py` — 14-01-T2 创建（chunk 边幂等 + 反查），14-03-T2 扩展（ENH-01 对齐阶梯）
- [ ] `server/tests/test_branch_diff.py` — 14-02-T1 创建（GitLab），14-02-T2 扩展（GitHub）
- [ ] `tests/knowledge/test_triggers.py` 扩展 — 14-04-T1/T2（workflow 组）、14-05-T1/T2（feishu 组，fake FeishuClient fixture 置于本文件内）、14-06-T1/T2（coding 组）
- [ ] `tests/knowledge/conftest.py` 扩展 — fake git platform client fixture（14-03-T3）
- [ ] 依赖：`cd server && uv add "unidiff>=0.7.5,<0.8"`（14-01-T1）

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 真实 git platform 拉 diff（GitHub/GitLab API 截断边界） | KMOD-05 | 平台超大 diff 截断行为 [ASSUMED]，需真实仓库验证 truncated 标记 | dev 环境配置真实仓库凭证，触发一次编码完成回调，检查 CodeChangeArchive 行与 truncated 字段 |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies（6 plans / 14 任务全部带 `<automated>`，命令在各自任务时点可跑且非空选中）
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references（测试文件归属映射见上节，首消费任务创建）
- [x] No watch-mode flags
- [x] Feedback latency < 120s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** planner 已填实（2026-06-12，随 14-0N-PLAN.md 一并提交）
