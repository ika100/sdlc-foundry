---
spec_id: 085-a-broken-spec-names-itself-and-stops
title: A broken spec names itself and stops nothing else
status: approved
priority: P1
tracks: [129]
---

# 085 — A broken spec names itself and stops nothing else

## Problem

Every `cplat spec` command reads every spec in the repo. So one spec whose front matter is not valid YAML, for example an unquoted `title: a: b`, makes every spec command fail with a bare YAML scanner error that names neither the file nor the fix. While specs 077 to 084 were being written, one unquoted colon blocked `cplat spec approve` for all eight of them, and someone had to find the bad file by hand (#129). This round adds thirteen specs written in parallel and later shipped unattended, so one typo must not stop the whole pipeline. A broken spec should name itself (file, line, how to fix it) and block only commands that need that spec.

## Stories

As a spec author (a person or the product-manager agent), I want a broken spec to report its file, its line and how to fix it, so that I can fix it in one edit instead of searching for it.

As the orchestrator of an unattended run, I want the commands for my spec to keep working when some other spec in the repo is broken, so that my run does not escalate over a file it never touches.

As a maintainer reading the spec list, index or CI output, I want a broken spec shown as broken and not silently left out, so that nothing disappears from the backlog without notice.

## Acceptance criteria

Throughout, "broken" means a spec's `spec.md` or `plan.md` front matter cannot be read: it is not valid YAML, it is missing the `---` fences, or it is not a mapping of keys to values. "Names itself" means the message contains the file's path relative to the repo root, the line number in that file, and a fix hint.

- **AC-085.1** Given a spec whose `spec.md` has `title: a: b` on line 3, when any `cplat spec` command reads that spec, then the command fails with an error that contains the path `docs/specs/<id>/spec.md`, line 3, and the hint `values that contain ': ' must be quoted, e.g. title: "a: b"`. No YAML stack trace is printed.
- **AC-085.2** Given a spec whose `spec.md` has no front-matter fences, or front matter that is valid YAML but not a mapping (for example a plain list), when any `cplat spec` command reads it, then the error names the file, line 1 and what the front matter must look like (`---`, `key: value` lines, `---`).
- **AC-085.3** Given a spec whose `plan.md` front matter is broken and whose `spec.md` is fine, when a command reads that spec, then the error names `docs/specs/<id>/plan.md` and the line, the same way as AC-085.1.
- **AC-085.4** Given one broken spec and other valid specs in the same repo, when `cplat spec approve`, `set-status`, `task-done`, `hash`, `trace` or `check` is run for a valid spec, then it gives the same result and exit code as it would with no broken spec in the repo. The broken spec's files are not modified.
- **AC-085.5** Given one broken spec and other valid specs, when `cplat ship` is run for a valid spec, then no step of the run fails or escalates because of the broken spec.
- **AC-085.6** Given one broken spec, when `cplat spec approve`, `set-status`, `task-done`, `hash` or `trace` addresses that spec by id, number or slug, then the command fails with exit code 1 and the error from AC-085.1 to AC-085.3, and no file is written.
- **AC-085.7** Given one broken spec and other valid specs, when `cplat spec check` is run without ids, then each valid spec is checked as usual, the broken spec gets one `ERROR: <id>:` line that names the file and line, the error count includes it, and the exit code is 1.
- **AC-085.8** Given one broken spec, when `cplat spec ci` runs (with or without `--strict`), then the output has one `::error` annotation whose file and line point to the bad line of the broken spec, the other specs are checked and traced as usual, and the exit code is 1.
- **AC-085.9** Given one broken spec and other valid specs, when `cplat spec list` is run (with or without `--json`), then every valid spec is listed as usual, the broken spec is listed under its folder id with status `broken`, and its next step tells the user to fix the named file and line. The exit code is 0.
- **AC-085.10** Given one broken spec, when `cplat spec index` regenerates the backlog table, then the broken spec keeps a row under its folder id, with status `broken` and an empty title, and all valid specs are shown as usual.
- **AC-085.11** Given a broken spec numbered 090, and 090 is the highest number in the repo, when `cplat spec new <title>` runs, then the new spec is numbered 091.
- **AC-085.12** Given a title that YAML would otherwise misread, such as `a: b`, `#7 retry`, `- list`, `[draft]`, `yes`, `null`, `123`, or a title that starts with a quote, when `cplat spec new <title>` creates the spec, then reading its front matter back returns the title exactly as typed, as a string, and `cplat spec check` reports no error for it.

## Non-goals

- Fixing a broken file automatically, for example by adding quotes for the author. The error only names the file, the line and the fix.
- Checks on front-matter content (missing keys, wrong status, duplicate criteria). `cplat spec check` already does these, and they do not change.
- Other documents with front matter outside spec folders, such as product plans in `docs/plan/`. They keep their current behaviour.
- Specs in other repos of a product. Each repo's commands read only that repo's specs.

## Open questions

- ~~Should a broken spec fail `cplat spec ci` even without `--strict`?~~ Answered: yes, it is always an error and exits 1, see AC-085.8.
- ~~Confirm: `cplat spec list` still exits 0 when a spec is broken.~~ Answered: yes, see AC-085.9.
- ~~Confirm: the index keeps a broken spec as a row with status `broken`.~~ Answered: yes, see AC-085.10.
- ~~Confirm the exact fix hint users see.~~ Answered: `values that contain ': ' must be quoted, e.g. title: "a: b"`, see AC-085.1 and AC-085.3.

## Changelog

- 2026-10-23 created
- 2026-10-23 amended: open questions answered (all recommended answers accepted); AC-085.1 now states the exact fix hint
- 2026-10-23 approved
