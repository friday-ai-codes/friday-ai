"""Provider 凭证访问校验服务（Phase / + Phase 共用）。
 决策：抽出 Phase `base_agent.py` / `prompt.py` / `variable_extractor.py`
三处内联的 scope 校验逻辑为共享服务函数；ViewSet `perform_acreate/perform_aupdate`
与节点端 runner 共用同一实现，避免后续维护漂移。
本模块仅提供纯函数 + 异常类，不做 I/O：credential 由调用方预读,project_id 由
调用方上下文提供；模块 import 路径保持最小，避免与 system.models 顶层循环依赖
（通过 TYPE_CHECKING 标注形参类型）。
"""
from __future__ import annotations
from typing import TYPE_CHECKING
import structlog
if TYPE_CHECKING:
 from system.models import ProviderCredential
logger = structlog.get_logger(__name__)
class CredentialScopeViolation(Exception):
 """凭证 scope 校验失败（跨项目越权或数据不一致）。
 ViewSet / Runner 捕获后按场景转 DRF PermissionDenied（API 层）或
 ValueError（节点端沿用 Phase 既有语义，Phase 迁移）。
 """
async def validate_credential_scope(
 credential: "ProviderCredential",
 project_id: str | None,
) -> None:
 """校验凭证 scope 与请求 project_id 的一致性。
 规则：
 - scope='system' → 直接放行（系统级凭证对所有项目可用）
 - scope='project' 且 scope_id 为 None → 数据不一致，抛 CredentialScopeViolation
 - scope='project' 且 scope_id 与 project_id 不匹配 → 跨项目越权，抛 CredentialScopeViolation
 Args:
 credential: 已加载的 ProviderCredential 实例
 project_id: 当前请求上下文中的 project UUID 字符串；None 表示无项目上下文
 Raises:
 CredentialScopeViolation: scope 约束不满足时抛出，调用方负责转 4xx 响应
 """
 if credential.scope != "project":
 # 系统级凭证无需 project 比对
 return
 if credential.scope_id is None:
 raise CredentialScopeViolation(
 f"project 级凭证 {credential.id} 缺少 scope_id，数据不一致"
 )
 target = str(project_id) if project_id else ""
 if str(credential.scope_id) != target:
 logger.warning(
 "credential_scope_violation",
 credential_id=str(credential.id),
 credential_scope_id=str(credential.scope_id),
 requested_project_id=target,
 )
 raise CredentialScopeViolation(
 f"凭证 {credential.id} 属于项目 {credential.scope_id}，"
 f"不能被项目 {target or 'unknown'} 使用"
 )
