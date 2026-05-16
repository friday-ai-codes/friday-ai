package main
import (
	"fmt"
	"strings"
)
// Hello greets the given name.
func Hello(name string) string {
	return fmt.Sprintf("Hello, %s!", strings.TrimSpace(name))
}
func main {
	fmt.Println(Hello("gopls"))
}
