package config

import (
	"runtime"

	"github.com/shirou/gopsutil/v4/mem"
)

func DetectConcurrent() int {
	cpuBased := max(1, runtime.NumCPU()-1)
	memStat, err := mem.VirtualMemory()
	if err != nil {
		return min(cpuBased, 8)
	}
	memBased := max(1, int(memStat.Total/(1024*1024*1024)/2))
	return min(cpuBased, memBased, 8)
}
