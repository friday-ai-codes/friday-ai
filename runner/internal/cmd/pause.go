package cmd

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"syscall"

	"github.com/spf13/cobra"

	"github.com/friday-ai-codes/friday-ai/runner/internal/config"
	"github.com/friday-ai-codes/friday-ai/runner/internal/ui"
)

var pauseCmd = &cobra.Command{
	Use:   "pause",
	Short: "暂停 Runner 接收新任务",
	RunE: func(cmd *cobra.Command, _ []string) error {
		pid, _ := cmd.Flags().GetInt("pid")
		actual, err := sendSignal(pid)
		if err != nil {
			return err
		}
		ui.Success(fmt.Sprintf("已发送暂停信号到 Runner (PID %d)", actual))
		return nil
	},
}

func init() {
	pauseCmd.Flags().Int("pid", 0, "Runner 进程 PID（默认从 PID 文件读取）")
	rootCmd.AddCommand(pauseCmd)
}

func sendSignal(pid int) (int, error) {
	if pid == 0 {
		data, err := os.ReadFile(config.PIDFilePath())
		if err != nil {
			ui.Error("未找到运行中的 Runner")
			ui.Hint("请确认 Runner 正在运行，或使用 --pid 指定进程 ID")
			return 0, fmt.Errorf("读取 PID 文件失败: %w", err)
		}
		p, err := strconv.Atoi(strings.TrimSpace(string(data)))
		if err != nil {
			ui.Error("PID 文件内容无效")
			return 0, fmt.Errorf("解析 PID 失败: %w", err)
		}
		pid = p
	}
	return pid, syscall.Kill(pid, syscall.SIGUSR1)
}
