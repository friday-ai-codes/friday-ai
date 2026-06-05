package ws

import (
	"github.com/shirou/gopsutil/v4/cpu"
	"github.com/shirou/gopsutil/v4/disk"
	"github.com/shirou/gopsutil/v4/mem"
)

// HeartbeatPayload 是心跳消息的 payload，与 Server 端 consumers.py 对齐。
type HeartbeatPayload struct {
	CPUPercent    float64 `json:"cpu_percent"`
	MemPercent    float64 `json:"mem_percent"`
	MemTotalMB    uint64  `json:"mem_total_mb"`
	MemUsedMB     uint64  `json:"mem_used_mb"`
	DiskPercent   float64 `json:"disk_percent"`
	DiskTotalGB   uint64  `json:"disk_total_gb"`
	DiskUsedGB    uint64  `json:"disk_used_gb"`
	CurrentTasks  int     `json:"current_tasks"`
	MaxConcurrent int     `json:"max_concurrent"`
	Accepting     bool    `json:"accepting"`
}

// CollectMetrics 采集系统指标，错误静默处理。
func CollectMetrics(currentTasks, maxConcurrent int, accepting bool) HeartbeatPayload {
	p := HeartbeatPayload{
		CurrentTasks:  currentTasks,
		MaxConcurrent: maxConcurrent,
		Accepting:     accepting,
	}
	if pcts, err := cpu.Percent(0, false); err == nil && len(pcts) > 0 {
		p.CPUPercent = pcts[0]
	}
	if v, err := mem.VirtualMemory(); err == nil {
		p.MemPercent = v.UsedPercent
		p.MemTotalMB = v.Total / 1024 / 1024
		p.MemUsedMB = v.Used / 1024 / 1024
	}
	if d, err := disk.Usage("/"); err == nil {
		p.DiskPercent = d.UsedPercent
		p.DiskTotalGB = d.Total / 1024 / 1024 / 1024
		p.DiskUsedGB = d.Used / 1024 / 1024 / 1024
	}
	return p
}

// Warmup 预热 CPU 指标采集（首次调用返回 0）。
func Warmup() { cpu.Percent(0, false) }
