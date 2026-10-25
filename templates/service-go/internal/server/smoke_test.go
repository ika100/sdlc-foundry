package server

import (
	"context"
	"net/http"
	"os"
	"strings"
	"testing"
	"time"
)

// TestSmokeHealth is a smoke test (spec 091): `SMOKE_BASE_URL=https://<host> devbox run smoke` runs it
// against a deployment. It reaches the service only through its URL and is skipped without SMOKE_BASE_URL.
func TestSmokeHealth(t *testing.T) {
	if os.Getenv("SMOKE_BASE_URL") == "" {
		t.Skip("SMOKE_BASE_URL is not set")
	}
	base := strings.TrimRight(os.Getenv("SMOKE_BASE_URL"), "/")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, base+"/health", http.NoBody)
	if err != nil {
		t.Fatalf("building request: %v", err)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("GET %s/health: %v", base, err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("GET %s/health = %d, want 200", base, resp.StatusCode)
	}
}
