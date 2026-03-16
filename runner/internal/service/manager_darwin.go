//go:build darwin
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
const (
	launchdLabel = "ai.friday.runner"
	plistFileName = launchdLabel + ".plist"
	userAgentsRelPath = "Library/LaunchAgents"
	systemDaemonsPath = "/Library/LaunchDaemons"
)
var plistTemplate = template.Must(template.New("plist").Parse(`<?xml version="1.0" encoding=""?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
 <key>Label</key>
 <string>{{ .Label }}</string>
 <key>ProgramArguments</key>
 <array>
 <string>{{ .ExePath }}</string>
 <string>run</string>
 <string>--config</string>
 <string>{{ .ConfigPath }}</string>
 <string>--json-log</string>
 </array>
 <key>RunAtLoad</key>
 <true/>
 <key>KeepAlive</key>
 <true/>
 <key>StandardOutPath</key>
 <string>{{ .StdoutLog }}</string>
 <key>StandardErrorPath</key>
 <string>{{ .StderrLog }}</string>
 <key>EnvironmentVariables</key>
 <dict>
 <key>PATH</key>
 <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
 </dict>
</dict>
</plist>
`))
type launchdManager struct {
	system bool
}
func New(system bool) (ServiceManager, error) {
	return &launchdManager{system: system}, nil
}
func (m *launchdManager) plistPath string {
	if m.system {
 return filepath.Join(systemDaemonsPath, plistFileName)
	}
	home, _:= os.UserHomeDir
	return filepath.Join(home, userAgentsRelPath, plistFileName)
}
func (m *launchdManager) Install(opts InstallOptions) error {
	plistPath:= m.plistPath
	if err:= os.MkdirAll(filepath.Dir(plistPath), 0755); err != nil {
 return fmt.Errorf("创建目录失败: %w", err)
	}
	if err:= os.MkdirAll(opts.LogDir, 0755); err != nil {
 return fmt.Errorf("创建日志目录失败: %w", err)
	}
	data:= map[string]string{
 "Label": launchdLabel,
 "ExePath": opts.ExePath,
 "ConfigPath": opts.ConfigPath,
 "StdoutLog": filepath.Join(opts.LogDir, "friday-runner.stdout.log"),
 "StderrLog": filepath.Join(opts.LogDir, "friday-runner.stderr.log"),
	}
	var buf bytes.Buffer
	if err:= plistTemplate.Execute(&buf, data); err != nil {
 return fmt.Errorf("生成 plist 失败: %w", err)
	}
	if err:= os.WriteFile(plistPath, buf.Bytes, 0644); err != nil {
 return fmt.Errorf("写入 plist 失败: %w", err)
	}
	if _, err:= run("launchctl", "load", "-w", plistPath); err != nil {
 return fmt.Errorf("加载服务失败: %w", err)
	}
	return nil
}
func (m *launchdManager) Uninstall error {
	plistPath:= m.plistPath
	// 尝试停止服务，即使失败也继续删除文件
	_, _ = run("launchctl", "unload", plistPath)
	if err:= os.Remove(plistPath); err != nil && !os.IsNotExist(err) {
 return fmt.Errorf("删除 plist 失败: %w", err)
	}
	return nil
}
func (m *launchdManager) Status (ServiceInfo, error) {
	info:= ServiceInfo{
 System: m.system,
 ConfigPath: m.plistPath,
	}
	// 检查 plist 文件是否存在
	if _, err:= os.Stat(m.plistPath); os.IsNotExist(err) {
 return info, nil
	}
	info.Installed = true
	// 通过 launchctl list 检查运行状态
	out, err:= run("launchctl", "list", launchdLabel)
	if err != nil {
 // 服务未加载
 return info, nil
	}
	// 解析输出，查找 PID
	for _, line:= range strings.Split(out, "\n") {
 line = strings.TrimSpace(line)
 if strings.HasPrefix(line, "\"PID\"") || strings.HasPrefix(line, "PID") {
 // launchctl list <label> 输出格式:
 // "PID" = 12345;
 parts:= strings.Split(line, "=")
 if len(parts) == 2 {
 pidStr:= strings.TrimSpace(strings.TrimRight(parts[1], ";\" "))
 if pid, convErr:= strconv.Atoi(pidStr); convErr == nil && pid > 0 {
 info.Running = true
 info.PID = pid
 }
 }
 }
	}
	// 如果没有通过上面解析到 PID，尝试用简单的 launchctl list 格式
	// launchctl list | grep <label> 输出: PID\tStatus\tLabel
	if !info.Running {
 listOut, listErr:= run("launchctl", "list")
 if listErr == nil {
 for _, line:= range strings.Split(listOut, "\n") {
 if strings.Contains(line, launchdLabel) {
 fields:= strings.Fields(line)
 if len(fields) >= 1 && fields[0] != "-" {
 if pid, convErr:= strconv.Atoi(fields[0]); convErr == nil && pid > 0 {
 info.Running = true
 info.PID = pid
 }
 }
 break
 }
 }
 }
	}
	return info, nil
}
func (m *launchdManager) LogCmd(follow bool, lines int) (*exec.Cmd, error) {
	info, err:= m.Status
	if err != nil {
 return nil, err
	}
	if !info.Installed {
 return nil, fmt.Errorf("服务未安装")
	}
	// 从 plist 中读取日志路径，使用 stderr 日志（包含应用日志）
	plistData, err:= os.ReadFile(m.plistPath)
	if err != nil {
 return nil, fmt.Errorf("读取 plist 失败: %w", err)
	}
	// 简单解析 StandardErrorPath
	logPath:= ""
	content:= string(plistData)
	if idx:= strings.Index(content, "<key>StandardErrorPath</key>"); idx >= 0 {
 rest:= content[idx:]
 if start:= strings.Index(rest, "<string>"); start >= 0 {
 rest = rest[start+len("<string>"):]
 if end:= strings.Index(rest, "</string>"); end >= 0 {
 logPath = rest[:end]
 }
 }
	}
	if logPath == "" {
 return nil, fmt.Errorf("未找到日志路径")
	}
	args:= string{"-n", strconv.Itoa(lines)}
	if follow {
 args = append(args, "-f")
	}
	args = append(args, logPath)
	return exec.Command("tail", args...), nil
}
