package cmd

import (
	"context"
	"fmt"

	"github.com/spf13/cobra"

	"github.com/friday-ai-codes/friday-ai/runner/internal/callback"
	"github.com/friday-ai-codes/friday-ai/runner/internal/config"
	"github.com/friday-ai-codes/friday-ai/runner/internal/crypto"
	"github.com/friday-ai-codes/friday-ai/runner/internal/docker"
	"github.com/friday-ai-codes/friday-ai/runner/internal/k8s"
	"github.com/friday-ai-codes/friday-ai/runner/internal/scheduler"
	"github.com/friday-ai-codes/friday-ai/runner/internal/ui"
	"github.com/friday-ai-codes/friday-ai/runner/internal/ws"
)

// resolveExecutorKind 归一 executor 类型：docker/""→docker，kubernetes/k8s→kubernetes，其余报错。
func resolveExecutorKind(raw string) (string, error) {
	switch raw {
	case "docker", "":
		return "docker", nil
	case "kubernetes", "k8s":
		return "kubernetes", nil
	default:
		return "", fmt.Errorf("未知的 executor 类型: %s", raw)
	}
}

var runCmd = &cobra.Command{
	Use:   "run",
	Short: "启动 Runner 主循环",
	RunE: func(_ *cobra.Command, _ []string) error {
		if !config.IsRegistered() {
			ui.Error("未注册任何 Runner")
			ui.Hint("使用 friday-runner register 注册")
			return fmt.Errorf("未注册")
		}
		key, err := crypto.GetOrCreateKey()
		if err != nil {
			return fmt.Errorf("读取密钥失败: %w", err)
		}
		token, err := crypto.Decrypt(key, config.GetToken())
		if err != nil {
			return fmt.Errorf("解密 token 失败: %w", err)
		}
		kind, err := resolveExecutorKind(config.GetExecutorType())
		if err != nil {
			return err
		}
		var executor ws.ExecutorService
		switch kind {
		case "docker":
			exec, err := docker.NewDockerExecutor(config.GetDefaultImage())
			if err != nil {
				return fmt.Errorf("初始化 Docker 执行器失败: %w", err)
			}
			executor = exec
		case "kubernetes":
			exec, err := k8s.New(k8s.Config{
				Namespace:             config.GetK8sNamespace(),
				DefaultImage:          config.GetDefaultImage(),
				RunnerName:            config.GetRunnerName(),
				BackoffLimit:          int32(config.GetK8sBackoffLimit()),
				TTLSeconds:            int32(config.GetK8sTTLSeconds()),
				ImagePullSecret:       config.GetK8sImagePullSecret(),
				ActiveDeadlineSeconds: config.GetK8sActiveDeadline(),
				CPURequest:            config.GetK8sCPURequest(),
				MemoryRequest:         config.GetK8sMemoryRequest(),
				CPULimit:              config.GetK8sCPULimit(),
				MemoryLimit:           config.GetK8sMemoryLimit(),
			})
			if err != nil {
				return fmt.Errorf("初始化 Kubernetes 执行器失败: %w", err)
			}
			executor = exec
		}
		sched := scheduler.New(config.GetConcurrent())
		return ws.Run(context.Background(), ws.Config{
			ServerURL:  config.GetServerURL(),
			Token:      string(token),
			Name:       config.GetRunnerName(),
			Version:    "5.0.0",
			Concurrent: config.GetConcurrent(),
			Executor:   executor,
			Scheduler:  sched,
			CallbackFactory: func(q *ws.MessageQueue, cbToken string, port int) ws.CallbackService {
				return callback.New(q, cbToken, port)
			},
			CallbackPort:   config.GetCallbackPort(),
			CallbackHost:   config.GetCallbackHost(),
			DefaultTimeout: config.GetExecutorTimeout(),
		})
	},
}

func init() { rootCmd.AddCommand(runCmd) }
