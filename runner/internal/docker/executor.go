package docker
import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"time"
	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/filters"
	"github.com/docker/docker/client"
	"github.com/docker/docker/pkg/stdcopy"
	"github.com/docker/go-connections/nat"
	"github.com/google/uuid"
	"github.com/rs/zerolog/log"
	"github.com/friday-ai-codes/friday-ai/runner/internal/ws"
)
// Executor 定义容器执行器接口（为 K8s 预留）。
type Executor interface {
	StartContainer(ctx context.Context, task ws.TaskPayload, callbackURL, callbackToken string) (containerID, answerEndpoint string, err error)
	WaitContainer(ctx context.Context, containerID string, timeout time.Duration) (exitCode int, logs string, err error)
	KillContainer(ctx context.Context, containerID string) error
	RemoveContainer(ctx context.Context, containerID string) error
	StartupCleanup(ctx context.Context) (int, error)
}
// DockerExecutor 通过 Docker API 管理容器生命周期。
type DockerExecutor struct {
	cli client.APIClient
	defaultImage string
}
// NewDockerExecutor 创建 DockerExecutor 并验证连接。
func NewDockerExecutor(defaultImage string) (*DockerExecutor, error) {
	cli, err:= client.NewClientWithOpts(client.FromEnv, client.WithAPIVersionNegotiation)
	if err != nil {
 return nil, fmt.Errorf("创建 Docker 客户端失败: %w", err)
	}
	if _, err:= cli.Ping(context.Background); err != nil {
 return nil, fmt.Errorf("Docker 连接失败: %w", err)
	}
	return &DockerExecutor{cli: cli, defaultImage: defaultImage}, nil
}
func (e *DockerExecutor) StartContainer(ctx context.Context, task ws.TaskPayload, callbackURL, callbackToken string) (string, string, error) {
	name:= fmt.Sprintf("friday-task-%s", uuid.NewString[:12])
	image:= task.Image
	if image == "" {
 image = e.defaultImage
	}
	remoteTools, _:= json.Marshal(task.Payload["remote_tools"])
	env:= string{
 "FRIDAY_SESSION_ID=" + task.TaskID,
 "FRIDAY_TASK_TYPE=" + task.TaskType,
 "FRIDAY_CALLBACK_URL=" + callbackURL,
 "FRIDAY_CALLBACK_TOKEN=" + callbackToken,
 "FRIDAY_GIT_REPO_URL=" + task.RepoURL,
 "FRIDAY_GIT_BRANCH=" + task.Branch,
 fmt.Sprintf("FRIDAY_TASK_TIMEOUT=%d", task.Timeout),
 "FRIDAY_ANSWER_PORT=8977",
 "FRIDAY_REMOTE_TOOLS=" + string(remoteTools),
	}
	exposed, _:= nat.NewPort("tcp", "8977")
	cfg:= &container.Config{
 Image: image,
 Env: env,
 ExposedPorts: nat.PortSet{exposed: struct{}{}},
 Labels: map[string]string{"friday.task_id": task.TaskID},
	}
	hostCfg:= &container.HostConfig{
 PortBindings: nat.PortMap{exposed: nat.PortBinding{{HostIP: "", HostPort: ""}}},
 ExtraHosts: string{"host.docker.internal:host-gateway"},
	}
	resp, err:= e.cli.ContainerCreate(ctx, cfg, hostCfg, nil, nil, name)
	if err != nil {
 return "", "", fmt.Errorf("创建容器失败: %w", err)
	}
	if err:= e.cli.ContainerStart(ctx, resp.ID, container.StartOptions{}); err != nil {
 return "", "", fmt.Errorf("启动容器失败: %w", err)
	}
	info, err:= e.cli.ContainerInspect(ctx, resp.ID)
	if err != nil {
 return resp.ID, "", nil
	}
	var answerEndpoint string
	if bindings, ok:= info.NetworkSettings.Ports[exposed]; ok && len(bindings) > 0 {
 answerEndpoint = fmt.Sprintf("http://host.docker.internal:%s/answer", bindings[0].HostPort)
	}
	log.Info.Str("task_id", task.TaskID).Str("container_id", resp.ID).Str("answer_endpoint", answerEndpoint).Msg("container_started")
	return resp.ID, answerEndpoint, nil
}
func (e *DockerExecutor) WaitContainer(ctx context.Context, containerID string, timeout time.Duration) (int, string, error) {
	waitCtx, cancel:= context.WithTimeout(ctx, timeout)
	defer cancel
	statusCh, errCh:= e.cli.ContainerWait(waitCtx, containerID, container.WaitConditionNotRunning)
	exitCode:= -1
	select {
	case err:= <-errCh:
 if err != nil {
 log.Warn.Str("container_id", containerID).Msg("container_timeout")
 _ = e.KillContainer(ctx, containerID)
 }
	case result:= <-statusCh:
 exitCode = int(result.StatusCode)
	}
	// 读取日志（multiplexed stream 需要 stdcopy 分离）
	logReader, err:= e.cli.ContainerLogs(ctx, containerID, container.LogsOptions{ShowStdout: true, ShowStderr: true, Tail: "2000"})
	if err != nil {
 return exitCode, "", nil
	}
	defer logReader.Close
	var stdout, stderr bytes.Buffer
	_, _ = stdcopy.StdCopy(&stdout, &stderr, logReader)
	logs:= stdout.String + stderr.String
	return exitCode, logs, nil
}
func (e *DockerExecutor) KillContainer(ctx context.Context, containerID string) error {
	err:= e.cli.ContainerKill(ctx, containerID, "KILL")
	if err != nil && !client.IsErrNotFound(err) {
 return err
	}
	return nil
}
func (e *DockerExecutor) RemoveContainer(ctx context.Context, containerID string) error {
	err:= e.cli.ContainerRemove(ctx, containerID, container.RemoveOptions{Force: true})
	if err != nil && !client.IsErrNotFound(err) {
 return err
	}
	return nil
}
func (e *DockerExecutor) StartupCleanup(ctx context.Context) (int, error) {
	containers, err:= e.cli.ContainerList(ctx, container.ListOptions{
 All: true,
 Filters: filters.NewArgs(filters.Arg("label", "friday.task_id")),
	})
	if err != nil {
 return 0, err
	}
	count:= 0
	for _, c:= range containers {
 if err:= e.cli.ContainerRemove(ctx, c.ID, container.RemoveOptions{Force: true}); err != nil && !client.IsErrNotFound(err) {
 log.Warn.Str("container_id", c.ID).Err(err).Msg("cleanup_remove_failed")
 continue
 }
 count++
	}
	log.Info.Int("count", count).Msg("startup_cleanup_completed")
	return count, nil
}
// ZombieScan 扫描僵尸容器：running 且不在 knownIDs 中超过阈值则 kill，exited 超过保留时间则 remove。
func (e *DockerExecutor) ZombieScan(ctx context.Context, knownIDs string, queue *ws.MessageQueue, zombieThreshold, retainHours float64) error {
	containers, err:= e.cli.ContainerList(ctx, container.ListOptions{
 All: true,
 Filters: filters.NewArgs(filters.Arg("label", "friday.task_id")),
	})
	if err != nil {
 return err
	}
	known:= make(map[string]struct{}, len(knownIDs))
	for _, id:= range knownIDs {
 known[id] = struct{}{}
	}
	now:= time.Now.UTC
	for _, c:= range containers {
 taskID:= c.Labels["friday.task_id"]
 if c.State == "running" {
 if _, ok:= known[c.ID]; !ok {
 age:= now.Sub(time.Unix(c.Created, 0)).Seconds
 if age > zombieThreshold {
 _ = e.cli.ContainerKill(ctx, c.ID, "KILL")
 queue.Push(ws.NewMessage(ws.TypeTaskFailed, map[string]any{
 "task_id": taskID, "exit_code": -1,
 "error": "zombie container killed",
 "duration_ms": int(age * 1000), "logs": "",
 }))
 log.Warn.Str("task_id", taskID).Str("container_id", c.ID).Msg("zombie_killed")
 }
 }
 } else if c.State == "exited" {
 // ContainerList 返回的 Created 是创建时间（秒级 epoch），
 // 用 Inspect 获取 FinishedAt 更精确，但为减少 API 调用，
 // 对 exited 容器直接 inspect。
 info, err:= e.cli.ContainerInspect(ctx, c.ID)
 if err != nil {
 continue
 }
 if finished, err:= time.Parse(time.RFC3339Nano, info.State.FinishedAt); err == nil {
 hours:= now.Sub(finished).Hours
 if hours > retainHours {
 _ = e.cli.ContainerRemove(ctx, c.ID, container.RemoveOptions{Force: true})
 log.Info.Str("task_id", taskID).Str("container_id", c.ID).Msg("container_cleaned")
 }
 }
 }
	}
	return nil
}
