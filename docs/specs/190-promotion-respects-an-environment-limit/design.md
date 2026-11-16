# Design — 190 Promotion respects an environment limit in the spec

## Decisions

- One new module, `scripts/cplat/envlimit.py`, owns the field: parsing, the `spec check` errors, which specs limit a target,
  and every output line of this spec. `spec.py`, `promote.py`, `staging.py` and `appship_joint.py` call it and format nothing
  themselves, so the four entry points cannot drift apart in wording.
- The limit is **fail-closed**: `environments: [qa]` or `environments: dev` (a string) is a `spec check` error, and at promotion
  the allowed set is the known names the field lists (a string counts as a one-item list; an empty or all-unknown list allows
  nothing). A malformed field therefore refuses promotion instead of silently allowing it. A spec whose front matter cannot be
  read at all (`BrokenSpec`) limits nothing locally: `cplat spec check` already fails on it.
- The limit is checked for `--to staging` and `--to prod` only. `--to dev --version <tag>` (the spec 124 rollback) and
  `--smoke` are never refused: dev follows `main` through pin PRs this spec does not gate, so refusing a rollback to a version
  dev already ran would protect nothing.
- `cplat instance promote` checks the limit right after it found the application directory and before `require_clean`, image
  lookups or writes: without the override it refuses at once, the dry run included (the preview then holds the `REFUSED:`
  lines and the `fix:` line, no image or digest lines). The limit does not depend on images, so there is nothing more to show,
  and no network call can hide the refusal.
- Every spec in the gitops-app repo's `docs/specs/` counts as a system spec of every system in it (A2, A4): a gitops-app repo
  holds one system in practice, and specs do not name their system.
- Automatic staging reads the limits in all three places that promote by themselves: `staging.decide` (the component ship's
  `deploy` and `instance verify dev`'s `follow_staging`, both reading the gitops-app over `gh api`) and
  `appship_joint._candidates` (the system ship, on its local gitops clone). `staging.decide` reads the specs last, only when
  every other check would promote, so a skip for another reason costs no extra API calls.
- Remote reading is fail-closed for a listed spec: when `docs/specs` cannot be listed (no such directory, or the call fails)
  there is no limit; when a listed `spec.md` cannot be read or parsed, staging is not promoted with the reason
  `environment limit of <dir> not readable`, because a transient read error must not let a limited system reach staging.
- AC-190.4's line `staging: not promoted: environment limit <spec_id> allows <envs>` is the existing spec-093 row with a new
  reason: the component path prints `Promotion (staging): not promoted: environment limit <spec_id> allows <envs>` (and
  `cplat component ship status` shows it as `staging: Promotion (staging): not promoted: …`), the system ship prints
  `Promotion (staging) <repo-id>: not promoted: environment limit <spec_id> allows <envs>`. Acceptance tests match on the
  substring `not promoted: environment limit <spec_id> allows <envs>`. A new prefix only for this reason would make one skip
  read differently from all the others.
- `cplat spec show <id> [--json]` is new (AC-190.5 names it; it did not exist). It prints the spec's summary lines and the
  limit line; `--json` is `spec list --json --detail`'s object for that spec. `environments` is added to the `summary` dict, so
  `spec list --json` carries it too. `/system:spec show <id>` keeps running `plan.py show`; the approval summaries call
  `cplat spec show`.
- `cplat spec approve` gains `--json` (AC-190.5 asks for `environments` in it).
- The override reuses `promote._reason_ok` (the digest override's rule, A5); one flag covers every limiting spec.
- The person-only override is a hard rule in `/instance:promote` under the existing register key `prod-needs-explicit-confirm`
  (as `--accept-digest-mismatch`), so the register keeps its 13 distinct hard rules.
- The product-manager rule and the benchmark case (AC-190.6) are prompt behaviour; the benchmark gets its own workflow
  `spec-environments` with a result check, like `explore-stop` (spec 188).
- No ADR: the field and its check are local to promotion and recorded here and in the spec-format reference.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/envlimit.py` | parse `environments:`, check errors, find limiting specs (local and remote), every line of this spec | new |
| `scripts/cplat/spec.py` | `check` calls `envlimit.field_errors`; `summary` carries `environments`; `show` subcommand; `approve` prints the limit line, `--json` | changed |
| `scripts/cplat/promote.py` | `--accept-environment-limit`, refusal, dry-run `REFUSED:`, accepted lines in output and PR body | changed |
| `scripts/cplat/staging.py` | `decide` skips with the limit reason (remote specs of the gitops-app) | changed |
| `scripts/cplat/appship_joint.py` | `_candidates` skips every repo with the limit reason (local specs) | changed |
| `scripts/cplat/runs_bench.py`, `scripts/cplat/benchmark/tasks.json` | benchmark workflow `spec-environments` and its result check | changed |
| prompts | product-manager rule, spec-format field, approval summaries, `/instance:promote` rule and hard rule | changed |

## Contract

### The field (AC-190.1)

Spec front matter, optional:

```yaml
environments: [dev]            # the environments the spec's behaviour may run in, out of dev, staging, prod
```

`cplat spec check` errors (printed as `ERROR: <spec_id>: <error>`, exit 1), checked for every status:

| Value | Error |
|---|---|
| absent | none (limits nothing) |
| `[]`, `null`, a string, a mapping | `spec.md: environments must be a non-empty list out of dev, staging, prod (got <value as YAML flow, e.g. [] or dev>)` |
| a list with an unknown name | `spec.md: environments: unknown environment '<name>' (valid: dev, staging, prod)`, one error per unknown name |

### envlimit.py (public interface)

```python
ENVIRONMENTS: tuple[str, ...]            # = model.ENVIRONMENTS: ("dev", "staging", "prod")
LIMITING = ("building", "done")          # A3

@dataclass(frozen=True)
class Limit:
    spec_id: str
    title: str
    environments: tuple[str, ...]        # the allowed set (known names, in field order)
    @property
    def number(self) -> str: ...         # "042" of "042-anonymous-use"

def field_errors(meta: dict) -> list[str]
def allowed(meta: dict) -> list[str] | None           # None: no field; else the known names listed (string -> [string])
def limit_of(spec_id: str, meta: dict, target: str) -> Limit | None   # status in LIMITING, field present, target not allowed
def local_limits(repo: Path, target: str) -> list[Limit]              # spec.scan(repo)[0], in spec-id order
def remote_limits(list_dirs: Callable[[str], list[str] | None], read_text: Callable[[str], str | None],
                  target: str) -> tuple[list[Limit], list[str]]       # (limits, dirs whose spec.md was unreadable)
def envs_text(envs) -> str                            # "dev" | "dev, staging"
def refusal_line(lim: Limit, target: str) -> str
def fix_text(limits: list[Limit]) -> str
def accepted_line(lim: Limit, reason: str) -> str
def skip_reason(limits: list[Limit], unreadable: list[str] = ()) -> str
def summary_line(envs: list[str]) -> str
```

`remote_limits` lists `list_dirs("docs/specs")` (None or `[]`: no limits) and reads each `read_text(f"docs/specs/{d}/spec.md")`,
parsing the front matter with `spec.FRONT` and `yaml.safe_load`. A dir whose text is None, has no front matter or does not
parse as a mapping goes into the second element. `envlimit` imports `model` at the top and `spec` inside the functions that
need it, so `spec.py` can import `envlimit` without a cycle.

### Lines (exact)

| Function | Text |
|---|---|
| `refusal_line` | `environment limit: <spec_id> allows <envs>, not <target> (<title>)` |
| `fix_text` | `widen the spec with /system:spec --amend <NNN> once the work that lifts the limit has shipped, or promote anyway with --accept-environment-limit "<reason>" (a person's decision)`; several specs: `/system:spec --amend 042 / /system:spec --amend 051` in place of the one command |
| `accepted_line` | `environment limit accepted: <spec_id> (<envs>): <reason>` |
| `skip_reason` | `environment limit <spec_id> allows <envs>`, several joined by `; `; each unreadable dir adds `environment limit of <dir> not readable` |
| `summary_line` | `Environment limit: <envs> (promotion to <the other environments> is refused)`; all three listed: `Environment limit: dev, staging, prod (no promotion is refused)` |

`<envs>` is `envs_text` of the allowed set; `<the other environments>` is `envs_text` of `ENVIRONMENTS` minus it, in
`ENVIRONMENTS` order.

### cplat instance promote (AC-190.2, AC-190.3)

New flag: `--accept-environment-limit REASON` (help: `promote although an approved spec limits the system to other
environments; REASON is a sentence`).

1. Argument time, before anything is read: a flag value failing `_reason_ok` (fewer than 3 words or not ending in `.`, `!`,
   `?`) raises `PlatformError("--accept-environment-limit needs a reason of at least one sentence (3 or more words, ending in . ! or ?)",
   hint='e.g. --accept-environment-limit "Login ships next week; the person accepts it."')`: stderr `ERROR: …`, `  fix: …`,
   exit 1.
2. After `find_app` and the `--smoke` branch, for `--to staging|prod`: `limits = envlimit.local_limits(repo, to)`.
3. Limits and no flag:
   - without `--dry-run`: `PlatformError("\n".join(refusal_line(l, to) for l in limits), hint=fix_text(limits))`:
     stderr `ERROR: environment limit: …` (one line per spec, the first prefixed `ERROR: `), `  fix: …`, exit 1; nothing
     written, no PR, `require_clean` not reached.
   - with `--dry-run`: `Report(title="promote <names|--all>: <from> → <to> (<app>)")` with `will_do` = `REFUSED: <refusal_line>`
     per spec, then `fix: <fix_text>`; `data.environment_limits` as below; `emit(True, json)`; exit 1. With `--all` the title
     says `--all` (the names are not resolved yet).
4. Limits and the flag: the promotion proceeds as today. `accepted_line(l, reason)` per spec is added to `will_do` (dry run)
   and `did` (run), and the PR body gets them as one block after the pin list (before the digest-accepted block and the
   evidence). `data.environment_limits` carries them.
5. No limit: the flag changes nothing; no line, `data.environment_limits = []`.

`--json` `data.environment_limits`: `[{"spec": "<spec_id>", "title": "<title>", "environments": ["dev"], "target": "staging",
"accepted": false}]`; when accepted also `"reason": "<reason>"`.

### Automatic staging (AC-190.4)

- `staging.decide`: after the `after-dev-smoke`, instance and nothing-to-pin checks and before `has_workflow`, it calls
  `envlimit.remote_limits` with `gh api repos/<gitops>/contents/<path>` (listing: JSON entries of `type: dir`; text:
  `-H "Accept: application/vnd.github.raw"`), target `staging`. Limits or unreadable dirs give
  `Decision("skip", skip_reason(...), app=..., app_dir=..., previous=...)`. The existing skip path prints
  `Promotion (staging): not promoted: <reason>`; skips are not red (`staging_deploy.skip` returns `True`, `follow_staging`
  changes no verify result).
- `appship_joint._candidates`: `envlimit.local_limits(gitops, "staging")` once; with limits every repo that passes the first
  check (pinned, gate exposed/internal) goes to `skipped[rid] = skip_reason(limits)`, checked before the per-repo digest
  lookups. The existing code prints `Promotion (staging) <rid>: not promoted: <reason>`, writes
  `staging_row = "not promoted: <reason>"` and sets `staging_done` (no candidates): `waits.REACHED`, not red.
- No dispatch, no PR, no state `escalated`.

### cplat spec show / approve (AC-190.5)

`cplat spec show <id> [--json]`:

```
<spec_id> — <title>   [<status>]
<priority> · <n> acceptance criteria · <n> assumptions · <n> open questions
Environment limit: dev (promotion to staging, prod is refused)        # only when the field is present
next: <next_step>
```

`--json`: `spec.detail(root, spec, shape)` (one object), which includes `"environments": ["dev"]` or `null`.

`cplat spec approve <id> [--json]`: text output unchanged plus the `summary_line` after `<spec_id>: approved` when the field
is present. `--json`: `{"id": "<spec_id>", "status": "approved", "plan_aside": "plan.v1.md" | null, "environments": [...] | null}`.

`spec.summary` gains `"environments": allowed(meta)` (a list or `null`); `broken_summary` gets `"environments": null`.

### Benchmark workflow `spec-environments` (AC-190.6)

`tasks.json` entry: `{"task_version": 1, "prompt": "/component:spec <a request for one access change that names dev,
staging and prod as the environments it must work in>", "max_runs": 2, "max_minutes": 20, "plugins": ["component"]}`;
`EXPECTED["spec-environments"] = "spec"`. Result check `environments_kept(keep, clone) -> str | None`: the spec.md files
added since `keep["head"]` on the clone's HEAD (`git diff --name-only --diff-filter=A <head> HEAD -- docs/specs`);
none gives `no spec written`; a spec whose `environments` is present and does not list all three gives
`<spec_id> limits environments: <envs>`; a bullet under `## Open questions` or `## Assumptions` containing `limits to`
gives `<spec_id> suggests an environment limit: <bullet, cut at 120 chars>`; else None.
