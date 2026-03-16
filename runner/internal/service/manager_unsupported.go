//go:build !darwin && !linux
package service
import "fmt"
func New(_ bool) (ServiceManager, error) {
	return nil, fmt.Errorf("当前操作系统不支持 service 命令")
}
