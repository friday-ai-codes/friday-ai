"""任务失败通知卡片（Phase）。
简洁文本卡片，包含任务名 + 失败原因 + 重试次数。
"""
from typing import Any
def build_failure_notification_card(
 task_type: str,
 error_message: str,
 retry_count: int = 0,
 repository_name: str = "",
 session_id: str = "",
) -> dict[str, Any]:
 """构建任务失败通知卡片。
 Args:
 task_type: 任务类型（coding/explore/ask/plan）
 error_message: 失败原因
 retry_count: 已重试次数
 repository_name: 仓库名（可选）
 session_id: 会话 ID（可选）
 Returns:
 飞书卡片 JSON 结构
 """
 task_type_display = {
 "coding": "编码任务",
 "explore": "仓库探索",
 "ask": "问答任务",
 "plan": "方案生成",
 }.get(task_type, task_type)
 elements =
 # 任务信息
 if repository_name:
 elements.append({
 "tag": "markdown",
 "content": f"**{task_type_display}** - {repository_name}",
 })
 else:
 elements.append({
 "tag": "markdown",
 "content": f"**{task_type_display}**",
 })
 elements.append({"tag": "hr"})
 # 失败原因
 error_display = error_message[:300] if len(error_message) > 300 else error_message
 elements.append({
 "tag": "markdown",
 "content": f"**失败原因**\n```\n{error_display}\n```",
 })
 # 重试信息
 if retry_count > 0:
 elements.append({
 "tag": "markdown",
 "content": f"已自动重试 {retry_count} 次",
 })
 return {
 "config": {"wide_screen_mode": True},
 "header": {
 "title": {"tag": "plain_text", "content": "任务失败"},
 "template": "red",
 },
 "elements": elements,
 }
