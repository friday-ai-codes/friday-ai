"""用户模型。"""
from datetime import datetime
from uuid import uuid4
from sqlmodel import Field, SQLModel
class UserBase(SQLModel):
 """用户基础模型。"""
 username: str = Field(unique=True, index=True, min_length=3, max_length=50)
 display_name: str | None = Field(default=None, max_length=100)
 is_active: bool = Field(default=True)
 is_superuser: bool = Field(default=False)
class User(UserBase, table=True):
 """用户数据库模型。"""
 __tablename__ = "users"
 id: str = Field(default_factory=lambda: str(uuid4), primary_key=True)
 hashed_password: str = Field(min_length=1)
 created_at: datetime = Field(default_factory=datetime.utcnow)
 updated_at: datetime = Field(default_factory=datetime.utcnow)
class UserCreate(SQLModel):
 """创建用户请求模型。"""
 username: str = Field(min_length=3, max_length=50)
 password: str = Field(min_length=6, max_length=100)
 display_name: str | None = Field(default=None, max_length=100)
 is_superuser: bool = False
class UserRead(UserBase):
 """用户响应模型（不包含密码）。"""
 id: str
 created_at: datetime
 updated_at: datetime
class UserUpdate(SQLModel):
 """更新用户请求模型。"""
 display_name: str | None = None
 is_active: bool | None = None
 is_superuser: bool | None = None
class ChangePasswordRequest(SQLModel):
 """修改密码请求模型。"""
 old_password: str = Field(min_length=1)
 new_password: str = Field(min_length=6, max_length=100)
class LoginRequest(SQLModel):
 """登录请求模型。"""
 username: str
 password: str
class TokenResponse(SQLModel):
 """Token 响应模型。"""
 access_token: str
 token_type: str = "bearer"
class LoginResponse(TokenResponse):
 """登录响应模型。"""
 user: UserRead
