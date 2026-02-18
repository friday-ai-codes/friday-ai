"""内存消息队列，断线期间缓冲待发消息。"""
from __future__ import annotations
import collections
from dataclasses import dataclass, field
@dataclass
class MessageQueue:
 """有界消息队列（maxlen=100），重连后按序重发。"""
 _queue: collections.deque[dict] = field(default_factory=lambda: collections.deque(maxlen=100))
 def push(self, message: dict) -> None:
 self._queue.append(message)
 def drain(self) -> list[dict]:
 items = list(self._queue)
 self._queue.clear
 return items
 def __len__(self) -> int:
 return len(self._queue)
