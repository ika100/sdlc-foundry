---
spec_id: 109-every-requirement-traces-to-its-evidence
shape: platform
spec_hash: 057a7e4dc3da
summary: "cplat spec trace <id> --chain [--json] prints, per active criterion, the chain issue -> spec -> criterion -> tests -> verdict -> PR (merged from feature/<spec_id>) -> release (oldest local vX.Y.Z tag containing the merge) -> dev/staging/prod (gitops-app pins through the model, gh default branch or a sibling local checkout), each link ok/missing/stale/unknown/n/a with a reason, a summary, a gap list, orphan tests and one note on what could not be reached; read-only, one gh probe with a 10 s timeout, always exit 0 once printed; plain trace unchanged; cplat spec ci warns once per orphan test id (withdrawn or unknown) without changing the exit code"
tasks:
  - id: t1
    title: spec.py — orphan_tests() shared scan, spec ci orphan warnings (never errors, exit unchanged), trace --chain flag handing off to spec_chain
    files: [scripts/cplat/spec.py]
    covers: [AC-109.1, AC-109.3, AC-109.11, AC-109.13]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: spec_chain_remote.py — gh seam and one-time probe, issue states, merged PRs of feature/<spec_id>, gitops pins (gh default branch, else sibling local checkout)
    files: [scripts/cplat/spec_chain_remote.py]
    covers: [AC-109.6, AC-109.8, AC-109.9, AC-109.10, AC-109.12]
    parallel_safe: true
    depends_on: []
  - id: t3
    title: spec_chain.py — link resolution per status, verdict reader and staleness, release from local tags, environment states, text and JSON output
    files: [scripts/cplat/spec_chain.py]
    covers: [AC-109.1, AC-109.2, AC-109.3, AC-109.4, AC-109.5, AC-109.6, AC-109.7, AC-109.8, AC-109.9, AC-109.10, AC-109.11, AC-109.12]
    parallel_safe: true
    depends_on: [t1, t2]
  - id: t4
    title: docs — HOW-IT-WORKS sentence on the chain and the orphan warning, CHANGELOG [Unreleased]
    files: [docs/HOW-IT-WORKS.md, docs/CHANGELOG.md]
    covers: [AC-109.1, AC-109.13]
    parallel_safe: true
    depends_on: []
---

# Plan — 109 Every requirement traces to its evidence

Design: [design.md](design.md). The contract (link texts, text and JSON output, the remote API) is binding.

There are two levels. t1, t2 and t4 share no file. t3 needs t1's `orphan_tests` and the `--chain` hand-off, and t2's
`Remote`. No plugin file changes, so there is no version bump. There is no gitops task.

## t1 — spec.py: orphans, the ci warning, the flag

**Files:** scripts/cplat/spec.py
**Covers:** AC-109.1, AC-109.3, AC-109.11, AC-109.13
**Goal:** one shared orphan scan; `spec ci` warns about orphan tests in every repo; `trace --chain` exists and leaves the
plain verb alone.

**Implementation notes:**
- `Orphan` (a small dataclass or NamedTuple: `file`, `id`, `spec_id`, `kind`) and
  `orphan_tests(root, specs, globs)`, as in the design's "Orphan tests":
  - read each file once, skipping `_ignored` paths;
  - match ids with `AC_ANY`;
  - map numbers through `{s.number: s}`;
  - classify an id as `withdrawn` (an `AC` with `withdrawn=True`) or `unknown` (not in `s.acs()`);
  - skip ids that match no spec's number;
  - sort by file, then id.
- `ci()`: after the existing problem lines, compute the orphans over all readable specs. The globs are the union of
  `test_globs(spec_shape(s, repo_shape(root)))`. Print each one as
  `::warning file=<file>,title=spec <spec_id>::<file> names <kind> criterion <id>`, always as a warning. Then print
  `spec-check: <k> orphan test reference(s) (warnings only)` when k > 0. The existing summary line, the `problems`
  list and the return value stay unchanged.
- `trace` parser: add `--chain` (`store_true`, help "the chain from issue to environment per criterion; report only,
  exit 0"). In `main`, when `ns.chain`, call `find` as today (a missing or broken spec still raises, exit 1), then
  `import spec_chain` lazily and `return spec_chain.main_chain(root, spec, as_json=ns.json)`. The non-chain branch
  stays byte-identical.
- Module docstring: mention `trace --chain` and the orphan warning in one line.

**Done when:** the acceptance tests for AC-109.13 pass, plain `trace` / `trace --json` output and exit codes are
unchanged (`tests/cplat/test_spec.py`, the ship trace tests), and `cplat spec ci --strict` on the platform repo returns
the same exit code as before.

## t2 — spec_chain_remote.py: every remote read

**Files:** scripts/cplat/spec_chain_remote.py
**Covers:** AC-109.6, AC-109.8, AC-109.9, AC-109.10, AC-109.12
**Goal:** the chain gets issue states, merged PRs and environment pins through one seam. The seam never writes, never
waits more than 10 s per call, and stops calling once GitHub is down.

**Implementation notes:**
- Seams `gh(args, *, cwd, timeout=TIMEOUT) -> (rc, out, err)` (`subprocess.run`, rc 124 on timeout, 127 when missing)
  and `which(tool)`. Tests replace both.
- `Remote(repo)`: lazy. `slug` comes from `git remote get-url origin` (the `smoke._slug` regex, None without a GitHub
  URL). `down()` probes once, in the design's order (`which gh`, `gh auth token`, `gh api rate_limit` with HTTP 401 or
  "Bad credentials" → `gh not authenticated`) and caches the reason. Any later call with rc 124 sets `down` to
  `GitHub not reachable` and adds it to `unreached` once.
- `issues(numbers)`: `gh issue view <n> -R <slug> --json number,state` per number → `{n: "open"|"closed"}`, or the
  reason (`no GitHub origin remote` without a slug).
- `merged_prs(branch)`: `gh pr list -R <slug> --head <branch> --state merged --json number,url,mergeCommit,mergedAt
  --limit 20` → newest first, `merge_commit = mergeCommit.oid`. Return `[]` when there is none, the reason when down.
- `pins(apps, service)`:
  - for each app slug, when gh is up, list `applications/` (contents API, dirs) and call
    `model.load_remote(system, read)` with `read` through the seam (raw contents, `yaml.safe_load`, None on error);
  - else find the local checkout `repo.parent / <name>` whose `origin` resolves to that slug, and call
    `model.load_dir(<checkout>/applications/<system>)` for each dir with a `system.yaml` (`NotMigrated`/`ModelError`
    → skip that system);
  - the first model where `find_component(self.slug, service)` is not None gives `Pins(source, system, component,
    tags)`, where `tags[env] = inst.tag` for each existing instance;
  - none found but at least one app read → `Pins(source, None, None, {})`;
  - no app readable → `"gitops-app <slug> not reachable (<reason>)"`, and each one goes to `unreached`.
- Only read commands are issued (gh: `auth token`, `api` GET, `issue view`, `pr list`; git: `remote get-url`). No cache
  file and no `git fetch`. Reuse `runlist`/`claim`/`evidence` only for constants, never their writing helpers.

**Done when:** the acceptance tests for AC-109.6, AC-109.8, AC-109.9, AC-109.10 and AC-109.12 that exercise the remote
reads pass with the seams replaced. One offline probe makes exactly one network attempt, and a timed-out call stops all
later calls.

## t3 — spec_chain.py: the chain

**Files:** scripts/cplat/spec_chain.py
**Covers:** AC-109.1, AC-109.2, AC-109.3, AC-109.4, AC-109.5, AC-109.6, AC-109.7, AC-109.8, AC-109.9, AC-109.10, AC-109.11, AC-109.12
**Goal:** `main_chain(root, spec, *, as_json) -> int` prints the design's text or JSON and returns 0.

**Implementation notes:**
- Use `Link(name, state, text, data)` and the link order of the design. A resolver that raises becomes
  `unknown: <Type>: <msg>` (AC-109.11).
- Status rules from the design's status table, including `superseded` and product specs (`spec_shape(...) ==
  "gitops-app"`).
- **Local links:**
  - issue numbers come from `spec.meta["tracks"]`; the states come from `Remote.issues` (`stale: issue still open (…)`
    on `done`, `unknown: <reason> (#…)` when down);
  - tests come from `spec.trace` and `spec._smoke_traced` with the trace globs;
  - orphans come from `spec.orphan_tests(root, [spec], globs)`, rendered `stale: names <kind> <id>`.
- **Verdict reader and staleness:** follow the design's "Verdict reader" exactly:
  - header-aware tables, first row wins, prefix matching with a qualifier;
  - the verified commit (`**Commit:**`, then the last commit touching verification.md, then the working tree);
  - shallow boundary → `unknown`;
  - `ac_hash` at the verified commit through `git show` and `spec.FRONT`/`Spec(...).ac_hash()`;
  - the walk that finds the `<commit>` of the last criteria change, or `uncommitted`;
  - withdrawn or unknown ids in rows;
  - the unverified reason from the changelog.
- **PR:** `Remote.merged_prs(f"feature/{spec.id}")`. The newest one is the link, and the others are listed as
  `; also merged: #a, #b`.
- **Release:**
  - `git cat-file -e <merge>^{commit}` fails → `unknown: merge commit not fetched`;
  - otherwise run `git tag --list 'v*' --contains <merge>`, filter `^v\d+\.\d+\.\d+$`, and take the minimum by
    `core.vtuple`;
  - no tag → `missing: merged, not in a release`.
- **Environments:**
  - library type (`model.type_lang(repo_shape)`) and no `.platform-app.yml` (`ship.gitops_apps`) → n/a;
  - otherwise `Remote.pins(apps, ship.service_name(root))`, then per env: absent → `n/a: not deployed to <env>`;
    release pins (`evidence.RELEASE`) compare with `vtuple`, or use the local-tag ancestry when there is no release;
    `sha-<7..40>` pins resolve with `git rev-parse --verify -q`, then `merge-base --is-ancestor`; anything else is
    `unknown: tag … is neither a release nor sha-<commit>`;
  - with no PR → `n/a: no merged PR`; with the PR unknown → `unknown: needs the PR (<reason>)`.
- **Output:**
  - text exactly as in the design: header, blocks with 12-character names, the `summary:` line, `missing or stale:`,
    `orphan tests:`, and one `note:` line built from `Remote.unreached`;
  - JSON with the design's keys;
  - nothing else is printed, and stderr stays empty on success.
- Only git read commands, and no import that writes (`runlist._merged_pr`, `claim`).

**Done when:** the acceptance tests for AC-109.1 to AC-109.12 pass, including the read-only check (no changed file, ref
or mtime, only read commands at the `gh` seam), and the 100-spec offline run finishes within 30 s.

## t4 — docs

**Files:** docs/HOW-IT-WORKS.md, docs/CHANGELOG.md
**Covers:** AC-109.1, AC-109.13
**Goal:** the chain and the orphan warning are findable.

**Implementation notes:**
- `HOW-IT-WORKS.md`, section 2, after the sentence on `cplat spec` checks, add one sentence:
  `cplat spec trace <id> --chain` shows, per criterion, the chain from the tracked issue through tests, verdict, PR and
  release to the environments that run it. Links it cannot check are `unknown`, and it never fails. `spec ci` also
  warns about tests that name a withdrawn or unknown criterion.
- `docs/CHANGELOG.md` [Unreleased]: one paragraph for spec 109 covering:
  - `trace --chain` / `--json`;
  - the link states;
  - read-only, with one `gh` probe;
  - pins read from the gitops-app;
  - the orphan-test warning in `spec ci` (warning only, also with `--strict`).

  There is no **Plugins:** line, because no plugin changed.

**Done when:** the Markdown link check passes (`scripts/ci-local.sh`).
