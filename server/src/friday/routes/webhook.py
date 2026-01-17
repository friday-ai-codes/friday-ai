"""飞书项目 Webhook 处理路由。"""
import json
from typing import Optional, Set
import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import selectinload
from sqlmodel import select
from ..database import get_session
from ..models import (
 Project,
 Task,
 TaskStatus,
 WebhookLog,
 WebhookLogStatus,
 WorkItemLog,
)
from ..services.feishu import create_feishu_client_for_project, verify_webhook_token
router = APIRouter(prefix="/api/webhook", tags=["webhook"])
logger = structlog.get_logger(__name__)
# 幂等处理：存储已处理的事件 UUID
# 注意：生产环境应使用 Redis 或数据库存储
_processed_events: Set[str] = set
_MAX_PROCESSED_EVENTS = 10000 # 防止内存无限增长
class FeishuWebhookHeader(BaseModel):
 """飞书 Webhook 请求头结构。"""
 operator: Optional[str] = None
 event_type: str = ""
 token: Optional[str] = None
 uuid: Optional[str] = None
 rule_name: Optional[str] = None
class FeishuWebhookPayload(BaseModel):
 """飞书 Webhook 请求体通用结构。"""
 model_config = {"extra": "allow"} # 允许额外字段
 id: Optional[int] = None
 name: Optional[str] = None
 project_key: Optional[str] = None
 project_simple_name: Optional[str] = None
 work_item_type_key: Optional[str] = None
 updated_at: Optional[int] = None
 updated_by: Optional[str] = None
 created_at: Optional[int] = None
 created_by: Optional[str] = None
 # 工作项状态相关
 work_item_status: Optional[dict] = None
 pre_work_item_status: Optional[dict] = None
 cur_work_item_status: Optional[dict] = None
 # 评论相关
 comment: Optional[str] = None
 # 字段变更相关
 changed_fields: Optional[list] = None
 fields: Optional[list] = None
 # 节点相关
 current_nodes: Optional[list] = None
 nodes: Optional[list] = None
class FeishuWebhookRequest(BaseModel):
 """飞书 Webhook 完整请求结构。"""
 model_config = {"extra": "allow"}
 header: Optional[FeishuWebhookHeader] = None
 payload: Optional[FeishuWebhookPayload] = None
 # URL 验证挑战
 type: Optional[str] = None
 challenge: Optional[str] = None
 token: Optional[str] = None
def is_event_processed(event_uuid: str) -> bool:
 """检查事件是否已处理（幂等性检查）。
 Args:
 event_uuid: 事件唯一标识
 Returns:
 如果已处理返回 True
 """
 return event_uuid in _processed_events
def mark_event_processed(event_uuid: str) -> None:
 """标记事件已处理。
 Args:
 event_uuid: 事件唯一标识
 """
 # 防止内存无限增长
 if len(_processed_events) >= _MAX_PROCESSED_EVENTS:
 # 简单策略：清除一半旧记录
 to_remove = list(_processed_events)[: _MAX_PROCESSED_EVENTS // 2]
 for uuid in to_remove:
 _processed_events.discard(uuid)
 _processed_events.add(event_uuid)
@router.post("/feishu")
async def handle_feishu_webhook(
 request: Request,
 background_tasks: BackgroundTasks,
):
 """处理飞书项目 Webhook 事件。
 支持的事件类型：
 - URL 验证挑战
 - WorkitemCreateEvent: 创建工作项
 - WorkitemStatusEvent: 工作项状态变更
 - WorkFlowNodeStatusEvent: 工作项节点流转
 - WorkitemCommentEvent: 工作项评论
 - WorkitemUpdateEvent: 工作项字段修改
 验证方式：
 - 使用 header.token 进行简单 Token 比对验证
 - 每个项目可配置独立的 webhook_token
 """
 body = await request.body
 raw_body = body.decode("utf-8")
 # 解析请求体
 try:
 data = json.loads(body)
 except json.JSONDecodeError:
 raise HTTPException(status_code=400, detail="无效的 JSON 格式")
 # 处理 URL 验证挑战
 if data.get("type") == "url_verification":
 return {"challenge": data.get("challenge", "")}
 # 解析 Webhook 请求
 try:
 webhook_request = FeishuWebhookRequest(**data)
 except Exception as e:
 logger.error(f"解析 Webhook 请求失败: {e}")
 raise HTTPException(status_code=400, detail=f"请求格式错误: {e}")
 if not webhook_request.header or not webhook_request.payload:
 # 记录被忽略的请求
 await _save_webhook_log(
 raw_request=raw_body,
 event_uuid=None,
 event_type="",
 project_key=None,
 project_id=None,
 status=WebhookLogStatus.IGNORED,
 error_message="缺少 header 或 payload",
 )
 return {"status": "ignored", "reason": "缺少 header 或 payload"}
 header = webhook_request.header
 payload = webhook_request.payload
 # 幂等性检查
 if header.uuid:
 if is_event_processed(header.uuid):
 logger.info(f"事件已处理，跳过: {header.uuid}")
 # 记录重复事件
 await _save_webhook_log(
 raw_request=raw_body,
 event_uuid=header.uuid,
 event_type=header.event_type or "",
 project_key=payload.project_key,
 project_id=None,
 status=WebhookLogStatus.DUPLICATE,
 error_message=None,
 )
 return {"status": "duplicate", "uuid": header.uuid}
 # 获取 project_key 并查找项目
 project_key = payload.project_key or payload.project_simple_name
 if not project_key:
 await _save_webhook_log(
 raw_request=raw_body,
 event_uuid=header.uuid,
 event_type=header.event_type or "",
 project_key=None,
 project_id=None,
 status=WebhookLogStatus.IGNORED,
 error_message="缺少 project_key",
 )
 return {"status": "ignored", "reason": "缺少 project_key"}
 # 查找项目并验证 Token
 project_id: Optional[str] = None
 async with get_session as db:
 result = await db.exec(
 select(Project).where(Project.feishu_project_key == project_key)
 )
 project = result.one_or_none
 if not project:
 logger.warning(f"未找到项目: {project_key}")
 await _save_webhook_log(
 raw_request=raw_body,
 event_uuid=header.uuid,
 event_type=header.event_type or "",
 project_key=project_key,
 project_id=None,
 status=WebhookLogStatus.IGNORED,
 error_message=f"项目未配置: {project_key}",
 )
 return {"status": "ignored", "reason": f"项目未配置: {project_key}"}
 project_id = project.id
 # 验证 Webhook Token
 if project.feishu_webhook_token:
 if not verify_webhook_token(
 header.token or "",
 project.feishu_webhook_token,
 ):
 await _save_webhook_log(
 raw_request=raw_body,
 event_uuid=header.uuid,
 event_type=header.event_type or "",
 project_key=project_key,
 project_id=project_id,
 status=WebhookLogStatus.ERROR,
 error_message="Token 验证失败",
 )
 raise HTTPException(status_code=401, detail="Token 验证失败")
 # 标记事件已处理
 if header.uuid:
 mark_event_processed(header.uuid)
 # 根据事件类型路由到处理器
 event_type = header.event_type or ""
 logger.info(f"处理事件: {event_type}, 项目: {project_key}, UUID: {header.uuid}")
 # 记录成功接收的请求
 await _save_webhook_log(
 raw_request=raw_body,
 event_uuid=header.uuid,
 event_type=event_type,
 project_key=project_key,
 project_id=project_id,
 status=WebhookLogStatus.ACCEPTED,
 error_message=None,
 )
 if event_type == "WorkitemCreateEvent":
 background_tasks.add_task(
 handle_workitem_create_event,
 project_key=project_key,
 payload=payload.model_dump,
 )
 elif event_type == "WorkitemStatusEvent":
 background_tasks.add_task(
 handle_workitem_status_event,
 project_key=project_key,
 payload=payload.model_dump,
 )
 elif event_type == "WorkFlowNodeStatusEvent":
 background_tasks.add_task(
 handle_workflow_node_status_event,
 project_key=project_key,
 payload=payload.model_dump,
 )
 elif event_type == "WorkitemCommentEvent":
 background_tasks.add_task(
 handle_workitem_comment_event,
 project_key=project_key,
 payload=payload.model_dump,
 )
 elif event_type == "WorkitemUpdateEvent":
 background_tasks.add_task(
 handle_workitem_update_event,
 project_key=project_key,
 payload=payload.model_dump,
 )
 else:
 logger.info(f"未处理的事件类型: {event_type}")
 return {"status": "ignored", "event_type": event_type}
 return {"status": "accepted", "event_type": event_type, "uuid": header.uuid}
async def _save_webhook_log(
 raw_request: str,
 event_uuid: Optional[str],
 event_type: str,
 project_key: Optional[str],
 project_id: Optional[str],
 status: WebhookLogStatus,
 error_message: Optional[str],
) -> None:
 """保存 Webhook 请求日志到数据库。"""
 try:
 async with get_session as db:
 log = WebhookLog(
 event_uuid=event_uuid,
 raw_request=raw_request,
 event_type=event_type,
 project_key=project_key,
 project_id=project_id,
 status=status,
 error_message=error_message,
 )
 db.add(log)
 await db.commit
 except Exception as e:
 logger.error(f"保存 Webhook 日志失败: {e}")
async def handle_workitem_create_event(project_key: str, payload: dict):
 """处理工作项创建事件。
 当在飞书项目中创建新的工作项时触发，自动创建对应的任务。
 """
 work_item_id = payload.get("id")
 work_item_name = payload.get("name", "")
 work_item_type = payload.get("work_item_type_key", "story")
 if not work_item_id:
 logger.warning("工作项创建事件缺少 id")
 return
 async with get_session as db:
 # 查找项目（预加载关联的仓库）
 result = await db.exec(
 select(Project)
 .where(Project.feishu_project_key == project_key)
 .options(selectinload(Project.repositories)) # type: ignore
 )
 project = result.one_or_none
 if not project:
 logger.warning(f"工作项创建事件：项目未找到 {project_key}")
 return
 # 检查任务是否已存在
 result = await db.exec(
 select(Task).where(Task.work_item_id == str(work_item_id))
 )
 existing_task = result.one_or_none
 if existing_task:
 logger.info(f"任务已存在: {work_item_id}")
 return
 # 获取工作项详情
 description = ""
 try:
 feishu_client = create_feishu_client_for_project(project)
 work_item_info = await feishu_client.get_work_item(
 project_key=project_key,
 work_item_id=work_item_id,
 work_item_type=work_item_type,
 )
 description = work_item_info.description
 work_item_name = work_item_info.name or work_item_name
 # 保存工作项日志
 if work_item_info.raw_response:
 try:
 work_item_log = WorkItemLog(
 raw_response=work_item_info.raw_response,
 work_item_id=str(work_item_id),
 work_item_type=work_item_type,
 project_key=project_key,
 project_id=project.id,
 task_id=None, # 任务稍后创建
 )
 db.add(work_item_log)
 await db.commit
 await db.refresh(work_item_log)
 except Exception as log_e:
 logger.error(f"保存工作项日志失败: {log_e}")
 except Exception as e:
 logger.error(f"获取工作项详情失败: {e}")
 # 使用 Webhook 中的基本信息继续创建
 # 尝试自动关联仓库
 # 1. 如果项目只有一个关联仓库，自动关联
 # 2. 如果有多个，暂不关联，需人工在任务详情页选择（或后续支持在飞书描述中指定）
 repository_id = None
 if len(project.repositories) == 1:
 repository_id = project.repositories[0].id
 logger.info(f"自动关联唯一仓库: {project.repositories[0].name}")
 elif len(project.repositories) > 1:
 logger.info("项目关联多个仓库，需手动指定任务仓库")
 else:
 logger.warning("项目未关联任何仓库，无法自动关联")
 # 创建新任务
 new_task = Task(
 project_id=project.id,
 repository_id=repository_id, # 可能为 None
 work_item_id=str(work_item_id),
 feature_id=str(work_item_id),
 title=work_item_name,
 description=description,
 status=TaskStatus.PENDING,
 )
 db.add(new_task)
 await db.commit
 logger.info(f"已创建任务: {work_item_id} -> {new_task.id}")
async def handle_workitem_status_event(project_key: str, payload: dict):
 """处理工作项状态变更事件。
 当飞书项目状态变更时触发：
 1. 如果任务不存在，自动创建任务并读取工作项详情
 2. 更新任务状态
 3. 触发后续的自动化流程（如 code 工作）
 """
 work_item_id = payload.get("id")
 work_item_name = payload.get("name", "")
 work_item_type = payload.get("work_item_type_key", "story")
 cur_status = payload.get("cur_work_item_status", {})
 pre_status = payload.get("pre_work_item_status", {})
 if not work_item_id:
 logger.warning("工作项状态变更事件缺少 id")
 return
 cur_state_key = cur_status.get("state_key", "")
 pre_state_key = pre_status.get("state_key", "")
 logger.info(f"状态变更: {work_item_id} {pre_state_key} -> {cur_state_key}")
 async with get_session as db:
 # 查找项目（预加载关联的仓库）
 result = await db.exec(
 select(Project)
 .where(Project.feishu_project_key == project_key)
 .options(selectinload(Project.repositories)) # type: ignore
 )
 project = result.one_or_none
 if not project:
 logger.warning(f"工作项状态变更事件：项目未找到 {project_key}")
 return
 # 查找任务
 result = await db.exec(
 select(Task).where(Task.work_item_id == str(work_item_id))
 )
 task = result.one_or_none
 # 如果任务不存在，自动创建
 if not task:
 logger.info(f"任务不存在，自动创建: {work_item_id}")
 # 获取工作项详情（需求文档）
 description = ""
 try:
 feishu_client = create_feishu_client_for_project(project)
 work_item_info = await feishu_client.get_work_item(
 project_key=project_key,
 work_item_id=work_item_id,
 work_item_type=work_item_type,
 )
 description = work_item_info.description
 work_item_name = work_item_info.name or work_item_name
 # 保存工作项日志
 if work_item_info.raw_response:
 try:
 work_item_log = WorkItemLog(
 raw_response=work_item_info.raw_response,
 work_item_id=str(work_item_id),
 work_item_type=work_item_type,
 project_key=project_key,
 project_id=project.id,
 task_id=None, # 任务稍后创建
 )
 db.add(work_item_log)
 await db.commit
 await db.refresh(work_item_log)
 logger.info(f"已保存工作项日志: {work_item_id}")
 except Exception as log_e:
 logger.error(f"保存工作项日志失败: {log_e}")
 except Exception as e:
 logger.error(f"获取工作项详情失败: {e}")
 # 使用 Webhook 中的基本信息继续创建
 # 尝试自动关联仓库
 repository_id = None
 if len(project.repositories) == 1:
 repository_id = project.repositories[0].id
 logger.info(f"自动关联唯一仓库: {project.repositories[0].name}")
 elif len(project.repositories) > 1:
 logger.info("项目关联多个仓库，需手动指定任务仓库")
 else:
 logger.warning("项目未关联任何仓库，无法自动关联")
 # 创建新任务
 task = Task(
 project_id=project.id,
 repository_id=repository_id,
 work_item_id=str(work_item_id),
 feature_id=str(work_item_id),
 title=work_item_name,
 description=description,
 status=TaskStatus.PENDING,
 )
 db.add(task)
 await db.commit
 await db.refresh(task)
 logger.info(f"已创建任务: {work_item_id} -> {task.id}")
 # 根据飞书状态更新任务状态
 # 这里可以根据实际的状态映射进行调整
 if "planning" in cur_state_key.lower or "规划" in cur_state_key.lower:
 if task.status == TaskStatus.PENDING:
 task.status = TaskStatus.PLANNING
 await db.commit
 logger.info(f"任务状态更新为 PLANNING: {task.id}")
 # TODO: 触发规划容器
 elif "doing" in cur_state_key.lower or "进行中" in cur_state_key.lower:
 if task.status == TaskStatus.PLAN_REVIEW:
 task.status = TaskStatus.EXECUTING
 await db.commit
 logger.info(f"任务状态更新为 EXECUTING: {task.id}")
 # TODO: 触发执行容器
 elif "review" in cur_state_key.lower or "评审" in cur_state_key.lower:
 if task.status == TaskStatus.EXECUTING:
 task.status = TaskStatus.CODE_REVIEW
 await db.commit
 logger.info(f"任务状态更新为 CODE_REVIEW: {task.id}")
async def handle_workflow_node_status_event(project_key: str, payload: dict):
 """处理工作项节点流转事件。
 用于节点流模式的工作流处理。
 """
 work_item_id = payload.get("id")
 nodes = payload.get("nodes", )
 status_change_type = payload.get("status_change_type", "")
 if not work_item_id:
 return
 logger.info(f"节点流转: {work_item_id}, 类型: {status_change_type}")
 # 节点流转事件的处理逻辑可以根据具体业务需求实现
 # 例如：检查是否到达特定节点，触发相应的自动化流程
async def handle_workitem_comment_event(project_key: str, payload: dict):
 """处理工作项评论事件。
 检测评论中的审批关键词，更新任务状态。
 """
 work_item_id = payload.get("id")
 comment = payload.get("comment", "")
 if not work_item_id or not comment:
 return
 # 解析评论内容，检查审批/驳回关键词
 comment_lower = comment.lower
 approval_keywords = ["通过", "批准", "approved", "lgtm", "ok", "👍"]
 rejection_keywords = ["驳回", "拒绝", "rejected", "需要修改", "不通过", "👎"]
 is_approved = any(kw in comment_lower for kw in approval_keywords)
 is_rejected = any(kw in comment_lower for kw in rejection_keywords)
 if not is_approved and not is_rejected:
 return
 logger.info(f"评论审批: {work_item_id}, 通过={is_approved}, 驳回={is_rejected}")
 async with get_session as db:
 result = await db.exec(
 select(Task).where(Task.work_item_id == str(work_item_id))
 )
 task = result.one_or_none
 if not task:
 return
 # 根据当前状态和评论内容更新任务
 if task.status == TaskStatus.PLAN_REVIEW:
 if is_approved:
 task.status = TaskStatus.EXECUTING
 task.human_feedback = None
 await db.commit
 logger.info(f"方案审批通过，开始执行: {task.id}")
 # TODO: 触发执行容器
 elif is_rejected:
 task.human_feedback = comment
 task.status = TaskStatus.PLANNING
 await db.commit
 logger.info(f"方案审批驳回，重新规划: {task.id}")
 # TODO: 触发重新规划
 elif task.status == TaskStatus.CODE_REVIEW:
 if is_approved:
 # 代码审批通过，等待 PR 合并
 logger.info(f"代码审批通过: {task.id}")
 elif is_rejected:
 task.human_feedback = comment
 task.status = TaskStatus.EXECUTING
 await db.commit
 logger.info(f"代码审批驳回，继续开发: {task.id}")
 # TODO: 触发继续开发
async def handle_workitem_update_event(project_key: str, payload: dict):
 """处理工作项字段修改事件。
 可用于同步工作项的标题、描述等字段变更。
 """
 work_item_id = payload.get("id")
 changed_fields = payload.get("changed_fields", ) or
 if not work_item_id:
 return
 logger.info(f"字段变更: {work_item_id}, 字段数: {len(changed_fields)}")
 # 可以根据需要同步字段变更到任务
 # 例如：更新任务标题、描述等
# === GitHub Webhook ===
@router.post("/github")
async def handle_github_webhook(
 request: Request,
 background_tasks: BackgroundTasks,
):
 """处理 GitHub Webhook 事件（PR 合并）。"""
 body = await request.body
 try:
 data = json.loads(body)
 except json.JSONDecodeError:
 raise HTTPException(status_code=400, detail="无效的 JSON 格式")
 action = data.get("action", "")
 pull_request = data.get("pull_request", {})
 if action == "closed" and pull_request.get("merged"):
 # PR 已合并
 branch = pull_request.get("head", {}).get("ref", "")
 background_tasks.add_task(
 handle_pr_merged,
 branch=branch,
 pr_url=pull_request.get("html_url", ""),
 )
 return {"status": "accepted"}
async def handle_pr_merged(branch: str, pr_url: str):
 """处理 PR 合并事件 - 更新任务为 MERGED 状态。"""
 async with get_session as db:
 # 根据分支名查找任务
 result = await db.exec(select(Task).where(Task.branch_name == branch))
 task = result.one_or_none
 if task and task.status == TaskStatus.CODE_REVIEW:
 task.status = TaskStatus.MERGED
 task.pr_url = pr_url
 await db.commit
 # 更新飞书状态
 project = await db.get(Project, task.project_id)
 if project and project.has_feishu_config:
 try:
 feishu_client = create_feishu_client_for_project(project)
 await feishu_client.transition_status(
 project_key=project.feishu_project_key or "",
 work_item_id=int(task.work_item_id),
 work_item_type="story",
 target_status_name="已完成",
 )
 logger.info(f"已更新飞书状态为已完成: {task.work_item_id}")
 except Exception as e:
 logger.error(f"更新飞书状态失败: {e}")
