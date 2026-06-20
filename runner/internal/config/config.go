package config

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/spf13/viper"
)

func InitWithPath(path string) error {
	viper.SetConfigFile(path)
	viper.SetConfigType("toml")
	bindEnvVars()
	if err := viper.ReadInConfig(); err != nil {
		if _, ok := err.(*os.PathError); ok {
			return nil
		}
		if _, ok := err.(viper.ConfigFileNotFoundError); ok {
			return nil
		}
		return fmt.Errorf("读取配置失败: %w", err)
	}
	return nil
}

func Init() error {
	path := ConfigFilePath()
	viper.SetConfigFile(path)
	viper.SetConfigType("toml")
	bindEnvVars()
	if err := viper.ReadInConfig(); err != nil {
		if _, ok := err.(*os.PathError); ok {
			return nil // 配置文件不存在，正常
		}
		if _, ok := err.(viper.ConfigFileNotFoundError); ok {
			return nil
		}
		return fmt.Errorf("读取配置失败: %w", err)
	}
	return nil
}

func bindEnvVars() {
	viper.SetEnvPrefix("FRIDAY_RUNNER")
	_ = viper.BindEnv("server.url", "FRIDAY_RUNNER_URL")
	_ = viper.BindEnv("server.token", "FRIDAY_RUNNER_TOKEN")
	_ = viper.BindEnv("runner.name", "FRIDAY_RUNNER_NAME")
	_ = viper.BindEnv("runner.concurrent", "FRIDAY_RUNNER_CONCURRENT")
	_ = viper.BindEnv("executor.type", "FRIDAY_RUNNER_EXECUTOR")
	_ = viper.BindEnv("executor.timeout", "FRIDAY_RUNNER_TIMEOUT")
	_ = viper.BindEnv("executor.image", "FRIDAY_RUNNER_IMAGE")
	_ = viper.BindEnv("callback.port", "FRIDAY_RUNNER_CALLBACK_PORT")
	// k8s 模式下 task→runner 回调地址的 host（runner Pod IP），docker 模式留空走默认。
	_ = viper.BindEnv("callback.host", "FRIDAY_RUNNER_CALLBACK_HOST")
	_ = viper.BindEnv("executor.k8s.namespace", "FRIDAY_RUNNER_K8S_NAMESPACE")
	_ = viper.BindEnv("executor.k8s.backoff_limit", "FRIDAY_RUNNER_K8S_BACKOFF_LIMIT")
	_ = viper.BindEnv("executor.k8s.ttl", "FRIDAY_RUNNER_K8S_TTL")
	_ = viper.BindEnv("executor.k8s.service_account", "FRIDAY_RUNNER_K8S_SERVICE_ACCOUNT")
	_ = viper.BindEnv("executor.k8s.image_pull_secret", "FRIDAY_RUNNER_K8S_IMAGE_PULL_SECRET")
}

func SaveConfig(serverURL, encryptedToken, name string, concurrent int) error {
	dir := ConfigDir()
	if err := os.MkdirAll(dir, 0700); err != nil {
		return fmt.Errorf("创建配置目录失败: %w", err)
	}
	viper.Set("server.url", serverURL)
	viper.Set("server.token", encryptedToken)
	viper.Set("runner.name", name)
	viper.Set("runner.concurrent", concurrent)
	viper.Set("executor.type", "docker")
	viper.Set("executor.timeout", 1800)
	path := filepath.Join(dir, "config.toml")
	if err := viper.WriteConfigAs(path); err != nil {
		return fmt.Errorf("写入配置失败: %w", err)
	}
	return os.Chmod(path, 0600)
}

func IsRegistered() bool {
	return GetToken() != ""
}

func GetServerURL() string  { return viper.GetString("server.url") }
func GetToken() string      { return viper.GetString("server.token") }
func GetRunnerName() string { return viper.GetString("runner.name") }
func GetConcurrent() int    { return viper.GetInt("runner.concurrent") }

func GetDefaultImage() string {
	if v := viper.GetString("executor.image"); v != "" {
		return v
	}
	return "friday-task:latest"
}

func GetExecutorTimeout() int {
	if v := viper.GetInt("executor.timeout"); v > 0 {
		return v
	}
	return 1800
}

func GetCallbackPort() int {
	if v := viper.GetInt("callback.port"); v > 0 {
		return v
	}
	return 8976
}

func GetExecutorType() string {
	v := viper.GetString("executor.type")
	if v == "" {
		return "docker"
	}
	// canonical=kubernetes，接受 k8s 别名（Open Q5）。
	if v == "k8s" {
		return "kubernetes"
	}
	return v
}

// GetCallbackHost 返回 task→runner 回调地址的 host；默认空（由 ws 层退回 host.docker.internal）。
func GetCallbackHost() string { return viper.GetString("callback.host") }

func GetK8sNamespace() string { return viper.GetString("executor.k8s.namespace") }

// GetK8sBackoffLimit 默认 0（不重试，对齐 docker 失败留存调试）。
func GetK8sBackoffLimit() int { return viper.GetInt("executor.k8s.backoff_limit") }

// GetK8sTTLSeconds 默认 3600（被动清理兜底）。
func GetK8sTTLSeconds() int {
	if v := viper.GetInt("executor.k8s.ttl"); v > 0 {
		return v
	}
	return 3600
}

func GetK8sImagePullSecret() string { return viper.GetString("executor.k8s.image_pull_secret") }
