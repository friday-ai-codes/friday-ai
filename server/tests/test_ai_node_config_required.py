"""Phase Plan 后端：use_custom_api 条件必填校验（228 认证混淆关闭）。
覆盖：AIAgentBaseNode.validate_config 对
``use_custom_api=True + api_base_url=""`` 返回非空 errors；
正常组合返 。
Threat mitigation:
- T- / T-：静默 fallthrough 到系统凭证（认证混淆）→ 保存前拒绝
- T-：空白字符串 ``" "`` 退化形式走 .strip 覆盖
- T-：攻击者构造 curl PATCH 绕过前端 → DRF serializer 链路拦截
"""
from __future__ import annotations
def test_use_custom_api_true_with_empty_api_base_url_returns_errors -> None:
 """C: use_custom_api=True + api_base_url="" → validate_config 返回非空 errors。"""
 from workflows.nodes.ai.base_agent import AIAgentBaseNode
 errors = AIAgentBaseNode.validate_config({
 "model": "claude-3-5-sonnet",
 "use_custom_api": True,
 "api_base_url": "",
 })
 assert len(errors) >= 1
 joined = " ".join(errors)
 assert "API Base URL" in joined or "api_base_url" in joined
def test_use_custom_api_true_with_valid_api_base_url_passes -> None:
 """D: use_custom_api=True + api_base_url="https://..." → validate_config 返 。"""
 from workflows.nodes.ai.base_agent import AIAgentBaseNode
 errors = AIAgentBaseNode.validate_config({
 "model": "claude-3-5-sonnet",
 "use_custom_api": True,
 "api_base_url": "https://api.openai.com/v1",
 })
 assert errors ==
def test_use_custom_api_false_ignores_api_base_url -> None:
 """E: use_custom_api=False + api_base_url="" → validate_config 返 （不触发 required）。"""
 from workflows.nodes.ai.base_agent import AIAgentBaseNode
 errors = AIAgentBaseNode.validate_config({
 "model": "claude-3-5-sonnet",
 "use_custom_api": False,
 "api_base_url": "",
 })
 assert errors ==
