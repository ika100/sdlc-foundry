# Design — 086 Repo gates survive skeleton updates

## Decisions

- **Every skeleton file a repo extends gets a repo-owned companion; the skeleton file itself stays platform-owned and
  is overwritten.** We do not merge edits into skeleton files (non-goal). Each companion lives where the update cannot
  reach it, and the update reports every customisation it overwrote. The companions are the `ci-extra` recipe (gates), the repo's own
  recipes in `devbox.json` (spec 060), the repo's own permission entries in `.claude/settings.json`, workflow files of
  the repo's own (extra CI jobs), and `.claude/project-notes.md` (project guidance). This decision outlives the
  feature: [ADR-031](../../adr/031-repo-owned-companions-for-skeleton-files.md).
- **`ci-extra` is a repo-only recipe that the template's `ci` and CI workflow call when it exists.** It is never
  defined by a template, so spec 060's merge keeps it like any repo-only recipe (AC-086.4). Existence is tested with
  `grep` on `devbox.json`. Every shape already has `grep`; `jq` is not in every shape's packages, and `devbox run <unknown>` cannot be
  told apart from a failing recipe.
- **The update tells repo customisations from template changes with a baseline render.** It renders the template as
  it was at the repo's previous platform version (`git archive v<old> templates/<t>` from the platform checkout, then
  `copier copy` with the repo's pre-update answers into a temp dir). A file, recipe or setting is a *repo
  customisation* only when the repo's pre-update value differs from that baseline. Without this, every update that
  brings template changes would report losses, and the fleet update (spec 096) would never merge (AC-086.13). When
  the baseline cannot be rendered (no stamp, tag not in the checkout, copier error), the update falls back to treating
  every difference as a customisation (today's behaviour). This is conservative: the `lost` list can be non-empty when
  nothing was lost, but it is never empty when something was.
- **Gates moved into `ci-extra` are the repo's own gates.** A gate the old `ci` ran is moved (AC-086.6) when the new
  template `ci` does not run it **and** the baseline template `ci` did not run it either. A gate the platform removed
  from `ci` is a template change, not a repo gate, and moving it would bring it back. When there is no baseline, every
  gate that is missing from the new `ci` is moved. Gates are compared by their real name (`gates._real`, so
  `quality` = `validate` in gitops-app).
- **A permission entry the platform removed is not a loss.** AC-086.11 removes entries the baseline template had and the
  new one does not. The repo did not add them, so they are listed under `settings.removed_by_platform` and never in
  `lost` (AC-086.13: "empty exactly when nothing the repo had added was lost"). Repo-added entries are never
  removed (AC-086.10), so the `permission` kind never appears in `lost`. The entry is removed only when the baseline is
  known. Without a baseline every entry the new template lacks is kept.
- **`ci-extra` is a required check** (`shapes.yml` `ci_checks`, spec 054). It always runs and is green when the recipe
  is absent (AC-086.3), so requiring it costs nothing and makes a repo gate as binding as a template gate.
- **The notes file is `.claude/project-notes.md`**, imported from `CLAUDE.md` with `@.claude/project-notes.md`.
  Claude Code loads imports in every session, including `claude -p` and headless ones, and skips an import whose file
  is missing without an error (AC-086.16). It sits next to the settings file the platform already owns, and the CI
  workflows' `paths-ignore` (`.claude/**`) means editing it starts no CI run. It is listed in `_skip_if_exists`, so an update never
  writes it, and `drop_new_project_owned_files` leaves it out of a repo that lacks it.
- **`cplat shape check`** becomes a subcommand of `cplat shape` that runs `scripts/shapes.py check`, so AC-086.5's
  command exists as written. The contract checks live in `shapes.py`, which CI already runs.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/gates.py` | `CI_EXTRA`, `CI_EXTRA_STEP`, `chain()`. The doctor check `gate ci = CI workflow` knows `ci-extra` (AC-086.7–9) | changed |
| `scripts/cplat/settingsmerge.py` | merge `.claude/settings.json`: keep repo permission entries, drop platform-removed ones, report replaced keys (AC-086.10–12) | new |
| `scripts/cplat/update.py` | baseline render, baseline-aware devbox merge, gate move into `ci-extra`, settings merge, the `lost` list and the per-file hints (AC-086.4, .6, .10–.14) | changed |
| `scripts/cplat/shapecmd.py` | `cplat shape check` → `shapes.main(["check"])` (AC-086.5) | changed |
| `scripts/shapes.py` | contract: no template `ci-extra`, `ci` ends with `CI_EXTRA_STEP`, a `ci-extra` job, the notes file and the CLAUDE.md section (AC-086.5, .15, .16) | changed |
| `templates/*/devbox.json[.jinja]` | `ci` ends with the `ci-extra` step (AC-086.1, .2) | changed |
| `templates/*/.github/workflows/ci.yml` | `ci-extra` job (AC-086.3) | changed |
| `templates/*/CLAUDE.md[.jinja]`, `templates/*/.claude/project-notes.md`, `templates/*/copier.yml` | "Where your additions go" section, notes import, notes file seeded empty and project-owned (AC-086.15, .16) | changed / new |
| `shapes.yml` | `ci-extra` in every shape's `ci_checks` | changed |

## Contract

### `ci` recipe (every template, AC-086.1, .2, .5)

```
CI_EXTRA_STEP = if grep -qs '"ci-extra"[[:space:]]*:' devbox.json; then devbox run ci-extra; fi
ci            = <the template's gates, unchanged, joined by " && "> && CI_EXTRA_STEP
```

This is the decoded command. In the JSON file the inner quotes are escaped (`\"ci-extra\"`), so the `ci` line
never matches its own pattern. Per shape: `devbox run quality && devbox run test && devbox run security && <step>`
(python, go, java), `devbox run install && devbox run quality && devbox run test && devbox run security && <step>`
(web-nextjs), and `devbox run validate && devbox run security && <step>` (gitops-app). A failing template gate
stops the `&&` chain before `ci-extra`. When the recipe is absent the `if` exits 0. When it is present the
`ci` exit status is `ci-extra`'s. `gates.CI_EXTRA_STEP` and `shapes.CI_EXTRA_STEP` hold this exact decoded string,
and a test asserts that they are equal. No template defines a `"ci-extra"` key.

### `ci-extra` CI job (every template's `.github/workflows/ci.yml`, AC-086.3, .5)

Job id `ci-extra`, `name: ci-extra` (exactly: it is the check name and a `ci_checks` entry). It is placed directly after the
last gate job (`security`), so the `devbox run` steps in job order still equal the `ci` chain (AC-075.1 test). It has no `needs`
and no `if`, and runs on every event the workflow runs on.

```yaml
  ci-extra:
    name: ci-extra
    runs-on: ${{ vars.CI_RUNNER || 'ubuntu-latest' }}
    steps:
      - uses: actions/checkout@<same pin as the other jobs>     # gitops-app: with: {ref: ${{ inputs.ref }}}
      - name: Is a ci-extra recipe defined?
        id: recipe
        run: |
          if grep -qs '"ci-extra"[[:space:]]*:' devbox.json; then
            echo "defined=true" >> "$GITHUB_OUTPUT"
          else
            echo "defined=false" >> "$GITHUB_OUTPUT"
            echo "::notice::no ci-extra recipe is defined in devbox.json: nothing to run (spec 086)"
          fi
      - uses: jetify-com/devbox-install-action@<same pin>
        if: steps.recipe.outputs.defined == 'true' && runner.environment == 'github-hosted'
        with: {enable-cache: true}
      - run: devbox run install                                 # web-nextjs only, same guard as the next step
        if: steps.recipe.outputs.defined == 'true'
      - run: devbox run ci-extra
        if: steps.recipe.outputs.defined == 'true'
```

In `service-python` and `library-python` (`_templates_suffix: ""`, every file is rendered) each `${{ … }}` is written
`${{ '{{' }} … {{ '}}' }}` as in the existing jobs. `if:` conditions contain no braces and need no escaping. The other
templates do not render `ci.yml` and use plain `${{ … }}`.

### `cplat doctor`: check `gate ci = CI workflow` (AC-086.7–9)

`gates.chain(cmd) -> list[str]` returns the `devbox run <name>` steps of a recipe in order. `ci-extra` is never
collapsed by `_real`. Other names are collapsed as today.

| Situation | status | detail | fix |
|---|---|---|---|
| repo defines `ci-extra` and `workflow_gates` has no `ci-extra` | warn | `CI does not run ci-extra: no job of .github/workflows/ci.yml runs devbox run ci-extra` | `/shared:update-service` |
| chain of `ci` equals the workflow gates | ok | `quality → test → security → ci-extra (chart-lint)`: `ci-extra` is followed by its own `chain()` joined by ` → `; it shows the raw command when that chain is empty, or `(not defined)` when the recipe is absent | — |
| `ci` runs gates `G` the workflow does not run | warn | as today: `` `devbox run ci` runs …, the workflow runs … `` | `move <G> into ci-extra: "ci-extra": "<existing ci-extra && >devbox run <g1> && devbox run <g2>" (updates replace the ci recipe; CI runs ci-extra)` |
| other mismatch | warn | as today | as today |

A repo on an older platform that has no `ci-extra` anywhere is unchanged (ok when the chains match).

### `.claude/settings.json` merge (`settingsmerge.py`, AC-086.10–12)

```python
LISTS = ("allow", "ask", "deny")
def merge_settings(project: dict, template: dict, baseline: dict | None) -> tuple[dict, dict]:
    """-> (merged, {"kept": [{"list", "entry"}], "removed_by_platform": [{"list", "entry"}], "replaced": [{"key", "was"}]})"""
def merge_settings_file(repo: Path, before: str | None, baseline: dict | None) -> tuple[dict, str | None]:
    """Reads the rendered file, writes the merge (only when something is kept), returns (report, note)."""
```

- For each list in `permissions.{allow,ask,deny}`, an entry of the project that is not in the template's list:
  - is in the baseline's same list → removed, `removed_by_platform` (only when `baseline` is not None);
  - otherwise → appended after the template's entries, in project order, and listed in `kept`.
- `replaced`: every key `k` of the project at the top level (except `permissions`) and every `permissions.<k>` except
  the three lists, whose project value differs from the template's value **and** from the baseline's value. With
  `baseline=None` the second condition is dropped. A baseline value containing `{{` counts as equal. `was` is the
  project's value as compact JSON.
- The merged text keeps the template file byte-for-byte and inserts kept entries before each list's closing `]`, the same
  technique as `update._insert_kept`/`_close`. When that cannot be done safely it falls back to
  `json.dumps(indent=2)`. Invalid project JSON: the template's file stays and the note says
  `.claude/settings.json was not valid JSON: replaced by the template's file; re-add your permission entries from git show HEAD~1:.claude/settings.json`.

### `cplat update-service` (AC-086.4, .6, .12–.14)

New functions in `update.py` (test seams: tests monkeypatch `update.render_baseline`):

```python
def render_baseline(template: str, old: str | None, answers: str, dest: Path) -> Path | None:
    """The template as rendered at platform `old` with the repo's pre-update answers, or None when it cannot be."""
def move_ci_gates(project: dict, template: dict, baseline: dict | None) -> tuple[list[str], list[str]]:
    """-> (moved, dropped): gates of the project's old `ci` the new template `ci` does not run (and the baseline `ci`
    did not run). `moved` when the project has no `ci-extra`, else `dropped`."""
def merge_devbox(project: dict, template: dict, baseline: dict | None = None) -> tuple[dict, list[str], list[tuple[str, str]]]:
    """Unchanged contract; with a baseline, `replaced` lists only entries whose project value differs from the baseline's."""
```

Order in `execute`: capture the pre-update `devbox.json`, `.claude/settings.json` and answers. Run copier. If anything changed,
render the baseline into a `tempfile.TemporaryDirectory`. Merge `devbox.json` with the baseline. Move the gates (a
new `"ci-extra": "devbox run g1 && devbox run g2"` is inserted like a kept recipe). Merge the settings. Compute
`lost`, then commit. A no-op update renders no baseline.

`scripts ci` is not reported as replaced when its chain, minus the moved gates, equals the baseline's `ci` chain (or
the new template's chain without the `ci-extra` step when there is no baseline). Anything else in the old `ci`, such as a
non-`devbox run` command, is a replaced recipe.

**Text report** (additions; the existing lines stay):

- did: `moved to ci-extra: chart-lint, helm-docs` (AC-086.6)
- did: `kept in .claude/settings.json: allow Bash(helm *); ask Bash(terraform apply *)` (AC-086.10)
- did: `removed by the platform from .claude/settings.json: allow Bash(kubectl rollout status *)` (AC-086.11)
- next: `dropped from ci (ci-extra exists and was left unchanged): chart-lint; add them with "ci-extra": "<current> && devbox run chart-lint"` (AC-086.6)
- next, one line per `lost` entry, replacing the old "review MODIFIED skeleton files" line:
  `replaced <file>[ <entry>]: the template's version wins; <where>` (AC-086.12), where `<where>` is:

| file | where |
|---|---|
| `devbox.json` (recipe, package, env) | `re-add it under a new recipe name; gates belong in the ci-extra recipe` |
| `devbox.json` (gate) | `add it to ci-extra: "ci-extra": "<current> && devbox run <gate>"` |
| `.github/workflows/ci.yml` | `gates belong in the ci-extra recipe, extra jobs in a workflow file of your own in .github/workflows/` |
| `.claude/settings.json` | `only your own permission entries (allow, ask, deny) are kept; other settings are the platform's` |
| `CLAUDE.md` | `project guidance belongs in .claude/project-notes.md (CLAUDE.md loads it; updates never change it)` |
| any other skeleton file | `it has no repo-owned companion: keep yours with git checkout HEAD~1 -- <file> and propose the change with /shared:report-issue` |

**`--json`** (additions to today's `changed`, `modified`, `new_answers`, `changelog`, `devbox`):

```json
{
  "baseline": "4.4.0",
  "devbox": {"kept": ["scripts chart-lint"], "replaced": [{"entry": "scripts test", "was": "..."}],
             "moved_to_ci_extra": ["chart-lint"], "dropped_gates": []},
  "settings": {"kept": [{"list": "allow", "entry": "Bash(helm *)"}],
               "removed_by_platform": [{"list": "allow", "entry": "Bash(old *)"}],
               "replaced": [{"key": "hooks", "was": "{...}"}]},
  "lost": [
    {"kind": "recipe",  "file": "devbox.json",              "entry": "scripts test", "was": "go test ./... -v", "where": "..."},
    {"kind": "gate",    "file": "devbox.json",              "entry": "chart-lint",   "was": null,               "where": "..."},
    {"kind": "setting", "file": ".claude/settings.json",    "entry": "hooks",        "was": "{...}",            "where": "..."},
    {"kind": "file",    "file": ".github/workflows/ci.yml", "entry": null,           "was": null,               "where": "..."}
  ]
}
```

- `baseline`: the platform version whose render was used, or `null` (then every difference counts as a customisation).
- `lost` lists exactly: `devbox.replaced` (kind `recipe`, including packages and env), `devbox.dropped_gates` (kind
  `gate`), `settings.replaced` (kind `setting`), and every **customised skeleton file** (kind `file`). A customised skeleton file is a
  path in `modified` other than `devbox.json`, `.claude/settings.json`, `.copier-answers.yml` and `.platform-version`
  whose pre-update content (`git show HEAD:<path>` before the commit) differs from the baseline's rendered file, or
  is missing from it. With no baseline every such path counts.
- `lost == []` exactly when nothing the repo had added was overwritten (AC-086.13). The no-op update (nothing changed)
  emits no data keys, as today.
- Workflow files the template does not ship are never written by copier, so they are not in `modified` or `lost` (AC-086.14).

### `cplat shape check` (AC-086.5, .15, .16)

`cplat shape check` exits with `scripts/shapes.py check`'s status and output. New `check_contract` errors, one per
template (`{sid}: …`):

- `devbox.json defines ci-extra; it is the repo's own recipe (spec 086)` when the template's devbox text has a `"ci-extra":` key.
- `` the ci recipe must end with ` && <CI_EXTRA_STEP>` (spec 086) `` when the decoded `ci` recipe does not end with it.
- `ci.yml has no ci-extra job running devbox run ci-extra (spec 086)` when `ci.yml` has no job with `name: ci-extra` whose
  steps include `run: devbox run ci-extra`.
- `template has no .claude/project-notes.md, or it is not empty (spec 086)`;
  `copier.yml must list .claude/project-notes.md in _skip_if_exists (spec 086)`;
  `CLAUDE.md must import @.claude/project-notes.md and have a '## Where your additions go' section (spec 086)`.

### `CLAUDE.md` (every template, AC-086.15, .16)

A section `## Where your additions go`, placed before `## Conventions` (or at the end), with this content as a table or list:

| Updates overwrite | Your additions go in |
|---|---|
| the template's recipes in `devbox.json` (including `ci`) | gates: the `ci-extra` recipe (`devbox run ci` and the `ci-extra` CI check run it); other tools: recipes of your own in `devbox.json` (kept) |
| `.github/workflows/ci.yml` | a workflow file of your own in `.github/workflows/` |
| `.claude/settings.json` | your own permission entries (allow, ask, deny) in it; they are kept |
| `CLAUDE.md` | `.claude/project-notes.md` |
| other skeleton files (Dockerfile, lint config …) | nowhere: propose the change to the platform (`/shared:report-issue`) |

The file ends with `## Project notes`, one sentence, and the import on its own line: `@.claude/project-notes.md`.
The `ci` row of each recipe table says it ends with `ci-extra` when the repo defines it.

## Risks

- **No tags in the platform checkout** (shallow CI clones, some plugin caches): no baseline, so the `lost` list is
  conservative and the fleet update holds a repo back that lost nothing. The report says `baseline: null` so the cause
  is visible. Tests monkeypatch `update.render_baseline`.
- **Old templates that copier ≥ the current version cannot render**: same fallback. Only a render error is caught; the
  update itself never fails because of the baseline.
- **Extra update time**: one more copier render, only when something changed.
- **`grep` false positive**: a `"ci-extra":` key elsewhere in `devbox.json` (e.g. `env`) is treated as the recipe.
  `devbox run ci-extra` then fails loudly, which is visible and not silent.
