package k8s

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"

	"github.com/rs/zerolog/log"

	"github.com/friday-ai-codes/friday-ai/runner/internal/exec"
	"github.com/friday-ai-codes/friday-ai/runner/internal/ws"
)

// ErrNotImplemented 标记本 plan 暂未实现、留待 64-02 的方法。
var ErrNotImplemented = errors.New("kubernetes executor: not implemented")

// 编译期接口检查
var _ ws.ExecutorService = (*KubernetesExecutor)(nil)

const (
	defaultPollInterval = 500 * time.Millisecond
	defaultAnswerPollN  = 10 // *500ms ≈ 5s，best-effort 拿 Pod IP 的上限
	defaultLogPollN     = 30 // *500ms ≈ 15s，等 Pod 离开 Pending 的上限
)

// Config 是 KubernetesExecutor 的构造配置。
type Config struct {
	Namespace       string
	DefaultImage    string
	RunnerName      string
	BackoffLimit    int32
	TTLSeconds      int32
	ImagePullSecret string
}

// KubernetesExecutor 经 k8s API（client-go）以 Job 形态运行任务容器。
// containerID 统一为 "<namespace>/<jobName>"，确定性可重 get/list。
type KubernetesExecutor struct {
	cs              kubernetes.Interface
	namespace       string
	defaultImage    string
	runnerName      string
	backoffLimit    int32
	ttlSeconds      int32
	imagePullSecret string

	// poll 参数全部有界，避免在 fake clientset / Pod 未就绪时挂死。
	pollInterval  time.Duration
	answerPollMax int
	logPollMax    int
}

// New 构造 KubernetesExecutor：优先 in-cluster config，回退 kubeconfig（dev）。
func New(cfg Config) (*KubernetesExecutor, error) {
	restCfg, err := newRestConfig()
	if err != nil {
		return nil, fmt.Errorf("构建 k8s 客户端配置失败: %w", err)
	}
	cs, err := kubernetes.NewForConfig(restCfg)
	if err != nil {
		return nil, fmt.Errorf("创建 k8s 客户端失败: %w", err)
	}
	ns := cfg.Namespace
	if ns == "" {
		ns = detectNamespace()
	}
	return newExecutor(cs, cfg, ns), nil
}

// NewWithClientset 用注入的 clientset 构造（单测专用，不连真集群）。
func NewWithClientset(cs kubernetes.Interface, cfg Config) *KubernetesExecutor {
	ns := cfg.Namespace
	if ns == "" {
		ns = "default"
	}
	return newExecutor(cs, cfg, ns)
}

func newExecutor(cs kubernetes.Interface, cfg Config, ns string) *KubernetesExecutor {
	return &KubernetesExecutor{
		cs:              cs,
		namespace:       ns,
		defaultImage:    cfg.DefaultImage,
		runnerName:      cfg.RunnerName,
		backoffLimit:    cfg.BackoffLimit,
		ttlSeconds:      cfg.TTLSeconds,
		imagePullSecret: cfg.ImagePullSecret,
		pollInterval:    defaultPollInterval,
		answerPollMax:   defaultAnswerPollN,
		logPollMax:      defaultLogPollN,
	}
}

func newRestConfig() (*rest.Config, error) {
	if cfg, err := rest.InClusterConfig(); err == nil {
		return cfg, nil
	}
	rules := clientcmd.NewDefaultClientConfigLoadingRules()
	return clientcmd.NewNonInteractiveDeferredLoadingClientConfig(
		rules, &clientcmd.ConfigOverrides{}).ClientConfig()
}

func detectNamespace() string {
	const saNamespaceFile = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
	if data, err := os.ReadFile(saNamespaceFile); err == nil {
		if ns := strings.TrimSpace(string(data)); ns != "" {
			return ns
		}
	}
	return "default"
}

func (k *KubernetesExecutor) config() Config {
	return Config{
		Namespace:       k.namespace,
		DefaultImage:    k.defaultImage,
		RunnerName:      k.runnerName,
		BackoffLimit:    k.backoffLimit,
		TTLSeconds:      k.ttlSeconds,
		ImagePullSecret: k.imagePullSecret,
	}
}

// StartContainer 创建 batch/v1 Job 运行任务容器。containerID = "<ns>/<jobName>"。
// env 复用共享 exec.BuildContainerEnv（无前缀漂移）。answerEndpoint best-effort：
// 有界 poll Pod IP，拿不到返回空（对齐 docker inspect 失败回退，不阻断主流程）。
func (k *KubernetesExecutor) StartContainer(ctx context.Context, task ws.TaskPayload, callbackURL, callbackToken string) (string, string, error) {
	jobName := makeJobName(task.TaskID)
	env := toEnvVars(exec.BuildContainerEnv(task, callbackURL, callbackToken))
	job := buildJobSpec(k.config(), task, jobName, env)

	if _, err := k.cs.BatchV1().Jobs(k.namespace).Create(ctx, job, metav1.CreateOptions{}); err != nil {
		return "", "", fmt.Errorf("创建 Job 失败: %w", err)
	}
	containerID := k.namespace + "/" + jobName
	answerEndpoint := k.pollAnswerEndpoint(ctx, jobName)
	log.Info().
		Str("task_id", task.TaskID).
		Str("job", containerID).
		Str("answer_endpoint", answerEndpoint).
		Msg("k8s_job_started")
	return containerID, answerEndpoint, nil
}

// pollAnswerEndpoint 有界 poll Job 的 Pod，拿到 Pod IP 即拼 answerEndpoint，否则返回空。
func (k *KubernetesExecutor) pollAnswerEndpoint(ctx context.Context, jobName string) string {
	sel := labelKeyJob + "=" + jobName
	for i := 0; i < k.answerPollMax; i++ {
		pods, err := k.cs.CoreV1().Pods(k.namespace).List(ctx, metav1.ListOptions{LabelSelector: sel})
		if err == nil {
			for idx := range pods.Items {
				if ip := pods.Items[idx].Status.PodIP; ip != "" {
					return fmt.Sprintf("http://%s:%d/answer", ip, answerPort)
				}
			}
		}
		select {
		case <-ctx.Done():
			return ""
		case <-time.After(k.pollInterval):
		}
	}
	return ""
}

// WaitContainer watch Job 的 Pod，取 terminated exitCode。
// 超时返回 (-1, "", nil) 并 best-effort 删 Job（对齐 docker：吞错由 exitCode 表达，
// 仅 API 调用错误才返 err，避免与 ws/client.go 调用方判定分叉，Pitfall 1）。logs 恒空。
func (k *KubernetesExecutor) WaitContainer(ctx context.Context, containerID string, timeout time.Duration) (int, string, error) {
	ns, jobName := splitID(containerID)
	wctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	sel := labelKeyJob + "=" + jobName
	w, err := k.cs.CoreV1().Pods(ns).Watch(wctx, metav1.ListOptions{LabelSelector: sel})
	if err != nil {
		return -1, "", err
	}
	defer w.Stop()

	for {
		select {
		case <-wctx.Done():
			_ = k.deleteJob(context.Background(), ns, jobName)
			return -1, "", nil
		case ev, ok := <-w.ResultChan():
			if !ok {
				return -1, "", nil
			}
			pod, _ := ev.Object.(*corev1.Pod)
			if pod == nil || len(pod.Status.ContainerStatuses) == 0 {
				continue
			}
			if t := pod.Status.ContainerStatuses[0].State.Terminated; t != nil {
				return int(t.ExitCode), "", nil
			}
		}
	}
}

// StreamLogs 经 Pods.GetLogs(Follow) 逐行回调 onLine。ctx 取消即止。
func (k *KubernetesExecutor) StreamLogs(ctx context.Context, containerID string, onLine func(string)) error {
	ns, jobName := splitID(containerID)
	podName, err := k.waitPodReady(ctx, ns, jobName)
	if err != nil {
		return err
	}
	if podName == "" {
		// ctx 取消或 Pod 始终未就绪：优雅退出（对齐 docker 流随容器在的语义）。
		return nil
	}
	req := k.cs.CoreV1().Pods(ns).GetLogs(podName, &corev1.PodLogOptions{Follow: true})
	stream, err := req.Stream(ctx)
	if err != nil {
		return fmt.Errorf("获取 Pod 日志流失败: %w", err)
	}
	defer stream.Close()

	s := bufio.NewScanner(stream)
	for s.Scan() {
		onLine(s.Text())
	}
	return s.Err()
}

// waitPodReady 有界 poll，等 Job 的 Pod 离开 Pending（GetLogs 在 Pending 期会报错）。
func (k *KubernetesExecutor) waitPodReady(ctx context.Context, ns, jobName string) (string, error) {
	sel := labelKeyJob + "=" + jobName
	for i := 0; i < k.logPollMax; i++ {
		pods, err := k.cs.CoreV1().Pods(ns).List(ctx, metav1.ListOptions{LabelSelector: sel})
		if err != nil {
			return "", err
		}
		for idx := range pods.Items {
			if pods.Items[idx].Status.Phase != corev1.PodPending {
				return pods.Items[idx].Name, nil
			}
		}
		select {
		case <-ctx.Done():
			return "", nil
		case <-time.After(k.pollInterval):
		}
	}
	return "", nil
}

// deleteJob 删除 Job（Background propagation 连带 Pod），NotFound 吞错。供 WaitContainer 超时清理。
func (k *KubernetesExecutor) deleteJob(ctx context.Context, ns, jobName string) error {
	policy := metav1.DeletePropagationBackground
	err := k.cs.BatchV1().Jobs(ns).Delete(ctx, jobName, metav1.DeleteOptions{PropagationPolicy: &policy})
	if err != nil && !apierrors.IsNotFound(err) {
		return err
	}
	return nil
}

// 以下方法留待 64-02 实现，暂返回 ErrNotImplemented 以满足编译期接口检查。

func (k *KubernetesExecutor) ReadContainerFile(_ context.Context, _, _ string) (string, error) {
	return "", ErrNotImplemented
}

func (k *KubernetesExecutor) RemoveContainer(_ context.Context, _ string) error {
	return ErrNotImplemented
}

func (k *KubernetesExecutor) StartupCleanup(_ context.Context) (int, error) {
	return 0, ErrNotImplemented
}

func (k *KubernetesExecutor) ZombieScan(_ context.Context, _ []string, _ *ws.MessageQueue, _, _ float64) error {
	return ErrNotImplemented
}
