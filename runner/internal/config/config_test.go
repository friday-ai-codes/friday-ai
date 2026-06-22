package config

import (
	"testing"

	"github.com/spf13/viper"
)

// TestGetImagePullPolicy 钉死拉取策略归一：默认 missing，always/never 原样，
// 兼容 k8s 风格大小写写法（Always/Never/IfNotPresent），未知值兜底 missing。
func TestGetImagePullPolicy(t *testing.T) {
	cases := map[string]string{
		"":              "missing",
		"missing":       "missing",
		"ifnotpresent":  "missing",
		"IfNotPresent":  "missing",
		"always":        "always",
		"Always":        "always",
		"  ALWAYS  ":    "always",
		"never":         "never",
		"Never":         "never",
		"bogus-unknown": "missing",
	}
	for in, want := range cases {
		viper.Reset()
		viper.Set("executor.image_pull_policy", in)
		if got := GetImagePullPolicy(); got != want {
			t.Fatalf("GetImagePullPolicy(%q) = %q, want %q", in, got, want)
		}
	}
	viper.Reset()
}
