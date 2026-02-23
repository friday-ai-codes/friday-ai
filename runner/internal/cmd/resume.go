package cmd
import (
	"fmt"
	"github.com/spf13/cobra"
	"github.com/friday-ai-codes/friday-ai/runner/internal/ui"
)
var resumeCmd = &cobra.Command{
	Use: "resume",
	Short: "恢复 Runner 接收新任务",
	RunE: func(cmd *cobra.Command, _ string) error {
 pid, _:= cmd.Flags.GetInt("pid")
 actual, err:= sendSignal(pid)
 if err != nil {
 return err
 }
 ui.Success(fmt.Sprintf("已发送恢复信号到 Runner (PID %d)", actual))
 return nil
	},
}
func init {
	resumeCmd.Flags.Int("pid", 0, "Runner 进程 PID（默认从 PID 文件读取）")
	rootCmd.AddCommand(resumeCmd)
}
