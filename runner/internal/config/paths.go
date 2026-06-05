package config

import (
	"os"
	"path/filepath"
	"runtime"
)

// realHomeDir 返回实际用户的 home 目录。
// 在 sudo 场景下通过 SUDO_USER 推断原始用户的 home，
// 避免返回 root 的 home 导致找不到注册配置。
//
// 不使用 user.Lookup 是因为 CGO_ENABLED=0 编译时
// 纯 Go 实现在 macOS 上无法查询 Directory Service 中的用户。
func realHomeDir() string {
	if sudoUser := os.Getenv("SUDO_USER"); sudoUser != "" {
		if runtime.GOOS == "darwin" {
			return filepath.Join("/Users", sudoUser)
		}
		return filepath.Join("/home", sudoUser)
	}
	home, _ := os.UserHomeDir()
	return home
}

func ConfigDir() string {
	if dir := os.Getenv("XDG_CONFIG_HOME"); dir != "" {
		return filepath.Join(dir, "friday-runner")
	}
	return filepath.Join(realHomeDir(), ".config", "friday-runner")
}

func DataDir() string {
	if dir := os.Getenv("XDG_DATA_HOME"); dir != "" {
		return filepath.Join(dir, "friday-runner")
	}
	return filepath.Join(realHomeDir(), ".local", "share", "friday-runner")
}

func ConfigFilePath() string {
	return filepath.Join(ConfigDir(), "config.toml")
}

func KeyFilePath() string {
	return filepath.Join(DataDir(), "key")
}

func PIDFilePath() string {
	return filepath.Join(DataDir(), "runner.pid")
}

func LogDir() string {
	return filepath.Join(DataDir(), "logs")
}
