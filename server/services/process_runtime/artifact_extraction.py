"""artifact_extraction —— 上游 wave 编码产物提取纯函数（Phase 45-01，ARTIFACT-01）。

把 ``SubAgentSession.task_result``（半可信 runner 容器产出的 git 产物：branch/commit/
pr_url/modified_files）做轻量路径启发式归类（API 契约 / OpenAPI / diff 计数摘要），构
结构化 ``produced_artifacts`` dict，供 Plan 02 注入下游 wave prompt。

**纯函数**（无 IO / 无 ORM / 无 LLM / DB-free 可单测）。入参为**已物化**标量 / TaskResult
实例（其字段为已加载列，安全）——**绝不**接 lazy ORM 对象（``task.subagent_session`` /
``task.repository``），保 DB-free 可单测（单测可构造未保存的内存 ``TaskResult`` 实例）。

安全命门（T-45-01）：产物只取白名单字段（branch/commit_sha/pr_url/path/计数），**绝不**
整体落 ``raw_output`` 正文、token、凭证——仅 path/url/计数。归类纯字符串匹配无递归
（T-45-02 DoS：无界展开由注入端 Plan 02 截断）。
"""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = ["build_produced_artifacts", "classify_modified_files"]

# 轻量路径启发式（v0.8，无 LLM）：OpenAPI/Swagger 优先匹配（更具体），否则落通用契约桶。
_OPENAPI_PATTERNS = ("openapi", "swagger")
_OPENAPI_SUFFIXES = ("openapi.json", "openapi.yaml", "openapi.yml", "swagger.json")
_CONTRACT_PATTERNS = ("/api/", "schema", ".proto", ".graphql", ".graphqls", "contract")


def classify_modified_files(modified_files: list[str]) -> tuple[list[str], list[str]]:
    """把 ``modified_files`` 路径启发式归类为 ``(api_contracts, openapi)``。纯字符串匹配。

    逐路径小写匹配：命中 ``openapi``/``swagger`` 模式或以 OpenAPI 后缀结尾 → openapi 桶；
    否则命中 ``/api/``/``schema``/``.proto``/``.graphql(s)``/``contract`` → api_contracts 桶；
    其余忽略（非契约文件不进任何桶）。``modified_files`` 为 ``None`` 时按空列表处理（绝不抛）。

    Returns:
        ``(api_contracts, openapi)``——两桶路径列表（保留原始大小写路径）。
    """
    api_contracts: list[str] = []
    openapi: list[str] = []
    for raw in modified_files or []:
        path = str(raw)
        low = path.lower()
        if any(p in low for p in _OPENAPI_PATTERNS) or low.endswith(_OPENAPI_SUFFIXES):
            openapi.append(path)
        elif any(p in low for p in _CONTRACT_PATTERNS):
            api_contracts.append(path)
    return api_contracts, openapi


def build_produced_artifacts(
    *,
    repository_id: str,
    repository_name: str,
    task_result,
) -> dict:
    """从 ``TaskResult``（git 产物）构结构化 ``produced_artifacts``；``task_result=None`` → 占位。

    ``task_result is None``（无 git 产物 / 未落 TaskResult）→ base + ``{"available": False}``
    占位（非异常路径，下游注入段为空降级，零回归）。否则读 ``task_result.modified_files``
    （已物化标量，**绝不**接 lazy ORM 对象）调 :func:`classify_modified_files` 归类，返回含
    branch/commit_sha/mr_url/modified_files/api_contracts/openapi/diff_summary 的结构化产物。

    安全：仅落 path/url/计数白名单字段——**绝不**落 ``raw_output`` 正文 / token / 凭证。

    Args:
        repository_id: 上游被编码仓 id（服务端权威，``str(task.repository_id)`` 标量）。
        repository_name: 仓名（取不到时调用方回退为 repository_id）。
        task_result: ``TaskResult`` 实例（git 产物）或 ``None``。

    Returns:
        结构化 ``produced_artifacts`` dict（含 ``available`` 标志位）。
    """
    base = {
        "repository_id": repository_id,
        "repository_name": repository_name,
        "extracted_at": datetime.now(UTC).isoformat(),
    }
    if task_result is None:
        return {**base, "available": False}

    modified = list(task_result.modified_files or [])
    api_contracts, openapi = classify_modified_files(modified)
    return {
        **base,
        "available": True,
        "branch": task_result.branch_name or "",
        "commit_sha": task_result.commit_sha or "",
        "mr_url": task_result.pr_url or "",
        "modified_files": modified,
        "api_contracts": api_contracts,
        "openapi": openapi,
        "diff_summary": {"files_changed": len(modified)},
    }
