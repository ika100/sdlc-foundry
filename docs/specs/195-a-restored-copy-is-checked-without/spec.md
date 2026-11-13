---
spec_id: 195-a-restored-copy-is-checked-without
title: A restored copy is checked without kubectl
status: done
priority: P1
shape: platform
tracks: [683]
---

# 195 — A restored copy is checked without kubectl

## Problem

A restore drill ends with "prove the restored copy holds the expected data", but no platform command runs a query against a database resource instance. In journeys 11 and 12 the session therefore ran `psql` through `kubectl exec` by hand, against the gitops-app rule "never call kubectl directly", and `/resource:restore` itself prints that kubectl line as its check step. A read-only query command closes the gap without giving the session a way to change data.

## Stories

As an operator of a system, I want to run a read-only query against a database of an environment, the restored copy included, so that I can prove a restore holds the expected rows without calling kubectl or risking a write.

## Acceptance criteria

- **AC-195.1** Given a database resource with an instance in `<env>`, when `/resource:query <db> --env <env> "<sql>"` runs a SELECT, then it runs the statement against the active instance and prints the result as a plain table (a header line with the column names, one line per row, then `<n> rows`) and exits 0; with `--json` it prints `{"instance": …, "columns": [...], "rows": [[...], ...], "truncated": false}` instead. At most 1000 rows are shown; beyond that it shows the first 1000, says `truncated at 1000 rows` (`"truncated": true` in JSON) and still exits 0.
- **AC-195.2** Given a restored or `previous` instance `<system>-<db>-g<N>` of `<db>` in `<env>` (spec 117), when the query runs with `--copy g<N>`, then the statement runs against that instance instead of the active one, and the output names the instance it was run on.
- **AC-195.3** Given any statement that would change data or schema (for example INSERT, UPDATE, DELETE, CREATE, DROP, or a SELECT calling a function that writes), when the query runs in any environment, `prod` included, then the database refuses it because the session is read-only, nothing is changed, and the command prints the database's error and exits 1. A query in `prod` needs no `--confirm prod`.
- **AC-195.4** Given an external database, an environment where `<db>` has no instance, a `--copy g<N>` that does not exist (the message lists the existing copies, or says there are none), an SQL error, or a query still running after 60 seconds (it is cancelled), when the query runs, then it changes nothing, prints the reason with a `fix:` line and exits 1.
- **AC-195.5** Given `/resource:restore <db> --env <env> --to <time>` that ends with a ready restored instance `<system>-<db>-g<N>` (AC-117.8), when it prints its next steps, then the check step is `/resource:query <db> --env <env> --copy g<N> "SELECT …"` and no step contains `kubectl`.

## Non-goals

- Writing to a database through this command, or an opt-in write mode.
- Interactive sessions (a `psql` prompt), file import or export, and multi-statement scripts.
- Queries against caches, brokers or buckets; only database resources (spec 115).
- A `--check '<sql>'` option on `/resource:restore`; the check is the separate query command.

## Assumptions

- **A1** The command is `/resource:query` (`cplat resource query`), separate from restore (other option: `--check '<sql>'` on `/resource:restore`; affects AC-195.1, AC-195.5).
- **A2** Read-only is enforced by the database session (a read-only transaction), not by parsing the SQL, so a writing function inside a SELECT fails too (other option: refuse non-SELECT text before sending; affects AC-195.3).
- **A3** The query connects as the application role of `<system>-<db>-app`, so it reads what the components read and nothing more (other option: the database superuser; affects AC-195.1, AC-195.2).
- **A4** Output is capped at 1000 rows and a query at 60 seconds (other option: no cap, or a `--limit` flag; affects AC-195.1, AC-195.4).
- **A5** A copy is named by its generation `g<N>`, as `/system:status` and the restore output show it; without `--copy` the active instance is queried (other option: `--copy restored|previous`; affects AC-195.2).
- **A6** Exactly one statement per call; more than one is an SQL error under AC-195.4 (other option: allow scripts; affects AC-195.4).
- **A7** Decided by the user 2026-11-13: a query reads `prod` data without `--confirm prod`, because it is read-only and connects with the application role only, as #683 asks (other option: require `--confirm prod`; affects AC-195.3).

## Open questions

- ~~May a query read `prod` data without `--confirm prod`? Its rows land in the session transcript. (suggested: yes, as #683 asks: it is read-only and connects with the application role only; affects AC-195.3)~~ Answered 2026-11-13: yes, no `--confirm prod`; recorded as A7, AC-195.3.

## Changelog

- 2026-11-13 created
- 2026-11-13 amended: prod-without-`--confirm` question answered (yes), recorded as A7; AC-195.3 unchanged
- 2026-11-13 approved
- 2026-11-13 building
- 2026-11-13 done
