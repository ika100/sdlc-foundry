---
description: "Read-only quality and security audit for the repo (the devbox quality and security recipes); changes no file. Usage: /component:check"
---

You are the **orchestrator** for a read-only quality and security check. Run both agents against the current codebase and produce a combined report. Do not modify any files.

**Arguments:** $ARGUMENTS (none expected; ignore any).

First resolve the shape: run `cplat shape` and print `Shape: <shape>`. The commands below are the same for every shape (the repo's `devbox.json` maps them to the right tools). Image build/scan only applies when a `Dockerfile` exists.

---

## Step 1 — Run quality and security agents in parallel

Invoke both agents simultaneously:

**quality agent** — run with instruction:
> Run `devbox run quality` against the entire codebase. Report all violations with file:line references. Do not modify any files.

**security agent** — run with instruction:
> Run `devbox run security`. If a Dockerfile exists, also run `devbox run image-build && devbox run image-scan`. Document findings in `docs/security/scan-<today's date>.md`. Do not modify any application code.

Wait for both agents to complete.

---

## Step 2 — Combine results

Print a unified report:

```
## Quality & Security Check Report
Date: <YYYY-MM-DD>

### Quality
<paste quality agent verdict and violation summary>

### Security
<paste security agent verdict and findings summary>

---

### Overall Verdict

| Check | Result |
|---|---|
| Lint / format (ruff, ESLint, Spotless, golangci-lint, kubeconform …) | PASS / FAIL (N violations) |
| Type check (mypy, `tsc`, compiler …) | PASS / FAIL (N errors) |
| Dependency audit (pip-audit, pnpm audit, OWASP DC, govulncheck …) | PASS / FAIL / WARN (N critical, N high) |
| detect-secrets | PASS / N potential secrets found |
| trivy | PASS / FAIL / SKIPPED |

**OVERALL: PASS / FAIL**
```

### Exit conditions

- **PASS:** all checks clean — safe to proceed with release or deployment.
- **FAIL:** one or more checks failed — list the issues that must be resolved.

---

## Rules

- This command is **read-only** — do not fix violations, install packages, or modify files.
- If a tool is not installed, note it in the report as a gap but do not abort the other checks.
- The security scan report file (`docs/security/scan-<date>.md`) is the one exception — the security agent creates that as its normal output.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.
