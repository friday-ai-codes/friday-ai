---
phase: 17
slug: varref
date: 2026-06-12
---

# Phase 17: 变量引用链路修复 — Validation Strategy (Nyquist)

来源：17-RESEARCH.md「Validation Architecture」+ ROADMAP Phase 17 四条成功标准。

## Test Framework

| Property | Value |
|----------|-------|
| 后端 | pytest>=9.0.2 + pytest-django（`server/pyproject.toml` [tool.pytest]） |
| 前端 | vitest ^4（`cd web && pnpm vitest run`） |
| Quick run | `cd server && uv run pytest tests/workflows/test_template_resolver.py -x` |
| Full suite | `cd server && uv run pytest` ；`cd web && pnpm vitest run` |

## 需求 → 验证方法映射

| Req ID | 行为（成功标准） | 验证类型 | 自动化命令 | 测试文件 | 归属计划 |
|--------|------------------|----------|------------|----------|----------|
| VAR-01 | bulk-update 落库客户端 short_id；缺失/冲突/非法重生成且同事务重写全 config；不变式"保存成功⇒引用可解析" | integration（django_db） | `cd server && uv run pytest tests/workflows/test_bulk_update_short_id.py -q` | `test_bulk_update_short_id.py`（新建，17-02） | 17-02（服务端）+ 17-03（payload 上送 short_id） |
| VAR-02 | 节点不存在/字段不存在/未知前缀 → TemplateResolutionError 显式失败；scheduler 落中文+结构化 error_message；非 nodes 前缀字段缺失维持现状（定界，OQ#1） | unit（零 DB）+ integration | `cd server && uv run pytest tests/workflows/test_template_resolver.py tests/workflows/test_error_handling.py -q` | `test_template_resolver.py`（新建）+ `test_error_handling.py`（扩展） | 17-01 |
| VAR-03 | 三入口（picker/端口复制/SmartInput）统一生成 `{{nodes.<short_id>.<path>}}`；非节点前缀生成同样收口统一构造函数；UUID 与 slice(0,8) 兜底绝迹 | unit（vitest）+ grep 门禁 | `cd web && pnpm vitest run src/utils/__tests__/variableRef.test.ts` + `rg -n "id\.slice\(0, 8\)" web/src/` 无结果 | `variableRef.test.ts`（新建，17-03） | 17-03 |
| VAR-04 | 嵌套 dict/list 路径、UUID vs short_id 双键、单变量保类型、多变量渲染、大小写近似提示、JSONPath/非 nodes 前缀现状锁定 | unit（纯函数零 DB） | `cd server && uv run pytest tests/workflows/test_template_resolver.py -q` | `test_template_resolver.py`（新建，17-01） | 17-01 |

## 人工检查点（/gsd-verify-work 阶段验收）

自动化无法覆盖的端到端体验，留待阶段验收人工执行：

1. **所选即所得全链路**：编辑器中通过变量选择器选择上游输出引用 → 保存 → 执行 → 节点取到值（成功标准 1+3 的 UI 链路）
2. **错误体验**：故意写坏引用（不存在节点/字段）→ 执行 → 执行详情可见中文错误指明引用与原因（成功标准 2 的展示侧；结构化展示组件属 Phase 21，本阶段仅验证 error_message 内容）
3. **端口复制/SmartInput 入口抽查**：复制端口引用、SmartInput 选择变量，确认产物均为 short_id 形式

## 抽样频率（Sampling Rate）

- **每任务提交**：`cd server && uv run pytest tests/workflows/test_template_resolver.py -x`（<30s 纯函数）或对应前端 `pnpm vitest run src/utils/__tests__/variableRef.test.ts`
- **每 wave 合并**：`cd server && uv run pytest tests/workflows/ -x` + `cd web && pnpm vitest run`
- **阶段门禁（17-04 计划 Task 2 承载）**：后端全量 `uv run pytest` + 前端 `pnpm vitest run` 全绿后进入 `/gsd-verify-work`

## Wave 0 缺口（计划内补齐）

- [ ] `server/tests/workflows/test_template_resolver.py` — 17-01 Task 1 创建（TDD：先 RED 后 GREEN）
- [ ] `server/tests/workflows/test_bulk_update_short_id.py` — 17-02 Task 2 创建
- [ ] `web/src/utils/__tests__/variableRef.test.ts` — 17-03 Task 1 创建（TDD）
- [ ] 框架安装：无需（pytest/vitest 均就绪，RESEARCH Environment Availability 已验证）
