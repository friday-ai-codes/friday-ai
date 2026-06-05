//go:build linux

package service

import (
	"bytes"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"text/template"
)

const unitName = "friday-runner.service"

var unitTemplate = template.Must(template.New("unit").Parse(`[Unit]
Description=Friday AI Runner
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={{ .ExePath }} run --config {{ .ConfigPath }} --json-log
Restart=always
RestartSec=5

[Install]
WantedBy={{ .WantedBy }}
`))

type systemdManager struct {
	system bool
}

func New(system bool) (ServiceManager, error) {
	return &systemdManager{system: system}, nil
}

func (m *systemdManager) unitPath() string {
	if m.system {
		return filepath.Join("/etc/systemd/system", unitName)
	}
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".config", "systemd", "user", unitName)
}

func (m *systemdManager) systemctl(args ...string) (string, error) {
	if !m.system {
		args = append([]string{"--user"}, args...)
	}
	return run("systemctl", args...)
}

func (m *systemdManager) Install(opts InstallOptions) error {
	installedBin, err := InstallBinary(opts.ExePath)
	if err != nil {
		return err
	}

	configPath := opts.ConfigPath
	if m.system {
		cp, err := InstallConfig(opts.ConfigPath)
		if err != nil {
			return err
		}
		configPath = cp
	}

	unitPath := m.unitPath()
	if err := os.MkdirAll(filepath.Dir(unitPath), 0755); err != nil {
		return fmt.Errorf("创建目录失败: %w", err)
	}

	wantedBy := "default.target"
	if m.system {
		wantedBy = "multi-user.target"
	}

	data := map[string]string{
		"ExePath":    installedBin,
		"ConfigPath": configPath,
		"WantedBy":   wantedBy,
	}

	var buf bytes.Buffer
	if err := unitTemplate.Execute(&buf, data); err != nil {
		return fmt.Errorf("生成 unit 文件失败: %w", err)
	}

	if err := os.WriteFile(unitPath, buf.Bytes(), 0644); err != nil {
		return fmt.Errorf("写入 unit 文件失败: %w", err)
	}

	if _, err := m.systemctl("daemon-reload"); err != nil {
		return fmt.Errorf("daemon-reload 失败: %w", err)
	}
	if _, err := m.systemctl("enable", unitName); err != nil {
		return fmt.Errorf("enable 失败: %w", err)
	}
	if _, err := m.systemctl("start", unitName); err != nil {
		return fmt.Errorf("启动服务失败: %w", err)
	}

	return nil
}

func (m *systemdManager) Uninstall() error {
	_, _ = m.systemctl("stop", unitName)
	_, _ = m.systemctl("disable", unitName)

	unitPath := m.unitPath()
	if err := os.Remove(unitPath); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("删除 unit 文件失败: %w", err)
	}

	_, _ = m.systemctl("daemon-reload")

	if err := RemoveBinary(); err != nil {
		return err
	}

	return nil
}

func (m *systemdManager) Status() (ServiceInfo, error) {
	info := ServiceInfo{
		System:     m.system,
		ConfigPath: m.unitPath(),
	}

	if _, err := os.Stat(m.unitPath()); os.IsNotExist(err) {
		return info, nil
	}
	info.Installed = true

	out, err := m.systemctl("is-active", unitName)
	if err == nil && strings.TrimSpace(out) == "active" {
		info.Running = true
	}

	pidOut, err := m.systemctl("show", unitName, "--property=MainPID", "--value")
	if err == nil {
		if pid, convErr := strconv.Atoi(strings.TrimSpace(pidOut)); convErr == nil && pid > 0 {
			info.PID = pid
		}
	}

	return info, nil
}

func (m *systemdManager) LogCmd(follow bool, lines int) (*exec.Cmd, error) {
	info, err := m.Status()
	if err != nil {
		return nil, err
	}
	if !info.Installed {
		return nil, fmt.Errorf("服务未安装")
	}

	args := []string{"-u", unitName, "-n", strconv.Itoa(lines)}
	if !m.system {
		args = append(args, "--user")
	}
	if follow {
		args = append(args, "--follow")
	}

	return exec.Command("journalctl", args...), nil
}
