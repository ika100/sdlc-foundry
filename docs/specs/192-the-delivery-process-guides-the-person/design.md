# Design — 192 The delivery process guides the person from triage to release

## Decisions

- **`cplat next` prints every screen; the session adds only judgement text** (A5). Three modules: `nextstate` reads the
  sources (read-only), `nextscreen` renders the text, `nextquestions` builds the choices. `nextcmd` puts them together.
  The decision outlives this spec (spec 193 builds its build screens on it). ADR: created in t10 with
  `cplat adr add delivery-screens-are-printed-by-cplat --decision "Delivery screens and their choices are printed by cplat; the session adds only judgement text and follows the procedure the screen carries"`.
- **The procedure travels with the screen.** `cplat next --json` carries `how`, one fixed paragraph that says how to
  print the screen, ask the questions and run a chosen option. `/platform:next` and the hand-over at the end of
  triage, spec approval, build, ship and release say only "run `cplat next --json` and follow its `how`" (AC-192.8).
  So eight prompts grow by one sentence each, not by a copy of the procedure, and the procedure is tested code.
- **Read-only by construction** (AC-192.1): `nextstate` calls only reading functions (`needs.collect` /
  `needs.collect_repo`, `runlist.collect`, `dispatch_view.status_doc`, `dispatch_state.load`, `notify.load_state`,
  `notify_config.load`, `spec.find`/`scan`, `git log`/`git describe`). It never calls `runs.start`, a `record_*`, a
  `dispatch_state.update`, `notify.save_state` or `gh` with a writing verb. `--later` comes back from the session (A8);
  nothing is stored.
- **Answers are recorded by a separate verb** `cplat next answer`, which the option's `record` argv runs after the
  person chose. It writes run-store **follow-up lines** (`"followup": "person"`), not run records: follow-ups are
  ignored by `runlist` (`cplat runs`, `needs` escalations, the notifier), so an answer can never look like a finished
  run (A9, AC-192.10).
- **Draft details come from the parse `needs` already did**: `needs._drafts` keeps each parsed `Spec` in a module
  cache read through `needs.draft_spec(slug, spec_id)`; the needs document itself is unchanged.
- **`Release` is a bar step, not a ninth stage**: `stages.STAGES` keeps its eight entries (the Board, `earliest` and
  every caller stay as they are); `stages.explain("Release")` and the three plain terms live in `stages.py`, and the
  console glossary takes its texts from there, so terminal and console show one text (AC-192.2, A2).
- **Group order** (AC-192.3, A4): 1 `escalation`, `stuck`, `budget`; 2 `answer`, `approve`; 3 `triage`; 4 `release`,
  `promote`, `review`. `review` (an engine fix waiting to merge) is not named in the criterion; it goes with group 4
  because, like a promotion, it lets finished work go out.
- **The approve question's "Show assumptions" is also its details option** (AC-192.5 fixes four choices, AC-192.6 caps
  a question at four): its screen lists the assumptions and every outward action with its target and undo. Every other
  question that acts outward has an option labelled `Show details`.
- **One draft to approve**: the question is "Approve (recommended)", "Show assumptions", "Later"; "Approve all 1" and
  "Approve only one" would say nothing for one spec.
- **Ids follow the description** (AC-192.9) even where the spec's example screen puts the number first; the example
  is an illustration.
- **Component repos read their own items** (`needs.collect_repo`); promotions come from the system and show only in a
  gitops-app repo, where `needs.collect` reads them (A3).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/stages.py` | `bar(shape)`, `bar_step(stage, shape)`, `explain("Release")`, `PLAIN` terms | changed |
| `scripts/cplat/console/glossary.py` | terms `release`, `runs_on_its_own`, `two_at_a_time`, `needs_you` from `stages`; Release on How it works | changed |
| `scripts/cplat/needs.py` | `draft_spec(slug, spec_id)`: the cached parse of a draft | changed |
| `scripts/cplat/nextstate.py` | `collect(repo_dir) -> state`: every source, read-only; `plain(text)`; item descriptions | new |
| `scripts/cplat/nextscreen.py` | `render(state, opts) -> (lines, parts)`: bar, what is happening, Your part; ASCII; width | new |
| `scripts/cplat/nextquestions.py` | `build(state, opts) -> (questions, page)`: groups, options, actions, undo, record argv | new |
| `scripts/cplat/nextcmd.py` | `cplat next` and `cplat next answer`; the `how` text | new |
| `scripts/cplat/runs.py` | `person_answer(...)`: one follow-up line per item | changed |
| `scripts/cplat/runs_report.py` | `aggregate_person`; the "Person time" lines and `person` JSON key | changed |
| `scripts/cplat/cplat.py` | plumbing `next` → `nextcmd` | changed |
| `plugins/platform/commands/next.md` | `/platform:next` | new |
| eight command prompts | the hand-over sentence (AC-192.8) | changed |

## Contract

### CLI

```
cplat next [--json] [--ascii] [--repo-dir DIR] [--later ITEM]... [--judgement FILE]
           [--page N] [--show assumptions | --show details:<QID>] [--choose approve]
cplat next answer --shown-at ISO --option ID [--item REF]...
```

- `cplat next` exits 0 in every repo state (a failing source is shown, not raised); a usage error exits 2. Text mode
  prints `screen` only; `--json` prints the document below.
- `--later ITEM` (repeatable, a needs item `id`): the item is left out of every group and question and counted.
- `--judgement FILE`: JSON `{"specs": {"<spec id or number>": {"you_get": str, "assumption": str}}}`; unknown keys and
  specs are ignored, an unreadable file is ignored with a line `Could not read the judgement file.` in part 2.
- `--page N` (1-based): the page of questions; a page past the last shows the last.
- `--show assumptions`: the approve sub-screen; `--show details:<QID>`: the details sub-screen of question `QID`;
  `--choose approve`: the "Approve only one" sub-screen. Sub-screens keep the three parts.
- ASCII mode: `--ascii`, or the first set of `LC_ALL`, `LC_CTYPE`, `LANG` does not contain `UTF-8` or `utf8`
  (case-insensitive), or none is set.
- `CPLAT_HEADLESS=1` (an unattended run): `attended: false`, `questions: []`; the screen is the same.
- `cplat next answer`: minutes = `min(10, max(0, (now − shown_at) / 60))`, divided evenly over the `--item`s; one
  follow-up line per item; prints `recorded: <n> item(s), <m> min` (m with one decimal) or the store's warning line
  (`runs` buffering); exit 0; a bad `--shown-at` exits 2. No `--item` records nothing and prints `recorded: 0 item(s), 0.0 min`.

### `cplat next --json` (schema 1)

```json
{
  "schema": 1, "repo": "owner/name", "shape": "platform", "attended": true,
  "shown_at": "2026-11-14T10:00:00Z",
  "bar": {"steps": [{"n": 1, "name": "Issue", "what": "<stages.explain text>", "state": "done"},
                    {"n": 2, "name": "Spec", "what": "...", "state": "here"},
                    {"n": 3, "name": "Build", "what": "...", "state": "todo"},
                    {"n": 4, "name": "Release", "what": "...", "state": "todo"}],
          "label": "you are here"},
  "screen": "<the whole text, lines joined by \\n, no trailing newline>",
  "waiting": {"group": "specs", "items": ["approve:o/n:189-x"], "also": {"triage": 3}, "later": 1},
  "running": [{"what": "A web image without the finding (spec 189)", "step": "testing", "bar_step": "Build"}],
  "drafts": [{"id": "approve:o/n:189-x", "spec": "189-x", "title": "...", "problem": "<≤600 chars>",
              "assumptions": ["..."], "pr": 690}],
  "judgement_wanted": true,
  "questions": [<question>],
  "page": {"n": 1, "of": 2, "text": "page 1 of 2"},
  "unavailable": [{"source": "github", "error": "...", "kinds": ["approve", "answer"]}],
  "how": "<the procedure paragraph>"
}
```

- `bar.steps[].state`: `here` for the step of the first item of the shown group, else `running` for the earliest step
  of running work, else none of the two; `done` for every step before that step; `todo` for the rest. `label`:
  `you are here` (a `here` step), `running on its own` (a `running` step), else `null`.
- `waiting.group`: `stopped` | `specs` | `issues` | `release` | `null`; `items`: the shown group, oldest `since` first;
  `also`: count per needs kind of every other waiting item not put off; `later`: how many `--later` items exist.
- `drafts`: every `answer`/`approve` item shown; `judgement_wanted`: drafts exist and no `--judgement` was given.
- `page.text` is `""` when `of` is 1.

`<question>`:

```json
{"id": "approve", "header": "Approve", "question": "Approve the 2 written specs?",
 "options": [{"id": "approve-all", "label": "Approve all 2", "recommended": true,
              "description": "Cannot be undone: the merge of PR #690 into main (a revert pull request takes it back). Runs /component:spec approve 189, /component:spec approve 190",
              "steps": ["/component:spec approve 189", "/component:spec approve 190"], "then": null,
              "actions": [{"what": "approval commit", "target": "docs/specs/189-x/ on feature/189-x",
                           "undo": "cplat spec set-status 189-x draft --reason \"undo approval\""},
                          {"what": "merge", "target": "PR #690 into main", "undo": null}],
              "cannot_undo": ["the merge of PR #690 into main (a revert pull request takes it back)"],
              "undo": ["Undo: cplat spec set-status 189-x draft --reason \"undo approval\""],
              "record": ["cplat", "next", "answer", "--shown-at", "2026-11-14T10:00:00Z", "--option", "approve-all",
                         "--item", "spec:o/n:189-x", "--item", "spec:o/n:190-y"]}]}
```

- At most 4 questions per page and 4 options per question; exactly one option has `recommended: true` and it is the
  first. `header` ≤ 12 characters. `label` never carries "(recommended)"; the prompt adds the marker.
- `description`: `Cannot be undone: <cannot_undo joined by "; ">.` first when `cannot_undo` is not empty, then
  `Runs <steps joined by ", ">` (the command only as a secondary detail, AC-192.8), or the sub-screen it opens.
- Exactly one of `steps` (non-empty list) and `then` (argv of a `cplat next` call) is set, or neither for an option
  that does nothing (Wait for tomorrow). `then` always repeats the call's `--later`, `--ascii` and `--judgement`
  arguments; "Later" adds `--later <id>` for each item of the question.
- `record`: the full argv of `cplat next answer` for this option; `--item` refs are `spec:<repo>:<spec id>` and
  `issue:<repo>:<number>` for the specs and issues the question concerns (none for budget, release, promote, review,
  try again).
- `undo`: one `Undo: <text>` line per action whose `undo` is not null, in action order.

### Questions per group

| Group / kind | Question (one per…) | Options in order |
|---|---|---|
| `escalation`, `stuck` | per item | "Try again" (steps `[item.command]`), "Show details" (when actions), "Later" |
| `budget` | per item | "Wait for tomorrow" (nothing), "Later" |
| `answer` | per open question of each draft, drafts oldest first | the suggested answer, the first alternative (if any), "Show details", "Later"; steps `["<item.command with <answers> → answers to open questions: <question>: <option>>"]` |
| `approve` (n ≥ 2) | one, after the `answer` questions | "Approve all <n>", "Show assumptions", "Approve only one", "Later" |
| `approve` (n = 1) | one | "Approve", "Show assumptions", "Later" |
| `--choose approve` | one | up to 2 specs (`<title> (spec N)`, oldest first), "Show details", "Next specs" (`--page`) or "Later" |
| `triage` | one for the group | "Triage them" (steps `["/issue:triage"]`; one issue: `[item.command]`), "Show details", "Later" |
| `release` | per item | "Release now" (steps `["/platform:release"]` or `["/component:release"]`), "Show details", "Later" |
| `promote`, `review` | per item | "Promote" / "Approve and merge" (steps `[item.command]`), "Show details", "Later" |
| a source unavailable | one, last on its page | "Try again" (`then`: the same call), "Not now" (nothing) |

Actions (`what`, `target`, `undo`):

| Kind | Actions |
|---|---|
| `approve` | per spec: `approval commit`, `docs/specs/<id>/ on feature/<id>`, `cplat spec set-status <id> draft --reason "undo approval"`; `merge`, `PR #<pr> into main` (no PR: `feature/<id> into main`), null |
| `answer` | `spec commit and push`, `PR #<pr>` / `feature/<id>`, `/<level>:spec --amend <N> <your new answer>` |
| `escalation` via `/<level>:ship N` | `push and pull request`, `<repo> feature/<spec>`, `gh pr close --delete-branch feature/<spec> -R <repo>`; `merge and deploy to dev`, `<repo> main`, null |
| `escalation` via `/component:fix #N` | `pull request`, `<repo>, a fix for #N`, `gh pr close <its number> -R <repo>` |
| `escalation`/`stuck` via `gh issue edit N --remove-label needs-decision` | `label removed`, `<repo>#N needs-decision`, `gh issue edit N -R <repo> --add-label needs-decision` |
| `stuck` via `cplat dispatch resume` | none (local) |
| `triage` | per issue: `labels and a comment`, `<repo>#N`, `/issue:triage N` again routes it differently |
| `release` | `release pull request and merge`, `<repo> main`, null; `tag`, `the next version`, null; `GitHub release`, `<repo>`, null |
| `promote` | `promotion pull request and merge`, `prod of <component>`, `item.way_back.command`; a `way_back.warning` is added to `cannot_undo` |
| `review` | `approve and merge`, `<repo> PR #<pr>`, null |

`cannot_undo` holds one text per action whose `undo` is null: `the merge of PR #690 into main (a revert pull request
takes it back)`, `the tag and the published release`, `the merge and the deploy to dev`.

### The screen

Three parts separated by one blank line; no line wider than 80 columns; long lines wrap at a space with the
continuation indented as their field.

1. **Bar**: `" " + " ── ".join("<num> <Name>[ <mark>]")`, then, when `label` is set, a line with the label starting
   at the column of the marked step (moved left so it ends by column 80). `<num>` is `①`…`⑥`, ASCII `1.`…`6.`;
   `<mark>` is `✓` / `●` (ASCII `[x]` / `[>]`); ASCII joins with ` -- `. Steps: `Issue, Spec, Build, Release` for
   `platform`, `library-python` and an unknown shape; `Issue, Spec, Build, Dev, Staging, Prod` for `service-python`,
   `service-java`, `service-go`, `web-nextjs`, `gitops-app`. `bar_step`: Issue→Issue, Spec→Spec,
   Plan/Build/Land→Build, Dev/Staging/Prod→themselves or Release, Release→Release.
2. **What is happening**, by case:
   - stopped group: `<n> run(s) stopped and wait for you.`, then per item `  ! <what>: <reason>` (ASCII `  [!] …`).
   - specs group: `<n> spec(s) are written and wait for your approval.` (and `<m> have questions for you.`), then per
     draft: `  <title> (spec N, from #682[, waiting 42 min])`, `    You get:   <you_get>` (only with judgement),
     `    I assumed: <assumption> (<k> assumptions in all)`, `    Size:      <small|medium|large>[, about <t> to build]`.
     The assumption is the judgement's text, else the first unstruck one with its `**A<n>**` marker and its
     ` (other option…)` tail removed, cut to 120 characters with `…`.
   - issues group: `<n> new issue(s) wait for triage.`, then `  <title> (#N)` per issue.
   - release group: `A release is ready: <n> change(s) since <tag>.` / `<component> <version> is verified in staging and can go to prod.` / `A fix waits for your review (PR #N).`
   - each listed item that was notified ends with `waiting <age>` (`42 min`, `1 h 5 min`, `2 days`).
   - then `Also waiting: <count> <kind words>, …` (group order; kind words: stopped run(s), stuck run(s), daily
     budget reached, spec(s) with questions, spec(s) to approve, new issue(s), release ready, release(s) to promote,
     fix(es) to review); then `<n> put off for later.`; then, while work runs, `Also running: <n> run(s).`
   - nothing waits, nothing runs: `Nothing is waiting for you.`, `<n> parked item(s).`, `New issues will show up here.`
   - runs and nothing waiting: `<n> run(s), <words> at a time.` (slots unknown: `<n> run(s).`), then `  <what>: <step>`.
   - a source unavailable: `Could not read <source name>; it may be missing <hint>.` per source; such a screen never
     says "Nothing is waiting". Names and hints: github → GitHub, a GitHub login (gh auth status) or the network;
     runs → the run records, the private run store (cplat platform doctor); dispatcher → the run queue, its state
     files; cluster → the cluster, a kube context; notifications → the notification settings, a valid notify.yaml.
   - lists show 5 entries and `  and <n> more`.
3. **Your part** (first line starts `Your part:`, continuation lines indented one space):
   stopped → `Your part: decide how the stopped run goes on.`; specs with questions → `Your part: answer <n> question(s), then approve.`;
   specs → `Your part: approve, or read first (PR #690, PR #691).`; issues → `Your part: triage the new issues.`;
   release → `Your part: release, or wait for more changes.`; promote → `Your part: promote to prod, or hold it back.`;
   review → `Your part: review the fix.`; only an unavailable source → `Your part: check what is missing, then try again.`;
   nothing → `Your part: nothing. You can walk away.`; runs → `Your part: nothing. You can walk away; a question reaches you <channels> and shows up here first.`,
   or `…; notifications are off, so look here again.` Channels are the cells of `notify_config.cells_for(cfg,
   "escalation", shape)` that are not `off`, in the order desktop (`on the desktop`), github (`on GitHub`), slack
   (`in Slack`), email (`by e-mail`), joined with `, ` and a last ` and `.
- Size: active criteria 1–4 small, 5–8 medium, 9+ large (0 counts as small). Time: the median of at least 3 comparable
  runs — this repo's done run rows of kind `ship` or `product-ship`, the latest per spec, whose local spec has the same
  size; minutes from `budget.used.minutes`, else `ended_at − started_at`; rounded to 5 (at least 5): `about 45 min`,
  `about 1 h`, `about 1 h 35 min`.
- Running entries: dispatch units and active run rows, one per spec or issue; `what` is the local spec title with
  `(spec N)` or `a fix for #N`; `step` maps the phase: plan→planning, build→building, red-tests/tests→testing,
  review/verify→review, pr/land/landing→landing, deploy→deploying, staging→in staging, else the phase.
- Slot words: one … ten, else the number.
- `plain(text)` runs over every screen line and question text: whole words, case-insensitive, `dispatcher(s)` → run
  queue, `escalat\w*` → stopped (escalate/escalation → stop), `slot(s)` → place(s), `unit(s)` → run(s), `claim\w*` →
  lock, `held` → waiting. JSON keys and ids keep their names.

### Person records (AC-192.10)

One run-store follow-up line per item:
`{"schema": 1, "followup": "person", "signature": "person", "run_id": "person-<12 hex>", "at": <answered ISO>,
"shown_at": <ISO>, "repo": "<slug>", "spec": "<spec id>" | null, "issue": <number> | null, "option": "<id>",
"questions": 1, "minutes": <float, 2 decimals>}`.

`cplat platform runs report` adds `person` to its JSON and a block to its text:

```json
"person": {"items": [{"kind": "spec", "repo": "o/n", "id": "189-x", "questions": 3, "minutes": 7.5},
                     {"kind": "issue", "repo": "o/n", "id": "676", "questions": null, "minutes": null}],
           "questions": 3, "minutes": 7.5}
```

```
Person time per delivered item:
  spec 189-x  questions 3  person 7.5 min
  issue o/n#676  questions –  person –
```

Delivered: a kept record with outcome `done`, kind `ship`, `product-ship`, `fix` or `dispatch`, and a `spec` or an
`issue.number`; one row per (repo, spec) or (repo, issue). Person lines are matched on the same key over the whole
store, not only the window. `Person time per delivered item: none` without delivered items. Person lines never
count as runs anywhere in the report.

### The `how` text (fixed in `nextcmd.HOW`)

Print `screen` verbatim. Then ask `questions` with AskUserQuestion: each question's `header` and `question`, its
`options` in order with `label` and `description`, the first marked "(Recommended)". After the person chose: run the
option's `record`; with `then`, run that call and follow its `how`; otherwise run its `steps` in order (a slash
command: follow that command; a `cplat` call: run it), print its `undo` lines verbatim, and run `cplat next --json`
again with the same `--later` arguments. Nothing in `steps` runs before the person chose. Without questions, stop.
