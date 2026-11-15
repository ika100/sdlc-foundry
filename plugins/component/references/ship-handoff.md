# Ship: the hand-off

Read from `/component:ship` when `ship start --detach` printed `headless: pid`.

- Never start a subagent or a step of plan, build, PR, land or deploy, because their context would fill this session.
- Always run `cplat component ship wait` in the foreground and act on its result, because the run goes on in its own process:
  - `WAIT:` or `TIMEOUT:` → the same wait; after three `TIMEOUT:` in a row never wait again: show their lines and stop, since the run goes on.
  - `ENDED:` → `cplat component ship start <spec> --detach [flags]`, then wait.
  - `REACHED:` → Finish of `ship.md`.
  - `ESCALATED:` cause `decision` with every question suggested and the person having said in this session to take suggested answers → resume with `--detach --answer '<the suggested answers>'`; otherwise always ask the person each question word for word and resume with their answer, because the person decides what the spec left open.
  - `ESCALATED:` with any other cause (`code`, `environment`, `platform`, `unknown`) → the Escalate report of `ship.md` (reason, status, decision), never a resume, since an answer cannot fix it.
