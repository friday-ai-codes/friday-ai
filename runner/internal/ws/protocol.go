package ws
import "github.com/google/uuid"
// Runner -> Server
const (
	TypeRunnerHello = "runner.hello"
	TypeRunnerHeartbeat = "runner.heartbeat"
	TypeRunnerBye = "runner.bye"
	TypeTaskAccepted = "task.accepted"
	TypeTaskRejected = "task.rejected"
	TypeTaskCompleted = "task.completed"
	TypeTaskFailed = "task.failed"
	TypeTaskLog = "task.log"
	TypeTaskProgress = "task.progress"
	TypeTaskQuestion = "task.question"
	TypeTaskTokenUsage = "task.token_usage"
)
// Server -> Runner
const (
	TypeTaskAssign = "task.assign"
	TypeTaskCancel = "task.cancel"
	TypeQuestionAnswer = "question.answer"
	TypeToolCall = "tool.call"
	TypeToolResult = "tool.result"
)
// Message 是 Runner <-> Server 的消息信封。
type Message struct {
	Type string `json:"type"`
	Payload any `json:"payload"`
	ID string `json:"id,omitempty"`
	Ref string `json:"ref,omitempty"`
}
// NewMessage 构造不带 ID 的消息。
func NewMessage(msgType string, payload any) Message {
	return Message{Type: msgType, Payload: payload}
}
// NewRequest 构造带自动生成 UUID 的请求消息。
func NewRequest(msgType string, payload any) Message {
	return Message{Type: msgType, Payload: payload, ID: uuid.NewString}
}
// NewResponse 构造关联原始请求的响应消息。
func NewResponse(refID, msgType string, payload any) Message {
	return Message{Type: msgType, Payload: payload, Ref: refID}
}
