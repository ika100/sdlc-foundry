// The steps of the recorded journey (journey 5, 2026-11-06, sdlc-foundry 5.12.0, organisation ika100-demo) for
// DemoWalkthrough.astro. `at` is the chapter marker's time in site/public/demo/demo-run.cast.gz; times and facts come from
// the recording, the journey record (`cplat platform runs journey`) and the demo repos.

const ORG = 'https://github.com/ika100-demo';
const GITOPS = `${ORG}/taskboard5-gitops`;
const API = `${ORG}/taskboard5-api`;
const WEB = `${ORG}/taskboard5-web`;
const ISSUES = 'https://github.com/ika100/sdlc-foundry';

export interface Section { heading: string; text?: string; items?: string[]; code?: string }
export interface Step {
  title: string; short: string;
  /** what you would say in Claude Code; empty when the step needs no input */
  say: string;
  /** the command that runs (the plugin command Claude picks for `say`, or the shell command) */
  run: string;
  /** what was typed in the recording */
  command: string; at: number;
  /** working time of the step with the waits for people cut; CI rounds count */
  time: string;
  sections: Section[]; links: { label: string; href: string }[];
}

export const steps: Step[] = [
  {
    title: 'Create the system', short: 'System',
    say: 'Create a system named taskboard5 with one Python service, taskboard5-api, for a task API, in public repos in the ika100-demo organization',
    run: '/system:new taskboard5.yaml --public', command: 'Create a system named taskboard5 with one Python service, taskboard5-api, …', at: 0, time: '7 min',
    sections: [
      { heading: 'Claude does', items: [
        'Writes a short manifest, previews the run with <code>--dry-run</code>, then runs <code>cplat system new</code>.',
        'Renders the gitops repo and the Python service from their templates, creates both public repos and pushes them.',
        'Protects <code>main</code> on both, links the service to the gitops repo, and opens one PR that adds it to <code>system.yaml</code>.',
      ] },
      { heading: 'What went wrong', items: [
        `The network dropped while the API repo was being created, and <code>system new</code> did not retry (<a href="${ISSUES}/issues/539">#539</a>). Its <code>--resume</code> then skipped the repo because the local folder existed (<a href="${ISSUES}/issues/540">#540</a>); Claude removed the folder and resumed again.`,
        `The manifest's <code>owner:</code> alone previewed the repos under another organisation; Claude added <code>org:</code> (<a href="${ISSUES}/issues/541">#541</a>).`,
      ] },
      { heading: 'Result', text: 'Two repos that already build, test, scan and publish an image, and one PR that adds the service to the system.' },
    ],
    links: [
      { label: 'taskboard5-gitops', href: GITOPS },
      { label: 'taskboard5-api', href: API },
      { label: 'PR: add the service', href: `${GITOPS}/pull/1` },
    ],
  },
  {
    title: 'Merge, cluster and expose', short: 'Cluster',
    say: 'Merge the PR once its CI is green, start a local cluster, and make the API reachable from my browser (merge that PR too)',
    run: 'devbox run cluster-up · /component:set taskboard5-api --expose', command: 'Merge the PR once its CI is green, start a local cluster, and make the API reachable …', at: 23.692, time: '10 min',
    sections: [
      { heading: 'Claude does', items: [
        'Merges the PR on green CI and runs <code>devbox run cluster-up</code>: a k3d cluster with Argo CD, External Secrets and the Gateway.',
        'Runs <code>/component:set taskboard5-api --expose</code>: one PR with the route, merged on green CI.',
        'Waits with <code>cplat system wait --env dev</code> until Argo reports the app Synced and Healthy.',
      ] },
      { heading: 'What went wrong', items: [
        `Argo CD's repo server timed out fetching the gitops repo, so the API's app was not created and the first wait failed; Claude asked Argo for one refresh and the next wait was green (<a href="${ISSUES}/issues/542">#542</a>).`,
      ] },
      { heading: 'Result', text: '<code>http://taskboard5-api.taskboard5-dev.localhost:8088/health</code> answers 200.' },
    ],
    links: [
      { label: 'PR: pin dev', href: `${GITOPS}/pull/2` },
      { label: 'PR: expose the API', href: `${GITOPS}/pull/3` },
    ],
  },
  {
    title: 'Write the spec', short: 'Spec',
    say: 'For taskboard5-api: I want to create and list tasks, each with a title and an optional due date, kept in memory',
    run: '/component:spec "create and list tasks …" · /component:spec approve 001', command: 'For taskboard5-api: I want to create and list tasks, each with a title and an optional due date, kept in memory', at: 43.99, time: '13 min',
    sections: [
      { heading: 'Claude does', text: 'A feature of one component takes the component route: the product-manager agent writes the spec in the API\'s own repo and asks every decision that is yours, each with a suggested answer. Then it asks for the approval and merges the spec PR on green CI.' },
      { heading: 'Claude asks, you answer', items: [
        'Path → <code>/tasks</code>; ids → UUID strings',
        'Title → 1 to 200 characters, as sent; due date → a date only',
        'Due date in the past → allowed',
        'List order → oldest first; status codes → <code>201</code> / <code>200</code> / <code>422</code>',
        'Limit on tasks held in memory → none',
        'Memory is per instance → run one replica',
        'Approve spec 001 → approve',
      ] },
      { heading: 'What went wrong', items: [
        `The network dropped again while <code>cplat spec land</code> marked the spec PR ready; the merge was refused and the error blamed a conflict. A second <code>spec land</code> merged it (<a href="${ISSUES}/issues/543">#543</a>).`,
      ] },
      { heading: 'Result', text: '8 acceptance criteria (one later withdrawn by the Postgres spec), approved and merged in the repo that builds them.' },
    ],
    links: [
      { label: 'the spec', href: `${API}/blob/main/docs/specs/001-create-and-list-tasks/spec.md` },
      { label: 'PR: the spec', href: `${API}/pull/2` },
    ],
  },
  {
    title: 'Ship the spec', short: 'Ship', say: 'Build it and get it running in dev. I\'m away: if a repo spec has questions, take the suggested answers.',
    run: '/component:ship 001', command: 'Build it and get it running in dev. I\'m away: …', at: 79.479, time: '33 min (+ 65 blocked)',
    sections: [
      { heading: 'Claude does', items: [
        'The architect plans the spec: models and an in-memory store, the <code>/tasks</code> routes, and a gitops change that pins one replica while tasks live in memory.',
        'The tester writes failing acceptance tests for all 8 criteria first, then the coders work until they pass; review, the gitops PR first, then the API PR, each merged on green CI.',
        'Waits until dev runs the merged build and runs the smoke tests against it.',
      ] },
      { heading: 'What went wrong', items: [
        `The plan's hash, <code>756184979554</code>, has only digits, so YAML read it as a number and <code>cplat spec check</code> called a current plan stale (<a href="${ISSUES}/issues/536">#536</a>). Fixed during the run (<a href="${ISSUES}/pull/537">#537</a>); 31 minutes blocked.`,
        `The gitops PR's CRD check demanded a read token for the public API repo, so the ship stopped for a secret nobody needs. Fixed during the run (<a href="${ISSUES}/pull/538">#538</a>); the gitops repo took the fix with <code>/platform:update</code>, 34 minutes blocked.`,
      ] },
      { heading: 'Result', text: 'Dev runs the task API at one replica; <code>POST /tasks</code> and <code>GET /tasks</code> answer, smoke 5 of 5.' },
    ],
    links: [
      { label: 'PR: one replica', href: `${GITOPS}/pull/4` },
      { label: 'PR: the platform update', href: `${GITOPS}/pull/5` },
      { label: 'PR: the task API', href: `${API}/pull/3` },
      { label: 'PR: pin dev', href: `${GITOPS}/pull/6` },
    ],
  },
  {
    title: 'Add a web UI', short: 'Web UI',
    say: 'Add a web UI to the system: a Next.js website taskboard5-web in a public repo, added to system.yaml and exposed (merge its PR once CI is green)',
    run: '/component:new taskboard5-web --system ika100-demo/taskboard5-gitops … · /component:add taskboard5-web --expose', command: 'Add a web UI to the system: a Next.js website taskboard5-web …', at: 140.947, time: '7 min',
    sections: [
      { heading: 'Claude does', text: 'A fresh session starts part 2 (<code>/clear</code>): every command keeps its state in the repos. Claude creates the Next.js repo from its template, adds it to <code>system.yaml</code> with its own host in dev, merges that PR on green CI and waits until dev runs it.' },
      { heading: 'Result', text: 'The template page runs at <code>http://taskboard5-web.taskboard5-dev.localhost:8088</code>.' },
    ],
    links: [
      { label: 'taskboard5-web', href: WEB },
      { label: 'PR: add the web UI', href: `${GITOPS}/pull/7` },
      { label: 'PR: pin dev', href: `${GITOPS}/pull/8` },
    ],
  },
  {
    title: 'One spec for the whole system', short: 'System spec',
    say: 'Keep tasks in a Postgres database instead of memory, and let people see and create tasks in the web UI',
    run: '/system:spec "…" · /system:spec approve 001', command: 'Keep tasks in a Postgres database instead of memory, and let people see and create tasks in the web UI', at: 158.832, time: '6 min',
    sections: [
      { heading: 'Claude does', text: 'This feature spans three repos, so it takes the system route: one system spec in the gitops repo. The API moves to Postgres, the web UI lists tasks and adds them with a form.' },
      { heading: 'Claude asks, you answer', items: [
        'API instances in dev → two, so the shared storage gets exercised',
        'Who calls the API → the web app\'s server, never the browser',
        'The page texts and the 200-character limit in the form → yes',
        'Tasks held in memory → no migration',
        'Database → dev only for now, backups in a later step',
        'Approve system spec 001 → approve',
      ] },
      { heading: 'Result', text: '10 criteria, approved and merged.' },
    ],
    links: [
      { label: 'the system spec', href: `${GITOPS}/blob/main/docs/specs/001-persistent-tasks-and-web-task-board/spec.md` },
      { label: 'PR: the spec', href: `${GITOPS}/pull/9` },
    ],
  },
  {
    title: 'Plan and ship it to dev', short: 'Ship',
    say: 'Plan it across the repos, merge the plan once its CI is green, and ship it to dev. I\'m away: take the suggested answers for repo-spec questions, and install operators the local cluster needs yourself.',
    run: '/system:plan 001 · /system:ship 001', command: 'Plan it across the repos, merge the plan …, and ship it to dev. …', at: 177.513, time: '43 min',
    sections: [
      { heading: 'Claude does', items: [
        'The planner splits the 10 criteria across the repos and, new in 5.12.0, writes each component repo\'s own criteria into the plan (spec 147): 6 for the API, 7 for the web UI, each naming the system criterion it serves.',
        'Each repo spec is created from the plan and approved at once: no product-manager round and no questions per repo.',
        '<b>API</b> and <b>web</b> build in parallel: a repo plan, failing acceptance tests first, code, review, PR, merge on green CI.',
        '<b>gitops</b>: Postgres, two API instances in dev and the API address for the web UI, landed with both builds in one PR after green checks.',
      ] },
      { heading: 'What went wrong', items: [
        `The waits for the repo builds timed out three times while the builds were still moving; Claude waited again each time (<a href="${ISSUES}/issues/544">#544</a>).`,
      ] },
      { heading: 'Result', text: 'Dev runs both builds against Postgres, shared by two API instances; API smoke 5 of 5, web smoke 1 of 1. No stop; 43 minutes instead of 65 in journey 4, with 13 repo criteria instead of 42.' },
    ],
    links: [
      { label: 'PR: spec and plan', href: `${GITOPS}/pull/10` },
      { label: 'PR: API on Postgres', href: `${API}/pull/4` },
      { label: 'PR: the web task board', href: `${WEB}/pull/3` },
      { label: 'PR: Postgres and wiring', href: `${GITOPS}/pull/11` },
      { label: 'PR: spec done', href: `${GITOPS}/pull/12` },
    ],
  },
  {
    title: 'Hosts, observability and staging', short: 'Staging',
    say: 'Give staging and prod local hosts I can open in the browser, turn on the Grafana observability stack for dev and staging, and promote both components to staging. Merge the PRs once their CI is green.',
    run: '/system:set --host · observability · /instance:promote --to staging --smoke', command: 'Give staging and prod local hosts …, turn on the Grafana observability stack …, and promote both components to staging. …', at: 232.484, time: '11 min',
    sections: [
      { heading: 'Claude does', text: 'A fresh session starts part 3. Claude sets a host for staging and prod, turns on the Grafana stack (logs, metrics, traces) for dev and staging, and promotes the builds dev tested to staging in one PR, which runs the staging smoke itself. Four PRs, each merged on green CI; the new operators arrive through git (5.12.0), nobody runs <code>bootstrap</code>.' },
      { heading: 'Result', text: 'Staging runs both components with its own Postgres; smoke green, Grafana at <code>http://grafana.localhost:8088</code>.' },
    ],
    links: [
      { label: 'PR: staging host', href: `${GITOPS}/pull/13` },
      { label: 'PR: observability', href: `${GITOPS}/pull/15` },
      { label: 'PR: promote to staging', href: `${GITOPS}/pull/16` },
    ],
  },
  {
    title: 'Release', short: 'Release', say: 'Release the API and the web UI from the builds staging tested',
    run: '/component:release (in each repo)', command: 'Release the API and the web UI from the builds staging tested', at: 252.827, time: '7 min',
    sections: [
      { heading: 'Claude does', items: [
        'Runs the quality, test and security gates in both repos, then tags <code>v0.1.0</code> on the commit staging runs: the tag never rebuilds, it gives the tested image its version.',
        'A follow-up PR per repo adds the changelog and moves <code>main</code> to the next development version.',
      ] },
      { heading: 'What went wrong', items: [
        `The web security gate's report named the wrong audit tool, so Claude ran <code>pnpm audit</code> itself, and no image scan ran (<a href="${ISSUES}/issues/545">#545</a>).`,
      ] },
      { heading: 'Result', text: 'Both releases point at exactly the images staging tested; 7 minutes instead of 13.' },
    ],
    links: [
      { label: 'PR: API follow-up', href: `${API}/pull/5` },
      { label: 'PR: web follow-up', href: `${WEB}/pull/4` },
    ],
  },
  {
    title: 'Backups and the prod PR', short: 'Prod PR',
    say: 'Before prod, back up the prod database daily to a bucket. Then open the prod PR for both components, but don\'t merge it.',
    run: '/resource:add backups --type bucket · /instance:promote --all --to prod', command: 'Before prod, back up the prod database daily to a bucket. Then open the prod PR …, but don\'t merge it.', at: 269.323, time: '6 min',
    sections: [
      { heading: 'Claude does', items: [
        'Declares a bucket for backups: a daily backup of the prod database at 03:00 UTC and continuous archiving, kept 30 days.',
        'Opens one prod PR for both components at 0.1.0, with Postgres at three instances.',
      ] },
      { heading: 'The prod check', text: 'The promotion shows its evidence before anything reaches prod: the image digests match what staging tested, dev and staging smoke passed for both components, no open smoke-failure or alert issue, CI green, no warning.' },
    ],
    links: [
      { label: 'PR: backups', href: `${GITOPS}/pull/18` },
      { label: 'PR: both to prod', href: `${GITOPS}/pull/20` },
    ],
  },
  {
    title: 'Prod', short: 'Prod', say: 'The prod check is clean. Merge the prod PR and verify prod, then create a task titled "Prod check" through the prod API.', run: 'merge the prod PR · /instance:verify prod',
    command: 'The prod check is clean. Merge the prod PR and verify prod, then create a task titled "Prod check" through the prod API.', at: 283.249, time: '7 min',
    sections: [
      { heading: 'Claude does', text: 'Merges the prod PR on green CI, waits for Argo, runs the smoke tests against prod and creates the "Prod check" task through the prod API.' },
      { heading: 'Result', text: 'Prod runs both components at 0.1.0; all 4 prod apps Synced and Healthy, smoke green (the API\'s two writing tests run only in dev), and the "Prod check" task is the only task in prod.' },
    ],
    links: [
      { label: 'PR: both to prod', href: `${GITOPS}/pull/20` },
    ],
  },
  {
    title: 'Restore drill', short: 'Restore', say: 'Restore prod to a copy, prove the Prod check task is in it, then discard the copy. I confirm prod for the discard.',
    run: '/resource:restore postgres --env prod --to latest · --discard --confirm prod', command: 'Restore prod to a copy, prove the Prod check task is in it, then discard the copy. …', at: 300.759, time: '14 min',
    sections: [
      { heading: 'Claude does', items: [
        'Restores the prod database from its backups to a separate copy next to the running one; prod keeps serving.',
        'Queries the copy read-only: the "Prod check" task is there, with the id the prod API gave it. Then discards the copy and its volumes with <code>--confirm prod</code>.',
      ] },
      { heading: 'Result', text: 'A checked restore on the first try, without touching prod. <code>--switch</code> would make the copy the active database in a real recovery.' },
    ],
    links: [
      { label: 'PR: restore', href: `${GITOPS}/pull/21` },
      { label: 'PR: discard', href: `${GITOPS}/pull/22` },
    ],
  },
];

/** The three recorded parts: the index of their first step and a heading. */
export const parts: { from: number; title: string; text: string }[] = [
  { from: 0, title: 'Part 1: from an empty folder to an endpoint in dev', text: 'One Python service, one spec in its own repo, a local cluster.' },
  { from: 4, title: 'Part 2: a database and a web UI', text: 'One system spec across three repos: Postgres instead of memory, and a Next.js web UI.' },
  { from: 7, title: 'Part 3: staging, a release, prod and a restore', text: 'Hosts, observability, a release from the tested builds, prod with daily backups, and a restore drill.' },
];

/** The run at a glance (from the recording, the journey record and the demo repos). */
export const glance: { value: string; label: string }[] = [
  { value: '≈ 2 h 45', label: 'of work from an empty folder to a checked restore, CI rounds included' },
  { value: '46 M', label: 'tokens, 40 % fewer than journey 4' },
  { value: '2 min', label: 'of a person\'s time: 20 answers, 5 stops on a platform problem' },
  { value: '28', label: 'real pull requests in the public demo repos' },
  { value: '1 restore', label: 'checked: a copy of prod held the task created there' },
];
