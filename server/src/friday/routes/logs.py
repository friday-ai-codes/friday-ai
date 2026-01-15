"""日志查看 API 路由。"""
import json
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import desc, select
from ..database import get_session
from ..models import (
 WebhookLog,
 WebhookLogRead,
 WebhookLogStatus,
 WorkItemLog,
 WorkItemLogRead,
)
router = APIRouter(prefix="/api/logs", tags=["logs"])
class WebhookLogListResponse(BaseModel):
 """Webhook 日志列表响应。"""
 items: list[WebhookLogRead]
 total: int
class WebhookLogDetailResponse(WebhookLogRead):
 """Webhook 日志详情响应（包含解析后的 JSON）。"""
 raw_request_parsed: Optional[dict] = None
class WorkItemLogListResponse(BaseModel):
 """工作项日志列表响应。"""
 items: list[WorkItemLogRead]
 total: int
class WorkItemLogDetailResponse(WorkItemLogRead):
 """工作项日志详情响应（包含解析后的 JSON）。"""
 raw_response_parsed: Optional[dict] = None
@router.get("/webhooks", response_model=WebhookLogListResponse)
async def list_webhook_logs(
 project_id: Optional[str] = Query(None, description="按项目 ID 过滤"),
 event_type: Optional[str] = Query(None, description="按事件类型过滤"),
 status: Optional[WebhookLogStatus] = Query(None, description="按处理状态过滤"),
 start_date: Optional[datetime] = Query(None, description="开始时间"),
 end_date: Optional[datetime] = Query(None, description="结束时间"),
 limit: int = Query(50, ge=1, le=100, description="每页数量"),
 offset: int = Query(0, ge=0, description="偏移量"),
):
 """获取 Webhook 日志列表。
 支持按项目、事件类型、状态、时间范围过滤。
 """
 async with get_session as db:
 # 构建查询
 query = select(WebhookLog)
 if project_id:
 query = query.where(WebhookLog.project_id == project_id)
 if event_type:
 query = query.where(WebhookLog.event_type == event_type)
 if status:
 query = query.where(WebhookLog.status == status)
 if start_date:
 query = query.where(WebhookLog.created_at >= start_date)
 if end_date:
 query = query.where(WebhookLog.created_at <= end_date)
 # 获取总数
 count_query = select(WebhookLog)
 if project_id:
 count_query = count_query.where(WebhookLog.project_id == project_id)
 if event_type:
 count_query = count_query.where(WebhookLog.event_type == event_type)
 if status:
 count_query = count_query.where(WebhookLog.status == status)
 if start_date:
 count_query = count_query.where(WebhookLog.created_at >= start_date)
 if end_date:
 count_query = count_query.where(WebhookLog.created_at <= end_date)
 result = await db.exec(count_query)
 total = len(result.all)
 # 获取分页数据
 query = query.order_by(desc(WebhookLog.created_at)).offset(offset).limit(limit)
 result = await db.exec(query)
 logs = result.all
 items = [
 WebhookLogRead(
 id=log.id,
 event_uuid=log.event_uuid,
 event_type=log.event_type,
 project_key=log.project_key,
 raw_request=log.raw_request,
 status=log.status,
 error_message=log.error_message,
 project_id=log.project_id,
 created_at=log.created_at,
 )
 for log in logs
 ]
 return WebhookLogListResponse(items=items, total=total)
@router.get("/webhooks/{log_id}", response_model=WebhookLogDetailResponse)
async def get_webhook_log(log_id: str):
 """获取 Webhook 日志详情。
 返回完整的日志记录，包含解析后的原始 JSON。
 """
 async with get_session as db:
 result = await db.exec(select(WebhookLog).where(WebhookLog.id == log_id))
 log = result.one_or_none
 if not log:
 raise HTTPException(status_code=404, detail="日志不存在")
 # 解析原始 JSON
 raw_request_parsed = None
 try:
 raw_request_parsed = json.loads(log.raw_request)
 except (json.JSONDecodeError, TypeError):
 pass
 return WebhookLogDetailResponse(
 id=log.id,
 event_uuid=log.event_uuid,
 event_type=log.event_type,
 project_key=log.project_key,
 raw_request=log.raw_request,
 status=log.status,
 error_message=log.error_message,
 project_id=log.project_id,
 created_at=log.created_at,
 raw_request_parsed=raw_request_parsed,
 )
@router.get("/work-items", response_model=WorkItemLogListResponse)
async def list_work_item_logs(
 project_id: Optional[str] = Query(None, description="按项目 ID 过滤"),
 task_id: Optional[str] = Query(None, description="按任务 ID 过滤"),
 work_item_id: Optional[str] = Query(None, description="按工作项 ID 过滤"),
 start_date: Optional[datetime] = Query(None, description="开始时间"),
 end_date: Optional[datetime] = Query(None, description="结束时间"),
 limit: int = Query(50, ge=1, le=100, description="每页数量"),
 offset: int = Query(0, ge=0, description="偏移量"),
):
 """获取工作项日志列表。
 支持按项目、任务、工作项 ID、时间范围过滤。
 """
 async with get_session as db:
 # 构建查询
 query = select(WorkItemLog)
 if project_id:
 query = query.where(WorkItemLog.project_id == project_id)
 if task_id:
 query = query.where(WorkItemLog.task_id == task_id)
 if work_item_id:
 query = query.where(WorkItemLog.work_item_id == work_item_id)
 if start_date:
 query = query.where(WorkItemLog.created_at >= start_date)
 if end_date:
 query = query.where(WorkItemLog.created_at <= end_date)
 # 获取总数
 count_query = select(WorkItemLog)
 if project_id:
 count_query = count_query.where(WorkItemLog.project_id == project_id)
 if task_id:
 count_query = count_query.where(WorkItemLog.task_id == task_id)
 if work_item_id:
 count_query = count_query.where(WorkItemLog.work_item_id == work_item_id)
 if start_date:
 count_query = count_query.where(WorkItemLog.created_at >= start_date)
 if end_date:
 count_query = count_query.where(WorkItemLog.created_at <= end_date)
 result = await db.exec(count_query)
 total = len(result.all)
 # 获取分页数据
 query = query.order_by(desc(WorkItemLog.created_at)).offset(offset).limit(limit)
 result = await db.exec(query)
 logs = result.all
 items = [
 WorkItemLogRead(
 id=log.id,
 work_item_id=log.work_item_id,
 work_item_type=log.work_item_type,
 project_key=log.project_key,
 raw_response=log.raw_response,
 project_id=log.project_id,
 task_id=log.task_id,
 created_at=log.created_at,
 )
 for log in logs
 ]
 return WorkItemLogListResponse(items=items, total=total)
@router.get("/work-items/{log_id}", response_model=WorkItemLogDetailResponse)
async def get_work_item_log(log_id: str):
 """获取工作项日志详情。
 返回完整的日志记录，包含解析后的原始 JSON。
 """
 async with get_session as db:
 result = await db.exec(select(WorkItemLog).where(WorkItemLog.id == log_id))
 log = result.one_or_none
 if not log:
 raise HTTPException(status_code=404, detail="日志不存在")
 # 解析原始 JSON
 raw_response_parsed = None
 try:
 raw_response_parsed = json.loads(log.raw_response)
 except (json.JSONDecodeError, TypeError):
 pass
 return WorkItemLogDetailResponse(
 id=log.id,
 work_item_id=log.work_item_id,
 work_item_type=log.work_item_type,
 project_key=log.project_key,
 raw_response=log.raw_response,
 project_id=log.project_id,
 task_id=log.task_id,
 created_at=log.created_at,
 raw_response_parsed=raw_response_parsed,
 )
