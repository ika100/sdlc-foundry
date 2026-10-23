# Design — 085 A broken spec names itself and stops nothing else

## Decisions

- **One error type, raised by the loader.** `spec.load` raises `BrokenSpec(PlatformError)` for every unreadable front matter (YAML error, no fences, not a mapping). Because it is a `PlatformError`, `cplat.py` already prints it as `ERROR: …` / `  fix: …` with exit 1 and no traceback (AC-085.1, AC-085.6). Callers outside spec folders (`slice_from_plan`, `migrate_plan` on `docs/plan/`) still get a `PlatformError`, so their behaviour is unchanged (non-goal).
- **Discovery separates good from broken, never drops either.** A new `scan(root)` returns `(specs, broken)`. `all_specs` keeps its signature and returns only readable specs, so every existing caller (`find` candidates, `test_diff`, `ci` count) keeps working when one spec is broken (AC-085.4, AC-085.5). Commands that report on *all* specs (`check` without ids, `ci`, `list`, `index`) and `next_number` also consume `broken` (AC-085.7 to AC-085.11).
- **`find` knows broken specs.** It matches the ref against readable and broken folders alike; when the single hit is broken it re-raises that `BrokenSpec` (AC-085.6). A valid spec is found exactly as today (AC-085.4). `cplat ship` reaches specs only through `find` and a `cplat spec trace` subprocess, so no ship change is needed (AC-085.5).
- **Titles are written so they read back as typed.** `save` keeps PyYAML's emitter, which already quotes scalars that would resolve to another type or are not plain-safe. `new` then re-reads the file; if the title does not come back as the identical `str`, it is a platform defect and `new` raises before returning. The tests pin the listed cases (AC-085.12).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/spec.py` `BrokenSpec`, `load`, `read` | parse front matter, locate the bad line, choose the hint | changed |
| `scripts/cplat/spec.py` `scan`, `all_specs`, `find`, `next_number` | discovery that tolerates broken folders | changed |
| `scripts/cplat/spec.py` `main` (`check`), `ci`, `ci_problems`, `summary`/`list`, `index_table` | report broken specs | changed |

## Contract

### `BrokenSpec`

```python
class BrokenSpec(PlatformError):
    dir: Path      # the spec folder (docs/specs/<id>)
    id: str        # folder name; number = id.split("-", 1)[0]
    rel: str       # file path relative to the repo root, e.g. "docs/specs/090-x/spec.md"
    line: int      # 1-based line in that file
    problem: str   # one line, no YAML snippet, e.g. "front matter is not valid YAML: mapping values are not allowed here"
    hint: str      # the fix hint (PlatformError.hint)
    def one_line(self) -> str: ...   # f"{rel}, line {line}: {problem} (fix: {hint})"
```

`str(e)` is `f"{rel}, line {line}: {problem}"`. The repo root is `sdir.parents[2]` for a spec folder; `load(path, root=None)` shows `path` unchanged when no root is given.

### Line and hint

| Case | `line` | `problem` | `hint` |
|---|---|---|---|
| YAML error whose problem is `mapping values are not allowed here` | `problem_mark.line + 2` (front matter starts on file line 2) | `front matter is not valid YAML: <problem>` | `values that contain ': ' must be quoted, e.g. title: "a: b"` (exact text, AC-085.1/085.3) |
| any other YAML error | `(problem_mark or context_mark).line + 2`, else 1 | `front matter is not valid YAML: <problem>` | `quote the value on that line, e.g. title: "a: b"` |
| no `---` fences | 1 | `missing front matter` | ``front matter must be: a `---` line, `key: value` lines, a `---` line`` |
| front matter not a mapping (list, scalar, empty) | 1 | `front matter is not a mapping of keys to values` | same as no fences |

Only `problem` from the YAML exception is used; its multi-line snippet and traceback are never printed.

### Command output

- **Addressed by ref** (`approve`, `set-status`, `task-done`, `hash`, `trace`, `check <id>`): stderr `ERROR: <rel>, line <n>: <problem>` then `  fix: <hint>`, exit 1, nothing written (AC-085.6). `plan.md` is reported the same way with its own path (AC-085.3).
- **`check` without ids**: valid specs as today; each broken spec adds exactly one line `ERROR: <id>: <one_line()>` and counts in `<n> error(s)`; exit 1 (AC-085.7).
- **`ci`** (strict or not): each broken spec prints `::error file=<rel>,line=<n>,title=spec <id>::<problem> (fix: <hint>)`; the summary counts it as a problem and as a spec; exit 1 whenever any spec is broken, otherwise unchanged (AC-085.8).
- **`list`** (text and `--json`, with or without `--all`): a broken spec is always listed. Row: `id`=folder name, `title`="", `status`="broken", `priority`="", `acs`=0, `open_questions`=0, `tasks`=0, `tasks_done`=0, `tracks`=[], `path`=folder, `next`=`fix <rel> line <n>: <hint>`. Exit 0 (AC-085.9).
- **`index`**: a broken spec keeps the row `| [<id>](specs/<id>/spec.md) —  |  | broken | 0 |  |` (empty title and priority) (AC-085.10).
- **`new`**: `next_number` counts the numbers of broken folders too (AC-085.11).

## Risks

- PyYAML marks some errors (an unclosed quote) at the end of the front matter, not the opening line. Acceptable: the hint still says what to do, and the criteria pin only the `: ` case.
