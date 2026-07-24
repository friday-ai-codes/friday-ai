package ws

import (
	"os"
	"path/filepath"
	"strconv"
	"testing"

	"github.com/friday-ai-codes/friday-ai/runner/internal/config"
)

// writePIDFile 直接把指定 PID 写入 PID 文件路径（绕过 WritePID 只写当前进程的限制，
// 用于构造"陈旧 PID 文件"场景）。
func writePIDFile(t *testing.T, pid int) {
	t.Helper()
	path := config.PIDFilePath()
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatalf("创建 PID 目录失败: %v", err)
	}
	if err := os.WriteFile(path, []byte(strconv.Itoa(pid)), 0644); err != nil {
		t.Fatalf("写入 PID 文件失败: %v", err)
	}
}

// TestCheckPIDIgnoresOwnPID 复现并锁定 friday-runner crash 循环修复：
// 容器内 runner 恒为 PID 1，重启后陈旧 PID 文件里写的还是自己的 PID，
// CheckPID 必须判为"未运行"，否则启动即自杀无限重启。
func TestCheckPIDIgnoresOwnPID(t *testing.T) {
	t.Setenv("XDG_DATA_HOME", t.TempDir())

	writePIDFile(t, os.Getpid())

	pid, alive := CheckPID()
	if alive {
		t.Fatalf("PID 文件写当前进程自身 PID(%d) 时应判为未运行，实际 alive=true", pid)
	}
}

// TestCheckPIDNoFile 无 PID 文件时应判为未运行。
func TestCheckPIDNoFile(t *testing.T) {
	t.Setenv("XDG_DATA_HOME", t.TempDir())

	if _, alive := CheckPID(); alive {
		t.Fatal("无 PID 文件时应判为未运行，实际 alive=true")
	}
}

// TestCheckPIDStaleDeadPID 陈旧 PID 指向一个已不存在的进程时应判为未运行。
func TestCheckPIDStaleDeadPID(t *testing.T) {
	t.Setenv("XDG_DATA_HOME", t.TempDir())

	// 找一个几乎不可能存活、且不等于自身的 PID。
	deadPID := 2147483646
	if deadPID == os.Getpid() {
		deadPID--
	}
	writePIDFile(t, deadPID)

	if _, alive := CheckPID(); alive {
		t.Fatal("陈旧 PID 指向已死进程时应判为未运行，实际 alive=true")
	}
}

// TestWriteRemovePID 写入后文件存在、删除后消失。
func TestWriteRemovePID(t *testing.T) {
	t.Setenv("XDG_DATA_HOME", t.TempDir())

	if err := WritePID(); err != nil {
		t.Fatalf("WritePID 失败: %v", err)
	}
	if _, err := os.Stat(config.PIDFilePath()); err != nil {
		t.Fatalf("WritePID 后 PID 文件应存在: %v", err)
	}

	RemovePID()
	if _, err := os.Stat(config.PIDFilePath()); !os.IsNotExist(err) {
		t.Fatalf("RemovePID 后 PID 文件应被删除，err=%v", err)
	}
}
