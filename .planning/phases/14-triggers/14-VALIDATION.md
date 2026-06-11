---
phase: 14
slug: triggers
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-11
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
| TBD（planner 填充） | — | — | KMOD-05 | T-14-V5 | unidiff 文件级解析、zlib 压缩往返、unique 幂等、commit_sha/mr_url/仓库元数据落库 | unit | `uv run pytest tests/knowledge/test_diff_archive.py -x` | ❌ W0 | ⬜ pending |
| TBD | — | — | INGEST-01 | — | plan_generation 成功/审批各投递一次；审批 content 含审批段（防 hash 短路吞掉）；HAS_PLAN exclusive 边 | unit | `uv run pytest tests/knowledge/test_triggers.py -k workflow -x` | ❌ W0 | ⬜ pending |
| TBD | — | — | INGEST-02 | T-14-V4 | 编码完成两路径（chat PR/skip + workflow MR 创建后）各投递；IMPLEMENTED_BY 边；宿主零回归 | unit + regression | `uv run pytest tests/knowledge/test_triggers.py -k coding -x && uv run pytest tests/test_coding_session_graph.py -x` | ❌ W0 | ⬜ pending |
| TBD | — | — | INGEST-04 | T-14-V5 | 飞书三事件投递；快照含 fields/relations/文档正文；文档失败降级 | unit | `uv run pytest tests/knowledge/test_triggers.py -k feishu -x` | ❌ W0 | ⬜ pending |
| TBD | — | — | ENH-01 | — | 符号级→行号级→文件级降级阶梯；封顶常量；chunk 边 3 连发幂等（代码级收口 apply_edge_specs）；反查链路 | unit | `uv run pytest tests/knowledge/test_modifies_chunk.py -x` | ❌ W0 | ⬜ pending |
| TBD | — | — | SC#5 大 diff | T-14-V5 | 10k+ 行夹具：生成文件跳过、chunk 封顶、归档统计正确 | unit | `uv run pytest tests/knowledge/test_diff_archive.py -k large -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**特别测试（防线固化）：**
- 时序防线：diff 归档挂 MR 创建之后（`create_pr_or_skip_node` / `_resume_after_containers`），测试断言回调时刻不归档
- 畸形 diff 防线（V5）：unidiff 解析失败 warning 降级"只归档不解析"，不拖垮摄取
- chunk 边幂等：`uniq_kedge_active` 对 chunk 边不生效（target_entity NULL）——代码级幂等收口 apply_edge_specs + 建议补 partial unique
- 权限维度：CodeChangeArchive 带 repository FK；KnowledgeEntity 写入恒带 project_id/repository_id

---

## Wave 0 Requirements

- [ ] `server/tests/knowledge/test_diff_archive.py` — KMOD-05 + 大 diff 夹具（`build_large_diff` helper）
- [ ] `server/tests/knowledge/test_modifies_chunk.py` — ENH-01 阶梯 + 幂等
- [ ] `tests/knowledge/test_triggers.py` 扩展 — workflow/coding/feishu 三组
- [ ] `tests/knowledge/conftest.py` 扩展 — fake git platform client / fake FeishuClient fixture
- [ ] 依赖：`cd server && uv add "unidiff>=0.7.5,<0.8"`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 真实 git platform 拉 diff（GitHub/GitLab API 截断边界） | KMOD-05 | 平台超大 diff 截断行为 [ASSUMED]，需真实仓库验证 truncated 标记 | dev 环境配置真实仓库凭证，触发一次编码完成回调，检查 CodeChangeArchive 行与 truncated 字段 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
