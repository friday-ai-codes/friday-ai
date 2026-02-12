"""容器提问处理器（Phase）。
负责：
1. 发送 Feishu 提问卡片
2. 接收用户回复后写入 answer.json 到共享卷
"""
import json
import os
import structlog
from asgiref.sync import async_to_sync
from django.conf import settings
from feishu.cards.container_question_card import (
 build_container_answered_card,
 build_container_question_card,
)
from services.protocols import ANSWER_FILE, CONTAINER_PROTOCOL_DIR
from subagent.models import SubAgentSession
logger = structlog.get_logger
def send_question_card(
 session: SubAgentSession,
 question: str,
 options: list[str] | None = None,
 context: str = "",
) -> None:
 """发送 Feishu 提问卡片。
 通过 session 关联的 main_session 找到 chat_id，
 然后发送交互式卡片。
 Args:
 session: SubAgentSession 实例
 question: 问题内容
 options: 可选的快捷选项
 context: 问题上下文
 """
 from services.feishu_im import FeishuIMClient
 log = logger.bind(session_id=session.session_id)
 # 获取 chat_id（从 main_session 的 metadata 中）
 chat_id = ""
 if session.main_session and session.main_session.metadata:
 chat_id = session.main_session.metadata.get("chat_id", "")
 if not chat_id:
 log.warning("question_no_chat_id", main_session_id=str(session.main_session_id))
 return
 # 构建卡片
 card = build_container_question_card(
 question=question,
 options=options,
 session_id=session.session_id,
 context=context,
 )
 # 发送卡片
 try:
 im_client = FeishuIMClient
 async_to_sync(im_client.send_card)(chat_id=chat_id, card=card)
 log.info("question_card_sent", chat_id=chat_id)
 except Exception as e:
 log.error("question_card_send_failed", error=str(e))
 raise
def write_answer_to_volume(session: SubAgentSession, answer: str) -> bool:
 """将用户回复写入容器共享卷的 answer.json。
 路径: server/data/transfers/{session_id}/.friday/answer.json
 Args:
 session: SubAgentSession 实例
 answer: 用户回复内容
 Returns:
 True 写入成功，False 写入失败
 """
 log = logger.bind(session_id=session.session_id)
 transfers_dir = os.path.join(settings.BASE_DIR, "data", "transfers")
 protocol_dir = os.path.join(transfers_dir, session.session_id, ".friday")
 answer_path = os.path.join(protocol_dir, ANSWER_FILE)
 # 从 last_output 获取问题 ID（如果有）
 question_id = ""
 if session.last_output and isinstance(session.last_output, dict):
 pending = session.last_output.get("pending_question", {})
 question_id = pending.get("question_id", "")
 answer_data = {
 "question_id": question_id,
 "answer": answer,
 "answered_at": __import__("django").utils.timezone.now.isoformat,
 }
 try:
 os.makedirs(protocol_dir, exist_ok=True)
 with open(answer_path, "w", encoding="utf-8") as f:
 json.dump(answer_data, f, ensure_ascii=False, indent=2)
 log.info("answer_written", path=answer_path)
 return True
 except OSError as e:
 log.error("answer_write_failed", path=answer_path, error=str(e))
 return False
def handle_container_answer(session_id: str, answer: str) -> bool:
 """处理容器提问的用户回复。
 1. 查找 session
 2. 写入 answer.json
 3. 清除 pending_question
 Args:
 session_id: SubAgentSession.session_id
 answer: 用户回复
 Returns:
 True 处理成功
 """
 log = logger.bind(session_id=session_id)
 try:
 session = SubAgentSession.objects.get(session_id=session_id)
 except SubAgentSession.DoesNotExist:
 log.warning("answer_session_not_found")
 return False
 # 写入 answer.json
 if not write_answer_to_volume(session, answer):
 return False
 # 清除 pending_question
 if session.last_output and isinstance(session.last_output, dict):
 session.last_output.pop("pending_question", None)
 session.save(update_fields=["last_output", "updated_at"])
 log.info("container_answer_processed", answer_preview=answer[:50])
 return True
