package ws

import "sync"

// MessageQueue 是有界消息缓冲队列，断线期间缓冲待发消息。
type MessageQueue struct {
	mu     sync.Mutex
	buf    []Message
	maxLen int
}

// NewMessageQueue 创建指定容量的有界队列。
func NewMessageQueue(maxLen int) *MessageQueue {
	return &MessageQueue{buf: make([]Message, 0, maxLen), maxLen: maxLen}
}

// Push 入队消息。队列满时返回 false，拒绝新消息。
func (q *MessageQueue) Push(msg Message) bool {
	q.mu.Lock()
	defer q.mu.Unlock()
	if len(q.buf) >= q.maxLen {
		return false
	}
	q.buf = append(q.buf, msg)
	return true
}

// Drain 返回全部消息并清空队列。
func (q *MessageQueue) Drain() []Message {
	q.mu.Lock()
	defer q.mu.Unlock()
	items := q.buf
	q.buf = make([]Message, 0, q.maxLen)
	return items
}

// Len 返回当前队列长度。
func (q *MessageQueue) Len() int {
	q.mu.Lock()
	defer q.mu.Unlock()
	return len(q.buf)
}
