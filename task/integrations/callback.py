"""Callback client for reporting task status to main API.

支持两种模式：
1. 回调模式 - 设置 callback_url 后向 server API 报告状态
2. 独立模式 - 不设置 callback_url 时仅记录日志

[新增] 文件模式 - 如果环境变量 FRIDAY_TASK_OUTPUT_DIR 存在，将状态写入文件
这作为网络回调不可靠时的兜底方案。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import TYPE_CHECKING, Any

import httpx
import structlog

if TYPE_CHECKING:
    from core.config import TaskConfig

logger = structlog.get_logger()


class CallbackClient:
    """Client for sending status updates back to the main Friday API.

    当 callback_url 为空时，自动切换到独立模式，仅记录日志。
    当 FRIDAY_TASK_OUTPUT_DIR 存在时，同时写入文件。
    """

    def __init__(self, config: "TaskConfig"):
        """Initialize callback client with config."""
        self.config = config
        self.enabled = bool(config.callback_url)
        self.base_url = config.callback_url if self.enabled else None
        self.headers = {
            "Content-Type": "application/json",
        }
        if config.callback_token:
            self.headers["Authorization"] = f"Bearer {config.callback_token}"

        # 检查是否开启了文件输出模式（用于网络隔离环境）
        self.output_dir = os.environ.get("FRIDAY_TASK_OUTPUT_DIR")
        if self.output_dir and not os.path.exists(self.output_dir):
            try:
                os.makedirs(self.output_dir, exist_ok=True)
            except Exception as e:
                logger.warning("Failed to create output directory", path=self.output_dir, error=str(e))
                self.output_dir = None

        if not self.enabled:
            logger.info("Callback disabled, running in standalone mode", task_id=config.task_id)
        if self.output_dir:
            logger.info("File output enabled", path=self.output_dir)

    def _callback_endpoint(self) -> str:
        """返回实际 callback endpoint，兼容 Runner 本地中转与直连 Server。

        Go Runner 传入的是本地中转端点 ``.../callback``；直连 Server 时传入的是
        服务根地址，需要追加 ``/api/containers/callback/``。
        """
        assert self.base_url is not None
        base = self.base_url.rstrip("/")
        if base.endswith("/callback"):
            return base
        return f"{base}/api/containers/callback/"

    async def report_status(
        self,
        status: str,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> bool:
        """Report task status to Friday Server's unified container callback endpoint.

        历史路径 ``{base_url}/tasks/{task_id}/status`` 不存在于任何后端（既不在
        Runner ``POST /callback`` 也不在 Friday Server）。每次任务（含 deep_analysis）
        启动时调 ``report_started`` 都会得到 404，更糟的是 ``report_error`` 调用本
        函数后 Friday 永远收不到失败通知，导致 SubAgentSession 状态卡在 RUNNING。

        统一改走 Friday Server ``/api/containers/callback/``（与 ``report_completed``
        / ``report_failed`` 同 endpoint）：
          - 终态 ``status == 'error'`` 直接代理 :meth:`report_failed`（统一失败协议）
          - 其它所有 status（started/git_ready/push_complete/execution_complete/
            plan_ready/no_changes/progress 等）映射为 ``type=progress``，原 status
            编码进 ``payload.phase``，consumer 端 ``parse_progress_payload`` 会把
            它落到 ``session.last_output.progress.phase``，前端可读。
        """
        log = logger.bind(task_id=self.config.task_id, status=status)

        # 1. 错误终态走 failed 协议，与 report_failed 一致
        if status == "error":
            return await self.report_failed(message or "Unknown error")

        # 2. 文件兜底（关键状态写 result.json，供网络隔离场景使用）
        file_payload = {
            "task_id": self.config.task_id,
            "status": status,
            "message": message,
            "details": details or {},
            "timestamp": datetime.utcnow().isoformat(),
        }
        if self.output_dir:
            try:
                if status in ("plan_ready", "execution_complete", "push_complete"):
                    result_path = os.path.join(self.output_dir, "result.json")
                    with open(result_path, "w") as f:
                        json.dump(file_payload, f, indent=2, ensure_ascii=False)
                    log.info("Status written to file", path=result_path)
            except Exception as e:
                log.error("Failed to write status to file", error=str(e))

        # 3. 未启用 HTTP 回调：standalone 模式
        if not self.enabled:
            log.info("Status update (standalone mode)", message=message, details=details)
            return True

        # 4. 走 Friday Server progress callback 协议
        details_dict = details or {}
        progress_payload: dict[str, Any] = {
            "phase": status,
            "progress": float(details_dict.get("progress", 0.0)),
            "message": message or "",
            "details": details_dict,
        }
        # coding_progress 是 progress serializer 的一等字段，单独透传
        coding_progress = details_dict.get("coding_progress")
        if isinstance(coding_progress, dict):
            progress_payload["coding_progress"] = coding_progress

        body = {
            "type": "progress",
            "session_id": self.config.task_id,
            "token": self.config.callback_token,
            "payload": progress_payload,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self._callback_endpoint(),
                    json=body,
                    headers=self.headers,
                    timeout=30.0,
                )
                response.raise_for_status()
            log.info("Status reported successfully")
            return True
        except httpx.HTTPError as e:
            if self.output_dir:
                log.warning("Failed to report status via HTTP (backed up to file)", error=str(e))
            else:
                log.error("Failed to report status", error=str(e))
            return False

    async def report_execution_complete(
        self,
        branch_name: str,
        commit_sha: str,
        diff_summary: str,
    ) -> bool:
        """Report that execution is complete."""
        return await self.report_status(
            status="execution_complete",
            message="Code changes are ready for review",
            details={
                "branch_name": branch_name,
                "commit_sha": commit_sha,
                "diff_summary": diff_summary,
            },
        )

    async def report_error(self, error: str, phase: str) -> bool:
        """Report an error during execution."""
        return await self.report_status(
            status="error",
            message=f"Error during {phase}: {error}",
            details={"error": error, "phase": phase},
        )

    async def report_started(self) -> bool:
        """Report that task execution has started."""
        return await self.report_status(
            status="started",
            message=f"Task execution started in {self.config.task_mode} mode",
            details={
                "mode": self.config.task_mode,
                "repo_url": self.config.git_repo_url,
                "branch": self.config.git_branch,
            },
        )

    async def report_git_ready(self, branch_name: str) -> bool:
        """Report that git repository is ready."""
        return await self.report_status(
            status="git_ready",
            message="Git repository cloned and branch created",
            details={"branch_name": branch_name},
        )

    async def report_push_complete(
        self,
        branch_name: str,
        commit_sha: str,
        modified_files: list[str],
    ) -> bool:
        """Report that push is complete, triggering MR creation on server."""
        return await self.report_status(
            status="push_complete",
            message="Branch pushed successfully, ready for MR creation",
            details={
                "branch_name": branch_name,
                "commit_sha": commit_sha,
                "modified_files": modified_files,
            },
        )

    async def report_completed(
        self,
        output: dict[str, Any],
        result_type: str = "text",
        sdk_session_id: str = "",
        sdk_transcript: str = "",
    ) -> bool:
        """通过新回调协议报告完成 — POST /api/containers/callback/。

        ``sdk_session_id`` / ``sdk_transcript`` 非空时随 payload 上传，供 server 落库到
        CodingSession 支撑 7 天内 resume 续跑（仅编码任务有意义）。
        """
        log = logger.bind(task_id=self.config.task_id, result_type=result_type)

        if not self.enabled:
            log.info("report_completed_standalone", output_keys=list(output.keys()))
            return True

        inner_payload: dict[str, Any] = {
            "result_type": result_type,
            "output": output,
            "branch_name": output.get("branch_name", ""),
            "commit_sha": output.get("commit_sha", ""),
            "modified_files": output.get("modified_files", []),
        }
        if sdk_session_id:
            inner_payload["sdk_session_id"] = sdk_session_id
            inner_payload["sdk_transcript"] = sdk_transcript
        payload = {
            "type": "completed",
            "session_id": self.config.task_id,
            "token": self.config.callback_token,
            "payload": inner_payload,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self._callback_endpoint(),
                    json=payload,
                    headers=self.headers,
                    timeout=30.0,
                )
                response.raise_for_status()
            log.info("report_completed_ok")
            return True
        except httpx.HTTPError as e:
            log.error("report_completed_failed", error=str(e))
            return False

    async def report_failed(self, error: str) -> bool:
        """通过新回调协议报告失败 — POST /api/containers/callback/。"""
        log = logger.bind(task_id=self.config.task_id)

        if not self.enabled:
            log.info("report_failed_standalone", error=error)
            return True

        payload = {
            "type": "failed",
            "session_id": self.config.task_id,
            "token": self.config.callback_token,
            "payload": {
                "error": error,
            },
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self._callback_endpoint(),
                    json=payload,
                    headers=self.headers,
                    timeout=30.0,
                )
                response.raise_for_status()
            log.info("report_failed_ok")
            return True
        except httpx.HTTPError as e:
            log.error("report_failed_failed", error=str(e))
            return False

    async def report_token_usage(self, usage: dict[str, Any]) -> bool:
        """主动上报本次容器执行的 token 用量 —— POST type=token_usage 到统一回调端点。

        补全此前断裂的 task→回调链路：executor 历史上只写本地 ``usage.json``（无人读取），
        容器 LLM token 从不到达 server。本方法让容器执行结束后主动 emit，server
        ``_handle_token_usage`` 写 ``TokenUsage`` 并桥接落 ``ModelUsageRecord`` 纳入 TPS。

        严格镜像 ``report_completed`` / ``report_failed`` 范式：
          - standalone 模式（``not self.enabled``）：记日志返回 True，不发 HTTP。
          - body 形状与既有回调一致，``payload`` 字段对齐 server ``TokenUsagePayloadSerializer``；
            可选键（provider/ttft_ms/call_source）仅在非空时放入。
          - **best-effort**：``httpx.HTTPError`` 吞掉 + 返回 False，**绝不抛**；token_usage 属
            server ``_DATA_APPEND_TYPES``（终态也接受），失败不影响任务终态回调。

        脱敏（T-72-03-01）：只承载 token 计数 + provider/model/ttft/call_source 元数据，
        **绝不**发 prompt/completion 文本；standalone 日志仅记 model（非敏感）。
        """
        log = logger.bind(task_id=self.config.task_id, model=usage.get("model"))

        if not self.enabled:
            log.info("report_token_usage_standalone", model=usage.get("model"))
            return True

        inner_payload: dict[str, Any] = {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_read_tokens": usage.get("cache_read_tokens", 0),
            "cache_write_tokens": usage.get("cache_write_tokens", 0),
            "total_cost_usd": usage.get("total_cost_usd", 0.0),
            "model": usage.get("model", ""),
            "timestamp": datetime.utcnow().isoformat(),
        }
        # 可选字段仅在非空时透传（向后兼容：旧 server 忽略未知键，新 server 缺省降级）。
        for opt_key in ("provider", "ttft_ms", "call_source"):
            val = usage.get(opt_key)
            if val not in (None, ""):
                inner_payload[opt_key] = val

        body = {
            "type": "token_usage",
            "session_id": self.config.task_id,
            "token": self.config.callback_token,
            "payload": inner_payload,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self._callback_endpoint(),
                    json=body,
                    headers=self.headers,
                    timeout=30.0,
                )
                response.raise_for_status()
            log.info("report_token_usage_ok")
            return True
        except httpx.HTTPError as e:
            log.warning("report_token_usage_failed", error=str(e))
            return False

    async def report_question(
        self,
        question: str,
        options: list[str] | None = None,
        context: str = "",
        code_snippet: str = "",
        default_option: str = "",
        timeout_minutes: int = 10,
    ) -> bool:
        """编码遇阻时向人发起提问（HITL）—— POST type=question 到统一回调端点。

        复用既有 question 协议契约（server 端 QuestionPayloadSerializer + _handle_question），
        不新增协议键。脱敏：question/context/code_snippet 正文绝不入日志，仅记 has_options/状态。
        """
        log = logger.bind(task_id=self.config.task_id)

        if not self.enabled:
            log.info("question_reported_standalone", has_options=bool(options))
            return True

        payload = {
            "type": "question",
            "session_id": self.config.task_id,
            "token": self.config.callback_token,
            "payload": {
                "question": question,
                "options": options or [],
                "context": context,
                "code_snippet": code_snippet,
                "default_option": default_option,
                "timeout_minutes": timeout_minutes,
            },
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self._callback_endpoint(),
                    json=payload,
                    headers=self.headers,
                    timeout=30.0,
                )
                response.raise_for_status()
            log.info("question_reported", has_options=bool(options))
            return True
        except httpx.HTTPError as e:
            log.error("report_question_failed", error=str(e))
            return False

    async def report_suggested_commit_message(
        self,
        suggested_commit_message: str,
    ) -> bool:
        """回传 AI 建议的 commit message 到 SubAgentSession.last_output。

        通过 progress 回调写入 last_output，供 Phase 完成回调读取。
        Per contract: Phase 容器通过 SubAgentSession.last_output 回传 suggested_commit_message。
        """
        return await self.report_status(
            status="progress",
            message="AI suggested commit message generated",
            details={
                "suggested_commit_message": suggested_commit_message,
                "phase": "coding_complete",
            },
        )
