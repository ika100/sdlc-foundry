---
spec_id: 222-the-ux-step-is-measured-on-website-plans
title: The UX step is measured on website plans
status: approved
priority: P1
shape: platform
tracks: [1059, 1060]
---

# 222 — The UX step is measured on website plans

## Problem

Spec 219 added the UX design step: `/component:plan` runs `web:ux-designer` for a website spec that changes what a user sees, and `cplat spec ux` decides that from a fixed word list. Two things are unmeasured (#1059, #1060):

- Every benchmark runs on the Python sample `todo-api`, so no measured run has seen the ux-designer: its tokens, time and the quality of its `ux.md` are unknown, and a change to the web prompts ships without a benchmark that runs them.
- The word list was a first guess. Checked against the 29 website specs of the journey and demo repos, it selects all of them, but at the level of single criteria it misses wording such as "edit mode", "input", "keyboard focus" or "presses Enter", and it fires on words that mean something else in a website repo: "container image", "the JSON fields", "page size".

## Stories

- As a platform maintainer, I want a benchmark that plans a small website spec through `/component:plan`, so that a change to the web prompts or the UX step is measured like a change to the other prompts.
- As a platform maintainer, I want the eval gate to ask for that benchmark only when the web prompts or the UX step changed, so that every other release and rebaseline costs what it costs today.
- As a website developer, I want the UX step selected for the specs that change what a user sees and skipped for the ones that only change routes, images or configuration, so that I neither miss the design nor pay for one I do not need.

## Acceptance criteria

- **AC-222.1** Given `scripts/cplat/benchmark/tasks.json`, when it is read, then it has a workflow `ux-plan` with the single step `/component:plan 902` and the spec file `spec-902.md`, a spec of shape `web-nextjs` whose criteria change a screen, and the workflow's sample is the `bench-files-web` component of the `system-ship` sample at that sample's pinned revision (one pin, no second sample repo).
- **AC-222.2** Given `cplat platform runs benchmark ux-plan`, when it prepares the sample, then it uses the clone `bench-files-web` in the system-ship folder (`--dir`, else `$CPLAT_BENCH_SYSTEM_DIR`, else `<state dir>/benchmark/system-ship`), whose Claude Code trust that benchmark already needs, and refuses with the folder and the command to fix it when that clone is missing or not trusted.
- **AC-222.3** Given a `ux-plan` run whose plan step finished, when its result is checked, then it is `done` only when the clone's `feature/<spec_id>` branch holds `docs/specs/<spec_id>/ux.md`, `cplat spec ux` answers `done` for it, the spec has no `cplat spec check` error, and `design.md` or `plan.md` names `ux.md`; otherwise the record is `failed` with the first missing item as its result check.
- **AC-222.4** Given a `ux-plan` run, when it ends, then its record is a `benchmark` record like the other workflows' (usage, phases, per-agent children with tokens and time) and the sample is put back to its pinned revision.
- **AC-222.5** Given the spec of the `build` benchmark on its `service-python` sample, when `cplat spec ux` decides it, then the answer is `none`: the existing Python benchmarks never run the ux-designer.
- **AC-222.6** Given `cplat platform eval-gate` (and `cplat platform release`, which runs it) without `--workflow`, when no changed file is under `plugins/web/` and `scripts/cplat/spec_ux.py` did not change, then it selects exactly `quick-task` and `build`, as before this spec.
- **AC-222.7** Given the same gate, when a changed prompt is under `plugins/web/` or `scripts/cplat/spec_ux.py` changed, then it also requires a `ux-plan` benchmark with this `plugins/` tree (same rules: outcome `done`, at most 1.5× the tokens of the base version's median); a change to `spec_ux.py` alone requires only `ux-plan`. `--workflow` accepts `ux-plan`, and `cplat platform rules rebaseline` still asks for `quick-task` and `build` only.
- **AC-222.8** Given a criterion or story of a website spec, when `cplat spec ux` looks for something a user sees, then it also recognises inputs, rows, labels, headings, headers and footers, keyboard focus, edit mode, empty and loading states, screen readers and accessible names, colours and themes, "appears", and a person typing, pressing, entering, selecting or submitting.
- **AC-222.9** Given a criterion that names a container, Docker or base image (or an image tag, digest or scan), fields of a JSON, request, response, body or query, a page size, page number or `page` parameter, or what logs or metrics show, when `cplat spec ux` looks for something a user sees, then those words do not count; another visible word in the same criterion still does.
- **AC-222.10** Given the labelled cases in `tests/cplat/fixtures/ux_cases.json` (criteria taken from the journey and demo website specs, each with its source, plus written website-repo criteria that change no screen), when the rule decides each one alone, then every case gets its label; a spec with a `ux:` field keeps that answer whatever its criteria say.
- **AC-222.11** Given the benchmark README, when it is read, then it names the `ux-plan` workflow, when the gate asks for it, its sample and its result check; and `cplat spec ux --help` says that image, field, page, header and log wording of a server or build does not count as visible.

## Non-goals

- A change to the ux-designer prompt, unless the measured run shows a defect in it.
- The UX step for system specs, the web console, a second sample repo.
- Adding `ux-plan` to the default benchmarks, to `rules rebaseline` or to every release.
- A learned or model-based decision: the rule stays deterministic, with the `ux:` field as the override.

## Assumptions

- **A1** The sample is system-ship's `bench-files-web` clone and pin, not a new repo (other option: a new pinned web sample; affects AC-222.1, AC-222.2). Reason: that clone is already trusted and kept current, a new one would need a manual trust step and its own upkeep.
- **A2** The workflow runs only `/component:plan`, not a build (other option: plan + build like `build`; affects AC-222.1, AC-222.3). Reason: the UX step and its readers (architect) are in the plan; a Next.js build would add an hour of cost without measuring the step.
- **A3** The gate selects `ux-plan` for any changed prompt under `plugins/web/` and for `scripts/cplat/spec_ux.py` (other option: only `ux-designer.md`; affects AC-222.6, AC-222.7). Reason: the web coder and tester read `ux.md` too, and `spec_ux.py` decides whether the step runs.
- **A4** The tuned rule removes vetoed phrases before it looks for a visible word, instead of dropping the ambiguous words (other option: drop "image", "field", "page"; affects AC-222.8, AC-222.9). Reason: "page" and "field" are the most frequent words of the real UI criteria.
- **A5** Ground truth for the cases is a person's reading: a criterion is labelled `needed` when it describes something a user sees or does in the browser (other option: label whole specs only; affects AC-222.10).
- **A6** The rule is documented in `cplat spec ux --help` and its module, not in the spec-format reference (other option: a sentence in that prompt; affects AC-222.11). Reason: the prompts are 49 bytes under their size baseline, and a prompt change would ask every release for new benchmarks.

## Open questions

None.

## Changelog

- 2026-11-24 created
- 2026-11-24 amended: AC-222.11 documents the rule in the command's help (A6)
- 2026-11-24 approved
- 2026-11-24 draft: amend: AC-222.11 documents the rule in cplat spec ux's help, not in a prompt (prompt size headroom)
- 2026-11-24 approved
