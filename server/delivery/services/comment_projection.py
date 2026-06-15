"""评论树投影 —— 从事件流读时计算当前评论树（CMT-02，非事实表）。

投影是**查询/视图，非另一张事实表**：``project_comment_tree`` 在读时对
``WorkItemCommentEvent`` 事件流计算当前评论树，**绝不写库 / 不改事件行**
（append-only 不可变，编辑/删除作为新事件，CMT-02）。

折叠规则（per CONTEXT Grey Area 5）：
- 按 ``feishu_comment_id`` 归并同一评论的事件序列，折叠出当前态节点；
- body 取**最新有效事件**（含 edited 取最新 body——本 phase 虽不合成 edited，
  逻辑须支持）；event_type / event_time 取最新；
- approval_semantic 取最新非 none（保留审批语义到节点）；
- ``deleted`` 事件 → 节点标 ``is_deleted=True``（**保留占位**以维持线程结构；
  deleted 节点 body 保留最新非空 body 供追溯，不置空）；
- 按 ``thread_parent_id`` 组装线程层级（根节点 = 父为空或父不在集合内）；
- 同层按 ``event_time`` 升序（None 排末尾，稳定保 ingested 顺序）。
"""

from __future__ import annotations

from datetime import UTC, datetime

from asgiref.sync import sync_to_async

from delivery.models import ApprovalSemantic, CommentEventType, WorkItemCommentEvent

__all__ = ["project_comment_tree", "aproject_comment_tree"]

# event_time 为 None 的事件排末尾用的哨兵（恒 aware，与事件 aware 戳可比较）
_TIME_MAX = datetime.max.replace(tzinfo=UTC)


def project_comment_tree(work_item) -> list[dict]:
    """从事件流投影当前评论树（读时计算，不写库，CMT-02）。

    Args:
        work_item: 目标 WorkItem（取其全部 comment_events 投影）。

    Returns:
        线程层级的节点 dict 列表（顶层为根节点）。节点形状：
        ``feishu_comment_id / author / body / event_type / approval_semantic /
        is_deleted / event_time / thread_parent_id / children``。
    """
    # 取全部事件，先按 ingested_at 稳定取出，再按 event_time 升序（None 末尾，稳定保序）
    events = list(WorkItemCommentEvent.objects.filter(work_item=work_item).order_by("ingested_at"))
    events.sort(key=lambda e: e.event_time or _TIME_MAX)

    nodes: dict[str, dict] = {}
    order: list[str] = []  # 首次出现顺序（已升序），保 children/roots 稳定排序

    for event in events:
        cid = event.feishu_comment_id
        node = nodes.get(cid)
        if node is None:
            node = {
                "feishu_comment_id": cid,
                "author": event.author,
                "body": event.body,
                "event_type": event.event_type,
                "approval_semantic": ApprovalSemantic.NONE,
                "is_deleted": False,
                "event_time": event.event_time,
                "thread_parent_id": event.thread_parent_id,
                "children": [],
            }
            nodes[cid] = node
            order.append(cid)
        else:
            # 最新事件覆盖当前态：body（含 edited 取最新）/ event_type / event_time
            node["body"] = event.body
            node["event_type"] = event.event_type
            node["event_time"] = event.event_time
            if event.author:
                node["author"] = event.author

        # 线程父以最新非空为准（线程父稳定）
        if event.thread_parent_id:
            node["thread_parent_id"] = event.thread_parent_id
        # approval_semantic 取最新非 none
        if event.approval_semantic and event.approval_semantic != ApprovalSemantic.NONE:
            node["approval_semantic"] = event.approval_semantic
        # deleted 标记节点（保留占位维持线程结构）
        if event.event_type == CommentEventType.DELETED:
            node["is_deleted"] = True

    # 组装线程层级：父在集合内挂 children，否则置顶层
    roots: list[dict] = []
    for cid in order:
        node = nodes[cid]
        parent_id = node["thread_parent_id"]
        if parent_id and parent_id in nodes:
            nodes[parent_id]["children"].append(node)
        else:
            roots.append(node)

    _sort_recursive(roots)
    return roots


def _sort_recursive(node_list: list[dict]) -> None:
    """同层按 event_time 升序（None 末尾），递归排子节点。"""
    node_list.sort(key=lambda n: n["event_time"] or _TIME_MAX)
    for node in node_list:
        _sort_recursive(node["children"])


# async 包装：供 REST / 异步调用方使用（纯同步投影经 sync_to_async 桥接 ORM 读）。
aproject_comment_tree = sync_to_async(project_comment_tree)
