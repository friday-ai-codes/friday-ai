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
	mu         sync.Mutex
	cond       *sync.Cond
	queue      []ws.TaskPayload
	sem        chan struct{}
	wg         sync.WaitGroup
	accepting  atomic.Bool
	containers sync.Map // task_id -> container_id
	// active 跟踪「已接受到执行结束」整个生命周期内的 task_id（队列等待 / 容器
	// 启动中 / 容器运行中都算 active）。比 containers 多覆盖「已 Submit 但容器还
	// 没 StartContainer」的时间窗，用于：1) 收到重复 task.assign 时幂等去重；
	// 2) 重连时 hello 上报正在跑的任务，让 server 精准判断是否需要重派发。
	active     sync.Map // task_id -> struct{}
	onTask     func(context.Context, ws.TaskPayload)
	concurrent int
}

// New 创建 TaskScheduler。
func New(concurrent int) *TaskScheduler {
	s := &TaskScheduler{
		queue:      make([]ws.TaskPayload, 0),
		sem:        make(chan struct{}, concurrent),
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
	s.active.Store(task.TaskID, struct{}{})
	s.mu.Lock()
	s.queue = append(s.queue, task)
	s.mu.Unlock()
	s.cond.Signal()
	log.Info().Str("task_id", task.TaskID).Msg("task_queued")
}

// Run 主循环：等待 accepting + 队列非空，取出队首，acquire sem，启动 goroutine 执行。
func (s *TaskScheduler) Run(ctx context.Context) {
	for {
		s.mu.Lock()
		for !s.accepting.Load() || len(s.queue) == 0 {
			// 检查 ctx 是否已取消
			select {
			case <-ctx.Done():
				s.mu.Unlock()
				return
			default:
			}
			s.cond.Wait()
		}
		task := s.queue[0]
		s.queue = s.queue[1:]
		s.mu.Unlock()

		s.sem <- struct{}{} // acquire semaphore
		s.wg.Add(1)
		go s.execute(ctx, task)
	}
}

func (s *TaskScheduler) execute(ctx context.Context, task ws.TaskPayload) {
	defer func() {
		<-s.sem // release semaphore
		s.wg.Done()
		s.containers.Delete(task.TaskID)
		s.active.Delete(task.TaskID)
	}()
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
func (s *TaskScheduler) GetAllContainerIDs() []string {
	var ids []string
	s.containers.Range(func(_, v any) bool {
		ids = append(ids, v.(string))
		return true
	})
	return ids
}

// IsTaskActive 判断 task 是否已在调度中（队列等待 / 容器启动中 / 容器运行中）。
// 用于幂等去重：server 重连恢复时若重复下发同一 task.assign，runner 据此忽略，
// 避免对同一任务起第二个容器（历史 non-fast-forward 冲突的根因）。
func (s *TaskScheduler) IsTaskActive(taskID string) bool {
	_, ok := s.active.Load(taskID)
	return ok
}

// GetRunningTaskIDs 返回当前仍在调度中的所有 task_id。
// 重连时随 hello 上报，server 据此判断哪些任务旧容器还活着（不必重派发）。
func (s *TaskScheduler) GetRunningTaskIDs() []string {
	ids := make([]string, 0)
	s.active.Range(func(k, _ any) bool {
		ids = append(ids, k.(string))
		return true
	})
	return ids
}

// ActiveCount 返回当前活跃任务数。
func (s *TaskScheduler) ActiveCount() int {
	return s.concurrent - (cap(s.sem) - len(s.sem))
}

// QueuedCount 返回队列中等待的任务数。
func (s *TaskScheduler) QueuedCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.queue)
}

// TogglePause 切换暂停状态。返回 true 表示现在已暂停。
func (s *TaskScheduler) TogglePause() bool {
	if s.accepting.Load() {
		s.accepting.Store(false)
		log.Info().Msg("scheduler_paused")
		return true
	}
	s.accepting.Store(true)
	s.cond.Broadcast()
	log.Info().Msg("scheduler_resumed")
	return false
}

// StopAccepting 停止接收新任务（不可恢复）。
func (s *TaskScheduler) StopAccepting() {
	s.accepting.Store(false)
	s.cond.Broadcast() // 唤醒 Run 循环以检查 ctx
	log.Info().Msg("scheduler_stop_accepting")
}

// IsAccepting 返回是否接受新任务。
func (s *TaskScheduler) IsAccepting() bool {
	return s.accepting.Load()
}

// WaitAllDone 等待所有活跃任务完成，超时后返回。
func (s *TaskScheduler) WaitAllDone(timeout time.Duration) {
	done := make(chan struct{})
	go func() {
		s.wg.Wait()
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(timeout):
		log.Warn().Msg("wait_all_done_timeout")
	}
}
