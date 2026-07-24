package ws

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"

	"github.com/friday-ai-codes/friday-ai/runner/internal/config"
)

// WritePID 写入当前进程 PID 文件。
func WritePID() error {
	path := config.PIDFilePath()
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	return os.WriteFile(path, []byte(strconv.Itoa(os.Getpid())), 0644)
}

// CheckPID 读取 PID 文件并检测进程是否存活。
func CheckPID() (int, bool) {
	data, err := os.ReadFile(config.PIDFilePath())
	if err != nil {
		return 0, false
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(data)))
	if err != nil {
		return 0, false
	}
	// 容器内 runner 恒为 PID 1（entrypoint exec 接管），容器重启后 PID 被复用：
	// 上一轮遗留的 PID 文件里写的还是 1，而新进程自己也是 1，直接 Signal(0) 必然
	// "存活"→误判"已在运行"→启动即自杀→无限重启循环（friday-runner crash loop）。
	// 若 PID 文件里的值等于当前进程自身 PID，必是自己遗留的陈旧文件，判为未运行。
	if pid == os.Getpid() {
		return pid, false
	}
	proc, err := os.FindProcess(pid)
	if err != nil {
		return pid, false
	}
	return pid, proc.Signal(syscall.Signal(0)) == nil
}

// RemovePID 删除 PID 文件。
func RemovePID() { os.Remove(config.PIDFilePath()) }
