#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml", "ruamel.yaml"]
# ///
"""cplat — deterministic implementation of the sdlc-foundry commands.

The slash commands (plugins/*/commands/*.md) are thin: they run this script with --dry-run, show the plan to the user,
and run it for real. Everything that can be code is code (and has tests in tests/cplat).

  cplat.py new-service <name> <description…> [--web|--gitops|--library|--type SHAPE] [--app ORG/REPO] [--dry-run]
  cplat.py new-app <app.yml> [--resume] [--no-github] [--dry-run]   create a gitops-app repo + all component repos, one compose PR
  cplat.py update-service [--data KEY=VALUE] [--dry-run]
  cplat.py doctor [--json]
  cplat.py shape [--repo DIR]          shape + agent routing for the /svc:* orchestrators
  cplat.py shape check                 the platform's shape contract (run in the platform repo)
  cplat.py compose add|remove <service…> [--expose] [--env K=V] [--from-k8s] [--pr]   (run inside a gitops-app repo)
  cplat.py promote <service…|--all> <from> <to> [--version V] [--sha S] [--pr]
  cplat.py addon add|remove|list [postgres]   backing services of the application (app.yaml)
  cplat.py secret set|list ...         remote secrets of the local cluster (values never go to git)
  cplat.py feedback --title T [--what …] [--details-file F] [--submit]   draft (and file) a platform issue, secrets removed
  cplat.py triage list|show|setup-labels|apply ...   issue intake for /shared:triage (labels and comments only after you confirm; never closes)
  cplat.py status [--context KUBE_CONTEXT]   one table: pins per env, service CI, Argo sync/health
  cplat.py spec new|check|approve|set-status|task-done|hash|trace|index|list|migrate ...   feature specs in docs/specs/ (ADR-026)
  cplat.py ship start|status|phase|pr|land|deploy|escalate|finish|gate ...   /svc:ship: spec → merged PR → dev (ADR-028)
  cplat.py pr wait <number|url> [-R owner/repo] [--merge]   wait for a PR's CI, heal stuck or transient runs, merge on green (spec 079)
  cplat.py headless <prompt> [--max-runs N] [--max-minutes M] [--quiet HH:MM-HH:MM]   unattended claude -p runs that resume (spec 070)
  cplat.py build schedule|merge|state|replan-commit|replan-abort|resolved ...   /svc:build Phase 2: schedule, merge, re-plan on conflict (spec 094)
  cplat.py runs init|flush|report|begin|phase|end|agent|gate|usage|benchmark ...   private run records, agent metrics, usage and cost (specs 087, 089, 099)
  cplat.py deps findings|patch|report ...   patch fixable dependency findings of a red security gate (spec 095, ADR-034)
  cplat.py fleet update [--owner O] [--only owner/name] [--ref TAG] [--dry-run] [--json]   bring every platform repo to this release (spec 096)
  cplat.py adopt --type SHAPE [--data KEY=VALUE]   bring an existing repo onto the platform template (spec 071)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import core  # noqa: E402

COMMANDS = {
    "new-service": "newsvc",
    "new-app": "newapp",
    "update-service": "update",
    "doctor": "doctor",
    "shape": "shapecmd",
    "compose": "compose",
    "promote": "promote",
    "status": "status",
    "secret": "secret",
    "addon": "addon",
    "feedback": "feedback",
    "triage": "triage",
    "spec": "spec",
    "ship": "ship",
    "pr": "pr",
    "headless": "headless",
    "adopt": "adopt",
    "runs": "runs",
    "deps": "deps",
    "fleet": "fleet",
    "build": "buildcmd",
}


_REPORT_HINT = ("  This looks like a platform bug. Run `/shared:report-issue` (or `cplat feedback --title ...`) to file it; "
                "nothing is sent without your OK.")


def _file_crash(argv: list[str], exc: Exception) -> list[str]:
    """Spec 088: inside a recorded run the crash is filed or +1'd at once; otherwise (or if the hook fails) the hint."""
    try:
        import autoissue   # lazily: a broken import must not stop cplat from starting
        import runs
        cwd = Path.cwd()
        rid = runs.current(cwd)
        if rid:
            return autoissue.file_crash(argv, exc, rid, cwd).lines
    except Exception:  # noqa: BLE001  (the hook never changes a crash's exit code)
        pass
    return [_REPORT_HINT]


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help") or argv[0] not in COMMANDS:
        print(__doc__)
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    module = __import__(COMMANDS[argv[0]])
    try:
        return module.main(argv[1:])
    except core.PlatformError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        if e.hint:
            print(f"  fix: {e.hint}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001  (an unexpected crash is a platform defect, not a user error)
        print(f"ERROR: unexpected failure in `cplat {argv[0]}`: {type(e).__name__}: {e}", file=sys.stderr)
        for line in _file_crash(argv, e):
            print(line, file=sys.stderr)
        if os.environ.get("CPLAT_DEBUG"):
            raise
        return 70


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
