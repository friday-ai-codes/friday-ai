package scheduler

import (
	"context"
	"sync"
	"testing"
	"time"

	"github.com/friday-ai-codes/friday-ai/runner/internal/ws"
)

// TestCancelDequeuesPendingTask 排队中的任务被取消后必须真正离开队列，
// 且不再算 active——否则后续同 ID 的 task.assign 会被幂等去重误判为"已在跑"。
func TestCancelDequeuesPendingTask(t *testing.T) {
	s := New(1)
	// 不启动 Run，任务停留在队列里，模拟"已接受但还没轮到执行"。
	s.Submit(ws.TaskPayload{TaskID: "task-a"})
	s.Submit(ws.TaskPayload{TaskID: "task-b"})

	outcome := s.Cancel("task-a")

	if !outcome.Found {
		t.Fatal("排队中的任务应当被识别为 Found")
	}
	if !outcome.Dequeued {
		t.Error("排队中的任务应当标记 Dequeued，由调用方补终态消息")
	}
	if outcome.ContainerID != "" {
		t.Errorf("容器尚未启动，ContainerID 应为空，实得 %q", outcome.ContainerID)
	}
	if s.IsTaskActive("task-a") {
		t.Error("取消后不应再算 active，否则重派发会被误判去重")
	}
	if s.QueuedCount() != 1 {
		t.Errorf("队列应只剩 task-b，实得 %d 条", s.QueuedCount())
	}
	if !s.IsTaskActive("task-b") {
		t.Error("取消 task-a 不应影响 task-b")
	}
}

// TestCancelRunningTaskReturnsContainerID 已启动容器的任务，Cancel 只交回
// container_id 由调用方停容器，并且不标 Dequeued——终态由 runTask 的
// WaitContainer 返回后上报，重复上报会让 server 把并发槽位减两次。
func TestCancelRunningTaskReturnsContainerID(t *testing.T) {
	s := New(1)
	s.Submit(ws.TaskPayload{TaskID: "task-run"})
	// 模拟 runTask 已取出任务并起了容器。
	s.mu.Lock()
	s.queue = nil
	s.mu.Unlock()
	s.RegisterContainer("task-run", "container-xyz")

	outcome := s.Cancel("task-run")

	if !outcome.Found {
		t.Fatal("运行中的任务应当被识别为 Found")
	}
	if outcome.Dequeued {
		t.Error("容器已启动时不应标 Dequeued，否则会与 runTask 重复上报终态")
	}
	if outcome.ContainerID != "container-xyz" {
		t.Errorf("应交回 container_id 供调用方停容器，实得 %q", outcome.ContainerID)
	}
}

// TestCancelUnknownTaskIsIdempotent server 重发 cancel、或容器刚好自己跑完时
// 都会走到这里，必须静默返回而不是报错或误伤别的任务。
func TestCancelUnknownTaskIsIdempotent(t *testing.T) {
	s := New(1)
	s.Submit(ws.TaskPayload{TaskID: "task-alive"})

	for _, taskID := range []string{"never-existed", ""} {
		outcome := s.Cancel(taskID)
		if outcome.Found {
			t.Errorf("未知 task_id %q 不应报 Found", taskID)
		}
		if outcome.Dequeued || outcome.ContainerID != "" {
			t.Errorf("未知 task_id %q 不应产生任何处置动作", taskID)
		}
	}

	if s.QueuedCount() != 1 || !s.IsTaskActive("task-alive") {
		t.Error("取消未知任务不应影响在册任务")
	}
}

// TestCancelActiveButContainerNotReady 覆盖 Submit 与 StartContainer 之间的
// 时间窗：任务已出队但容器还没注册，此时不应误报 Dequeued（那会让调用方补一条
// 终态，而容器其实马上就要起来了）。
func TestCancelActiveButContainerNotReady(t *testing.T) {
	s := New(1)
	s.Submit(ws.TaskPayload{TaskID: "task-gap"})
	s.mu.Lock()
	s.queue = nil
	s.mu.Unlock()

	outcome := s.Cancel("task-gap")

	if !outcome.Found {
		t.Fatal("任务仍 active，应报 Found")
	}
	if outcome.Dequeued {
		t.Error("任务已离开队列，不应标 Dequeued")
	}
	if outcome.ContainerID != "" {
		t.Error("容器尚未注册，ContainerID 应为空")
	}
}

// TestCancelConcurrentWithExecution 并发取消不应死锁或 panic。
// Cancel 会拿 s.mu，而 Run 循环同样持锁，回归时容易写出锁重入。
func TestCancelConcurrentWithExecution(t *testing.T) {
	s := New(2)
	released := make(chan struct{})
	s.SetTaskCallback(func(_ context.Context, _ ws.TaskPayload) {
		<-released
	})

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go s.Run(ctx)

	for i := range 20 {
		s.Submit(ws.TaskPayload{TaskID: string(rune('a'+i%26)) + "-task"})
	}

	var wg sync.WaitGroup
	for i := range 20 {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			s.Cancel(string(rune('a'+i%26)) + "-task")
		}(i)
	}

	done := make(chan struct{})
	go func() {
		wg.Wait()
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("并发 Cancel 超时，疑似死锁")
	}
	close(released)
}
