package ws
import (
	"context"
	"fmt"
	"math/rand/v2"
	"os/signal"
	"strings"
	"syscall"
	"time"
	"github.com/coder/websocket"
	"github.com/coder/websocket/wsjson"
	"github.com/rs/zerolog/log"
	"golang.org/x/sync/errgroup"
	"github.com/friday-ai-codes/friday-ai/runner/internal/ui"
)
const (
	initialDelay = 1 * time.Second
	maxDelay = 60 * time.Second
	maxRetries = 20
	heartbeatInterval = 30 * time.Second
	closeCodeReplaced = 4002
)
// Config 是 WebSocket 客户端配置。
type Config struct {
	ServerURL string
	Token string
	Name string
	Version string
	Concurrent int
}
// Run 启动 WebSocket 客户端主循环：PID 保护→连接→重连。
func Run(ctx context.Context, cfg Config) error {
	if pid, alive:= CheckPID; alive {
 return fmt.Errorf("Runner 已在运行 (PID %d)", pid)
	}
	RemovePID // 清理死进程残留
	if err:= WritePID; err != nil {
 return fmt.Errorf("写入 PID 文件失败: %w", err)
	}
	defer RemovePID
	Warmup
	ctx, cancel:= signal.NotifyContext(ctx, syscall.SIGTERM, syscall.SIGINT)
	defer cancel
	queue:= NewMessageQueue(100)
	delay:= initialDelay
	for attempt:= 0; attempt < maxRetries; attempt++ {
 err:= connectAndServe(ctx, cfg, queue)
 if ctx.Err != nil {
 ui.Info("正常关闭")
 return nil
 }
 if websocket.CloseStatus(err) == closeCodeReplaced {
 ui.Info("被新连接替代，停止重连")
 return nil
 }
 // 连接成功后重置（connectAndServe 内部已连接过）
 attempt++
 ui.Warn(fmt.Sprintf("重连中... 第 %d/%d 次", attempt, maxRetries))
 log.Warn.Err(err).Int("attempt", attempt).Msg("reconnecting")
 jitter:= time.Duration(rand.Int64N(int64(delay) / 10))
 select {
 case <-time.After(delay + jitter):
 case <-ctx.Done:
 return nil
 }
 delay = min(delay*2, maxDelay)
	}
	return fmt.Errorf("重连 %d 次全部失败", maxRetries)
}
func connectAndServe(ctx context.Context, cfg Config, queue *MessageQueue) error {
	wsURL:= httpToWS(cfg.ServerURL) + "/ws/v1/runner/?token=" + cfg.Token
	c, _, err:= websocket.Dial(ctx, wsURL, nil)
	if err != nil {
 return err
	}
	defer c.CloseNow
	// hello 握手
	hello:= NewRequest(TypeRunnerHello, map[string]any{
 "name": cfg.Name, "version": cfg.Version, "concurrent": cfg.Concurrent,
	})
	if err:= wsjson.Write(ctx, c, hello); err != nil {
 return err
	}
	ui.Success("已连接到 Server")
	// drain 缓冲队列
	for _, msg:= range queue.Drain {
 if err:= wsjson.Write(ctx, c, msg); err != nil {
 return err
 }
	}
	eg, ctx:= errgroup.WithContext(ctx)
	eg.Go(func error { return readLoop(ctx, c) })
	eg.Go(func error { return heartbeatLoop(ctx, c, cfg) })
	return eg.Wait
}
func readLoop(ctx context.Context, c *websocket.Conn) error {
	for {
 var msg Message
 if err:= wsjson.Read(ctx, c, &msg); err != nil {
 return err
 }
 log.Debug.Str("type", msg.Type).Msg("received message")
	}
}
func heartbeatLoop(ctx context.Context, c *websocket.Conn, cfg Config) error {
	ticker:= time.NewTicker(heartbeatInterval)
	defer ticker.Stop
	for {
 select {
 case <-ctx.Done:
 // 优雅关闭：发送 bye
 byeCtx, cancel:= context.WithTimeout(context.Background, 3*time.Second)
 defer cancel
 wsjson.Write(byeCtx, c, NewMessage(TypeRunnerBye, nil))
 c.Close(websocket.StatusNormalClosure, "bye")
 return ctx.Err
 case <-ticker.C:
 payload:= CollectMetrics(0, cfg.Concurrent, true)
 if err:= wsjson.Write(ctx, c, NewMessage(TypeRunnerHeartbeat, payload)); err != nil {
 return err
 }
 }
	}
}
func httpToWS(u string) string {
	u = strings.Replace(u, "https://", "wss://", 1)
	u = strings.Replace(u, "http://", "ws://", 1)
	return strings.TrimRight(u, "/")
}
