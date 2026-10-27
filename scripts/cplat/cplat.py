#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml", "ruamel.yaml"]
# ///
"""cplat — deterministic implementation of the sdlc-foundry commands, grouped by noun (5.0).

The slash commands (plugins/*/commands/*.md) are thin: they run this script with --dry-run, show the plan to the user,
and run it for real. Everything that can be code is code (and has tests in tests/cplat).

  cplat system new <manifest.yml> [--resume] [--no-github] [--dry-run]   create a gitops-app repo + all component repos, one component PR
  cplat system status [--context KUBE_CONTEXT] [--json]   one table: components by environment, CI, Argo sync/health
  cplat system ship start|status|phase|publish|next|repo|entry|complete|escalate|finish|gate ...   /system:ship: a product spec → every repo → dev
  cplat component new <name> <description…> [--type service|website|library] [--lang python|java|go|typescript] [--system OWNER/REPO] [--dry-run]
  cplat component add|set|remove <component…> [--type T] [--lang L] [--expose] [--env K=V] [--instance ENV --replicas N] [--from-k8s] [--pr]
  cplat component ship start|status|phase|pr|land|deploy|escalate|finish|gate ...   /component:ship: spec → merged PR → dev
  cplat component build schedule|merge|state|replan-commit|replan-abort|resolved ...   /component:build Phase 2
  cplat cluster new <name> [--org O] [--public] | add <owner>/<repo> [--name S] | remove <system>   the cluster repo and the systems it installs
  cplat api list [--system NAME] [--repo-dir DIR] [--json]   the system's APIs with type, provider and consumers
  cplat resource add|remove postgres [--version N]   the system's database resource (system.yaml)
  cplat resource backup <db> --env ENV [--context C] [--json]   one base backup of a database now
  cplat resource restore <db> --env ENV (--to TIME|latest | --switch | --discard) [--confirm prod] [--context C] [--dry-run] [--json]   restore a database
  cplat system restore <env> [--backup NAME or latest] [--replace] [--confirm prod] [--context C] [--json]   restore an environment from its Velero backup
  cplat instance promote <component…|--all> --to <env> [--version V] [--sha S] [--pr]
  cplat instance secret set <component>/<env> <secret> <KEY> | list [--env dev]   remote secrets of the local cluster (values never go to git)
  cplat instance verify [ENV] [--base-url URL] [--spec SPEC] [--no-retry] [--json]   the repo's smoke tests against a deployment
  cplat issue triage list|show|setup-labels|apply ...   issue intake (labels and comments only after you confirm; never closes)
  cplat platform doctor [--json]
  cplat platform update [--migrate] [--data KEY=VALUE] [--dry-run]
  cplat platform fleet update [--owner O] [--only owner/name] [--ref TAG] [--dry-run] [--json]   bring every platform repo to this release
  cplat platform runs init|flush|report|begin|phase|end|agent|gate|usage|benchmark ...   private run records, agent metrics, usage and cost
  cplat system set --env ENV [--promote RULE] [--policy POLICY] [--host HOST]   one environment's promote rule, policy or host
  cplat runs [--json] [--since DAYS] [--repo OWNER/NAME] [--spec ID]   the run list (active and recent runs)
  cplat needs [--json] [--repo-dir DIR] [--system NAME]   what waits for your decision
  cplat ui | cplat platform ui   the local console
  cplat platform retro [--week W] [--json] [--out DIR] | propose --dir DIR | post [--dir DIR]   weekly platform retro

Plumbing keeps its name:
  cplat shape [--repo DIR]             shape + agent routing for the orchestrators; `shape check` is the platform's shape contract
  cplat feedback --title T [--what …] [--details-file F] [--submit]   draft (and file) a platform issue, secrets removed
  cplat model show [--json] [--app APP] [--repo-dir DIR]   the declared domain model of a gitops-app
  cplat spec new|check|approve|set-status|task-done|hash|trace|index|list|migrate ...   feature specs in docs/specs/ (ADR-026)
  cplat pr wait|open …   wait <number|url> [-R owner/repo] [--merge]: CI watch; open --title T: commit -s, push, PR in one step
  cplat quiet <devbox-script>   run it with output in a log: one line on success, the tail and log path on failure
  cplat validate plan|run|final [--base REF] [--full] [--risk low|medium|high]   change-aware validation of the inner loop
  cplat headless <prompt> [--max-runs N] [--max-minutes M] [--quiet HH:MM-HH:MM]   unattended claude -p runs that resume
  cplat deps findings|patch|report ...   patch fixable dependency findings of a red security gate
  cplat alerts poll [--dry-run] [--app APP]   firing alerts become issues
  cplat budget show|gate|attempt|stage|resume ...   one budget per run tree, no-progress stops, verified stages for resume
  cplat adopt --type SHAPE [--data KEY=VALUE]   bring an existing repo onto the platform template
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import core  # noqa: E402

# noun -> verb -> (module, argv prefix put before the remaining args)
NOUNS: dict[str, dict[str, tuple[str, list[str]]]] = {
    "system": {"new": ("newapp", []), "status": ("status", []), "ship": ("appship", []),
               "restore": ("envrestore", []),
               "set": ("systemset", [])},
    "component": {"new": ("newsvc", []), "add": ("compose", ["add"]), "set": ("compose", ["set"]), "remove": ("compose", ["remove"]),
                  "ship": ("ship", []), "build": ("buildcmd", [])},
    "cluster": {"new": ("clusterrepo", ["new"]), "add": ("clusterrepo", ["add"]), "remove": ("clusterrepo", ["remove"])},
    "api": {"list": ("apilist", [])},
    "resource": {"add": ("addon", ["add"]), "remove": ("addon", ["remove"]),
                 "backup": ("dbbackup", []), "restore": ("dbrestore", [])},
    "instance": {"promote": ("promote", []), "secret": ("secret", []), "verify": ("smoke", ["run"])},
    "issue": {"triage": ("triage", [])},
    "platform": {"doctor": ("doctor", []), "update": ("update", []), "fleet": ("fleet", []), "runs": ("runs", []), "retro": ("retro", []),
                 "ui": ("ui", [])},
}

PLUMBING = {
    "shape": "shapecmd", "feedback": "feedback", "model": "modelcmd", "spec": "spec", "pr": "pr", "quiet": "quiet", "validate": "validate",
    "headless": "headless", "deps": "deps", "alerts": "alerts", "budget": "budget", "adopt": "adopt",
    "needs": "needs", "ui": "ui",
}

# 4.x top-level name -> its 5.0 form (exit 2, the module is not imported)
MOVED = {
    "new-app": "system new", "status": "system status", "app-ship": "system ship", "new-service": "component new",
    "compose": "component add|set|remove", "ship": "component ship", "build": "component build", "addon": "resource add|remove",
    "promote": "instance promote", "secret": "instance secret", "smoke": "instance verify", "triage": "issue triage",
    "doctor": "platform doctor", "update-service": "platform update", "fleet": "platform fleet", "runs": "platform runs",
    "retro": "platform retro",
}


RUNLIST_VALUED = ("--since", "--repo", "--spec")

_REPORT_HINT = ("  This looks like a platform bug. Run `/issue:report` (or `cplat feedback --title ...`) to file it; "
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


def _resolve(argv: list[str]) -> tuple[str, list[str], str] | int:
    """(module, its argv, label of the command), or the exit code after printing."""
    name = argv[0] if argv else ""
    if name in ("-h", "--help"):
        print(__doc__)
        return 0
    if name == "runs" and all(a.startswith("-") or (i and argv[i].lstrip("-").isdigit()) or (i and argv[i - 1] in RUNLIST_VALUED)
                              for i, a in enumerate(argv[1:], 1)):
        return "runlist", argv[1:], name   # spec 122: the verb-less form lists runs; `runs <verb>` stays moved
    if name in MOVED:
        print(f"`cplat {name}` is `cplat {MOVED[name]}` in 5.0", file=sys.stderr)
        return 2
    if name in PLUMBING:
        return PLUMBING[name], argv[1:], name
    if name in NOUNS:
        verbs = NOUNS[name]
        if len(argv) > 1 and argv[1] in ("-h", "--help"):
            print(__doc__)
            return 0
        if len(argv) < 2 or argv[1] not in verbs:
            print(f"usage: cplat {name} <verb> ...  (verbs: {' '.join(verbs)})", file=sys.stderr)
            for v in verbs:
                print(f"  cplat {name} {v}", file=sys.stderr)
            return 2
        module, prefix = verbs[argv[1]]
        return module, [*prefix, *argv[2:]], f"{name} {argv[1]}"
    print(__doc__)
    return 2


def main(argv: list[str]) -> int:
    resolved = _resolve(argv)
    if isinstance(resolved, int):
        return resolved
    modname, rest, label = resolved
    module = __import__(modname)
    try:
        return module.main(rest)
    except core.PlatformError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        if e.hint:
            print(f"  fix: {e.hint}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001  (an unexpected crash is a platform defect, not a user error)
        print(f"ERROR: unexpected failure in `cplat {label}`: {type(e).__name__}: {e}", file=sys.stderr)
        for line in _file_crash(argv, e):
            print(line, file=sys.stderr)
        if os.environ.get("CPLAT_DEBUG"):
            raise
        return 70


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
