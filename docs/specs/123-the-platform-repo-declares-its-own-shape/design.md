# Design — 123 The platform repo declares its own shape

## Decisions

- **`platform` is a registry entry without a template, declared only in the committed `.platform-settings.yml`.** It is never sniffed and never listed where repos are created, adopted, updated or rolled out. ADR: [docs/adr/056-the-platform-repo-declares-its-shape.md](../../adr/056-the-platform-repo-declares-its-shape.md).
- **Two registry views keep every existing caller safe without touching it.** `shapes.load()` keeps returning only the template shapes, so `/component:new`, `/system:new`, `cplat adopt`, the fleet, the model's type/lang pairs (`model.TYPE_LANGS`), `compose`, `newsvc`, `newapp`, `validate`, the test fixtures and the shape contract check see exactly what they see today (AC-123.9, AC-123.7). Only shape resolution, routing and `cplat spec` use the new `load_all()` / `get()`.
- **The declaration is read by one function, `settings.declared_shape(repo)`.** Every resolution goes through `shapecmd.resolve(repo)`, which applies it before `detect-shape.sh`. `detect-shape.sh` stays unchanged: component repos find their shape exactly as before (AC-123.2, the third story).
- **A bad declaration is its own error type, `settings.ShapeDeclarationError(PlatformError)`.** Callers that treat "no shape" as normal (`spec.repo_shape`, `runs_agents.identity`) still swallow "cannot determine the repo's shape" but let this one through, so every command that needs the shape fails on it (AC-123.3 to AC-123.6). `cplat platform doctor` reports it as a FAIL row instead of crashing.
- **Specs without a `shape:` line in the platform repo keep the shape-less rules** (AC-123.16): a spec's effective shape is its own `shape:`, else the repo's shape unless that shape is declared. Only new specs record `shape: platform` and get the `(smoke)` rule (AC-123.15, AC-123.17).
- **Deploy for `platform` is one early return,** before the kube context lookup, the pin wait, Argo, smoke and staging (AC-123.21). The library path stays as it is.
- **The release refusal is data, not a shape name in the command.** The platform routing has no `release` role. `/component:release` refuses when `agents` has no `release` (AC-123.23).
- **The acceptance tests live in one new file,** `tests/cplat/test_platform_shape_123.py`. They follow the style of the existing `tests/cplat` suite: subprocess `cplat` calls in a temporary git repo with `XDG_CONFIG_HOME` pointed at a temporary directory, and `shapes.py` checks against a copied `shapes.yml`, as `tests/cplat/test_spec_driven.py` does.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `shapes.yml` | the `platform` entry | changed |
| `scripts/shapes.py` | `load()` (template shapes), `load_all()`, `get()`, `is_declared()`, `declared_ids()`; validation of declared entries; `check_files`, `check_contract` and `check_prd` skip them | changed |
| `site/scripts/generate-reference.mjs` | the shapes table lists template shapes only | changed |
| `scripts/cplat/settings.py` | `ShapeDeclarationError`, `declared_shape(repo)` | changed |
| `scripts/cplat/shapecmd.py` | `resolve(repo)`, platform routing | changed |
| `scripts/cplat/spec.py` | `repo_shape` lets declaration errors through; `known` from `load_all()`; `spec_shape()` used by `check`, `ci_problems`, `trace` | changed |
| `scripts/cplat/ship.py` | `start` resolves the shape first and records it; `deploy` returns early for `platform`; issue drafts fall back to the run's shape | changed |
| `scripts/cplat/update.py` | refuses the platform repo | changed |
| `scripts/cplat/doctor.py` | `repo shape` and `repo platform version` rows for `platform`; a FAIL row for a bad declaration | changed |
| `scripts/cplat/fleet.py` | an `--only` row that explains why the platform repo is skipped | changed |
| `plugins/component/commands/{spec,plan,verify,build,ship,release}.md` | declaration errors stop the command; ship's final report for non-deployable runs; release refuses without a release role | changed |
| `.platform-settings.yml` | `shape: platform` for this repo | new |

## Contract

### Registry entry (`shapes.yml`)

Appended after `service-go`:

```yaml
  - id: platform
    plugin: svc
    template: null          # no template: the platform repo is never created, adopted, updated or rolled out from one (ADR-056)
    deployable: false
    library: false
    detection:
      declared: .platform-settings.yml   # only `shape: platform` in the committed settings file; never sniffed
    status: stable
    adr: [55]
```

It has no `test_globs`, `smoke_tag`, `smoke_globs`, `ci_checks`, `validation`, `default_stack` or `runtime`. Leaving out `default_stack` means `model._pair` never makes a type/lang pair from it. Leaving out `validation` and `test_globs` means `cplat validate` and `cplat spec trace` behave exactly as they do in a repo without a shape.

### Registry API (`scripts/shapes.py`)

```python
DECLARED_IN = ".platform-settings.yml"
def load_all() -> list[dict]          # every entry in file order
def is_declared(entry: dict) -> bool  # (entry.get("detection") or {}).get("declared") is not None
def load() -> list[dict]              # [e for e in load_all() if not is_declared(e)]  (unchanged meaning)
def get(sid: str) -> dict | None      # from load_all()
def declared_ids() -> list[str]       # ["platform"]
```

CLI: `ids` prints the `load()` ids, as today (`scripts/test-detect-shape.sh` iterates them). `get <id> <field>` reads `load_all()`. `validate` and `check` run over `load_all()`.

Validation rules for a declared entry (AC-123.10). Each one is an `ERROR:` line from `shapes.py validate`/`check`, which then exits 1:

| Condition | Message |
|---|---|
| `detection.declared` is not `.platform-settings.yml` | `<id>: detection.declared must be .platform-settings.yml (ADR-056)` |
| `detection` also has `copier_src` or `sniff` | `<id>: a declared shape has no copier_src or sniff rule (ADR-056)` |
| `template` is not null | `<id>: a declared shape has no template (template: null, ADR-056)` |
| `deployable` or `library` is true | `<id>: a declared shape is neither deployable nor a library (ADR-056)` |
| any of `runtime`, `smoke_tag`, `smoke_globs`, `default_stack` is present | `<id>: a declared shape has no <key> (ADR-056)` |
| `plugins/<plugin>/` missing (`check_files`) | `<id>: plugins/<plugin>/ missing (status <status>)` (existing text) |

A declared entry is exempt from the `copier_src`/`sniff` rule, the `test_globs` and `ci_checks` requirements, `check_contract` (no template to check) and `check_prd` (the PRD §4 table lists template shapes; the PRD parser also only matches ids that contain a hyphen).

A non-declared entry keeps every existing rule, plus one new one: `template` null or missing → `<id>: template missing: only a shape declared in .platform-settings.yml has none (ADR-056)`. A missing `detection` or `plugin` still fails through the existing `missing field` and `plugins/... missing` errors.

### Settings key (`scripts/cplat/settings.py`)

```python
class ShapeDeclarationError(PlatformError): ...
def declared_shape(repo: Path) -> str | None
```

The checks run in this order. The first one that applies wins.

1. **User file** (`${XDG_CONFIG_HOME:-~/.config}/sdlc-foundry/settings.yml`) has a top-level `shape` key, whatever its value (AC-123.6):
   `ShapeDeclarationError("<user file path>: `shape` belongs in the repo's committed .platform-settings.yml, not in the personal settings file", hint="move or remove the `shape:` line; only the platform repo declares a shape")`
2. **Project file** (`<repo>/.platform-settings.yml`) missing, not a mapping, or without `shape` → `None`. Nothing changes for any repo (AC-123.7).
3. Value is a template shape id (in `load()` ids) (AC-123.4):
   `ShapeDeclarationError("<project file path>: shape '<value>' cannot be declared: only 'platform' can be declared; a component repo's shape comes from its .copier-answers.yml (for an existing repo: cplat adopt --type <value>)")`
4. Value is not in `declared_ids()`, including non-strings, which are shown with `str()` (AC-123.3):
   `ShapeDeclarationError("<project file path>: unknown shape '<value>'; the shapes that can be declared are: platform", hint="fix or remove the `shape:` line in .platform-settings.yml")`
   The list is `", ".join(declared_ids())`.
5. Otherwise → the value (`"platform"`).

Unreadable YAML in either file → `PlatformError("<path> cannot be read: <e>")`, as the other readers already do. The readers of `coordinator_model`, `kube_context`, `budget`, `validation` and `telemetry` are not changed. They read only their own key, so a `shape` key next to them changes nothing (AC-123.7).

### Resolution (`scripts/cplat/shapecmd.py`)

```python
def resolve(repo: Path) -> str | None
```

1. `declared = settings.declared_shape(repo)`. Its errors propagate.
2. If `declared` is set: read `_src_path` from `<repo>/.copier-answers.yml` (when the file exists) with the same rule as `detect-shape.sh` (trailing `/` and quotes stripped). If it ends in `templates/<t>` for a template `t` of `load()`, raise (AC-123.5):
   `ShapeDeclarationError("conflicting shape sources: .platform-settings.yml declares 'platform' and .copier-answers.yml names templates/<t>; remove one of them", hint="a component repo keeps .copier-answers.yml and drops `shape:`; the platform repo has no .copier-answers.yml")`
   Sniffed markers never conflict: only `.copier-answers.yml` counts. Otherwise return `declared`.
3. Else return the stdout of `detect-shape.sh`, or `None` when it is empty.

Nothing is written in any of these steps.

`route(repo)` calls `resolve`. `None` raises the existing error unchanged: `PlatformError("cannot determine the repo's shape", hint="ask the user which shape this is, or add a .copier-answers.yml (docs/ADOPTING.md)")` (AC-123.2). The entry comes from `core.registry.get(shape)`. A declared shape has no `release` role.

`cplat shape` output for `platform` (AC-123.1), exactly these keys in this order:

```json
{
  "shape": "platform",
  "plugin": "svc",
  "deployable": false,
  "library": false,
  "agents": {
    "coder": "svc:coder",
    "tester": "svc:tester",
    "product-manager": "svc:product-manager",
    "architect": "svc:architect",
    "reviewer": "svc:reviewer",
    "quality": "shared:quality",
    "security": "shared:security"
  }
}
```

The output has no `unsupported`, `deployment`, `observability`, `migrations` or `release` key. The routing of every other shape is unchanged.

Every command that needs the shape fails on a declaration error with exit 1, the message on stderr in cplat's usual error format, and no file written: `cplat shape`, `cplat spec new|check|approve|trace|ci|migrate|test-diff`, `cplat component ship start|deploy`, `cplat platform update`.

### Specs (`scripts/cplat/spec.py`)

- `repo_shape(root)`: `except ShapeDeclarationError: raise`, then `except PlatformError: return None`, as today.
- `check()`: `known = {s["id"] for s in core.registry.load_all()}`, so `shape: platform` is accepted (AC-123.15). An unknown shape still prints `spec.md: unknown shape '<x>' (valid: <sorted ids incl. platform>)`.
- New helper:

  ```python
  def spec_shape(spec: Spec, repo_shape: str | None) -> str | None:
      return spec.meta.get("shape") or (None if repo_shape in core.registry.declared_ids() else repo_shape)
  ```

  It is used for `eff_shape` in `check()`, for `own_shape` in `ci_problems()`, and in the `trace` command. A spec without a `shape:` line in the platform repo is checked and traced exactly as in a repo without a shape. AC-104.4's `(smoke)` raises no error (AC-123.16).
- `smoke_tag()`, `test_globs()` and `smoke_globs()` keep reading `load()`. For `platform`, `smoke_tag` is `None`, so a new spec with `shape: platform` and a `(smoke)` criterion fails with the existing text (AC-123.17):
  `AC-<n>.<m>: (smoke) needs a deployable shape (platform has no smoke tests)`
- `cplat spec new` records `shape: platform` through the existing `repo_shape` path (AC-123.15). `--no-shape` still records none.

### Ship (`scripts/cplat/ship.py`)

- `start()`: the first statement is `shape = shapecmd.resolve(repo)`, before the budget options, the product link and the spec lookup (AC-123.3). The state gets `st["shape"] = shape` (new and resumed runs). After `save_state`, `runs.set_section(st.get("run_id"), "shape", shape)` when `shape` is set: the ship run record has a top-level `"shape": "platform"` (AC-123.22). The `GITOPS_TOKEN` check is unchanged. It asks nothing without a `.platform-app.yml`, and the platform repo has none (AC-123.19).
- `land()`: unchanged (AC-123.20). It already waits for every check `gh pr checks` reports, treats the `skipping` bucket as not blocking, ends at the first `fail`/`cancel`, and squash-merges when all are green. The test drives it with the platform's check names `ci-success`, `DCO sign-off`, `spec-required`, `pr-title` and a skipped job.
- `deploy()`: right after `require_state` and the `phase == "done"` return, before the kube-context lookup:

  ```python
  if shapecmd.route(repo)["shape"] == "platform":
      st["smoke"] = {"outcome": "not-deployable", "row": "not deployable"}
      return _done(repo, st, ["not deployable (platform): nothing to deploy",
                              "Smoke (dev): not deployable", "Promotion (staging): not deployable"])
  ```

  `deploy` returns `(True, lines)` and the phase becomes `done` (AC-123.21). Nothing calls `gh` for pins, `kubectl`, `devbox run smoke` or `staging_deploy`. The run record gets no `smoke` or `promotion` section. Library repos keep today's path (`not deployable (library): nothing to deploy`).
- Issue drafts (`_file_platform_failure`, `smoke.file_issue`): `shape=core.read_stamp(repo).get("shape") or st.get("shape") or "none"`.

### Platform update, doctor, fleet

- `cplat platform update` (`update.resolve`): right after the `.git` check and before the `.copier-answers.yml`, dirty-tree and `--data` checks, `if shapecmd.resolve(repo) == "platform": raise PlatformError("the platform repo is not updated from a template", hint="the platform is released through its own procedure: CONTRIBUTING.md, Releases")`. It exits 1 and writes no file. The same refusal applies with `--migrate` and `--dry-run` (AC-123.11).
- `cplat platform doctor` (`check_repo`): the shape comes from `shapecmd.resolve(repo)`. Rows for `platform` (AC-123.13):
  - `check(OK, "repo shape", "platform")`
  - `check(OK, "repo platform version", f"platform source at v{core.platform_version(repo)}")` replaces the stamp rows. Without `docs/CHANGELOG.md` it reads `platform source at v?`.
  - A `ShapeDeclarationError` → `check(FAIL, "repo shape", str(e), e.hint)` and no stamp row.
  - Component repos: the rows are unchanged.
- `cplat platform fleet` (`process`): repos without a `.platform-version` stamp are still skipped before any clone (AC-123.12). With `--only` the code reads `.platform-settings.yml` through `_read`, and when it parses as a mapping with `shape: platform` the row is `_row(slug, None, None, "skipped", "the platform repo is not updated from a template")`. Otherwise the row stays `skipped` / `not a platform repo`. Without `--only` nothing extra is read and the repo is left out of the report, as today. It never clones, opens a PR or writes.

### Commands (`plugins/component/commands/`)

- `spec.md` step 4, `plan.md` step 2, `verify.md` (under `cplat shape`), `build.md` (under `cplat shape`), `ship.md` (after the first calls): add the sentence "A `cplat shape` error that names `.platform-settings.yml` (an invalid shape declaration) → stop and show it; never ask for the shape." `spec.md` step 4 also says that a repo with a shape (the platform repo included, `shape: platform`) records it: no `--no-shape`. `spec.md`'s "product-manager" line and `verify.md` keep their fallbacks for repos without a shape (AC-123.14).
- `build.md` Phase 5 keeps `Skip with ## Phase 5 skipped — <shape> is not deployable when deployable is false`, which prints `## Phase 5 skipped — platform is not deployable` here. The gates are the existing `cplat quiet test-fast|quality|lint-fix|ci` calls, which run the repo's own `devbox run` scripts (AC-123.18). No shape-specific gate is added.
- `ship.md` Finish: "When deploy printed `not deployable (<shape>): nothing to deploy`, the `dev`, `Promotion (staging)`, `Smoke (staging)` and `Smoke (dev)` rows read `not deployable`; leave out the Unchecked line and every `Next:` line that names `/instance:promote`." The Phase `deploy` paragraph names the platform case: "In the platform repo (shape `platform`) deploy ends at once with `not deployable (platform): nothing to deploy`: no pin, Argo, smoke or staging, and no `devbox run smoke` (which here smoke-tests the templates)." (AC-123.22, AC-123.19)
- `release.md` Phase 0: "If `agents` has no `release` role (shape `platform`), stop before anything changes and print:

  ```
  ## Release refused: the platform is not released with /component:release

  The platform is released through its own procedure: version bumps in .claude-plugin/marketplace.json and each changed plugin's .claude-plugin/plugin.json, the CHANGELOG section, a release PR and a tag. It is described in CONTRIBUTING.md, section Releases.
  ```
  " (AC-123.23)

### The repo's own declaration

`/.platform-settings.yml`, committed (AC-123.8):

```yaml
# Project settings (ADR-036). The platform repo declares its own shape here (ADR-056); component repos never do.
shape: platform
```

`CLAUDE.md` (Layout row for `shapes.yml`, Conventions "Platform changes start with a spec") and `docs/specs/README.md` (line 5) stop saying that the repo has no shape. They say that it declares `shape: platform`, so spec, plan, build, verify and ship work as in a component repo, and that releases follow CONTRIBUTING.md, Releases. `CONTRIBUTING.md` Releases adds one sentence: `/component:release` refuses here; this section is the procedure.

## Risks

- **Existing tests that run against the platform checkout** (`ROOT`) and expect "no shape" change behaviour once `.platform-settings.yml` lands, for example `cplat spec check` on the repo or `runs_agents.identity` on `ROOT`. `spec_shape()` keeps spec checking identical. Any other test that hard-codes "no shape" for `ROOT` is fixed in the task that changes the behaviour, never by weakening an acceptance test.
- **A transitional state on the feature branch:** if t11 (the declaration) merges before t3 and t4, `cplat spec check` on the repo can briefly report AC-104.4. The final state is green, and t4's acceptance test (AC-123.16) proves it.
- **ADR number 056**: 055 is taken by spec 122 (another session, local console).
