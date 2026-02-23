package scheduler
import (
	"context"
	"sync"
	"sync/atomic"
	"time"
	"github.com/rs/zerolog/log"
	"github.com/friday-ai-codes/friday-ai/runner/internal/ws"
)
// TaskScheduler 通过 FIFO 队列 + semaphore 控制并发调度。
type TaskScheduler struct {
	mu sync.Mutex
	cond *sync.Cond
	queue ws.TaskPayload
	sem chan struct{}
	wg sync.WaitGroup
	accepting atomic.Bool
	containers sync.Map // task_id -> container_id
	onTask func(context.Context, ws.TaskPayload)
	concurrent int
}
// New 创建 TaskScheduler。
func New(concurrent int) *TaskScheduler {
	s:= &TaskScheduler{
 queue: make(ws.TaskPayload, 0),
 sem: make(chan struct{}, concurrent),
 concurrent: concurrent,
	}
	s.cond = sync.NewCond(&s.mu)
	s.accepting.Store(true)
	return s
}
// SetTaskCallback 设置任务执行回调。
func (s *TaskScheduler) SetTaskCallback(fn func(context.Context, ws.TaskPayload)) {
	s.onTask = fn
}
// Submit 将任务加入 FIFO 队列。
func (s *TaskScheduler) Submit(task ws.TaskPayload) {
	s.mu.Lock
	s.queue = append(s.queue, task)
	s.mu.Unlock
	s.cond.Signal
	log.Info.Str("task_id", task.TaskID).Msg("task_queued")
}
// Run 主循环：等待 accepting + 队列非空，取出队首，acquire sem，启动 goroutine 执行。
func (s *TaskScheduler) Run(ctx context.Context) {
	for {
 s.mu.Lock
 for !s.accepting.Load || len(s.queue) == 0 {
 // 检查 ctx 是否已取消
 select {
 case <-ctx.Done:
 s.mu.Unlock
 return
 default:
 }
 s.cond.Wait
 }
 task:= s.queue[0]
 s.queue = s.queue[1:]
 s.mu.Unlock
 s.sem <- struct{}{} // acquire semaphore
 s.wg.Add(1)
 go s.execute(ctx, task)
	}
}
func (s *TaskScheduler) execute(ctx context.Context, task ws.TaskPayload) {
	defer func {
 <-s.sem // release semaphore
 s.wg.Done
 s.containers.Delete(task.TaskID)
	}
	if s.onTask != nil {
 s.onTask(ctx, task)
	}
}
// RegisterContainer 注册 task_id -> container_id 映射。
func (s *TaskScheduler) RegisterContainer(taskID, containerID string) {
	s.containers.Store(taskID, containerID)
}
// UnregisterContainer 移除映射。
func (s *TaskScheduler) UnregisterContainer(taskID string) {
	s.containers.Delete(taskID)
}
// GetAllContainerIDs 返回所有已注册的 container ID。
func (s *TaskScheduler) GetAllContainerIDs string {
	var ids string
	s.containers.Range(func(_, v any) bool {
 ids = append(ids, v.(string))
 return true
	})
	return ids
}
// ActiveCount 返回当前活跃任务数。
func (s *TaskScheduler) ActiveCount int {
	return s.concurrent - (cap(s.sem) - len(s.sem))
}
// QueuedCount 返回队列中等待的任务数。
func (s *TaskScheduler) QueuedCount int {
	s.mu.Lock
	defer s.mu.Unlock
	return len(s.queue)
}
// TogglePause 切换暂停状态。返回 true 表示现在已暂停。
func (s *TaskScheduler) TogglePause bool {
	if s.accepting.Load {
 s.accepting.Store(false)
 log.Info.Msg("scheduler_paused")
 return true
	}
	s.accepting.Store(true)
	s.cond.Broadcast
	log.Info.Msg("scheduler_resumed")
	return false
}
// StopAccepting 停止接收新任务（不可恢复）。
func (s *TaskScheduler) StopAccepting {
	s.accepting.Store(false)
	s.cond.Broadcast // 唤醒 Run 循环以检查 ctx
	log.Info.Msg("scheduler_stop_accepting")
}
// IsAccepting 返回是否接受新任务。
func (s *TaskScheduler) IsAccepting bool {
	return s.accepting.Load
}
// WaitAllDone 等待所有活跃任务完成，超时后返回。
func (s *TaskScheduler) WaitAllDone(timeout time.Duration) {
	done:= make(chan struct{})
	go func {
 s.wg.Wait
 close(done)
	}
	select {
	case <-done:
	case <-time.After(timeout):
 log.Warn.Msg("wait_all_done_timeout")
	}
}
