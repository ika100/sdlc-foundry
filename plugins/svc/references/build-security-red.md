# Build: the security gate is red

Read from `/svc:build` Phase 3 when `cplat quiet ci` is red on the security gate.

Security → run `cplat deps patch` first (ADR-034): it bumps every fixable dependency finding, re-runs the gates and commits, or reverts. Exit 0 → the gate is green, go to step 3. Exit 3 → escalate with the `ESCALATE` reason and the `CAUSE` it printed: in a `/svc:ship` run `cplat ship escalate '<reason>' --cause <CAUSE>`, alone `cplat runs end --outcome escalated --reason '<reason>' --cause <CAUSE>`. Exit 4 → not a dependency finding (secrets, bandit, image scan): the **security** agent (`agents.security`) handles it as before: a CRITICAL secrets or bandit finding escalates at once; HIGH is documented and the build continues. A red gate after a bump is never handed to a coder, and acceptance tests stay fixed. Patch rounds (at most 2, counted by cplat) are separate from the 2 fix rounds below.
