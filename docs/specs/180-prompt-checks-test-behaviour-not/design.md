# Design — 180 Prompt checks test behaviour not sentences

## Decisions

- **Two new pure modules, one check.** `promptrefs` (the targets a prompt points to) and `promptpins` (sentence pins in
  tests) hold the logic; `rulescheck.check` calls both, so CI, `pr-check` (rule `rules`) and `ci-local` get them with no
  new command (A3). Same split as spec 168 (`promptrules` pure, `rulescheck` reports).
- **cplat names are checked in code only.** `cplat <noun> <verb>` is read from inline code spans and fenced blocks, never
  from prose, because prose says "cplat runs it" and would fail on the moved noun `runs`. The noun must be a key of
  `cplat.NOUNS` or `cplat.PLUMBING` (or the verb-less run list `cplat runs`); for a `NOUNS` noun the verb (each
  alternative of `a|b`) must be a key of `cplat.NOUNS[noun]`. Plumbing nouns parse their own verbs in their modules, so
  only the noun is checked: importing every plumbing module to read its parser is slow and has side effects.
- **A pin is found by the literal, not the assertion** (A2): every `ast.Constant` string of a `tests/**/*.py` file,
  docstrings and f-strings left out, with at least 4 whitespace-separated words, that occurs (whitespace collapsed,
  case-sensitive) in the collapsed text of one prompt file. Helpers that name targets take short keys
  (`cplat component build`, `/component:build`, a path), so structural tests never trip the guard.
- **The baseline moves only through `cplat platform rules rebaseline`**, which applies the eval gate exactly as the
  `rules-retired` house rule does (`evalgate.verdict_runs`, workflows quick-task and build, plugin tree of `HEAD`, clean
  tree), and records each raise in `baseline.history` of the register (A6). `pr-check` rule `rules-baseline` refuses a
  raise without a matching history entry, so a hand edit cannot slip through.
- **Register edits are line edits**, like `rules_retire._write_runs`: the register carries comments that a YAML dump
  would drop.
- These outlive the feature (how every future prompt test is written; how the size cap moves): one ADR, created in t4
  with `cplat adr add prompt-tests-check-structure-not-wording --decision "Prompt tests check the targets a prompt
  points to; a literal is pinned only as a marked interface; the prompt byte baseline rises only through the gated
  rules rebaseline"`.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/promptrefs.py` | targets of a prompt (links, anchors, plugin-root paths, cplat names, slash commands) and their problems | new |
| `scripts/cplat/promptpins.py` | sentence pins and `# interface:` markers in `tests/**/*.py` | new |
| `scripts/cplat/promptrules.py` | `baseline.history` parsed and validated; `baseline_bytes_line` | changed |
| `scripts/cplat/rules_rebaseline.py` | `cplat platform rules rebaseline` logic and register write | new |
| `scripts/cplat/rulescheck.py` | calls promptrefs + promptpins; counts; `rebaseline` subcommand | changed |
| `scripts/cplat/rules_baseline.py` | pr-check rule `rules-baseline` | new |
| `scripts/cplat/house_rules.py` | registers `rules-baseline`, prints notes, `notes` in `--json` | changed |
| `tests/cplat/structure.py` | test helpers on top of `promptrefs` for the rewritten tests | new |

## Contract

### Prompt targets (`promptrefs`, AC-180.1)

Prompts are `promptrules.prompt_files(root)` (the `evalgate.PROMPT` pattern). Frontmatter is scanned; fenced code is
scanned for cplat names and slash commands only.

| Target | Where it is read | Resolves when |
|---|---|---|
| Markdown link `[t](target)` | outside fenced code and inline code | `target` (before `#`) exists as file or directory. `${CLAUDE_PLUGIN_ROOT}/x` resolves to `plugins/<p>/x` (`<p>` the prompt's plugin), `/x` to the repo root, else relative to the prompt's directory. Skipped: `http://`, `https://`, `mailto:`, targets containing `<` or `{{`. |
| Anchor `#a` (alone or after a `.md` path) | as above | `a` equals a heading slug of the target file (the prompt itself when alone) |
| Plugin-root path `${CLAUDE_PLUGIN_ROOT}/<path>` | everywhere, also code spans and fences | `plugins/<p>/<path>` exists; `<path>` is `[A-Za-z0-9_./-]+` with trailing `.,;:` removed; skipped when it contains `<` or `*` |
| `cplat <noun> [<verb>]` | inline code spans and fenced blocks; regex `\bcplat\s+([a-z][a-z0-9-]*)(?:\s+([a-z][a-z0-9-]*(?:\|[a-z][a-z0-9-]*)*))?` | see Decisions; `runs` passes only with no verb token |
| Slash command `/<p>:<c>` | everywhere; regex `(?<![\w/.:-])/([a-z][a-z0-9-]*):([a-z][a-z0-9-]*)` | `plugins/<p>/commands/<c>.md` exists (a tombstone counts) |

Heading slug (GitHub): heading text with inline code backticks, `*`, `_` emphasis markers and link syntax removed
(link text kept), lowercased, every character other than letters, digits, space, `-` and `_` dropped, spaces to `-`;
the n-th repeat of a slug gets `-n`. Headings inside fences do not count.

```python
@dataclass(frozen=True)
class Target:
    kind: str      # "link" | "anchor" | "plugin-path" | "cplat" | "slash"
    line: int      # 1-based line in the prompt
    raw: str       # as written, e.g. "${CLAUDE_PLUGIN_ROOT}/references/build-pr.md", "cplat component build merge"
    key: str       # normalized: repo-relative path ("plugins/component/references/build-pr.md"), "<path>#<slug>",
                   # "cplat <noun>" or "cplat <noun> <verb>" (one per alternative), "/<p>:<c>"

def slug(heading: str) -> str
def anchors(text: str) -> set[str]
def targets(root: Path, rel: str, text: str) -> list[Target]
def problems(root: Path, rel: str, text: str) -> list[tuple[str, int, str, str]]   # (kind, line, raw, message)
```

Problem kinds and messages (the message names the missing target):

| kind | message |
|---|---|
| `broken-link` | `` `<target>` does not exist (resolved to <repo path>) `` (links and plugin-root paths) |
| `broken-anchor` | `` no heading for `#<a>` in <repo path> `` |
| `unknown-cplat` | `` `cplat <noun> <verb>` is not offered (verbs of <noun>: <v1> <v2> …) `` or `` `cplat <noun>` is no cplat command `` |
| `unknown-slash` | `` `/<p>:<c>` is defined by no plugin (no plugins/<p>/commands/<c>.md) `` |

### Sentence pins (`promptpins`, AC-180.2, AC-180.3)

- Scanned: every `*.py` under `<root>/tests/` (a file that does not parse is skipped). Literals: `ast.Constant` with a
  `str` value, excluding the first-statement docstring of a module, class or function, and excluding f-strings
  (`ast.JoinedStr`). Implicit concatenation is one literal (`lineno` .. `end_lineno`).
- **Pin**: `" ".join(value.split())` has at least 4 words and is a substring of `" ".join(prompt_text.split())` of at
  least one prompt file.
- **Marker**: a comment token `# interface: <reason>` (regex `^#\s*interface:\s*(.*)$`); reason words counted with
  `promptrules`' word pattern; at least 3 (`promptrules.MIN_REASON_WORDS`).
- A marker on line `L` **covers** every pin with `lineno - 1 <= L <= end_lineno`.

| kind | file:line | text | when / message |
|---|---|---|---|
| `sentence-pin` | test file : pin `lineno` | the literal | pin covered by no marker. Message: `` a test pins prompt wording: check structure (the targets `cplat platform rules check` resolves, tests/cplat/structure.py) or mark the literal `# interface: <reason>` `` |
| `short-interface` | test file : marker line | the reason | reason under 3 words: `` the `# interface:` reason has fewer than 3 words ``. The pins it would cover are not counted and not reported again. |
| `stray-interface` | test file : marker line | the reason | the marker covers no pin: `` `# interface:` on a line with no literal that occurs in a prompt `` |

Interface pins = pins covered by a valid marker.

```python
@dataclass
class PinScan:
    failures: list[tuple[str, str, int, str, str]]   # (kind, file, line, text, message)
    interface_pins: int
def scan(root: Path) -> PinScan
```

Budget: the scan adds at most 5 s to `rules check` on the platform repo (prefilter literals whose inner words all
occur in the prompts' word set before the substring test).

### `cplat platform rules check` (changed)

New failure kinds `broken-link`, `broken-anchor`, `unknown-cplat`, `unknown-slash` (file = prompt) and
`sentence-pin`, `short-interface`, `stray-interface` (file = test), same `Failure` shape and sort order as today.
`--only`: prompt-target checks run on the prompts in scope; the pin scan is global and skipped, like `bytes`.

`counts` gains `targets` (targets checked) and `interface_pins` (`null`-free int; 0 under `--only`).
Text OK line:
`OK: <n> rule sentences classified, <k> hard rules; <t> prompt targets resolve; <i> interface pins; prompts <bytes> bytes (baseline <bytes>)`.
`--json` as today with the two new `counts` keys.

### Register `baseline.history` (AC-180.5)

```yaml
baseline:
  commit: "<sha of the commit measured>"
  prompt_bytes: 346010
  history:                       # newest last; written only by `cplat platform rules rebaseline`
    - date: "2026-11-12"
      old: 345859
      new: 346010
      reason: "the replan rule needs its reason clause"
      benchmark_runs: [r-20261112-ab12, r-20261112-cd34]
```

`promptrules.load_register` validates `history` (absent = empty): a list of mappings with exactly these keys; `date` ISO
(string or YAML date), `old` < `new` ints, `reason` of at least 3 words, `benchmark_runs` a non-empty list of strings.
Each violation is a `reg.problems` line (reported as `bad-entry` on `register.yml`). `Register` gains
`baseline_history: list[BaselineRaise]` and `baseline_bytes_line: int` (line of `prompt_bytes:`);
`BaselineRaise(date: str, old: int, new: int, reason: str, benchmark_runs: list[str], line: int)`.
`promptrules.parse_baseline(text: str) -> tuple[int | None, list[BaselineRaise], int]` reads the same from a register
text (used on `git show <base>:docs/rules/register.yml`).

### `cplat platform rules rebaseline` (AC-180.5, AC-180.6)

```
cplat platform rules rebaseline --reason "<why>" [--json] [--repo DIR]
```

Order of checks; the register is written only in the last step:

1. reason under 3 words → `ERROR: the reason needs at least 3 words`, exit 1.
2. `git status --porcelain` not empty → `ERROR: uncommitted changes: <paths>; rebaseline measures a clean tree`, exit 1.
3. `prompt_bytes(root) <= baseline.prompt_bytes` → `OK: the prompts total <n> bytes, within the baseline <b>; nothing needs raising`, exit 0.
4. `evalgate.verdict_runs(evalgate._records(evalgate.WINDOW_DAYS), head_tree=plugins_tree(repo, "HEAD"), tree_of=…,
   baseline_version=latest_tag(repo).lstrip("v"), workflows=("quick-task", "build"))` (`_records` looked up at call
   time so tests replace it). Failures → one `FAIL: <failure>` line each (they carry
   `cplat platform runs benchmark <w> --plugins plugins --reset-first`), then
   `ERROR: the eval gate did not pass; the baseline stays <b>`, exit 1. A `PlatformError` (no run store) propagates
   (cplat prints `ERROR:` and `fix:`), exit 1.
5. Write: `commit` = `git rev-parse HEAD`, `prompt_bytes` = current total, append the history entry (date = today UTC,
   old, new, reason, the run ids in workflow order). Print
   `raised the prompt baseline from <old> to <new> bytes (benchmark runs <id>, <id>); commit docs/rules/register.yml`,
   exit 0.

`--json`: `{"status": "raised"|"nothing"|"refused", "old": int, "new": int, "reason": str, "benchmark_runs": [str],
"failures": [str]}` (same exit codes). It never lowers the baseline (A8).

### `cplat platform pr-check` rule `rules-baseline` (AC-180.7)

`rules_baseline.check(repo: Path, base: str, notes: list[str]) -> list[str]`, in `house_rules.RULES` after
`rules-retired`, skipped when the register is missing at head or at the merge base. Base side: `git show
<merge-base>:docs/rules/register.yml` through `parse_baseline`. Head bytes not above base bytes → nothing. Otherwise:

- head history has no entry absent from base history → problem
  `rules-baseline: docs/rules/register.yml:<prompt_bytes line>: the baseline rose from <base> to <head> bytes with no history entry; raise it with cplat platform rules rebaseline --reason "<why>", not by hand`.
- the newest (last) head entry's `new` ≠ head `prompt_bytes` → problem
  `rules-baseline: docs/rules/register.yml:<prompt_bytes line>: the newest history entry raises to <new> bytes, the baseline says <head>`.
- whenever a raise is detected and head history is not empty, a note
  `rules-baseline: prompt baseline <old> → <new> bytes; reason: <reason>; benchmark runs: <id>, <id>` from the newest
  entry (printed before the problems; also under a new `--json` key `"notes": [str]`).

The OK line becomes `OK: the house rules pass (pr-title, spec-required, changelog fragment, validate, dco, links, rules,
rules-retired, rules-baseline)`.

### Test helpers (`tests/cplat/structure.py`)

```python
def refs(rel: str) -> set[str]            # promptrefs Target.key of every target of the prompt
def points_to(rel: str, key: str) -> bool # key in refs(rel); a path key is repo-relative or plugin-relative ("references/x.md")
def headings(rel: str) -> list[str]       # heading texts of the prompt, in order
```

A rewritten test asserts structure: `points_to(BUILD, "plugins/component/references/build-pr.md")`,
`points_to(PLAN, "cplat adr add")`, `"Phase 2" in " ".join(headings(BUILD))`. Literals code depends on (a `cplat`
output line a prompt quotes, the `**Hard rule:**` marker sentence, `promptrules.STATEMENT`) keep their pin with
`# interface: <reason>`. Every rewritten test keeps the criterion ids it named (A5).

## Risks

- Fixture repos in the spec 168/172 tests contain prompts whose links or cplat names do not resolve inside the fixture;
  t5 adjusts those fixtures (`rules_support.py`) so the old criteria stay proven.
- Between t5 and the rewrite tasks the repo's own `rules check` is red (unrewritten pins); tests that run it on the
  repo (`test_183_prompts.py`) are red until t7–t10 land.
