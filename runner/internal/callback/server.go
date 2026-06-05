package callback

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"strconv"
	"sync"
	"time"

	"github.com/friday-ai-codes/friday-ai/runner/internal/ws"
	"github.com/rs/zerolog/log"
)

const (
	DefaultPort        = 8976
	DefaultToolTimeout = 60 * time.Second
)

// callbackToWS 将容器回调类型映射到 WS 消息类型。
var callbackToWS = map[string]string{
	"completed":   ws.TypeTaskCompleted,
	"failed":      ws.TypeTaskFailed,
	"question":    ws.TypeTaskQuestion,
	"heartbeat":   ws.TypeTaskProgress,
	"progress":    ws.TypeTaskProgress,
	"action_log":  ws.TypeTaskLog,
	"token_usage": ws.TypeTaskTokenUsage,
}

type callbackRequest struct {
	Type      string         `json:"type"`
	Token     string         `json:"token"`
	SessionID string         `json:"session_id"`
	Payload   map[string]any `json:"payload"`
}

// pendingCall 存储等待中的 tool call 信息。
type pendingCall struct {
	ch     chan map[string]any
	taskID string
}

// CallbackServer 接收容器 HTTP 回调并转发到 WS MessageQueue。
type CallbackServer struct {
	queue        *ws.MessageQueue
	token        string
	pendingCalls sync.Map // call_id -> *pendingCall
	server       *http.Server
}

// New 创建 CallbackServer。
func New(queue *ws.MessageQueue, token string, port int) *CallbackServer {
	s := &CallbackServer{queue: queue, token: token}
	mux := http.NewServeMux()
	mux.HandleFunc("POST /callback", s.handleCallback)
	s.server = &http.Server{
		Addr:    net.JoinHostPort("0.0.0.0", strconv.Itoa(port)),
		Handler: mux,
	}
	return s
}

// Start 启动 HTTP 服务器，ctx 取消时自动关闭。
func (s *CallbackServer) Start(ctx context.Context) error {
	go func() {
		<-ctx.Done()
		_ = s.Shutdown(context.Background())
	}()
	log.Info().Str("addr", s.server.Addr).Msg("callback server started")
	if err := s.server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		return err
	}
	return nil
}

// Shutdown 优雅关闭服务器。
func (s *CallbackServer) Shutdown(ctx context.Context) error {
	return s.server.Shutdown(ctx)
}

func (s *CallbackServer) handleCallback(w http.ResponseWriter, r *http.Request) {
	var req callbackRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "bad json"})
		return
	}
	if req.Token != s.token {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	if req.Type == "tool_call" {
		s.handleToolCall(w, &req)
		return
	}
	wsType, ok := callbackToWS[req.Type]
	if !ok {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "unknown type"})
		return
	}
	payload := mergePayload(req.Payload, req.SessionID)
	s.queue.Push(ws.NewMessage(wsType, payload))
	writeJSON(w, http.StatusOK, map[string]any{"ok": true})
}

func (s *CallbackServer) handleToolCall(w http.ResponseWriter, req *callbackRequest) {
	callID, _ := req.Payload["call_id"].(string)
	toolName, _ := req.Payload["tool_name"].(string)
	if callID == "" || toolName == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "missing call_id or tool_name"})
		return
	}
	arguments, _ := req.Payload["arguments"].(map[string]any)

	ch := make(chan map[string]any, 1)
	s.pendingCalls.Store(callID, &pendingCall{ch: ch, taskID: req.SessionID})
	defer s.pendingCalls.Delete(callID)

	s.queue.Push(ws.NewMessage(ws.TypeToolCall, map[string]any{
		"task_id":   req.SessionID,
		"call_id":   callID,
		"tool_name": toolName,
		"arguments": arguments,
	}))

	select {
	case result := <-ch:
		writeJSON(w, http.StatusOK, map[string]any{"ok": true, "result": result})
	case <-time.After(DefaultToolTimeout):
		writeJSON(w, http.StatusGatewayTimeout, map[string]any{
			"ok":    false,
			"error": map[string]string{"code": "timeout", "message": "tool call " + callID + " timed out"},
		})
	}
}

// ResolveToolCall 由 WS 层调用，将结果写入等待中的 channel。
func (s *CallbackServer) ResolveToolCall(callID string, result map[string]any) {
	if v, ok := s.pendingCalls.Load(callID); ok {
		pc := v.(*pendingCall)
		select {
		case pc.ch <- result:
		default:
		}
	}
}

// CleanupPendingToolCalls 清理指定 task 的所有等待中 tool call。
func (s *CallbackServer) CleanupPendingToolCalls(taskID string) {
	s.pendingCalls.Range(func(key, value any) bool {
		pc := value.(*pendingCall)
		if pc.taskID == taskID {
			close(pc.ch)
			s.pendingCalls.Delete(key)
		}
		return true
	})
}

func mergePayload(payload map[string]any, taskID string) map[string]any {
	m := make(map[string]any, len(payload)+1)
	for k, v := range payload {
		m[k] = v
	}
	m["task_id"] = taskID
	return m
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
