package cmd
import (
	"io"
	"os"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"github.com/spf13/cobra"
	"github.com/friday-ai-codes/friday-ai/runner/internal/config"
)
var (
	cfgFile string
	verbose bool
	jsonLog bool
	Version = "dev"
)
var rootCmd = &cobra.Command{
	Use: "friday-runner",
	Short: "Friday AI Runner - 独立任务执行器",
	Version: Version,
	PersistentPreRunE: func(cmd *cobra.Command, args string) error {
 if verbose {
 zerolog.SetGlobalLevel(zerolog.DebugLevel)
 } else {
 zerolog.SetGlobalLevel(zerolog.InfoLevel)
 }
 var w io.Writer = os.Stderr
 if !jsonLog {
 w = zerolog.ConsoleWriter{Out: os.Stderr}
 }
 log.Logger = zerolog.New(w).With.Timestamp.Logger
 if cfgFile != "" {
 return config.InitWithPath(cfgFile)
 }
 return config.Init
	},
}
func init {
	rootCmd.PersistentFlags.StringVar(&cfgFile, "config", "", "配置文件路径")
	rootCmd.PersistentFlags.BoolVarP(&verbose, "verbose", "v", false, "详细日志输出")
	rootCmd.PersistentFlags.BoolVar(&jsonLog, "json-log", false, "JSON 格式日志输出")
}
func Execute error {
	return rootCmd.Execute
}
