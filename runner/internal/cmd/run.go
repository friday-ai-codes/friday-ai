package cmd
import (
	"context"
	"fmt"
	"github.com/spf13/cobra"
	"github.com/friday-ai-codes/friday-ai/runner/internal/config"
	"github.com/friday-ai-codes/friday-ai/runner/internal/crypto"
	"github.com/friday-ai-codes/friday-ai/runner/internal/ui"
	"github.com/friday-ai-codes/friday-ai/runner/internal/ws"
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
 key, err:= crypto.GetOrCreateKey
 if err != nil {
 return fmt.Errorf("读取密钥失败: %w", err)
 }
 token, err:= crypto.Decrypt(key, config.GetToken)
 if err != nil {
 return fmt.Errorf("解密 token 失败: %w", err)
 }
 return ws.Run(context.Background, ws.Config{
 ServerURL: config.GetServerURL,
 Token: string(token),
 Name: config.GetRunnerName,
 Version: "5.0.0",
 Concurrent: config.GetConcurrent,
 })
	},
}
func init { rootCmd.AddCommand(runCmd) }
