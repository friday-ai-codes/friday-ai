package cmd
import (
	"fmt"
	"net/url"
	"os"
	"strings"
	"github.com/charmbracelet/huh"
	"github.com/spf13/cobra"
	"github.com/friday-ai-codes/friday-ai/runner/internal/api"
	"github.com/friday-ai-codes/friday-ai/runner/internal/config"
	"github.com/friday-ai-codes/friday-ai/runner/internal/crypto"
	"github.com/friday-ai-codes/friday-ai/runner/internal/ui"
)
var registerCmd = &cobra.Command{
	Use: "register",
	Short: "注册 Runner 到 Friday 服务端",
	RunE: runRegister,
}
func init {
	f:= registerCmd.Flags
	f.String("url", "", "Friday 服务端地址")
	f.String("token", "", "注册令牌")
	f.String("name", "", "Runner 名称（默认主机名）")
	f.String("scope", "global", "Runner 作用域")
	f.Int("concurrent", 0, "并发数（0 = 自动检测）")
	rootCmd.AddCommand(registerCmd)
}
func runRegister(cmd *cobra.Command, _ string) error {
	if config.IsRegistered {
 ui.Error("已注册，请先执行 friday-runner unregister")
 ui.Hint("friday-runner unregister --force")
 return fmt.Errorf("已注册")
	}
	serverURL, _:= cmd.Flags.GetString("url")
	token, _:= cmd.Flags.GetString("token")
	name, _:= cmd.Flags.GetString("name")
	scope, _:= cmd.Flags.GetString("scope")
	concurrent, _:= cmd.Flags.GetInt("concurrent")
	// 交互式提示缺失的必要参数
	if serverURL == "" || token == "" {
 fields:= make(huh.Field, 0, 2)
 if serverURL == "" {
 fields = append(fields, huh.NewInput.Title("Server URL").Value(&serverURL))
 }
 if token == "" {
 fields = append(fields, huh.NewInput.Title("注册令牌").Value(&token).EchoMode(huh.EchoModePassword))
 }
 if err:= huh.NewForm(huh.NewGroup(fields...)).Run; err != nil {
 return fmt.Errorf("输入取消: %w", err)
 }
	}
	if name == "" {
 name, _ = os.Hostname
	}
	if concurrent == 0 {
 concurrent = config.DetectConcurrent
	}
	serverURL = strings.TrimRight(serverURL, "/")
	if !strings.HasPrefix(serverURL, "http://") && !strings.HasPrefix(serverURL, "https://") {
 serverURL = "http://" + serverURL
	}
	if _, err:= url.ParseRequestURI(serverURL); err != nil {
 ui.Error("无效的 Server URL")
 return fmt.Errorf("无效 URL: %w", err)
	}
	// 调用 API 注册
	resp, err:= api.NewClient(serverURL).Register(api.RegisterRequest{
 Token: token,
 Name: name,
 Scope: scope,
 Concurrent: concurrent,
 Version: Version,
	})
	if err != nil {
 ui.Error(fmt.Sprintf("注册失败: %s", err))
 ui.Hint("请检查 token 是否过期，重新获取: friday-runner register --help")
 return fmt.Errorf("注册失败: %w", err)
	}
	// 加密 runner_token 并保存配置
	key, err:= crypto.GetOrCreateKey
	if err != nil {
 return fmt.Errorf("密钥错误: %w", err)
	}
	encrypted, err:= crypto.Encrypt(key, byte(resp.RunnerToken))
	if err != nil {
 return fmt.Errorf("加密失败: %w", err)
	}
	if err:= config.SaveConfig(serverURL, encrypted, resp.Name, concurrent); err != nil {
 return fmt.Errorf("保存配置失败: %w", err)
	}
	ui.Success("注册成功")
	ui.Info(fmt.Sprintf("Runner: %s", resp.Name))
	ui.Info(fmt.Sprintf("Server: %s", serverURL))
	ui.Info(fmt.Sprintf("Scope: %s", resp.Scope))
	return nil
}
