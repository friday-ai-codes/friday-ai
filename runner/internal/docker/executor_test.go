package docker
import (
	"testing"
	"github.com/friday-ai-codes/friday-ai/runner/internal/ws"
)
func envMap(items string) map[string]string {
	result:= make(map[string]string, len(items))
	for _, item:= range items {
 for i, ch:= range item {
 if ch == '=' {
 result[item[:i]] = item[i+1:]
 break
 }
 }
	}
	return result
}
func TestBuildContainerEnvSeparatesTaskModeAndTaskType(t *testing.T) {
	task:= ws.TaskPayload{
 TaskID: "coding-123",
 TaskType: "coding",
 RepoURL: "https://git.example.com/repo.git",
 Branch: "master",
 Timeout: 3600,
 Payload: map[string]any{
 "prompt": "执行编码",
 "metadata": map[string]any{
 "env_FRIDAY_TASK_BRANCH_STRATEGY": "fix20260528.tabstudy-gift-aftersearch-slot",
 },
 },
	}
	env:= envMap(buildContainerEnv(task, "http://callback", "token"))
	if env["FRIDAY_TASK_TASK_MODE"] != "execute" {
 t.Fatalf("FRIDAY_TASK_TASK_MODE = %q, want execute", env["FRIDAY_TASK_TASK_MODE"])
	}
	if env["FRIDAY_TASK_TASK_TYPE"] != "coding" {
 t.Fatalf("FRIDAY_TASK_TASK_TYPE = %q, want coding", env["FRIDAY_TASK_TASK_TYPE"])
	}
	if env["FRIDAY_TASK_MODE"] != "coding" {
 t.Fatalf("FRIDAY_TASK_MODE = %q, want coding", env["FRIDAY_TASK_MODE"])
	}
	if env["FRIDAY_TASK_BRANCH_STRATEGY"] != "fix20260528.tabstudy-gift-aftersearch-slot" {
 t.Fatalf("missing branch strategy env: %#v", env)
	}
}
