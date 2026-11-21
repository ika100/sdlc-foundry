**`cplat system ship land` ends each call within its budget, so no coordinator runs it in the background and waits on it with its own loop (#924).**
A land that waited longer than Claude Code's 600 s Bash limit was moved to the background, and the coordinator waited with a
`pgrep -f` loop that matched itself and ran its full 9.5 minutes. One call now stops its waits after `--budget` seconds (default 480)
and exits 3 with a `WAIT:` line; the next call resumes where it stopped (checks, Argo CD, smokes, staging), and the checks' own
`--timeout` still counts from the first call. A running land is a cplat wait the Stop hook sees (ADR-093) and detaches under
`cplat headless`. `/system:ship` runs land in the foreground and calls it again on exit 3.
