package service

import (
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

const binName = "friday-runner"

// ServiceInfo 描述服务的安装和运行状态
type ServiceInfo struct {
	Installed  bool   `json:"installed"`
	Running    bool   `json:"running"`
	System     bool   `json:"system"`
	ConfigPath string `json:"config_path"`
	PID        int    `json:"pid"`
}

// InstallOptions 是 install 子命令的参数
type InstallOptions struct {
	ExePath    string // friday-runner 源二进制文件路径（将被复制到标准安装位置）
	ConfigPath string // 用户配置文件路径（系统级安装时会复制到 /etc）
	LogDir     string // 日志输出目录
}

// ServiceManager 是平台相关的服务管理接口
type ServiceManager interface {
	Install(opts InstallOptions) error
	Uninstall() error
	Status() (ServiceInfo, error)
	LogCmd(follow bool, lines int) (*exec.Cmd, error)
}

const binInstallDir = "/usr/local/bin"

// BinInstallPath 返回二进制文件的完整安装路径
func BinInstallPath() string {
	return filepath.Join(binInstallDir, binName)
}

// SystemConfigDir 返回系统级配置目录
func SystemConfigDir() string {
	return "/etc/friday-runner"
}

// SystemConfigPath 返回系统级配置文件路径
func SystemConfigPath() string {
	return filepath.Join(SystemConfigDir(), "config.toml")
}

// SystemLogDir 返回系统级日志目录
func SystemLogDir() string {
	return "/var/log/friday-runner"
}

// InstallBinary 将 Runner 二进制复制到 /usr/local/bin，返回安装后的路径
func InstallBinary(srcPath string) (string, error) {
	if err := os.MkdirAll(binInstallDir, 0755); err != nil {
		return "", fmt.Errorf("创建目录 %s 失败: %w", binInstallDir, err)
	}

	dst := BinInstallPath()
	if err := copyFile(srcPath, dst, 0755); err != nil {
		return "", fmt.Errorf("安装二进制文件到 %s 失败: %w", dst, err)
	}
	return dst, nil
}

// InstallConfig 将配置文件复制到系统级配置目录，返回安装后的路径
func InstallConfig(srcPath string) (string, error) {
	dir := SystemConfigDir()
	if err := os.MkdirAll(dir, 0755); err != nil {
		return "", fmt.Errorf("创建配置目录 %s 失败: %w", dir, err)
	}

	dst := SystemConfigPath()
	if err := copyFile(srcPath, dst, 0600); err != nil {
		return "", fmt.Errorf("安装配置文件到 %s 失败: %w", dst, err)
	}
	return dst, nil
}

// RemoveBinary 删除已安装的二进制文件
func RemoveBinary() error {
	path := BinInstallPath()
	if err := os.Remove(path); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("删除 %s 失败: %w", path, err)
	}
	return nil
}

func copyFile(src, dst string, perm os.FileMode) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()

	out, err := os.OpenFile(dst, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, perm)
	if err != nil {
		return err
	}
	defer out.Close()

	if _, err := io.Copy(out, in); err != nil {
		return err
	}
	return out.Close()
}

// run 执行外部命令并返回合并的输出
func run(name string, args ...string) (string, error) {
	cmd := exec.Command(name, args...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("%s %s 失败: %w\n%s", name, strings.Join(args, " "), err, strings.TrimSpace(string(out)))
	}
	return strings.TrimSpace(string(out)), nil
}
