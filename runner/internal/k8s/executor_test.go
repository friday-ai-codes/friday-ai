package k8s

import (
	"context"
	"sync/atomic"
	"testing"
	"time"

	batchv1 "k8s.io/api/batch/v1"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/watch"
	"k8s.io/client-go/kubernetes/fake"
	ktesting "k8s.io/client-go/testing"

	"github.com/friday-ai-codes/friday-ai/runner/internal/exec"
	"github.com/friday-ai-codes/friday-ai/runner/internal/ws"
)

// newJob 构造一个带本 runner label 的 Job，供生命周期单测预置。
func newJob(ns, name, runner string, labelsExtra map[string]string) *batchv1.Job {
	labels := map[string]string{
		labelKeyApp:    labelApp,
		labelKeyRunner: sanitizeName(runner),
		labelKeyJob:    name,
	}
	for k, v := range labelsExtra {
		labels[k] = v
	}
	return &batchv1.Job{
		ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: ns, Labels: labels},
	}
}

// newFast 构造一个 poll 间隔极小的 executor，避免单测受有界 poll 拖慢。
func newFast(cs *fake.Clientset, cfg Config) *KubernetesExecutor {
	k := NewWithClientset(cs, cfg)
	k.pollInterval = time.Millisecond
	k.answerPollMax = 2
	k.logPollMax = 3
	return k
}

func TestStartContainerCreatesJob(t *testing.T) {
	cs := fake.NewSimpleClientset()
	k := newFast(cs, Config{Namespace: "friday", DefaultImage: "task:latest", RunnerName: "r1"})

	task := ws.TaskPayload{
		TaskID:   "coding-123",
		TaskType: "coding",
		RepoURL:  "https://git.example.com/repo.git",
		Branch:   "master",
		Timeout:  3600,
		Payload: map[string]any{
			"prompt":       "执行编码",
			"remote_tools": []any{map[string]any{"name": "a", "description": "da", "input_schema": map[string]any{}}},
		},
	}

	id, _, err := k.StartContainer(context.Background(), task, "http://cb", "tok")
	if err != nil {
		t.Fatalf("StartContainer err: %v", err)
	}
	wantID := "friday/" + makeJobName("coding-123")
	if id != wantID {
		t.Fatalf("containerID = %q, want %q", id, wantID)
	}

	jobs, err := cs.BatchV1().Jobs("friday").List(context.Background(), metav1.ListOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if len(jobs.Items) != 1 {
		t.Fatalf("want 1 job, got %d", len(jobs.Items))
	}
	j := jobs.Items[0]
	if j.Labels[labelKeyTask] != "coding-123" {
		t.Fatalf("friday.task_id label = %q, want coding-123 (labels=%v)", j.Labels[labelKeyTask], j.Labels)
	}
	if j.Labels[labelKeyRunner] != "r1" {
		t.Fatalf("friday.runner label = %q, want r1", j.Labels[labelKeyRunner])
	}

	env := envOf(j.Spec.Template.Spec.Containers[0].Env)
	if env["FRIDAY_TASK_REMOTE_TOOLS"] == "" {
		t.Fatalf("missing FRIDAY_TASK_REMOTE_TOOLS env (Pitfall 2): %#v", env)
	}
	if env["FRIDAY_TASK_CALLBACK_URL"] != "http://cb" {
		t.Fatalf("FRIDAY_TASK_CALLBACK_URL = %q, want http://cb", env["FRIDAY_TASK_CALLBACK_URL"])
	}
}

func TestWaitContainerReturnsExitCode(t *testing.T) {
	cs := fake.NewSimpleClientset()
	k := newFast(cs, Config{Namespace: "friday", RunnerName: "r1"})

	taskID := "coding-123"
	jobName := makeJobName(taskID)
	containerID := "friday/" + jobName

	resultCh := make(chan int, 1)
	go func() {
		code, logs, err := k.WaitContainer(context.Background(), containerID, 5*time.Second)
		if err != nil {
			t.Errorf("WaitContainer err: %v", err)
		}
		if logs != "" {
			t.Errorf("logs = %q, want empty", logs)
		}
		resultCh <- code
	}()

	// 给 Watch 建立时间，再注入一个 terminated Pod。
	time.Sleep(30 * time.Millisecond)
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      jobName + "-pod",
			Namespace: "friday",
			Labels:    map[string]string{labelKeyJob: jobName},
		},
		Status: corev1.PodStatus{
			ContainerStatuses: []corev1.ContainerStatus{{
				State: corev1.ContainerState{
					Terminated: &corev1.ContainerStateTerminated{ExitCode: 7},
				},
			}},
		},
	}
	if _, err := cs.CoreV1().Pods("friday").Create(context.Background(), pod, metav1.CreateOptions{}); err != nil {
		t.Fatal(err)
	}

	select {
	case code := <-resultCh:
		if code != 7 {
			t.Fatalf("exitCode = %d, want 7", code)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("WaitContainer 未在预期时间内返回")
	}
}

func TestWaitContainerTimeoutReturnsMinusOne(t *testing.T) {
	cs := fake.NewSimpleClientset()
	k := newFast(cs, Config{Namespace: "friday", RunnerName: "r1"})

	code, logs, err := k.WaitContainer(context.Background(), "friday/friday-task-none", 50*time.Millisecond)
	if err != nil {
		t.Fatalf("超时不应返回 err，得到 %v", err)
	}
	if code != -1 {
		t.Fatalf("exitCode = %d, want -1（对齐 docker 超时语义）", code)
	}
	if logs != "" {
		t.Fatalf("logs = %q, want empty", logs)
	}
}

// TestWaitContainerReWatchesOnClosedChannel 验证 CR-01：watch channel 中途关闭
// （server-side watch 超时/瞬时抖动）不得被当作任务终止——必须 re-watch 继续等待，
// 真实终止仍能被检测，且仍在运行的任务不会被误判 failed、其 Job 不会泄漏。
func TestWaitContainerReWatchesOnClosedChannel(t *testing.T) {
	cs := fake.NewSimpleClientset()
	k := newFast(cs, Config{Namespace: "friday", RunnerName: "r1"})

	jobName := makeJobName("coding-rewatch")
	containerID := "friday/" + jobName

	var watchCount int32
	first := watch.NewFake()
	second := watch.NewFake()
	cs.PrependWatchReactor("pods", func(ktesting.Action) (bool, watch.Interface, error) {
		switch atomic.AddInt32(&watchCount, 1) {
		case 1:
			// 模拟 server-side watch 超时：建立后短暂即关闭 channel（不投递终止）。
			go func() {
				time.Sleep(20 * time.Millisecond)
				first.Stop()
			}()
			return true, first, nil
		default:
			return true, second, nil
		}
	})

	resultCh := make(chan int, 1)
	go func() {
		code, logs, err := k.WaitContainer(context.Background(), containerID, 5*time.Second)
		if err != nil {
			t.Errorf("WaitContainer err: %v", err)
		}
		if logs != "" {
			t.Errorf("logs = %q, want empty", logs)
		}
		resultCh <- code
	}()

	// 等第一个 watch 关闭并触发 re-watch；此时绝不能已返回（否则即 CR-01 的误判）。
	time.Sleep(80 * time.Millisecond)
	select {
	case c := <-resultCh:
		t.Fatalf("watch 关闭后 WaitContainer 过早返回 code=%d，应 re-watch 继续等待", c)
	default:
	}
	if atomic.LoadInt32(&watchCount) < 2 {
		t.Fatalf("应在 channel 关闭后重建 watch，watchCount=%d", atomic.LoadInt32(&watchCount))
	}

	// 经第二个（重建后的）watch 投递真实终止，应被检测并返回真实 exitCode。
	second.Modify(&corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      jobName + "-pod",
			Namespace: "friday",
			Labels:    map[string]string{labelKeyJob: jobName},
		},
		Status: corev1.PodStatus{
			ContainerStatuses: []corev1.ContainerStatus{{
				State: corev1.ContainerState{
					Terminated: &corev1.ContainerStateTerminated{ExitCode: 9},
				},
			}},
		},
	})

	select {
	case code := <-resultCh:
		if code != 9 {
			t.Fatalf("re-watch 后 exitCode = %d, want 9", code)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("re-watch 后未检测到真实终止")
	}
}

func TestStreamLogs(t *testing.T) {
	cs := fake.NewSimpleClientset()
	k := newFast(cs, Config{Namespace: "friday", RunnerName: "r1"})

	jobName := "friday-task-abc"
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      jobName + "-pod",
			Namespace: "friday",
			Labels:    map[string]string{labelKeyJob: jobName},
		},
		Status: corev1.PodStatus{Phase: corev1.PodRunning},
	}
	if _, err := cs.CoreV1().Pods("friday").Create(context.Background(), pod, metav1.CreateOptions{}); err != nil {
		t.Fatal(err)
	}

	var lines []string
	err := k.StreamLogs(context.Background(), "friday/"+jobName, func(l string) {
		lines = append(lines, l)
	})
	if err != nil {
		t.Fatalf("StreamLogs err: %v", err)
	}
	if len(lines) == 0 {
		t.Fatalf("expected at least one log line from fake clientset")
	}
}

func TestBuildJobSpec(t *testing.T) {
	cfg := Config{Namespace: "friday", DefaultImage: "img:1", RunnerName: "runner-1", BackoffLimit: 0, TTLSeconds: 3600}
	task := ws.TaskPayload{TaskID: "t1", TaskType: "coding"}
	env := toEnvVars(exec.BuildContainerEnv(task, "http://cb", "tok"))

	job := buildJobSpec(cfg, task, "friday-task-t1", env)

	if got := job.Spec.Template.Spec.RestartPolicy; got != corev1.RestartPolicyNever {
		t.Fatalf("restartPolicy = %q, want Never", got)
	}
	if job.Spec.BackoffLimit == nil || *job.Spec.BackoffLimit != 0 {
		t.Fatalf("backoffLimit = %v, want 0", job.Spec.BackoffLimit)
	}
	if job.Spec.TTLSecondsAfterFinished == nil || *job.Spec.TTLSecondsAfterFinished != 3600 {
		t.Fatalf("ttlSecondsAfterFinished = %v, want 3600", job.Spec.TTLSecondsAfterFinished)
	}
	if job.Labels[labelKeyApp] != labelApp {
		t.Fatalf("app label = %q, want %q", job.Labels[labelKeyApp], labelApp)
	}
	if job.Labels[labelKeyRunner] != "runner-1" {
		t.Fatalf("friday.runner label = %q, want runner-1", job.Labels[labelKeyRunner])
	}
	if job.Spec.Template.Spec.Containers[0].Image != "img:1" {
		t.Fatalf("image = %q, want img:1", job.Spec.Template.Spec.Containers[0].Image)
	}
}

func TestRemoveContainerDeletesJobAndSwallowsNotFound(t *testing.T) {
	cs := fake.NewSimpleClientset()
	k := newFast(cs, Config{Namespace: "friday", RunnerName: "r1"})

	job := newJob("friday", "friday-task-abc", "r1", nil)
	if _, err := cs.BatchV1().Jobs("friday").Create(context.Background(), job, metav1.CreateOptions{}); err != nil {
		t.Fatal(err)
	}

	if err := k.RemoveContainer(context.Background(), "friday/friday-task-abc"); err != nil {
		t.Fatalf("RemoveContainer err: %v", err)
	}
	if _, err := cs.BatchV1().Jobs("friday").Get(context.Background(), "friday-task-abc", metav1.GetOptions{}); !apierrors.IsNotFound(err) {
		t.Fatalf("Job 应已删除，got err=%v", err)
	}

	// 第二次删除（已不存在）应吞 NotFound 返 nil，对齐 docker。
	if err := k.RemoveContainer(context.Background(), "friday/friday-task-abc"); err != nil {
		t.Fatalf("RemoveContainer NotFound 应吞错返 nil，got %v", err)
	}
}

func TestStartupCleanupOnlyRemovesOwnRunnerJobs(t *testing.T) {
	cs := fake.NewSimpleClientset()
	k := newFast(cs, Config{Namespace: "friday", RunnerName: "r1"})

	// 本 runner 两个 Job + 他 runner 一个 Job（同 namespace）。
	mine1 := newJob("friday", "friday-task-mine1", "r1", nil)
	mine2 := newJob("friday", "friday-task-mine2", "r1", nil)
	other := newJob("friday", "friday-task-other", "r2", nil)
	for _, j := range []*batchv1.Job{mine1, mine2, other} {
		if _, err := cs.BatchV1().Jobs("friday").Create(context.Background(), j, metav1.CreateOptions{}); err != nil {
			t.Fatal(err)
		}
	}

	count, err := k.StartupCleanup(context.Background())
	if err != nil {
		t.Fatalf("StartupCleanup err: %v", err)
	}
	if count != 2 {
		t.Fatalf("cleanup count = %d, want 2（仅本 runner）", count)
	}

	remaining, err := cs.BatchV1().Jobs("friday").List(context.Background(), metav1.ListOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if len(remaining.Items) != 1 || remaining.Items[0].Name != "friday-task-other" {
		t.Fatalf("应仅保留他 runner 的 Job，remaining=%v", remaining.Items)
	}
}

func TestZombieScanKillsActiveUnknownAndKeepsKnown(t *testing.T) {
	cs := fake.NewSimpleClientset()
	k := newFast(cs, Config{Namespace: "friday", RunnerName: "r1"})

	old := metav1.NewTime(time.Now().Add(-2 * time.Hour))

	// 活跃僵尸：不在 known、超龄、无终态 → 应删除 + 推 TaskFailed。
	zombie := newJob("friday", "friday-task-zombie", "r1", map[string]string{labelKeyTask: "task-zombie"})
	zombie.CreationTimestamp = old
	// 活跃已知：在 known → 不动。
	knownJob := newJob("friday", "friday-task-known", "r1", map[string]string{labelKeyTask: "task-known"})
	knownJob.CreationTimestamp = old
	for _, j := range []*batchv1.Job{zombie, knownJob} {
		if _, err := cs.BatchV1().Jobs("friday").Create(context.Background(), j, metav1.CreateOptions{}); err != nil {
			t.Fatal(err)
		}
	}

	queue := ws.NewMessageQueue(10)
	known := []string{"friday/friday-task-known"}
	if err := k.ZombieScan(context.Background(), known, queue, 3600, 1); err != nil {
		t.Fatalf("ZombieScan err: %v", err)
	}

	// zombie 应被删，known 应保留。
	if _, err := cs.BatchV1().Jobs("friday").Get(context.Background(), "friday-task-zombie", metav1.GetOptions{}); !apierrors.IsNotFound(err) {
		t.Fatalf("zombie Job 应被删除，got err=%v", err)
	}
	if _, err := cs.BatchV1().Jobs("friday").Get(context.Background(), "friday-task-known", metav1.GetOptions{}); err != nil {
		t.Fatalf("known Job 不应被删除，got err=%v", err)
	}

	msgs := queue.Drain()
	if len(msgs) != 1 {
		t.Fatalf("应推 1 条 TaskFailed，got %d", len(msgs))
	}
	if msgs[0].Type != ws.TypeTaskFailed {
		t.Fatalf("消息类型 = %q, want %q", msgs[0].Type, ws.TypeTaskFailed)
	}
	payload, _ := msgs[0].Payload.(map[string]any)
	if payload["task_id"] != "task-zombie" {
		t.Fatalf("TaskFailed task_id = %v, want task-zombie", payload["task_id"])
	}
	if payload["exit_code"] != -1 {
		t.Fatalf("TaskFailed exit_code = %v, want -1", payload["exit_code"])
	}
}

func TestZombieScanRemovesTerminalRetainedJob(t *testing.T) {
	cs := fake.NewSimpleClientset()
	k := newFast(cs, Config{Namespace: "friday", RunnerName: "r1"})

	doneAt := metav1.NewTime(time.Now().Add(-2 * time.Hour))
	finished := newJob("friday", "friday-task-done", "r1", map[string]string{labelKeyTask: "task-done"})
	finished.Status.Succeeded = 1
	finished.Status.CompletionTime = &doneAt
	if _, err := cs.BatchV1().Jobs("friday").Create(context.Background(), finished, metav1.CreateOptions{}); err != nil {
		t.Fatal(err)
	}

	queue := ws.NewMessageQueue(10)
	if err := k.ZombieScan(context.Background(), nil, queue, 3600, 1); err != nil {
		t.Fatalf("ZombieScan err: %v", err)
	}
	if _, err := cs.BatchV1().Jobs("friday").Get(context.Background(), "friday-task-done", metav1.GetOptions{}); !apierrors.IsNotFound(err) {
		t.Fatalf("超保留期的终态 Job 应被删除，got err=%v", err)
	}
	if queue.Len() != 0 {
		t.Fatalf("终态清理不应推 TaskFailed，got %d", queue.Len())
	}
}

func TestReadContainerFileDegradesGracefully(t *testing.T) {
	cs := fake.NewSimpleClientset()
	k := newFast(cs, Config{Namespace: "friday", RunnerName: "r1"})

	out, err := k.ReadContainerFile(context.Background(), "friday/friday-task-abc", "/app/sessions/x.json")
	if err == nil {
		t.Fatal("ReadContainerFile 应返回非 nil err（k8s 退化语义）")
	}
	if out != "" {
		t.Fatalf("ReadContainerFile 应返回空串，got %q", out)
	}
}

func envOf(items []corev1.EnvVar) map[string]string {
	m := make(map[string]string, len(items))
	for _, e := range items {
		m[e.Name] = e.Value
	}
	return m
}
