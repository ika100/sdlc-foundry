"""Measure one recorded journey for docs/PERFORMANCE.md: wall clock split, tokens, a person's share and GitHub CI.

  python3 scripts/journey/measure.py <session> <start> <end> <owner/repo>... [--json]

<session> is the Claude Code transcript of the recorded session without `.jsonl`
(~/.claude/projects/<dir>/<id>); its subagents are read from <session>/subagents/. <start> and <end> are ISO times (UTC)
of the journey. The repos are the journey's demo repos.

Each minute of the wall clock is counted once, agent work first: a person (a question open, or the gap until the next
input), agents working (model turns and local commands), or waiting with no agent working (CI and merges, deploys and
Argo, promotions and restores, cluster, smoke). Tokens are summed per API message (each message once), main thread and
subagents. GitHub numbers come from `gh run list` and `gh pr list` within the window.
"""

import collections
import datetime as dt
import glob
import json
import re
import subprocess
import sys

WAIT_CATS = [  # (category, regex on the Bash command), first match wins
    ("deploy", r"ship deploy|system wait|cluster wait|ship wait|ship next --wait|release wait"),
    ("ci", r"cplat pr wait|gh run watch|gh pr checks|gh run view|ship land|entry land|spec land|ship pr\b|pr merge|pin-dev"
     r"|gh run list|check-runs|check-suites|devbox run ci"),
    ("promote", r"instance promote|resource restore|resource add|system set|component set|component add|system new"),
    ("smoke", r"instance verify|curl "),
    ("cluster", r"kubectl|argocd|rollout|wait --for|cluster-up|bootstrap|helm"),
    ("tests", r"devbox run (test|quality|lint|typecheck|security|smoke|validate|test-fast|e2e)|pytest|vitest|pnpm"
     r"|npm (run|test)|uv run|playwright|docker build"),
    ("platform", r"cplat |gh pr create|gh api|git push|git commit|copier"),
]
WAITING = {"ci", "deploy", "promote", "smoke", "cluster"}
# agent work first: a minute in which any agent works counts as agent work, even while another thread waits
PRIO = ["person", "model", "tests", "shell", "platform", "files", "other", "smoke", "promote", "cluster", "ci", "deploy"]
STEP = 5.0


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def category(name, inp):
    if name == "Agent":
        return "subagent"
    if name == "Bash":
        cmd = (inp or {}).get("command", "")
        if re.search(r"\bsleep \d|until |while true|for i in \$\(seq", cmd) and re.search(r"gh |cplat ", cmd):
            return "deploy" if "ship status" in cmd or "deployed" in cmd else ("ci" if re.search(r"pr |checks|run ", cmd) else "cluster")
        return next((c for c, rx in WAIT_CATS if re.search(rx, cmd)), "shell")
    if name in ("Read", "Write", "Edit", "Grep", "Glob"):
        return "files"
    return "person" if name == "AskUserQuestion" else "other"


def thread(path, main):
    events = [e for e in (json.loads(line) for line in open(path)) if e.get("timestamp")]
    uses, ivs, prompts, last = {}, [], [], None
    for e in events:
        t, content = ts(e["timestamp"]), (e.get("message") or {}).get("content")
        if e.get("type") == "assistant" and isinstance(content, list):
            for c in content:
                if c.get("type") == "tool_use":
                    uses[c["id"]] = (t, c.get("name"), c.get("input"))
            last = t
        elif e.get("type") == "user":
            if isinstance(content, list):
                for c in content:
                    if c.get("type") == "tool_result" and c.get("tool_use_id") in uses:
                        t0, n, inp = uses.pop(c["tool_use_id"])
                        ivs.append((t0, t, category(n, inp)))
            elif isinstance(content, str) and main and not e.get("isMeta") and last and not content.startswith("<"):
                prompts.append((last, t))
    return ivs, prompts, (ts(events[0]["timestamp"]), ts(events[-1]["timestamp"]))


def wall_split(session, start, end):
    main_ivs, prompts, (w0, w1) = thread(session + ".jsonl", True)
    w0, w1 = max(w0, start), min(w1, end)
    subs = [thread(p, False) for p in glob.glob(session + "/subagents/*.jsonl")]
    person = [(a, b) for a, b in prompts if b > a] + [(a, b) for a, b, c in main_ivs if c == "person"]
    threads = [(main_ivs, (w0, w1))] + [(iv, span) for iv, _, span in subs]
    minutes, t = collections.Counter(), w0
    while t < w1:
        active = set()
        if any(a <= t < b for a, b in person):
            active.add("person")
        else:
            for ivs, (s0, s1) in threads:
                if not s0 <= t < s1:
                    continue
                here = [c for a, b, c in ivs if a <= t < b and c not in ("subagent", "person")]
                if here:
                    active.update(here)
                elif not any(c == "subagent" and a <= t < b for a, b, c in ivs):
                    active.add("model")
        minutes[next((p for p in PRIO if p in active), "model")] += STEP / 60
        t += STEP
    turns = sum(1 for a, b in prompts if w0 <= b <= w1)
    return {"wall_min": (w1 - w0) / 60, "subagents": len(subs), "inputs": turns,
            "by_category": {c: round(minutes[c], 1) for c in PRIO},
            "person_min": round(minutes["person"], 1),
            "waiting_min": round(sum(minutes[c] for c in WAITING), 1),
            "agents_min": round(sum(minutes[c] for c in PRIO if c not in WAITING and c != "person"), 1)}


def tokens(session, start, end):
    seen, tot, out_by_model = set(), collections.Counter(), collections.Counter()
    for path in [session + ".jsonl"] + glob.glob(session + "/subagents/*.jsonl"):
        for line in open(path):
            e = json.loads(line)
            if e.get("type") != "assistant" or not e.get("timestamp") or not start <= ts(e["timestamp"]) <= end:
                continue
            m = e.get("message") or {}
            if not m.get("id") or m["id"] in seen:
                continue
            seen.add(m["id"])
            u = m.get("usage") or {}
            for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"):
                tot[k] += u.get(k) or 0
            out_by_model[m.get("model", "?")] += u.get("output_tokens") or 0
    total = sum(tot.values())
    return {"api_calls": len(seen), "input": tot["input_tokens"], "cache_write": tot["cache_creation_input_tokens"],
            "cache_read": tot["cache_read_input_tokens"], "output": tot["output_tokens"], "total": total,
            "output_by_model": dict(out_by_model)}


def github(repos, start, end):
    runs, merged = [], 0
    for repo in repos:
        out = subprocess.run(["gh", "run", "list", "-R", repo, "--limit", "1000", "--json", "createdAt,startedAt,updatedAt,conclusion"],
                             capture_output=True, text=True, check=True).stdout
        runs += [r for r in json.loads(out) if start <= ts(r["createdAt"]) <= end]
        out = subprocess.run(["gh", "pr", "list", "-R", repo, "--state", "merged", "--limit", "500", "--json", "mergedAt"],
                             capture_output=True, text=True, check=True).stdout
        merged += sum(1 for p in json.loads(out) if start <= ts(p["mergedAt"]) <= end)
    spans = sorted((ts(r["startedAt"]), ts(r["updatedAt"])) for r in runs)
    active, cur = 0.0, None
    for s, e in spans:
        if cur and s <= cur[1]:
            cur = (cur[0], max(cur[1], e))
        else:
            active += (cur[1] - cur[0]) if cur else 0
            cur = (s, e)
    active += (cur[1] - cur[0]) if cur else 0
    return {"merged_prs": merged, "runs": len(runs), "failed_runs": sum(r["conclusion"] == "failure" for r in runs),
            "run_min": round(sum(e - s for s, e in spans) / 60), "queue_min": round(sum(max(0, ts(r["startedAt"]) - ts(r["createdAt"])) for r in runs) / 60),
            "ci_active_min": round(active / 60)}


def main(argv):
    as_json = "--json" in argv
    session, start, end, *repos = [a for a in argv if a != "--json"]
    start, end = ts(start), ts(end)
    result = {"wall": wall_split(session, start, end), "tokens": tokens(session, start, end), "github": github(repos, start, end)}
    if as_json:
        print(json.dumps(result, indent=2))
        return
    w, t, g = result["wall"], result["tokens"], result["github"]
    print(f"wall clock {w['wall_min']:.0f} min, {w['subagents']} subagents, {w['inputs']} inputs")
    print(f"  person {w['person_min']}, waiting {w['waiting_min']}, agents {w['agents_min']}  ({w['by_category']})")
    print(f"tokens {t['total'] / 1e6:.1f} M in {t['api_calls']} calls: input {t['input']}, cache write {t['cache_write']},"
          f" cache read {t['cache_read']}, output {t['output']}; output by model {t['output_by_model']}")
    print(f"github {g['merged_prs']} merged PRs, {g['runs']} runs ({g['failed_runs']} failed), {g['run_min']} min run,"
          f" {g['queue_min']} min queued, CI active {g['ci_active_min']} min")


if __name__ == "__main__":
    main(sys.argv[1:])
