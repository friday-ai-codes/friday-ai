# Phase 16 Verification — Multi-Entry Exposure & Frontend Timeline

**Verified:** 2026-06-12  
**Status:** PASSED

## Requirements

| ID | Criterion | Status | Evidence |
|----|-----------|--------|----------|
| EXPO-01 | MCP PAT 三工具 + 审计 + 越权空结果 | PASS | `search_delivery_knowledge` / `get_entity_timeline` / `get_related_entities` in `mcp_tools/views.py`; `test_delivery_knowledge_tools.py` |
| EXPO-02 | Workflow 节点 + ai_plan_generation 飞轮 | PASS | `delivery_knowledge_search.py`, `plan_generation.py` hook; `test_delivery_knowledge_search_node.py` |
| EXPO-03 | Chat agent 三工具 | PASS | `delivery_knowledge_tools.py`; `test_delivery_knowledge_tools.py` |
| EXPO-04 | npm friday-knowledge skill | PASS | `skills/skills/friday-knowledge/` (submodule commit 90e98bf) |
| ENH-03 | 只读实体详情页 | PASS | `web/src/pages/knowledge/entities/[id].vue` + component suite |
| ENH-04 | as_of 四入口透传 | PASS | `exposure.parse_as_of`, MCP/chat/workflow/REST query param |

## Test Results

### Wave 1 (16-01)
```
40 passed (includes exposure, timeline, MCP schema, MCP PAT)
```

### Wave 2 (16-02, 16-03, 16-04)
```
tests/agents/tools/test_delivery_knowledge_tools.py — 9 passed
tests/workflows/test_delivery_knowledge_search_node.py — 6 passed
validate-node-definitions.ts — PASS
skills/friday-knowledge — docs verified via rg
```

### Wave 3 (16-05)
```
tests/knowledge/test_knowledge_api.py — 4 passed
vitest knowledge components + entity-detail — 3 passed
```

## Commits

| Plan | Commit | Message |
|------|--------|---------|
| 16-01 | d79daba3 | feat(16-01): MCP delivery knowledge tools + exposure layer |
| 16-02 | 88f79f74 | feat(16-02): chat agent delivery knowledge tools |
| 16-03 | a767cda5 | feat(16-03): workflow delivery knowledge node + plan hook |
| 16-04 | 90e98bf (skills submodule) | docs(16-04): add friday-knowledge skill |
| 16-05 | 28a0d859 | feat(16-05): JWT entity detail REST + read-only UI |

## Self-Check

- [x] `server/knowledge/exposure.py` exists
- [x] TOOL_SCHEMA_SNAPSHOT has 22 tools
- [x] `/knowledge/entities/:id` route
- [x] Cross-user REST 404 (`test_entity_other_user_404`)

## Blockers

None.

## Notes

- `skills/` is a git submodule; friday-knowledge committed inside `skills` repo at `90e98bf`. Parent repo may need `git submodule update` to pin pointer.
- Wave 2 backend+frontend tests run per plan after waves 1–3 completion.
