// Package exec 提供 docker / k8s executor 共享的中立逻辑。
// BuildContainerEnv 是任务容器 env 装配的唯一真相源，纯函数、不依赖具体 runtime，
// docker 与 k8s executor 复用同一份装配，避免 FRIDAY_TASK_ 前缀错位回归（Pitfall 2）。
package exec

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/friday-ai-codes/friday-ai/runner/internal/ws"
)

// BuildContainerEnv 装配任务容器环境变量（docker/k8s 共用）。
// 返回 `K=V` 形态的字符串切片，与 docker container.Config.Env 兼容；
// k8s 侧由 toEnvVars 适配为 []corev1.EnvVar。
func BuildContainerEnv(task ws.TaskPayload, callbackURL, callbackToken string) []string {
	remoteTools, _ := json.Marshal(task.Payload["remote_tools"])
	prompt, _ := task.Payload["prompt"].(string)
	taskMode := taskModeForPython(task.TaskType)
	env := []string{
		// 旧协议变量（兼容已有代码）
		"FRIDAY_SESSION_ID=" + task.TaskID,
		"FRIDAY_TASK_TYPE=" + task.TaskType,
		"FRIDAY_CALLBACK_URL=" + callbackURL,
		"FRIDAY_CALLBACK_TOKEN=" + callbackToken,
		"FRIDAY_GIT_REPO_URL=" + task.RepoURL,
		"FRIDAY_GIT_BRANCH=" + task.Branch,
		fmt.Sprintf("FRIDAY_TASK_TIMEOUT=%d", task.Timeout),
		"FRIDAY_ANSWER_PORT=8977",
		"FRIDAY_REMOTE_TOOLS=" + string(remoteTools),
		// git-wrapper.sh 读取该变量，必须保留 coding/coding_commit 语义来拦截 git 写操作。
		"FRIDAY_TASK_MODE=" + task.TaskType,
		// pydantic TaskConfig 需要 FRIDAY_TASK_ 前缀
		"FRIDAY_TASK_TASK_ID=" + task.TaskID,
		"FRIDAY_TASK_TASK_DESCRIPTION=" + prompt,
		"FRIDAY_TASK_TASK_MODE=" + taskMode,
		"FRIDAY_TASK_TASK_TYPE=" + task.TaskType,
		"FRIDAY_TASK_GIT_REPO_URL=" + task.RepoURL,
		"FRIDAY_TASK_GIT_BRANCH=" + task.Branch,
		"FRIDAY_TASK_CALLBACK_URL=" + callbackURL,
		"FRIDAY_TASK_CALLBACK_TOKEN=" + callbackToken,
		// 前缀修复（Pitfall 2）：TaskConfig 只认 FRIDAY_TASK_ 前缀，与旧 FRIDAY_REMOTE_TOOLS 同源同值。
		"FRIDAY_TASK_REMOTE_TOOLS=" + string(remoteTools),
		fmt.Sprintf("FRIDAY_TASK_EXECUTION_TIMEOUT=%d", task.Timeout),
		"GIT_SSL_NO_VERIFY=true",
		"CLAUDE_CODE_DISABLE_NONINTERACTIVE_SUBAGENTS=true",
		// 关闭 claude CLI 遥测/统计/bootstrap 等非必要外联：
		// ANTHROPIC_BASE_URL 指向第三方代理时这些端点持续 403 刷屏。
		"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1",
	}
	// 从 task.Payload["metadata"] 中提取 env_ 前缀的字段注入容器环境变量
	// 服务端通过 DispatchTask.metadata 传入，例如 {"env_FRIDAY_TASK_CLAUDE_API_KEY": "sk-..."}
	if meta, ok := task.Payload["metadata"].(map[string]any); ok {
		for k, v := range meta {
			if strings.HasPrefix(k, "env_") {
				envKey := strings.TrimPrefix(k, "env_")
				if s, ok := v.(string); ok && s != "" {
					env = append(env, envKey+"="+s)
				}
			}
		}
	}
	return env
}

func taskModeForPython(taskType string) string {
	switch taskType {
	case "coding", "coding_commit":
		return "execute"
	default:
		return taskType
	}
}
