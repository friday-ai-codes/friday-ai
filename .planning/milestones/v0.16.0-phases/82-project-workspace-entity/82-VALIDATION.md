---
phase: 82
slug: project-workspace-entity
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-26
---

# Phase 82 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. Derived from `82-RESEARCH.md` §Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-django + pytest-asyncio + respx（httpx mock）+ pytest-socket（网络隔离）；前端 vitest + vue-tsc |
| **Config file** | `server/pyproject.toml`（`[tool.pytest.ini_options]`）；`web/vitest.config.ts` |
| **Quick run command** | `cd server && uv run pytest tests/initiatives/ -x` |
| **Full suite command** | `cd server && uv run pytest tests/initiatives/ tests/services/test_project_context_packer.py tests/test_chat_project_recall.py && uv run python manage.py makemigrations --check --dry-run` |
| **Estimated runtime** | ~60–120 seconds（后端）+ ~20s（前端 vitest/vue-tsc） |

---

## Sampling Rate

- **After every task commit:** Run `cd server && uv run pytest tests/initiatives/ -x`
- **After every plan wave:** Run Full suite command + `cd web && pnpm vitest run && pnpm vue-tsc --noEmit`
- **Before `$gsd-verify-work`:** Full suite must be green + INV-6 guards（含新建 `test_project_doc_inv6_guard.py`）+ `makemigrations --check` 干净
- **Max feedback latency:** ~120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 82-W0 | 00 | 0 | DOC-01~05 | — | 测试桩落地 | unit | `cd server && uv run pytest tests/initiatives/test_project_doc_service.py` | ❌ W0 | ⬜ pending |
| 82-models | 01 | 1 | DOC-01~05 | T-tamper | 3 新模型唯一约束 + 零业务方法 | unit/migration | `uv run python manage.py makemigrations --check --dry-run` | ❌ W0 | ⬜ pending |
| 82-svc | 02 | 1 | WS-04, DOC-* | T-bypass | 写入收口 service + 后台 provision + broken 路径 | unit/async(respx) | `uv run pytest tests/initiatives/test_project_doc_service.py -x` | ❌ W0 | ⬜ pending |
| 82-inv6 | 02 | 1 | INV-6 | T-tamper | 3 新模型无旁路写 | static grep | `uv run pytest tests/initiatives/test_project_doc_inv6_guard.py` | ❌ W0 | ⬜ pending |
| 82-feishu | 02 | 1 | WS-04 | T-leak | `create_folder` respx 形状 + 限流退避 | unit/async(respx) | `uv run pytest tests/services/ -k feishu_doc` | ❌ W0 | ⬜ pending |
| 82-perm | 03 | 2 | WS-02 | T-disclosure | public_org 非成员可召回；members_only 非成员零召回；非成员写被拒 | unit/async | `uv run pytest tests/services/test_project_context_packer.py tests/test_chat_project_recall.py -x` | ✅（扩充） | ⬜ pending |
| 82-rest | 03 | 2 | WS-03, DOC-02/06 | T-priv | ProjectDoc 列表/重建、StateApi CRUD、visibility/space 改归成员/admin 闸 | unit/async | `uv run pytest tests/initiatives/ -k "view or api or visibility"` | ❌ W0 | ⬜ pending |
| 82-fe | 04 | 2 | WS-01 | — | 侧边栏「项目」tab（首页↓空间↑）+ 所选空间 localStorage | unit(vitest) | `cd web && pnpm vitest run` | ✅（扩充） | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/initiatives/test_project_doc_service.py` — ProjectDocService 写入 + provision + broken 路径（WS-04/DOC）
- [ ] `tests/initiatives/test_project_doc_inv6_guard.py` — 镜像 `test_artifact_inv6_guard.py` 多模型版（覆盖 ProjectDoc/ProjectDocBlockMap/ProjectStateApi，处理前缀重叠）
- [ ] 扩充 `tests/services/test_project_context_packer.py` — public_org vs members_only 对称用例
- [ ] `create_folder` respx 形状 + 限流退避（扩充 `tests/services/test_feishu_doc_errors.py` 或新增）
- [ ] 扩充 `web/src/pages/projects/__tests__/projects-list.spec.ts` — 所选空间 localStorage + 侧边栏 tab

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 飞书真实建文件夹 + 5 文件落 token | WS-04 | 需真实飞书 app 凭证 + Drive/Docx scope + 真实 Space folder | 在已配飞书凭证的实例创建项目，确认飞书出现专属文件夹 + 5 文件，DB 落 token；断网/无凭证则置 broken |
| 飞书 `create_folder` 端点字段/返回结构 | WS-04 | 库内无实现，端点形态需 live 验证（A1 MEDIUM） | live 调 `POST /drive/v1/files/create_folder`，确认 body `{name, folder_token}`、返回 `data.token` |
| 看板描述追加「项目工作区」段可打开 | DOC-06 | 工作项 description field_key 需 live 验证（A2） | live 读 `get_work_item` 取 description field_key，追加段后回看板确认链接可打开 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
