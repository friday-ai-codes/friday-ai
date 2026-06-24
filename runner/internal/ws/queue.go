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

// isTerminal 判断是否为任务终态消息。终态消息（completed/failed）一旦丢弃，
// server 端的 SubAgentSession 会永远停在 pending/running，是生产上大量悬挂会话的
// 根因之一，因此绝不可静默丢弃。
func isTerminal(msgType string) bool {
	return msgType == TypeTaskCompleted || msgType == TypeTaskFailed
}

// Push 入队消息。
//
// 容量策略：
//   - 未满：直接入队。
//   - 已满 + 终态消息：优先驱逐最旧的「非终态」消息（log/progress 可丢）腾位；
//     若队列全是终态消息，则越界追加——宁可暂时超出软上限，也绝不丢任务终态。
//   - 已满 + 非终态消息：返回 false 丢弃（log/progress 丢失可接受）。
func (q *MessageQueue) Push(msg Message) bool {
	q.mu.Lock()
	defer q.mu.Unlock()
	if len(q.buf) < q.maxLen {
		q.buf = append(q.buf, msg)
		return true
	}
	if isTerminal(msg.Type) {
		for i, m := range q.buf {
			if !isTerminal(m.Type) {
				q.buf = append(q.buf[:i], q.buf[i+1:]...)
				q.buf = append(q.buf, msg)
				return true
			}
		}
		// 全是终态消息：越界保留，绝不丢终态。
		q.buf = append(q.buf, msg)
		return true
	}
	return false
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
