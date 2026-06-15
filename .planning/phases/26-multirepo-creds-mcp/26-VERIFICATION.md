---
phase: 26-multirepo-creds-mcp
verified: 2026-06-15T01:29:37Z
status: passed
score: 7/7 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 6/7
  gaps_closed:
    - "同一 GitLab 实例多仓可复用同一凭证（D-02：所有 git 平台 API / 容器 dispatch 取 token 路径统一经解析器，消除散落的 per-repo 取 token 逻辑）"
  gaps_remaining: []
  regressions: []
deferred:
  - truth: "管理员可在前端 /admin/git-credentials 页面完成实例凭证 CRUD（浏览器端交互观感）"
    addressed_in: "Deferred UAT (autonomous)"
    evidence: "前端页面 / API client / vitest 守护测试均已落地且通过；纯浏览器端交互观感按指示作非阻塞 UAT 处理"
---

# Phase 26: 多仓凭证统一 + MCP 多仓参数 Verification Report

**Phase Goal:** GitLab 凭证统一池 + MCP RAG 多仓检索参数。
**Verified:** 2026-06-15T01:29:37Z
**Status:** passed
**Re-verification:** Yes — after gap closure（commits b76a9f1d6 / 39d351ad7）

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | `GitInstanceCredential` 模型（host 唯一、Fernet 加密 token、无明文字段）+ 迁移 0036（仅建表、依赖 0035） | ✓ VERIFIED | `models.py` L630-667（host unique=True、encrypted_token TextField、`__str__` 仅 provider:host）；`migrations/0036_git_instance_credential.py` 单一 CreateModel |
| 2 | 解析器 `resolve_git_token_sync`/`aresolve_git_token`：per-repo token 优先 → host 实例池 fallback → None；不泄漏 token | ✓ VERIFIED | `services/git_credentials.py` L59-93：①per-repo→②`GitInstanceCredential.filter(host=)`→③None；仅记 has_token/source 布尔 |
| 3 | 解析器接入 clone/index/repo_mirror/graph + plan 列举的 MR/PR 客户端 + coding dispatch + diff archive + base-branch 校验 | ✓ VERIFIED | grep `aresolve_git_token`/`resolve_git_token` 命中 indexer.py、repo_mirror.py、graph_builder.py、merge_request_service.py、mr_service.py、coding.py、coding_session_service.py、diff_archive.py、views.py L562 |
| 4 | per-repo token 存在时所有接线路径仍优先用 per-repo token（向后兼容不回退） | ✓ VERIFIED | 解析器①分支优先返回 per-repo token；`test_git_credentials.py` + `test_git_credential_clone_wiring.py` + `test_git_credential_platform_wiring.py` 守护，33 passed |
| 5 | 实例凭证 REST CRUD：token write-only/加密、IsSuperUser、响应/日志无明文；前端不回显 | ✓ VERIFIED | `views.py` L1124-1253（IsSuperUser、encrypt_value、空 token PATCH 不清空）；read 序列化器仅 has_token；`gitInstanceCredentials.ts` 读类型无 token 字段；`.vue` password 框不回填 |
| 6 | **D-02：同一 GitLab 实例多仓可复用同一凭证——所有 git 平台 API / dispatch 取 token 路径统一经解析器，消除散落 per-repo 取 token 逻辑** | ✓ VERIFIED（gap 已闭环） | grep `decrypt_value(.*encrypted_token` 非测试代码仅剩 `services/git_credentials.py`（解析器自身 L72/L86）；原 6 文件 8 处已改 `aresolve_git_token`：pr.py L168/L358、coding_graph.py L235/L597、code_review.py L603、summary_service.py L285、chat_tools.py L1101、views.py L856（TestConnection 既有仓库分支）、L562（base-branch）；None 分支降级文案保留不回退；`test_git_credential_gap_wiring.py` 6 passed |
| 7 | REPO-02 `search_rag_chunks` 多仓/全仓参数、每仓 fail-closed 复用、单仓向后兼容、仅已索引授权仓 | ✓ VERIFIED | `serializers.py` L16-45（repository_ids/all_repositories/max_repos→target_repository_ids）；`views.py` L456-594（一次性 search_rag chokepoint、item.repository_id 标注、单仓标量回退）；chokepoint `rag_search.py` L85 逐仓 build_matcher_for_repo；5 守护测试全绿（回归未破） |

**Score:** 7/7 truths verified

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | 前端 /admin/git-credentials CRUD 浏览器交互观感 | Deferred UAT (autonomous) | 页面/API client/vitest 守护已落地通过；按指示纯浏览器检查作非阻塞 UAT |

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `repositories/models.py::GitInstanceCredential` | host 唯一 + 加密 token 模型 | ✓ VERIFIED | L630-667 |
| `migrations/0036_git_instance_credential.py` | 仅建表迁移 | ✓ VERIFIED | 单一 CreateModel，依赖 0035 |
| `services/git_credentials.py` | 单一解析器 | ✓ VERIFIED | per-repo→实例池→None |
| `repositories/{serializers,views,urls}.py` | 实例凭证 REST CRUD | ✓ VERIFIED | IsSuperUser、write-only token、路由先于 router include |
| `web/src/api/gitInstanceCredentials.ts` + `pages/admin/git-credentials/index.vue` | 前端 client + 管理页 | ✓ VERIFIED | 读类型无 token；password 框不回显 |
| `mcp_tools/{serializers,views}.py` | search_rag_chunks 多仓 | ✓ VERIFIED | 多仓参数 + 合并检索 + 来源标注 |

### Key Link Verification

| From | To | Via | Status |
| --- | --- | --- | --- |
| indexer/graph/repo_mirror | git_credentials 解析器 | clone 取 token | ✓ WIRED |
| merge_request_service/mr_service/coding.py | aresolve_git_token | MR/PR client + dispatch | ✓ WIRED |
| diff_archive / views.py(base-branch) | 解析器 | 取 token | ✓ WIRED |
| **pr.py / coding_graph.py / code_review.py / summary_service.py / chat_tools.py / views.py(TestConn)** | aresolve_git_token | 取 token | ✓ WIRED（gap 闭环，内联 decrypt 已移除） |
| mcp_tools/views.py | HybridSearchService.search(repository_ids=) → search_rag chokepoint | 多仓 fail-closed | ✓ WIRED |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| REPO-01 解析器 + clone/平台接线 + REST CRUD 守护 | `pytest test_git_credentials* test_git_instance_credentials.py` | 28 passed | ✓ PASS |
| REPO-02 多仓 RAG 守护 | `pytest test_search_rag_multi_repo.py` | 5 passed | ✓ PASS |
| REPO-01 gap 闭环接线守护（re-verify） | `pytest test_git_credential_gap_wiring.py + 5 套` | 39 passed | ✓ PASS |

### Anti-Patterns Found

无（re-verify）。原 6 文件 8 处内联 git-token decrypt 已全部移除并改经解析器；grep `decrypt_value(.*encrypted_token` 非测试代码仅剩解析器自身 `services/git_credentials.py` L72/L86。

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| REPO-01 | 26-01..04 + gap 闭环 | GitLab 凭证统一/集中管理，多仓复用 | ✓ SATISFIED | 模型/解析器/REST/前端齐备；全部 git-platform / dispatch / clone / 检索取 token 路径统一经 `aresolve_git_token`，实例池-only 仓库可在所有路径复用同一凭证；grep 确认无解析器旁路残留 |
| REPO-02 | 26-05 | MCP RAG 多仓/全仓参数 | ✓ SATISFIED | search_rag_chunks 多仓参数 + 跨仓 fail-closed + 单仓兼容，5 守护测试全绿 |

### Gap Closure（Re-verification）

初次验证的唯一阻断点——6 个 git 平台 API / 容器 dispatch 文件中 8 处内联 `decrypt_value(credential.encrypted_token)` 绕过统一解析器——已在 commits `b76a9f1d6` / `39d351ad7` 闭环：

- `workflows/nodes/git/pr.py` L168 / L358、`orchestration/coding_graph.py` L235 / L597、`workflows/nodes/ai/code_review.py` L603、`repositories/summary_service.py` L285、`agents/tools/chat_tools.py` L1101、`repositories/views.py` L856（TestConnection 既有仓库分支）全部改经 `await aresolve_git_token(repo)`；各 None 分支保留既有缺凭证报错/降级文案（行为不回退），dispatch 路径仍仅 token 非空才注入。
- grep `decrypt_value(.*encrypted_token`：非测试代码仅剩解析器自身 `services/git_credentials.py`（L72/L86）；其余命中均为测试断言/文档。
- `test_git_credential_gap_wiring.py` 6 passed；连同既有 5 套守护测试合计 39 passed，REPO-02 多仓守护与回归未破。

成功标准 1「同一 GitLab 实例多仓可复用同一凭证」与标准 2「MCP RAG 多仓/全仓参数」均完全达成。仅余前端浏览器交互观感按指示作非阻塞 UAT（已有 vitest 守护通过）。

**最终状态：passed。**

---

_Initial verified: 2026-06-15T01:16:44Z（gaps_found）_
_Re-verified: 2026-06-15T01:29:37Z（passed，gap 闭环）_
_Verifier: Claude (gsd-verifier)_
