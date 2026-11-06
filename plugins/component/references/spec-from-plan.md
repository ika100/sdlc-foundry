# Spec: this repo's slice of a system plan

Read from `/component:spec --from-plan <plan> [<repo-id>]` (section D). The plan lives in the gitops-app repo (`docs/plan/<spec_id>.md`, ADR-011/026); never edit it from here.

1. `<repo-id>` defaults to this repo's name (or `repo` in `.platform-app.yml`). Run `cplat spec new --from-plan <abs plan path> <repo-id>` (add `--no-shape` only in a repo without a shape): it writes this repo's spec with the system's problem, a **System context** section (the system criteria assigned to this repo, the contract, notes) and `parent:` set. Then `git checkout -b feature/<spec_id>`.
2. **The plan wrote this repo's criteria** (spec 147: the new spec already has acceptance criteria, each naming its `(system AC-<NNN>.<n>)`, and no open questions): no product-manager. Run `cplat spec check <id>`; under `/system:ship` run `cplat spec approve <id>` right away (AC-147.4), by hand show the criteria and ask for the approval. Then continue with step 4 or the plan and build. Otherwise (a plan written before spec 147):
   **product-manager**: `MODE: new`, `SPEC_DIR`, and "the System context section is binding: write this repo's criteria so that together they implement each listed system criterion and follow the contract; every criterion names the system criterion it serves, `(system AC-<NNN>.<n>)`". Then `cplat spec check`, and section B from step 5 on (questions loop, commit, finish).
3. **When run unattended by `/system:ship`** (its prompt says so) with a spec the product-manager wrote: skip the questions loop; the user approved the system spec and its plan (spec 141).
   - `OPEN QUESTIONS` is `none` → `cplat spec approve <id>`.
   - Every question has a suggested answer, and none would change a criterion of the system spec or the plan's contract → **product-manager** `MODE: amend`, "answers to open questions: the suggested ones; also list each question and its answer as one bullet under `## Decisions taken during the ship`". Then `cplat spec check <id>` and `cplat spec approve <id>`.
   - Otherwise (a question without a suggestion, or one that changes the system spec or the contract) → stop and report the questions verbatim. Never invent an answer.
   Then continue with `/component:plan` and `/component:build` as instructed.
4. When run by hand, remind the user that `/system:ship` (or `/system:spec done <id> <repo-id>`, in the gitops-app repo) records the repo as done after its PR merges.
