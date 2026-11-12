---
spec_id: 192-the-delivery-process-guides-the-person
title: The delivery process guides the person from triage to release
status: approved
priority: P1
shape: platform
---

# 192 — The delivery process guides the person from triage to release

## Problem

On 2026-11-12 the platform owner took nine issues through the whole process by hand: triage, write and approve specs, hand
the work over to run on its own, release. It took about 15 messages, and at every step the person had to know which
command comes next; each command ends by printing another command to type. The facts were all there (`cplat needs`, the
dispatcher's status and inbox, the run records), but nothing put them together into "where am I, and what is my part
now". The last journeys needed a person for about 5 of 131 to 256 minutes; the goal is that those minutes are spent on
decisions, not on finding the next command. The flow was designed and walked through twice with the user, who asked for
the best experience possible.

## Stories

- As the person delivering in a repo, I want one entry point that always shows where I am in the process and the one
  thing waiting for me, so that I never have to remember which command comes next.
- As that person, I want every question to be a choice with a recommended answer, so that I can go on without typing a
  command and approve several specs in one answer.
- As that person, I want to see what an action does outside my machine before I say ok, and how to undo it after, so that
  I can trust a one-click answer.
- As the platform owner, I want each delivered item to record how many questions it asked and how many minutes of a
  person it cost, so that the next journey can report person time for this flow.

## Example screens (illustration, not criteria)

The numbers are invented. The build log and interruption screen belong to the proposed follow-up spec (see Non-goals).

```
 ① Issue ✓ ── ② Spec ● ── ③ Build ── ④ Release
                you are here

 2 specs are written and wait for your approval.

   189  A web image without the security finding              (from #682)
        You get:   a smaller web image without the finding, and a check
                   that scans every template image in our own CI
        I assumed: the check fails only on critical findings (8 assumptions in all)
        Size:      small, about 45 min to build

 Also waiting: 3 new issues.
 Your part: approve, or read first (PR #690, PR #691).
```

```
 ① Issue ✓ ── ② Spec ✓ ── ③ Build ● ── ④ Release
                           running on its own

 2 runs, two at a time: spec 189 (testing), fix #676 (review).

 Your part: nothing. You can walk away; a question reaches you on the
 desktop and shows up here first.
```

## Acceptance criteria

- **AC-192.1** Given any repo state, when the person runs `/platform:next` (or `cplat next`), then the screen has exactly
  three parts in this order: the process bar, what is happening, and a last line starting `Your part:` that says what the
  person has to do or `nothing` with "You can walk away"; the command changes nothing (no GitHub write, no commit, file,
  branch, worktree, claim or run record), keeps no state of its own, and prints the same screen for the same state in a
  fresh session, in another worktree of the repo and after an interrupted session.
- **AC-192.2** Given the repo's shape, when the process bar is printed, then its steps are console stage names with the
  console's explanation texts: Issue, Spec, Build (covering Plan, Build and Land), then `Release` in a platform or library
  repo, or Dev, Staging, Prod in a service, web or gitops-app repo; finished steps carry ✓, the step of the first waiting
  item (else of running work) carries ● with `you are here` under a step the person decides or `running on its own`
  under one that runs without them; the console's How it works and tips show the same text for `Release` and for these
  plain terms.
- **AC-192.3** Given several things waiting at once, when the screen is printed, then it shows the first group in this
  order: a stopped run, a stuck run or a reached daily budget; specs to answer or approve; new issues to triage; a release
  or promotion that is ready; within a group the oldest first; every other waiting item is one line `Also waiting:` with a
  count per kind; an item that was notified shows its age (`waiting 42 min`).
- **AC-192.4** Given nothing waits and nothing runs, when the screen is printed, then it says "Nothing is waiting for
  you.", the number of parked items, and that new issues will show up here; given runs going and nothing waiting, it
  lists each run with its step and says `Your part: nothing` and through which channels of the notification settings a
  question would reach the person, or that notifications are off and to look here again; given a source that cannot be
  read, it names the source and what may be missing, never says "Nothing is waiting", and offers "Try again".
- **AC-192.5** Given drafts that wait for approval, when the spec step is shown, then each spec has its title, the issues
  it tracks, `You get:` (one line of the session's judgement), `I assumed:` with one assumption and the count of all
  unstruck ones, and `Size:` (small for 1–4 active criteria, medium 5–8, large 9+) with a time only when at least 3
  comparable finished runs of that size are recorded in the repo, no number otherwise; no criteria count is shown; the
  choices are "Approve all <n> (recommended)", "Show assumptions", "Approve only one", "Later"; a draft with an open
  question is not in "Approve all" and its questions come first, each with the spec's suggested answer as the recommended
  choice; without the session's judgement text the spec shows its title and no empty field.
- **AC-192.6** Given any screen that asks, when `cplat next --json` is read, then it holds at most 4 questions per page
  with at most 4 options each, the recommended option first and marked, and `page 1 of 2` when more are waiting; an item
  passed with `--later <item>` is not asked again and is counted as "1 put off for later"; the person can go on through
  every step by choosing an option, never only by typing a command.
- **AC-192.7** Given a choice that acts outside the machine (label, comment, pull request, approval commit, merge, tag,
  release), when it is offered, then a "Show details" option lists each outward action with its target, anything that
  cannot be undone is said before the ok, nothing outward runs before the person chose, and the result ends with one
  `Undo:` line per action that can be undone.
- **AC-192.8** Given triage, a spec approval, a finished build or a release has ended, when its output is printed, then it
  ends with the next step as `/platform:next` would show it first, offered as a choice with the recommended option first,
  and a command line appears only as a secondary detail.
- **AC-192.9** Given any screen, when it is printed, then no line is wider than 80 columns; every state is readable
  without colour (a symbol and a word); with `--ascii` or a terminal that is not UTF-8 the symbols become `[x]`, `[>]`,
  `[!]` and the step numbers `1.` to `6.`; a list longer than 5 shows 5 and "and <n> more"; ids (#682, spec 189, PR #690)
  follow the plain description; and the words dispatcher, slot, escalation, escalated, unit, claim and held do not appear
  on screen (the `--json` output keeps its field names).
- **AC-192.10** Given the person answers a question from the entry point, when the answer is recorded, then the record of
  each item it concerns gains one question and the minutes from the screen being shown to the answer (at most 10 per
  question; a group answer splits its minutes evenly over its items), and `cplat platform runs report` shows per
  delivered spec or issue the questions and the person minutes, `–` for an item without records.

## Non-goals

- The build screens, proposed as a follow-up spec "Building and releasing run on their own and interrupt only to ask":
  the build start (numbered queue with estimates from recorded runs, the day's token budget against the queue's need,
  "two at a time / one at a time / not now", first-run set-up of the policy file as a choice), the build log of timed
  events, the three-line interruption ("What happened", "Why I ask", "While you think") with its answer written into the
  spec, a failure that is not a decision (what happened, what was tried, try again / park / show the log path), the end
  of the build with totals and the release in changelog words ("Release now" / "Collect more"), and the last screen.
- The grouped triage screen ("Needs your decision / Clear / Already handled"): spec 176, amended separately; this spec
  only requires that triage ends with the hand-over of AC-192.8.
- The same guidance in the console's web Inbox (follow-up).
- New dispatcher scheduling features, any change to gates or hard rules, and the component-repo promote flow beyond the
  bar's last steps.
- Estimates from anything but recorded runs.

## Assumptions

- **A1** The command is `/platform:next` with `cplat next` behind it, because plugin commands are namespaced and the
  platform plugin is in the starter set of every repo (other option: a bare `/next` project command rendered into every
  template; affects AC-192.1, AC-192.8).
- **A2** The bar uses the console stage names, so its first step reads `Issue`, not `Triage` as in the simulation; Plan
  and Land fold into Build; the one new term is `Release` (platform and library repos), added to the console glossary
  with "runs on its own", "two at a time" and "needs you" (other option: `Triage` as an alias term in the glossary;
  affects AC-192.2).
- **A3** A gitops-app repo shows the same Dev, Staging, Prod steps as a deployable component, read from the system's
  needs (other option: a system-only bar with Spec, Plan, Ship; affects AC-192.2).
- **A4** A reached daily budget ranks with stopped runs, because it blocks all starts; approvals rank before triage
  because approved work can start at once (other option: budget last as information; affects AC-192.3).
- **A5** Screens are printed by `cplat` (code, tested, identical every run); the session supplies only judgement text
  (`You get`, the chosen assumption, later "Why I ask") that `cplat` renders in fixed places (other option: the agent
  writes the screen; affects AC-192.1, AC-192.5).
- **A6** Size comes from the active criteria count with the thresholds 4 and 8, and the time is the median of at least 3
  comparable finished runs, as the console's estimates already are (other option: size from the plan's task count, known
  only after planning; affects AC-192.5).
- **A7** The most important assumption is chosen by the session; without judgement text the spec's A1 is shown (other
  option: always A1; affects AC-192.5).
- **A8** "Later" is passed back by the session as `--later <item>`, so `cplat next` stays stateless; a new session asks
  again (other option: store "later" in the dispatcher state; affects AC-192.6).
- **A9** The screen's `--json` carries the time it was shown, and the answer carries it back, so measuring needs no write
  by `cplat next`; a question left over 10 minutes counts as 10, the rest as away (other option: no cap; affects
  AC-192.1, AC-192.10).
- **A10** The approval screen's group choice approves each spec with the existing approval command, one approval commit
  per spec; the chosen option is the person's own answer under the existing hard rule (other option: approve only one
  spec per answer; affects AC-192.5, AC-192.7).
- **A11** Lists cut after 5 entries; the ASCII symbols are chosen by `--ascii` or a locale that is not UTF-8, and colour is
  never needed to read a state (other option: cut after 10; affects AC-192.9).
- **A12** The build needs prompt rules in the new command and in the triage, spec, release and ship commands (hand-over,
  choices); each gets an entry in the rule register and the prompts stay within the size baseline or raise it with a
  reason (other option: none; this is a build note, not a criterion).

## Open questions

None.

## Changelog

- 2026-11-12 created
- 2026-11-12 approved
