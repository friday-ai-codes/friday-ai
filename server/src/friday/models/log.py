"""飞书数据日志模型，用于存储 Webhook 请求和工作项详情。"""
import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import ClassVar, Optional
from sqlmodel import Field, SQLModel
def _utc_now -> datetime:
 """返回当前 UTC 时间（推荐方式）。"""
 return datetime.now(UTC)
class WebhookLogStatus(str, Enum):
 """Webhook 处理状态。"""
 ACCEPTED = "accepted" # 已接受并处理
 IGNORED = "ignored" # 已忽略（如项目未配置）
 ERROR = "error" # 处理出错
 DUPLICATE = "duplicate" # 重复事件
class WebhookLogBase(SQLModel):
 """Webhook 日志基础字段。"""
 # 事件信息
 event_uuid: Optional[str] = Field(
 default=None,
 index=True,
 description="飞书事件唯一标识（幂等 ID）",
 )
 event_type: str = Field(
 default="",
 index=True,
 description="事件类型（如 WorkitemCreateEvent）",
 )
 project_key: Optional[str] = Field(
 default=None,
 index=True,
 description="飞书项目空间 Key",
 )
 # 原始数据
 raw_request: str = Field(
 default="{}",
 description="原始请求 JSON 字符串",
 )
 # 处理结果
 status: WebhookLogStatus = Field(
 default=WebhookLogStatus.ACCEPTED,
 index=True,
 description="处理状态",
 )
 error_message: Optional[str] = Field(
 default=None,
 description="错误信息（如果有）",
 )
class WebhookLog(WebhookLogBase, table=True):
 """Webhook 日志数据库模型。"""
 __tablename__: ClassVar[str] = "webhook_logs"
 id: str = Field(
 default_factory=lambda: str(uuid.uuid4),
 primary_key=True,
 )
 project_id: Optional[str] = Field(
 default=None,
 foreign_key="projects.id",
 index=True,
 )
 created_at: datetime = Field(
 default_factory=_utc_now,
 index=True,
 )
class WebhookLogRead(WebhookLogBase):
 """Webhook 日志读取模型。"""
 id: str
 project_id: Optional[str]
 created_at: datetime
class WorkItemLogBase(SQLModel):
 """工作项日志基础字段。"""
 # 工作项信息
 work_item_id: str = Field(
 index=True,
 description="飞书工作项 ID",
 )
 work_item_type: str = Field(
 default="story",
 description="工作项类型（story、task、bug 等）",
 )
 project_key: str = Field(
 index=True,
 description="飞书项目空间 Key",
 )
 # 原始数据
 raw_response: str = Field(
 default="{}",
 description="飞书 API 响应 JSON 字符串",
 )
class WorkItemLog(WorkItemLogBase, table=True):
 """工作项日志数据库模型。"""
 __tablename__: ClassVar[str] = "work_item_logs"
 id: str = Field(
 default_factory=lambda: str(uuid.uuid4),
 primary_key=True,
 )
 project_id: str = Field(
 foreign_key="projects.id",
 index=True,
 )
 task_id: Optional[str] = Field(
 default=None,
 foreign_key="tasks.id",
 index=True,
 )
 created_at: datetime = Field(
 default_factory=_utc_now,
 index=True,
 )
class WorkItemLogRead(WorkItemLogBase):
 """工作项日志读取模型。"""
 id: str
 project_id: str
 task_id: Optional[str]
 created_at: datetime
