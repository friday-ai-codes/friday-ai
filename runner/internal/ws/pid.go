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
func WritePID error {
	path:= config.PIDFilePath
	if err:= os.MkdirAll(filepath.Dir(path), 0700); err != nil {
 return err
	}
	return os.WriteFile(path, byte(strconv.Itoa(os.Getpid)), 0644)
}
// CheckPID 读取 PID 文件并检测进程是否存活。
func CheckPID (int, bool) {
	data, err:= os.ReadFile(config.PIDFilePath)
	if err != nil {
 return 0, false
	}
	pid, err:= strconv.Atoi(strings.TrimSpace(string(data)))
	if err != nil {
 return 0, false
	}
	proc, err:= os.FindProcess(pid)
	if err != nil {
 return pid, false
	}
	return pid, proc.Signal(syscall.Signal(0)) == nil
}
// RemovePID 删除 PID 文件。
func RemovePID { os.Remove(config.PIDFilePath) }
