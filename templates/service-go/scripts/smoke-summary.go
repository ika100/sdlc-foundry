//go:build ignore

// Platform-owned (spec 091): turns `go test -json` (stdin) into the result lines of `devbox run smoke`:
// one `PASS|FAIL|SKIP  <dir>/<file>_test.go::<TestName>` line per top-level test, then
// `smoke: <p> passed, <f> failed, <s> skipped`, or `0 smoke tests`.
// A package that does not build gives `FAIL  <dir>::(build)`.
// Run: go test -json ... | go run scripts/smoke-summary.go
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

type event struct {
	Action  string `json:"Action"`
	Package string `json:"Package"`
	Test    string `json:"Test"`
}

func modulePath() string {
	data, err := os.ReadFile("go.mod")
	if err != nil {
		return ""
	}
	if m := regexp.MustCompile(`(?m)^module\s+(\S+)`).FindSubmatch(data); m != nil {
		return strings.Trim(string(m[1]), `"`)
	}
	return ""
}

// testFile finds the *_test.go file of dir that declares the test function.
func testFile(dir, name string) string {
	decl := regexp.MustCompile(`(?m)^func\s+` + regexp.QuoteMeta(name) + `\s*\(`)
	files, _ := filepath.Glob(filepath.Join(dir, "*_test.go"))
	for _, f := range files {
		if data, err := os.ReadFile(f); err == nil && decl.Match(data) {
			return filepath.ToSlash(f)
		}
	}
	return filepath.ToSlash(filepath.Join(dir, "(unknown)_test.go"))
}

func packageDir(module, pkg string) string {
	dir := strings.TrimPrefix(strings.TrimPrefix(pkg, module), "/")
	if dir == "" {
		return "."
	}
	return dir
}

func main() {
	module := modulePath()
	var lines []string
	passed, failed, skipped := 0, 0, 0
	testFailed := map[string]bool{}
	packageFailed := []string{}
	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 1024*1024), 16*1024*1024)
	for scanner.Scan() {
		var ev event
		if json.Unmarshal(scanner.Bytes(), &ev) != nil {
			continue
		}
		dir := packageDir(module, ev.Package)
		if ev.Test == "" {
			if ev.Action == "fail" {
				packageFailed = append(packageFailed, ev.Package)
			}
			continue
		}
		if strings.Contains(ev.Test, "/") {
			continue // sub-tests are part of their top-level test
		}
		result := ""
		switch ev.Action {
		case "pass":
			result = "PASS"
			passed++
		case "fail":
			result = "FAIL"
			failed++
			testFailed[ev.Package] = true
		case "skip":
			result = "SKIP"
			skipped++
		default:
			continue
		}
		lines = append(lines, result+"  "+testFile(dir, ev.Test)+"::"+ev.Test)
	}
	for _, pkg := range packageFailed {
		if !testFailed[pkg] { // the package failed without a failing test: it did not build
			lines = append(lines, "FAIL  "+packageDir(module, pkg)+"::(build)")
			failed++
		}
	}
	if len(lines) == 0 {
		fmt.Println("0 smoke tests")
		return
	}
	for _, l := range lines {
		fmt.Println(l)
	}
	fmt.Printf("smoke: %d passed, %d failed, %d skipped\n", passed, failed, skipped)
}
