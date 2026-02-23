package cmd
import (
	"encoding/json"
	"fmt"
	"os"
	"github.com/charmbracelet/lipgloss/v2"
	"github.com/charmbracelet/lipgloss/v2/table"
	"github.com/spf13/cobra"
	"github.com/friday-ai-codes/friday-ai/runner/internal/api"
	"github.com/friday-ai-codes/friday-ai/runner/internal/config"
	"github.com/friday-ai-codes/friday-ai/runner/internal/crypto"
	"github.com/friday-ai-codes/friday-ai/runner/internal/ui"
)
var statusCmd = &cobra.Command{
	Use: "status",
	Short: "显示 Runner 注册状态",
	RunE: runStatus,
}
func init {
	statusCmd.Flags.Bool("json", false, "以 JSON 格式输出")
	rootCmd.AddCommand(statusCmd)
}
func runStatus(cmd *cobra.Command, _ string) error {
	if !config.IsRegistered {
 ui.Error("未注册任何 Runner")
 ui.Hint("使用 friday-runner register 注册")
 return fmt.Errorf("未注册")
	}
	name:= config.GetRunnerName
	serverURL:= config.GetServerURL
	concurrent:= config.GetConcurrent
	// 尝试从服务端获取状态
	var status, version, lastHeartbeat, scope string
	status = "未知（服务端不可达）"
	key, err:= crypto.GetOrCreateKey
	if err == nil {
 token, decErr:= crypto.Decrypt(key, config.GetToken)
 if decErr == nil {
 if resp, apiErr:= api.NewClient(serverURL).Verify(string(token)); apiErr == nil {
 status = resp.Status
 version = resp.Version
 scope = resp.Scope
 concurrent = resp.Concurrent
 if resp.LastHeartbeat != nil {
 lastHeartbeat = *resp.LastHeartbeat
 }
 }
 }
	}
	jsonFlag, _:= cmd.Flags.GetBool("json")
	if jsonFlag {
 return outputJSON(name, serverURL, scope, concurrent, status, version, lastHeartbeat)
	}
	return outputTable(name, serverURL, scope, concurrent, status, version, lastHeartbeat)
}
func outputJSON(name, serverURL, scope string, concurrent int, status, version, lastHeartbeat string) error {
	data:= map[string]any{
 "name": name,
 "url": serverURL,
 "scope": scope,
 "concurrent": concurrent,
 "status": status,
 "version": version,
 "last_heartbeat": lastHeartbeat,
	}
	enc:= json.NewEncoder(os.Stdout)
	enc.SetIndent("", " ")
	return enc.Encode(data)
}
func outputTable(name, serverURL, scope string, concurrent int, status, version, lastHeartbeat string) error {
	rows:= string{
 {"Runner 名称", name},
 {"Server URL", serverURL},
 {"Scope", scope},
 {"并发数", fmt.Sprintf("%d", concurrent)},
 {"状态", status},
 {"版本", version},
 {"最后心跳", lastHeartbeat},
	}
	headerStyle:= lipgloss.NewStyle.Bold(true).Padding(0, 1)
	cellStyle:= lipgloss.NewStyle.Padding(0, 1)
	t:= table.New.
 Headers("字段", "值").
 Rows(rows...).
 StyleFunc(func(row, _ int) lipgloss.Style {
 if row == table.HeaderRow {
 return headerStyle
 }
 return cellStyle
 })
	fmt.Println(t)
	return nil
}
