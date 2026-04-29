""" / /: CRUD + toggle + refresh-models 行为测试 + W4 脱敏链路断言。
覆盖契约：
-：Pydantic dispatch 校验 + Read Serializer 不回显 encrypted_config
-：scope=system / scope=project 过滤
-：toggle-active 切 is_active + aresolve 下次解析跳过
-：refresh-models 写回 available_models + 上游异常脱敏链路
- W4（T-）：mock 上游异常含 `sk-ant-realkey...` 时，HTTP body + DB 字段
 双路径均不含明文且含脱敏标记（***REDACTED***）
测试路径：DRF APIClient + force_authenticate 同步路径
（与既有 tests/test_provider_credential_permissions 完全一致）。
DRF Router 把 POST 同步分派到 create，不经 async perform_acreate；
toggle-active / refresh-models 是 adrf @action 的 async 方法，APIClient
通过 asgiref.sync 兼容同步调用。
"""
from __future__ import annotations
from unittest.mock import patch
import pytest
from rest_framework.test import APIClient
# ======================================================================
# helper
# ======================================================================
def _client_for(user) -> APIClient:
 """force_authenticate 注入用户（与 test_provider_credential_permissions 同模式）。"""
 client = APIClient
 client.force_authenticate(user=user)
 return client
# ======================================================================
#：Create Serializer Pydantic dispatch 校验
# ======================================================================
@pytest.mark.django_db
def test_create_credential_pydantic_dispatch_invalid_anthropic(
 system_admin_user,
) -> None:
 """anthropic credential_schema 校验失败（api_key 缺失）应返 400。
 AnthropicCredentialSchema 把 api_key 标记为 Required SecretStr，
 传入空 config 会触发 Pydantic missing 错误 → DRF 400 ValidationError。
 """
 client = _client_for(system_admin_user)
 resp = client.post(
 "/api/providers/credentials/",
 data={
 "provider_type": "anthropic",
 "name": "bad-anth",
 "scope": "system",
 "default_model": "claude-3-5-sonnet-20241022",
 "config": {}, # 缺 api_key → Pydantic missing
 },
 format="json",
 )
 assert resp.status_code == 400, f"应 400 got {resp.status_code}: {resp.content!r}"
 # Pydantic ConfigDict(hide_input_in_errors=True) 保证错误结构不回显输入；
 # DRF ValidationError 可能把字段错误挂到 'config' 或归到 'detail'（取决于 serializer
 # 层抛 ValidationError 的参数结构）—— 只要 400 且错误消息提及 api_key required 即可。
 body_text = resp.content.decode("utf-8", errors="replace")
 assert "api_key" in body_text.lower or "field required" in body_text.lower, (
 f"错误消息应提示 api_key 字段缺失，实际: {body_text!r}"
 )
@pytest.mark.django_db
def test_create_credential_pydantic_dispatch_valid_anthropic(
 system_admin_user,
) -> None:
 """anthropic schema 校验通过返 201；Read Serializer 按写权限分级回显 config。
 Pitfall 3 重新校准（admin/providers 编辑表单 API key/base_url 回显需求）：
 - 写权限用户（此处 superuser）GET retrieve 时 config 含 base_url + api_key 明文，
 与 Vue 表单 `initialValues.config` 直接对接，编辑时可以查看已配置值；
 - 非写权限用户仍只能拿 api_key_last4，明文 api_key 完全不出现（覆盖见
 `test_retrieve_system_credential_non_superuser_hides_secret_plaintext`）。
 """
 client = _client_for(system_admin_user)
 resp = client.post(
 "/api/providers/credentials/",
 data={
 "provider_type": "anthropic",
 "name": "good-anth",
 "scope": "system",
 "default_model": "claude-3-5-sonnet-20241022",
 "config": {
 "api_key": "sk-test-placeholder",
 "base_url": "https://api.anthropic.com",
 },
 },
 format="json",
 )
 assert resp.status_code == 201, f"应 201 got {resp.status_code}: {resp.content!r}"
 body = resp.json
 # POST 201 仍走 CreateSerializer，config write_only / encrypted_config 不回显
 assert "encrypted_config" not in body, "encrypted_config 不应回显"
 assert "config" not in body, "POST 201 (Create Serializer) 仍不应回显 config"
 # 基础字段（POST 201 使用 CreateSerializer 回显，Read 派生字段 has_api_key /
 # api_key_last4 / config 仅在 GET retrieve 时由 ProviderCredentialSerializer 产生）
 assert body.get("provider_type") == "anthropic"
 assert body.get("scope") == "system"
 # POST 响应 body 不应直接复读输入 api_key
 assert b"sk-test-placeholder" not in resp.content, (
 "POST 201 响应不应回显 api_key"
 )
 # GET retrieve 验证 Read Serializer 契约
 # Create Serializer 不回显 id，从 DB 按 name 读取刚创建的凭证
 from system.models import ProviderCredential
 cred_id = ProviderCredential.objects.get(name="good-anth").id
 retrieve_resp = client.get(f"/api/providers/credentials/{cred_id}/")
 assert retrieve_resp.status_code == 200, retrieve_resp.content
 retrieve_body = retrieve_resp.json
 # 派生字段：has_api_key + api_key_last4 末 4 位脱敏（任意可读用户均可见）
 assert retrieve_body.get("has_api_key") is True, (
 f"retrieve 应回显 has_api_key=True: {retrieve_body!r}"
 )
 assert retrieve_body.get("api_key_last4", "").endswith("cdef"), (
 f"api_key_last4 应末 4 位匹配，实际: {retrieve_body.get('api_key_last4')!r}"
 )
 assert "encrypted_config" not in retrieve_body, "retrieve 不应回显 encrypted_config"
 # 写权限用户（superuser）retrieve 时 config 字段含 base_url + api_key 明文
 config = retrieve_body.get("config")
 assert isinstance(config, dict), f"retrieve 应回显 config dict: {retrieve_body!r}"
 assert config.get("base_url") == "https://api.anthropic.com", (
 f"非密字段 base_url 必须回显: {config!r}"
 )
 assert config.get("api_key") == "sk-test-placeholder", (
 f"superuser 写权限用户 api_key 明文应回显: {config!r}"
 )
# ======================================================================
# Pitfall 3 重新校准：config 按写权限分级回显矩阵
# ======================================================================
@pytest.mark.django_db
def test_retrieve_system_credential_non_superuser_hides_secret_plaintext(
 project_a_member_user,
 system_default_anthropic_credential,
) -> None:
 """非 superuser 读 system 级凭证：config 含 base_url 但绝不含 api_key 明文。
 `_user_can_reveal_secrets` 仅 superuser 满足 system 写权限分支，普通认证用户
 （即使是某项目 MEMBER）GET system 凭证仅可拿非密字段 + api_key_last4。
 """
 client = _client_for(project_a_member_user)
 resp = client.get(
 f"/api/providers/credentials/{system_default_anthropic_credential.id}/"
 )
 assert resp.status_code == 200, resp.content
 body = resp.json
 # 非密字段对所有可读用户回显
 config = body.get("config")
 assert isinstance(config, dict), f"retrieve 应有 config dict: {body!r}"
 assert config.get("base_url") == "https://api.anthropic.com", (
 f"base_url 非密字段必须回显: {config!r}"
 )
 # 严格秘密字段：不在 config dict 中出现 + 不在响应原文出现
 assert "api_key" not in config, (
 f"非写权限用户 config 不得含 api_key key: {config!r}"
 )
 assert b"sk-test-placeholder" not in resp.content, (
 f"明文 api_key 泄漏到非写权限用户的 retrieve 响应:\n{resp.content!r}"
 )
 # 派生字段：仍可见 has_api_key=True + last4
 assert body.get("has_api_key") is True
 assert body.get("api_key_last4", "").endswith("ting"), body.get("api_key_last4")
@pytest.mark.django_db
def test_retrieve_project_credential_member_reveals_secret_plaintext(
 project_a_member_user,
 project_a_anthropic_credential,
) -> None:
 """项目 MEMBER 读项目凭证：config 含 base_url + api_key 明文（写权限分支）。
 `_user_can_reveal_secrets` project 分支与 ProviderCredentialPermission 写分支
 一致：MEMBER+ 即拥有写权限，可看到完整 config 用于编辑表单回显。
 """
 client = _client_for(project_a_member_user)
 resp = client.get(
 f"/api/providers/credentials/{project_a_anthropic_credential.id}/"
 )
 assert resp.status_code == 200, resp.content
 body = resp.json
 config = body.get("config")
 assert isinstance(config, dict), f"retrieve 应有 config dict: {body!r}"
 # MEMBER 看得见明文 api_key，与编辑权限对齐（能改即能看）
 assert "api_key" in config, (
 f"MEMBER 写权限用户 config 应含 api_key key: {config!r}"
 )
 assert isinstance(config.get("api_key"), str) and config["api_key"], (
 f"api_key 应为非空字符串: {config!r}"
 )
@pytest.mark.django_db
def test_retrieve_project_credential_viewer_hides_secret_plaintext(
 project_a_viewer_user,
 project_a_anthropic_credential,
) -> None:
 """项目 VIEWER 读项目凭证：config 含 base_url 但不含 api_key 明文（无写权限）。
 `_user_can_reveal_secrets` project 分支要求 MEMBER+，VIEWER 不达标 → 仅可读
 非密字段 + api_key_last4，与列表卡片展示口径完全一致。
 """
 client = _client_for(project_a_viewer_user)
 resp = client.get(
 f"/api/providers/credentials/{project_a_anthropic_credential.id}/"
 )
 assert resp.status_code == 200, resp.content
 body = resp.json
 config = body.get("config")
 assert isinstance(config, dict), f"retrieve 应有 config dict: {body!r}"
 # 非密字段仍回显
 assert "base_url" in config, f"VIEWER 仍可见 base_url: {config!r}"
 # 秘密字段必须缺席
 assert "api_key" not in config, (
 f"VIEWER 无写权限不得看到 api_key 明文: {config!r}"
 )
# ======================================================================
#：toggle-active + aresolve_or_error 跳过验证
# ======================================================================
@pytest.mark.django_db(transaction=True)
def test_toggle_active_skips_in_aresolve(
 system_admin_user, system_default_anthropic_credential
) -> None:
 """PATCH toggle-active 反转 is_active；aresolve_or_error 下次解析不再命中该凭证。
 Phase `_fetch_credential_by_id / _fetch_system_default_credential` 的
 queryset 均带 `filter(is_active=True)`，is_active=false 时系统级 anthropic
 解析应返回 ProviderMissingError（测试库里除本凭证外没有其他 system-anthropic）。
 使用 `transaction=True`：aresolve_or_error 内部经 asgiref.sync_to_async 访问
 DB 时需跨线程共享 connection；默认 `@pytest.mark.django_db` 单事务封装
 会导致 SQLite 'database table is locked' 错误。transaction=True 下每次
 数据库操作走真实事务，容许跨线程访问。
 """
 from asgiref.sync import async_to_sync
 from services.provider_config import (
 ProviderConfigService,
 ProviderMissingError,
 ProviderType,
 )
 client = _client_for(system_admin_user)
 resp = client.patch(
 f"/api/providers/credentials/{system_default_anthropic_credential.id}/toggle-active/",
 )
 assert resp.status_code == 200, f"toggle-active 应 200: {resp.content!r}"
 assert resp.json["is_active"] is False
 # DB 回读确认
 system_default_anthropic_credential.refresh_from_db
 assert system_default_anthropic_credential.is_active is False
 # aresolve_or_error（ Result 模式）应返回 ProviderMissingError；
 # 没有其他 system-scope anthropic 凭证可用，且 node_config 强制 anthropic 类型。
 result = async_to_sync(ProviderConfigService.aresolve_or_error)(
 node_config={"provider_type": ProviderType.ANTHROPIC.value},
 conversation=None,
 project=None,
 )
 assert isinstance(result, ProviderMissingError), (
 f"期望 ProviderMissingError，实际: {type(result).__name__} value={result!r}"
 )
# ======================================================================
#：refresh-models 写回 available_models（成功路径）
# ======================================================================
@pytest.mark.django_db
def test_refresh_models_writes_available(
 system_admin_user, system_default_anthropic_credential
) -> None:
 """mock fetch_models_for_credential 返回 list → POST refresh-models →
 HTTP 响应 + DB 字段 available_models 均被写入。
 """
 from system.models import ProviderCredential
 client = _client_for(system_admin_user)
 fake_list = [
 {"id": "claude-opus-4-7", "display_name": "Claude Opus 4.7"},
 {"id": "claude-sonnet-4", "display_name": "Claude Sonnet 4"},
 ]
 async def _fake_fetch(cred):
 return fake_list
 with patch(
 "services.provider_health.fetch_models_for_credential",
 new=_fake_fetch,
 ):
 resp = client.post(
 f"/api/providers/credentials/{system_default_anthropic_credential.id}/refresh-models/",
 )
 assert resp.status_code == 200, f"应 200: {resp.content!r}"
 assert resp.json["available_models"] == fake_list
 # DB 回读确认
 cred = ProviderCredential.objects.get(id=system_default_anthropic_credential.id)
 assert cred.available_models == fake_list
# ======================================================================
# W4 修复：refresh-models 上游异常脱敏链路（T- 核心）
# ======================================================================
@pytest.mark.django_db
def test_refresh_models_upstream_error_redacted(
 system_admin_user, system_default_anthropic_credential
) -> None:
 """W4 + T-：上游错误经 redact_secrets_in_text 脱敏后入库 + 不泄漏到响应。
 断言链：
 1. fetch_models_for_credential 被 mock 替换为抛含 sk-ant-realkey... 的异常
 2. view 层 except 分支将异常 message 脱敏后写入 credential.last_health_check_error
 3. HTTP 响应 body 不含明文 sk-ant-realkey...
 4. DB 回读 last_health_check_error 不含明文，且含脱敏标记 ***REDACTED***
 5. DB 字段长度 ≤ ERROR_TRUNCATE_LIMIT（500 字符契约）
 """
 from system.models import ProviderCredential
 client = _client_for(system_admin_user)
 leaking_key = "sk-test-placeholder"
 upstream_exc_msg = (
 f"401 Unauthorized: invalid api_key={leaking_key} at /v1/models"
 )
 async def _raise_with_key(cred):
 raise RuntimeError(upstream_exc_msg)
 with patch(
 "services.provider_health.fetch_models_for_credential",
 new=_raise_with_key,
 ):
 resp = client.post(
 f"/api/providers/credentials/{system_default_anthropic_credential.id}/refresh-models/",
 )
 # view 层兜底异常分支：返 502（契约允许 200 或 502；实际用 502 语义更清晰）
 assert resp.status_code in (200, 502, 500), (
 f"status={resp.status_code} body={resp.content!r}"
 )
 # ==== 断言 1: HTTP 响应 body 不含明文 api_key ====
 assert leaking_key.encode not in resp.content, (
 f"明文 api_key 泄漏到 HTTP 响应:\n{resp.content!r}"
 )
 assert leaking_key not in resp.content.decode("utf-8", errors="replace"), (
 "明文 api_key 泄漏到 HTTP 响应（字符串层）"
 )
 # ==== 断言 2: DB 回读 last_health_check_error 不含明文 ====
 cred = ProviderCredential.objects.get(id=system_default_anthropic_credential.id)
 err_text = cred.last_health_check_error or ""
 assert leaking_key not in err_text, (
 f"明文 api_key 泄漏到 DB.last_health_check_error:\n{err_text!r}"
 )
 # ==== 断言 3: DB 字段含脱敏标记 ====
 assert ("***REDACTED***" in err_text) or ("sk-ant-***" in err_text), (
 f"last_health_check_error 缺脱敏占位，实际: {err_text!r}; "
 f"预期含 '***REDACTED***' 或 'sk-ant-***'（common.logging.redact_secrets_in_text 契约）"
 )
 # ==== 断言 4: DB 字段长度 ≤ 500（ERROR_TRUNCATE_LIMIT 契约）====
 assert len(err_text) <= 500, (
 f"last_health_check_error 长度 {len(err_text)} > 500 违反截断契约"
 )
# ======================================================================
# list/retrieve scope 过滤
# ======================================================================
@pytest.mark.django_db
def test_list_scope_filter_system(
 system_admin_user,
 system_default_anthropic_credential,
 project_a_anthropic_credential,
) -> None:
 """?scope=system 只返回 system 凭证，不含 project 凭证。"""
 client = _client_for(system_admin_user)
 resp = client.get("/api/providers/credentials/?scope=system")
 assert resp.status_code == 200, resp.content
 payload = resp.json
 items = payload if isinstance(payload, list) else payload.get("results", )
 ids = {item["id"] for item in items}
 assert str(system_default_anthropic_credential.id) in ids
 assert str(project_a_anthropic_credential.id) not in ids
@pytest.mark.django_db
def test_list_scope_filter_project(
 system_admin_user,
 system_default_anthropic_credential,
 project_a_anthropic_credential,
 project_a,
) -> None:
 """?scope=project&project_id=<uuid> 只返回该项目凭证，不含 system 凭证。"""
 client = _client_for(system_admin_user)
 resp = client.get(
 f"/api/providers/credentials/?scope=project&project_id={project_a.id}"
 )
 assert resp.status_code == 200, resp.content
 payload = resp.json
 items = payload if isinstance(payload, list) else payload.get("results", )
 ids = {item["id"] for item in items}
 assert str(project_a_anthropic_credential.id) in ids
 assert str(system_default_anthropic_credential.id) not in ids
# ======================================================================
# UAT 第 3 项 hotfix follow-up：scope=any 联合查询
# ======================================================================
@pytest.mark.django_db
def test_list_scope_filter_any(
 system_admin_user,
 system_default_anthropic_credential,
 project_a_anthropic_credential,
 project_a,
) -> None:
 """?scope=any&project_id=<uuid> 返回 system 凭证 ∪ 该项目 project 凭证。
 UAT 第 3 项 hotfix follow-up：chat 路径
 ChatInput 底部 model-selector 需要 system + 当前项目两 scope 全集。
 """
 client = _client_for(system_admin_user)
 resp = client.get(
 f"/api/providers/credentials/?scope=any&project_id={project_a.id}"
 )
 assert resp.status_code == 200, resp.content
 payload = resp.json
 items = payload if isinstance(payload, list) else payload.get("results", )
 ids = {item["id"] for item in items}
 assert str(system_default_anthropic_credential.id) in ids
 assert str(project_a_anthropic_credential.id) in ids
@pytest.mark.django_db
def test_list_scope_filter_any_without_project_id_returns_system_only(
 system_admin_user,
 system_default_anthropic_credential,
 project_a_anthropic_credential,
) -> None:
 """?scope=any 不带 project_id 时仅返回 system 凭证（防越权 / 默认收敛语义）。"""
 client = _client_for(system_admin_user)
 resp = client.get("/api/providers/credentials/?scope=any")
 assert resp.status_code == 200, resp.content
 payload = resp.json
 items = payload if isinstance(payload, list) else payload.get("results", )
 ids = {item["id"] for item in items}
 assert str(system_default_anthropic_credential.id) in ids
 assert str(project_a_anthropic_credential.id) not in ids
@pytest.mark.django_db
def test_list_scope_filter_system_with_project_id_ignored(
 system_admin_user,
 system_default_anthropic_credential,
 project_a_anthropic_credential,
 project_a,
) -> None:
 """W2 回归保护：?scope=system&project_id=<uuid> 仅返 system 凭证（project_id 被忽略）。
 重构前：旧代码 `if project_id: qs.filter(scope='project', scope_id=project_id)`
 在 scope='system' 之后执行 → 二次 filter 抹掉所有 system 行（导致空结果）。
 重构后：scope=system 进入 elif 分支，project_id 仅在 scope=project 子句内消费 →
 对 scope=system 调用方零回归，project_id 被静默忽略。
 本用例锁定「scope 优先 + project_id 在 scope=system 下被忽略」语义。
 """
 client = _client_for(system_admin_user)
 resp = client.get(
 f"/api/providers/credentials/?scope=system&project_id={project_a.id}"
 )
 assert resp.status_code == 200, resp.content
 payload = resp.json
 items = payload if isinstance(payload, list) else payload.get("results", )
 ids = {item["id"] for item in items}
 assert str(system_default_anthropic_credential.id) in ids, (
 "scope=system 应返回 system 凭证（project_id 应被忽略，不应抹掉 system 结果）"
 )
 assert str(project_a_anthropic_credential.id) not in ids, (
 "scope=system 不应返回 project 凭证"
 )
@pytest.mark.django_db
def test_list_scope_filter_any_non_superuser_excludes_non_member_project(
 project_a_member_user,
 project_b,
 project_b_openai_credential,
 system_default_anthropic_credential,
) -> None:
 """W3 安全防护：非超管用户 ?scope=any&project_id=<非成员项目> 不应返回该项目凭证。
 层 2 queryset 上层强制 `Q(scope='system') | Q(scope='project', scope_id__in=user_project_ids)`，
 新增 scope=any 分支必须与上层 `__in=user_project_ids` 串联生效（不绕过）。
 本用例锁定「即使前端构造越权 query param，后端 queryset 上层兜底拦截」契约。
 Fixtures：
 - `project_a_member_user`：项目 A MEMBER 角色（非超管）
 - `project_b`：非成员项目
 - `project_b_openai_credential`：非成员项目 B 的凭证（应被层 2 兜底过滤）
 - `system_default_anthropic_credential`：system 凭证（应仍可见）
 """
 client = _client_for(project_a_member_user)
 resp = client.get(
 f"/api/providers/credentials/?scope=any&project_id={project_b.id}"
 )
 assert resp.status_code == 200, resp.content
 payload = resp.json
 items = payload if isinstance(payload, list) else payload.get("results", )
 ids = {item["id"] for item in items}
 assert str(project_b_openai_credential.id) not in ids, (
 "非超管用户构造越权 ?project_id=<非成员项目> 不应返回该项目凭证"
 )
 assert str(system_default_anthropic_credential.id) in ids, (
 "system 凭证应仍可见（scope=any 分支与层 2 上层过滤串联，system 部分照常返回）"
 )
