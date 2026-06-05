package cmd

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"runtime"

	"github.com/charmbracelet/lipgloss/v2"
	"github.com/charmbracelet/lipgloss/v2/table"
	"github.com/spf13/cobra"

	"github.com/friday-ai-codes/friday-ai/runner/internal/config"
	"github.com/friday-ai-codes/friday-ai/runner/internal/service"
	"github.com/friday-ai-codes/friday-ai/runner/internal/ui"
)

var serviceCmd = &cobra.Command{
	Use:   "service",
	Short: "管理 Runner 系统服务（安装/卸载/状态/日志）",
}

var serviceInstallCmd = &cobra.Command{
	Use:   "install",
	Short: "安装 Runner 为系统服务",
	RunE:  runServiceInstall,
}

var serviceUninstallCmd = &cobra.Command{
	Use:   "uninstall",
	Short: "卸载 Runner 系统服务",
	RunE:  runServiceUninstall,
}

var serviceStatusCmd = &cobra.Command{
	Use:   "status",
	Short: "显示 Runner 服务状态",
	RunE:  runServiceStatus,
}

var serviceLogsCmd = &cobra.Command{
	Use:   "logs",
	Short: "查看 Runner 服务日志",
	RunE:  runServiceLogs,
}

func init() {
	serviceCmd.PersistentFlags().Bool("system", false, "管理系统级服务（需要 root 权限）")

	serviceStatusCmd.Flags().Bool("json", false, "以 JSON 格式输出")
	serviceLogsCmd.Flags().BoolP("follow", "f", false, "持续跟踪日志输出")
	serviceLogsCmd.Flags().Int("lines", 50, "显示最近 N 行日志")

	serviceCmd.AddCommand(serviceInstallCmd)
	serviceCmd.AddCommand(serviceUninstallCmd)
	serviceCmd.AddCommand(serviceStatusCmd)
	serviceCmd.AddCommand(serviceLogsCmd)
	rootCmd.AddCommand(serviceCmd)
}

func newServiceManager(cmd *cobra.Command) (service.ServiceManager, error) {
	system, _ := cmd.Flags().GetBool("system")
	return service.New(system)
}

func requireRoot(cmd *cobra.Command) error {
	if os.Geteuid() != 0 {
		system, _ := cmd.Flags().GetBool("system")
		ui.Error("安装到 /usr/local/bin 需要 root 权限")
		if system {
			ui.Hint("sudo friday-runner service " + cmd.Name() + " --system")
		} else {
			ui.Hint("sudo friday-runner service " + cmd.Name())
		}
		return fmt.Errorf("权限不足")
	}
	return nil
}

func runServiceInstall(cmd *cobra.Command, _ []string) error {
	if err := requireRoot(cmd); err != nil {
		return err
	}

	if !config.IsRegistered() {
		ui.Error("未注册，请先注册 Runner")
		ui.Hint("friday-runner register --token <TOKEN>")
		return fmt.Errorf("未注册")
	}

	mgr, err := newServiceManager(cmd)
	if err != nil {
		return err
	}

	info, err := mgr.Status()
	if err != nil {
		return fmt.Errorf("检查服务状态失败: %w", err)
	}
	if info.Installed {
		ui.Warn("检测到已有安装，正在重新安装...")
		if err := mgr.Uninstall(); err != nil {
			ui.Error(fmt.Sprintf("卸载旧服务失败: %s", err))
			return fmt.Errorf("卸载失败: %w", err)
		}
	}

	// 获取可执行文件绝对路径
	exePath, err := os.Executable()
	if err != nil {
		return fmt.Errorf("获取可执行文件路径失败: %w", err)
	}
	exePath, err = filepath.EvalSymlinks(exePath)
	if err != nil {
		return fmt.Errorf("解析可执行文件路径失败: %w", err)
	}

	logDir := config.LogDir()

	opts := service.InstallOptions{
		ExePath:    exePath,
		ConfigPath: config.ConfigFilePath(),
		LogDir:     logDir,
	}

	if err := mgr.Install(opts); err != nil {
		ui.Error(fmt.Sprintf("安装服务失败: %s", err))
		return fmt.Errorf("安装失败: %w", err)
	}

	system, _ := cmd.Flags().GetBool("system")

	ui.Success("服务安装成功")
	ui.Info(fmt.Sprintf("二进制文件: %s", service.BinInstallPath()))
	if system {
		ui.Info(fmt.Sprintf("配置文件:   %s", service.SystemConfigPath()))
		ui.Info(fmt.Sprintf("日志目录:   %s", service.SystemLogDir()))
	}
	ui.Info("Runner 将在系统启动时自动运行")
	ui.Hint("使用 friday-runner service status 查看状态")

	if runtime.GOOS == "linux" && !system {
		ui.Hint("如需在非登录状态下运行，请执行: loginctl enable-linger $USER")
	}

	return nil
}

func runServiceUninstall(cmd *cobra.Command, _ []string) error {
	if err := requireRoot(cmd); err != nil {
		return err
	}

	mgr, err := newServiceManager(cmd)
	if err != nil {
		return err
	}

	info, err := mgr.Status()
	if err != nil {
		return fmt.Errorf("检查服务状态失败: %w", err)
	}
	if !info.Installed {
		ui.Error("服务未安装")
		return fmt.Errorf("服务未安装")
	}

	if err := mgr.Uninstall(); err != nil {
		ui.Error(fmt.Sprintf("卸载服务失败: %s", err))
		return fmt.Errorf("卸载失败: %w", err)
	}

	ui.Success("服务已卸载")
	ui.Info(fmt.Sprintf("已移除: %s", service.BinInstallPath()))
	return nil
}

func runServiceStatus(cmd *cobra.Command, _ []string) error {
	mgr, err := newServiceManager(cmd)
	if err != nil {
		return err
	}

	info, err := mgr.Status()
	if err != nil {
		return fmt.Errorf("检查服务状态失败: %w", err)
	}

	jsonFlag, _ := cmd.Flags().GetBool("json")
	if jsonFlag {
		enc := json.NewEncoder(os.Stdout)
		enc.SetIndent("", "  ")
		return enc.Encode(info)
	}

	installedStr := "未安装"
	if info.Installed {
		installedStr = "已安装"
	}
	runningStr := "未运行"
	if info.Running {
		runningStr = fmt.Sprintf("运行中 (PID %d)", info.PID)
	}
	levelStr := "用户级"
	if info.System {
		levelStr = "系统级"
	}

	rows := [][]string{
		{"服务状态", installedStr},
		{"运行状态", runningStr},
		{"级别", levelStr},
		{"配置文件", info.ConfigPath},
	}
	headerStyle := lipgloss.NewStyle().Bold(true).Padding(0, 1)
	cellStyle := lipgloss.NewStyle().Padding(0, 1)
	t := table.New().
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

func runServiceLogs(cmd *cobra.Command, _ []string) error {
	mgr, err := newServiceManager(cmd)
	if err != nil {
		return err
	}

	follow, _ := cmd.Flags().GetBool("follow")
	lines, _ := cmd.Flags().GetInt("lines")

	logCmd, err := mgr.LogCmd(follow, lines)
	if err != nil {
		ui.Error(fmt.Sprintf("获取日志失败: %s", err))
		return err
	}

	logCmd.Stdout = os.Stdout
	logCmd.Stderr = os.Stderr

	return logCmd.Run()
}
