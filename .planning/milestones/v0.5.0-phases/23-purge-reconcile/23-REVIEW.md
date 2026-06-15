---
phase: 23-purge-reconcile
reviewed: 2026-06-14T15:59:35Z
depth: deep
files_reviewed: 11
files_reviewed_list:
  - server/services/purge.py
  - server/services/purge_reconcile.py
  - server/services/sensitive_purge.py
  - server/services/indexer.py
  - server/repositories/models.py
  - server/repositories/migrations/0033_cleanup_run.py
  - server/repositories/serializers.py
  - server/repositories/urls.py
  - server/repositories/views.py
  - web/src/api/reconcile.ts
  - web/src/components/repository/ReconcilePanel.vue
findings:
  blocker: 1
  high: 3
  medium: 4
  low: 1
  total: 9
status: partially_resolved
resolution:
  resolved_at: 2026-06-15
  fixed: [BL-01, HI-01, HI-02, HI-03, ME-01, ME-04]
  remaining: [ME-02, ME-03, LOW-01]
  note: >-
    数据安全相关项（BLOCKER + 3 HIGH + 安全相关 MEDIUM ME-04/ME-01）已修复并补守护测试，
    见 fix(23-review) 系列提交。余下 ME-02（并发护栏）/ ME-03（子串匹配假阳性）/
    LOW-01（孤儿 overlay collection）非本轮安全范围，留待后续处理。
---

> **修复状态（2026-06-15）**：BL-01 / HI-01 / HI-02 / HI-03 / ME-01 / ME-04 已修复，
> 均补了守护测试（`tests/services/test_purge_reconcile.py`、`test_sensitive_purge.py`、
> `test_purge_file.py`，全绿）。
> - **BL-01**：`run_cleanup` 在对账 `degraded` 时 fail-closed（`CleanupRun=failed` +
>   `failures=[reconcile_degraded]` + error，绝不 `completed`）；POST 视图 degraded 返回
>   409 拒绝派发，不再依赖前端 TOCTOU 禁用。
> - **HI-01**：新增 `code_change_knowledge` 面，剔除 `KnowledgeEntityVersion.content` 的被
>   排除文件 diff 段并删除其向量；caveat 如实纳入知识检索面。
> - **HI-02**：chat `Message` 清理收敛到本仓会话（`CodingSession.repository`），他仓/无关联
>   消息不动，并以 `chat_messages_unscoped` 如实计入 `unscrubbed`。
> - **HI-03**：归档 diff 段剔除增加后置不变量校验（被剔除段数 == 命中 files 项数），不一致
>   则保守保留原归档并记 `errors`，绝不在未确认正文剔除时回写"已 scrub"。
> - **ME-01**：Qdrant collection 不存在视为幂等 no-op，不再误报删除失败。
> - **ME-04**：`TaskResult`/`ActionLog` 关联收敛到 `Repository` 稳定 FK；仅 `repo_url` 可用
>   且多仓共享同一 remote 时保守跳过并如实披露。
>
> **未处理（非本轮安全范围）**：ME-02（清理无并发护栏）、ME-03（`_redact_value` 裸子串假
> 阳性）、LOW-01（孤儿 overlay collection 残留）。

# Phase 23: Code Review Report — 清理对账 / 两模式清理

**Reviewed:** 2026-06-14T15:59:35Z
**Depth:** deep
**Files Reviewed:** 11
**Status:** issues_found

## Summary

Phase 23 引入了统一删除入口 `purge_file`（五个派生面：Qdrant 主 + overlay / FileIndex /
ChunkRegistry+ChunkEdge / codegraph）、规则驱动的对账清理（`compute_reconciliation` /
`run_cleanup` + `CleanupRun` 持久化）、敏感清理（`CodeChangeArchive` / `TaskResult` /
`ActionLog` / chat `Message` scrub），以及前端 `ReconcilePanel`。整体的「best-effort 逐面
隔离 + 失败如实落 `failures`」纪律和 `degraded` 贯通 serializer→client 的设计是健康的，索引
删除路径也确实收敛到了 `purge_file`（PF-03/PF-05），没有发现绕过信号的孤儿写法。

但本次评审从**数据安全**视角发现若干必须修复的问题，集中在三类：

- **「completed」掩盖失败诊断**：`run_cleanup` 读取了 `compute_reconciliation` 的
  `excluded_paths`，却**完全忽略 `degraded` 标记**——匹配器构造失败时静默以
  `status=completed / match_count=0` 收尾，把"对账不可信"伪装成"已干净/清理完成"
  （BL-01）。这违反项目 fail-closed 约束，敏感模式下等于"声称已清，实则未清"的安全泄漏。
- **残留 + 不诚实披露**：敏感清理声称清理"归档 diff"，但只 scrub 了
  `CodeChangeArchive.diff_compressed`；同一份被排除文件 diff 早已被复制进
  `KnowledgeEntityVersion.content`（embedding 输入）及其向量，**未清、且未计入
  `unscrubbed`/`caveat`**（HI-01）。CodeChangeArchive 段切割对精确格式的强依赖也可能
  在 metadata 声称剔除的同时把正文留在 diff 体内（HI-03）。
- **过度清理**：松散文本面对 chat `Message` **全表无仓库作用域**扫描 + 命中即整段叶子
  替换，可不可逆地销毁其他仓库/空间的对话记录（HI-02）。

下面按严重度列出。

## Blocker

### BL-01: `run_cleanup` 忽略 `degraded`，把"对账不可信"伪装成"清理完成"

**File:** `server/services/purge_reconcile.py:215-218, 264-272`；`server/repositories/views.py:1142-1177`
**Issue:**
`run_cleanup` 在 `paths is None` 时调用 `compute_reconciliation` 并只取 `excluded_paths`：

```python
if paths is None:
    recon = await compute_reconciliation(repo_id)
    paths = recon.excluded_paths      # degraded 时恒为 []
target_paths = list(paths)
...
final_status = "completed" if not report.failures else "failed"
```

`compute_reconciliation` 在匹配器**构造失败**时返回 `degraded=True / excluded_paths=[] /
match_count=0`（这是 W3 刻意保留的"对账不可信"信号）。但 `run_cleanup` 既不读取
`recon.degraded` 也不读取 `recon.error`：degraded → `target_paths=[]` → 循环空跑 →
`report.failures` 为空 → **`status=completed`、`match_count=0`、`error=""`**。
`CleanupRun` 因此持久化为一条"成功、无命中、无失败"的记录，状态端点与前端
（`ReconcilePanel.vue:199, 207` 渲染绿色 ✓ "已完成"）都会显示清理成功。

后端 POST 视图（`views.py:1153`）虽然自己也算了一次 `compute_reconciliation`，但同样
**没有在 degraded 时拒绝派发**——它把 `degraded` 丢弃（响应体只回 `match_count`），照常
建 `CleanupRun(running)` 并派发后台 `run_cleanup`。前端按钮禁用（`cleanupDisabled =
degraded`）只是基于**另一次** GET 请求的结果，存在 TOCTOU：GET 时匹配器构造正常、后台
`run_cleanup` 重算时构造失败（瞬时 DB/规则异常），即可触发本路径。

数据安全后果：在 `mode="sensitive"` 下，用户被告知"敏感清理已完成"，而实际上因为对账
诊断失败一个文件都没清——这是把安全泄漏伪装成成功，且违反 CLAUDE.md / AGENTS.md 的
fail-closed 约束（诊断不可信时绝不能渲染"已一致/已完成"）。

**Fix:** 在 `run_cleanup` 内对 degraded 走 fail-closed 收尾，并在 POST 视图层拒绝派发：

```python
# run_cleanup: paths is None 分支
if paths is None:
    recon = await compute_reconciliation(repo_id)
    if recon.degraded:
        await _finalize_run(
            run, status="failed", match_count=0,
            failures=["reconcile_degraded"], sensitive=None,
            error=recon.error or "对账匹配器构造失败，诊断不可信，已中止清理",
        )
        log_purge_event("purge.completed", mode=mode, repository_id=repo_id,
                        match_count=0, failures=["reconcile_degraded"])
        return CleanupReport(mode=mode, failures=["reconcile_degraded"])
    paths = recon.excluded_paths
```

并在 `RepositoryReconcileView.post` 中：`if report.degraded: return 409/422`（degraded 时
不建 running 行、不派发）。前端在 `status=failed + error` 下已能显式展示，但后端必须是
权威 fail-closed 点，不能依赖前端 TOCTOU 禁用。

## High

### HI-01: 敏感清理未触及 `KnowledgeEntityVersion.content` 与其向量——被排除文件 diff 残留且未披露

**File:** `server/services/sensitive_purge.py:122-209, 47-55`（对照 `server/knowledge/diff_archive.py:290-301, 625-658`）
**Issue:**
`_scrub_code_change_archives` 只更新 `CodeChangeArchive.diff_compressed` + `files` 元数据。
但归档时 `build_code_change_content`（`diff_archive.py:290-295`）把**逐文件 raw diff**
（`raw_by_path[fd.path]`，含被排除文件正文）写进了 `## diff` 段，落入
`KnowledgeEntityVersion.content`（Phase 13 embedding 输入，`knowledge/models.py:206`），并
被向量化进知识检索面。敏感清理：

- **不 scrub** 这份 `KnowledgeEntityVersion.content`（DB 明文，可被知识检索读出）；
- **不删** 其对应向量；
- 普通 `purge_file` 也兜不住——它按 `file_path` payload 删 Qdrant，而 code_change 知识
  实体/向量并非以**源文件路径**为 payload 键（它是 archive 实体维度）。

结果：被排除文件的代码 diff 在敏感清理后仍以明文 + 向量形式留在知识面，而
`SENSITIVE_PLANES_CAVEAT` 明确宣称"已尽力清理 Friday 操作记录中的该文件正文（**归档 diff** /
任务结果 / 执行轨迹 / 消息正文段）"，`UNSCRUBBED_PLANES = ["prompt_snapshot", "backups",
"git_objects"]` 也未列入此面。这是**残留泄漏 + 不诚实披露**双重问题，正是本阶段
（§9.1 诚实边界）要避免的。

**Fix:**
- 在 `_scrub_code_change_archives` 命中归档时，定位其派生 `KnowledgeEntityVersion`（同
  source_kind/source_id/archive 维度）的 `content`，剔除/脱敏被排除文件的 `## diff` 段并
  重新 embedding 或删除该版本向量；或
- 若短期内无法清知识面，**至少**把 `code_change_knowledge` 加入 `UNSCRUBBED_PLANES` 并在
  `caveat` 中如实声明该 diff 文本可能残留于知识检索面（保住诚实披露底线）。

### HI-02: 松散文本面（chat `Message`）全表无仓库作用域扫描 + 整段叶子替换，过度销毁他仓记录

**File:** `server/services/sensitive_purge.py:331-384, 267-292`
**Issue:**
`_scrub_loose_text_planes` 对 `Message` 的查询**没有任何 repository / project 作用域**：

```python
content_q = reduce(or_, (Q(content__contains=t) for t in targets))
for msg in Message.objects.filter(content_q):       # 全库所有 Message
    new_content, changed = _redact_value(msg.content, targets)
    ...
for msg in Message.objects.exclude(parts=[]):        # 全库所有非空 parts
    ...
```

注释承认"无稳定 repo↔message 关联键（Conversation 绑 Project 而非 Repository）"，但其应对
是**对全系统所有消息**做子串脱敏。叠加 `_redact_value` 对 `str` 叶子的语义——**只要
包含**被排除路径子串，就把**整个叶子**替换为占位符（`content` 即整条消息正文被抹掉）——
后果是：

- **跨仓/跨空间销毁**：仓库 A 排除 `config/secret.py`，会把仓库 B / 完全无关空间里任何
  提到该路径子串的对话整条正文清空。
- **整条销毁**：哪怕消息里只是顺带提了一句文件名，整段 `content` 被替换，丢失其余正常内容。
- **不可逆**：`msg.save(update_fields=["content"/"parts"])` 直接覆写，无备份。

这正是"过度清理销毁需要的记录"（T-23-13 要避免的）反向破坏，且与 `TaskResult` /
`ActionLog` 面**已正确按 `session.repo_url` 作用域**的做法不一致——`Message` 面是唯一缺
作用域的离群面。

**Fix:**
- 优先：只 scrub 与本仓相关的会话消息（经 `Conversation→Project→Repository` 或既有
  `session`/`repo` 关联键过滤），无法关联的消息**不动**（保守不删，与 §9.3 矩阵对齐）。
- 退一步：不要整段替换 `content` 叶子，改为只替换**命中子串**本身（`str.replace`），保留
  其余正文；并把"无关联消息面"如实计入 `unscrubbed`，而非全库激进抹除。

### HI-03: `CodeChangeArchive` diff 段切割无后置校验，路径解析偏差导致"元数据已剔除但正文残留"

**File:** `server/services/sensitive_purge.py:85-119, 159-199`
**Issue:**
`_split_diff_segments` 依据 `_assemble_raw_diff` 的**精确字面格式**（`diff --git a/{old}
b/{new}`，未做 git 风格引号/转义）切段，`_parse_paths` 用 `body.find(" b/")` 取新路径。
scrub 时按 `new_p not in targets and old_p not in targets` 保留段，并**无条件**把归档
metadata 改成 `files=remaining` / 重算计数 / `scrubbed += 1`。问题：

- 路径含空格或特殊字符（git 通常加引号 `"a/…"`，而此处汇编是裸 f-string），或路径恰含
  `" b/"` 子串时，`_parse_paths` 可能解析出与 `targets` 不匹配的路径 → 该段被**保留** →
  `diff_compressed` 仍含被排除文件正文；
- 若归档 `diff_compressed` 来自非该汇编格式（格式漂移/历史数据），整段解析成单个
  `new_path=""` 段，永不匹配 → 全量保留；
- 两种情况下 `files`/`file_count` 已被改为剔除后的值、`diff_sha256` 按"新"正文重算、
  `scrubbed` 计数 +1 → **对外报告成功**，实际正文残留（静默 under-scrub，等于在敏感清理
  内部"completed 掩盖残留"）。

**Fix:** 增加后置不变量校验：被剔除的目标段数应与 `hit`（命中的 `files` 项）数量一致；
不一致则**不写库**、记 `errors`、保守保留原行或整删，绝不在未确认正文剔除的情况下回写
"已 scrub"的 metadata。同时对引号/含空格路径补健壮解析（或在汇编侧统一加引号并对称解析）。

## Medium

### ME-01: `purge_file` 在 Qdrant 主 collection 不存在时误记 `qdrant_main` 失败，违反幂等契约

**File:** `server/services/purge.py:119-133`（对照 `server/services/qdrant_service.py:710-732`）
**Issue:**
`QdrantService.delete_by_file_path` 对**不存在的 collection** 会触发 `UnexpectedResponse`
（404）并返回 `False`。`purge_file` 据此 `result.failures.append("qdrant_main")`。于是对一个
"从未索引（无 collection）但 FileIndex/ChunkRegistry 有残留"的仓库做清理，或对已清净的文件
**重复** purge，都会被标成 `qdrant_main` 失败 → `run_cleanup` 把整个 `CleanupRun` 置
`status=failed`。这与模块 docstring 承诺的"文件已不存在/各面已空时全部 no-op，计数 0、
`failures` 空"的幂等语义矛盾，会让一次实际上"无残留"的清理对用户显示为失败。
**Fix:** 区分"collection 不存在（幂等 no-op）"与"真实删除失败"。可在 `delete_by_file_path`
对 collection-not-found 返回成功语义（或新增标记），`purge_file` 据此不计 failure。

### ME-02: 清理无并发护栏，并发派发产生竞态与陈旧状态回显

**File:** `server/repositories/views.py:1156-1167`；`server/services/purge_reconcile.py:139-155`
**Issue:**
POST 每次都新建 `CleanupRun(running)` 并派发后台 `run_cleanup`，对同一仓库无"已有 running
则拒绝/排队"的护栏。两个并发清理会并行 `purge_file` 同一批路径（虽多为幂等，但 codegraph/
overlay 删除与摘要重建会重复甚至交错），且状态端点取"`-started_at` 最近一条"，先发后完成
的旧 run 可能在新 run 之后落终态，导致前端回显与实际不符。
**Fix:** 派发前检查该仓是否存在 `status=running` 的 `CleanupRun`，存在则拒绝（409）或复用；
或对 `CleanupRun` 做仓库级互斥。

### ME-03: `_redact_value` 子串匹配易误命中，过度脱敏

**File:** `server/services/sensitive_purge.py:272-274`
**Issue:**
`any(t and t in value for t in targets)` 用**裸子串**判断命中。被排除路径若较短（如
`a.py`、`api.py`），会成为无关文本/其他路径（`schema.py`、`data.py`）的子串，触发误脱敏。
对 `ActionLog.payload` / `Message` 等自由文本面尤其放大误删面。
**Fix:** 按路径边界匹配（前后为分隔符/字符串边界），或匹配完整 token，降低假阳性。

### ME-04: `TaskResult`/`ActionLog` 仅按归一化 `git_url` 关联，多仓共享同一 remote 会互相误清

**File:** `server/services/sensitive_purge.py:218-233, 298-313, 58-70`
**Issue:**
关联判据是 `_normalize_repo_url(session.repo_url) == _normalize_repo_url(repo.git_url)`。若
两条不同 `Repository`（不同 id、不同排除规则）指向**同一 remote**（同一仓库克隆为两条记录、
或 mirror），对其一做敏感清理会把按 URL 关联到的 `TaskResult`/`ActionLog` 一并 scrub，影响
另一条仓库的产物（over-scrub）。
**Fix:** 关联尽量收敛到 `Repository` 维度的稳定外键/会话归属，而非仅 URL；URL 相同但仓库
不同的记录应谨慎处理（或在 caveat 中声明）。

## Low

### LOW-01: overlay 枚举仅依赖 `RepositoryBranchIndex` 行，孤儿 overlay collection 残留

**File:** `server/services/purge.py:60-73`
**Issue:**
`_overlay_collection_names` 只枚举 `RepositoryBranchIndex.collection_name`。若某 branch 的
index 行已被删除而其 Qdrant overlay collection 物理仍在（孤儿），`purge_file` 不会枚举到它，
被排除文件的向量在该孤儿 collection 中残留。属边界场景，但与"删后无残留"目标相关。
**Fix:** 可在对账/清理路径补一条孤儿 overlay collection 的探测（按命名前缀枚举 Qdrant 实际
collection 与 index 行比对），或文档化该残留面。

---

_Reviewed: 2026-06-14T15:59:35Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
