package ws

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"fmt"
	mathrand "math/rand/v2"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/coder/websocket"
	"github.com/coder/websocket/wsjson"
	"github.com/hashicorp/go-retryablehttp"
	"github.com/rs/zerolog/log"
	"golang.org/x/sync/errgroup"

	"github.com/friday-ai-codes/friday-ai/runner/internal/ui"
)

const (
	initialDelay        = 1 * time.Second
	maxDelay            = 60 * time.Second
	maxRetries          = 20
	heartbeatInterval   = 30 * time.Second
	closeCodeReplaced   = 4002
	zombieScanInterval  = 30 * time.Second
	shutdownWaitTimeout = 300 * time.Second
)

// TaskPayload 是 ws 包内部的任务描述，避免导入 docker 包。
type TaskPayload struct {
	TaskID   string
	TaskType string
	Image    string
	RepoURL  string
	Branch   string
	Timeout  int
	Payload  map[string]any
}

// CancelOutcome 描述一次 task.cancel 的处置结果。
//
// 定义在 ws 包而非 scheduler 包：scheduler 已导入 ws，反向导入会成环。
type CancelOutcome struct {
	// Found 表示 task 当时确实在调度中。false 说明任务已结束或从未收到，
	// 取消按幂等处理（server 重发 cancel、或容器刚好自己跑完都会走到这里）。
	Found bool
	// Dequeued 表示任务尚在排队、已直接从队列摘除，容器从未启动。
	// 此时不会有 runTask 去上报终态，调用方必须自己补一条终态消息。
	Dequeued bool
	// ContainerID 非空表示容器已启动，调用方需要停容器。
	// 停掉后 runTask 的 WaitContainer 会返回，由它上报终态——调用方不要重复上报。
	ContainerID string
}

// CallbackService 解耦 ws 与 callback 包的循环依赖。
type CallbackService interface {
	Start(ctx context.Context) error
	Shutdown(ctx context.Context) error
	ResolveToolCall(callID string, result map[string]any)
	CleanupPendingToolCalls(taskID string)
}

// CallbackFactory 在 Run 内部创建 CallbackServer。
type CallbackFactory func(queue *MessageQueue, token string, port int) CallbackService

// ExecutorService 抽象容器执行器。
type ExecutorService interface {
	StartContainer(ctx context.Context, task TaskPayload, callbackURL, callbackToken string) (containerID, answerEndpoint string, err error)
	WaitContainer(ctx context.Context, containerID string, timeout time.Duration) (exitCode int, logs string, err error)
	ReadContainerFile(ctx context.Context, containerID, path string) (string, error)
	StreamLogs(ctx context.Context, containerID string, onLine func(line string)) error
	RemoveContainer(ctx context.Context, containerID string) error
	StartupCleanup(ctx context.Context) (int, error)
	ZombieScan(ctx context.Context, knownIDs []string, queue *MessageQueue, zombieThreshold, retainHours float64) error
}

// SchedulerService 抽象任务调度器。
type SchedulerService interface {
	SetTaskCallback(fn func(context.Context, TaskPayload))
	Submit(task TaskPayload)
	Cancel(taskID string) CancelOutcome
	Run(ctx context.Context)
	RegisterContainer(taskID, containerID string)
	UnregisterContainer(taskID string)
	GetAllContainerIDs() []string
	GetRunningTaskIDs() []string
	IsTaskActive(taskID string) bool
	ActiveCount() int
	IsAccepting() bool
	StopAccepting()
	WaitAllDone(timeout time.Duration)
	TogglePause() bool
}

// Config 是 WebSocket 客户端配置。
type Config struct {
	ServerURL       string
	Token           string
	Name            string
	Version         string
	Concurrent      int
	Executor        ExecutorService
	Scheduler       SchedulerService
	CallbackFactory CallbackFactory
	CallbackPort    int
	CallbackHost    string
	DefaultTimeout  int
}

// Run 启动 WebSocket 客户端主循环。
func Run(ctx context.Context, cfg Config) error {
	if pid, alive := CheckPID(); alive {
		return fmt.Errorf("Runner 已在运行 (PID %d)", pid)
	}
	RemovePID()
	if err := WritePID(); err != nil {
		return fmt.Errorf("写入 PID 文件失败: %w", err)
	}

	Warmup()

	ctx, cancel := signal.NotifyContext(ctx, syscall.SIGTERM, syscall.SIGINT)
	defer cancel()

	// SIGUSR1 触发 pause/resume，不终止进程
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGUSR1)
	defer signal.Stop(sigCh)
	go func() {
		for {
			select {
			case <-ctx.Done():
				return
			case <-sigCh:
				paused := cfg.Scheduler.TogglePause()
				if paused {
					log.Info().Msg("sigusr1_paused")
				} else {
					log.Info().Msg("sigusr1_resumed")
				}
			}
		}
	}()

	queue := NewMessageQueue(100)

	// 生成 callbackToken
	tokenBytes := make([]byte, 32)
	if _, err := rand.Read(tokenBytes); err != nil {
		return fmt.Errorf("生成 callback token 失败: %w", err)
	}
	callbackToken := base64.URLEncoding.EncodeToString(tokenBytes)
	// docker 模式默认 host.docker.internal（零回归）；k8s 模式经 CallbackHost
	// 注入 runner Pod 可达地址（FRIDAY_RUNNER_CALLBACK_HOST，通常为 runner Pod IP）。
	callbackHost := cfg.CallbackHost
	if callbackHost == "" {
		callbackHost = "host.docker.internal"
	}
	callbackURL := fmt.Sprintf("http://%s:%d/callback", callbackHost, cfg.CallbackPort)

	// 创建并启动 CallbackServer
	cb := cfg.CallbackFactory(queue, callbackToken, cfg.CallbackPort)
	go cb.Start(ctx)

	// 清理残留容器
	if cleaned, err := cfg.Executor.StartupCleanup(ctx); err != nil {
		log.Warn().Err(err).Msg("startup_cleanup_failed")
	} else if cleaned > 0 {
		log.Info().Int("count", cleaned).Msg("startup_cleanup")
	}

	// 设置 scheduler onTask 回调
	cfg.Scheduler.SetTaskCallback(func(taskCtx context.Context, task TaskPayload) {
		runTask(taskCtx, task, cfg, cb, queue, callbackURL, callbackToken)
	})
	go cfg.Scheduler.Run(ctx)

	// 僵尸扫描
	go zombieScanLoop(ctx, cfg, queue)

	defer func() {
		cfg.Scheduler.StopAccepting()
		cfg.Scheduler.WaitAllDone(shutdownWaitTimeout)
		cb.Shutdown(context.Background())
		RemovePID()
	}()

	delay := initialDelay
	for attempt := 0; attempt < maxRetries; attempt++ {
		err := connectAndServe(ctx, cfg, cb, queue)
		if ctx.Err() != nil {
			ui.Info("正常关闭")
			return nil
		}
		if websocket.CloseStatus(err) == closeCodeReplaced {
			ui.Info("被新连接替代，停止重连")
			return nil
		}
		attempt++
		ui.Warn(fmt.Sprintf("重连中... 第 %d/%d 次", attempt, maxRetries))
		log.Warn().Err(err).Int("attempt", attempt).Msg("reconnecting")

		jitter := time.Duration(mathrand.Int64N(int64(delay) / 10))
		select {
		case <-time.After(delay + jitter):
		case <-ctx.Done():
			return nil
		}
		delay = min(delay*2, maxDelay)
	}
	return fmt.Errorf("重连 %d 次全部失败", maxRetries)
}

func connectAndServe(ctx context.Context, cfg Config, cb CallbackService, queue *MessageQueue) error {
	wsURL := httpToWS(cfg.ServerURL) + "/ws/v1/runner/?token=" + cfg.Token
	c, _, err := websocket.Dial(ctx, wsURL, nil)
	if err != nil {
		return err
	}
	defer c.CloseNow()

	hello := NewRequest(TypeRunnerHello, map[string]any{
		"name": cfg.Name, "version": cfg.Version, "concurrent": cfg.Concurrent,
		// 重连时上报仍在跑的任务，server 据此跳过重派发（避免重复容器）。
		"running_tasks": cfg.Scheduler.GetRunningTaskIDs(),
	})
	if err := wsjson.Write(ctx, c, hello); err != nil {
		return err
	}
	ui.Success("已连接到 Server")

	for _, msg := range queue.Drain() {
		if err := wsjson.Write(ctx, c, msg); err != nil {
			return err
		}
	}

	eg, ctx := errgroup.WithContext(ctx)
	eg.Go(func() error { return readLoop(ctx, c, cfg, cb, queue) })
	eg.Go(func() error { return heartbeatLoop(ctx, c, cfg) })
	eg.Go(func() error { return writeLoop(ctx, c, queue) })
	return eg.Wait()
}

func readLoop(ctx context.Context, c *websocket.Conn, cfg Config, cb CallbackService, queue *MessageQueue) error {
	for {
		var raw json.RawMessage
		if err := wsjson.Read(ctx, c, &raw); err != nil {
			return err
		}
		var msg Message
		if err := json.Unmarshal(raw, &msg); err != nil {
			log.Warn().Err(err).Msg("bad_message")
			continue
		}
		switch msg.Type {
		case TypeTaskAssign:
			handleTaskAssign(ctx, c, raw, cfg.Scheduler, queue)
		case TypeTaskCancel:
			go handleTaskCancel(ctx, raw, cfg, queue)
		case TypeToolResult:
			handleToolResult(raw, cb)
		case TypeQuestionAnswer:
			go handleQuestionAnswer(raw)
		default:
			log.Debug().Str("type", msg.Type).Msg("received")
		}
	}
}

func writeLoop(ctx context.Context, c *websocket.Conn, queue *MessageQueue) error {
	ticker := time.NewTicker(100 * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
			for _, msg := range queue.Drain() {
				if err := wsjson.Write(ctx, c, msg); err != nil {
					// 写失败，放回队列
					queue.Push(msg)
					return err
				}
			}
		}
	}
}

func heartbeatLoop(ctx context.Context, c *websocket.Conn, cfg Config) error {
	ticker := time.NewTicker(heartbeatInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			byeCtx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
			defer cancel()
			wsjson.Write(byeCtx, c, NewMessage(TypeRunnerBye, nil))
			c.Close(websocket.StatusNormalClosure, "bye")
			return ctx.Err()
		case <-ticker.C:
			payload := CollectMetrics(cfg.Scheduler.ActiveCount(), cfg.Concurrent, cfg.Scheduler.IsAccepting())
			if err := wsjson.Write(ctx, c, NewMessage(TypeRunnerHeartbeat, payload)); err != nil {
				return err
			}
		}
	}
}

func handleTaskAssign(_ context.Context, c *websocket.Conn, raw json.RawMessage, sched SchedulerService, queue *MessageQueue) {
	var envelope struct {
		ID      string         `json:"id"`
		Payload map[string]any `json:"payload"`
	}
	if err := json.Unmarshal(raw, &envelope); err != nil {
		return
	}
	taskID, _ := envelope.Payload["task_id"].(string)

	if !sched.IsAccepting() {
		resp := NewResponse(envelope.ID, TypeTaskRejected, map[string]any{"task_id": taskID, "reason": "not_accepting"})
		if err := wsjson.Write(context.Background(), c, resp); err != nil {
			queue.Push(resp)
		}
		return
	}

	// 幂等去重：同一 task 已在调度/运行中（多见于 WS 重连后 server 的恢复重派发），
	// 直接回 accepted 但不再 Submit，避免对同一任务起第二个容器。回 accepted 而非
	// rejected 是为了不触发 server 端 on_task_rejected 的 requeue 循环。
	if taskID != "" && sched.IsTaskActive(taskID) {
		resp := NewResponse(envelope.ID, TypeTaskAccepted, map[string]any{"task_id": taskID})
		if err := wsjson.Write(context.Background(), c, resp); err != nil {
			queue.Push(resp)
		}
		log.Info().Str("task_id", taskID).Msg("task_assign_deduped")
		return
	}

	resp := NewResponse(envelope.ID, TypeTaskAccepted, map[string]any{"task_id": taskID})
	if err := wsjson.Write(context.Background(), c, resp); err != nil {
		queue.Push(resp)
	}

	task := TaskPayload{
		TaskID:   taskID,
		TaskType: strVal(envelope.Payload, "task_type", "coding"),
		Image:    strVal(envelope.Payload, "image", ""),
		RepoURL:  strVal(envelope.Payload, "repo_url", ""),
		Branch:   strVal(envelope.Payload, "branch", ""),
		Timeout:  intVal(envelope.Payload, "timeout", 0),
		Payload:  envelope.Payload,
	}
	sched.Submit(task)
	log.Info().Str("task_id", taskID).Msg("task_accepted")
}

// handleTaskCancel 处理 server 下发的 task.cancel。
//
// 在此之前 runner 完全不处理这个消息类型，导致 chat 的「停止容器」与
// container_suspend_service 调用 dispatcher.cancel() 后容器照跑不误，一直占着
// 并发槽位直到超时；而 dispatcher.cancel() 只要 WS 发出去就返回 True，前端拿到
// 的是成功回执。
func handleTaskCancel(ctx context.Context, raw json.RawMessage, cfg Config, queue *MessageQueue) {
	var envelope struct {
		Payload map[string]any `json:"payload"`
	}
	if err := json.Unmarshal(raw, &envelope); err != nil {
		log.Warn().Err(err).Msg("task_cancel_bad_payload")
		return
	}
	taskID := strVal(envelope.Payload, "task_id", "")
	if taskID == "" {
		log.Warn().Msg("task_cancel_missing_task_id")
		return
	}

	outcome := cfg.Scheduler.Cancel(taskID)
	if !outcome.Found {
		// 幂等：任务已结束或重复下发 cancel，静默即可。
		log.Info().Str("task_id", taskID).Msg("task_cancel_not_active")
		return
	}

	if outcome.Dequeued {
		// 容器从未启动，没有 runTask 会上报终态——这里补一条，否则 server 侧
		// 一直等在 RUNNING。
		queue.Push(NewMessage(TypeTaskFailed, map[string]any{
			"task_id": taskID, "exit_code": -1, "error": "cancelled",
			"duration_ms": 0, "logs": "",
		}))
		log.Info().Str("task_id", taskID).Msg("task_cancelled_before_start")
		return
	}

	if outcome.ContainerID == "" {
		return
	}

	// RemoveContainer 是 Force 删除（杀 + 删）。停掉后 runTask 里阻塞的
	// WaitContainer 会返回并上报终态，此处刻意不再推送终态消息避免重复。
	if err := cfg.Executor.RemoveContainer(ctx, outcome.ContainerID); err != nil {
		log.Error().Str("task_id", taskID).Str("container_id", outcome.ContainerID).
			Err(err).Msg("task_cancel_remove_container_failed")
		return
	}
	log.Info().Str("task_id", taskID).Str("container_id", outcome.ContainerID).
		Msg("task_cancelled_container_removed")
}

func handleToolResult(raw json.RawMessage, cb CallbackService) {
	var envelope struct {
		Payload map[string]any `json:"payload"`
	}
	if err := json.Unmarshal(raw, &envelope); err != nil {
		return
	}
	callID, _ := envelope.Payload["call_id"].(string)
	if callID == "" {
		return
	}
	result, _ := envelope.Payload["result"].(map[string]any)
	cb.ResolveToolCall(callID, result)
}

func handleQuestionAnswer(raw json.RawMessage) {
	var envelope struct {
		Payload map[string]any `json:"payload"`
	}
	if err := json.Unmarshal(raw, &envelope); err != nil {
		return
	}
	endpoint, _ := envelope.Payload["answer_endpoint"].(string)
	if endpoint == "" {
		return
	}
	body, _ := json.Marshal(map[string]any{
		"question_id": envelope.Payload["question_id"],
		"answer":      envelope.Payload["answer"],
	})
	client := retryablehttp.NewClient()
	client.RetryMax = 2
	client.Logger = nil
	resp, err := client.Post(endpoint, "application/json", bytes.NewReader(body))
	if err != nil {
		log.Warn().Err(err).Str("endpoint", endpoint).Msg("question_answer_forward_failed")
		return
	}
	resp.Body.Close()
}

func runTask(ctx context.Context, task TaskPayload, cfg Config, cb CallbackService, queue *MessageQueue, callbackURL, callbackToken string) {
	start := time.Now()
	defer func() {
		cfg.Scheduler.UnregisterContainer(task.TaskID)
		cb.CleanupPendingToolCalls(task.TaskID)
	}()

	containerID, answerEndpoint, err := cfg.Executor.StartContainer(
		ctx, task, callbackURL, callbackToken,
	)
	if err != nil {
		queue.Push(NewMessage(TypeTaskFailed, map[string]any{
			"task_id": task.TaskID, "exit_code": -1, "error": err.Error(),
			"duration_ms": int(time.Since(start).Milliseconds()), "logs": "",
		}))
		return
	}
	cfg.Scheduler.RegisterContainer(task.TaskID, containerID)
	// 失败时保留容器用于调试，成功时清理
	taskFailed := true
	defer func() {
		if taskFailed {
			log.Info().Str("task_id", task.TaskID).Str("container_id", containerID).Msg("container_retained_for_debug")
		} else {
			cfg.Executor.RemoveContainer(context.Background(), containerID)
		}
	}()

	if answerEndpoint != "" {
		queue.Push(NewMessage(TypeTaskAccepted, map[string]any{
			"task_id": task.TaskID, "answer_endpoint": answerEndpoint,
		}))
	}

	// 启动流式日志转发
	streamCtx, cancelStream := context.WithCancel(ctx)
	streamDone := make(chan struct{})
	go func() {
		defer close(streamDone)
		cfg.Executor.StreamLogs(streamCtx, containerID, func(line string) {
			queue.Push(NewMessage(TypeTaskLog, map[string]any{
				"task_id": task.TaskID, "message": line,
			}))
		})
	}()

	timeout := time.Duration(task.Timeout) * time.Second
	if timeout == 0 {
		timeout = time.Duration(cfg.DefaultTimeout) * time.Second
	}
	exitCode, _, err := cfg.Executor.WaitContainer(ctx, containerID, timeout)
	cancelStream()
	<-streamDone
	durationMs := int(time.Since(start).Milliseconds())

	if err != nil {
		queue.Push(NewMessage(TypeTaskFailed, map[string]any{
			"task_id": task.TaskID, "exit_code": -1, "error": err.Error(),
			"duration_ms": durationMs, "logs": "",
		}))
		return
	}

	if exitCode == 0 {
		taskFailed = false
		var sessionData map[string]any
		var textOutput string
		if rawSession, readErr := cfg.Executor.ReadContainerFile(ctx, containerID, fmt.Sprintf("/app/sessions/%s.json", task.TaskID)); readErr != nil {
			log.Warn().Str("task_id", task.TaskID).Err(readErr).Msg("read_session_file_failed")
		} else if err := json.Unmarshal([]byte(rawSession), &sessionData); err != nil {
			log.Warn().Str("task_id", task.TaskID).Err(err).Msg("parse_session_file_failed")
		} else if out, ok := sessionData["last_output"].(string); ok {
			textOutput = out
		}
		queue.Push(NewMessage(TypeTaskCompleted, map[string]any{
			"task_id": task.TaskID, "exit_code": 0, "duration_ms": durationMs, "logs": "",
			"text_output": textOutput, "output": sessionData,
		}))
	} else {
		errMsg := "timeout"
		if exitCode != -1 {
			errMsg = fmt.Sprintf("exited with code %d", exitCode)
		}
		queue.Push(NewMessage(TypeTaskFailed, map[string]any{
			"task_id": task.TaskID, "exit_code": exitCode, "error": errMsg,
			"duration_ms": durationMs, "logs": "",
		}))
	}
}

func zombieScanLoop(ctx context.Context, cfg Config, queue *MessageQueue) {
	ticker := time.NewTicker(zombieScanInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			ids := cfg.Scheduler.GetAllContainerIDs()
			if err := cfg.Executor.ZombieScan(ctx, ids, queue, 3600, 1); err != nil {
				log.Warn().Err(err).Msg("zombie_scan_failed")
			}
		}
	}
}

func httpToWS(u string) string {
	u = strings.Replace(u, "https://", "wss://", 1)
	u = strings.Replace(u, "http://", "ws://", 1)
	return strings.TrimRight(u, "/")
}

func strVal(m map[string]any, key, fallback string) string {
	if v, ok := m[key].(string); ok && v != "" {
		return v
	}
	return fallback
}

func intVal(m map[string]any, key string, fallback int) int {
	switch v := m[key].(type) {
	case float64:
		return int(v)
	case int:
		return v
	}
	return fallback
}
