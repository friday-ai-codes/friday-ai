package docker

import (
	"strings"
	"testing"

	"github.com/friday-ai-codes/friday-ai/runner/internal/ws"
)

func envMap(items []string) map[string]string {
	result := make(map[string]string, len(items))
	for _, item := range items {
		for i, ch := range item {
			if ch == '=' {
				result[item[:i]] = item[i+1:]
				break
			}
		}
	}
	return result
}

func TestBuildContainerEnvSeparatesTaskModeAndTaskType(t *testing.T) {
	task := ws.TaskPayload{
		TaskID:   "coding-123",
		TaskType: "coding",
		RepoURL:  "https://git.example.com/repo.git",
		Branch:   "master",
		Timeout:  3600,
		Payload: map[string]any{
			"prompt": "执行编码",
			"metadata": map[string]any{
				"env_FRIDAY_TASK_BRANCH_STRATEGY": "feature/demo-task-branch",
			},
		},
	}

	env := envMap(buildContainerEnv(task, "http://callback", "token"))

	if env["FRIDAY_TASK_TASK_MODE"] != "execute" {
		t.Fatalf("FRIDAY_TASK_TASK_MODE = %q, want execute", env["FRIDAY_TASK_TASK_MODE"])
	}
	if env["FRIDAY_TASK_TASK_TYPE"] != "coding" {
		t.Fatalf("FRIDAY_TASK_TASK_TYPE = %q, want coding", env["FRIDAY_TASK_TASK_TYPE"])
	}
	if env["FRIDAY_TASK_MODE"] != "coding" {
		t.Fatalf("FRIDAY_TASK_MODE = %q, want coding", env["FRIDAY_TASK_MODE"])
	}
	if env["FRIDAY_TASK_BRANCH_STRATEGY"] != "feature/demo-task-branch" {
		t.Fatalf("missing branch strategy env: %#v", env)
	}
}

// TestBuildContainerEnv_RemoteTools 钉死 RemoteTool 闭环的 runner env 装配契约（RTOOL-03）：
//   - FRIDAY_TASK_REMOTE_TOOLS：由 payload remote_tools 序列化（前缀修复，Pitfall 2 ——
//     现状只注 FRIDAY_REMOTE_TOOLS，TaskConfig 的 FRIDAY_TASK_ 前缀读不到 → 11-03 落地前 RED）。
//   - FRIDAY_TASK_USER_TOKEN / FRIDAY_TASK_TOOLS_ENDPOINT：经 metadata env_ 前缀 TrimPrefix 透传。
func TestBuildContainerEnv_RemoteTools(t *testing.T) {
	task := ws.TaskPayload{
		TaskID:   "rtool-123",
		TaskType: "coding",
		RepoURL:  "https://git.example.com/repo.git",
		Branch:   "master",
		Timeout:  3600,
		Payload: map[string]any{
			"prompt": "执行编码",
			"remote_tools": []any{
				map[string]any{
					"name":         "a",
					"description":  "da",
					"input_schema": map[string]any{},
				},
			},
			"metadata": map[string]any{
				"env_FRIDAY_TASK_USER_TOKEN":     "friday_pat_TESTTOKEN",
				"env_FRIDAY_TASK_TOOLS_ENDPOINT": "https://friday.example.com/api/tools/execute/",
			},
		},
	}

	env := envMap(buildContainerEnv(task, "http://callback", "token"))

	// 前缀修复（Pitfall 2）：TaskConfig 读 FRIDAY_TASK_ 前缀，须注入 FRIDAY_TASK_REMOTE_TOOLS。
	if env["FRIDAY_TASK_REMOTE_TOOLS"] == "" {
		t.Fatalf("missing FRIDAY_TASK_REMOTE_TOOLS env (Pitfall 2 前缀错位): %#v", env)
	}
	if !strings.Contains(env["FRIDAY_TASK_REMOTE_TOOLS"], "\"a\"") {
		t.Fatalf("FRIDAY_TASK_REMOTE_TOOLS = %q, want remote_tools JSON 含工具名 a", env["FRIDAY_TASK_REMOTE_TOOLS"])
	}

	// metadata env_ 透传：PAT + 工具端点。
	if env["FRIDAY_TASK_USER_TOKEN"] != "friday_pat_TESTTOKEN" {
		t.Fatalf("FRIDAY_TASK_USER_TOKEN = %q, want friday_pat_TESTTOKEN", env["FRIDAY_TASK_USER_TOKEN"])
	}
	if env["FRIDAY_TASK_TOOLS_ENDPOINT"] != "https://friday.example.com/api/tools/execute/" {
		t.Fatalf("FRIDAY_TASK_TOOLS_ENDPOINT = %q, want .../api/tools/execute/", env["FRIDAY_TASK_TOOLS_ENDPOINT"])
	}
}

// TestBuildContainerEnv_RemoteTools_NoPATNoEmptyKey 钉死向后兼容：metadata 无 PAT 键时，
// env 不含 FRIDAY_TASK_USER_TOKEN（既有 env_ 循环已 `s != ""` 守卫，不注入空键）。
func TestBuildContainerEnv_RemoteTools_NoPATNoEmptyKey(t *testing.T) {
	task := ws.TaskPayload{
		TaskID:   "rtool-nopat-456",
		TaskType: "coding",
		RepoURL:  "https://git.example.com/repo.git",
		Branch:   "master",
		Timeout:  3600,
		Payload: map[string]any{
			"prompt": "执行编码",
			"remote_tools": []any{
				map[string]any{"name": "a", "description": "da", "input_schema": map[string]any{}},
			},
			"metadata": map[string]any{
				"env_FRIDAY_TASK_TOOLS_ENDPOINT": "https://friday.example.com/api/tools/execute/",
			},
		},
	}

	env := envMap(buildContainerEnv(task, "http://callback", "token"))

	if _, ok := env["FRIDAY_TASK_USER_TOKEN"]; ok {
		t.Fatalf("无 PAT 键时不应注入 FRIDAY_TASK_USER_TOKEN（向后兼容）: %#v", env)
	}
}
