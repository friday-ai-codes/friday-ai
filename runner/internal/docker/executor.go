package docker

import (
	"archive/tar"
	"bufio"
	"context"
	"fmt"
	"io"
	"time"

	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/filters"
	imagetypes "github.com/docker/docker/api/types/image"
	"github.com/docker/docker/client"
	"github.com/docker/docker/pkg/stdcopy"
	"github.com/docker/go-connections/nat"
	"github.com/google/uuid"
	"github.com/rs/zerolog/log"

	"github.com/friday-ai-codes/friday-ai/runner/internal/exec"
	"github.com/friday-ai-codes/friday-ai/runner/internal/ws"
)

// Executor 定义容器执行器接口（为 K8s 预留）。
type Executor interface {
	StartContainer(ctx context.Context, task ws.TaskPayload, callbackURL, callbackToken string) (containerID, answerEndpoint string, err error)
	WaitContainer(ctx context.Context, containerID string, timeout time.Duration) (exitCode int, logs string, err error)
	ReadContainerFile(ctx context.Context, containerID, path string) (string, error)
	StreamLogs(ctx context.Context, containerID string, onLine func(line string)) error
	KillContainer(ctx context.Context, containerID string) error
	RemoveContainer(ctx context.Context, containerID string) error
	StartupCleanup(ctx context.Context) (int, error)
}

// DockerExecutor 通过 Docker API 管理容器生命周期。
type DockerExecutor struct {
	cli          client.APIClient
	defaultImage string
}

// NewDockerExecutor 创建 DockerExecutor 并验证连接。
func NewDockerExecutor(defaultImage string) (*DockerExecutor, error) {
	cli, err := client.NewClientWithOpts(client.FromEnv, client.WithAPIVersionNegotiation())
	if err != nil {
		return nil, fmt.Errorf("创建 Docker 客户端失败: %w", err)
	}
	if _, err := cli.Ping(context.Background()); err != nil {
		return nil, fmt.Errorf("Docker 连接失败: %w", err)
	}
	return &DockerExecutor{cli: cli, defaultImage: defaultImage}, nil
}

func (e *DockerExecutor) StartContainer(ctx context.Context, task ws.TaskPayload, callbackURL, callbackToken string) (string, string, error) {
	name := fmt.Sprintf("friday-task-%s", uuid.NewString()[:12])
	image := task.Image
	if image == "" {
		image = e.defaultImage
	}
	if err := e.ensureImage(ctx, image); err != nil {
		return "", "", err
	}
	env := buildContainerEnv(task, callbackURL, callbackToken)
	exposed, _ := nat.NewPort("tcp", "8977")
	cfg := &container.Config{
		Image:        image,
		Env:          env,
		ExposedPorts: nat.PortSet{exposed: struct{}{}},
		Labels:       map[string]string{"friday.task_id": task.TaskID},
	}
	hostCfg := &container.HostConfig{
		PortBindings: nat.PortMap{exposed: []nat.PortBinding{{HostIP: "", HostPort: ""}}},
		ExtraHosts:   []string{"host.docker.internal:host-gateway"},
	}
	resp, err := e.cli.ContainerCreate(ctx, cfg, hostCfg, nil, nil, name)
	if err != nil {
		return "", "", fmt.Errorf("创建容器失败: %w", err)
	}
	if err := e.cli.ContainerStart(ctx, resp.ID, container.StartOptions{}); err != nil {
		return "", "", fmt.Errorf("启动容器失败: %w", err)
	}
	info, err := e.cli.ContainerInspect(ctx, resp.ID)
	if err != nil {
		return resp.ID, "", nil
	}
	var answerEndpoint string
	if bindings, ok := info.NetworkSettings.Ports[exposed]; ok && len(bindings) > 0 {
		answerEndpoint = fmt.Sprintf("http://host.docker.internal:%s/answer", bindings[0].HostPort)
	}
	log.Info().Str("task_id", task.TaskID).Str("container_id", resp.ID).Str("answer_endpoint", answerEndpoint).Msg("container_started")
	return resp.ID, answerEndpoint, nil
}

// ensureImage 确保镜像在本地存在；不存在时从 registry 拉取。
// Runner 创建的是宿主 daemon 上的兄弟容器，compose 不会替 task 镜像做 pull，
// 因此首次使用发版镜像（ghcr.io/.../task）时必须在这里兜底拉取。
func (e *DockerExecutor) ensureImage(ctx context.Context, ref string) error {
	_, err := e.cli.ImageInspect(ctx, ref)
	if err == nil {
		return nil
	}
	if !client.IsErrNotFound(err) {
		return fmt.Errorf("检查镜像失败: %w", err)
	}
	log.Info().Str("image", ref).Msg("image_pull_started")
	reader, err := e.cli.ImagePull(ctx, ref, imagetypes.PullOptions{})
	if err != nil {
		return fmt.Errorf("拉取镜像失败: %w", err)
	}
	defer reader.Close()
	// 必须读完响应流，pull 才会真正完成
	if _, err := io.Copy(io.Discard, reader); err != nil {
		return fmt.Errorf("拉取镜像中断: %w", err)
	}
	log.Info().Str("image", ref).Msg("image_pull_completed")
	return nil
}

// buildContainerEnv 薄委托共享的 exec.BuildContainerEnv，保持函数名/签名不变以使
// docker executor_test.go 逐字不改（零回归命门，Pitfall 6）。
func buildContainerEnv(task ws.TaskPayload, callbackURL, callbackToken string) []string {
	return exec.BuildContainerEnv(task, callbackURL, callbackToken)
}

func (e *DockerExecutor) WaitContainer(ctx context.Context, containerID string, timeout time.Duration) (int, string, error) {
	waitCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	statusCh, errCh := e.cli.ContainerWait(waitCtx, containerID, container.WaitConditionNotRunning)
	exitCode := -1
	select {
	case err := <-errCh:
		if err != nil {
			log.Warn().Str("container_id", containerID).Msg("container_timeout")
			_ = e.KillContainer(ctx, containerID)
		}
	case result := <-statusCh:
		exitCode = int(result.StatusCode)
	}

	return exitCode, "", nil
}

// StreamLogs 实时逐行读取容器日志，每行调用 onLine 回调。ctx 取消时自动终止。
func (e *DockerExecutor) StreamLogs(ctx context.Context, containerID string, onLine func(line string)) error {
	reader, err := e.cli.ContainerLogs(ctx, containerID, container.LogsOptions{
		ShowStdout: true, ShowStderr: true, Follow: true,
	})
	if err != nil {
		return fmt.Errorf("获取容器日志流失败: %w", err)
	}
	defer reader.Close()

	pr, pw := io.Pipe()
	go func() {
		_, _ = stdcopy.StdCopy(pw, pw, reader)
		pw.Close()
	}()

	s := bufio.NewScanner(pr)
	for s.Scan() {
		onLine(s.Text())
	}
	return s.Err()
}

func (e *DockerExecutor) ReadContainerFile(ctx context.Context, containerID, path string) (string, error) {
	reader, _, err := e.cli.CopyFromContainer(ctx, containerID, path)
	if err != nil {
		return "", fmt.Errorf("从容器读取文件失败: %w", err)
	}
	defer reader.Close()

	tr := tar.NewReader(reader)
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return "", fmt.Errorf("读取容器归档失败: %w", err)
		}
		if hdr.Typeflag != tar.TypeReg {
			continue
		}
		data, err := io.ReadAll(tr)
		if err != nil {
			return "", fmt.Errorf("读取容器文件内容失败: %w", err)
		}
		return string(data), nil
	}

	return "", fmt.Errorf("容器文件不存在: %s", path)
}

func (e *DockerExecutor) KillContainer(ctx context.Context, containerID string) error {
	err := e.cli.ContainerKill(ctx, containerID, "KILL")
	if err != nil && !client.IsErrNotFound(err) {
		return err
	}
	return nil
}

func (e *DockerExecutor) RemoveContainer(ctx context.Context, containerID string) error {
	err := e.cli.ContainerRemove(ctx, containerID, container.RemoveOptions{Force: true})
	if err != nil && !client.IsErrNotFound(err) {
		return err
	}
	return nil
}

func (e *DockerExecutor) StartupCleanup(ctx context.Context) (int, error) {
	containers, err := e.cli.ContainerList(ctx, container.ListOptions{
		All:     true,
		Filters: filters.NewArgs(filters.Arg("label", "friday.task_id")),
	})
	if err != nil {
		return 0, err
	}
	count := 0
	for _, c := range containers {
		if err := e.cli.ContainerRemove(ctx, c.ID, container.RemoveOptions{Force: true}); err != nil && !client.IsErrNotFound(err) {
			log.Warn().Str("container_id", c.ID).Err(err).Msg("cleanup_remove_failed")
			continue
		}
		count++
	}
	log.Info().Int("count", count).Msg("startup_cleanup_completed")
	return count, nil
}

// ZombieScan 扫描僵尸容器：running 且不在 knownIDs 中超过阈值则 kill，exited 超过保留时间则 remove。
func (e *DockerExecutor) ZombieScan(ctx context.Context, knownIDs []string, queue *ws.MessageQueue, zombieThreshold, retainHours float64) error {
	containers, err := e.cli.ContainerList(ctx, container.ListOptions{
		All:     true,
		Filters: filters.NewArgs(filters.Arg("label", "friday.task_id")),
	})
	if err != nil {
		return err
	}

	known := make(map[string]struct{}, len(knownIDs))
	for _, id := range knownIDs {
		known[id] = struct{}{}
	}
	now := time.Now().UTC()

	for _, c := range containers {
		taskID := c.Labels["friday.task_id"]

		if c.State == "running" {
			if _, ok := known[c.ID]; !ok {
				age := now.Sub(time.Unix(c.Created, 0)).Seconds()
				if age > zombieThreshold {
					_ = e.cli.ContainerKill(ctx, c.ID, "KILL")
					queue.Push(ws.NewMessage(ws.TypeTaskFailed, map[string]any{
						"task_id": taskID, "exit_code": -1,
						"error":       "zombie container killed",
						"duration_ms": int(age * 1000), "logs": "",
					}))
					log.Warn().Str("task_id", taskID).Str("container_id", c.ID).Msg("zombie_killed")
				}
			}
		} else if c.State == "exited" {
			// ContainerList 返回的 Created 是创建时间（秒级 epoch），
			// 用 Inspect 获取 FinishedAt 更精确，但为减少 API 调用，
			// 对 exited 容器直接 inspect。
			info, err := e.cli.ContainerInspect(ctx, c.ID)
			if err != nil {
				continue
			}
			if finished, err := time.Parse(time.RFC3339Nano, info.State.FinishedAt); err == nil {
				hours := now.Sub(finished).Hours()
				if hours > retainHours {
					_ = e.cli.ContainerRemove(ctx, c.ID, container.RemoveOptions{Force: true})
					log.Info().Str("task_id", taskID).Str("container_id", c.ID).Msg("container_cleaned")
				}
			}
		}
	}
	return nil
}
