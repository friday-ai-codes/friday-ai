---
phase: 26-multirepo-creds-mcp
reviewed: 2026-06-15T09:45:00Z
depth: deep
files_reviewed: 14
files_reviewed_list:
  - server/repositories/models.py
  - server/repositories/migrations/0036_git_instance_credential.py
  - server/repositories/serializers.py
  - server/repositories/urls.py
  - server/repositories/views.py
  - server/services/git_credentials.py
  - server/services/repo_mirror.py
  - server/services/indexer.py
  - server/services/graph_builder.py
  - server/services/retrieval/rag_search.py
  - server/mcp_tools/views.py
  - server/mcp_tools/serializers.py
  - web/src/api/gitInstanceCredentials.ts
  - web/src/pages/admin/git-credentials/index.vue
findings:
  blocker: 0
  high: 1
  medium: 1
  low: 2
  total: 4
status: clean
resolution:
  resolved_at: 2026-06-15T09:45:00Z
  HI-01: fixed (291fd896f) — scp-style SSH 正则仅在无 :// 协议头时生效，带协议头的 URL 一律走 urlparse，保留 host:port 与实例凭证存储口径一致；新增 userinfo+端口 / 同域不同端口 守护测试。
  LO-02: fixed (9c627303e) — access_token 改 allow_blank=True，PATCH 空串=保留既有 token，create 仍由视图 required-on-create 守护拒绝空串。
  ME-01: accepted — all-powerful-token 模型为既定产品决策（AccessToken 有效即全权限，不做 scope/project 分权），all_repositories 返回整实例为有意行为，保持现状；后续如需多租户分权再单立 phase。
  LO-01: deferred — provider 一致性校验为低收益加固（一 host 一平台，blast radius 近零），本轮不动。
---

# Phase 26: Code Review Report — 多仓凭证统一 + MCP 多仓参数 (REPO-01/REPO-02)

**Reviewed:** 2026-06-15T09:45:00Z
**Depth:** deep (cross-file: resolver → wired token-read sites → retrieval exclusion → auth model)
**Files Reviewed:** 14 source files (commits `160f32905`..`44fd4cdca`)
**Status:** clean — HI-01 修复（`291fd896f`）、LO-02 修复（`9c627303e`）；ME-01 作为既定产品决策接受、LO-01 低收益加固本轮延后（见 frontmatter `resolution`）。

## Summary

The credential-security core is solid. Confirmed strengths:

- **No plaintext token leak.** `GitInstanceCredentialSerializer` is read-only with `read_only_fields = fields` and exposes only a `has_token` boolean; `access_token` is `write_only` on the write serializer. No view puts a token in any `Response`. Logs record only `host` / `has_token` / `token_changed` booleans (`views.py:1187-1193,1261-1266,1276`). `__str__` excludes the token (`models.py:665-667`). Frontend read type has no token field; the form input is `password`-type, never back-filled, and cleared after submit (`git-credentials/index.vue:78,99,140,158`).
- **Encryption correctness.** Tokens stored via `encrypt_value`, decrypted only through `decrypt_value` (the single decrypt exit in the resolver). Migration `0036` is `CreateModel`-only, no backfill (compatible with existing deployments).
- **`IsSuperUser` enforcement.** Both `GitInstanceCredentialsView` and `GitInstanceCredentialDetailView` set `permission_classes = [IsSuperUser]` (views.py:1138,1209); `IsSuperUser.has_permission` correctly requires authenticated + `is_superuser` (`permissions/api_permissions.py:21-31`). URL literals are registered before the router so they are not captured as a repository UUID.
- **No silent empty-token injection.** `build_authenticated_git_url` returns the URL unchanged when `token` is falsy (`views.py:85-86`) — no `oauth2:@host` malformed injection. Every wired token-read site (indexer, repo_mirror, graph_builder, merge_request_service, mr_service, coding.py, pr.py, coding_graph.py, code_review.py, diff_archive.py, coding_session_service.py, chat_tools.py, summary_service.py, views.py base-branch check) guards `if not token` and either raises a clear "缺凭证" error or skips injection. Resolver returns `None` (not a forged empty token) when no credential is found.
- **Multi-repo search does NOT bypass per-repo exclusion.** `SearchRagChunksView` delegates to `HybridSearchService.search(repository_ids=...)`, whose L3 items come from `search_rag` (`services/retrieval/rag_search.py:81-113`), which builds a `build_matcher_for_repo` matcher **per repo**, applies `is_excluded` per item fail-closed (matcher-build failure or `is_excluded` exception → entire repo / item dropped), and tags each surviving item with `repository_id`. Neighbor edges are filtered via `_filter_excluded_neighbors`. `grep_repository` filters each repo through `_filter_grep_result` (fail-closed) and recomputes counts. Per-repo failures are isolated (best-effort merge), single-repo retains legacy 404/400.

One genuine defect in host extraction (HIGH) and three lower-severity items follow.

## High

### HI-01: `_extract_git_host` SSH regex mis-parses HTTPS URLs with embedded userinfo + port → inconsistent host / credential misrouting

**File:** `server/services/git_credentials.py:33,36-56`

The SSH branch is tried **first** and unconditionally:

```python
_SSH_RE = re.compile(r"^[^@]+@([^:/]+):")
...
ssh_match = _SSH_RE.match(git_url.strip())
if ssh_match:
    return ssh_match.group(1).lower()
```

`[^@]+@` also matches the userinfo segment of an HTTPS URL, so any `https://<user>@host:port/...` is wrongly treated as scp-style SSH and the **port is dropped**. Verified empirically:

| git_url | extracted host |
|---|---|
| `https://gitlab.example.com:8443/ns/repo.git` | `gitlab.example.com:8443` ✅ |
| `https://oauth2:tok@gitlab.example.com:8443/ns/repo.git` | `gitlab.example.com` ❌ (port dropped) |
| `https://gitlab-ci-token@git.corp:8443/ns/repo.git` | `git.corp` ❌ (port dropped) |

The model stores host "含端口若有" and the no-userinfo URL extracts *with* port, so the same instance is keyed two different ways depending on whether the stored `git_url` carries credentials. Impact:

1. **Reliability (common):** A repo whose `git_url` contains an embedded username and a custom port (typical for self-hosted GitLab, e.g. `https://oauth2@gitlab.internal:8443/...`) will never match an instance credential registered as `gitlab.internal:8443` → instance-pool fallback silently misses → repo fails with "缺凭证" even though a valid instance credential exists.
2. **Wrong-token-to-wrong-host (threat T-26-03, narrow):** If two instance credentials exist on the same domain differing only by port (`gitlab.internal` and `gitlab.internal:8443`), a userinfo-bearing URL for the `:8443` instance resolves to the portless `gitlab.internal` credential → the wrong instance's token is sent. (Blast radius is limited to same-domain/different-port; the domain itself is always parsed correctly, so a token cannot leak to an unrelated host.)

This is also inconsistent with the serializer's own SSH handling (`serializers.py:22-23`), where `_SSH_URL_RE` explicitly drops the ssh port via `(?::\d+)?` and `_SSH_SCP_RE` anchors on `^git@`.

**Fix:** Only treat the URL as scp-style SSH when it has no `://` scheme; route everything with a scheme through `urlparse`, which already strips userinfo and preserves `host:port` consistently:

```python
def _extract_git_host(git_url: str | None) -> str | None:
    if not git_url:
        return None
    url = git_url.strip()
    # scp-style SSH (git@host:path) has no scheme; ssh:// is handled by urlparse below
    if "://" not in url:
        ssh_match = _SSH_RE.match(url)
        if ssh_match:
            return ssh_match.group(1).lower()
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        return parsed.netloc.rsplit("@", 1)[-1].lower()
    return None
```

(Note: stored repo URLs are normalized to HTTPS at creation via `validate_https_git_url`, so the HTTPS-with-userinfo path is the realistic one. Add a guard test for `https://user@host:port/...`.)

## Medium

### ME-01: `all_repositories` enables one-call enumeration/retrieval of every indexed repo's content — diverges from the phase's stated "只检索调用方有权访问的仓库"

**File:** `server/mcp_tools/views.py:472-509` (SearchRagChunks) and `:662-679` (GrepRepository); `server/mcp_tools/serializers.py:27,93`

The access scope is "存在 + INDEXED + 非删除" only — there is no per-caller / per-project authorization filter:

```python
target_ids = [
    str(rid)
    async for rid in Repository.objects.filter(
        is_deleted=False, index_status=IndexStatus.INDEXED
    ).order_by("name").values_list("id", flat=True)[:max_repos]
]
```

The phase context D-03 promises "权限/范围受控：只检索调用方有权访问的仓库（复用既有权限判定）". In practice the "既有权限判定" for MCP is **none at the repo level**: `AccessToken` is documented as a single all-powerful token ("有效即全权限，不做 scope / project / allowlist 分权", `access_tokens/models.py:3-4`), and `_get_indexed_repo` never checks project membership. So this is *consistent with the existing single-repo MCP behavior* and is **not a new privilege-boundary bypass**.

However, `all_repositories` materially **amplifies exposure**: previously a caller had to know each `repository_id`; now a single low-privilege token holder can enumerate and pull chunk content (and via `grep_repository`, file content) from every indexed repository across all spaces/teams in the instance. For multi-tenant deployments this is a real data-exposure change that should be an explicit product decision, not an implicit side effect.

**Fix (choose one):**
- If the all-powerful-token model is intended, document explicitly that `all_repositories` returns the whole instance and update the D-03 wording so the spec and code agree; or
- Scope the `all_repositories` / `repository_ids` enumeration to repositories reachable from the token owner's project memberships (reuse `PermissionService`/space linkage), matching the literal D-03 promise.

## Low

### LO-01: Resolver matches instance credential by host only, ignoring `provider`

**File:** `server/services/git_credentials.py:74-86`

Step ② matches `GitInstanceCredential.objects.filter(host=host)` with no `provider` constraint, while `repo.git_platform` is never consulted. Because `host` is globally unique, a single host can only hold one credential regardless of platform, so a repo whose `git_platform` differs from the stored `instance.provider` would still receive that token. Blast radius is effectively nil in practice (one host = one platform), but the resolver should still assert provider agreement (or at least log a mismatch) to avoid sending a GitLab token to a Gitea/GitHub host that happens to share a domain.

**Fix:** Optionally filter `GitInstanceCredential.objects.filter(host=host, provider=repo.git_platform)` or log a warning when `instance.provider != repo.git_platform`.

### LO-02: PATCH with empty-string `access_token` returns 400 instead of "keep existing"

**File:** `server/repositories/serializers.py:380-382`; `server/repositories/views.py:1247-1251`

`access_token` is declared `allow_blank=False`. The documented contract is "access_token 留空表示不修改既有 token", and the view only overwrites when truthy (`if access_token:`). But because `allow_blank=False`, a client that sends `access_token: ""` (empty string, as opposed to omitting the field) is rejected with a validation error before reaching the "keep existing" logic. Only field *omission* works as documented. This is a contract/UX mismatch, not a security issue.

**Fix:** Either set `allow_blank=True` and rely on the existing `if access_token:` truthiness guard to skip overwrite on blank, or document that the field must be omitted (not sent empty) to preserve the existing token.

---

_Reviewed: 2026-06-15T09:45:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
