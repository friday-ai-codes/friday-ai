package k8s

import (
	"crypto/sha256"
	"encoding/hex"
	"strings"

	batchv1 "k8s.io/api/batch/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	"github.com/friday-ai-codes/friday-ai/runner/internal/ws"
)

const (
	labelApp       = "friday-task"
	labelKeyApp    = "app"
	labelKeyTask   = "friday.task_id"
	labelKeyRunner = "friday.runner"
	// labelKeyJob 以 jobName 为值，提供与 taskID sanitize 无关的确定性选择器，
	// 供 WaitContainer/StreamLogs/answerEndpoint 直接由 containerID 派生选择 Pod。
	labelKeyJob   = "friday.job"
	answerPort    = 8977
	jobNamePrefix = "friday-task-"
)

// buildJobSpec 纯函数装配 batch/v1 Job（便于单测 label/env/backoffLimit/ttl/restartPolicy）。
// jobName 由调用方经 makeJobName 计算并传入，保持 StartContainer 与 spec 装配使用同一名称。
func buildJobSpec(cfg Config, task ws.TaskPayload, jobName string, env []corev1.EnvVar) *batchv1.Job {
	image := task.Image
	if image == "" {
		image = cfg.DefaultImage
	}
	labels := map[string]string{
		labelKeyApp:    labelApp,
		labelKeyTask:   sanitizeName(task.TaskID),
		labelKeyRunner: sanitizeName(cfg.RunnerName),
		labelKeyJob:    jobName,
	}
	backoff := cfg.BackoffLimit
	ttl := cfg.TTLSeconds
	podSpec := corev1.PodSpec{
		RestartPolicy: corev1.RestartPolicyNever,
		Containers: []corev1.Container{{
			Name:            "task",
			Image:           image,
			ImagePullPolicy: corev1.PullIfNotPresent,
			Env:             env,
			Ports:           []corev1.ContainerPort{{ContainerPort: answerPort}},
		}},
	}
	if cfg.ImagePullSecret != "" {
		podSpec.ImagePullSecrets = []corev1.LocalObjectReference{{Name: cfg.ImagePullSecret}}
	}
	return &batchv1.Job{
		ObjectMeta: metav1.ObjectMeta{
			Name:      jobName,
			Namespace: cfg.Namespace,
			Labels:    labels,
		},
		Spec: batchv1.JobSpec{
			BackoffLimit:            &backoff,
			TTLSecondsAfterFinished: &ttl,
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{Labels: labels},
				Spec:       podSpec,
			},
		},
	}
}

// toEnvVars 将 docker 形态的 []string("K=V") 适配为 []corev1.EnvVar。
func toEnvVars(items []string) []corev1.EnvVar {
	out := make([]corev1.EnvVar, 0, len(items))
	for _, item := range items {
		if i := strings.IndexByte(item, '='); i >= 0 {
			out = append(out, corev1.EnvVar{Name: item[:i], Value: item[i+1:]})
		}
	}
	return out
}

// sanitizeName 将任意字符串规整为 RFC1123 label（小写 [a-z0-9-]、首尾字母数字、≤63）。
func sanitizeName(s string) string {
	var b strings.Builder
	for _, r := range strings.ToLower(s) {
		if (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') {
			b.WriteRune(r)
		} else {
			b.WriteRune('-')
		}
	}
	out := strings.Trim(b.String(), "-")
	if out == "" {
		out = "x"
	}
	if len(out) > 63 {
		out = strings.Trim(out[:63], "-")
	}
	return out
}

// makeJobName 生成确定性 jobName：friday-task-<sanitized taskID>-<sha8(raw taskID)>。
// 始终拼接源 taskID 的短哈希后缀（WR-02）：sanitizeName 把所有非 [a-z0-9] 规整为 -，
// 不同 taskID（如 Task_1 / task.1 / task-1）会塌缩成同名，仅在超长时补哈希无法避免
// 这类 sanitize 冲突 → 第二个 Jobs.Create 报 AlreadyExists 致任务失败。无条件以源
// taskID 的 sha8 区分，保证不同 taskID 永不撞名，同时确定性可重 get/list 且 ≤63、DNS-1123 合法。
func makeJobName(taskID string) string {
	sum := sha256.Sum256([]byte(taskID))
	short := hex.EncodeToString(sum[:])[:8]
	maxBody := 63 - len(jobNamePrefix) - 1 - len(short)
	body := sanitizeName(taskID)
	if len(body) > maxBody {
		body = strings.Trim(body[:maxBody], "-")
	}
	return jobNamePrefix + body + "-" + short
}

// splitID 解析 containerID（统一形态 "<namespace>/<jobName>"）。
func splitID(containerID string) (namespace, jobName string) {
	if i := strings.Index(containerID, "/"); i >= 0 {
		return containerID[:i], containerID[i+1:]
	}
	return "", containerID
}
