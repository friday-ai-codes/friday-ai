"""Code review result card for AI code review workflow.
Provides card builder for sending review result notifications via Feishu.
Pure notification card (no interactive buttons) - review results directly
drive workflow decisions.
"""
from typing import Any
# 卡片内容最大长度（与 plan_card.py 一致，确保 < 30KB）
_MAX_SUMMARY_LENGTH = 2000
def build_code_review_card(
 approved: bool,
 issues_count: int,
 severity_breakdown: dict[str, int],
 plan_title: str,
 document_url: str,
 mr_count: int,
) -> dict[str, Any]:
 """构建代码审查结果通知卡片。
 纯通知卡片，展示审查摘要 + 文档链接。
 approved 时绿色 header，未通过时红色 header。
 Args:
 approved: 审查是否通过（无 critical issue 即通过）
 issues_count: 问题总数
 severity_breakdown: 按严重度分类统计，如 {"critical": 0, "warning": 2, "info": 1}
 plan_title: 技术方案标题
 document_url: 完整审查报告文档链接（可为空字符串）
 mr_count: 审查的 MR 数量
 Returns:
 飞书卡片 JSON 结构
 """
 template = "green" if approved else "red"
 header_title = "代码审查通过" if approved else "代码审查未通过"
 critical = severity_breakdown.get("critical", 0)
 warning = severity_breakdown.get("warning", 0)
 info = severity_breakdown.get("info", 0)
 # 审查状态标记
 status_text = "APPROVED" if approved else "REJECTED"
 summary = (
 f"**{plan_title}**\n\n"
 f"审查状态: **{status_text}**\n"
 f"审查 MR 数: {mr_count}"
 )
 # severity 统计
 severity_text = (
 f"问题总数: **{issues_count}**\n"
 f"- Critical: {critical}\n"
 f"- Warning: {warning}\n"
 f"- Info: {info}"
 )
 elements: list[dict[str, Any]] = [
 {"tag": "markdown", "content": summary},
 {"tag": "hr"},
 {"tag": "markdown", "content": severity_text},
 ]
 # 文档链接（如果有）
 if document_url:
 elements.append({"tag": "hr"})
 elements.append({
 "tag": "markdown",
 "content": f"[查看完整审查报告]({document_url})",
 })
 return {
 "config": {"wide_screen_mode": True},
 "header": {
 "title": {"tag": "plain_text", "content": header_title},
 "template": template,
 },
 "elements": elements,
 }
