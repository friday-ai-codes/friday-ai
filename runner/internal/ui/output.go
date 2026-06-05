package ui

import (
	"fmt"
	"os"

	"github.com/charmbracelet/lipgloss/v2"
)

var ci = detectCI()

func detectCI() bool {
	for _, key := range []string{"CI", "GITHUB_ACTIONS", "GITLAB_CI", "JENKINS_URL"} {
		if os.Getenv(key) != "" {
			return true
		}
	}
	return false
}

func IsCI() bool { return ci }

var (
	greenStyle  = lipgloss.NewStyle().Foreground(lipgloss.Color("2"))
	redStyle    = lipgloss.NewStyle().Foreground(lipgloss.Color("1"))
	yellowStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("3"))
	grayStyle   = lipgloss.NewStyle().Foreground(lipgloss.Color("8"))
)

func Success(msg string) {
	if ci {
		fmt.Fprintf(os.Stderr, "[OK] %s\n", msg)
	} else {
		fmt.Fprintln(os.Stderr, greenStyle.Render("✓ "+msg))
	}
}

func Error(msg string) {
	if ci {
		fmt.Fprintf(os.Stderr, "[ERROR] %s\n", msg)
	} else {
		fmt.Fprintln(os.Stderr, redStyle.Render("✗ "+msg))
	}
}

func Warn(msg string) {
	if ci {
		fmt.Fprintf(os.Stderr, "[WARN] %s\n", msg)
	} else {
		fmt.Fprintln(os.Stderr, yellowStyle.Render("⚠ "+msg))
	}
}

func Info(msg string) {
	fmt.Fprintf(os.Stderr, "  %s\n", msg)
}

func Hint(msg string) {
	if ci {
		fmt.Fprintf(os.Stderr, "  -> %s\n", msg)
	} else {
		fmt.Fprintln(os.Stderr, grayStyle.Render("  → "+msg))
	}
}
