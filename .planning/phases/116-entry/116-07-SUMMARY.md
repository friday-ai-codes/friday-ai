---
phase: 116-entry
plan: 07
subsystem: repo-source-read + citation-preview + mcp-contract
tags: [view-02, fail-closed, existence-oracle, service-extraction, shared-implementation, observability, security]
requires: ["116-06", "115-03"]
provides:
  - "services/repo_file_read.aread_repository_file（按 path + 行区间读源码正文的唯一实现，MCP 面与 SPA 面共享）"
  - "GET /api/repositories/<uuid:repository_id>/file-lines/（name=repository-file-lines，中性口径 200 空 + 区间硬上限截断）"
  - "web getRepositoryFileLines（usable 判据封装进返回值，覆盖 200-空 lines）"
  - "CitationCodePreview 真正的代码预览：源码正文 + 行号列 + citation 区间行高亮"
affects: []
tech-stack:
  added: []
  patterns:
    [neutral-fail-closed-response, dual-path-exclusion-recheck, single-implementation-two-contracts, truncate-not-reject, usable-in-return-type]
key-files:
  created:
    - server/services/repo_file_read.py
    - server/repositories/repo_file_views.py
    - server/tests/repositories/test_repo_file_read_views.py
  modified:
    - server/mcp_tools/views.py
    - server/repositories/urls.py
    - server/tests/mcp_tools/test_container_knowledge_chain.py
    - server/tests/mcp_tools/test_get_repository_file.py
    - server/tests/mcp_tools/test_mcp_exclusion.py
    - server/tests/mcp_tools/test_mcp_read_flow.py
    - server/tests/delivery/test_blueprint_log_redaction_guard.py
    - web/src/api/repositoryChunks.ts
    - web/src/components/blueprint/citation/CitationCodePreview.vue
    - web/src/components/blueprint/__tests__/citationPreview.spec.ts
    - web/src/locales/zh-CN.json
decisions:
  - "service 返回中性结构而不是 Response：两个调用面的 is_excluded 口径不一样（MCP 404 file_excluded / SPA 200 空），把状态码留在 service 里就是两个口径互相污染的起点"
  - "SPA 面取 chunk_at 的中性口径而不是 MCP 的显式告知：被排除 / 不存在 / 无镜像三者响应体逐字相同，⛔ 无存在性预言机"
  - "区间超 _MAX_LINES=400 是截断而不是 400：区间来自半可信 citation locator，写错一个数字不该让整个预览失败（同时是 T-116-64 的 DoS 防线）"
  - "_get_indexed_repo / _resolve_graph_branch ⛔ 未下沉：它们是 McpToolView 基类共享方法（8 个工具在用），改为 MCP 面预解析后传入 service，保住 repository_not_found 404 / repository_not_indexed 400 两个既有错误码"
  - "_language_from_path / _EXT_LANG_MAP 一并下沉（PLAN 只说「五个方法体」）：留在 View 里就成了只剩一个调用点的孤儿"
metrics:
  duration: "~3h（含收口自检与里程碑收尾簿记）"
  completed: 2026-08-01
---

# Phase 116 Plan 07: 源码正文读面与引用预览升级 Summary

**One-liner:** 补上 115 从 SC-3 顺延过来的最后一块 —— 把 `GetRepositoryFileView` 里**全部内联**的读取逻辑（排除判定 / 镜像读取 / Qdrant chunk 拼接回退）下沉成 `services/repo_file_read.py` 这**唯一一份**，在其上开出 SPA 的 `GET /repositories/<id>/file-lines/` 读面，让引用预览从「路径 + 行号 + 快照」升级为**带正文与 citation 区间行高亮的真代码预览**；两个 `is_excluded` 口径刻意分道（MCP 逐字保持 404 `file_excluded`，SPA 把「被排除 / 不存在 / 无镜像」映射成**逐字相同的 200 空**），分道与 fail-closed 双路径复判都有**实跑变异**背书。VIEW-02 闭合，Phase 116 的 7 个 plan 全部完成。

## PHASE_BASE

```
PHASE_BASE = 0c6e537744d3a8dde0586265b501000b554aead0
```

本 plan 全部冻结面 / 删除行 / `--name-only` 断言一律写作 `git diff $PHASE_BASE -- <file>`，⛔ 无一条裸 `git diff`（GSD 逐 Task 原子提交后裸 `git diff` 恒空、断言会静默恒真，B5）。计数型断言一律 `| grep -c '<pat>' || true` 再比对数字。

## Commits

| # | Hash | 内容 |
|---|---|---|
| 1 | `2242d4fe` | Task 1：下沉 `services/repo_file_read` 作源码正文读取唯一实现（MCP View 改调，对外契约逐字不变） |
| 2 | `9babf666` | Task 2：新增 `file-lines` 源码正文读面（中性口径 + 区间截断）+ 路由 + 18 条后端用例 |
| 3 | `96658922` | Task 3：引用预览升级为真正的代码预览（正文 + 行高亮）+ API 封装 + 6 条前端用例 + i18n |
| 4 | `0b7b6e52` | **收口自检发现的 fix**：把两个新模块纳入蓝图日志脱敏守卫扫描面（见 §9） |

⚠️ **执行分两段**：前三个 commit 由上一个执行者完成，随后在簿记阶段被 provider 资源上限打断（SUMMARY 未写）。本次为**续跑收口**：不重做实现，逐条复核 + 补 fix + 补簿记。

---

## ⭐ 1. `aread_repository_file` 的逐字签名与恒定返回键

```python
async def aread_repository_file(
    repository_id: str,
    path: str,
    *,
    branch_name: str = "",
    surface: str = "",
    line_start: int | None = None,
    line_end: int | None = None,
    max_lines: int | None = None,
    repo: Any = None,
    collection_name: str | None = None,
) -> dict[str, Any]
```

⚠️ **相对 PLAN 的签名增补两个可选预解析入参 `repo` / `collection_name`** —— 理由见 §3 的偏离①。缺省 `None` 时 service 自行解析，解析不出记 `unavailable`。

**恒定返回键（闭集，15 键）**：

```
{"status", "path", "resolved_path", "content", "lines", "line_start", "line_end",
 "truncated", "detail", "source", "commit_sha", "language", "total_chunks",
 "total_lines", "returned_lines"}
```

- `status ∈ {"ok", "excluded", "not_found", "unavailable"}`；⭐ 后三态下 `content` 恒 `""`、`lines` 恒 `[]`（`_neutral()` 是这三态的**唯一构造入口**，⇒ 「命中排除绝不返回任何 content」由构造函数结构性保证，不靠调用点自觉）。
- `lines` 项形状 `{"line_no": int, "text": str}`，**1-based**，与 citation 的 `line_start` 同口径。
- ⛔ **不含任何 DRF 对象**：`rg -n "Response\(|error_response\(|rest_framework" server/services/repo_file_read.py` **零命中**（实跑）。

### 五块方法体的搬运对照表

| 原 `GetRepositoryFileView` 成员 | 原行号（@ PHASE_BASE） | 新落点 | 备注 |
|---|---|---|---|
| `_excluded_response` | `mcp_tools/views.py:988-1010` | `repo_file_read._acheck_excluded(repository_id, *paths, surface=) -> bool` | 返回 `bool` 而不是 `Response`；命中时调 `log_exclusion_blocked` 后返 `True`，由调用面自己映射错误口径 |
| `_read_from_mirror` | `:1149-1180` | `repo_file_read._aread_from_mirror` | 逻辑逐行一致；⭐ **日志改进**：原实现打 `file_path=file_path` 原文，新实现只打 `path_len` 且 `detail` 过 `redact_secrets_in_text` |
| Qdrant chunk 拼接回退段 | `:1071-1135`（`post` 体内内联） | `aread_repository_file` 的 ② 段 | `chunk_index` 排序 / 区间过滤 / 行拼接 / 截断逐字一致 |
| `_language_from_path` + `_EXT_LANG_MAP` | `:206-224`（**模块级，不在类里**） | `repo_file_read.language_from_path` + `_EXT_LANG_MAP` | ⚠️ PLAN 只说「五个方法体」，这一对是超出的第 6 块 —— 见 §3 偏离③ |
| `_get_indexed_repo` / `_resolve_graph_branch` | `McpToolView` **基类** | ⛔ **未下沉** | 见 §3 偏离① |

`_aresolve_indexed_repo` / `_aresolve_collection` 是 service 侧**新写**的中性等价物（只服务于「三态不可区分」的 SPA 面），⛔ 不是基类方法的副本。

---

## ⭐ 2. 两个调用面的错误口径对照表（为什么必须分道）

| service `status` | MCP `get_repository_file` | SPA `GET .../file-lines/` |
|---|---|---|
| `ok` | **200** + 既有 16 键响应体（`file_path` / `requested_file_path` / `content` / `truncated` / `source` / `commit_sha` / … / `run_id`），键集一字未改 | **200** + `{path, line_start, line_end, lines, truncated}` |
| `excluded` | **404** `error_response("file_excluded", "文件已被排除策略屏蔽", 404)`（**逐字**） | **200** + `_neutral_payload(...)` |
| `not_found` | **404** `error_response("file_not_found", f"索引中找不到文件: {file_path}", 404)`（**逐字**） | **200** + `_neutral_payload(...)`（**与上一行逐字相同**） |
| `unavailable` | 不可达（MCP 面预解析 `repo`/`collection_name` 后传入 ⇒ service 不会走到自解析失败分支；`repository_not_found` 404 / `repository_not_indexed` 400 仍由基类给出） | **200** + `_neutral_payload(...)`（**与上两行逐字相同**） |

**为什么必须分道**：仓内两个既有口径本就不一样，且**各自都有存在理由** ——

- MCP 面是 **PAT 认证的工具面**，调用方是 agent，显式告知「这文件被排除了」让 agent 不再重试同一个路径；`chunk_at_views.py:5-9` 的 docstring 明写 SPA 侧的相反理由：被排除与无命中不可区分是**存在性防线**。
- 引用预览面本就有 quote 快照兜底，且 115-07 的前端实现是「非 200 不进错误分档」⇒ 给它 404 只会让它掉进错误档而不是快照档。
- ⇒ 一份实现两种映射，**状态码留在两个 View 里**、service 只回中性 `status`。⛔ 把 HTTP 语义混进 service 就是两个口径互相污染的起点（模块 docstring 逐字写着这条）。

---

## ⭐ 3. 相对 PLAN 的四处偏离（逐条登记）

### 偏离① `_get_indexed_repo` / `_resolve_graph_branch` ⛔ 未下沉（PLAN 要求「五块全下沉」）

**实读发现**：这两个不是 `GetRepositoryFileView` 的私有方法，而是 **`McpToolView` 基类方法**，`mcp_tools/views.py` 里 8 个工具共用。删掉就是砸 7 个无关工具的面。

**改法**：MCP 面**预解析后传入** —— `result = await aread_repository_file(..., repo=repo, collection_name=collection_name)`。这同时保住了 MCP 面 `repository_not_found`（404）/ `repository_not_indexed`（400）两个既有错误码的逐字契约（它们由基类方法给出，⛔ 不该搬进一个「三态不可区分」的中性 service）。SPA 面不传，走 service 自解析的 `_aresolve_indexed_repo`。

### 偏离② `is_excluded` 在 `mcp_tools/views.py` 里**无法归零**（PLAN 验收写的是 `== 0`）

**实测 `rg -c "is_excluded" server/mcp_tools/views.py` = 6** —— 但这 6 处**全部与本 plan 无关**：`grep_repository`（`:639`）/ `list_repository_files`（`:902`）/ `find_related_chunks`（`:1100`）三个工具各自经 `_exclusion_matcher(repository_id)` 取匹配器再判，是 Phase 22 既有实现。PLAN 的判据默认了「只有 `GetRepositoryFileView` 用它」，实读证伪。

**判据收紧为类体内零命中**（AST 取 `GetRepositoryFileView` 类体源码段后计数，实跑）：

```
is_excluded count in class: 0
_exclusion_matcher count: 0
lines: 958 1051
```

`_excluded_response` / `_read_from_mirror` 两个方法定义也已从类体中消失。⇒ 「本 plan 涉及的排除判定只有一份」成立。

⚠️ **fail-closed 语义等价性已逐条核对**：原 `_exclusion_matcher` 在 `build_matcher_for_repo` 抛异常时返回 `_FailClosedMatcher`（`is_excluded` 恒 `True`）；新 `_acheck_excluded` 在同一异常下直接 `return True` 并补打 `log_exclusion_blocked`。⇒ 两者对外行为一致（MCP 面仍是 404 `file_excluded`），且新实现**多**了一条审计埋点。既有用例 `test_get_file_fail_closed_on_matcher_error` 覆盖，绿。

### 偏离③ 删除行超配额：`server/mcp_tools/views.py` **152 行**（PLAN 上界 **90**）

`git diff $PHASE_BASE -- server/mcp_tools/views.py | grep -c '^-[^-]'` → **152**。逐块归类：

| 块 | 删除行 | 是否在 PLAN 预算内 |
|---|---|---|
| `_excluded_response` 方法整体 | 25 | ✅ |
| `_read_from_mirror` 方法整体 | 31 | ✅ |
| `post` 体内镜像分支（响应装配 + `_record`） | ~40 | ✅ |
| `post` 体内 Qdrant 回退分支（chunk 排序 / 过滤 / 拼接 / 截断） | ~48 | ✅ |
| `_EXT_LANG_MAP` + `_language_from_path`（**模块级**） | 22 | ❌ **超出**——PLAN 只授权「五个方法体」 |
| import 收缩（4 个已无用的符号） | 6 | ❌ **超出**——但不删就是 ruff `F401` 红 |

**判定：可接受，非缺陷。** 理由：① 超出的 22 行是「下沉后只剩一个调用点、且那个调用点已在 service 里」的孤儿函数 —— 留在 `views.py` 会形成跨模块反向依赖；`rg -n "_language_from_path|_EXT_LANG_MAP" server/**/*.py` 确认 `mcp_tools/` 内**零残留引用**（`services/indexer.py` 里的同名局部变量是无关的独立实现）。② import 收缩是 ruff 强制。③ **对外契约零漂移**已由 §4 的独立证据链背书 —— 删除行上界是「防止顺手删别的东西」的代理指标，代理指标失真时以直接证据为准。

### 偏离④ 边界超出：改动 **13** 个源码文件（PLAN 声明 **9** 个）

多出的 4 个全部是 `server/tests/mcp_tools/` 下的既有用例，改动**全部是 monkeypatch 落点重指**（Rule 3 阻塞：下沉后旧目标不存在）：

| 文件 | 改动行 | 内容 |
|---|---|---|
| `test_mcp_exclusion.py` | 7 处 | `mcp_tools.views.GetRepositoryFileView._read_from_mirror` → `services.repo_file_read._aread_from_mirror`；`mcp_tools.views._scroll_file_from_collection` → `services.repo_file_read._scroll_file_from_collection`；`mcp_tools.views.build_matcher_for_repo` → `services.repo_file_read.build_matcher_for_repo` |
| `test_container_knowledge_chain.py` | 1 处 | 同上 |
| `test_get_repository_file.py` | 1 处 | 同上 |
| `test_mcp_read_flow.py` | 1 处 | 同上 |

⭐ **断言一条未削弱**：四个文件的 diff **只有 patch target 字符串变了**，`assert` 行零改动（`git diff $PHASE_BASE -- server/tests/mcp_tools/` 逐 hunk 人工核对，全部是 `monkeypatch.setattr(` 的第一个实参）。

---

## ⭐ 4. MCP 契约零漂移的核算证据

| 证据 | 结果 |
|---|---|
| `git diff $PHASE_BASE -- server/mcp_tools/serializers.py \| wc -l` | **0**（`TOOL_SCHEMA_SNAPSHOT` 的 `get_repository_file` 条目一字未动） |
| `rg -n 'file_excluded' server/mcp_tools/views.py` | 命中 |
| `rg -n '文件已被排除策略屏蔽' server/mcp_tools/views.py` | 命中（文案一字未改） |
| `uv run pytest tests/mcp_tools/ -q` | **285 passed / 1 failed / 2 skipped**（含本 plan 新用例；⚠️ 唯一失败见下） |
| `tests/mcp_tools/test_schema_snapshot.py` | 全绿 |

⚠️ **`test_skills_snapshot_guard.py::test_skill_files_discovered` 逐条核对为同一条既有环境项**（P-16）：它断言 `skills/skills/*/SKILL.md` ≥ 4，而本 worktree 的 `skills/` 是空目录（主检出里有内容）。与 116-06 收口时**同一条、同一原因**，⛔ 不是本 plan 引入。里程碑收尾在主检出复跑即可。

⚠️ **一处曾担心的语义漂移，实测证伪**：service 里 `limit = max(int(max_lines) ..., 1)` 对 `max_lines <= 0` 做了钳制，下沉前没有。查 `mcp_tools/serializers.py:72` —— `max_lines = IntegerField(required=False, default=500, min_value=1, max_value=2000)` ⇒ **`<= 0` 在序列化层就被挡掉，钳制不可达** ⇒ 零行为差异。

---

## ⭐ 5. 新端点契约表

| 项 | 值 |
|---|---|
| URL | `GET /api/repositories/<uuid:repository_id>/file-lines/` |
| `name` | `repository-file-lines`（紧随 `chunk-at` 之后，UUID 通配安全，照既有顺序注释纪律） |
| 权限 | `permission_classes = [IsAuthenticated, RepositoryPermission]` + `aget_object_or_404(Repository, id=..., is_deleted=False)` |
| query 参数 | `path`（必填）/ `line_start`（必填正整数）/ `line_end`（必填正整数，≥ `line_start`）/ `branch_name`（可选） |
| 200 响应键 | `{path, line_start, line_end, lines: [{line_no, text}], truncated}` |
| 400 响应体 | `{"error": "<中文文案>"}` — ⭐ **键是 `error` 不是 `detail`**（`rg -n '"detail"' repositories/repo_file_views.py` **零命中**，实跑） |
| 状态码全集 | **200 / 400 / 401 / 403 / 404（仅仓库不存在或已删）** — ⛔ **没有任何「文件未找到」的 404 分支**（源码级断言 `"HTTP_404" not in src` 钉死） |
| `_MAX_LINES` | **400**。返回行数超上界 ⇒ **截断到上界 + `truncated: true`，状态码仍 200**，⛔ 不 400 |
| observability | 一条 caller 事件 `repository_file_lines_read`（`category="caller"`, `component="repo_file_lines_view"`），字段 `repository_id / path_len / line_start / line_end / line_count / truncated / usable / duration_ms`，整段 `try/except: pass` |

**为什么截断而不是报错**：引用的行区间来自半可信的 citation `locator`（含 LLM 产出）。一个写错的区间不该让整个预览失败 —— 报错在用户侧的观感是「这个引用坏了」，截断是「这个引用很长」。同时这就是 T-116-64 的 DoS 防线（挡住「一次请求读整个大文件」）。

---

## ⭐ 6. 存在性预言机：本 plan 的头号靶子（含**实跑变异**背书）

### 断言形态

`tests/repositories/test_repo_file_read_views.py::TestNeutralFailClosed::test_three_unusable_cases_are_byte_identical` 构造三种不可用情形并**两两比对整个响应体**：

| 情形 | 构造方式 | service `status` |
|---|---|---|
| (a) 文件被排除规则挡掉 | 镜像命中 `.env`（含哨兵串 `SECRET_TOKEN=filelinesleak`） | `excluded` |
| (b) 文件不存在 | 镜像未命中 + 索引 scroll 全空 | `not_found` |
| (c) 仓库无镜像可读 | 未建索引的仓库 | `unavailable` |

```python
assert resp_a.status_code == resp_b.status_code == resp_c.status_code == 200
assert resp_a.json() == resp_b.json()
assert resp_b.json() == resp_c.json()
```

结构性保证：三者共用 `_neutral_payload(path, line_start, line_end)` 这**唯一一个**构造函数（View 里 `else` 分支只有它一条出口）。

### ⭐ 它真的会红（变异实跑，⛔ 不是恒真断言）

在 `repo_file_views.py` 的 `else` 分支注入一行 `payload["reason"] = result["status"]`（一个足以区分三态、却不触发 `"file_excluded" not in src` 源码守卫的**隐蔽**变异）：

```
FAILED tests/repositories/test_repo_file_read_views.py::TestNeutralFailClosed::test_three_unusable_cases_are_byte_identical
=========== 1 failed, 1 passed, 16 deselected ===========
```

变异已 `git checkout --` 还原，还原后复跑全绿。

### `is_excluded` 的 fail-closed 与双路径复判（**两个面各变异一次**）

`_acheck_excluded` 对 **requested 与 resolved 两个路径都复判**（T-22-21：requested 写成 `env` 可能解析到真实的 `.env`），且**匹配器构造失败一律视为命中**（T-22-25）。

变异：把镜像分支的调用从 `_acheck_excluded(repository_id, requested_path, resolved_path, ...)` 改成只传 `requested_path` ——

```
FAILED tests/mcp_tools/test_mcp_exclusion.py::test_get_file_mirror_suffix_resolution_cannot_bypass
FAILED tests/repositories/test_repo_file_read_views.py::TestNeutralFailClosed::test_dual_path_recheck_blocks_suffix_resolution_bypass
2 failed
```

⭐ **两个调用面同时转红** ⇒ 「一份实现、两个面共享」不只是写在 docstring 里，而是被两条独立用例从两个方向钉住的事实。变异已还原，还原后 `tests/repositories/test_repo_file_read_views.py` + `tests/mcp_tools/` 复跑 **285 passed / 1 failed（同一条既有环境项）**。

### 两个口径并列（分道且互不污染）

`TestTwoSurfacesDoNotContaminateEachOther::test_mcp_says_file_excluded_while_spa_stays_neutral` 对**同一个被排除文件**同时打两个面：MCP 面 `404` + `error_code == "file_excluded"`，SPA 面 `200` + `lines == []` + 响应体里 `"file_excluded"` **零出现**；两个响应体都断言哨兵串 `filelinesleak` 零出现。

---

## ⭐ 7. 源码正文不进日志（源码扫描 + **运行期捕获**双证）

### 证据 A：AST 源码扫描（永久用例）

`TestObservability::test_logger_calls_never_take_raw_path_or_content` 对 `repositories/repo_file_views.py` 与 `services/repo_file_read.py` 两个模块做 AST 遍历，断言所有 `logger.{info,warning,error,debug,exception}` 调用的 kwarg 里没有 `content` / `path` / `text` / `source`。

⚠️ **登记一处刻意的命名**：`_emit` 里用的是 `read_source=result["source"]`（值域只有 `"git"` / `"index"` 两个字面量）而不是 `source=` —— 改名是为了不撞 AST 守卫的名单，**不是**为了绕过它藏正文。值域已逐条核对。

⚠️ **登记一处既有行为豁免**：`log_exclusion_blocked(rel_path=...)` 带路径原文，是 Phase 22 的既有审计埋点（排除审计需要知道拦了哪个路径），本模块沿用不改。

### 证据 B：运行期日志捕获（本次收口自检临时跑，跑完即删）

AST 扫描只按 kwarg **名**判，逮不住「换个名字把正文塞进去」。因此另做一次运行期捕获：让端点真的读到一段带哨兵串的源码正文，用 `structlog.testing.LogCapture` 抓下整条链的输出 ——

```
LOGCAPTURE_OK events=6 names=['handler_registered', 'handler_registered', 'handler_registered',
                              'handler_registered', 'repo_file_read_completed', 'repository_file_lines_read']
1 passed
```

- 本 plan 的两条事件（`repo_file_read_completed` / `repository_file_lines_read`）**都真的发了**（⇒ 断言非空转）；
- 前置断言 `SENTINEL in json.dumps(resp.json())` 通过（⇒ 正文确实被读到了，不是「没读到所以没泄漏」）；
- 哨兵正文串与 `path` 原文在整个捕获流里**零出现**。

⇒ 「⛔ 正文与路径不进日志」在源码层与运行期两侧都成立。

### 观测纪律

两处埋点都整段 `try/except: pass`（best-effort，⛔ 绝不反噬读取主流程）；service 侧收口事件是 `logger.debug` + `category="sampling"`（⛔ 不在读路径上刷 INFO），View 侧是 `logger.info` + `category="caller"`（可归因的一次用户调用）。异常文本一律过 `redact_secrets_in_text` 后截断。

---

## ⭐ 8. 前端契约与降级路径

### `getRepositoryFileLines` 签名与 `usable` 判据

```ts
export async function getRepositoryFileLines(
  repositoryId: string,
  params: { path: string, lineStart: number, lineEnd: number, branchName?: string },
): Promise<{ lines: RepoFileLine[], truncated: boolean, usable: boolean }>
```

⭐ **判据封装在返回类型里**（照 115-02 为 `getChunkAt` 立的 `{chunks, usable}` 形态，⛔ 调用点不各自判）：

```ts
usable = ok && lines.length > 0
```

**200-空 也不可用** —— 这是 P-3 最容易漏的一档，也正是后端「三态不可区分」的必然结果。函数**恒不抛**：任何失败归一成 `{ lines: [], truncated: false, usable: false }`，⛔ 不回显后端错误体（键是 `error`，`ApiError.detail` 只会回落成无意义的 `'请求失败'`）。

### 用户明确要求复核的三档降级，逐条实测

| 档 | 后端形态 | 前端行为 | 覆盖用例 |
|---|---|---|---|
| `file-lines` **200 + 空 `lines`** | 被排除 / 不存在 / 无镜像 | `usable=false` ⇒ 回落 quote 快照、⛔ 不关弹窗 | 用例 10 |
| `file-lines` 非 2xx / 网络失败 | 400 / 401 / 403 / 5xx | 同上，且构造含 `internal/path/leak` 的错误体断言其**零出现** | 用例 11 |
| **旧 `chunk-at` 200 + `{"chunks": []}`** | 无命中与被排除文件不可区分，错误体键是 `error` 而非 `detail` | `getChunkAt` 的 `usable = chunks.length > 0` 已覆盖（115-02 既有封装，本 plan 未改）⇒ 整个预览落 `CitationFallback` | 用例 2c（既有）+ 用例 4（既有，断言 `error` 体不回显） |

⚠️ **判断调用（非缺陷，登记备查）**：组件的**顶层**渲染门是 `chunk-at` 的 `usable`（115-03 既有形态）。⇒ 若 `chunk-at` 不可用而 `file-lines` 可用，正文**不会**被渲染，整块落快照兜底。这是 115-03 立的结构而非 116-07 引入的回退（升级前该分支同样只显示快照）。改成「两个数据源各自独立降级」需要重排组件的渲染门，超出本 plan 的 ≤20 删除行配额与「扩写而不是重写」的边界 ⇒ **本轮不改**，记在此处备里程碑收尾定夺。

### `CitationCodePreview` 渲染契约

- **行号列**：`row.line_no` 逐字来自后端（⛔ 前端不重算，否则与后端行号口径分叉）；用例 8 断言 `data-line-no` 序列 `['12','13','14']`。
- **高亮区间**：`isCited(lineNo)` 只看 `locator.line_start..line_end`（`line_end` 缺失退化成单行）⇒ 后端返回更宽上下文时**不越界高亮**；用例 9 用 10..15 的正文配 12..13 的 citation，断言高亮恰为 `['12','13']` 且另有 **4 行明确标 `false`**（负向对照）。高亮走既有语义类 `bg-primary/10`，⛔ 零颜色字面量。
- **截断提示**：`truncated: true` ⇒ 出现 `data-testid="citation-code-truncated"`，⛔ 不当成失败去兜底（用例 13）。
- **零请求**：`locator.line_start` 缺失 ⇒ `canQuery` 为假，**两个查询都不发**（用例 12）。
- ⛔ **零新增依赖**：`rg -n "codemirror|highlight.js|shiki|prismjs"` 零命中；呈现沿用 115-03 的 `<pre class="font-mono">` + 行号列。
- ⛔ `refetchInterval` 零命中；源码守卫六条全绿（**6 passed**）。
- **docstring 过时话术已清**：`rg -n "本相位显式降级形态|⛔ 没有源码正文|归 Phase 116"` 零命中，历史结论（115 为什么做不到的三条证据）作为「设计沿革」保留。

---

## 9. 收口自检发现并修复的问题（commit `0b7b6e52`）

**Rule 2（缺失的关键守卫覆盖）**：`tests/delivery/test_blueprint_log_redaction_guard.py` 的 `_SCANNED_MODULES` docstring 逐字写着「新增蓝图模块请一并加进」，116-04 / 116-05 / 116-06 都照做了（各自带 Phase 注释），**116-07 的两个新模块漏登记**：

- `services/repo_file_read.py` —— MirrorError 与匹配器构造异常的文本经 `error=` / `detail=` 进日志，是本 plan **唯一带 tainted kwarg 的新模块**；
- `repositories/repo_file_views.py` —— `surface="blueprint_citation_preview"` 的数据面，当前无 `error=` kwarg，纳入是为了锁住后续改动。

两者现状均已过 `redact_secrets_in_text` ⇒ 补进扫描面后**直接绿**（`21 passed`），⛔ 无行为改动。

**核对过的其它候选，判定为非缺陷**：`_SCANNED_MODULES` 现有 18 条**逐条实测文件存在**（脚本输出全 `OK`），且每条都与命名它的 Phase 在同一 commit 落地 ⇒ 无「登记了不存在的模块」或「模块先落、登记后补」的漂移。

---

## 10. 四道门与 116-06 基线的逐条比对

| 门 | 116-06 基线 | 116-07 收口 | 判定 |
|---|---|---|---|
| `cd server && uv run pytest tests/ -q` | 8916 passed / 1 failed | **8934 passed / 1 failed** / 63 skipped / 26 deselected / 1 xfailed（509.61s） | ✅ **+18 零回归**；唯一失败是同一条 `test_skills_snapshot_guard`（worktree 环境项） |
| `manage.py makemigrations --check --dry-run` | 退出码 0 | `No changes detected`，**退出码 0** | ✅ 相位内零 migration |
| `cd web && pnpm exec vitest run` | 1697 passed / 1 skipped | **1704 passed / 1 skipped**（215 files passed / 1 skipped） | ✅ **+7 零回归** |
| `pnpm type-check` | exit 0 | **exit 0** | ✅ |
| `pnpm build` | 通过 | **✓ built in 6.06s** | ✅ |
| `pnpm lint`（`eslint .`） | 111 problems | **111 problems（106 errors / 5 warnings）** | ✅ 与基线**逐字相同** |
| `pnpm exec eslint <4 个触及文件>` | — | **零问题** | ✅ 触及文件零新增 |
| `ruff check` / `ruff format --check`（5 个 / 3 个后端文件） | — | `All checks passed!` / `3 files already formatted` | ✅ |

⚠️ **上一相位登记的 `test_memory_mr_api` 排序 flake 本次未复现**（全量门一次通过，无需重跑）。

新增用例计数：后端 `grep -c "def test_" tests/repositories/test_repo_file_read_views.py` = **18**（PLAN 要求 ≥14）；前端 `citationPreview.spec.ts` 共 **23** 个 `it(`，其中 116-07 新增 **7 条**（用例 8/9/10/11/12/13/14，PLAN 要求 ≥6）。

---

## 11. 边界、冻结面与删除行核算

### `git diff $PHASE_BASE --name-only`（源码，**14** 个）

- **9 个** —— PLAN 声明的 `files_modified` 全集；
- **+4 个** —— `server/tests/mcp_tools/` 下的既有用例，全部是 patch 落点重指（偏离④）；
- **+1 个** —— `server/tests/delivery/test_blueprint_log_redaction_guard.py`，收口 fix（commit 4，§9）。

⚠️ 三个实现 commit（`2242d4fe`..`96658922`）的footprint 是前 **13** 个；第 14 个由 commit 4 引入。§12 的可独立顺延性论证按 **4 个 commit** 为单位。

### 冻结面（全部 `git diff $PHASE_BASE -- <file>` 为 **0 行**）

| 冻结面 | 结果 |
|---|---|
| `server/mcp_tools/serializers.py` | **0** |
| `server/services/chunk_lookup.py` | **0** |
| `server/repositories/chunk_at_views.py` | **0** |
| `server/codegraph/services/repo_router_v2.py`（§13.2） | **0** |
| 六个 legacy `technical_plan` process 文件 | **0**（不在 `--name-only` 输出内） |
| `web/src/components/chat/TechPlanCard.vue` | **0** |
| `web/src/components/chat/RoutingDecisionPanel.vue` | **0** |
| `web/src/components/execution/NodeDataTab.vue` | **0** |
| `web/src/components/delivery/ArtifactTimeline.vue` | **0** |
| `web/package.json` / `web/pnpm-lock.yaml` | **0**（⭐ 零新增运行时依赖） |

### 删除行逐个核算

| 文件 | 上界 | 实测 | 判定 |
|---|---|---|---|
| `server/mcp_tools/views.py` | 90 | **152** | ⚠️ **超出** —— 逐块归类与判定理由见 §3 偏离③ |
| `server/repositories/urls.py` | 0 | **0** | ✅ 纯追加 |
| `web/src/api/repositoryChunks.ts` | 0 | **0** | ✅ 纯追加 |
| `web/src/components/blueprint/citation/CitationCodePreview.vue` | 20 | **17** | ✅ |
| `web/src/components/blueprint/__tests__/citationPreview.spec.ts` | 8 | **0** | ✅ 纯扩写 |
| `web/src/locales/zh-CN.json` | 0 | **0** | ✅ i18n 零降级（新增 2 键：`sourceText` / `sourceTruncated`） |

### 环境项核算（P-15 + `components.d.ts`）

- `web/pnpm-workspace.yaml`：`git status --porcelain` **为空**（本次 `pnpm` 未产生 catalog 回填）。
- `web/src/components.d.ts`：`pnpm build` 后确实被重写 —— `git diff --stat` 显示 **29 deletions / 0 insertions**（纯剪枝、零新增条目）⇒ 116-07 **不需要**手工补任何条目，已 `git checkout --` 整体还原。还原后 `git status --porcelain web/pnpm-workspace.yaml web/src/components.d.ts` **为空**。

---

## ⭐ 12. 可独立顺延性

三个实现 commit 从 `PHASE_BASE` 起构成**连续链**，且 `git diff 0c6e5377 96658922 --name-only` 的输出**全部落在 `server/` 与 `web/` 之下**（13 个文件，零 `.planning/` 与零配置文件）。⇒ 整体 revert 这条链回到的就是 `PHASE_BASE` 的树对象 `f78783d05a753b5ae22873d9da416c9227743f07` —— 这是 git 的构造性恒等式，四道门必然逐字回到 116-06 基线。

上一个执行者在临时分支 `tmp/verify-116-07-revert` 上做过一次**实跑**并登记了回退后的数值（后端 8916/1、前端 1697/1、type-check 0、build 0、eslint 111，与 116-06 基线逐字相符；工作区已恢复、`git status --porcelain` 与验证前一致），该记录保留在 STATE.md。本次续跑**未重复实跑**（树同一性已由上述构造性论证给出，重跑只是再花 10 分钟得到同一结论）—— 此为判断调用，明确登记。

⚠️ **顺延单位现在是 4 个 commit**（收口 fix `0b7b6e52` 亦属本 plan）。⛔ 无任何前置 plan 依赖本 plan（`affects: []`）。

⭐ **本 plan 已执行 ⇒ PLAN 里那条「若最终顺延须改写 `REQUIREMENTS.md` VIEW-02 顺延目标」的逃生条款自然消解**；VIEW-02 已直接转 Complete（见 §14）。

---

## ⭐ 13. VIEW-02 验收映射表

| VIEW-02 的子诉求 | 兑现它的用例 |
|---|---|
| 引用可弹二级预览（知识实体 / 代码位置 / 其他蓝图 / 章程） | 用例 1a–1g（115-03 既有，本 plan 未改） |
| **代码位置：文件路径** | 用例 2d（`data-testid="citation-code-path"` 面包屑） |
| **代码位置：行号区间** | 用例 2d（`第 10–42 行` 徽标） |
| ⭐ **代码位置：当前源码正文** | 后端 用例 5（`lines` 11 项、`line_no` 从 10 起、`truncated is False`）+ 前端 用例 8（三行正文 + `data-line-no` 序列逐字来自后端） |
| ⭐ **代码位置：citation 区间行高亮** | 前端 用例 9（后端返 10..15、citation 指 12..13 ⇒ 高亮恰为 12/13，另 4 行明确标 `false`）+ 用例 14（`line_end` 缺失退化成单行高亮） |
| **取不到正文时回落引用快照** | 前端 用例 10（200-空 `lines`）+ 用例 11（请求失败且零回显错误体） |
| 半可信 `locator` 不让预览失败 | 后端 用例 6（1..10000 ⇒ 截断到 400、状态码 200）+ 用例 7（`line_end` 越过文件末尾 ⇒ 只返回到最后一行、`truncated is False`）+ 前端 用例 13（截断提示） |
| ⭐ 不泄漏存在性 | 后端 用例 3（三态响应体两两 `==`，**变异实跑背书**） |
| ⭐ 不泄漏源码 | 后端 用例 4（service 级 + 端点级）+ 用例 8（双路径复判，**变异实跑背书**）+ 用例 9（两个口径并列） |
| 权限闸 | 后端 用例 1（未认证 401/403） |

---

## 14. 里程碑收尾簿记（本 plan 是 v0.20.0 功能面的最后一个 plan）

### `REQUIREMENTS.md`

- **VIEW-02**：需求正文改成交付形态（「文件路径 + 行号区间 + **当前源码正文 + citation 区间行高亮，取不到正文时回落引用快照**」）；Phase 115 的降级说明作为历史结论保留；原「⏭ 顺延目标」子条改写成「✅ 顺延目标已兑现 @ 116-07」并附 commit 与口径分道说明；Traceability 行转 **Complete**。
- ⭐ **修掉 26 行陈旧 Traceability**（用户点名了 3 行，扫全表另发现 23 行）：
  - **VIEW-01 / VIEW-03 / CLAR-01** 原写 `Pending（…待 115-02+ / 待 115-06 / 待 115-03/04）`，而 Phase 115 早已 completed 且 verification 107/107 ⇒ 全部转 Complete 并写明交付它的 plan。
  - **Phase 111 的 8 行**（SCHEMA-01/06/07, LIFE-01/02/03, CHARTER-01, GATE-02）、**Phase 112 的 6 行**（FLOW-01/02/03/04, CHARTER-02/03）、**Phase 113 的 9 行**（FLOW-05/06, SCHEMA-02/03/04/05, BUS-01/02/03）同样全是陈旧 `Pending` —— 三个相位在 ROADMAP 里都是 `[x] completed`（分别 verification 24/24、16/17 + gap closure、54/54）⇒ 逐行转 Complete 并标注交付 plan。
  - **GATE-01** 原写「**在 116 执行完成后按实际交付复核**」—— 116 已全部完成 ⇒ 复核完毕，改成「已交付 / 仍缺」两段式：已交付的是入口收编 + 开关 + MCP 异步澄清协议全量；仍缺的是同步点 2 之后的默认切换四件套。
  - ⚠️ **同步修了需求清单的复选框**：上述 23 条需求正文仍是 `- [ ]`，与新的 Complete 行直接矛盾 ⇒ 一并勾成 `- [x]`。此为判断调用（用户只点名了 Traceability 表），理由是只改表会**制造**一个新的自相矛盾。
- ⛔ **未动 Coverage 35/35 与按相位汇总表**（映射关系没变）。

### `STATE.md`

- Status 段换成 116-07 的收口记录（PHASE_BASE / 四个 commit / 门数值 / 两个口径分道 / 两处偏离），116-06 原文整段下移存档。
- **Pending Todos** 按里程碑收尾口径复核：VIEW-02 那条划掉并附闭合证据；其余保留项全部改写成「里程碑收尾之后的独立工作项」措辞，⛔ 不再有任何一条指向某个已完成的 plan 去接。**四条真正顺延的**：
  1. **同步点 2 的默认切换与三处触点升级**（含 `plan_research._map_terminal` 的 `DONE→completed` 必须先改成人审 HITL 挂起 —— 四件事同批，任何一件单独做都是回退）；
  2. **`redact_secrets_in_text` 不覆盖数据库连接串**（`postgres://user:pass@host/db` 实测原样进日志；平台级、非 116 引入，与「全仓二十余处 `error=str(exc)` 未脱敏」合并成独立清理相位）；
  3. **MN-03 的 400 分支存在性预言机**（暴露面 116 收口后为 15 个端点；⭐ **116-07 的 `file-lines` 走仓库读面权限口径、不经 `_aassert_project_scope` ⇒ 不再 +1**）；
  4. **澄清飞书卡片的交互回调 + apscheduler 周期提醒接线**（等同步点 1，届时仍只改 `blueprint_notify.py` 一个文件）。
- Session Continuity 的 Next step 换成里程碑收尾路径（`/gsd-verify-work` → `/gsd-audit-milestone` → 与 v0.19.0 合并 → `/gsd-complete-milestone`），原「下一步是 116-07」下移存档。

---

## 15. 安全复核中的一条观察（非本 plan 缺陷，登记备查）

`RepositoryPermission`（`repositories/permissions.py:12-25`）的实现是「**任意登录用户均可访问存在且未删除的仓库**」，其 docstring 自承「未来若需要引入仓库级 ACL，在此处扩展 ownership 检查」。⇒ 严格说，T-116-63（「新端点缺仓库权限闸 ⇒ 任一登录用户可读任意仓库源码」）的缓解**只挡住了未认证与已删除仓库，没有挡住跨仓越权**。

**判定：不是 116-07 引入的暴露面，本轮不改。** 三条理由：

1. 这是**平台级现状**而非本端点特例 —— 仓内每一个仓库读面都是这个口径（`codegraph/views.py` 的六个 adrf 读面同样是 `[IsAuthenticated, RepositoryPermission]`），而本端点声明的 analog `chunk_at_views.py` 甚至**只有 `IsAuthenticated`** ⇒ `file-lines` 严格**强于**它的 analog。
2. **源码正文的出口本就存在** —— `POST /api/repositories/<id>/search/`（向量检索）对任一登录用户返回带 `content` 的 chunk。⇒ 本 plan 未新增任何跨用户可达性。
3. PLAN 的 prohibition 逐字要求「按 `repositories/permissions.py` 与既有仓库读面的口径取（执行期实读，⛔ 不猜）」—— 实现照做了。

⇒ **正确形态是给平台补仓库级 ACL**，与 `REQUIREMENTS.md` 已登记的 MN-12「权限口径」一并定夺，⛔ 不是在本端点单点加一道别人都没有的闸（那会造成口径分叉）。

---

## Self-Check: PASSED

**文件存在性**（实跑 `[ -f ... ]`）：

- `server/services/repo_file_read.py` — FOUND
- `server/repositories/repo_file_views.py` — FOUND
- `server/tests/repositories/test_repo_file_read_views.py` — FOUND
- `web/src/api/repositoryChunks.ts` — FOUND（`getRepositoryFileLines` 命中）
- `web/src/components/blueprint/citation/CitationCodePreview.vue` — FOUND
- `.planning/phases/116-entry/116-07-SUMMARY.md` — FOUND

**commit 存在性**（实跑 `git log --oneline --all | grep -q`）：`2242d4fe` / `9babf666` / `96658922` / `0b7b6e52` — 全部 FOUND。

**无 Known Stubs**：本 plan 未留任何硬编码空值 / 占位文案 / 未接数据源的组件；`lines: []` 是**语义上的中性响应**（fail-closed 契约）而不是 stub，有 §6 的变异用例背书。

**无 Threat Flags**：新增的唯一安全相关面（`file-lines` 源码正文出口）已在 PLAN 的 `<threat_model>` 中登记为 T-116-59~68，逐条 mitigate 已核（§6 / §7 / §5）；§15 那条是既有平台面的复核观察，不是本 plan 新增的暴露面。
