"""群聊提问卡片模板。
构建群聊提问交互卡片和已回复状态卡片。
与 question_card.py（Agent 提问）不同，此模板用于群聊节点提问，
action value 包含 execution_id + node_id 用于工作流回调路由。
"""
from typing import Any
def build_chat_question_card(
 question: str,
 execution_id: str,
 node_id: str,
 options: list[str] | None = None,
 work_item_name: str = "",
 history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
 """构建群聊提问交互卡片。
 Args:
 question: 当前问题文本
 execution_id: 工作流执行 ID，用于回调路由
 node_id: 节点 ID，用于回调路由
 options: 可选的快捷选项列表
 work_item_name: 工作项名称，显示在 header 中
 history: 历史 Q&A 列表，每项含 question 和 answer 键
 Returns:
 飞书卡片 JSON 结构
 """
 elements: list[dict[str, Any]] =
 # 历史 Q&A 区块
 if history:
 history_content = ""
 for qa in history:
 history_content += f"**Q:** {qa.get('question', '')}\n"
 history_content += f"**A:** {qa.get('answer', '')}\n\n"
 elements.append({
 "tag": "div",
 "text": {
 "tag": "lark_md",
 "content": history_content.strip,
 },
 })
 elements.append({"tag": "hr"})
 # 当前问题（加粗）
 elements.append({
 "tag": "markdown",
 "content": f"**{question}**",
 })
 # 快捷选项按钮
 if options:
 actions: list[dict[str, Any]] =
 for opt in options:
 actions.append({
 "tag": "button",
 "text": {"tag": "plain_text", "content": opt},
 "type": "default",
 "value": {
 "action": "chat_question_answer",
 "execution_id": execution_id,
 "node_id": node_id,
 "answer": opt,
 },
 })
 elements.append({"tag": "action", "actions": actions})
 # 自由输入表单
 elements.append({
 "tag": "form",
 "name": "chat_answer_form",
 "elements": [
 {
 "tag": "input",
 "name": "custom_answer",
 "placeholder": {"tag": "plain_text", "content": "输入自定义回复..."},
 },
 {
 "tag": "button",
 "name": "submit_chat_answer",
 "text": {"tag": "plain_text", "content": "提交"},
 "type": "primary",
 "action_type": "form_submit",
 "value": {
 "action": "chat_question_answer",
 "execution_id": execution_id,
 "node_id": node_id,
 },
 },
 ],
 })
 # Header 标题
 title = "Friday 提问"
 if work_item_name:
 title = f"Friday 提问 — {work_item_name}"
 return {
 "config": {"wide_screen_mode": True},
 "header": {
 "title": {"tag": "plain_text", "content": title},
 "template": "blue",
 },
 "elements": elements,
 }
def build_chat_answered_card(
 question: str,
 answer: str,
 responder_name: str = "",
 work_item_name: str = "",
) -> dict[str, Any]:
 """构建已回复状态卡片（灰色主题，替换原交互卡片）。
 Args:
 question: 原始问题
 answer: 用户回复内容
 responder_name: 回复者名称
 work_item_name: 工作项名称
 Returns:
 飞书卡片 JSON 结构
 """
 elements: list[dict[str, Any]] =
 # Q&A 内容
 content = f"**Q:** {question}\n\n**A:** {answer}"
 if responder_name:
 content += f"\n\n**回复者:** {responder_name}"
 elements.append({"tag": "markdown", "content": content})
 elements.append({"tag": "hr"})
 # 处理中提示
 elements.append({
 "tag": "markdown",
 "content": "_正在处理中..._",
 })
 return {
 "config": {"wide_screen_mode": True},
 "header": {
 "title": {"tag": "plain_text", "content": "已收到回复"},
 "template": "grey",
 },
 "elements": elements,
 }
