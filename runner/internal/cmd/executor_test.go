package cmd

import "testing"

func TestResolveExecutorKind(t *testing.T) {
	cases := []struct {
		name    string
		raw     string
		want    string
		wantErr bool
	}{
		{"empty defaults docker", "", "docker", false},
		{"docker explicit", "docker", "docker", false},
		{"kubernetes canonical", "kubernetes", "kubernetes", false},
		{"k8s alias", "k8s", "kubernetes", false},
		{"unknown errors", "nomad", "", true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got, err := resolveExecutorKind(c.raw)
			if c.wantErr {
				if err == nil {
					t.Fatalf("resolveExecutorKind(%q) 期望 error，实际无", c.raw)
				}
				return
			}
			if err != nil {
				t.Fatalf("resolveExecutorKind(%q) 意外 error: %v", c.raw, err)
			}
			if got != c.want {
				t.Fatalf("resolveExecutorKind(%q) = %q, want %q", c.raw, got, c.want)
			}
		})
	}
}
