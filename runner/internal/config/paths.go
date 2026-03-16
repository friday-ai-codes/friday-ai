package config
import (
	"os"
	"path/filepath"
)
func ConfigDir string {
	if dir:= os.Getenv("XDG_CONFIG_HOME"); dir != "" {
 return filepath.Join(dir, "friday-runner")
	}
	home, _:= os.UserHomeDir
	return filepath.Join(home, ".config", "friday-runner")
}
func DataDir string {
	if dir:= os.Getenv("XDG_DATA_HOME"); dir != "" {
 return filepath.Join(dir, "friday-runner")
	}
	home, _:= os.UserHomeDir
	return filepath.Join(home, ".local", "share", "friday-runner")
}
func ConfigFilePath string {
	return filepath.Join(ConfigDir, "config.toml")
}
func KeyFilePath string {
	return filepath.Join(DataDir, "key")
}
func PIDFilePath string {
	return filepath.Join(DataDir, "runner.pid")
}
func LogDir string {
	return filepath.Join(DataDir, "logs")
}
