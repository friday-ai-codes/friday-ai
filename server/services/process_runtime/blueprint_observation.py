"""蓝图会话的**消费方观测**共享读侧（同步点 2 边界接缝收口）。

蓝图链能建会话的四个入口里只有 chat 一家把「出口观测」做对了
（``agents/tools/plan_research_tools._map_terminal_blueprint``）；另外三家沿用**旧链模型**
观测蓝图会话，各自坏在不同地方（v0.20.0 里程碑审计 §4.1 的 G1 / G3 / G4）：

- **workflow**：挂起判据用旧链 ``ClarificationService.ahas_pending``。蓝图链**从不写**
  ``Clarification`` 行（全仓该模型的唯一写入点在 ``clarification_service.py``），
  蓝图侧写的是 ``BlueprintThread`` ⇒ 每一次规格门提问与每一次确认硬门都把工作流判成
  ``failed``。
- **feature_list**：待答问题取自 ``ClarificationQuestion``（旧链子题模型）⇒ 阻塞在
  ``BlueprintThread`` 上的会话永久显示 ``researching``、问题列表为空。
- **mcp**：主载荷读 ``content["execution_plan"]``，blueprint/v1 无此顶层键 ⇒
  ``repository_tasks`` 恒 ``[]``（**结构合法而语义为空**的静默降级）。

本模块把「这条蓝图会话现在是什么状态、卡在哪个问题上」收成**一份**读侧实现，形状照
chat 的既有做法（⛔ 不造第四套约定）。三个入口各自在自己的边界上早返回到本模块，
⛔ 绝不把蓝图分支交织进旧链代码路径 —— 开关关闭时旧链必须逐字不变。

**纯读侧**：只查询，不转移状态、不写库（INV-6 —— 写一律经 service）。所有 Django 模型
import 都在函数内（lazy），与 ``blueprint_resume`` 同口径，避免 ``process_runtime`` 在
模块级依赖 ``delivery``。

**脱敏不可绕过**：线程题面来自半可信 LLM 产物，逐条过 ``redact_secrets_in_text`` 再出栈。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

__all__ = [
    "BLUEPRINT_PENDING_THREAD_LIMIT",
    "BLUEPRINT_STATUS_MESSAGES",
    "BlueprintObservation",
    "ablueprint_observation",
    "aload_blocking_threads",
    "blueprint_status_message",
    "is_blueprint_session",
    "render_observed_blueprint",
]

# 单次观测返回的阻塞线程条数上限（与 ``mcp_tools/views._BLUEPRINT_PENDING_LIMIT`` 同量级）。
# 上限存在的理由是「一次响应体不被一个异常会话撑爆」，⛔ 不是业务语义。
BLUEPRINT_PENDING_THREAD_LIMIT = 50

# 蓝图状态 → 对外文案（**唯一事实源**）。
#
# ⛔ 键名不是响应体字段名，不触 INV-6 的字典键形态扫描；响应体里那一位一律叫
# ``current_status``（114-05 立的既有解法），⛔ 绝不出现字面 ``blueprint_status``。
#
# ⚠️ 表里**没有** ``needs_clarification`` / ``failed``：那两档在调用侧分别走「挂起」与
# 「失败」分支，落不到文案表；写进来只会给出「看起来正常」的第三种归宿。
BLUEPRINT_STATUS_MESSAGES: dict[str, str] = {
    "pending_review": "技术蓝图已产出，等待人工终审。",
    "confirmed": "技术蓝图已确认，可进入实施。",
    "implementing": "技术蓝图已确认并在实施中。",
    "implemented": "技术蓝图已实施完成。",
}

_DEFAULT_STATUS_MESSAGE = "技术蓝图编排仍在进行中。"


@dataclass(frozen=True)
class BlueprintObservation:
    """一条蓝图会话的对外可观测快照（读侧值对象）。

    - ``artifact_id``：蓝图 artifact id，**后续一切续取 / 作答的寻址键**；取不到为空串。
    - ``current_status``：``Artifact.blueprint_status``（空串 = 尚未进入状态机）。
    - ``threads``：仍待人回答的 **open + blocking** 线程（``ai_clarification`` 与
      ``repo_confirmation`` 两类都算，⛔ **不按 ``kind`` 过滤** —— 判据与
      ``blueprint_resume`` 的 pause 短路逐字同源，只认一类会让确认门挂起的会话被判死）。
    """

    artifact_id: str = ""
    current_status: str = ""
    threads: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_blocked(self) -> bool:
        """是否卡在待人回答的阻塞线程上（⇒ 调用方应挂起而不是报失败/报完成）。"""
        return bool(self.threads)

    @property
    def first_thread(self) -> dict[str, Any]:
        """首个阻塞线程（无则空 dict）；顺序由 ``created_at`` 显式排序保证稳定。"""
        return self.threads[0] if self.threads else {}


def is_blueprint_session(session: Any) -> bool:
    """该会话是否走蓝图 process（三个入口早返回的**唯一**判据）。

    ⛔ 绝不按 ``entrypoint`` 判：MCP 入口记的 ``entrypoint`` 实测就是 ``"workflow"``
    （既有约定，见 ``mcp_tools/orchestration_delegate`` 模块 docstring）。
    """
    from services.process_runtime.blueprint_resume import BLUEPRINT_PROCESS_TYPE

    return str(getattr(session, "process_type", "")) == BLUEPRINT_PROCESS_TYPE


def blueprint_status_message(current_status: str) -> str:
    """蓝图状态 → 对外文案；未登记的中间态回落「仍在进行中」。

    ⭐ **其余中间态一律不报失败**：会话到终态而蓝图状态仍停在 ``researching`` /
    ``drafting`` 属于**可诊断的异常**，报「失败」只会让用户以为方案没了（产物其实在库里、
    可继续推进）。
    """
    return BLUEPRINT_STATUS_MESSAGES.get(str(current_status or ""), _DEFAULT_STATUS_MESSAGE)


def render_observed_blueprint(content: dict[str, Any], current_status: str) -> str:
    """按观测到的状态渲染蓝图 markdown（三个消费方共用**同一个**调用点）。

    ⚠️ **收成一个函数不只是去重**：INV-6 的字段级守卫
    （``tests/delivery/test_blueprint_inv6_guard.py``）把状态字段的 kwarg 形态当旁路写
    扫描，「读状态 → 传进纯渲染器」的豁免是**逐行**匹配的（kwarg 与渲染器名不在同一行
    即判违规）。散在三处、各自受缩进影响随时可能被 formatter 折行 —— 收成一处后只需
    保证下面那一行不折。

    水印由 ``render_blueprint_markdown`` 按状态**无条件**加，白名单是闭合集合：空串 /
    未知状态一律落集合外 ⇒ 当作「未确认」渲染，方向恰好是 fail-safe。
    """
    from services.process_runtime.blueprint_render import render_blueprint_markdown

    return render_blueprint_markdown(content, blueprint_status=current_status)


async def aload_blocking_threads(artifact_id: Any) -> list[dict[str, Any]]:
    """该 artifact 上仍待人回答的 **open + blocking** 线程（⛔ **不传 ``kind``**）。

    显式 ``order_by("created_at")``：``BlueprintThread.Meta`` 无 ``ordering``，不排序会让
    「首题」随数据库返回顺序漂移，用户每次刷新看到的问题都可能不同。

    ⚠️ **异常不吞**：读失败必须让调用方看到失败，⛔ 绝不包成「空清单」——调用方会把它
    读成「没有待澄清」并据此推进（那正是 Phase 115 MJ-04 要消灭的静默降级）。调用侧按
    自己的失败语义处理（工作流回 failed 出边、MCP 回 failed delegate 结果）。
    """
    from delivery.models import BlueprintThread, BlueprintThreadMessage, ThreadStatus

    if not artifact_id:
        return []
    rows = [
        row
        async for row in BlueprintThread.objects.filter(
            artifact_id=artifact_id, status=ThreadStatus.OPEN, blocking=True
        ).order_by("created_at")[:BLUEPRINT_PENDING_THREAD_LIMIT]
    ]
    if not rows:
        return []
    first_body: dict[str, str] = {}
    async for message in (
        BlueprintThreadMessage.objects.filter(thread_id__in=[row.id for row in rows])
        .order_by("thread_id", "created_at")
        .values("thread_id", "body")
    ):
        first_body.setdefault(str(message["thread_id"]), str(message["body"] or ""))
    return [
        {
            "thread_id": str(row.id),
            "kind": str(row.kind or ""),
            # 半可信 LLM 产出进响应体/对话，脱敏不可绕过。
            "question": redact_secrets_in_text(first_body.get(str(row.id), ""))[:2000],
            "options": list(row.options or []) if isinstance(row.options, list) else [],
            "created_at": row.created_at.isoformat() if row.created_at else "",
        }
        for row in rows
    ]


async def ablueprint_observation(
    session: Any, *, with_threads: bool = True
) -> BlueprintObservation:
    """会话 → 蓝图观测快照（``artifact_id`` + ``blueprint_status`` + 阻塞线程）。

    ``with_threads=False`` 时只取状态两键，跳过线程查询（调用方已知不需要问题清单时用，
    省一次 join）。

    **async ORM 防裸 lazy-FK**：全程用 ``*_id`` 标量 + ``.values()`` + ``afirst``。
    """
    from delivery.models import ArtifactVersion

    version_id = getattr(session, "current_artifact_version_id", None)
    if not version_id:
        return BlueprintObservation()

    row = await (
        ArtifactVersion.objects.filter(id=version_id)
        .values("artifact_id", "artifact__blueprint_status")
        .afirst()
    )
    artifact_id = str((row or {}).get("artifact_id") or "")
    current_status = str((row or {}).get("artifact__blueprint_status") or "")
    if not artifact_id or not with_threads:
        return BlueprintObservation(artifact_id=artifact_id, current_status=current_status)

    return BlueprintObservation(
        artifact_id=artifact_id,
        current_status=current_status,
        threads=await aload_blocking_threads(artifact_id),
    )
