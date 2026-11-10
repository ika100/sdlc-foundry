# ADR-092: A land settles what has an obvious answer

**Status:** Accepted (2026-11-10, spec 171)
**Builds on:** [ADR-089](089-every-merge-into-main-holds-the-repo-merge-lock.md) (the repo merge lock), spec 072 (`ship land`), spec 079 (`cplat pr wait --merge`)

## Context

In the round of specs 167 and 168 and journey 9, landing a pull request stopped for a person four times when the
answer was obvious: `ship land` reported "merge conflicts" after GitHub had already merged, because the local switch
to `main` failed in a worktree (#622); the merge lock judged checks on a head it read but did not pass to the merge
(#623); a resumed repo ship judged the old red CI of a head that lacked its local commits (#625); and a conflict
confined to the generated backlog index stopped the land twice, each retry costing about 25 minutes of CI (#633).

## Decision

`cplat component ship land` and `cplat pr wait --merge` share one landing module (`scripts/cplat/land_merge.py`) with
four rules:

1. **A merge GitHub accepted is a merge.** `gh pr merge` runs without `--delete-branch`; the land deletes the remote
   branch through the API and does the local steps itself (switch to the base branch, fast-forward it, delete the
   feature branch). A failed local step is one `WARNING:` line and never changes the result. When the base branch is
   checked out in another worktree, the land does not switch to it and moves no branch of that worktree. "Merge
   conflicts" is said only when GitHub reports the pull request as conflicting.
2. **The merge carries the head its checks were judged on.** A head the land had to read (it was not known before
   the lock) is the head passed to `--match-head-commit`; a head that moved before the merge sends the land back to
   wait for the new head's checks.
3. **Local commits are pushed before checks are judged.** A feature branch ahead of the pull request's head is pushed
   the way `cplat component ship pr` pushes (its local checks, no force, the open pull request); only the pushed
   commit's checks count.
4. **A conflict in a generated file is regenerated.** `land_merge.GENERATED` lists the files `cplat` writes (today
   the spec index block of `docs/backlog.md`) with their generator. A conflict confined to them is settled by merging
   the base branch into the feature branch, merging the hand-written rest of each file as text, running the
   generator, committing with sign-off and pushing without force; at most 3 rounds per land. Any other conflict,
   and a conflict in the hand-written part of a listed file, aborts the merge attempt and stays a person's decision.

## Consequences

- A new generated file joins rule 4 by adding it, its generated region and its generator to `GENERATED`; nothing else
  regenerates on a guess.
- The land needs a checkout on the feature branch for rules 3 and 4; without one (a `pr wait -R` from another repo)
  a conflict stops as before.
- Rebasing, force-pushing and resolving hand-written conflicts stay out of every automatic path.
