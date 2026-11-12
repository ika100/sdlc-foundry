package server

import (
	"context"
	"log/slog"
	"net/http"
	"regexp"
	"strings"
)

type traceKey struct{}

type traceIDs struct{ traceID, spanID string }

// TraceContext reads the W3C `traceparent` request header and stores its trace
// id and span id in the request context. An absent or invalid header stores nothing.
func TraceContext(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		if t, s, ok := parseTraceparent(req.Header.Get("traceparent")); ok {
			ctx := context.WithValue(req.Context(), traceKey{}, traceIDs{t, s})
			req = req.WithContext(ctx)
		}
		next.ServeHTTP(w, req)
	})
}

// TraceIDs returns the trace and span id stored by TraceContext.
func TraceIDs(ctx context.Context) (traceID, spanID string, ok bool) {
	v, ok := ctx.Value(traceKey{}).(traceIDs)
	if !ok {
		return "", "", false
	}
	return v.traceID, v.spanID, true
}

var traceparentRE = regexp.MustCompile(`^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$`)

func parseTraceparent(h string) (traceID, spanID string, ok bool) {
	m := traceparentRE.FindStringSubmatch(h)
	if m == nil {
		return "", "", false
	}
	traceID, spanID = m[1], m[2]
	if strings.Trim(traceID, "0") == "" || strings.Trim(spanID, "0") == "" {
		return "", "", false
	}
	return traceID, spanID, true
}

type traceHandler struct{ slog.Handler }

// NewTraceHandler wraps h so every record logged with a context carrying trace
// ids gets `trace_id` and `span_id` attributes.
func NewTraceHandler(h slog.Handler) slog.Handler { return traceHandler{h} }

func (h traceHandler) Handle(ctx context.Context, r slog.Record) error {
	if t, s, ok := TraceIDs(ctx); ok {
		r.AddAttrs(slog.String("trace_id", t), slog.String("span_id", s))
	}
	return h.Handler.Handle(ctx, r)
}

func (h traceHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	return traceHandler{h.Handler.WithAttrs(attrs)}
}

func (h traceHandler) WithGroup(name string) slog.Handler {
	return traceHandler{h.Handler.WithGroup(name)}
}
