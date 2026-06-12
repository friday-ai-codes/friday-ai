---
slug: fix-clarification-resume-context
created: 2026-06-12
type: quick
---

# Quick Task: 修复 clarification 答复后 resume 后台任务崩溃导致会话永久卡死

## 问题

用户答复 ask_clarification 卡片后，`ClarificationAnswerView` 返回 200、trace 落库成功（前端显示「已回复」），但后台 `_resume_graph` 任务在 `build_sdk_config` 的第一个异步 ORM 查询处抛出：

```
RuntimeError: CurrentThreadExecutor already quit or is broken
```

根因：`asyncio.create_task(_resume_graph())` 复制了当前 HTTP 请求的 contextvars，
其中包含 asgiref 的 `CurrentThreadExecutor`。请求结束后该 executor 退出，后台任务里
`sync_to_async`（Django async ORM 内部）仍向已关闭的 executor 提交工作 → RuntimeError。

次生问题：该异常逃过了 `resume_clarification_run` 中 `except ValueError` 的兜底，
外层只记日志不更新状态，`OrchestrationRun` 永久停在 `WAITING / waiting_clarification`，
前端一直显示「进行中 / 等待你在上方卡片中确认…」。

## 任务

1. `server/chat/views.py` `ClarificationAnswerView.post`：用
   `asyncio.create_task(coro, context=contextvars.Context())` 以干净上下文启动后台
   resume 任务，不继承请求级 executor。
2. `server/chat/conversation_service.py` `resume_clarification_run`：
   `build_sdk_config` 的异常捕获从 `except ValueError` 放宽为 `except Exception`，
   任何配置阶段失败都走 `_mark_error`（run → ERROR + 兜底错误消息），杜绝永久等待态。
3. 回归测试：`build_sdk_config` 抛非 ValueError 时 run 必须被标记为 ERROR。

## 验收

- `uv run pytest tests/test_clarification_answer_endpoint.py tests/test_clarification_resume.py` 通过
- 修复后在新 HEAD 打 `v0.3.0` tag（v0.3.0 里程碑已 shipped 但从未打过 tag）
