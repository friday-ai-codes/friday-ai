package k8s

import (
	"context"
	"errors"
	"time"

	"github.com/friday-ai-codes/friday-ai/runner/internal/ws"
)

var ErrNotImplemented = errors.New("kubernetes executor: not implemented")

// 编译期接口检查
var _ ws.ExecutorService = (*KubernetesExecutor)(nil)

type KubernetesExecutor struct{}

func New() *KubernetesExecutor { return &KubernetesExecutor{} }

func (k *KubernetesExecutor) StartContainer(_ context.Context, _ ws.TaskPayload, _, _ string) (string, string, error) {
	return "", "", ErrNotImplemented
}

func (k *KubernetesExecutor) WaitContainer(_ context.Context, _ string, _ time.Duration) (int, string, error) {
	return 0, "", ErrNotImplemented
}

func (k *KubernetesExecutor) ReadContainerFile(_ context.Context, _, _ string) (string, error) {
	return "", ErrNotImplemented
}

func (k *KubernetesExecutor) StreamLogs(_ context.Context, _ string, _ func(string)) error {
	return ErrNotImplemented
}

func (k *KubernetesExecutor) RemoveContainer(_ context.Context, _ string) error {
	return ErrNotImplemented
}

func (k *KubernetesExecutor) StartupCleanup(_ context.Context) (int, error) {
	return 0, ErrNotImplemented
}

func (k *KubernetesExecutor) ZombieScan(_ context.Context, _ []string, _ *ws.MessageQueue, _, _ float64) error {
	return ErrNotImplemented
}
