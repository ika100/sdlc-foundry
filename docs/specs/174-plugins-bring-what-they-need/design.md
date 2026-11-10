# Design — 174 Plugins bring what they need, and one plugin installs the starter set

## Decisions

- **Dependencies go in `plugin.json` only.** The manual check proved Claude Code resolves them from the plugin manifest; the
  marketplace entries do not repeat them, so the dependency list lives in one place. The validator (AC-174.3) still checks a
  marketplace entry that declares `dependencies`, so a later copy cannot go wrong silently. Entries are bare names (`"shared"`),
  never `name@sdlc-foundry`, because a bare name resolves in this marketplace and a fork that renames the marketplace keeps working.
- **`starter` is a bundle plugin:** `.claude-plugin/plugin.json` and a `README.md`, nothing else. Its `dependencies` are the one
  definition of the starter set; `scripts/check-docs.py` reads them (AC-174.4), the docs name the plugin (AC-174.5).
  ADR: [docs/adr/095-plugins-declare-dependencies-and-starter-bundles-the-set.md](../../adr/095-plugins-declare-dependencies-and-starter-bundles-the-set.md).
- **One definition of "tombstone-only".** A new stdlib-only module `scripts/cplat/plugin_set.py` decides it; the dependency
  validator, the docs check and `/platform:doctor` all ask it. Today `check-docs.py` decides it from command descriptions; that
  logic moves into the module (keyed on the `moved-to:` front-matter key that `scripts/tombstones.py` writes), so a bundle with no
  commands counts as installable and the three callers cannot disagree.
- **The doctor's new rows live inside `check_tools()` and `check_plugins()`.** Eight test files stub exactly those functions when
  they exercise `run_checks`; a new top-level check function would run `claude --version` for real in all of them.
- **The minimum Claude Code version is `doctor.MIN_CLAUDE_VERSION = "2.1.311"`** (A2). The docs write the number; a test compares
  them, so raising the constant fails until the pages follow.
- **The dependency check is a separate script** (`scripts/check-plugin-deps.py`, stdlib only like `check-settings.py`) run by the
  `validate` recipe, the CI `validate-manifests` job and `ci-local.sh`, because the `validate` job has no `uv` and must stay a
  `python3` call.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `plugins/starter/.claude-plugin/plugin.json`, `plugins/starter/README.md` | the starter bundle | new |
| `plugins/<live>/.claude-plugin/plugin.json` (12), `.claude-plugin/marketplace.json` | `dependencies: ["shared"]`, minor bumps, the `starter` entry, the new `shared` description | changed |
| `scripts/cplat/plugin_set.py` | marketplace catalog, tombstone-only test, dependency-entry parsing, the starter set | new |
| `scripts/check-plugin-deps.py` | AC-174.3 validator | new |
| `devbox.json` (`validate`), `.github/workflows/ci.yml` (`validate-manifests`), `scripts/ci-local.sh` | run the validator | changed |
| `scripts/check-docs.py` | starter set from `plugins/starter`, `starter@sdlc-foundry` counts as the set, live plugins via `plugin_set` | changed |
| `scripts/cplat/doctor.py` | `claude version` row, `plugin shared` row, starter in the "none installed" fix | changed |
| `docs/QUICKSTART.md`, `README.md`, `docs/USER-JOURNEY.md`, `site/src/content/docs/get-started/local-cluster.md` | the two-line install | changed |

## Contract

### Manifests (AC-174.1, AC-174.2, AC-174.7)

Live plugins (`svc`, `web`, `svc-go`, `svc-java`, `system`, `component`, `api`, `resource`, `instance`, `issue`, `platform`,
`cluster`) gain `"dependencies": ["shared"]` in `plugin.json`. `shared`, `app` and `gitops` declare no `dependencies`.

`plugins/starter/.claude-plugin/plugin.json` has exactly these keys:

```json
{
  "name": "starter",
  "version": "1.0.0",
  "description": "Installs the sdlc-foundry starter set: shared, system, component and platform. Each plugin can still be installed on its own.",
  "author": {"name": "Eike Hensler", "email": "eike.hensler@gmail.com"},
  "license": "Apache-2.0",
  "dependencies": ["shared", "system", "component", "platform"]
}
```

`plugins/starter/` holds no `commands/`, `agents/`, `skills/`, `hooks/` or `bin/`. The marketplace entry:
`{"name": "starter", "source": "./plugins/starter", "version": "1.0.0", "description": <same as plugin.json>, "category": "agents", "tags": ["starter", "bundle"]}`.

`shared`'s description, identical in `plugin.json` and `marketplace.json`: "The cplat launcher every sdlc-foundry command calls,
the quality and security agents and the session hooks. The other plugins depend on it and install it with them."

Each changed plugin (the 12 live plugins and `shared`) moves one minor up from its version on `main` at build time, in both files
(on today's main: svc 4.9.0, web 0.8.0, svc-go 0.8.0, svc-java 0.8.0, shared 1.4.0, system 1.16.0, component 1.16.0, api 1.3.0,
resource 1.9.0, instance 1.6.0, issue 1.2.0, platform 1.8.0, cluster 1.4.0).

### `scripts/cplat/plugin_set.py` (stdlib only)

```python
MARKETPLACE = "sdlc-foundry"
STARTER = "starter"                       # the bundle plugin's name
EXTRAS = ("agents", "skills", "hooks", "bin")

def catalog(root: Path) -> dict[str, dict]
    """Marketplace entries by name, in file order; ValueError("<rel path>: <reason>") when unreadable or not JSON."""
def plugin_dir(root: Path, entry: dict) -> Path          # root / entry["source"]
def manifest(root: Path, name: str) -> dict              # that plugin's plugin.json; ValueError as above
def is_tombstone_only(plugin_dir: Path) -> bool
    """True when the directory has >= 1 commands/*.md, every one has a `moved-to:` key in its front matter, and none of EXTRAS."""
def dependency_name(entry: object) -> str | None
    """'x' or 'x@sdlc-foundry' (x matching [a-z0-9][a-z0-9-]*) -> 'x'; anything else (an object, a version, another marketplace) -> None."""
def starter(root: Path) -> tuple[str, ...]               # dependency names of plugins/starter, in order
```

### `scripts/check-plugin-deps.py` (AC-174.3)

`python3 scripts/check-plugin-deps.py [--root DIR]`; `problems(root: Path) -> list[str]` is importable. For every marketplace entry
and its `plugin.json` that declare `dependencies` (`<file>` is `plugins/<p>/.claude-plugin/plugin.json` or
`.claude-plugin/marketplace.json`):

| Problem | Line |
|---|---|
| `dependencies` is not a list | `ERROR: <p> (<file>): dependencies is not a list` |
| entry not a bare name or `name@sdlc-foundry` (an object, a version range, another marketplace) | `ERROR: <p> (<file>): dependency "<entry>" is not a plugin name or <name>@sdlc-foundry (version ranges are not supported)` |
| name not in the marketplace | `ERROR: <p> (<file>): dependency "<entry>" names no plugin of this marketplace` |
| name is tombstone-only | `ERROR: <p> (<file>): dependency "<entry>" holds only tombstones` |
| name is `<p>` itself | `ERROR: <p> (<file>): dependency "<entry>" is the plugin itself` |
| cycle in the union graph of both files | `ERROR: dependency cycle: <a> -> <b> -> <a>` (once per cycle, starting at its alphabetically first plugin) |

An entry that is not a string prints as its JSON. Then `FAILED: <n> problem(s) in plugin dependencies` (exit 1), or
`OK: <k> plugin(s) declare dependencies on live plugins of this marketplace, no cycle` (exit 0). An unreadable or invalid JSON file
is one `ERROR: <rel path>: <reason>` line and exit 1. Wired as `python3 scripts/check-plugin-deps.py` into `devbox run validate`,
the CI `validate-manifests` job (its own step) and the first step of `scripts/ci-local.sh`.

### `scripts/check-docs.py` (AC-174.4)

- `STARTER = plugin_set.starter(ROOT)` at import (today `("shared", "system", "component", "platform")`); no literal tuple remains.
- `live_plugins(cmds)` keeps its signature; it returns every directory under `plugins/` with a `plugin.json` that is not
  `plugin_set.is_tombstone_only`. `starter` is live, so `/plugin install starter@sdlc-foundry` passes and its README is checked.
- A page whose fenced blocks install `starter@sdlc-foundry` counts as installing every name in `STARTER`. A block with neither
  `starter` nor all four still fails with today's message (`installs … but not the starter plugin(s) …`).

### `/platform:doctor` (AC-174.6)

| Row name | Status | Detail | Fix | When |
|---|---|---|---|---|
| `claude version` | ok | `<have> (minimum 2.1.311)` | — | `claude` on PATH, `claude --version` gives `X.Y.Z` ≥ minimum |
| `claude version` | warn | `<have>, older than 2.1.311: installing one plugin does not install the plugins it depends on` | `claude update` | version below minimum |
| `plugin shared` | fail | `not installed, but <a, b> need it: their commands call cplat, which shared provides` | `claude plugin install shared@sdlc-foundry` | ≥ 1 sdlc-foundry plugin installed, `shared` not, and ≥ 1 installed catalog plugin other than `shared` is not tombstone-only |

No `claude version` row when `claude` is missing (the `claude` row already warns), when `claude --version` fails, times out
(10 s) or prints no `X.Y.Z`. The version is the first `\d+\.\d+\.\d+` in its stdout (`2.1.311 (Claude Code)`). The `claude version`
row follows the `claude` row in `check_tools()`; the `plugin shared` row follows the `plugins` row in `check_plugins()`. The
"none installed" fix becomes `/plugin marketplace add ika100/sdlc-foundry && /plugin install starter@sdlc-foundry`. A `fail` row
makes `cplat platform doctor` exit 1, as today. `doctor.MIN_CLAUDE_VERSION = "2.1.311"`.

### Docs (AC-174.5)

Each of the four pages has a fenced `text` block with exactly the two lines

```text
/plugin marketplace add ika100/sdlc-foundry
/plugin install starter@sdlc-foundry
```

and, outside fenced blocks, one sentence that each plugin can be installed alone, with `component` (which brings `shared`) as the
example in inline code, and the minimum version `2.1.311` with `claude update`. A single-plugin install never goes in a fenced block,
because the docs check would read it as an incomplete starter set.

## Test impact

The acceptance tests replace two assertions of `tests/cplat/test_161_docs.py` that pin the four-line install: AC-161.5
(`set(STARTER) <= set(installs)` in the quickstart's text block) and AC-161.8 (the four `/plugin install` lines in the user journey).
AC-174.5 says the AC-161.5 test checks the new block. `check_docs.STARTER` stays a tuple equal to today's, so the AC-161.3 test holds.
