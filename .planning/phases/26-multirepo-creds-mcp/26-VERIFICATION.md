---
phase: 26-multirepo-creds-mcp
verified: 2026-06-15T01:16:44Z
status: gaps_found
score: 6/7 must-haves verified
overrides_applied: 0
gaps:
  - truth: "同一 GitLab 实例多仓可复用同一凭证（D-02：所有 git 平台 API / 容器 dispatch 取 token 路径统一经解析器，消除散落的 per-repo 取 token 逻辑）"
    status: partial
    reason: >-
      解析器已接入 plan 显式列举的路径（clone/index、repo_mirror、graph、
      mcp_tools/merge_request_service、workflows/mr_service、coding.py dispatch+MR、
      coding_session_service、diff_archive、base-branch 校验），但仍有 ≥8 处内联
      `decrypt_value(credential.encrypted_token)` 直读 per-repo 凭证、绕过解析器，
      分布在 6 个 git 平台 API / 容器 dispatch 文件中。仅靠实例池（无 per-repo token）
      的仓库在这些路径会失败（"凭据未配置"/注入空 token），与 26-03 SUMMARY
      "消除了所有散落的内联 GitCredential → decrypt_value 取 token 逻辑" 的断言不符。
    artifacts:
      - path: "server/workflows/nodes/git/pr.py"
        issue: "L179 / L373 PR(MR) 创建 + cross-reference 更新仍内联 decrypt_value(credential.encrypted_token)，未经 aresolve_git_token（git-platform MR/PR 客户端路径）"
      - path: "server/orchestration/coding_graph.py"
        issue: "L240 冲突预检 compare_branches、L601 PR 创建仍内联 decrypt_value(cred.encrypted_token)，实例池仓库 PR 创建会 'Git 凭据未配置，无法创建 PR'"
      - path: "server/workflows/nodes/ai/code_review.py"
        issue: "L613 get_merge_request_diff 仍内联 decrypt_value(credential.encrypted_token)，实例池仓库返回 '仓库未配置访问凭证'"
      - path: "server/repositories/summary_service.py"
        issue: "L289 容器 dispatch git token 注入仍内联 decrypt_value(cred.encrypted_token)，实例池仓库注入空 token"
      - path: "server/agents/tools/chat_tools.py"
        issue: "L1104 explore 模式容器 dispatch git token 注入仍内联 decrypt_value(cred.encrypted_token)，实例池仓库注入空 token"
      - path: "server/repositories/views.py"
        issue: "L862 TestConnectionView 既有仓库（repository_id）分支仍内联 decrypt_value，实例池仓库 '测试连接' 报 '仓库未配置访问凭证'（仅用户当场输入 token 分支应免接，既有仓库分支应经解析器）"
    missing:
      - "将上述 6 个文件的 git-token 内联解密替换为 aresolve_git_token(repo) / resolve_git_token_sync(repo)，保留各自既有缺凭证报错/降级文案（行为不回退）"
      - "TestConnectionView 仅 'repository_id 既有仓库' 分支接解析器；'用户当场输入 token' 分支保持不变"
deferred:
  - truth: "管理员可在前端 /admin/git-credentials 页面完成实例凭证 CRUD（浏览器端交互观感）"
    addressed_in: "Deferred UAT (autonomous)"
    evidence: "前端页面 / API client / vitest 守护测试均已落地且通过；纯浏览器端交互观感按指示作非阻塞 UAT 处理"
human_verification:
  - test: "用浏览器打开 /admin/git-credentials，以管理员创建/编辑/删除一条实例凭证，确认 token 输入框为 password、不回显既有 token、列表仅显示 has_token 徽标"
    expected: "CRUD 正常，token 全程不回显明文，文案为中文"
    why_human: "纯前端浏览器交互观感，按指示作非阻塞 UAT（已有 vitest 守护测试通过）"
---

# Phase 26: 多仓凭证统一 + MCP 多仓参数 Verification Report

**Phase Goal:** GitLab 凭证统一池 + MCP RAG 多仓检索参数。
**Verified:** 2026-06-15T01:16:44Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | `GitInstanceCredential` 模型（host 唯一、Fernet 加密 token、无明文字段）+ 迁移 0036（仅建表、依赖 0035） | ✓ VERIFIED | `models.py` L630-667（host unique=True、encrypted_token TextField、`__str__` 仅 provider:host）；`migrations/0036_git_instance_credential.py` 单一 CreateModel |
| 2 | 解析器 `resolve_git_token_sync`/`aresolve_git_token`：per-repo token 优先 → host 实例池 fallback → None；不泄漏 token | ✓ VERIFIED | `services/git_credentials.py` L59-93：①per-repo→②`GitInstanceCredential.filter(host=)`→③None；仅记 has_token/source 布尔 |
| 3 | 解析器接入 clone/index/repo_mirror/graph + plan 列举的 MR/PR 客户端 + coding dispatch + diff archive + base-branch 校验 | ✓ VERIFIED | grep `aresolve_git_token`/`resolve_git_token` 命中 indexer.py、repo_mirror.py、graph_builder.py、merge_request_service.py、mr_service.py、coding.py、coding_session_service.py、diff_archive.py、views.py L562 |
| 4 | per-repo token 存在时所有接线路径仍优先用 per-repo token（向后兼容不回退） | ✓ VERIFIED | 解析器①分支优先返回 per-repo token；`test_git_credentials.py` + `test_git_credential_clone_wiring.py` + `test_git_credential_platform_wiring.py` 守护，33 passed |
| 5 | 实例凭证 REST CRUD：token write-only/加密、IsSuperUser、响应/日志无明文；前端不回显 | ✓ VERIFIED | `views.py` L1124-1253（IsSuperUser、encrypt_value、空 token PATCH 不清空）；read 序列化器仅 has_token；`gitInstanceCredentials.ts` 读类型无 token 字段；`.vue` password 框不回填 |
| 6 | **D-02：同一 GitLab 实例多仓可复用同一凭证——所有 git 平台 API / dispatch 取 token 路径统一经解析器，消除散落 per-repo 取 token 逻辑** | ✗ FAILED | 6 文件 ≥8 处内联 `decrypt_value(credential.encrypted_token)` 绕过解析器（见 Gaps）；实例池-only 仓库在 PR 创建/冲突预检/code review/2 处 dispatch/测试连接路径失败 |
| 7 | REPO-02 `search_rag_chunks` 多仓/全仓参数、每仓 fail-closed 复用、单仓向后兼容、仅已索引授权仓 | ✓ VERIFIED | `serializers.py` L16-45（repository_ids/all_repositories/max_repos→target_repository_ids）；`views.py` L456-594（一次性 search_rag chokepoint、item.repository_id 标注、单仓标量回退）；chokepoint `rag_search.py` L85 逐仓 build_matcher_for_repo |

**Score:** 6/7 truths verified

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
| **pr.py / coding_graph.py / code_review.py / summary_service.py / chat_tools.py / views.py(TestConn)** | 解析器 | 取 token | ✗ NOT_WIRED（内联 decrypt 绕过） |
| mcp_tools/views.py | HybridSearchService.search(repository_ids=) → search_rag chokepoint | 多仓 fail-closed | ✓ WIRED |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| REPO-01 解析器 + clone/平台接线 + REST CRUD 守护 | `pytest test_git_credentials* test_git_instance_credentials.py` | 28 passed | ✓ PASS |
| REPO-02 多仓 RAG 守护 | `pytest test_search_rag_multi_repo.py` | 5 passed（共 33 passed） | ✓ PASS |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| workflows/nodes/git/pr.py | 179, 373 | 内联 git-token decrypt 绕过解析器 | ⚠️ Warning | 实例池-only 仓 PR 创建/cross-ref 失败 |
| orchestration/coding_graph.py | 240, 601 | 同上 | ⚠️ Warning | 冲突预检跳过 + PR 创建失败 |
| workflows/nodes/ai/code_review.py | 613 | 同上 | ⚠️ Warning | MR diff 拉取失败 |
| repositories/summary_service.py | 289 | dispatch token 内联 | ⚠️ Warning | 注入空 git token |
| agents/tools/chat_tools.py | 1104 | dispatch token 内联 | ⚠️ Warning | 注入空 git token |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| REPO-01 | 26-01..04 | GitLab 凭证统一/集中管理，多仓复用 | ⚠️ PARTIAL | 模型/解析器/REST/前端齐备且已接入主索引/检索路径；但多处 git-platform/dispatch 路径仍绕过解析器，实例池-only 复用不完整 |
| REPO-02 | 26-05 | MCP RAG 多仓/全仓参数 | ✓ SATISFIED | search_rag_chunks 多仓参数 + 跨仓 fail-closed + 单仓兼容，5 守护测试全绿 |

### Gaps Summary

REPO-02 完全达成。REPO-01 的数据/解析/REST/前端地基与 plan 显式列举的接线点均已验证落地且测试全绿，per-repo 优先与 token 不泄漏契约成立。

唯一阻断点：CONTEXT D-02 与 26-03 SUMMARY 均声称"消除所有散落的 per-repo 取 token 逻辑 / 统一经解析器"，但实际仍有 ≥8 处内联 `decrypt_value(credential.encrypted_token)` 分布于 6 个 git 平台 API / 容器 dispatch 文件（`pr.py`、`coding_graph.py`、`code_review.py`、`summary_service.py`、`chat_tools.py`、`views.py` TestConnection 既有仓库分支），绕过统一解析器。其后果是：一个仅靠实例凭证池（无 per-repo token）的仓库——恰是成功标准 1 承诺的场景——在"chat 编码 PR 创建 / 冲突预检 / 工作流 git PR 节点 / code review diff 拉取 / 两处容器派发 git token 注入 / 既有仓库测试连接"等路径仍会因缺 per-repo token 而失败或注入空 token。

因此成功标准 1「同一 GitLab 实例多仓可复用同一凭证」仅部分达成。修复为机械替换（同 26-02/26-03 范式），不引入新设计。

---

_Verified: 2026-06-15T01:16:44Z_
_Verifier: Claude (gsd-verifier)_
