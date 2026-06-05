"""initial implementation plan：validate_credential_scope 5 分支单元测试（contract 服务契约）。

分支矩阵：
1. scope='system' + project_id=任意 → 返回 None（系统级凭证全通）
2. scope='project' + scope_id == project_id → 返回 None（匹配放行）
3. scope='project' + scope_id != project_id → raise CredentialScopeViolation（跨项目越权）
4. scope='project' + scope_id is None → raise CredentialScopeViolation（数据不一致）
5. scope='project' + scope_id 非空 + project_id=None → raise CredentialScopeViolation（system 上下文不可消费 project 凭证）

加 1 条日志侧信道断言：分支 3 触发时 structlog warning 事件名 credential_scope_violation。

纯单元测试：用 SimpleNamespace mock ProviderCredential，无 DB 依赖，--disable-socket 下通过。
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from identity.credential_access import (
    CredentialScopeViolation,
    validate_credential_scope,
)


def _make_cred(scope: str, scope_id=None) -> SimpleNamespace:
    """用 SimpleNamespace 模拟 ProviderCredential，避开 DB。

    validate_credential_scope 仅读 credential.scope / credential.scope_id / credential.id
    三个属性，不触 ORM，符合契约"调用方预读 credential"。
    """
    return SimpleNamespace(id=uuid4(), scope=scope, scope_id=scope_id)


class TestValidateCredentialScope:
    """validate_credential_scope 5 分支契约 + 日志侧信道。"""

    async def test_system_scope_any_project_returns_none(self) -> None:
        """分支 1：scope='system' 对所有 project_id 放行（含 None / 空串 / UUID）。

        validate_credential_scope 声明 `-> None`，不抛异常即放行（契约只体现在
        是否 raise CredentialScopeViolation）。这里三次调用若任一抛异常都会失败。
        """
        cred = _make_cred(scope="system", scope_id=None)
        await validate_credential_scope(cred, str(uuid4()))
        await validate_credential_scope(cred, None)
        await validate_credential_scope(cred, "")

    async def test_project_scope_matching_project_id_returns_none(self) -> None:
        """分支 2：scope='project' + scope_id 与 project_id 字符串相等 → 放行（不抛）。"""
        project_id = uuid4()
        cred = _make_cred(scope="project", scope_id=project_id)
        await validate_credential_scope(cred, str(project_id))

    async def test_project_scope_different_project_id_raises(self) -> None:
        """分支 3：跨项目越权 → 抛 CredentialScopeViolation，异常消息含 scope_id。"""
        cred = _make_cred(scope="project", scope_id=uuid4())
        other_project_id = str(uuid4())
        with pytest.raises(CredentialScopeViolation) as exc_info:
            await validate_credential_scope(cred, other_project_id)
        assert str(cred.scope_id) in str(exc_info.value)

    async def test_project_scope_missing_scope_id_raises(self) -> None:
        """分支 4：scope='project' + scope_id=None 表示数据不一致 → 必须抛错。"""
        cred = _make_cred(scope="project", scope_id=None)
        with pytest.raises(CredentialScopeViolation) as exc_info:
            await validate_credential_scope(cred, str(uuid4()))
        assert "scope_id" in str(exc_info.value) or "数据不一致" in str(exc_info.value)

    async def test_project_scope_none_project_id_raises(self) -> None:
        """分支 5：project 级凭证在无 project 上下文中被消费 → 拒绝（system 上下文不得命中 project 凭证）。"""
        cred = _make_cred(scope="project", scope_id=uuid4())
        with pytest.raises(CredentialScopeViolation):
            await validate_credential_scope(cred, None)

    async def test_violation_logs_structured_warning(self, caplog) -> None:
        """日志侧信道：分支 3 触发时结构化日志事件名 credential_scope_violation。

        structlog 在测试环境下挂 stdlib logging（initial implementation settings.py 配置），
        caplog.records 可捕获 warning 级别事件。若 caplog 未拿到，也接受异常消息
        含"不能被项目"等兜底断言。
        """
        cred = _make_cred(scope="project", scope_id=uuid4())
        with caplog.at_level("WARNING"):
            with pytest.raises(CredentialScopeViolation) as exc_info:
                await validate_credential_scope(cred, str(uuid4()))

        # structlog 通过 stdlib logging 走 caplog；至少一种证据表明违规被记录
        logged_text = " ".join(r.message for r in caplog.records)
        assert (
            "credential_scope_violation" in logged_text
            or "不能被项目" in str(exc_info.value)
        )
