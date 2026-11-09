---
description: "Read-only quality and security audit for the repo (the devbox quality and security recipes); changes no file. Usage: /component:check"
---

You are the **orchestrator** for a quality and security check without edits. Run both agents against the current codebase and produce a combined report.

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

**Arguments:** $ARGUMENTS (none expected; ignore any).

First resolve the shape: run `cplat shape` and print `Shape: <shape>`. The commands below are the same for every shape (the repo's `devbox.json` maps them to the right tools). Image build/scan applies to a repo with a `Dockerfile`.

---

## Step 1 — Run quality and security agents in parallel

Invoke both at once:

**quality agent** — run with instruction:
> Run `devbox run quality` against the entire codebase. Report all violations with file:line references (no edits).

**security agent** — run with instruction:
> Run `devbox run security`. If a Dockerfile exists, also run `devbox run image-build && devbox run image-scan`. Document findings in `docs/security/scan-<today's date>.md` (no edits apart from that report).

Wait for both.

---

## Step 2 — Combine results

Print a unified report:

```
## Quality & Security Check Report
Date: <YYYY-MM-DD>

### Quality
<quality verdict and violation summary>

### Security
<security verdict and findings summary>

---

### Overall Verdict

One line each for lint / format, type check, dependency audit (N critical, N high), detect-secrets and trivy: PASS / FAIL / WARN / SKIPPED, with the counts.

**OVERALL: PASS / FAIL**
```

### Exit conditions

- **PASS:** all checks clean — safe to proceed with release or deployment.
- **FAIL:** one or more checks failed — list the issues to resolve.

---

## Rules

- This command is **read-only**: do not fix violations, install packages or modify files, so that a check never changes what it checks.
- If a tool is not installed, note it in the report as a gap but do not abort the other checks, so that one missing tool hides no other result.

Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).
