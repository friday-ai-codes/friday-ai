---
phase: 14-triggers
reviewed: 2026-06-11T18:30:00Z
depth: quick
files_reviewed: 12
files_reviewed_list:
  - server/knowledge/diff_archive.py
  - server/knowledge/sources/task_result.py
  - server/knowledge/sources/workflow_plan.py
  - server/knowledge/sources/feishu_work_item.py
  - server/knowledge/models.py
  - server/knowledge/ingestion.py
  - server/knowledge/chunking.py
  - server/services/git_platform/github_client.py
  - server/services/git_platform/gitlab_client.py
  - server/feishu/views.py
  - server/orchestration/coding_graph.py
  - server/workflows/nodes/ai/coding.py
findings:
  critical: 0
  warning: 4
  info: 1
  total: 5
status: fixed
fixed_at: 2026-06-12T02:30:00+08:00
---

# Phase 14: Code Review Report

**Reviewed:** 2026-06-11T18:30:00Z
**Depth:** quick
**Files Reviewed:** 12
**Status:** fixed（WR-01..04 已修复，IN-01 接受为已知权衡）

## Summary

quick 单遍扫描：3 个新建 normalizer + diff 归档核心全文细读，6 个宿主文件只看 `c9633c0d..HEAD` diff，外加反模式 grep（秘钥/eval/调试残留/空 catch——全部干净，coding.py:887 的 TODO 为 diff 范围外既有内容）。

重点契约逐项核对结论：

- **mr_url 权威源三路**（task_result.py:144-166）：workflow 走 `mr_results`→`merge_requests` 回退、legacy 走 `task_result.pr_url`、chat 走 `CodingSession.pr_url`——三路分支与定案一致，`TaskResult.pr_url` 仅 legacy 分支读取。✓
- **时序防线**：coding_graph.py 两处投递均在 `amark_completed` 之后、coding.py 投递在 MR 创建 + `mr_results` 持久化之后，容器回调主路径零投递。✓
- **畸形 diff 降级**（diff_archive.py:192-219）：逐文件独立 PatchSet + "非空 diff 零 hunk" 哨兵 → `parse_failed=True` 不污染整批。✓
- **zlib 往返**（diff_archive.py:236-243）：`compress(level 6)`/`decompress` 对称，`bytes(blob)` 兼容 memoryview。✓
- **MODIFIES_CHUNK 阶梯**：①符号②行号③文件级封顶 20 ④unresolved，按 chunk_id 全局去重；DB 侧 `uniq_kedge_chunk_active` partial unique 封堵 NULL 不相等漏洞。✓
- **接线铁律**：三处接线均 lazy import、只投 ID；`aschedule_ingestion` 调用本身零 try/except（coding.py 的 try/except 包的是 mr_results 持久化，属定案降级路径）。✓
- **凭证**：仅经 `GitCredential`（OneToOne，`aget` 无 MultipleObjectsReturned 风险）+ `decrypt_value`，token 不入日志/归档。✓
- **aware datetime**：task_result/workflow_plan/feishu_work_item 三处均有 naive→aware 防线。✓

发现 4 个 Warning（均为边界/降级路径缺口，非主路径错误）与 1 个 Info。

## Warnings

### WR-01: build_code_change_content 的 head 区段不受 MAX_CONTENT_BYTES 预算约束

**Fixed:** ✅ `b74275c9` — head（含文件清单）纳入总预算，超出按行截断 + `[摘要 truncated]` 标注，最终 content 严格 ≤ MAX_CONTENT_BYTES。
**File:** `server/knowledge/diff_archive.py:262-283`（head 来源 `:629-635`）
**Issue:** 预算只约束 diff 区段（`budget = MAX_CONTENT_BYTES - len(head)`），但 head 本身含 `summary_lines` 文件清单——`DIFF_FETCH_MAX_FILES = 1000` 时文件清单可达上千行（长路径场景轻松数百 KB）。head 超 256KB 时 `budget` 为负、`allowed` 钳到 0，diff 全部截掉，但 head 原样保留，最终 content 仍可远超 `MAX_CONTENT_BYTES`，击穿 "version.content 受控大小" 的锁定语义（embedding 输入超限）。
**Fix:** 对文件清单封顶（如只列前 100 个文件 + `... 其余 N 个文件省略`），或把 head 也纳入预算、超限时先截清单：

```python
_MAX_SUMMARY_FILES = 100
listed = file_diffs[:_MAX_SUMMARY_FILES]
summary_lines = [..., *(f"- {fd.path}（...）" for fd in listed)]
if len(file_diffs) > _MAX_SUMMARY_FILES:
    summary_lines.append(f"-（其余 {len(file_diffs) - _MAX_SUMMARY_FILES} 个文件省略）")
```

### WR-02: CodeChangeArchive.mr_url 为默认 URLField(max_length=200)，超长 URL 在 acreate 抛 DataError 未被捕获

**Fixed:** ✅ `06d4faec` — `mr_url` 改 `max_length=500`（migration 0004），且步⑥同时捕获 `DataError` 走 warning 降级路径。
**File:** `server/knowledge/models.py:382`（写入点 `server/knowledge/diff_archive.py:591-620`）
**Issue:** `mr_url = models.URLField(blank=True, default="")` 默认 `max_length=200`。自托管 GitLab 深层 group 嵌套的 MR URL 可超 200 字符；`acreate` 不走 `full_clean`，Postgres 直接抛 `DataError`（值超列宽），而 `archive_code_change` 步⑥只捕 `IntegrityError`——异常将穿透 normalizer 直达 ingestion worker，违反"任何降级路径返回 None、整批绝不 raise"的锁定契约（T-14 防线）。`branch_name`/`mr_id` 同理但实际来源已有 255/64 上限，风险集中在 mr_url。
**Fix:** 任选其一（推荐前者，需补 migration）：

```python
mr_url = models.URLField(max_length=500, blank=True, default="")
```

或写入前防御性截断 / 在步⑥同时捕获 `django.db.DataError` 走幂等放弃路径。

### WR-03: _extract_doc_token 不剥离 query string / fragment，带参数的文档 URL 必然拉取失败

**Fixed:** ✅ `4123ef75` — 经 `urlparse(value).path` 先剥离 query/fragment 再取末段 path。
**File:** `server/knowledge/sources/feishu_work_item.py:64-75`
**Issue:** `value.rstrip("/").split("/")[-1]` 对 `https://xxx.feishu.cn/docx/doxcnABC?from=tab_search`（从浏览器复制的 URL 普遍带 `?from=` 参数）产出 `doxcnABC?from=tab_search`，doc API 必然 404 → 走 `_fetch_doc_body` 静默降级，快照恒缺 PRD/技术方案正文段且只有 warning 日志可循。既有 `_extract_document_id`（feishu_doc_tools.py:317）同病，但那是交互式工具路径，用户可见报错；本处是无人值守后台快照，失败更隐蔽、影响面更大。
**Fix:**

```python
from urllib.parse import urlparse
if "feishu.cn" in value or "larksuite.com" in value:
    return urlparse(value).path.rstrip("/").split("/")[-1]
```

### WR-04: _handle_workitem_update 缺 work_item_type_key 时默认 "story" 进 natural key，存在实体身份分裂窗口

**Fixed:** ✅ `0dd11a21` — 缺 `work_item_type_key` 时跳过 `aschedule_ingestion` + warning（挂起工作流唤醒路径不受影响），不再用占位类型构造身份 key。
**File:** `server/feishu/views.py:880,894-902`
**Issue:** 三元组 `{project_key}:{work_item_type}:{work_item_id}` 是实体 natural key（同 key 重摄 = 版本翻转）。update 事件 payload 缺 `work_item_type_key` 时回退 `"story"`——若 create 事件携带真实类型（如 `issue`）而 update 事件缺失，同一工作项会以 `...:issue:123` 与 `...:story:123` 两个 source_id 分裂为两个实体，后续快照升级落在错误实体上。`"story"` 默认值是既有 handler 惯例（views.py:636/754/776），但既有用途只是 API 查询参数，本阶段把它升级进了实体身份 key，语义不再等价。飞书不同事件类型 payload 字段不一致属常见形态。
**Fix:** 投递前校验：`work_item_type_key` 缺失时跳过 `aschedule_ingestion` + warning（与 workflow_plan.py T-14-14 "三字段齐备才建锚" 同款防线），不要用占位类型构造身份 key。

## Info

### IN-01: chunking 的 diff 探测对非 code_change 内容存在误判面

**Resolution:** 不修——接受为已知权衡（content 即真理可重派生，仅检索/summary 质量降级）。
**File:** `server/knowledge/chunking.py:37,134-136`
**Issue:** `_DIFF_PROBE_RE`（`^diff --git `，MULTILINE）对全部实体内容生效。work_item 快照（feishu_work_item.py 拼入的 PRD/技术方案 markdown）或 tech_plan 正文里若嵌有 diff 代码块（行首 `diff --git `，技术文档常见），自该行起整段按 `chunk_kind="diff"` 分层切块，丢失标题分段语义。无数据丢失（content 即真理可重派生），仅该实体检索/summary 质量降级。
**Fix:** 可接受的已知权衡；如需收紧，可把 diff-aware 分支限定为 `kind=code_change`（需把 kind 传入纯函数）或要求探测命中行前一行为 `## diff` 标题。

---

_Reviewed: 2026-06-11T18:30:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: quick_
