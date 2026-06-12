---
slug: fix-clarification-resume-context
status: complete
completed: 2026-06-12
commit: e6374837
---

# Summary: 修复 clarification 答复后 resume 后台任务崩溃导致会话永久卡死

## 根因

`ClarificationAnswerView` 用 `asyncio.create_task(_resume_graph())` 启动后台 resume，
默认复制了当前 HTTP 请求的 contextvars（含 asgiref `CurrentThreadExecutor`）。
请求结束后该 executor 退出，后台任务里 `build_sdk_config` 的第一个 async ORM 查询
（`sync_to_async` 内部）向已关闭的 executor 提交工作，抛
`RuntimeError: CurrentThreadExecutor already quit or is broken`。

该异常逃过 `resume_clarification_run` 中仅针对 `ValueError` 的兜底，外层只记日志，
`OrchestrationRun` 永久停在 `WAITING / waiting_clarification` —— 前端卡片显示
「已回复」但会话一直「进行中 / 等待你在上方卡片中确认…」。

## 修改

| 文件 | 改动 |
|------|------|
| `server/chat/views.py` | `create_task(..., context=contextvars.Context())` 以干净上下文启动后台任务 |
| `server/chat/conversation_service.py` | `build_sdk_config` 兜底从 `except ValueError` 放宽为 `except Exception`，失败必标 ERROR + 落兜底消息 |
| `server/tests/test_clarification_resume.py` | 新增回归测试：非 ValueError 配置异常也必须终结等待态 |

## 验证

- `uv run pytest tests/test_clarification_resume.py tests/test_clarification_answer_endpoint.py` → 13 passed
- `ruff check` 通过（format 偏差为改动前已存在，未触碰）

## 后续

- 在新 HEAD 打 `v0.3.0` tag（v0.3.0 里程碑 2026-06-12 已 shipped 但从未打 tag）
