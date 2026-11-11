package server

import (
	"bytes"
	"encoding/json"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"
)

func logLine(t *testing.T, traceparent string) map[string]any {
	t.Helper()
	var buf bytes.Buffer
	logger := slog.New(NewTraceHandler(slog.NewJSONHandler(&buf, nil)))
	h := TraceContext(http.HandlerFunc(func(_ http.ResponseWriter, req *http.Request) {
		logger.InfoContext(req.Context(), "request")
	}))
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	if traceparent != "" {
		req.Header.Set("traceparent", traceparent)
	}
	h.ServeHTTP(httptest.NewRecorder(), req)
	var m map[string]any
	if err := json.Unmarshal(buf.Bytes(), &m); err != nil {
		t.Fatalf("log line is not JSON: %v", err)
	}
	return m
}

func TestTraceparentLogsIDs(t *testing.T) {
	m := logLine(t, "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
	if m["trace_id"] != "4bf92f3577b34da6a3ce929d0e0e4736" || m["span_id"] != "00f067aa0ba902b7" {
		t.Fatalf("unexpected ids: %v", m)
	}
}

func TestNoOrInvalidTraceparentLogsNothing(t *testing.T) {
	for _, tp := range []string{
		"",
		"garbage",
		"01-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
		"00-00000000000000000000000000000000-00f067aa0ba902b7-01",
		"00-4bf92f3577b34da6a3ce929d0e0e4736-0000000000000000-01",
		"00-4BF92F3577B34DA6A3CE929D0E0E4736-00f067aa0ba902b7-01",
	} {
		m := logLine(t, tp)
		if _, ok := m["trace_id"]; ok {
			t.Errorf("%q: trace_id present", tp)
		}
		if _, ok := m["span_id"]; ok {
			t.Errorf("%q: span_id present", tp)
		}
	}
}
