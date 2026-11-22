**`cplat next` reads GitHub and the run records in time in a repo with many pull requests (#859).** In the platform repo
(over 600 pull requests, over 200 specs), `next` said "Could not read GitHub" and "Could not read the run records"
although `gh` worked: the run list asked `gh` once per branch because one listing of 300 PRs was not complete, the drafts
asked for every spec on its own, and the run list was built twice. Now one listing holds up to 1000 PRs and a branch it
misses is asked once, the specs on `main` come from one GraphQL call, the escalations reuse those texts, and the run list
and budget ledgers are read once per `next`. A source that answers too late is named as such: "Could not read GitHub
within 20 s; it may be missing …".
