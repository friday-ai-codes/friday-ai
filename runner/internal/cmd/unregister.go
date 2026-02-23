package cmd
import (
	"fmt"
	"os"
	"github.com/charmbracelet/huh"
	"github.com/spf13/cobra"
	"github.com/friday-ai-codes/friday-ai/runner/internal/api"
	"github.com/friday-ai-codes/friday-ai/runner/internal/config"
	"github.com/friday-ai-codes/friday-ai/runner/internal/crypto"
	"github.com/friday-ai-codes/friday-ai/runner/internal/ui"
)
var unregisterCmd = &cobra.Command{
	Use: "unregister",
	Short: "注销 Runner 并清除本地配置",
	RunE: runUnregister,
}
func init {
	unregisterCmd.Flags.BoolP("force", "f", false, "跳过确认直接注销")
	rootCmd.AddCommand(unregisterCmd)
}
func runUnregister(cmd *cobra.Command, _ string) error {
	if !config.IsRegistered {
 ui.Error("未注册任何 Runner")
 return fmt.Errorf("未注册")
	}
	name:= config.GetRunnerName
	force, _:= cmd.Flags.GetBool("force")
	if !force {
 var confirmed bool
 err:= huh.NewConfirm.
 Title(fmt.Sprintf("确定要注销 Runner '%s' 吗？", name)).
 Value(&confirmed).Run
 if err != nil {
 return fmt.Errorf("输入取消: %w", err)
 }
 if !confirmed {
 return nil
 }
	}
	// 解密 token 并调用 API 注销
	key, err:= crypto.GetOrCreateKey
	if err == nil {
 token, decErr:= crypto.Decrypt(key, config.GetToken)
 if decErr == nil {
 if apiErr:= api.NewClient(config.GetServerURL).Unregister(string(token)); apiErr != nil {
 ui.Warn(fmt.Sprintf("服务端注销失败: %s，仅清除本地配置", apiErr))
 }
 }
	}
	// 删除配置文件
	_ = os.Remove(config.ConfigFilePath)
	ui.Success(fmt.Sprintf("Runner '%s' 已注销", name))
	return nil
}
