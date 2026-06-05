package cmd

import (
	"context"
	"fmt"

	"github.com/spf13/cobra"

	"github.com/friday-ai-codes/friday-ai/runner/internal/callback"
	"github.com/friday-ai-codes/friday-ai/runner/internal/config"
	"github.com/friday-ai-codes/friday-ai/runner/internal/crypto"
	"github.com/friday-ai-codes/friday-ai/runner/internal/docker"
	"github.com/friday-ai-codes/friday-ai/runner/internal/scheduler"
	"github.com/friday-ai-codes/friday-ai/runner/internal/ui"
	"github.com/friday-ai-codes/friday-ai/runner/internal/ws"
)

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
		var executor ws.ExecutorService
		switch config.GetExecutorType() {
		case "docker", "":
			exec, err := docker.NewDockerExecutor(config.GetDefaultImage())
			if err != nil {
				return fmt.Errorf("初始化 Docker 执行器失败: %w", err)
			}
			executor = exec
		case "kubernetes":
			ui.Error("Kubernetes executor 尚未实现")
			ui.Hint("请在 config.toml 中设置 executor.type = \"docker\"")
			return fmt.Errorf("kubernetes executor 未实现")
		default:
			return fmt.Errorf("未知的 executor 类型: %s", config.GetExecutorType())
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
			DefaultTimeout: config.GetExecutorTimeout(),
		})
	},
}

func init() { rootCmd.AddCommand(runCmd) }
