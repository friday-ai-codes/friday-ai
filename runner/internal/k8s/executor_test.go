package k8s

import (
	"context"
	"testing"
	"time"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes/fake"

	"github.com/friday-ai-codes/friday-ai/runner/internal/exec"
	"github.com/friday-ai-codes/friday-ai/runner/internal/ws"
)

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

func envOf(items []corev1.EnvVar) map[string]string {
	m := make(map[string]string, len(items))
	for _, e := range items {
		m[e.Name] = e.Value
	}
	return m
}
