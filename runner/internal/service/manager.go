package service
import (
	"fmt"
	"os/exec"
	"strings"
)
// ServiceInfo 描述服务的安装和运行状态
type ServiceInfo struct {
	Installed bool `json:"installed"`
	Running bool `json:"running"`
	System bool `json:"system"`
	ConfigPath string `json:"config_path"`
	PID int `json:"pid"`
}
// InstallOptions 是 install 子命令的参数
type InstallOptions struct {
	ExePath string // friday-runner 可执行文件绝对路径
	ConfigPath string // --config 配置文件路径
	LogDir string // 日志输出目录
}
// ServiceManager 是平台相关的服务管理接口
type ServiceManager interface {
	Install(opts InstallOptions) error
	Uninstall error
	Status (ServiceInfo, error)
	LogCmd(follow bool, lines int) (*exec.Cmd, error)
}
// run 执行外部命令并返回合并的输出
func run(name string, args ...string) (string, error) {
	cmd:= exec.Command(name, args...)
	out, err:= cmd.CombinedOutput
	if err != nil {
 return "", fmt.Errorf("%s %s 失败: %w\n%s", name, strings.Join(args, " "), err, strings.TrimSpace(string(out)))
	}
	return strings.TrimSpace(string(out)), nil
}
