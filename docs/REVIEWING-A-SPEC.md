# Reviewing a spec before you approve it

Approving a spec is the one decision the platform cannot take for you. Everything after it, the plan, the acceptance tests, the code, the verification and the merge, follows the criteria you approved, and an unattended ship runs them to the end without asking again. A wrong turn costs a sentence to fix in the spec and an hour of agent work, CI and a redo once it is built.

The review takes two to five minutes. You do not need to read every line; you need to answer one question per part, in an order that lets you stop at the first part that is wrong.

## Read it in this order

| Part | The question | Stop and push back when |
|---|---|---|
| **Problem** | Is this the problem I asked about? | It solves a slightly different problem, or the scope grew ("while we are in there…"). |
| **Acceptance criteria** | When all of these hold, is the feature done? | One of the red flags below. This part needs most of your time. |
| **Assumptions** | Would I have decided these the same way? | An assumption picks the option you did not want. |
| **Non-goals** | Is everything I need inside the scope? | Something you need is listed as a non-goal. |
| **Open questions** | Can I answer them in a word? | Answer them; the spec cannot be approved while one is open. |

If the problem is wrong, stop there: criteria written for the wrong problem are not worth reading yet.

## The criteria: is "done" defined correctly?

Each criterion becomes a test that is written before the code and frozen, and the build is finished when those tests pass. So a criterion that is vague, missing or wrong is built exactly that way. Look for these red flags:

- **Not observable.** "Handles large uploads gracefully" cannot be tested; "a file over 10 MB gets a `413` with a JSON error body" can. Every criterion should say what someone outside the code would see.
- **Only the happy path.** The valid request is easy. The empty input, the missing record, the second click, the database that is down: those are where bugs live. Ask *what is the one case I would be upset to see broken?* and make sure a criterion names it.
- **Numbers left open.** Limits, timeouts, sizes, how many replicas: a criterion without the number lets the build pick one.
- **Two behaviours in one criterion.** One criterion, one behaviour, so that a failing test points at one thing.
- **Restating the problem.** A criterion that repeats the story in other words tests nothing.
- **Too many criteria.** A spec with more than about twelve criteria is usually two features; split it.
- **Changes what an earlier spec promised.** If the feature changes behaviour an earlier spec defines (tasks that used to be lost on restart are now kept), the new criterion must say which old criterion it replaces, and the old one must be struck through as withdrawn. Otherwise both stay active, and a later verification or test checks behaviour that no longer holds.

## Assumptions: decisions taken for you

The spec decides everything it safely can by default and lists those decisions as assumptions, each with the other option and what it affects. Approving the spec approves them. Read the "other option" of each: if you prefer it, say so, and the decision moves into the criteria.

## A system spec and its repos

A system spec describes one feature across several repos. When you review it, also check that each criterion can be placed in a repo: a criterion about configuration (two replicas of the API, an environment variable) needs a repo that changes too, not only the code repos. After `/system:plan`, every repo gets its own spec with a few criteria; those follow from the plan and need no second approval.

## Pushing back is cheap

Say what to change in plain words ("titles up to 200 characters", "a missing task returns 404, not 500"), or run `/component:spec --amend <id> <change>` (`/system:spec --amend <id> <change>` for a system spec). The spec is amended and comes back for approval. In the local console, "Request changes" on a spec does the same.

When it is right:

```text
/component:spec approve <id>
/system:spec approve <id>
```

## Background

The reading order and the red flags are adapted from OpenSpec's guide to reviewing a change. The red flag about earlier specs comes from the second journey run (issue #477), where a new criterion said in free text which criterion it replaced and the old one stayed active.
