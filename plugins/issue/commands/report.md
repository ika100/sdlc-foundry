---
description: "Report a platform problem or idea as a GitHub issue, with secrets removed. Nothing is sent without your OK. Usage: /issue:report [what went wrong]"
---

Help the user report a platform problem or idea. **Context from the user:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

1. **Gather**: what was running (command or step), what happened versus what was expected, and this session's error text. Use what you know; ask at most one short question for anything essential that is missing. Never include secrets, and user code only as far as it reproduces the problem, because the issue is public.
2. **Draft** (nothing is sent). Write the error output to a temp file under `$CLAUDE_JOB_DIR/tmp` (or `$TMPDIR`) and run:

```bash
cplat feedback --kind bug|idea --title "<one line>" --what "<what happened>" --command "<the command or step>" --details-file <file>
```

3. **Show the draft verbatim and ask**: "File this issue on ika100/sdlc-foundry? It is a **public** repository, so anyone can read it." The draft has tokens, e-mail addresses and home-directory names removed; the user reads it first.
4. **After an explicit yes**, run the same command again with `--submit` and give the user the issue URL. Without `gh` it prints a prefilled browser link; hand that over.

**Hard rule:** never submit without the user's yes, because the platform repository is public. One issue per problem; include `cplat`'s own error text if it crashed.

Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.
