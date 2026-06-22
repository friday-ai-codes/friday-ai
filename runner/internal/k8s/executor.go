package k8s

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"strings"
	"time"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/watch"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"

	"github.com/rs/zerolog/log"

	"github.com/friday-ai-codes/friday-ai/runner/internal/exec"
	"github.com/friday-ai-codes/friday-ai/runner/internal/ws"
)

// 编译期接口检查
var _ ws.ExecutorService = (*KubernetesExecutor)(nil)

const (
	defaultPollInterval = 500 * time.Millisecond
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
	// ImagePullPolicy 任务 Pod 镜像拉取策略：always / never / missing（空=missing=
	// PullIfNotPresent）。helm 透传以保证发版后 task 镜像在各节点按需刷新。
	ImagePullPolicy string

	// ActiveDeadlineSeconds >0 时作为 Job 级超时兜底（秒）：runner 永久丢失时由
	// k8s 主动终止超期任务 Job，不再单纯依赖 runner 存活或重启扫描。0=禁用（默认安全）。
	ActiveDeadlineSeconds int64
	// 任务 Pod 的资源 requests/limits（values 注入，留空=不设置，行为同旧版）。
	CPURequest    string
	MemoryRequest string
	CPULimit      string
	MemoryLimit   string
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
	imagePullPolicy string

	activeDeadlineSeconds int64
	cpuRequest            string
	memoryRequest         string
	cpuLimit              string
	memoryLimit           string

	// poll 参数全部有界，避免在 fake clientset / Pod 未就绪时挂死。
	pollInterval time.Duration
	logPollMax   int
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
		cs:                    cs,
		namespace:             ns,
		defaultImage:          cfg.DefaultImage,
		runnerName:            cfg.RunnerName,
		backoffLimit:          cfg.BackoffLimit,
		ttlSeconds:            cfg.TTLSeconds,
		imagePullSecret:       cfg.ImagePullSecret,
		imagePullPolicy:       cfg.ImagePullPolicy,
		activeDeadlineSeconds: cfg.ActiveDeadlineSeconds,
		cpuRequest:            cfg.CPURequest,
		memoryRequest:         cfg.MemoryRequest,
		cpuLimit:              cfg.CPULimit,
		memoryLimit:           cfg.MemoryLimit,
		pollInterval:          defaultPollInterval,
		logPollMax:            defaultLogPollN,
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
		Namespace:             k.namespace,
		DefaultImage:          k.defaultImage,
		RunnerName:            k.runnerName,
		BackoffLimit:          k.backoffLimit,
		TTLSeconds:            k.ttlSeconds,
		ImagePullSecret:       k.imagePullSecret,
		ImagePullPolicy:       k.imagePullPolicy,
		ActiveDeadlineSeconds: k.activeDeadlineSeconds,
		CPURequest:            k.cpuRequest,
		MemoryRequest:         k.memoryRequest,
		CPULimit:              k.cpuLimit,
		MemoryLimit:           k.memoryLimit,
	}
}

// StartContainer 创建 batch/v1 Job 运行任务容器。containerID = "<ns>/<jobName>"。
// env 复用共享 exec.BuildContainerEnv（无前缀漂移）。
//
// answerEndpoint 在 k8s 下恒空（WR-01）：HITL/answer 投递是本阶段已知未支持限制，
// 而新建 Job 的 Pod 几乎不可能在数秒内被调度并分到 IP，旧逻辑同步 poll Pod IP（≈5s）
// 几乎必然耗尽预算返回空串，却串行卡在调度热路径上、给每个 k8s 任务派发凭空增加数秒
// 时延。这里直接返回空（runTask 仅在 answer_endpoint 非空时才推送），消除该税；
// 待 HITL 真正接入时再以惰性/异步方式解析 IP。
func (k *KubernetesExecutor) StartContainer(ctx context.Context, task ws.TaskPayload, callbackURL, callbackToken string) (string, string, error) {
	jobName := makeJobName(task.TaskID)
	env := toEnvVars(exec.BuildContainerEnv(task, callbackURL, callbackToken))
	job := buildJobSpec(k.config(), task, jobName, env)

	if _, err := k.cs.BatchV1().Jobs(k.namespace).Create(ctx, job, metav1.CreateOptions{}); err != nil {
		return "", "", fmt.Errorf("创建 Job 失败: %w", err)
	}
	containerID := k.namespace + "/" + jobName
	log.Info().
		Str("task_id", task.TaskID).
		Str("job", containerID).
		Msg("k8s_job_started")
	return containerID, "", nil
}

// WaitContainer watch Job 的 Pod，取 terminated exitCode。
// 超时返回 (-1, "", nil) 并 best-effort 删 Job（对齐 docker：吞错由 exitCode 表达，
// 仅 API 调用错误才返 err，避免与 ws/client.go 调用方判定分叉，Pitfall 1）。logs 恒空。
//
// k8s watch 不是长生命周期保证：apiserver 会按 minRequestTimeout 主动断流，
// 任何瞬时网络抖动也会关闭 channel。绝不把 channel 关闭当作任务终止——否则长任务
// （AI coding，默认 1800s，可超 watch 窗口）会被误判为 timeout/failed，且因 taskFailed
// 留真导致仍在运行的 Job 泄漏（CR-01）。这里用「List 捕获已终态 + Watch + channel 关闭重建」
// 的循环：仅在 (a) Pod 真正 Terminated（返回真实 exitCode）、(b) 调用方超时（返回 (-1,"",nil)
// 并删 Job）、(c) ctx 取消 时退出。channel 关闭只触发 re-watch，不返回。所有等待均受 wctx 有界。
func (k *KubernetesExecutor) WaitContainer(ctx context.Context, containerID string, timeout time.Duration) (int, string, error) {
	ns, jobName := splitID(containerID)
	wctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	sel := labelKeyJob + "=" + jobName
	for {
		// 先 List 捕获 watch 间隙/启动前已发生的 Terminated（避免漏检），
		// 并以其 resourceVersion 作为 watch 起点，衔接 List→Watch 不丢事件。
		pods, err := k.cs.CoreV1().Pods(ns).List(wctx, metav1.ListOptions{LabelSelector: sel})
		if err != nil {
			if wctx.Err() != nil {
				_ = k.deleteJob(context.Background(), ns, jobName)
				return -1, "", nil
			}
			return -1, "", err
		}
		for i := range pods.Items {
			if code, ok := terminatedExitCode(&pods.Items[i]); ok {
				return code, "", nil
			}
		}

		w, err := k.cs.CoreV1().Pods(ns).Watch(wctx, metav1.ListOptions{
			LabelSelector:   sel,
			ResourceVersion: pods.ResourceVersion,
		})
		if err != nil {
			if wctx.Err() != nil {
				_ = k.deleteJob(context.Background(), ns, jobName)
				return -1, "", nil
			}
			return -1, "", err
		}

		code, done, timedOut := drainWatch(wctx, w)
		w.Stop()
		switch {
		case done:
			return code, "", nil
		case timedOut:
			_ = k.deleteJob(context.Background(), ns, jobName)
			return -1, "", nil
		}
		// channel 关闭但未超时 → 回到循环顶部 re-watch（先 List 再 Watch）。
	}
}

// drainWatch 消费一个 watch channel：Pod Terminated → (exitCode,true,false)；
// wctx 超时/取消 → (-1,false,true)；channel 关闭（!ok）→ (-1,false,false) 表示需 re-watch。
func drainWatch(wctx context.Context, w watch.Interface) (exitCode int, done, timedOut bool) {
	for {
		select {
		case <-wctx.Done():
			return -1, false, true
		case ev, ok := <-w.ResultChan():
			if !ok {
				return -1, false, false
			}
			pod, _ := ev.Object.(*corev1.Pod)
			if pod == nil {
				continue
			}
			if code, term := terminatedExitCode(pod); term {
				return code, true, false
			}
		}
	}
}

// terminatedExitCode 提取 Pod 首容器的终止 exitCode；未终止返回 (0,false)。
func terminatedExitCode(pod *corev1.Pod) (int, bool) {
	if len(pod.Status.ContainerStatuses) == 0 {
		return 0, false
	}
	if t := pod.Status.ContainerStatuses[0].State.Terminated; t != nil {
		return int(t.ExitCode), true
	}
	return 0, false
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

// runnerSelector 构造仅命中本 runner（friday.runner=<name>）任务 Job 的 label selector，
// 用于 StartupCleanup/ZombieScan 隔离多副本，避免误杀同 namespace 其他 runner 在途 Job（Pitfall 3）。
func (k *KubernetesExecutor) runnerSelector() string {
	return fmt.Sprintf("%s=%s,%s=%s", labelKeyApp, labelApp, labelKeyRunner, sanitizeName(k.runnerName))
}

// RemoveContainer 删除 Job（PropagationBackground 连带删 Pod），NotFound 吞错（对齐 docker
// ContainerRemove(Force) + IsErrNotFound）。containerID 形态 "<namespace>/<jobName>"。
func (k *KubernetesExecutor) RemoveContainer(ctx context.Context, containerID string) error {
	ns, jobName := splitID(containerID)
	if ns == "" {
		ns = k.namespace
	}
	return k.deleteJob(ctx, ns, jobName)
}

// StartupCleanup 仅清理本 runner（friday.runner=<name>）残留 Job，返回成功删除计数。
// 必须带 friday.runner 限定，避免同 namespace 多副本误杀彼此在途 Job（Pitfall 3 / T-64-05）。
func (k *KubernetesExecutor) StartupCleanup(ctx context.Context) (int, error) {
	jobs, err := k.cs.BatchV1().Jobs(k.namespace).List(ctx, metav1.ListOptions{LabelSelector: k.runnerSelector()})
	if err != nil {
		return 0, err
	}
	count := 0
	for i := range jobs.Items {
		name := jobs.Items[i].Name
		if derr := k.deleteJob(ctx, k.namespace, name); derr != nil {
			log.Warn().Str("job", k.namespace+"/"+name).Err(derr).Msg("k8s_cleanup_remove_failed")
			continue
		}
		count++
	}
	log.Info().Int("count", count).Msg("k8s_startup_cleanup_completed")
	return count, nil
}

// ZombieScan 按 friday.runner label 扫描本 runner 的 Job：
//   - 活跃（Succeeded==0 && Failed==0）且不在 known（ns/jobName 集）且超 zombieThreshold 秒
//     → 删除 Job 并推 TypeTaskFailed（对齐 docker 僵尸 kill）；
//   - 已终态（Succeeded>0 || Failed>0）且完成超 retainHours 小时 → 删除 Job。
//
// best-effort：单个 API error 仅 log 不中断，整体返回 nil（与 docker ZombieScan 一致）。
func (k *KubernetesExecutor) ZombieScan(ctx context.Context, knownIDs []string, queue *ws.MessageQueue, zombieThreshold, retainHours float64) error {
	jobs, err := k.cs.BatchV1().Jobs(k.namespace).List(ctx, metav1.ListOptions{LabelSelector: k.runnerSelector()})
	if err != nil {
		return err
	}
	known := make(map[string]struct{}, len(knownIDs))
	for _, id := range knownIDs {
		known[id] = struct{}{}
	}
	now := time.Now().UTC()

	for i := range jobs.Items {
		job := &jobs.Items[i]
		id := k.namespace + "/" + job.Name
		taskID := job.Labels[labelKeyTask]
		terminal := job.Status.Succeeded > 0 || job.Status.Failed > 0

		if !terminal {
			if _, ok := known[id]; ok {
				continue
			}
			age := now.Sub(job.CreationTimestamp.Time).Seconds()
			if age <= zombieThreshold {
				continue
			}
			if derr := k.deleteJob(ctx, k.namespace, job.Name); derr != nil {
				log.Warn().Str("job", id).Err(derr).Msg("zombie_delete_failed")
				continue
			}
			queue.Push(ws.NewMessage(ws.TypeTaskFailed, map[string]any{
				"task_id": taskID, "exit_code": -1,
				"error":       "zombie job killed",
				"duration_ms": int(age * 1000), "logs": "",
			}))
			log.Warn().Str("task_id", taskID).Str("job", id).Msg("zombie_killed")
			continue
		}

		// 已终态：完成超保留期则删除。CompletionTime 可能为 nil（如 Failed Job），回退创建时间。
		completed := job.CreationTimestamp.Time
		if job.Status.CompletionTime != nil {
			completed = job.Status.CompletionTime.Time
		}
		if now.Sub(completed).Hours() > retainHours {
			if derr := k.deleteJob(ctx, k.namespace, job.Name); derr != nil {
				log.Warn().Str("job", id).Err(derr).Msg("retained_job_delete_failed")
				continue
			}
			log.Info().Str("task_id", taskID).Str("job", id).Msg("job_cleaned")
		}
	}
	return nil
}

// ReadContainerFile 在 k8s 下 best-effort 退化：Job 的 restartPolicy=Never，容器完成后即终止，
// exec/cp 对已退出 Pod 恒失败，故直接返回错误，让 ws/client.go 既有 log.Warn 容错生效
// （text_output 退化为空、output=nil，任务仍按 exitCode 判 completed，不阻断主流程）。
// 绝不为读文件 exec 已退出容器（恒失败）。完整产物读取（callback 回传 / RWX 共享卷）
// 超出本阶段不动 task 约束（Open Q4），属已知限制。
func (k *KubernetesExecutor) ReadContainerFile(_ context.Context, _, _ string) (string, error) {
	return "", fmt.Errorf("kubernetes executor: ReadContainerFile 未支持已退出 Pod 产物读取（k8s 已知限制）")
}
