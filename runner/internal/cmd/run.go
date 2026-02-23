package cmd
import (
	"fmt"
	"github.com/spf13/cobra"
	"github.com/friday-ai-codes/friday-ai/runner/internal/config"
	"github.com/friday-ai-codes/friday-ai/runner/internal/ui"
)
var runCmd = &cobra.Command{
	Use: "run",
	Short: "启动 Runner 主循环",
	RunE: func(_ *cobra.Command, _ string) error {
 if !config.IsRegistered {
 ui.Error("未注册任何 Runner")
 ui.Hint("使用 friday-runner register 注册")
 return fmt.Errorf("未注册")
 }
 ui.Warn("run 命令将在后续版本实现")
 return fmt.Errorf("未实现")
	},
}
func init { rootCmd.AddCommand(runCmd) }
