"""artifact_injection —— 上游 wave 编码产物注入下游 prompt（Phase 45-02，ARTIFACT-02）。

兑现跨仓上下文传递的「注入」半环：下游 wave dispatch 时沿**直接** ``depends_on``
反查上游仓的 ``produced_artifacts``（Plan 01 提取落库的结构化产物），渲染为「上游产物 /
上游契约」段注入下游编码容器 prompt——使下游仓（如 wave2 前端）能消费上游仓（如 wave1
后端）产出的 API 契约。

两个职责拆分：

- :func:`acollect_upstream_artifacts`（**async**）：DB 反查收集，async ORM 安全
  （``async for ... depends_on.all()`` + JSON 列标量读取，绝不裸访问 lazy-FK，D-10）。
  仅取**直接** ``depends_on``（不做传递闭包，D-06）；按 ``repository_id`` 排序保渲染确定性
  （Open Q2）；跳过空 / ``available=False`` 占位产物（零回归降级）。
- :func:`render_upstream_artifacts_section`（**纯函数**，无 IO / 无 ORM，DB-free 可单测）：
  空 list → ``""``（零回归命门，绝不渲染空标题）；非空才逐行拼装结构化段。

安全命门（T-45-05/06/07）：渲染段**仅列结构化白名单字段**（仓名 / 分支 / MR url / 契约文件
路径 / 计数），**作为数据呈现**而非指令——**绝不**内联 ``raw_output`` 正文（防 prompt 注入
与 prompt 膨胀）。产物源已在 Plan 01 提取阶段限定白名单字段（不含 token / 凭证）。
"""

from __future__ import annotations

__all__ = ["acollect_upstream_artifacts", "render_upstream_artifacts_section"]

# 注入端显式上限（兑现 artifact_extraction docstring「无界展开由注入端截断」承诺，T-45-02）：
# 每桶（OpenAPI / API 契约）最多渲染前 N 条，超出折叠为「… (+M more)」省略行，
# 防半可信上游产物驱动的无界 prompt 膨胀。
_MAX_FILES_PER_BUCKET = 50
# 单条内联字符串最大长度（防超长路径撑爆 prompt）。
_MAX_INLINE_LEN = 200


def _safe_inline(value: object, *, max_len: int = _MAX_INLINE_LEN) -> str:
    """半可信值消毒——去换行 + 转义反引号，确保渲染为惰性数据而非指令（T-45-05/06/07）。

    上游 runner 容器产出半可信：反引号会提前闭合 Markdown code span、换行会注入伪标题 /
    指令，使「数据」越权成下游 AI 编码 agent 的「指令」。统一把反引号替换为视觉近似的安全
    字符、换行（``\\n`` / ``\\r``）压成空格，并截断长度，绝不让其逃逸成 Markdown 控制结构。
    确定性、无副作用：相同输入恒得相同输出。
    """
    s = str(value).replace("`", "ʼ").replace("\r", " ").replace("\n", " ")
    return s[:max_len]


async def acollect_upstream_artifacts(task) -> list[dict]:
    """沿**直接** ``depends_on`` 反查上游 ``produced_artifacts``（D-06 仅直接依赖）。

    async ORM 安全：``async for upstream in task.depends_on.all()`` 安全迭代正向 M2M +
    读 ``upstream.produced_artifacts``（JSON 列标量，已物化安全），**绝不**裸访问 lazy-FK。
    跳过空 dict 与 ``available`` 非真（缺失或 False）的占位产物——fail-closed：无明确
    ``available`` 标志即视为不可用（无成功产物 → 下游注入段对其不渲染，零回归）。返回前按
    ``repository_id`` 排序保多上游渲染顺序确定性（Open Q2）。

    Args:
        task: 下游 ``RepoCodingTask`` 实例（其 ``depends_on`` 为上游仓级依赖边）。

    Returns:
        上游 ``produced_artifacts`` dict 列表（按 ``repository_id`` 升序，可能为空）。
    """
    out: list[dict] = []
    async for upstream in task.depends_on.all():
        artifacts = upstream.produced_artifacts or {}
        # 空 / 占位（available 缺失或为 False）跳过——fail-closed：无明确 available 标志即视为
        # 不可用（与提取端占位 {"available": False} 保守语义对齐），下游注入段对其不渲染（零回归）。
        if artifacts and artifacts.get("available", False):
            out.append(artifacts)
    return sorted(out, key=lambda a: a.get("repository_id", ""))


def render_upstream_artifacts_section(artifacts: list[dict]) -> str:
    """渲染「# 上游产物 / 上游契约」段；空 list → ``""``（零回归命门，不渲染空标题）。

    镜像 ``AICodingNode._build_files_section`` 的空守卫 + 逐行 append 结构。每个上游仓输出
    仓名（``repository_name`` 缺则 ``repository_id``）、分支 / MR（非空才出）、OpenAPI 与 API
    契约文件清单（非空才出标签 + 逐文件 ``  - `path```）、变更文件数（非 None 才出）。

    安全（T-45-05/06/07）：所有半可信字段（仓名 / 分支 / MR / 文件路径）均过
    :func:`_safe_inline` 消毒（去换行 + 转义反引号 + 截长），仅渲染白名单结构化字段为
    Markdown **数据**，绝不内联产物正文，亦不让半可信内容越权成指令。
    截断（T-45-02）：每桶（OpenAPI / API 契约）最多渲染前 ``_MAX_FILES_PER_BUCKET`` 条，
    超出折叠为「``… (+M more)``」省略行，防无界 prompt 膨胀。

    Args:
        artifacts: 上游 ``produced_artifacts`` dict 列表（由 collect 收集排序）。

    Returns:
        渲染后的 Markdown 段；``artifacts`` 为空时返回 ``""``。
    """
    if not artifacts:
        return ""
    lines = ["# 上游产物 / 上游契约", "", "下游仓编码可消费以下上游仓已产出的契约："]
    for a in artifacts:
        name = a.get("repository_name") or a.get("repository_id", "")
        lines.append(f"\n## {_safe_inline(name)}")
        if a.get("branch"):
            lines.append(f"- 分支: `{_safe_inline(a['branch'])}`")
        if a.get("mr_url"):
            lines.append(f"- MR: {_safe_inline(a['mr_url'])}")
        for label, key in (("OpenAPI", "openapi"), ("API 契约", "api_contracts")):
            files = a.get(key) or []
            if files:
                lines.append(f"- {label}:")
                shown = files[:_MAX_FILES_PER_BUCKET]
                lines.extend(f"  - `{_safe_inline(f)}`" for f in shown)
                if len(files) > _MAX_FILES_PER_BUCKET:
                    lines.append(f"  - … (+{len(files) - _MAX_FILES_PER_BUCKET} more)")
        changed = (a.get("diff_summary") or {}).get("files_changed")
        if changed is not None:
            lines.append(f"- 变更文件数: {changed}")
    return "\n".join(lines)
