# issue plugin

The `issue` noun: GitHub issues of your repo and of the platform.

| Command | Does |
|---|---|
| `/issue:triage` | Read new issues, discuss gaps with you and show one table, hand fixes to the dispatcher, route features to a spec, answer with a reply, close confirmed question, duplicate, wontfix and silent needs-info issues as not planned, ask reporters plainly for what is missing, or "needs exploring" when the issue is too open to spec (then `/component:explore #<issue>`) (`cplat issue triage`) |
| `/issue:report` | Report a platform problem or idea as a GitHub issue, with secrets removed; nothing is sent without your OK (`cplat feedback`) |

Needs the `shared` plugin (it puts `cplat` on the Bash PATH).
